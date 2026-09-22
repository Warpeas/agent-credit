# agent-credit

本地 Agent 积分台账 + 签到编排。当日清零、登录即领的软件**不自动启动**，用的时候再开。

## 命令

在本目录：

```bat
credit.cmd status
credit.cmd due
credit.cmd doctor
credit.cmd checkin
credit.cmd checkin --open
credit.cmd open workbuddy
credit.cmd recommend 重构这个仓库
credit.cmd record autoclaw claimed
credit.cmd set-balance minimax 3200
credit.cmd record workbuddy used 50
```

或：`python credit.py status`

## 一期范围

- 每日必签（无上限可攒）：WorkBuddy / MiniMax / TraeWork / AutoClaw / LobsterAI；MonkeyCode 积分仍手签
- 自动签到：本机已装客户端 UI（点「签到」；MiniMax 额外尝试发送 `/checkin`）。点不到则 pending，不入账
- 可选：在 `catalog.yaml` 填 `command` 覆盖为外部脚本
- AutoClaw：每日 200，无明确过期；UI 失败后 `record autoclaw claimed 200`
- DuMate / ToDesk：上限未测出前不自动领
- 不做：定时启动 Mavis / MonkeyCode Token / Loomy 等当日清零客户端

## 计划任务（可选）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
```

## Agent 技能

技能文件：`skill/SKILL.md`。已安装到用户技能目录后，对话里说「今天签到」「这个任务用哪个」即可。
