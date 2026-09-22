# 答案格式规范

各家的回答统一用这份 YAML。除了 YAML 本身，最多再加三行说明。

填之前读一遍 `research/README.md` 的「回填规矩」，尤其是 token 那一条。

```yaml
account_id: <account_id>
software: <软件名>
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

catalog_patch:                      # 只写确定要改的字段，不确定的别写
  <account_id>:                             # 示例（按需增删，注释行可删）:
    # claim_mode: external
    # command: "python C:\path\to\checkin.py"
    # status_command: "python C:\path\to\status.py"
    # notes: "接口从 xx 逆向；改版后失效条件：..."
```
