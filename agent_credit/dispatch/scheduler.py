from __future__ import annotations

from dataclasses import dataclass, field

from .base import Provider, Result, Task, usage_failed
from .registry import build


@dataclass
class Attempt:
    provider: str
    ok: bool
    exit_code: int
    duration_s: float
    note: str = ""
    balance_before: int | None = None
    balance_unknown: bool = False
    usage: dict = field(default_factory=dict)
    route: str = ""


@dataclass
class Outcome:
    ok: bool
    provider: str = ""
    text: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    fallback: bool = False
    balance_unknown: bool = False
    exit_code: int = 1

    @property
    def plan(self) -> list[str]:
        return [a.provider for a in self.attempts]


def candidates(task: Task, forced: str | None = None) -> list[Provider]:
    providers = [p for p in build() if p.enabled and p.supports_capability(task.capability)]
    if forced:
        providers = [p for p in providers if p.name == forced]
    return providers


def run(
    task: Task,
    *,
    forced: str | None = None,
    allow_fallback: bool = True,
) -> Outcome:
    """单机串行派单：按配置顺序预检 → 执行 → 失败回退到下一个。

    余额规则：
    - unbounded（本地模型）直接放行；
    - 声明 supports_balance 且能读到值：<=0 跳过；
    - 读不到（None）：不排除，标记 balance_unknown，失败时照常回退。
    """
    providers = candidates(task, forced)
    outcome = Outcome(ok=False, exit_code=1)
    if not providers:
        outcome.attempts.append(
            Attempt(provider="-", ok=False, exit_code=64, duration_s=0.0,
                    note=f"没有启用的提供者支持能力 {task.capability}" + (f"（指定了 {forced}）" if forced else ""),
                    usage=usage_failed("未执行：没有启用的提供者支持该能力"))
        )
        outcome.exit_code = 64  # 契约：64 = 没有可用候选，由调度器产出
        return outcome

    for index, provider in enumerate(providers):
        pre = provider.preflight(task)
        if not pre.available:
            outcome.attempts.append(
                Attempt(provider=provider.name, ok=False, exit_code=69, duration_s=0.0,
                        note=f"预检失败: {pre.reason}",
                        usage=usage_failed(f"未执行：预检失败（{pre.reason}）"))
            )
            continue

        balance_before: int | None = None
        balance_unknown = False
        if provider.unbounded:
            balance_before = None
        elif provider.supports_balance:
            balance_before, note = provider.read_balance()
            if balance_before is not None and balance_before <= 0:
                outcome.attempts.append(
                    Attempt(provider=provider.name, ok=False, exit_code=75, duration_s=0.0,
                            note=f"余额不足: {note}", balance_before=balance_before,
                            usage=usage_failed("未执行：余额不足被跳过"))
                )
                continue
            if balance_before is None:
                balance_unknown = True
        else:
            balance_unknown = True

        try:
            result: Result = provider.dispatch(task)
        except Exception as exc:  # 适配器自身异常不应中断回退链
            result = Result(ok=False, exit_code=-1, note=f"适配器异常: {exc}")

        outcome.attempts.append(
            Attempt(
                provider=provider.name,
                ok=result.ok,
                exit_code=result.exit_code,
                duration_s=round(result.duration_s, 1),
                note=result.note,
                balance_before=balance_before,
                balance_unknown=balance_unknown,
                usage=result.usage or usage_failed(
                    f"适配器未回传 usage（{provider.name} 未实现用量采集或未执行）"),
                route=result.route,
            )
        )
        if result.ok:
            outcome.ok = True
            outcome.provider = provider.name
            outcome.text = result.text
            outcome.exit_code = 0
            outcome.fallback = index > 0
            outcome.balance_unknown = balance_unknown
            return outcome

        if not allow_fallback:
            break

    outcome.exit_code = outcome.attempts[-1].exit_code if outcome.attempts else 1
    return outcome
