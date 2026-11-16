from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from ..base import Preflight, Provider, Result, Task

# lobster.cmd 的退出码约定（见 LOBSTERAI-ACCESS.md §8）
_EXIT_NOTES = {
    1: "运行失败（模型报错/超时/JSON 解析失败）",
    2: "路由被拒（模型不属于 lobsterai-server）",
    3: "环境缺失（LobsterAI 未启动或 token 文件缺失）",
    64: "参数错误（缺 -Prompt）",
}

# 其中 3 / 64 与契约表冲突（3 = 疑似额度/限流、64 = 没有可用候选），
# 派单时归一到契约码，lobster.cmd 的原始码留在 note 里；2（路由被拒）按
# "适配器判定失败"记 1。
_CONTRACT_CODES = {2: 1, 3: 126, 64: 1}


class LobsterAIProvider(Provider):
    """LobsterAI 本地网关（lobster.cmd）。

    额度：仓库里还没有同步余额的实现，所以 supports_balance = False，
    调度器会降级为"按退出码 / 429 / 事后账单"判断，而不会排除它。
    等余额同步代码接上后，把 supports_balance 改 True 并实现 read_balance 即可。
    """

    name = "lobsterai"
    capabilities = {"text", "code", "review", "commit"}
    supports_balance = False

    @property
    def binary(self) -> Path:
        raw = self.config.get("binary") or r"C:\Users\M4A1g\lobsterai\project\tools\lobster.cmd"
        return Path(str(raw))

    def _run(self, extra: list[str], timeout: float) -> subprocess.CompletedProcess:
        cmd = ["cmd", "/c", str(self.binary), *extra]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )

    def preflight(self, task: Task) -> Preflight:
        if not self.binary.exists():
            return Preflight(available=False, reason=f"找不到 {self.binary}")
        try:
            proc = self._run(["-Mode", "status"], timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Preflight(available=False, reason=f"status 调用失败: {exc}")
        out = f"{proc.stdout}\n{proc.stderr}"
        if proc.returncode != 0:
            return Preflight(
                available=False,
                reason=f"status 退出码 {proc.returncode}（{_EXIT_NOTES.get(proc.returncode, '未知')}）：{out.strip()[-200:]}",
            )
        if "alive=true" not in out.lower():
            return Preflight(available=False, reason=f"网关未就绪：{out.strip()[-200:]}")
        return Preflight(available=True, balance_note="余额查询未接入，按退出码降级判断")

    def read_balance(self) -> tuple[int | None, str]:
        return None, "未实现：仓库内尚未接入 LobsterAI 余额同步，改用退出码/429/账单判断"

    def dispatch(self, task: Task) -> Result:
        caller = str(self.config.get("caller") or "agent-credit")
        extra = [
            "-Prompt", task.text,
            "-Caller", caller,
            "-TimeoutSeconds", str(task.timeout_s),
            "-Json",
        ]
        started = time.time()
        try:
            proc = self._run(extra, timeout=task.timeout_s + 30)
        except subprocess.TimeoutExpired:
            return Result(ok=False, exit_code=124, note=f"超时 {task.timeout_s}s", duration_s=time.time() - started)
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"启动失败: {exc}", duration_s=time.time() - started)

        duration = time.time() - started
        text = ""
        try:
            data = json.loads(proc.stdout)
            payloads = ((data.get("result") or {}).get("payloads") or [])
            if payloads:
                text = str(payloads[0].get("text") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            text = (proc.stdout or "").strip()

        ok = proc.returncode == 0 and bool(text)
        note = "" if ok else f"exit={proc.returncode}"
        if proc.returncode in _EXIT_NOTES:
            note = f"exit={proc.returncode}（{_EXIT_NOTES[proc.returncode]}）"
        return Result(
            ok=ok,
            exit_code=_CONTRACT_CODES.get(proc.returncode, proc.returncode),
            text=text,
            duration_s=duration,
            note=note,
            raw_tail=(proc.stderr or proc.stdout or "")[-400:],
        )
