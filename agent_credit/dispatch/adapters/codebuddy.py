from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from ...paths import DATA_DIR
from ..base import Preflight, Provider, Result, Task, usage_failed
from ._cli_json import format_usage_summary, parse_result_json, parse_usage_detail

# 启动即失败的特征（2026-11-15 实测 codebuddy 2.184.0，判定依据见
# doc/adapter-contract.md §10.3）。codebuddy 启动时要写
# ~/.codebuddy/projects/<cwd-slug>/*.jsonl 和 traces/；沙箱或 ACL 不允许写时，
# 它 2~3 秒就退出，**退出码仍然是 0**，错误可能落在 stderr，也可能塞进 JSON
# 的 is_error / errors 里。只看返回码会把它当成功，回退链就停在这里空转。
_STARTUP_FAIL_MARKERS = (
    "enoent",
    "eperm",
    "eacces",
    "authentication required",
    "please use /login",
)

# 沙箱类拒绝的固定口径：note 与错误里都要出现这句话，别让读者再去猜是权限还是环境。
SANDBOX_NOTE = "调用环境受限，需在非沙箱环境执行"


def _is_sandbox_denial(raw: str) -> bool:
    """EPERM/EACCES/ENOENT 且目标路径落在当前用户家目录下 → 判定为调用方沙箱。

    2026-11-15 实测：同一台机器上，用户在普通终端跑写入探针六条全 OK，
    但本进程（及其子进程）写 %USERPROFILE% 根与 ~/.codebuddy 全被拒，
    写工作区与 %TEMP% 正常。目录与 ACL 都已排除，问题只在调用方环境。
    """
    lowered = (raw or "").lower().replace("/", "\\")
    if not any(marker in lowered for marker in ("eperm", "eacces", "enoent")):
        return False
    home = str(Path.home()).lower().replace("/", "\\").rstrip("\\")
    return bool(home) and home in lowered


def _first_line(raw: str) -> str:
    """取第一行非空文本，用于把错误摘要塞进 note。"""
    for line in (raw or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


class CodeBuddyProvider(Provider):
    """腾讯 CodeBuddy Code CLI（codebuddy / cbc），headless 走 -p/--print。

    直连时把 `CODEBUDDY_CONFIG_DIR` 注入子进程，指向固定的可写目录
    （默认 data/codebuddy-home）。这样 CLI 的 traces/projects/sessions/logs
    不再写 %USERPROFILE%\\.codebuddy；2026-11-15 实测空目录即可正常调用模型
    和读写工具，用户级 settings/skills/MCP 不是派单必需项。

    transport=auto（默认）：先直连；直连因写盘/启动失败（归一化 126/127）时
    自动回落到队列，账本 `route` 记 direct / queue / direct->queue。
    transport=direct：只直连；transport=queue：只队列。

    快速失败判定（命中任一即 ok=False，调度器回退到下一个候选）：
      1. 退出码非 0；
      2. JSON is_error=true / subtype=error*；
      3. 退出码 0，但 stderr 或解析出的错误命中 _STARTUP_FAIL_MARKERS；
      4. 退出码 0 但没有正文。
    1/2/3 的 exit_code 归一到 126（启动失败），4 归一到 1；原始码写进 note。

    沙箱冷却：3 命中且错误路径落在当前用户家目录下时，判定为"调用环境受限"，
    写 data/codebuddy_health.json 记下 blocked_until（默认 300s，配置
    sandbox_block_ttl_s 可调）与当时的数据目录。冷却期内 auto 直接走队列，
    不再起注定失败的进程；冷却只对同一个 config_dir 生效，换了数据目录即作废。
    """

    name = "codebuddy"
    capabilities = {"code", "review", "test-gen", "commit", "explain"}
    supports_balance = False

    @property
    def binary(self) -> str:
        return str(self.config.get("binary") or "codebuddy")

    @property
    def config_dir(self) -> Path:
        raw = self.config.get("config_dir")
        return Path(str(raw)) if raw else DATA_DIR / "codebuddy-home"

    @property
    def settings_arg(self) -> str | None:
        """可选的 --settings 值（文件路径或 JSON 串）。

        实测派单不需要用户 settings：空 config_dir + bypassPermissions 下，
        读文件和写文件都成功且 permission_denials 为空。留这个口子只是给
        确实依赖 settings（代理/环境变量等）的机器用。
        """
        raw = self.config.get("settings")
        return str(raw) if raw else None

    @property
    def queue_fallback_enabled(self) -> bool:
        return bool(self.config.get("queue_fallback", True))

    @property
    def health_path(self) -> Path:
        return DATA_DIR / "codebuddy_health.json"

    @property
    def sandbox_block_ttl_s(self) -> float:
        return float(self.config.get("sandbox_block_ttl_s") or 300)

    def _read_health(self) -> dict:
        try:
            return json.loads(self.health_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _blocked_until(self) -> float:
        data = self._read_health()
        # 冷却记录绑定数据目录：换成可写的固定目录后，旧的家目录失败不应再挡路。
        if str(data.get("config_dir") or "") != str(self.config_dir):
            return 0.0
        try:
            return float(data.get("sandbox_blocked_until") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _cooldown_left(self) -> tuple[int, str]:
        until = self._blocked_until()
        left = int(until - time.time())
        if left <= 0:
            return 0, ""
        return left, str(self._read_health().get("reason") or "写家目录被拒")

    def _mark_sandbox_blocked(self, reason: str) -> None:
        until = time.time() + self.sandbox_block_ttl_s
        payload = {
            "sandbox_blocked_until": until,
            "blocked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "reason": (reason or "")[:200],
            "config_dir": str(self.config_dir),
        }
        try:
            self.health_path.parent.mkdir(parents=True, exist_ok=True)
            self.health_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass  # 记不下冷却状态不影响本次失败结论，只是下次还会再试一次

    def _clear_sandbox_block(self) -> None:
        try:
            self.health_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ---------- 直连通道 ----------

    def _resolve_binary(self) -> str | None:
        """解析完整路径。裸写 codebuddy 在 Python 子进程里会 WinError 2。"""
        return shutil.which(self.binary)

    def _ensure_config_dir(self) -> str | None:
        """确保固定数据目录存在且真的可写；返回错误说明，None 表示可用。"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            probe = self.config_dir / ".agent-credit-write-probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            return f"数据目录不可写 {self.config_dir}: {exc}"
        return None

    def _direct_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["CODEBUDDY_CONFIG_DIR"] = str(self.config_dir)
        return env

    def _preflight_direct(self) -> Preflight:
        path = self._resolve_binary()
        if not path:
            return Preflight(
                available=False,
                reason=f"PATH 中找不到 {self.binary}（npm i -g @tencent-ai/codebuddy-code）",
            )
        problem = self._ensure_config_dir()
        if problem:
            return Preflight(available=False, reason=problem)
        return Preflight(
            available=True,
            balance_note=f"直连 {path}；数据目录 {self.config_dir}",
        )

    # ---------- 队列通道（transport=queue） ----------
    #
    # 前台进程若在沙箱里，直接起 codebuddy 必然写家目录失败。queue 通道把任务
    # 落到 data/codebuddy-taskbox/pending，由计划任务在当前用户会话（非沙箱）
    # 里拉起 scripts/codebuddy-worker.py 执行，结果写回 results。
    # 协议见 doc/ledger-lock-and-scheduled-dispatch.md。

    @property
    def transport(self) -> str:
        raw = str(self.config.get("transport") or "auto").strip().lower()
        return raw if raw in ("auto", "direct", "queue") else "auto"

    @property
    def queue_box(self) -> Path:
        raw = self.config.get("queue_dir")
        return Path(str(raw)) if raw else DATA_DIR / "codebuddy-taskbox"

    @property
    def task_name(self) -> str:
        return str(self.config.get("task_name") or "agent-credit-codebuddy")

    @property
    def poll_interval_s(self) -> float:
        return float(self.config.get("poll_interval_s") or 2)

    @property
    def retrigger_s(self) -> float:
        """等待期间多久补一次触发：上一次实例还在跑时 IgnoreNew 会丢掉 /Run，
        补触发让排在后面的任务在前一个结束后立刻被拉起。"""
        return float(self.config.get("retrigger_s") or 10)

    def _ensure_queue_dirs(self) -> Path:
        self.queue_box.mkdir(parents=True, exist_ok=True)
        for sub in ("pending", "running", "results"):
            (self.queue_box / sub).mkdir(exist_ok=True)
        return self.queue_box

    def _atomic_json(self, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _task_registered(self) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["schtasks", "/Query", "/TN", self.task_name],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"无法查询计划任务（{exc}）"
        if proc.returncode == 0:
            return True, ""
        return False, (proc.stdout or proc.stderr or "").strip()[:200]

    def _trigger(self) -> bool:
        try:
            proc = subprocess.run(
                ["schtasks", "/Run", "/TN", self.task_name],
                capture_output=True, text=True, timeout=20,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def _preflight_queue(self) -> Preflight:
        try:
            box = self._ensure_queue_dirs()
        except OSError as exc:
            return Preflight(available=False, reason=f"队列目录不可写: {exc}")
        ok, detail = self._task_registered()
        if not ok:
            return Preflight(
                available=False,
                reason=(
                    f"计划任务 {self.task_name} 未注册或查询失败（{detail}）；"
                    "在普通 PowerShell 里执行 scripts/register-codebuddy-task.ps1，"
                    "见 doc/ledger-lock-and-scheduled-dispatch.md"
                ),
            )
        return Preflight(
            available=True,
            balance_note=f"队列通道 {box}；任务 {self.task_name}（InteractiveToken，IgnoreNew）",
        )

    def _dispatch_queue(self, task: Task) -> Result:
        started = time.time()
        try:
            box = self._ensure_queue_dirs()
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"队列目录不可写: {exc}",
                          duration_s=time.time() - started,
                          usage=usage_failed(f"未执行：队列目录不可写（{exc}）"))

        task_id = hashlib.sha1(f"{task.text}|{uuid.uuid4()}".encode("utf-8")).hexdigest()[:12]
        payload = {
            "id": task_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "capability": task.capability,
            "text": task.text,
            "cwd": str(task.cwd) if task.cwd else None,
            "timeout_s": task.timeout_s,
            "binary": self._resolve_binary() or self.binary,
            "permission_mode": str(self.config.get("permission_mode") or "bypassPermissions"),
            # 主题随 payload 走，worker 侧同样用 --append-system-prompt 注入
            "append_system_prompt": self.theme_text(),
        }
        pending_file = box / "pending" / f"{task_id}.json"
        result_file = box / "results" / f"{task_id}.json"
        try:
            self._atomic_json(pending_file, payload)
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"投递队列失败: {exc}",
                          duration_s=time.time() - started,
                          usage=usage_failed(f"未执行：投递队列失败（{exc}）"))
        if not self._trigger():
            try:
                pending_file.unlink(missing_ok=True)
            except OSError:
                pass
            return Result(
                ok=False, exit_code=126,
                note=f"计划任务 {self.task_name} 拉不起来（schtasks /Run 失败）；"
                     "任务未投递，检查任务是否已注册",
                duration_s=time.time() - started,
                usage=usage_failed("未执行：计划任务拉不起来"),
            )

        deadline = started + task.timeout_s
        last_trigger = started
        while time.time() < deadline:
            if result_file.exists():
                try:
                    data = json.loads(result_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    time.sleep(self.poll_interval_s)
                    continue
                try:
                    result_file.unlink(missing_ok=True)
                except OSError:
                    pass  # 读到了就算数，删不掉留给 worker 的 24h 清理
                text = str(data.get("text") or "").strip()
                ok = bool(data.get("ok")) and bool(text)  # 契约：ok 只在真有正文时为 True
                exit_code = int(data.get("exit_code") or (0 if ok else 1))
                note = f"taskbox {task_id}" + (
                    f", worker {data.get('elapsed_s')}s" if data.get("elapsed_s") else "")
                worker_note = str(data.get("note") or "")
                if worker_note:
                    note += f"; {worker_note}"
                usage = data.get("usage")
                if not isinstance(usage, dict):
                    usage = usage_failed("worker 结果缺少 usage 字段（worker 版本过旧或未解析）")
                summary = format_usage_summary(usage)
                if summary:
                    note += f"; {summary}"
                return Result(
                    ok=ok,
                    exit_code=0 if ok else exit_code,
                    text=text,
                    duration_s=time.time() - started,
                    note=note,
                    raw_tail=str(data.get("raw_tail") or "")[:400],
                    usage=usage,
                )
            if time.time() - last_trigger >= self.retrigger_s:
                self._trigger()
                last_trigger = time.time()
            time.sleep(self.poll_interval_s)

        waited = time.time() - started
        try:
            if pending_file.exists():
                pending_file.unlink(missing_ok=True)
                stuck = "已撤单（worker 未认领）"
            elif (box / "running" / f"{task_id}.json").exists():
                stuck = "已被 worker 认领、仍在执行，结果将留在队列不被读取"
            else:
                stuck = "状态不明（既不在 pending 也不在 running）"
        except OSError as exc:
            stuck = f"撤单时出错: {exc}"
        return Result(
            ok=False, exit_code=124,
            note=f"taskbox 超时 {task.timeout_s}s：{stuck}",
            duration_s=waited,
            raw_tail=task.text[:200],
            usage=usage_failed(f"超时未取得用量：{stuck}"),
        )

    def preflight(self, task: Task) -> Preflight:
        mode = self.transport
        if mode == "queue":
            return self._preflight_queue()
        direct = self._preflight_direct()
        if mode == "direct":
            if not direct.available:
                return direct
            left, last = self._cooldown_left()
            if left > 0:
                return Preflight(
                    available=False,
                    reason=(
                        f"{SANDBOX_NOTE}；上次失败: {last or '写家目录被拒'}。"
                        f"{left}s 内跳过（冷却状态 data/codebuddy_health.json）"
                    ),
                )
            return direct
        # auto：直连能起来就优先直连；不能起来则只要队列可用就放行，本次走队列。
        queue = self._preflight_queue()
        if direct.available:
            note = direct.balance_note
            note += ("；队列兜底就绪" if queue.available
                     else f"；队列兜底不可用（{queue.reason[:120]}）")
            return Preflight(available=True, balance_note=note)
        if queue.available:
            return Preflight(
                available=True,
                balance_note=f"直连不可用（{direct.reason}）；本次走队列 {self.queue_box}",
            )
        return Preflight(
            available=False,
            reason=f"直连不可用（{direct.reason}）；队列兜底也不可用（{queue.reason}）",
        )

    def read_balance(self) -> tuple[int | None, str]:
        return None, "未实现：CodeBuddy CLI 无余额接口，只能按报错判断是否额度耗尽"

    @staticmethod
    def _should_fallback(result: Result) -> bool:
        """直连失败后是否值得再投队列。

        124 超时不能重放（进程可能还在执行，重投会重复干活）；126/127 是启动/
        写盘/找不到可执行文件，属于环境问题，换到用户会话的队列里有意义。
        """
        if result.ok:
            return False
        if result.exit_code == 124:
            return False
        if SANDBOX_NOTE in (result.note or ""):
            return True
        return result.exit_code in (126, 127)

    def _queue_result(self, task: Task, prefix: str = "", route: str = "queue") -> Result:
        result = self._dispatch_queue(task)
        result.route = route
        if prefix:
            result.note = (prefix + ("; " + result.note if result.note else ""))[:400]
        return result

    def _dispatch_auto(self, task: Task) -> Result:
        direct = self._preflight_direct()
        if not direct.available:
            return self._queue_result(
                task, f"直连不可用（{direct.reason}），走队列", route="direct->queue")

        left, last = self._cooldown_left()
        if left > 0 and self._preflight_queue().available:
            return self._queue_result(
                task, f"直连冷却 {left}s（{last}），走队列", route="direct->queue")

        result = self._dispatch_direct(task)
        result.route = "direct"
        if not self.queue_fallback_enabled or not self._should_fallback(result):
            return result

        queue = self._preflight_queue()
        if not queue.available:
            result.note = (result.note + f"；队列兜底不可用: {queue.reason}")[:400]
            return result

        fallback = self._dispatch_queue(task)
        fallback.route = "direct->queue"
        prefix = f"直连失败(exit={result.exit_code})，已回落队列: {result.note[:180]}"
        fallback.note = (prefix + ("; " + fallback.note if fallback.note else ""))[:400]
        return fallback

    def dispatch(self, task: Task) -> Result:
        mode = self.transport
        if mode == "queue":
            return self._queue_result(task)
        if mode == "direct":
            result = self._dispatch_direct(task)
            result.route = "direct"
            return result
        return self._dispatch_auto(task)

    def _dispatch_direct(self, task: Task) -> Result:
        path = self._resolve_binary()
        if not path:
            return Result(ok=False, exit_code=127, note=f"找不到 {self.binary}",
                          usage=usage_failed(f"未执行：PATH 中找不到 {self.binary}"))
        problem = self._ensure_config_dir()
        if problem:
            return Result(ok=False, exit_code=126, note=problem,
                          usage=usage_failed(f"未执行：{problem}"))
        cmd = [
            path,
            "-p",
            # npm 的 .cmd shim 会把参数里的换行当成命令分隔符，多行 prompt 会被
            # 截断（2026-11-15 实测：只收到第一段，然后反问"接下来做什么"）。
            " ".join(task.text.splitlines()),
            "--output-format",
            "json",
            "--permission-mode",
            # headless 必须 bypassPermissions：acceptEdits 下它连 Bash/pytest 都要
            # 授权，没人点就只回一句"需要授权/接下来做什么"并 exit 0（2026-11-15 实测）。
            str(self.config.get("permission_mode") or "bypassPermissions"),
        ]
        if self.settings_arg:
            cmd += ["--settings", self.settings_arg]
        # 派单主题：走 CLI 原生的 --append-system-prompt，不覆盖它自己的系统提示。
        # 必须单行（.cmd shim 会把参数里的换行当命令分隔符）。
        theme = self.theme_oneliner()
        if theme:
            cmd += ["--append-system-prompt", theme]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=task.timeout_s,
                encoding="utf-8", errors="replace",
                cwd=str(task.cwd) if task.cwd else None,
                env=self._direct_env(),
            )
        except subprocess.TimeoutExpired:
            return Result(ok=False, exit_code=124, note=f"超时 {task.timeout_s}s", duration_s=time.time() - started,
                          usage=usage_failed(f"超时 {task.timeout_s}s，未取得用量"))
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"启动失败: {exc}", duration_s=time.time() - started,
                          usage=usage_failed(f"未执行：启动失败（{exc}）"))

        duration = time.time() - started
        text, error = parse_result_json(proc.stdout)
        # 只扫 stderr 和解析出的错误，不扫正文：任务本身要是"解释这个 ENOENT
        # 报错"，正文里出现这些词不该被判成启动失败。
        haystack = f"{proc.stderr}\n{error}".lower()
        startup_fail = any(marker in haystack for marker in _STARTUP_FAIL_MARKERS)
        sandbox_denied = startup_fail and _is_sandbox_denial(f"{proc.stderr}\n{error}")
        if startup_fail:
            if not error:
                error = _first_line(proc.stderr or text) or "启动期写入失败（ENOENT/EPERM）"
            if sandbox_denied:
                # 目录/ACL 已在普通终端验证正常，这里只可能是调用方进程的环境限制。
                detail = error
                error = f"{SANDBOX_NOTE}: {detail}"
                self._mark_sandbox_blocked(detail)
            text = ""  # 错误文本绝不能当正文返回
        elif not error and not text.strip():
            error = "无正文"
        ok = proc.returncode == 0 and bool(text) and not error
        if ok:
            self._clear_sandbox_block()

        if ok:
            exit_code = 0
        elif proc.returncode != 0:
            exit_code = proc.returncode  # 退出码非 0 时透传 CLI 原始码
        elif startup_fail:
            exit_code = 126
        else:
            exit_code = 1

        # 结构化用量：token 取 result.usage，credit/quota/模型取 assistant 的 rawUsage。
        # 解析失败也返回 status=failed 的字典，不留空。
        usage = parse_usage_detail(proc.stdout)
        usage_summary = format_usage_summary(usage)
        note_parts: list[str] = []
        if not ok:
            code = f"exit={proc.returncode}" if proc.returncode != 0 else f"exit=0->{exit_code}"
            note_parts.append(code + (f", {error[:200]}" if error else ""))
        if usage_summary:
            note_parts.append(usage_summary)
        note = "; ".join(note_parts)
        return Result(
            ok=ok,
            exit_code=exit_code,
            text=text,
            duration_s=duration,
            note=note,
            raw_tail=(proc.stderr or proc.stdout or "")[-400:],
            usage=usage,
        )
