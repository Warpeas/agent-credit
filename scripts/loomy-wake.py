#!/usr/bin/env python3
"""Loomy 任务箱唤醒源：由 Windows 计划任务每 5 分钟调一次。

为什么需要它：Loomy 官方定时任务只能按天/周触发（userData/schedule-tasks.json 里
frequency 只有 daily/weekly/一次性），没有分钟级轮询；适配器派单最多等 600s，
等不到它的日级兜底。这个脚本复用 Loomy 自己写出来的调度桥
（userData/schedule-dispatch-bridge.env 里的 URL + token），把已有的
「loomy任务箱兜底」任务再触发一次——等效于给 Loomy 装了个分钟级触发器，
Loomy 侧零改动。

状态：
  ok          POST 2xx，Loomy 会起一轮 worker（箱空也算成功）
  skip        距上次成功唤醒不足 COOLDOWN_S，跳过（避免和 09:30 兜底/手动触发重叠）
  launched    桥不可达，按 Loomy 官方脚本的做法回落启动 Loomy.exe --scheduled-dispatch
  failed      env 缺失、token 被拒、回落也失败

落盘：
  logs/loomy-wake.log          一行一条，>512KB 轮转 .1
  data/loomy-wake-state.json   最近状态 + last_ok_at + next_at（适配器 preflight 读它）

不做的事：不判断箱里有没有单（空箱也触发，保持 worker 心跳新鲜），
不读写任务箱本身，不碰 ledger（唤醒不是派单）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "logs" / "loomy-wake.log"
STATE_PATH = ROOT / "data" / "loomy-wake-state.json"
LOCK_PATH = ROOT / "data" / "loomy-wake.lock"

DEFAULT_TASK_ID = "schedule-1794738990729-c63dj7g"
LOOMY_EXE = Path(r"C:\Program Files\Loomy\Loomy.exe")
BRIDGE_GLOB = "C:/Users/Public/Loomy/*/userData/schedule-dispatch-bridge.env"

COOLDOWN_S = 120          # 两次成功唤醒的最小间隔；与 09:30 兜底撞车时靠它退让
LOCK_STALE_S = 600        # 锁文件超过 10 分钟视为上次进程异常退出
HTTP_TIMEOUT_S = 8
RETRY_DELAYS = (0, 2, 5)  # 共 3 次尝试
LOG_MAX_BYTES = 512 * 1024


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            rotated = LOG_PATH.with_suffix(".log.1")
            try:
                rotated.unlink(missing_ok=True)
            except OSError:
                pass
            os.replace(LOG_PATH, rotated)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def read_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        log(f"state_write_failed {exc}")


def find_bridge_env() -> Path | None:
    """Loomy 的实例目录带 hash（C:/Users/Public/Loomy/<hash>/），取最新写的那份。"""
    candidates = [Path(p) for p in Path("C:/Users/Public/Loomy").glob("*/userData/schedule-dispatch-bridge.env")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_bridge(path: Path) -> tuple[str | None, str | None]:
    url = token = None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = raw.strip().partition("=")
        if not sep:
            continue
        if key == "LOOMY_SCHEDULE_DISPATCH_URL":
            url = value
        elif key == "LOOMY_SCHEDULE_DISPATCH_TOKEN":
            token = value
    return url, token


def post_bridge(url: str, token: str, task_id: str) -> tuple[bool, str]:
    """返回 (成功?, 说明)。只对连接级错误返回失败让上层回落启动客户端。"""
    # source 必须是 manual-run：schedule-task-service 只有在 manual-run 时
    # scheduleSlotKey 才为 null；用其它 source 会按「当天 09:30 那个排程点」领槽，
    # 当天第一次唤醒后其余唤醒全被判 schedule-slot-already-claimed 静默跳过
    # （2026-11-15 实测：23:18 成功，23:23、23:26 的 POST 返回 200 但根本没跑）。
    payload = json.dumps(
        {"taskId": task_id, "source": "manual-run"}, ensure_ascii=False
    ).encode("utf-8")
    last = ""
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                body = resp.read(4096).decode("utf-8", "replace")
                tag = ""
                try:
                    parsed = json.loads(body)
                except ValueError:
                    parsed = {}
                if parsed.get("success") is False:
                    return False, f"http={resp.status} error={parsed.get('error')}"
                if parsed.get("queued"):
                    tag = " queued"
                return True, f"http={resp.status}{tag} attempt={attempt}"
        except urllib.error.HTTPError as exc:
            last = f"http={exc.code} attempt={attempt}"
            if exc.code < 500:
                return False, last  # 4xx 重试无用（token 失效 / 任务 id 不存在）
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"connect_failed attempt={attempt}: {exc}"
    return False, last


def launch_loomy(task_id: str) -> tuple[bool, str]:
    if not LOOMY_EXE.exists():
        return False, f"loomy_exe_missing {LOOMY_EXE}"
    try:
        subprocess.Popen(
            [str(LOOMY_EXE), "--scheduled-dispatch", task_id],
            cwd=str(LOOMY_EXE.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return False, f"launch_failed {exc}"
    return True, "launched Loomy.exe --scheduled-dispatch"


def acquire_lock() -> bool:
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
        except OSError:
            return False
        if age < LOCK_STALE_S:
            return False
        try:
            LOCK_PATH.unlink(missing_ok=True)
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    except OSError:
        return False
    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)
    return True


def release_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def main(argv: list[str]) -> int:
    task_id = DEFAULT_TASK_ID
    interval_s = 300.0
    for i, arg in enumerate(argv):
        if arg == "--task-id" and i + 1 < len(argv):
            task_id = argv[i + 1]
        elif arg == "--interval-s" and i + 1 < len(argv):
            interval_s = float(argv[i + 1])

    state = read_state()
    now = time.time()

    if not acquire_lock():
        next_at = datetime.fromtimestamp(now + interval_s).isoformat(timespec="seconds")
        write_state({**state, "at": _now_iso(), "status": "skip", "detail": "busy", "next_at": next_at})
        log("skip busy（另一个唤醒进程在跑）")
        return 0

    try:
        last_ok = state.get("last_ok_at")
        if last_ok:
            try:
                age = now - datetime.fromisoformat(str(last_ok)).timestamp()
            except ValueError:
                age = COOLDOWN_S
            if age < COOLDOWN_S:
                next_at = datetime.fromtimestamp(now + (COOLDOWN_S - age)).isoformat(timespec="seconds")
                write_state({**state, "at": _now_iso(), "status": "skip",
                             "detail": f"cooldown {int(age)}s<{COOLDOWN_S}s", "next_at": next_at})
                log(f"skip cooldown {int(age)}s/{COOLDOWN_S}s（上次唤醒刚成功，可能是 09:30 兜底）")
                return 0

        env_path = find_bridge_env()
        if env_path is None:
            write_state({**state, "at": _now_iso(), "status": "failed",
                         "detail": "bridge env not found"})
            log("failed bridge_env_missing（C:/Users/Public/Loomy/*/userData/ 下没找到调度桥配置）")
            return 1

        url, token = load_bridge(env_path)
        if not url or not token:
            write_state({**state, "at": _now_iso(), "status": "failed",
                         "detail": "bridge env incomplete"})
            log("failed bridge_env_incomplete（缺 URL 或 TOKEN）")
            return 1

        ok, detail = post_bridge(url, token, task_id)
        status = "ok"
        if not ok:
            launched, launch_detail = launch_loomy(task_id)
            status = "launched" if launched else "failed"
            detail = f"{detail}; {launch_detail}"

        next_at = datetime.fromtimestamp(now + interval_s).isoformat(timespec="seconds")
        new_state = {
            **state,
            "at": _now_iso(),
            "status": status,
            "detail": detail,
            "task_id": task_id,
            "interval_s": interval_s,
            "next_at": next_at,
        }
        if status == "ok":
            new_state["last_ok_at"] = new_state["at"]
        write_state(new_state)
        log(f"{status} task={task_id} {detail}")
        return 0 if status in ("ok", "launched") else 1
    finally:
        release_lock()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass
    raise SystemExit(main(sys.argv[1:]))
