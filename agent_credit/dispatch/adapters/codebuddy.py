from __future__ import annotations

import shutil
import subprocess
import time

from ..base import Preflight, Provider, Result, Task
from ._cli_json import parse_result_json

# 启动即失败但退出码仍为 0 的几类输出（实测 codebuddy 2.184.0）
_FAIL_MARKERS = ("authentication required", "please use /login", "eperm", "enoent")


class CodeBuddyProvider(Provider):
    """腾讯 CodeBuddy Code CLI（codebuddy / cbc），headless 走 -p/--print。

    注意：CLI 会写 ~/.codebuddy/{projects,traces}。在受限沙箱里这步可能
    EPERM/ENOENT，并表现为"退出码 0 + 错误文本"，因此成败要按输出判定，
    不能只看返回码；写盘失败时如实标记失败并让调度器回退，不做任何绕过。
    """

    name = "codebuddy"
    capabilities = {"code", "review", "test-gen", "commit", "explain"}
    supports_balance = False

    @property
    def binary(self) -> str:
        return str(self.config.get("binary") or "codebuddy")

    def preflight(self, task: Task) -> Preflight:
        path = shutil.which(self.binary)
        if not path:
            return Preflight(available=False, reason=f"PATH 中找不到 {self.binary}（npm i -g @tencent-ai/codebuddy-code）")
        return Preflight(available=True, balance_note="CodeBuddy 无余额查询入口，额度按退出码/报错降级判断")

    def read_balance(self) -> tuple[int | None, str]:
        return None, "未实现：CodeBuddy CLI 无余额接口，只能按报错判断是否额度耗尽"

    def dispatch(self, task: Task) -> Result:
        path = shutil.which(self.binary)
        if not path:
            return Result(ok=False, exit_code=127, note=f"找不到 {self.binary}")
        cmd = [
            path,
            "-p",
            # npm 的 .cmd shim 会把参数里的换行当成命令分隔符，多行 prompt 会被
            # 截断（2026-11-15 实测：只收到第一段，然后反问"接下来做什么"）。
            " ".join(task.text.splitlines()),
            "--output-format",
            "json",
            "--permission-mode",
            str(self.config.get("permission_mode") or "acceptEdits"),
        ]
        started = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=task.timeout_s,
                encoding="utf-8", errors="replace",
                cwd=str(task.cwd) if task.cwd else None,
            )
        except subprocess.TimeoutExpired:
            return Result(ok=False, exit_code=124, note=f"超时 {task.timeout_s}s", duration_s=time.time() - started)
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"启动失败: {exc}", duration_s=time.time() - started)

        duration = time.time() - started
        text, error = parse_result_json(proc.stdout)
        lower = f"{text}\n{proc.stderr}".lower()
        if not error and any(m in lower for m in _FAIL_MARKERS):
            error = (proc.stderr or text).strip().splitlines()[0][:200] if (proc.stderr or text).strip() else "启动失败"
            text = ""
        ok = proc.returncode == 0 and bool(text) and not error
        note = ""
        if not ok:
            note = f"exit={proc.returncode}" + (f", {error[:200]}" if error else "")
        return Result(
            ok=ok,
            exit_code=proc.returncode,
            text=text,
            duration_s=duration,
            note=note,
            raw_tail=(proc.stderr or proc.stdout or "")[-400:],
        )
