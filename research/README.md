# research · 让各家 Agent 自己交代签到方式

## 为什么这么干

从外部逆向各家客户端的接口有三宗罪：慢、容易随版本失效、而且现代前端普遍用 `isTrusted`
校验把模拟点击挡在门外（MiniMax 已经实测撞过两次）。

换个方向：**直接问它们本人**。这些软件大多是 Agent 产品，能读自己的安装目录、能查自己的文档、
能告诉我页面上有什么。它们对自己的签到入口比任何外部逆向都清楚。

## 流程

```
scripts/gen_research_prompts.py
        │  从 catalog.yaml 生成定制 prompt
        ▼
research/prompts/<id>.md
        │  整段粘进对应软件的对话框
        ▼
  该软件按 SCHEMA 回答
        │  存进 research/answers/<id>.md
        ▼
  catalog_patch 合入 catalog.yaml
```

## 目录

| 路径 | 作用 |
|---|---|
| `scripts/gen_research_prompts.py` | 生成器。改了 catalog 后重跑，prompt 会带上最新已知信息 |
| `scripts/check_research_answers.py` | 入库前校验：填了没 + 有没有 token 明文。发现疑似明文 exit 1 |
| `research/prompts/<id>.md` | 每家一份，粘进它自己的对话框 |
| `research/answers/<id>.md` | 答案存放处。**已存在的不会被生成器覆盖** |
| `research/ANSWER-SCHEMA.md` | 答案格式规范，独立一份方便随时对照 |

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

按额度 × 缺口排，`research/prompts/` 里的生成顺序即优先级：

1. `minimax` — 400/天，全靠手签，最大缺口
2. `autoclaw` — 200/天，OCR 入口定位已失效
3. `traework` — 150/天，UI 路线未验证
4. `lobsterai` — 100/天，UI 路线未验证
5. `workbuddy` — 已通，主要想补齐余额查询接口
6. `dumate` / `todesk` — 卡在领取上限（cap）没测出来
7. `monkeycode_credit` — 手签
8. `kimi` / `joycode` / `qclaw` — 月度或一次性，优先级最低
