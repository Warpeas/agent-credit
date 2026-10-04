# research · 让各家 Agent 自己交代签到方式

## ⚠️ 先读这个

**`research/SAFETY.md` —— 探索安全约束（禁止清单 / 允许路线 / 探测预算 / 收手判据）**

这些客户端的账号承载真实付费订阅，被服务端判定为自动化攻击会**直接封号**，
已囤的积分与订阅归零。动手探测任何客户端之前先读那份文件，冲突时以它为准。

## 为什么这么干

从外部逆向各家客户端的接口有三宗罪：慢、容易随版本失效、而且现代前端普遍用 `isTrusted`
校验把模拟点击挡在门外（MiniMax 已经实测撞过两次）。

换个方向：**直接问它们本人**。这些软件大多是 Agent 产品，能读自己的安装目录、能查自己的文档、
能告诉我页面上有什么。它们对自己的签到入口比任何外部逆向都清楚。

## 流程

```
scripts/gen_research_prompts.py
        │  生成通用 prompt + 各家答案模板
        ▼
research/prompts/UNIVERSAL.md
        │  整段粘进目标客户端的对话框（一次一家）
        ▼
  该软件按 SCHEMA 回答
        │  存进 research/answers/<id>.md
        ▼
  catalog_patch 合入 catalog.yaml
```

## 目录

| 路径 | 作用 |
|---|---|
| `scripts/gen_research_prompts.py` | 生成器。改了 catalog 后重跑，速查表会带上最新路径与额度 |
| `scripts/check_research_answers.py` | 入库前校验：填了没 + 有没有 token 明文。发现疑似明文 exit 1 |
| `research/prompts/UNIVERSAL.md` | **只有一份**。通用探索流程 + 本机安装目录速查表，粘进任意一家客户端 |
| `research/answers/<id>.md` | 答案存放处，**按家分文件**。已存在的不会被生成器覆盖 |
| `research/ANSWER-SCHEMA.md` | 答案格式规范，独立一份方便随时对照 |
| `research/tools/` | 逆向/取证脚本。记录「怎么发现的」，比结论更值钱 |
| `vendor/<客户端>/*/` | 官方接口直签与探测脚本，凭据一律运行时从本机读，不落盘 |

## tools：取证脚本值得入库

`research/tools/` 下的脚本不是草稿，是**排查过程的存档**。举几个例子说明为什么：

- `analyze_minimax_windows.py` — MiniMax「全黑窗口」的取证入口，
  枚举进程下每个窗口报 class/可见性/渲染采样
- `timeline_minimax_startup.py` — 冷启动时序采样，
  回答「黑窗是否早期 visible 且渲染纯黑、之后被隐藏」
- `probe_minimax_windows.py` — 逐窗口 PrintWindow 判空白
- `explore_monkeycode.ps1` — MonkeyCode 界面探索（只截图 OCR，不点击）

结论会写进 `catalog.yaml` 的 notes，但**「怎么排除其他可能」只有脚本记得**。
下次该客户端改版、问题复发时，照着改几个常量就能重跑，
比从头逆向一遍省几小时。所以这类脚本一律入库，不按「本地草稿」处理。

## 回填规矩

1. 答案存进 `research/answers/<id>.md`，保留对方原话。
2. **先查 `evidence` 段有没有 token / cookie / 密码明文**，有就全换成 `<redacted>`。
   仓库里不留任何登录态。拿不准就跑一遍：

   ```bat
   python scripts\check_research_answers.py
   ```

   它扫 JWT / Bearer / `sk-` / Authorization / 长 base64 / 口令 / cookie 字段，
   命中就 exit 1 并把片段打出来。宁可误报也不漏报，误报人工看一眼就能排除。
3. `confidence: 推测` 或 `reliability: 未实测` 的，别急着改 `catalog.yaml`。
   先按它给的 `command` 手动跑一次，确认 exit 0 且真的入账了再合。
4. 合入时只动 `catalog_patch` 里列出的字段，顺手更新账户的 `notes`，
   把「怎么找到的」和「已知会失效的条件」写进去——下次它改版时能省一半时间。

## 当前运行时支持范围

`catalog.yaml` 里现在只有 `command` 被 `checkin` 消费。

`status_command` 是**预留字段**：语义为输出一行 JSON
`{"balance": 0, "claimed_today": false}`，供后续 `credit sync`（拉真实余额校正台账）使用。
现在填进去不影响任何现有逻辑，但会记录下来。

## 优先级

按额度 × 缺口排，`gen_research_prompts.py` 里的 `RESEARCH_IDS` 顺序即优先级
（答案文件按这个顺序生成，速查表也按这个顺序排）：

**已打通**（2026-10-04）：`workbuddy`(external) / `minimax`(external+UI 回退) /
`traework`(UI) / `autoclaw`(UI) / `lobsterai`(UI) / `monkeycode_credit`(UI)

**仍待探索**：

1. `dumate` / `todesk` — 卡在领取上限（cap）没测出来
2. `kimi` / `joycode` / `qclaw` — 月度或一次性，优先级最低
3. `monkeycode_token` — 10M/天当日清零，用时再开，不用每日签

各家的坑（黑窗、坐标换算、验证码）记在 `catalog.yaml` 对应账户的 `notes` 里，
排查过程记在 `research/tools/`。
