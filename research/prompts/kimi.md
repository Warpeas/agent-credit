# Kimi Work · 自述调研

| 项 | 值 |
|---|---|
| 账户 id | `kimi` |
| 厂商 | 月之暗面 |
| 本机客户端 | C:\Users\Hunter\AppData\Local\Programs\Kimi\Kimi.exe |
| 台账已知额度 | 未知 |
| 当前 claim_mode | never |
| 生成日期 | 2026-09-23 |

**怎么用**：把下面四反引号围栏里的整段内容，原样粘进 Kimi Work 的对话框。

````text
你是 Kimi Work（月之暗面）的客户端本体，运行在我这台 Windows 机器上。我搭了一个本地积分台账，想把你的每日签到和余额查询自动化。
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

- 模型线：Kimi K3 / 100万上下文
- 台账记的下次重置：2026-10-14

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
account_id: kimi
software: Kimi Work
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
  kimi:                             # 示例（按需增删，注释行可删）:
    # claim_mode: external
    # command: "python C:\path\to\checkin.py"
    # status_command: "python C:\path\to\status.py"
    # notes: "接口从 xx 逆向；改版后失效条件：..."
```
````

## 回填

1. 把它的回答整段存进 `research/answers/kimi.md`
2. 人工核对 `evidence` 里没有 token 明文
3. 把 `catalog_patch` 段合进 `catalog.yaml`（当前运行时只消费 `claim_mode` 和 `command`；
   `status_command` 是给后续 `credit sync` 预留的字段，先存着不影响现有逻辑）
