from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from ...paths import ROOT
from ..base import Preflight, Provider, Result, Task

# 任务箱目录布局（协议见 skill/loomy-taskbox-worker/SKILL.md）：
#   pending/<id>.json   适配器投递的任务，等 worker 认领
#   running/<id>.json   worker 已认领、执行中
#   results/<id>.json   worker 写回的结果，适配器读走后即删
#   worker.heartbeat    worker 每次运行 touch，preflight 用它判断 worker 活性
# id 都是 sha1(text|uuid4)[:12]，任务正文属运行期状态，data/loomy-taskbox/ 已入 .gitignore。


class LoomyProvider(Provider):
    """讯飞 Loomy（任务箱通道）。

    Loomy 没有官方 CLI、没有本地网关，官方远程入口（IM 远控）尚未配置，
    所以走本机任务箱：适配器投递任务文件，Loomy 侧的 worker
    （skill「跑任务箱」或每日定时任务）认领执行并写回结果。

    约束来自台账策略（catalog.yaml 的 loomy 条目）：
    - never_auto：绝不替主人启动 Loomy 客户端；进程不在就如实报不可用，
      让调度器回退到下一个提供者——额度本来就该「用时再开」。
    - 余额只在客户端 UI 展示、无官方 API：supports_balance = False，
      调度器会标记 balance_unknown 并按失败回退，不猜、不伪造。
    """

    name = "loomy"
    capabilities = {"office", "search", "text", "commit", "explain"}
    supports_balance = False

    # ---------- 配置 ----------

    @property
    def box(self) -> Path:
        """任务箱根目录。默认仓库内 data/loomy-taskbox，可用 taskbox 配置覆盖。"""
        raw = self.config.get("taskbox") or (ROOT / "data" / "loomy-taskbox")
        path = Path(str(raw))
        if not path.is_absolute():
            path = ROOT / path
        return path

    @property
    def poll_interval_s(self) -> float:
        return float(self.config.get("poll_interval_s") or 2)

    @property
    def heartbeat_max_age_s(self) -> float:
        # 必须 ≥ 3 倍唤醒间隔：唤醒源每 wake_interval_s 触发一次，留两次失败的余量。
        return float(self.config.get("heartbeat_max_age_s") or 900)

    @property
    def wake_interval_s(self) -> float:
        """外部唤醒源（scripts/loomy-wake.py + Windows 计划任务）的触发间隔。"""
        return float(self.config.get("wake_interval_s") or 300)

    @property
    def wake_state_path(self) -> Path:
        raw = self.config.get("wake_state") or (ROOT / "data" / "loomy-wake-state.json")
        path = Path(str(raw))
        return path if path.is_absolute() else ROOT / path

    @property
    def process_names(self) -> list[str]:
        raw = self.config.get("process_names") or ["Loomy"]
        return [str(n) for n in raw] if isinstance(raw, list) else [str(raw)]

    # ---------- 任务箱基础 ----------

    def _ensure_dirs(self) -> Path:
        self.box.mkdir(parents=True, exist_ok=True)
        for sub in ("pending", "running", "results"):
            (self.box / sub).mkdir(exist_ok=True)
        return self.box

    def _atomic_json(self, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _process_state(self) -> tuple[bool, str]:
        """(客户端在跑?, 说明)。tasklist 不可用时如实报检查失败，不猜。"""
        names = [n.lower() for n in self.process_names]
        try:
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"进程检查失败（tasklist 不可用: {exc}），按不可用处理"
        listing = proc.stdout.lower()
        for n in names:
            if f'"{n}.exe"' in listing:
                return True, ""
        return False, ""

    def _heartbeat_age_s(self) -> float | None:
        """worker 心跳距今秒数；从未运行过返回 None。"""
        hb = self.box / "worker.heartbeat"
        try:
            return time.time() - hb.stat().st_mtime
        except OSError:
            return None

    def _pending_count(self) -> int:
        try:
            return len(list((self.box / "pending").glob("*.json")))
        except OSError:
            return 0

    def _wake_state(self) -> dict | None:
        """读唤醒源状态（scripts/loomy-wake.py 写）；缺文件或坏 JSON 返回 None。"""
        try:
            data = json.loads(self.wake_state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _wake_note(self, now: float | None = None) -> str:
        """一行说明唤醒源状态与下次消费时间，让人分清「真不可用」和「还没到点」。"""
        now = now if now is not None else time.time()
        state = self._wake_state()
        if not state:
            return "唤醒源状态未知（计划任务未注册或从未运行），只能靠 Loomy 每日定时兜底"
        status = str(state.get("status") or "?")
        last_ok = state.get("last_ok_at")
        if not last_ok:
            return f"唤醒源状态 {status}（无成功记录），下次消费时间不可估算"
        try:
            last_ok_ts = datetime.fromisoformat(str(last_ok)).timestamp()
        except ValueError:
            return f"唤醒源状态 {status}（last_ok_at 无法解析）"
        next_ts = last_ok_ts + self.wake_interval_s
        next_at = datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")
        if next_ts <= now:
            return f"唤醒源每 {int(self.wake_interval_s)}s 触发，下次唤醒已到期（应约 {next_at}），可能卡住"
        return f"唤醒源每 {int(self.wake_interval_s)}s 触发，下次消费约 {next_at}"

    # ---------- 契约方法 ----------

    def preflight(self, task: Task) -> Preflight:
        try:
            self._ensure_dirs()
        except OSError as exc:
            return Preflight(available=False, reason=f"任务箱目录不可用: {exc}")

        running, detail = self._process_state()
        if not running:
            reason = detail or (
                "Loomy 客户端未运行（台账策略 never_auto：不自动启动，主人打开客户端后本提供者自动可用）"
            )
            return Preflight(available=False, reason=reason)

        age = self._heartbeat_age_s()
        if age is None:
            return Preflight(
                available=False,
                reason=(
                    "taskbox worker 从未运行过——在 Loomy 会话里说「跑任务箱」激活，"
                    f"或确认唤醒源计划任务已注册（{self._wake_note()}）"
                ),
            )
        if age > self.heartbeat_max_age_s:
            return Preflight(
                available=False,
                reason=(
                    f"worker 心跳已陈旧（距上次 {int(age)}s > 阈值 {int(self.heartbeat_max_age_s)}s），"
                    f"现在派单大概率没人消费会超时——先检查唤醒源：{self._wake_note()}"
                ),
            )

        backlog = self._pending_count()
        note = f"worker 心跳 {int(age)}s 前；pending 积压 {backlog}；{self._wake_note()}"
        if backlog:
            note += "（worker 下次运行会先消费积压）"
        return Preflight(available=True, balance_note=note)

    def read_balance(self) -> tuple[int | None, str]:
        return None, "Loomy 无官方余额 API（余额只在客户端 UI 展示），不猜不伪造"

    def dispatch(self, task: Task) -> Result:
        started = time.time()
        try:
            box = self._ensure_dirs()
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"任务箱不可写: {exc}",
                          duration_s=time.time() - started, route="taskbox")

        task_id = hashlib.sha1(f"{task.text}|{uuid.uuid4()}".encode("utf-8")).hexdigest()[:12]
        payload = {
            "id": task_id,
            "at": datetime.now().isoformat(timespec="seconds"),
            "capability": task.capability,
            "text": task.text,
            "cwd": str(task.cwd) if task.cwd else None,
            "timeout_s": task.timeout_s,
            "caller": str(self.config.get("caller") or "agent-credit"),
        }
        pending_file = box / "pending" / f"{task_id}.json"
        result_file = box / "results" / f"{task_id}.json"
        try:
            self._atomic_json(pending_file, payload)
        except OSError as exc:
            return Result(ok=False, exit_code=126, note=f"投递任务失败: {exc}",
                          duration_s=time.time() - started, route="taskbox")

        # 轮询等 worker 写回结果。worker 的写回是原子替换，读到就是完整 JSON。
        deadline = started + task.timeout_s
        while time.time() < deadline:
            if result_file.exists():
                try:
                    # utf-8-sig：worker 若用 PowerShell 5 写回执会带 BOM（Set-Content -Encoding UTF8），
                    # 用 utf-8 会直接 JSONDecodeError，表现为假超时。
                    data = json.loads(result_file.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(self.poll_interval_s)
                    continue
                try:
                    result_file.unlink(missing_ok=True)
                except OSError:
                    pass  # 读都读到了，删不掉就留给 worker 的孤儿清理
                ok = bool(data.get("ok"))
                text = str(data.get("text") or "").strip()
                worker_note = str(data.get("note") or "")
                error = str(data.get("error") or "")
                ok = ok and bool(text)  # 契约 §9.4：ok 只在真有正文时为 True
                note = f"taskbox {task_id}" + (f", worker {data.get('elapsed_s')}s" if data.get("elapsed_s") else "")
                if worker_note:
                    note += f"; {worker_note}"
                raw_tail = ""
                if not ok:
                    raw_tail = (error or "worker 上报 ok=false（无正文）")[:400]
                    note = f"taskbox {task_id} worker 失败: {error or '无正文'}"
                return Result(
                    ok=ok,
                    exit_code=0 if ok else 1,
                    text=text,
                    duration_s=time.time() - started,
                    note=note,
                    raw_tail=raw_tail,
                    route="taskbox",
                )
            time.sleep(self.poll_interval_s)

        # 超时：还在 pending 就撤单（没人认领过）；已被认领就留给 worker 跑完，
        # 结果文件成为孤儿，由 worker 的 24h 清理兜底。
        waited = time.time() - started
        try:
            if pending_file.exists():
                pending_file.unlink(missing_ok=True)
                stuck = "任务已撤单（worker 未认领）"
            elif (box / "running" / f"{task_id}.json").exists():
                stuck = "任务已被 worker 认领、仍在执行，结果将留在任务箱不被读取"
            else:
                stuck = "任务状态不明（既不在 pending 也不在 running）"
        except OSError as exc:
            stuck = f"撤单时出错: {exc}"
        return Result(
            ok=False,
            exit_code=124,
            note=f"taskbox 超时 {task.timeout_s}s：{stuck}",
            duration_s=waited,
            raw_tail=payload["text"][:400],
            route="taskbox",
        )
