# MonkeyCode 积分 · 自述答案

| 项 | 值 |
|---|---|
| 账户 id | `monkeycode_credit` |
| 状态 | **已填（2026-11-14 更新）** |

目前 MonkeyCode 只有每日签到 +100 积分，不再发放其他额度或 Token。

```yaml
account_id: monkeycode_credit
software: MonkeyCode 积分
version: "monkeycode-desktop.exe 51MB（2026-10-20 复扫）"
researched_at: 2026-10-20
confidence: high

checkin:
  supported: true
  human_path: "左下角设置 → 账号页积分卡片下方「签到 +100」"
  api: "POST https://monkeycode-ai.com/api/v1/users/wallet/checkin（需 captcha，code 10701，禁止破解）"
  cli: "python {REPO}\\scripts\\ui_claim_monkeycode.py"
  daily_amount: 100
  streak_cycle: null
  validity_days: unknown
  cap: null
  idempotent: true                 # GET /wallet/checkin 先查 checked_in，已签直接返回

status:
  balance: "GET https://monkeycode-ai.com/api/v1/users/wallet → data.balance 毫积分；界面积分 = balance // 1000"
  claimed_today: "GET https://monkeycode-ai.com/api/v1/users/wallet/checkin → data.checked_in"
  unit: credit
  per_grant_expiry: false          # 官方接口与 UI 都没有逐条 grant / 过期时间

automation:
  claim_mode: ui
  command: "python {REPO}\\scripts\\ui_claim_monkeycode.py"
  status_command: "set PYTHONPATH={REPO}&& python -m agent_credit.mc_credits --line"
  credits_command: "set PYTHONPATH={REPO}&& python -m agent_credit.mc_credits --ledger"
  blockers: "POST checkin 需图形验证码，禁止破解；external 直签不可行"
  reliability: 已实测

evidence:
  - "2026-10-20 只读 GET /api/v1/users/wallet HTTP 200：余额无逐条 grant/过期字段"
  - "2026-10-20 只读 GET /api/v1/users/wallet/checkin HTTP 200：{checked_in: true}"
  - "2026-10-20 只读 GET /api/v1/users/subscription HTTP 200：会员 plan=basic，不是积分包"
  - "2026-10-20 复扫 monkeycode-desktop.exe：积分相关路径仍只有 /api/v1/users/wallet 与 /api/v1/users/wallet/checkin"
  - "2026-10-04 UI：设置→账号 三栏（今日额度 / 积分 / 已邀请），无明细、无有效期文案"
  - "毫积分口径：2026-10-04 界面「积分 195」vs API 195267；签到 +100 后界面 295 vs API 295267。把 raw 入账会放大 1000 倍"
  - "凭据：明文 cookie 文件 %APPDATA%\\com.chaitin.baizhi.monkeycode\\monkeycode-cookies.json（运行时读取，不落盘、不打印）"

open_questions:
  - "有效期服务端到底有没有、只是不下发？维持 unknown，不再扩探测面"

catalog_patch:
  monkeycode_credit:
    status_command: "set PYTHONPATH={REPO}&& python -m agent_credit.mc_credits --line"
    credits_command: "set PYTHONPATH={REPO}&& python -m agent_credit.mc_credits --ledger"
```

## 查询 / 登记流程（2026-10-20）

能拿到的：

- 积分**总量**（界面积分）
- 今日是否已签

拿不到的：

- 每条积分的剩余
- 每条积分的过期时间

每日签到后自动同步：

1. `checkin` 跑 UI 签到（已签则 GET checkin 短路）
2. 末尾对账：`credits_command` → `python -m agent_credit.mc_credits --ledger`
   输出 `{"grants":[{"remain":N,"expires":null}],"total":N}`，source=sync 重建账本
3. `_refresh_board` 写 `logs/board/board-日期.md` 与 `data/board.json`
4. 计划任务 `scripts/_daily_chain.ps1` 末尾再跑一次 `credit board`

手动：

```bat
python -m agent_credit.mc_credits
python -m agent_credit.mc_credits --line
python credit.py credits monkeycode_credit
python credit.py sync --only monkeycode_credit
python credit.py board
```

回归：`python scripts/test_mc_credits.py`

⚠️ 不要把 wallet.balance 原样 `set-balance`。必须 ÷1000。
