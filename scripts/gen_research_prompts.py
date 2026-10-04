#!/usr/bin/env python3
"""生成 research/prompts/UNIVERSAL.md 与 research/answers/<id>.md。

思路：不让主项目从外部硬逆向各家接口，而是给每家 Agent 一份**通用**的探索 prompt，
让它自己交代签到入口、余额查询方式和自动化可行性。答案按 SCHEMA 回填到
research/answers/，其中的 catalog_patch 段可直接合入 catalog.yaml。

为什么 prompt 只有一份通用的：
  各家都是打包型客户端，签到信息藏在自己的 resources/app.asar 里，探索流程完全一样。
  按家定制问卷的好处只是「能带上这家已知的额度」，而这点用一张安装目录速查表就够，
  代价却是十几份文件要跟 catalog 同步维护。所以：prompt 通用化，答案仍按家分文件存。

用法：
    python scripts/gen_research_prompts.py            # 生成（答案文件已存在则跳过）
    python scripts/gen_research_prompts.py --force    # 强制重建（只影响 prompt / schema）
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

UNIVERSAL_PATH = PROMPT_DIR / "UNIVERSAL.md"

# 需要维护答案文件的账户。顺序 = 优先级（额度大 / 缺口严重的靠前）。
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

UNIVERSAL_TEMPLATE = """# 通用探索调研 prompt

| 项 | 值 |
|---|---|
| 适用 | 本机任意一家 Agent 客户端（AutoClaw / TraeWork / LobsterAI / ...） |
| 生成日期 | {today} |
| 用法 | 粘进目标客户端的对话框，一次搞定一家 |

**怎么用**

1. 打开目标客户端
2. 把下面四反引号围栏里的整段，原样粘进它的对话框
3. 把它的回答（探索日志 + YAML）整段存进 `research/answers/<id>.md`
4. 跑 `python scripts\\check_research_answers.py` 确认没混进 token 明文
5. `reliability: 已实测` 才改 `catalog.yaml`

**为什么只有一份通用的**

各家都是打包型客户端，签到信息藏在自己的 `resources/app.asar` 里，探索流程完全一样。
上一代按家定制的问卷在 MiniMax Code 上失效过——它全程答 `unknown`，
而端点就在它自己的 `resources/app.asar` 里（`/minimax-cloud/api/v1/signin/status`
与 `/signin/claim`），我十分钟就翻出来了。失效根因是：客户端工作在用户的项目目录里，
压根没想到去翻自己的安装目录，于是凭印象作答。

所以这一版不做定制描述，改为**统一探索流程 + 一张安装目录速查表**：
谁都能用，也不随 `catalog.yaml` 变动而失效。**粘贴前不用改任何东西**，
正文里带了本机的路径表，让它自己对号入座。

**若它仍然交白卷**：自述路线对打包型客户端价值有限，兜底是自己扫它的 `resources/app.asar`
找接口字面量。点击路线一律走 OS 级注入（`SetCursorPos` + `mouse_event`），
**不要**用 UIA 的 `InvokePattern`——那条 `isTrusted` 为 false 会被前端过滤。
结论出处：`research/answers/minimax.md`。

````text
你是本机装的一个 AI Agent 客户端。我搭了本地积分台账，想把你的「每日签到」和「剩余积分」自动化。

先讲一个反面案例。我用「请你自述」的问法问过本机另一家客户端，它全程回答 unknown。
后来我自己在它的 resources/app.asar 里翻了十分钟，就找到了签到端点的字面量路径
（形如 /xxx/api/v1/signin/status 与 /signin/claim）。
它答 unknown 不是因为做不到，而是凭印象作答、没真的去读自己的打包产物。
**所以这次我要的不是你的印象，是你查过之后的证据。**

## 0. 先对号入座，再自报家门

本机已探测到的客户端（找到你自己那一行；表里没有你，就自己找安装目录并告诉我）：

{path_table}

然后回答：

- 你的 `account_id`（用表里的 id；表里没有就自己起一个英文小写 id）
- 你的版本号
- 逐条说能做 / 不能做：执行本机 PowerShell 或 Python；读本机任意路径的文件；
  对大文件（几百 MB 的二进制归档）做字符串搜索；看到并截取当前界面；
  有没有内置的「定时任务 / 自动化」入口；有没有自带 CLI

哪一项不行就直说，我换路线，不要硬答。

## 1. 探索步骤（按顺序做，边做边贴命令与输出片段）

A. 列你的安装目录与 `resources` 目录，说明每个子目录大概是干什么的
B. 确认你是不是 Electron 应用。如果是，前端打包产物通常在：
   - `resources/app.asar`          （归档；接口路径是字符串常量，混淆不掉）
   - `resources/app.asar.unpacked` （未打包部分）
   顺手看同目录有没有 CLI 线索（*.cmd、node/、python/ 之类）
C. 在上面这些文件里搜签到相关字面量，中英文都要搜：
   - 英文：signin / sign_in / checkin / check-in / daily / claim / reward / points / credit / quota / task
   - 中文：签到 / 积分 / 领取 / 已签 / 连续 / 活动
   二进制也能直接搜。参考：

```python
import re, pathlib
d = pathlib.Path(r"<你的 app.asar 绝对路径>").read_bytes()
n = 0
for m in re.finditer(rb"signin|checkin|daily|points|积分|签到", d):
    print(m.start(), d[max(0, m.start() - 120):m.start() + 200])
    n += 1
    if n > 20:
        break
```

   一次搜全盘会很慢，先搜 resources 下的 *.asar / *.js / *.json
D. 命中疑似端点后补齐四件事：HTTP 方法、完整路径、host 常量（一般在同文件的 BASE / HOST 常量里）、
   鉴权怎么带（只说「从哪个字段 / 哪个请求头读」，不要贴值）
E. 找本机明文配置与日志（典型位置：`%APPDATA%\\<你>`、`%USERPROFILE%\\.<你>`、安装目录下的 logs / userData），
   看有没有能直接读出「今日是否已签」「剩余积分」的文件
F. 如果你有「定时任务 / 自动化 / Skills」入口，说清楚它能不能每天自己触发一次签到动作

## 2. 我要的结论

1. **签到的人类点击路径**：从界面哪个入口进、几步、按钮叫什么
2. **端点**（能确认就给）：method + path + host + 参数形状 + 鉴权来源
3. **规则**：每日额度、连续签到周期与额外奖励、积分有效期、有没有领取上限
   （表里我记的额度与实际不符就纠正我）
4. **幂等与风控**：重复触发签到会怎样，有没有频率限制
5. **外部自动化哪条路走得通**：官方 CLI / 本地 HTTP / 只能模拟点击 / 都不行。
   若涉及模拟点击：你们前端有没有 isTrusted 之类校验，会不会被系统 UIPI 拦掉
6. **你自己能不能用定时任务每天自签**（可以的话说清怎么配）

## 3. 硬约束（违反就别做）

- 不解密任何加密的登录态，不绕开鉴权
- 不输出 token / cookie / 密码原文，一律写 `<redacted>`，只说明「从哪个字段读」
- 不把任何本机数据上传到第三方
- 不执行兑换、抽奖、购买、下单这类会消耗资源的操作
- **探索阶段不要替我点签到**——今天这份额度我自己安排；要真点验证，先问我一句
- 不确定就写 `unknown`，但必须附上「我试了 X，没找到 Y」。**不许没查就写 unknown**
- 每条结论都要带证据：文件路径 + 命中片段。推测的标 `reliability: 推测`

## 4. 输出格式

先给一段「探索日志」：你跑了哪些命令、看到了什么、哪几步没结果，5~15 行。
再给下面这份 YAML，原样填好。除了探索日志和 YAML，最多再加三行说明。

```yaml
{schema}```
````

## 回填

1. 把它的回答整段存进 `research/answers/<id>.md`
2. 人工核对 `evidence` 里没有 token 明文（或跑 `python scripts\\check_research_answers.py`）
3. 把 `catalog_patch` 段合进 `catalog.yaml`（当前运行时只消费 `claim_mode` 和 `command`；
   `status_command` 是给后续 `credit sync` 预留的字段，先存着不影响现有逻辑）
"""

ANSWER_TEMPLATE = """# {name} · 探索答案

| 项 | 值 |
|---|---|
| 账户 id | `{id}` |
| 状态 | **待填** |

把 {name} 的回答原样粘到下面。粘之前确认：`evidence` 段里没有 token / cookie / 密码明文，
有的话全部替换成 `<redacted>`。

```yaml
{schema}```
"""


def _dirs(acc_id: str) -> tuple[str, str]:
    """(安装目录, resources 目录)。客户端不会自己找安装目录，必须由我们喂给它。"""
    exe = find_exe(acc_id)
    if not exe:
        return "未探测到", "未探测到"
    install = Path(exe).parent
    return str(install), str(install / "resources")


def _amount(acc: dict) -> str:
    parts = []
    if acc.get("daily_amount"):
        parts.append(f"{acc['daily_amount']} {acc.get('unit')}/天")
    if acc.get("monthly_amount"):
        parts.append(f"{acc['monthly_amount']} {acc.get('unit')}/月")
    if acc.get("grant_type") == "one_shot":
        parts.append("一次性")
    return "；".join(parts) or "未知"


def render_path_table() -> str:
    lines = [
        "| account_id | 软件 | 安装目录 | resources | 台账已知额度 |",
        "|---|---|---|---|---|",
    ]
    for acc_id in RESEARCH_IDS:
        try:
            acc = find_account(acc_id)
        except Exception:
            continue
        install, resources = _dirs(acc_id)
        lines.append(
            f"| `{acc_id}` | {acc['name']} | `{install}` | `{resources}` | {_amount(acc)} |"
        )
    return "\n".join(lines)


def render_universal(today: str) -> str:
    return UNIVERSAL_TEMPLATE.format(
        today=today,
        path_table=render_path_table(),
        schema=SCHEMA.format(id="«你的 account_id，见上表»", name="«你的名字»"),
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
    ap = argparse.ArgumentParser(description="生成通用调研 prompt 与各家答案模板")
    ap.add_argument("--force", action="store_true", help="强制重建（prompt / schema）")
    args = ap.parse_args()

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    ANSWER_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    (RESEARCH_DIR / "ANSWER-SCHEMA.md").write_text(render_schema_doc(), encoding="utf-8")
    UNIVERSAL_PATH.write_text(render_universal(today), encoding="utf-8")
    print(f"prompt {UNIVERSAL_PATH.relative_to(ROOT)}")

    known = {a["id"] for a in accounts()}
    written_a: list[str] = []
    for acc_id in RESEARCH_IDS:
        if acc_id not in known:
            print(f"skip unknown account: {acc_id}", file=sys.stderr)
            continue
        a = ANSWER_DIR / f"{acc_id}.md"
        if not a.exists():
            a.write_text(render_answer(find_account(acc_id)), encoding="utf-8")
            written_a.append(str(a.relative_to(ROOT)))

    for f in written_a:
        print("answer", f)


if __name__ == "__main__":
    main()
