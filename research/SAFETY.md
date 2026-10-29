# 探索安全约束

> 适用于**所有**对本机已安装 Agent 客户端的探测活动：接口逆向、端点猜测、
> 凭据读取、UI 自动化、取证抓图、写诊断脚本。
>
> 违反这里的约束，风险不是「脚本跑不通」，而是**账号被封**或**客户端被判定为攻击流量**。

## 0. 为什么立这份约束

这些客户端的账号承载着真实付费订阅（MiniMax、WorkBuddy、Trae 等），
一旦被服务端判定为自动化攻击或凭据窃取，轻则风控限流、重则**封号**，
而封号意味着已囤的积分与订阅直接归零。代价远高于「多领 100 积分」的收益。

**默认立场：宁可不查，不可越界。** 任何探索动作在动手前先问一句：
「这个动作会不会让服务端看到异常？」会，就不做。

## 1. 绝对禁止（任何情况都不做）

| 禁止 | 原因 |
|---|---|
| **解密加密存储的登录态** | 如 Trae `storage.json` 的 `iCubeAuthInfo`、AutoClaw `auth.json` 的 safeStorage（`enc:` 前缀）。解密本身就是攻击行为，且密钥派生可能触发本地检测。 |
| **内存读取/注入/hook 取token** | Trae 的 token 只存在于 Electron 主进程内存，取它必须注入或 hook，等同于窃取凭据。 |
| **开remote-debugging / CDP 端口** | 如 `AUTOCLAW_CDP_PORT`。这是**本机任意进程可连**的调试口，一旦开启等于把整个客户端的控制权暴露给任何程序。 |
| **绕过完整性级别 / 反调试 / 代码签名校验** | UIPI 提权只为「让点击能被接收」，不是用来绕过签名或篡改客户端的。 |
| **篡改客户端本地数据以伪造额度** | 改 localStorage / LevelDB / sqlite 伪造签到成功。 |
| **高频/并发压测式请求** | 无意义的重试风暴会被风控识别。**不写循环重试**，一个动作失败就停下换思路。 |
| **把凭据外传给任何第三方** | 包括"帮我分析一下"这类场景、包括打到公网探针服务。 |
| **绕过验证码 / 反自动化验证** | 图形/滑块验证码的正常交互是**点一次**，不是破解它。若交互成本高于收益，就放弃该路线。 |

## 2. 允许（且是首选路线）

按优先级从高到低：

1. **只读本机明文凭据 + 调官方接口**
   例：WorkBuddy `workbuddy-desktop.info`、MiniMax `auth.json`、
   MonkeyCode `monkeycode-cookies.json`、LobsterAI `sqlite` 的 `auth_tokens`。
   约束：凭据**运行时读取**，不落盘、不进命令行、不进日志、不进输出。

2. **让客户端自己说话**
   读 `app.asar` / `dist` 里的 i18n 文案与接口路径字符串。**只读，不执行、不改写。**
   延伸（2026-10-20 对 Qoder CN 实测有效）：客户端常把自己拿到的服务端响应**明文落在
   自己的日志里**（如 `%APPDATA%\com.qodercn.app.stable\logs\*/main.log` 的
   `用量响应摘要`）。读它 = 读客户端已经说出来过的话，不解密、不额外发请求、
   不碰凭据。注意它受客户端自己的缓存/触发条件限制，要用新鲜度闸门。

3. **本机UI 自动化**
   走客户端自身界面点按钮（OCR 定位 + OS 级输入注入）。这是**客户端期望的交互路径**，
   服务端看到的就是一个正常用户的点击。

4. **只读的 GET探测**
   查询余额、查签到状态这类**语义上就是给你看的**接口。
   但也要限速，且见第3 条的「探测预算」。

5. **问客户端自己**
   `research/prompts/UNIVERSAL.md` 那套：把问题丢给各家 Agent，让它读自己的文档回答。

## 3. 探测预算

- **同一个端点最多试 2 次**。第一次不通，第二次确认不是偶发；仍不通就记为「不可行」，
  换路线或留待主人决定。**严禁写循环重试。**
- **候选端点枚举上限 10 个**。列举超过说明在盲猜，应当停下来先从客户端二进制里找路径字符串。
- 单次探索**不超过 20 个工具调用**。超了就停下来写清楚「卡在哪、需要什么信息」，
  而不是继续扩大探索面。
- 一家客户端**同一轮只做一个假设**。想同时验三个猜想，就分三轮做。

## 4. 判据：什么时候该收手

出现以下任一情况，**立即停止并记录为 unknown**：

- 需要的凭据必须靠解密才能拿到 → 记unknown，走 UI 路线
- 路线需要开调试口 / 改客户端 / 提权到超出正常交互 → 记 unknown，走 UI 路线
- 端点存在但需要自算签名密钥（如 AutoClaw 的 `X-Auth-Sign=md5(APP_ID&ts&APP_KEY)`）→ 记 unknown
- 连续两轮探索都没拿到新信息 → 收手，写进 `validity_audit` 的 unknown 档

**unknown 不是一个失败结果。** 它是一个诚实的结论：这条���不可查，且不重要。
本项目一半以上的有效期就是 unknown，照样运转。

## 5. 记录义务

探索结束后，把结论写进 `catalog.yaml` 对应账户的 `notes`，包含：

- 结论 + **可信度分档**（confirmed / measured / unknown）
- 证据来源（官方文案 / 服务端字段 / 实测 / 客户端二进制）
- **失效条件**（版本号、字段名、端点路径变化）
- 明确写下「哪些路线已排除、为什么」——否则下次会有人重走一遍

写进 `research/answers/<id>.md` 的答案要过
`python scripts\check_research_answers.py`：确认没有 token/cookie/密码明文。

### 5.1 本项目已排除的路线（别再重走）

| 客户端 | 路线 | 为什么排除 |
|---|---|---|
| Trae / TraeCode | external 直签 | token 只存在于 Electron 主进程内存，源自 `storage.json` 的加密登录态。取它必须注入或 hook → 规则 1 禁止 |
| AutoClaw | external 直签 | `auth.json` 凭据为 safeStorage 加密（`enc:` 前缀）；且签名需自算 `md5(APP_ID&ts&APP_KEY)` |
| AutoClaw | CDP 自动化 | 需开 `AUTOCLAW_CDP_PORT`，本机任意进程可连，等于交出客户端控制权 → 规则 1 禁止 |
| MonkeyCode | external 直签 | `POST /users/wallet/checkin` 需 captcha（code 10701）。challenge 的 `{c:50,s:32,d:3}` 恒定 = 固定规格图形验证码，破解它 → 规则 1 禁止 |
| MonkeyCode | 逐条 grant / 过期 | 2026-10-20 复扫 exe 仍只有 `/users/wallet` 与 `/users/wallet/checkin`；GET wallet 无 expire/grants。不要再猜 records/transactions/detail/points（10-04 已 404）。总量对账走明文 cookie + GET wallet（毫积分÷1000） |
| LobsterAI | external 直签 | 服务端 `slot` 恒为 `slotState=empty`，**没有活动可领**。不是脚本问题 |
| Qoder CN | external 直签 / 直查 | 登录态在 `%APPDATA%\com.qodercn.app.stable\auth.v1.dat`，头三字节 `v10` = Chromium safeStorage(DPAPI) 密文 → 规则 1 禁止解密。此前 notes 记的「~/.qoder-cn/.auth 无明文凭据」结论对，但位置要认准 Roaming 的 auth.v1.dat，别再翻 .auth |
| Qoder CN | 逐条 grant / 每条过期 | 2026-10-20 实测 `GET /sash/api/v2/me/usage` 只下发 `userQuota`/`addOnQuota` 两个桶（+ 个人号恒为 missing 的 org/dedicated 计数），**没有任何批次数组**；`expiresAt` 是本套餐的年 9999 哨兵。不要再猜 packages/records 类端点 |
| 各家 | 余额自动对账 | 对 **没有** 明文凭据+官方余额接口的客户端仍成立。WorkBuddy / Trae / MonkeyCode 已分别打通，Qoder CN 靠读客户端自己的日志打通（第四种形态），别再按「只能 OCR」处理这四家 |

这些结论都标了 evidence 位置，改动前先看 notes 里的失效条件。

## 6. 一句话版本

> **只读明文凭据 + 只调官方接口 + 只走客户端自己的界面。
> 解密、调试口、篡改、重试风暴、绕验证码——都不做。
> 查不到就写 unknown，别硬钻。账号比积分贵。**
