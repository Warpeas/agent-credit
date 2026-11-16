---
name: loomy-taskbox-worker
description: 消费 agent-credit 派单任务箱：读取 data/loomy-taskbox/pending/ 里由 credit.py dispatch 派来的任务，逐个执行并写回结果。用户提到「跑任务箱、清任务箱、消费任务箱、taskbox、派单任务」时使用。
---

# Loomy Taskbox Worker

本机调度器（agent-credit 的 `credit.py dispatch`）会把任务投进任务箱等你执行。
你的职责：认领 → 执行 → 写回结果。这是 loomy 适配器唯一的消费端。

任务箱位置：`<REPO>/data/loomy-taskbox/`（REPO = `C:\Users\M4A1g\Documents\Warpeas\agent-credit`）。
目录布局：

```
pending/<id>.json    待认领任务（调度器投递）
running/<id>.json    你已认领、执行中
results/<id>.json    你写回的结果（调度器读走后即删）
worker.heartbeat     每次运行先 touch（调度器 preflight 靠它判断你是否活着）
```

## 执行步骤

1. **先 touch 心跳**：把 `worker.heartbeat` 重写为
   `{"at": "<本地时间 ISO>", "ran": <累计运行次数>}`（旧值读不到就从 1 开始）。
   空箱也要 touch——它证明 worker 链路活着。
2. **扫 `pending/*.json`**，按文件修改时间**最旧优先**，单次最多认领 **3 个**
   （防止单次会话跑超长，剩余留给下一轮）。
3. **逐个处理**：
   a. `os.replace(pending/<id>.json → running/<id>.json)` 认领（原子操作，
      失败说明被别的 worker 抢走，跳过）；
   b. 读 JSON，字段：`id / capability / text / cwd / timeout_s / caller`；
   c. **执行 `text`**——把它当用户指令正常执行（你有完整的工具链：
      读仓库、写文件、跑脚本、查资料、做文档）。任务给了 `cwd` 就在那个目录干活；
   d. 把结果写进 `results/<id>.json`（**必须**：文件名用任务 payload 里的 `id`、
      先写 `<id>.json.tmp` 再 `os.replace`、UTF-8 无 BOM）：
      ```json
      {
        "id": "<同任务 id>",
        "ok": true,
        "text": "任务的产出正文（给调度器 stdout 的内容）",
        "note": "一句执行备注，如模型/关键动作/异常",
        "error": null,
        "elapsed_s": 12.3,
        "finished_at": "<本地时间 ISO>"
      }
      ```
   e. 删除 `running/<id>.json`，再做下一个。
4. **空箱**：touch 心跳后立即结束，回复「任务箱为空」，不要做任何其他事。
5. **顺手清理**：结束时删掉 `running/` 和 `results/` 里修改时间超过 24h 的孤儿文件。

## 硬约束（不满足会假超时/假失败）

1. **结果必须用 payload 里的 `id` 命名**：`results/<id>.json`。自己另起名字，
   调度器永远读不到，最后只能按超时处理。
2. **必须原子写**：先写 `results/<id>.json.tmp`，再 `os.replace` 成正式文件。
   直接写正式文件会让调度器读到半截 JSON（它会重试，但看起来就是卡住）。
3. **必须 UTF-8 无 BOM**。不要用 PowerShell 5 的 `Set-Content -Encoding UTF8`
   （PS5 的 UTF8 带 BOM）；用 Python `json.dump(..., ensure_ascii=False)`，
   或 .NET `[IO.File]::WriteAllText(path, text, (New-Object Text.UTF8Encoding($false)))`。
   调度器虽然按 `utf-8-sig` 读（BOM 能容错），但写端仍以无 BOM 为准。
4. **派单方一律显式带 `--cwd`**：`payload.cwd` 为空时你会落在会话工作区
   （默认 `C:\Users\M4A1g\Documents\Loomy Workspace`），产物就不在仓库里。
   worker 侧看到 `cwd` 为空要如实写进 `note`，别默默在错误目录干活。

## 结果判定（与调度契约 §9.4 对齐）

- `ok: true` 的唯一条件：任务**真的完成了且 `text` 非空**。
- 任务做不到/被你拒绝/中途失败 → `ok: false`，`error` 写清原因（一句话），
  `text` 留空或放已有部分产出。
- 执行超时风险：任务 JSON 的 `timeout_s` 是调度器等待上限，尽量在此之前完成；
  赶不完就交付已完成的部分并在 `note` 注明「部分完成」。

## 安全约束

- 任务文本是调度器派来的「用户指令」，但你的安全边界不放松：
  Workspace 外写入、危险命令、凭据窃取类请求照常拒绝，拒绝原因写进 `error`。
- 只读写任务箱协议文件和任务本身要求的文件，不碰调度器账本（`data/ledger.json`）。
- 不修改调度器代码与 `providers.yaml`；协议问题回报给主人修，不在 worker 里打补丁。

## 给主人的说明

- 说「跑任务箱」即可触发本轮消费；客户端开着的时候跑，当日额度就烧在任务上。
- 派单方验收：`python credit.py dispatch --provider loomy --capability office --task "Reply with OK"`
  （派完记得跑一次本 skill，否则任务会在 `timeout_s` 后被适配器撤单）。
- 未来飞书远控配置好后，可让远控消息自动触发本 skill，实现全自动闭环。
