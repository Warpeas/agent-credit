from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

    def preflight(self, task: Task) -> Preflight:
        """检查是否可调用：二进制在不在、登录态、服务是否在跑。"""
        return Preflight(available=True)

    def read_balance(self) -> tuple[int | None, str]:
        """返回 (剩余额度, 说明)。查不到返回 (None, 原因)，不要靠猜。"""
        return None, "适配器未声明余额查询能力"

    def dispatch(self, task: Task) -> Result:
        raise NotImplementedError
