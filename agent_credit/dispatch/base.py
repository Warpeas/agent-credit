from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..paths import ROOT

# 派单主题：一份静态指令，替代"每次在 --task 里手写同样的上下文"。
# 默认读仓库内 instructions/dispatch-theme.md；单个 provider 可用配置
# theme: <相对/绝对路径> 覆盖，theme: off 关闭；环境变量 AGENT_CREDIT_THEME 优先级最高。
DEFAULT_THEME_PATH = ROOT / "instructions" / "dispatch-theme.md"


@dataclass
class Task:
    """一次派单请求。"""

    text: str
    capability: str
    cwd: Path | None = None
    timeout_s: int = 600
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Preflight:
    """派单前自检结果。"""

    available: bool
    reason: str = ""
    balance: int | None = None
    balance_note: str = ""


@dataclass
class Result:
    """一次派单的执行结果。"""

    ok: bool
    exit_code: int
    text: str = ""
    duration_s: float = 0.0
    note: str = ""
    balance_after: int | None = None
    raw_tail: str = ""
    # 结构化用量；None = 适配器没有回传（调度器会按 failed 记）。字段与状态语义见
    # doc/adapter-contract.md §7.2。
    usage: dict[str, Any] | None = None
    # 本次尝试实际走的通道：direct / queue / direct->queue；写进 ledger 便于核对。
    route: str = ""


def usage_failed(error: str) -> dict[str, Any]:
    """构造「没拿到用量」的结构：状态显式为 failed，字段全 null，原因写 error。"""
    return {
        "status": "failed",
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "credits": None,
        "remaining_percent": None,
        "reset_at": None,
        "error": error,
    }


class Provider:
    """适配器基类。子类在 adapters/ 下实现，调度器只依赖这里的接口。"""

    name: str = ""
    capabilities: set[str] = set()
    # 是否能真的查到"剩余额度"。声明为 False 时调度器不会因此排除该提供者，
    # 只会把它标记为 balance_unknown 并在失败时降级。
    supports_balance: bool = False
    # 不消耗任何额度的提供者（如本地模型），余额检查直接放行。
    unbounded: bool = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = dict(config or {})
        caps = self.config.get("capabilities")
        if caps:
            self.capabilities = set(caps)
        self.enabled: bool = bool(self.config.get("enabled", True))
        self.priority: int = int(self.config.get("priority", 100))
        # 允许用配置覆盖"是否支持余额查询"的声明，便于先接上查询再改实现
        if "supports_balance" in self.config:
            self.supports_balance = bool(self.config["supports_balance"])

    def supports_capability(self, capability: str) -> bool:
        return capability in self.capabilities or "any" in self.capabilities

    # ---------- 派单主题 ----------

    @property
    def theme_path(self) -> Path | None:
        raw = os.environ.get("AGENT_CREDIT_THEME") or self.config.get("theme")
        if raw is None:
            return DEFAULT_THEME_PATH
        text = str(raw).strip()
        if not text or text.lower() in ("off", "none", "false", "0"):
            return None
        path = Path(text)
        return path if path.is_absolute() else ROOT / path

    def theme_text(self) -> str:
        """读主题全文；文件缺失/为空时返回空串（不报错，派单照常进行）。"""
        path = self.theme_path
        if path is None:
            return ""
        try:
            # utf-8-sig：主题文件可能被 Windows 编辑器存成带 BOM
            return path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return ""

    def theme_oneliner(self) -> str:
        """给只收单行参数的 CLI 用：折叠换行。

        codebuddy/qoder 的可执行文件是 npm 的 .cmd/.ps1 shim，参数里带换行会被
        截断（2026-11-15 实测 codebuddy 只收到第一段），所以这两家必须走单行。
        """
        return " ".join(self.theme_text().split())

    def preflight(self, task: Task) -> Preflight:
        """检查是否可调用：二进制在不在、登录态、服务是否在跑。"""
        return Preflight(available=True)

    def read_balance(self) -> tuple[int | None, str]:
        """返回 (剩余额度, 说明)。查不到返回 (None, 原因)，不要靠猜。"""
        return None, "适配器未声明余额查询能力"

    def dispatch(self, task: Task) -> Result:
        raise NotImplementedError
