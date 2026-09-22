# WorkBuddy · 自述答案

| 项 | 值 |
|---|---|
| 账户 id | `workbuddy` |
| 状态 | **待填** |

把 WorkBuddy 的回答原样粘到下面。粘之前确认：`evidence` 段里没有 token / cookie / 密码明文，
有的话全部替换成 `<redacted>`。

```yaml
account_id: workbuddy
software: WorkBuddy
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
  status_command: unknown           # 输出 JSON: {"balance": 0, "claimed_today": false}
  blockers: unknown                 # 如 "模拟点击被 isTrusted 过滤 / UIPI 拦截"
  reliability: unknown              # 已实测 | 未实测 | 推测

evidence:
  - unknown                         # 文件 / URL / 命令 -> 看到了什么；token 一律 <redacted>

open_questions:
  - unknown

catalog_patch:                      # 只写确定要改的字段，不确定的整块删掉
  workbuddy: {}
```
