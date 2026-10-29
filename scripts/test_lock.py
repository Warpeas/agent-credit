#!/usr/bin/env python3
"""签到防撞锁回归：Python 互斥、PS 互斥、链路放行、CLI 退出码。

守卫 2026-10-29 的漏签场景：23:58 的链路跨过零点还在跑，00:00 的触发不能再
并发开一遍客户端；同时手动 checkin 撞上时要说清楚而不是静默排队。

用法：python scripts/test_lock.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit import lock  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="agent-credit-lock-"))
lock_path = tmp / "checkin.lock"

bad = 0


def check(label: str, got, expect) -> None:
    global bad
    ok = got == expect
    if not ok:
        bad += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}"
          + ("" if ok else f"\n      got:    {got!r}\n      expect: {expect!r}"))


# ---------- 同一进程内互斥 ----------
first = lock.acquire(lock_path)
check("第一次抢锁成功", bool(first), True)
check("持锁时第二次抢不到", lock.acquire(lock_path, wait=0), None)
check("带 wait 也超时返回", lock.acquire(lock_path, wait=0.6), None)

# ---------- 释放后可再抢 ----------
first.release()
second = lock.acquire(lock_path)
check("释放后能重新抢到", bool(second), True)
second.release()

# ---------- 链路子进程直接放行 ----------
os.environ[lock.HOLD_ENV] = "1"
check("链路子进程不重复抢锁", lock.acquire_for_checkin(), None)
os.environ.pop(lock.HOLD_ENV, None)

# ---------- 与 PowerShell 的 FileShare.None 互斥 ----------
ps_hold = (
    "$s=[System.IO.File]::Open('%s','OpenOrCreate','ReadWrite','None'); "
    "Start-Sleep -Seconds 3; $s.Close()" % str(lock_path)
)
proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_hold],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.8)
check("PowerShell 持锁时 Python 抢不到", lock.acquire(lock_path, wait=0), None)
proc.wait(timeout=20)
check("PowerShell 释放后 Python 能抢到", bool(lock.acquire(lock_path)), True)
# 上一行拿到锁的句柄随对象被回收前先显式释放，避免下一步被自己挡住。

# ---------- Python 持锁时 PowerShell 打不开 ----------
held = lock.acquire(lock_path)
check("重抢成功（前置条件）", bool(held), True)
ps_try = (
    "try { $s=[System.IO.File]::Open('%s','OpenOrCreate','ReadWrite','None'); "
    "'opened'; $s.Close() } catch { 'blocked' }" % str(lock_path)
)
res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_try],
                     capture_output=True, text=True, timeout=20)
check("Python 持锁时 PS 被拒绝", "blocked" in res.stdout, True)
held.release()

# ---------- CLI：撞锁时退出码 4，且不碰账本 ----------
hold = lock.acquire(lock_path)
check("CLI 前置：锁在主进程手里", bool(hold), True)
env = os.environ.copy()
env.pop(lock.HOLD_ENV, None)
env[lock.PATH_ENV] = str(lock_path)
data_dir = tmp / "data"
env["AGENT_CREDIT_DATA"] = str(data_dir)
cli = subprocess.run([sys.executable, "credit.py", "checkin", "--only", "dumate"],
                     cwd=str(ROOT), env=env, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=60)
check("CLI 撞锁退出码 4", cli.returncode, 4)
check("CLI 提示另一个签到在跑", "另一个签到正在运行" in (cli.stderr or ""), True)
check("CLI 没写账本", (data_dir / "ledger.json").exists(), False)
hold.release()

print()
print("全部通过" if not bad else f"{bad} 个失败")
sys.exit(1 if bad else 0)
