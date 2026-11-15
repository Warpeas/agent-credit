"""DuMate 百度搭子适配器。

DuMate 桌面端不带可直接调用的命令行，但自带一套 opencode 运行时：

    resources/extra-resource/opencode/bin/dumate-opencode.exe

桌面端平时用 `serve` 把它拉起来，再由 UI 通过本地 HTTP 创建会话。这里走同一条
非交互链路：临时起一个只监听 127.0.0.1 的运行时，创建会话、提交任务、取回正文，
结束后杀掉进程树。模型请求仍由 DuMate 自己的本地网关（QianfanPersonalQuota）
发出，因此真实消耗账号额度；适配器不读、不复制、不改写任何凭据。

余额：DuMate 没有公开的余额查询入口，`supports_balance = False`，由调度器按
balance_unknown 正常降级，不因此排除该提供者。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..base import Preflight, Provider, Result, Task

# 这些环境变量是桌面端注入给自家运行时的：从普通 shell 里继承过来会让临时服务
# 进入"必须带 X-Dumate-Inapp-Key"的模式，而我们不该去读那把钥匙。
_SCRUB_ENV = (
    "DUMATE_INAPP_KEY",
    "DUMATE_HOST_URL",
    "DUMATE_BACK_END_PORT",
    "OPENCODE_SERVER_PASSWORD",
    "OPENCODE_SERVER_USERNAME",
)

_QUOTA_MARKERS = (
    "429",
    "rate limit",
    "ratelimit",
    "quota",
    "insufficient",
    "额度",
    "限流",
    "余额不足",
)


class DumateProvider(Provider):
    """DuMate 百度搭子：经自带 opencode 运行时派单，消耗个人额度。"""

    name = "dumate"
    capabilities = {"text", "code", "review", "test-gen", "commit", "explain"}
    supports_balance = False

    # ---------- 路径发现 ----------

    @property
    def binary(self) -> str:
        configured = str(self.config.get("binary") or "").strip()
        if configured:
            return configured
        env = os.environ.get("DUMATE_OPENCODE_BIN")
        if env:
            return env
        for base in (
            os.environ.get("LOCALAPPDATA"),
            str(Path.home() / "AppData" / "Local"),
        ):
            if not base:
                continue
            candidate = Path(base) / "Programs" / "DuMate" / "resources" / "extra-resource" / "opencode" / "bin" / "dumate-opencode.exe"
            if candidate.is_file():
                return str(candidate)
        return "dumate-opencode"

    def _resolve_binary(self) -> str | None:
        raw = self.binary
        path = Path(raw)
        if path.is_file():
            return str(path)
        return shutil.which(raw)

    def _resolve_config_root(self) -> Path | None:
        configured = str(self.config.get("config_dir") or "").strip()
        candidates: list[Path] = []
        if configured:
            root = Path(configured)
            if root.is_file():
                candidates.append(root.parent.parent)
            else:
                candidates.append(root)
                candidates.append(root / "opencode")
        env = os.environ.get("DUMATE_OPENCODE_CONFIG")
        if env:
            candidates.append(Path(env))

        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "qianfan-desktop-app" / "qianfan_desk_xdg"
            # 多个登录账号时取最近用过的那份配置，只看修改时间，不读内容。
            found = sorted(
                base.glob("*/config"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            candidates.extend(found)
        candidates.append(Path.home() / ".config")

        for root in candidates:
            if (root / "opencode" / "opencode.json").is_file():
                return root
            if (root / "opencode.json").is_file():  # 直接传了 opencode 子目录
                return root.parent
        return None

    # ---------- 契约 ----------

    def preflight(self, task: Task) -> Preflight:
        binary = self._resolve_binary()
        if not binary:
            return Preflight(
                available=False,
                reason=(
                    "找不到 dumate-opencode（DuMate 自带运行时）；"
                    "请安装/打开 DuMate，或在 providers.yaml 配 binary"
                ),
            )
        root = self._resolve_config_root()
        if root is None:
            return Preflight(
                available=False,
                reason=(
                    "找不到 DuMate 的 opencode 配置（%APPDATA%\\qianfan-desktop-app\\"
                    "qianfan_desk_xdg\\*\\config\\opencode\\opencode.json）；"
                    "请先打开并登录 DuMate，或用 config_dir 指定"
                ),
            )
        return Preflight(
            available=True,
            balance_note="额度经 DuMate 本地网关消耗；无公开余额接口，按 balance_unknown 处理",
        )

    def read_balance(self) -> tuple[int | None, str]:
        return None, "DuMate 未提供公开的余额查询接口，不猜余额"

    def dispatch(self, task: Task) -> Result:
        started = time.time()
        deadline = started + max(1, int(task.timeout_s))
        binary = self._resolve_binary()
        if not binary:
            return Result(ok=False, exit_code=127, note=f"找不到 {self.binary}")

        root = self._resolve_config_root()
        if root is None:
            return Result(ok=False, exit_code=126, note="找不到 DuMate opencode 配置")

        port = self._free_port()
        workdir = Path(task.cwd).resolve() if task.cwd else Path.cwd()
        sandbox = Path(tempfile.mkdtemp(prefix="agent-credit-dumate-"))
        log_path = sandbox / "runtime.log"
        env = self._runtime_env(root, sandbox)
        proc: subprocess.Popen[bytes] | None = None

        try:
            log = open(log_path, "wb")
            try:
                proc = subprocess.Popen(
                    [binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    # 运行时自己的相对路径日志落在临时目录，别污染任务工作区；
                    # 任务实际目录由 x-opencode-directory 头指定。
                    cwd=str(sandbox),
                    creationflags=self._creation_flags(),
                )
            finally:
                log.close()

            startup_deadline = min(deadline, started + int(self.config.get("startup_timeout_s") or 45))
            if not self._wait_ready(port, proc, startup_deadline):
                return Result(
                    ok=False,
                    exit_code=126,
                    duration_s=time.time() - started,
                    note="DuMate 运行时启动失败或超时",
                    raw_tail=self._tail(log_path),
                )

            base = f"http://127.0.0.1:{port}"
            header_dir = workdir.as_posix()
            status, body = self._request(
                base,
                "POST",
                "/session",
                {"title": f"agent-credit: {task.capability}"},
                header_dir,
                self._remaining(deadline),
            )
            if status != 200:
                return self._http_failure(status, body, started, log_path)

            session_id = str((self._json(body) or {}).get("id") or "")
            if not session_id:
                return Result(
                    ok=False,
                    exit_code=1,
                    duration_s=time.time() - started,
                    note="运行时没有返回 session id",
                    raw_tail=body[-400:].decode("utf-8", "replace"),
                )

            status, body = self._request(
                base,
                "POST",
                f"/session/{session_id}/message",
                {"parts": [{"type": "text", "text": task.text}]},
                header_dir,
                self._remaining(deadline),
            )
            if status != 200:
                return self._http_failure(status, body, started, log_path)

            return self._result(body, started, log_path)
        except (socket.timeout, TimeoutError):
            return Result(
                ok=False,
                exit_code=124,
                duration_s=time.time() - started,
                note=f"超时 {task.timeout_s}s",
                raw_tail=self._tail(log_path),
            )
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            code = 124 if "timed out" in reason.lower() else 126
            return Result(
                ok=False,
                exit_code=code,
                duration_s=time.time() - started,
                note=f"本地运行时请求失败: {reason[:200]}",
                raw_tail=self._tail(log_path),
            )
        except OSError as exc:
            return Result(
                ok=False,
                exit_code=126,
                duration_s=time.time() - started,
                note=f"启动失败: {exc}",
                raw_tail=self._tail(log_path),
            )
        finally:
            if proc is not None:
                self._stop(proc)
            shutil.rmtree(sandbox, ignore_errors=True)

    # ---------- 运行时 ----------

    def _runtime_env(self, root: Path, sandbox: Path) -> dict[str, str]:
        env = os.environ.copy()
        for key in _SCRUB_ENV:
            env.pop(key, None)
        env["XDG_CONFIG_HOME"] = str(root)
        env["XDG_DATA_HOME"] = str(sandbox / "data")
        env["XDG_CACHE_HOME"] = str(sandbox / "cache")
        env["XDG_STATE_HOME"] = str(sandbox / "state")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    @staticmethod
    def _creation_flags() -> int:
        if os.name == "nt":
            return getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return 0

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_ready(self, port: int, proc: subprocess.Popen[bytes], deadline: float) -> bool:
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    pass
                status, _ = self._request(
                    f"http://127.0.0.1:{port}",
                    "GET",
                    "/health",
                    None,
                    "",
                    max(1.0, deadline - time.time()),
                )
                if status == 200:
                    return True
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.2)
        return False

    @staticmethod
    def _stop(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def _request(
        base: str,
        method: str,
        path: str,
        payload: Any,
        directory: str,
        timeout: float,
    ) -> tuple[int, bytes]:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if directory:
            headers["x-opencode-directory"] = directory
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(1.0, deadline - time.time())

    # ---------- 结果解析 ----------

    @staticmethod
    def _json(body: bytes) -> dict[str, Any] | None:
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _http_failure(self, status: int, body: bytes, started: float, log_path: Path) -> Result:
        text = body.decode("utf-8", "replace")
        quota = any(marker in text.lower() for marker in _QUOTA_MARKERS)
        code = 3 if quota else (126 if status in (401, 403) else 1)
        note = f"运行时 HTTP {status}" + (", 疑似额度/限流" if quota else "")
        parsed = self._json(body) or {}
        for key in ("msg", "error", "message"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                note += f": {value.strip()[:160]}"
                break
        return Result(
            ok=False,
            exit_code=code,
            duration_s=time.time() - started,
            note=note,
            raw_tail=(text[-400:] or self._tail(log_path)),
        )

    def _result(self, body: bytes, started: float, log_path: Path) -> Result:
        data = self._json(body)
        if data is None:
            return Result(
                ok=False,
                exit_code=1,
                duration_s=time.time() - started,
                note="运行时返回了非 JSON 正文",
                raw_tail=body[-400:].decode("utf-8", "replace"),
            )

        info = data.get("info") or {}
        parts = data.get("parts") or []
        texts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n".join(item.strip() for item in texts if isinstance(item, str) and item.strip())
        error = info.get("error")
        tokens = info.get("tokens") or {}
        model = "/".join(
            str(info.get(key) or "").strip("/")
            for key in ("providerID", "modelID")
            if info.get(key)
        ) or "unknown"
        note = f"{model}, {tokens.get('total', 0)} tok"
        if info.get("finish") and info.get("finish") != "stop":
            note += f", finish={info.get('finish')}"

        ok = bool(text) and not error
        if error:
            note += f", error={str(error)[:160]}"
        elif not text:
            note += ", 运行结束但没有正文"
        return Result(
            ok=ok,
            exit_code=0 if ok else 1,
            text=text,
            duration_s=time.time() - started,
            note=note,
            raw_tail="" if ok else body[-400:].decode("utf-8", "replace"),
        )

    @staticmethod
    def _tail(path: Path) -> str:
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # Windows 原生程序（cmd/PowerShell）的失败输出多是 GBK，别让几个
            # 非法字节把整段排障线索变成乱码。
            text = data.decode("gb18030", errors="replace")
        return text[-400:]