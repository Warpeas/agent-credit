"""Trae 积分明细：人话打印 + 把登记交给标准对账通道。

解析与口径统一在 agent_credit/trae_credits.py（通用对账契约的实现方），
本脚本只做两件事：
  1. 打印人话明细（总余额 / 到期日 / 口径 / 逐条）
  2. --record 时调用 `credit.py sync --only trae` 走标准登记通道

为什么不再直接 set-balance：set-balance 写的是一条**无过期时间**的快照，
「快过期先烧」这条规则对 Trae 形同虚设（台账里 Trae 曾只有 25 条本地估算
+ 4 条无到期日快照）。改走 credits_command 后，Trae 的到期日来自客户端
导出的 dump（2026-10-20 实测为 2026-10-31 23:59），与 WorkBuddy 同一套通道。

写账仍然只走 CLI（本脚本不碰 data/ledger.json）。

用法：
    python scripts\trae_credit_detail.py            # 只看明细
    python scripts\trae_credit_detail.py --record   # 明细 + 登记进台账
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import trae_credits  # noqa: E402


def main() -> int:
    try:
        parsed = trae_credits.parse_dump(trae_credits.load_dump())
    except trae_credits.CreditQueryError as exc:
        print(f"!! {exc}")
        return 2

    print(trae_credits.format_text(parsed))
    dump_day = trae_credits.dump_date(parsed)
    print(f"dump 归属日期: {dump_day}（今天={trae_credits.date.today()}）")

    if "--record" not in sys.argv:
        return 0

    # 登记走标准对账通道：它自带新鲜度闸门，不是今天的 dump 会被拒（不动台账）
    ret = subprocess.run(
        [sys.executable, str(ROOT / "credit.py"), "sync", "--only", "trae"],
        cwd=str(ROOT),
    )
    print(f"credit.py sync --only trae exit={ret.returncode}")
    return ret.returncode


if __name__ == "__main__":
    raise SystemExit(main())
