from __future__ import annotations

import shutil
import subprocess
import time

from ..base import Preflight, Provider, Result, Task
from ._cli_json import parse_result_json


class QoderProvider(Provider):
    """Qoder CN 官方 CLI（qoderclicn），headless 走 -p/--print。"""

    name = "qoder"
    capabilities = {"code", "review", "test-gen", "commit"}
    supports_balance = False

    @property
    def binary(self) -> str:
        return str(self.config.get("binary") or "qoderclicn")

    def _resolve(self) -> str | None:
        return shutil.which(self.binary)

    def preflight(self, task: Task) -> Preflight:
        path = self._resolve()
        if not path:
            return Preflight(available=False, reason=f"PATH 中找不到 {self.binary}")
        try:
            proc = subprocess.run(
                [path, "status"], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace"
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Preflight(available=False, reason=f"status 调用失败: {exc}")
        out = f"{proc.stdout}\n{proc.stderr}".lower()
        if "not logged in" in out or "未登录" in out or "authentication required" in out:
            return Preflight(available=False, reason="未登录，先在普通终端执行 qoderclicn login")
        return Preflight(available=True, balance_note="CLI 无余额接口，余额需从 Qoder 客户端获取")

    def read_balance(self) -> tuple[int | None, str]:
        return None, "Qoder CLI 不提供余额查询（0.2.0 实测只有 status 登录态）"

    def dispatch(self, task: Task) -> Result:
        path = self._resolve()
        if not path:
            return Result(ok=False, exit_code=127, note=f"找不到 {self.binary}")
        cmd = [
            path,
            "-p",
            task.text,
            "--output-format",
            "json",
            "--permission-mode",
            str(self.config.get("permission_mode") or "accept_edits"),
        ]
        if task.cwd:
            cmd += ["-w", str(task.cwd)]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=task.timeout_s,
                encoding="utf-8", errors="replace", cwd=str(task.cwd) if task.cwd else None,
            )
        except subprocess.TimeoutExpired:
            return Result(ok=False, exit_code=124, note=f"超时 {task.timeout_s}s", duration_s=time.time() - started)
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"启动失败: {exc}", duration_s=time.time() - started)

        duration = time.time() - started
        text, error = parse_result_json(proc.stdout)
        ok = proc.returncode == 0 and bool(text) and not error
        tail = (proc.stderr or proc.stdout or "")[-400:]
        note = ""
        if not ok:
            note = f"exit={proc.returncode}" + (f", {error[:200]}" if error else "")
        return Result(
            ok=ok,
            exit_code=proc.returncode,
            text=text,
            duration_s=duration,
            note=note,
            raw_tail=tail,
        )
