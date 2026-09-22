#!/usr/bin/env python3
"""生成 research/prompts/<id>.md 与 research/answers/<id>.md。

思路：不让主项目从外部硬逆向各家接口，而是给每家 Agent 一份定制 prompt，
让它自己交代签到入口、余额查询方式和自动化可行性。答案按 SCHEMA 回填到
research/answers/，其中的 catalog_patch 段可直接合入 catalog.yaml。

用法：
    python scripts/gen_research_prompts.py            # 生成（答案文件已存在则跳过）
    python scripts/gen_research_prompts.py --force    # 强制重建 prompts
已有答案文件永不被覆盖。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit.apps import find_exe  # noqa: E402
from agent_credit.catalog import accounts, find_account  # noqa: E402

RESEARCH_DIR = ROOT / "research"
PROMPT_DIR = RESEARCH_DIR / "prompts"
ANSWER_DIR = RESEARCH_DIR / "answers"

# 需要调研的账户。顺序 = 优先级（额度大 / 缺口严重的靠前）。
RESEARCH_IDS = [
    "minimax",
    "autoclaw",
    "traework",
    "lobsterai",
    "workbuddy",
    "dumate",
    "todesk",
    "monkeycode_credit",
    "kimi",
    "joycode",
    "qclaw",
]

SCHEMA = """account_id: {id}
software: {name}
version: unknown
researched_at: YYYY-MM-DD
confidence: unknown                # high | medium | low

checkin:
  supported: unknown               # true | false | unknown
  human_path: unknown               # 人类在界面里的点击路径，如「左下角头像 → 每日签到」
  api: unknown                      # "POST https://.../path" + 关键参数形状
  cli: unknown                      # 官方 CLI / 脚本命令
  daily_amount: unknown
  streak_cycle: unknown             # 如 "7 天一轮；第 4、7 天各 +1000"
  validity_days: unknown            # 积分有效期，无过期写 null
  cap: unknown                      # 领取上限，测不出写 null
  idempotent: unknown               # 重复触发签到是否安全

status:
  balance: unknown                  # 查剩余积分：界面路径 / API / 本机文件
  claimed_today: unknown            # 查今日是否已签
  unit: credit

automation:
  claim_mode: unknown               # external | ui | manual | never
  command: unknown                  # Windows 一行命令，签到成功 exit 0
  status_command: unknown           # 输出 JSON: {{"balance": 0, "claimed_today": false}}
  blockers: unknown                 # 如 "模拟点击被 isTrusted 过滤 / UIPI 拦截"
  reliability: unknown              # 已实测 | 未实测 | 推测

evidence:
  - unknown                         # 文件 / URL / 命令 -> 看到了什么；token 一律 <redacted>

open_questions:
  - unknown

catalog_patch:                      # 只写确定要改的字段，不确定的别写
  {id}:                             # 示例（按需增删，注释行可删）:
    # claim_mode: external
    # command: "python C:\\path\\to\\checkin.py"
    # status_command: "python C:\\path\\to\\status.py"
    # notes: "接口从 xx 逆向；改版后失效条件：..."
"""

PROMPT_TEMPLATE = """# {name} · 自述调研

| 项 | 值 |
|---|---|
| 账户 id | `{id}` |
| 厂商 | {vendor} |
| 本机客户端 | {exe} |
| 台账已知额度 | {daily} |
| 当前 claim_mode | {mode} |
| 生成日期 | {today} |

**怎么用**：把下面四反引号围栏里的整段内容，原样粘进 {name} 的对话框。

````text
你是 {name}（{vendor}）{app_role}。我搭了一个本地积分台账，想把你的每日签到和余额查询自动化。
我从外部逆向你的接口既慢又容易失效，而且容易被你们的前端校验拦掉——**你最了解你自己**，所以我直接问你。

请回答下面 6 个问题。目标是让我能在无人值守的情况下做到两件事：
  (1) 每天触发一次你的签到；
  (2) 随时查询「今天是否已签」和「剩余积分」。

## 一、需要你回答的

1. **签到入口**：人类在你界面里的点击路径；如果你知道对应的 HTTP 接口（方法 + 路径 + 关键参数形状），也写出来。
2. **签到规则**：每日额度、连续签到周期与额外奖励、积分有效期、有没有领取上限（cap）。
3. **查询方法**：查「剩余积分」和「今日是否已签」分别怎么做——界面路径、接口、还是本机某个可读文件。
4. **自动化可行性**：从外部程序触发你的签到，哪条路走得通？
   - 有没有官方 CLI / 开放 API / 可编程入口？
   - 模拟点击会不会被你们前端的 isTrusted 校验或系统 UIPI 拦掉？
   - 有没有配置文件、本地服务、或浏览器扩展可以驱动？
5. **本机线索**：你的安装目录、配置文件、日志在哪；其中哪些是明文可读的。
6. **幂等与风险**：重复调用签到会怎样；有没有频率限制或反刷风控。

## 二、我已经知道 / 已经试过

{known}

## 三、你可以怎么查

- 读你自己的安装目录、前端资源/bundle、本地缓存里的接口路径
- 读本机**明文**的配置与日志
- 查你的官方文档、设置页、帮助中心
- 让我打开某个页面，然后告诉我你在页面上看到了什么
- 直接给我一段可执行的命令（PowerShell / Python），我自己跑

## 四、硬约束（违反就别做）

- **不要**解密任何加密的登录态，**不要**绕开鉴权
- **不要**输出 token / cookie / 密码原文，一律写 `<redacted>`，只说明「从哪个字段读」
- **不要**把任何本机数据上传到第三方
- **不要**执行兑换、抽奖、购买、下单这类会消耗资源的操作
- 签到**只给我方法，不要你替我点**——真正的领取由我的脚本执行
- 不确定就写 `unknown`，**不要编**；猜测必须标 `reliability: 推测`

## 五、输出格式

把答案写成下面这段 YAML，原样填好回给我。除了 YAML 本身，最多再加三行说明。

```yaml
{schema}```
````

## 回填

1. 把它的回答整段存进 `research/answers/{id}.md`
2. 人工核对 `evidence` 里没有 token 明文
3. 把 `catalog_patch` 段合进 `catalog.yaml`（当前运行时只消费 `claim_mode` 和 `command`；
   `status_command` 是给后续 `credit sync` 预留的字段，先存着不影响现有逻辑）
"""

ANSWER_TEMPLATE = """# {name} · 自述答案

| 项 | 值 |
|---|---|
| 账户 id | `{id}` |
| 状态 | **待填** |

把 {name} 的回答原样粘到下面。粘之前确认：`evidence` 段里没有 token / cookie / 密码明文，
有的话全部替换成 `<redacted>`。

```yaml
{schema}```
"""


def _known_block(acc: dict) -> str:
    lines: list[str] = []
    notes = (acc.get("notes") or "").strip()
    if notes:
        lines.append(f"- {notes}")
    models = (acc.get("models_note") or "").strip()
    if models:
        lines.append(f"- 模型线：{models}")
    daily = acc.get("daily_amount")
    monthly = acc.get("monthly_amount")
    if daily:
        lines.append(f"- 台账记的每日额度：{daily} {acc.get('unit')}")
    if monthly:
        lines.append(f"- 台账记的每月额度：{monthly} {acc.get('unit')}")
    if acc.get("expires_on"):
        lines.append(f"- 台账记的到期日：{acc['expires_on']}")
    if acc.get("next_reset"):
        lines.append(f"- 台账记的下次重置：{acc['next_reset']}")
    streak = acc.get("streak") or {}
    if streak:
        lines.append(
            f"- 台账记的连签：{streak.get('cycle_days')} 天一轮，第 {streak.get('bonus_on')} 天奖励 {streak.get('bonus_amount')}"
        )
    return "\n".join(lines) or "- （暂无，从零开始）"


def render_prompt(acc: dict, today: str) -> str:
    exe = find_exe(acc["id"])
    daily = acc.get("daily_amount") or acc.get("monthly_amount") or 0
    app_role = "的客户端本体，运行在我这台 Windows 机器上"
    return PROMPT_TEMPLATE.format(
        id=acc["id"],
        name=acc["name"],
        vendor=acc.get("vendor") or "unknown",
        exe=str(exe) if exe else "未探测到",
        daily=f"{daily} {acc.get('unit')}" if daily else "未知",
        mode=acc.get("claim_mode") or "unknown",
        today=today,
        app_role=app_role,
        known=_known_block(acc),
        schema=SCHEMA.format(id=acc["id"], name=acc["name"]),
    )


def render_answer(acc: dict) -> str:
    return ANSWER_TEMPLATE.format(
        id=acc["id"],
        name=acc["name"],
        schema=SCHEMA.format(id=acc["id"], name=acc["name"]),
    )


def render_schema_doc() -> str:
    return (
        "# 答案格式规范\n\n"
        "各家的回答统一用这份 YAML。除了 YAML 本身，最多再加三行说明。\n\n"
        "填之前读一遍 `research/README.md` 的「回填规矩」，尤其是 token 那一条。\n\n"
        "```yaml\n"
        + SCHEMA.format(id="<account_id>", name="<软件名>")
        + "```\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="生成各 Agent 软件的调研 prompt")
    ap.add_argument("--force", action="store_true", help="强制重建 prompts")
    args = ap.parse_args()

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    ANSWER_DIR.mkdir(parents=True, exist_ok=True)
    (RESEARCH_DIR / "ANSWER-SCHEMA.md").write_text(render_schema_doc(), encoding="utf-8")

    known = {a["id"] for a in accounts()}
    today = date.today().isoformat()
    written_p: list[str] = []
    written_a: list[str] = []
    skipped: list[str] = []

    for acc_id in RESEARCH_IDS:
        if acc_id not in known:
            print(f"skip unknown account: {acc_id}", file=sys.stderr)
            continue
        acc = find_account(acc_id)

        p = PROMPT_DIR / f"{acc_id}.md"
        if args.force or not p.exists():
            p.write_text(render_prompt(acc, today), encoding="utf-8")
            written_p.append(str(p.relative_to(ROOT)))
        else:
            skipped.append(str(p.relative_to(ROOT)))

        a = ANSWER_DIR / f"{acc_id}.md"
        if not a.exists():
            a.write_text(render_answer(acc), encoding="utf-8")
            written_a.append(str(a.relative_to(ROOT)))

    for f in written_p:
        print("prompt", f)
    for f in written_a:
        print("answer", f)
    for f in skipped:
        print("exists", f)


if __name__ == "__main__":
    main()
