"""签到过程的可观测性：控制台实时打印 + 落盘日志。

起因：计划任务跑 `python credit.py checkin` 时只有一个黑框，而 UI 签到动辄
几十秒到几分钟（拉起客户端 / 等窗口 / OCR / 点击 / 复核），中途没有任何输出
就无法判断是卡住还是正常。这个模块提供四件事：

  * note()     —— 带耗时与时间戳的阶段打印，立即 flush，同时写进当日日志
  * stream()   —— 跑子进程并实时转发它的输出（不再被管道缓冲吞掉）
  * LogTailer  —— 提权路径拿不到子进程 stdout（UAC 另起窗口），改 tail 它的日志文件
  * wait_for() —— 等结果文件时定期心跳，顺带把 tail 到的新行打出来

落盘位置 logs/checkin_YYYY-MM-DD.log：黑框跑完就关，事后要能回看。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .paths import LOG_DIR

_START = time.time()
_LOG_PATH: Path | None = None


def init() -> Path:
    """打开当日日志并让控制台输出即时可见、中文不乱码。

    Windows 控制台默认走 GBK，脚本里的中文 print 会抛 UnicodeEncodeError
    或显示成问号；stdout 又是块缓冲的，管道/黑框下要等结束才吐出来。
    """
    global _LOG_PATH
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    if _LOG_PATH is None:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            _LOG_PATH = LOG_DIR / ("checkin_%s.log" % datetime.now().strftime("%Y-%m-%d"))
            _append("=== run %s  cmd=%s ===" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                " ".join(sys.argv),
            ))
        except Exception:
            _LOG_PATH = None
    return _LOG_PATH or LOG_DIR


def _append(line: str) -> None:
    if _LOG_PATH is None:
        return
    try:
        with open(_LOG_PATH, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def elapsed_at(ts: float) -> int:
    """某个时刻相对本次进程启动的秒数（结果汇总时用来标「第几秒落定」）。"""
    return int(ts - _START)


def _stamp() -> str:
    return "[+%4ds %s]" % (int(time.time() - _START), datetime.now().strftime("%H:%M:%S"))


def note(msg: str, label: str = "") -> None:
    """打一行进度。label 用来标来源（哪个账户/哪个子进程）。"""
    if _LOG_PATH is None:
        init()
    head = _stamp() + (" <%s>" % label if label else "")
    line = "%s %s" % (head, msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    _append(line)


def _env() -> dict[str, str]:
    """子进程环境：关掉 Python 输出缓冲，并统一用 UTF-8，否则转发过来的中文是乱码。"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _decode(raw: bytes) -> str:
    """子进程输出按 UTF-8 解，失败退回 GB18030。

    不是所有脚本都设了 [Console]::OutputEncoding=UTF8（启动器那几个就没设），
    硬解 UTF-8 会把中文整行变成替换字符，等于没有进度。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def stream(
    cmd: Sequence[str] | str,
    *,
    label: str,
    timeout: float | None = None,
    cwd: str | None = None,
    shell: bool = False,
    announce: bool = True,
) -> tuple[int | None, str]:
    """跑子进程并实时把它的输出打出来。

    返回 (returncode, 合并输出)。returncode 为 None 表示超时被杀。
    """
    if announce:
        shown = cmd if isinstance(cmd, str) else " ".join(str(c) for c in cmd)
        note("$ %s" % shown, label=label)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=_env(),
        )
    except OSError as exc:
        note("启动子进程失败: %s" % exc, label=label)
        return -1, ""

    lines: list[str] = []

    def _reader() -> None:
        try:
            for raw in proc.stdout or []:
                line = _decode(raw).rstrip("\r\n")
                lines.append(line)
                note(line, label=label)
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    deadline = time.time() + timeout if timeout else None
    timed_out = False
    while proc.poll() is None:
        if deadline and time.time() > deadline:
            timed_out = True
            # shell=True 时直接子进程是 cmd.exe，只 kill 它的话，真正的
            # python / powershell 及其拉起的客户端会继续搬窗口、点击。
            # Windows 上用 taskkill /T 收掉整棵树，其它平台退回 kill()。
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=20)
                except (subprocess.SubprocessError, OSError):
                    proc.kill()
            else:
                proc.kill()
            note("子进程超时（%ss），已终止整棵进程树" % int(timeout or 0), label=label)
            break
        time.sleep(0.4)
    t.join(timeout=5)
    try:
        if proc.stdout:
            proc.stdout.close()
    except Exception:
        pass
    return (None if timed_out else proc.returncode), "\n".join(lines)


class LogTailer:
    """增量读取另一个进程写的日志文件（提权路径拿不到它的 stdout）。

    起点取构造时的文件大小，所以只看本次运行新增的行；文件被截断重写时
    自动从头读。
    """

    def __init__(self, path: str | Path, label: str) -> None:
        self.path = Path(path)
        self.label = label
        self.pos = 0
        try:
            self.pos = self.path.stat().st_size if self.path.is_file() else 0
        except OSError:
            self.pos = 0

    def poll(self) -> int:
        try:
            if not self.path.is_file():
                return 0
            size = self.path.stat().st_size
            if size < self.pos:
                self.pos = 0
            if size == self.pos:
                return 0
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                data = fh.read(size - self.pos)
            self.pos = size
        except OSError:
            return 0
        count = 0
        for line in data.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                note(line.rstrip(), label=self.label)
                count += 1
        return count


def wait_for(
    check: Callable[[], Any],
    *,
    timeout: float,
    label: str,
    tailer: LogTailer | None = None,
    interval: float = 2.0,
    heartbeat: float = 20.0,
) -> tuple[bool, Any]:
    """轮询 check()，期间 tail 日志并定期心跳。返回 (是否等到, payload)。"""
    deadline = time.time() + timeout
    last_hb = 0.0
    while True:
        if tailer:
            tailer.poll()
        try:
            payload = check()
        except Exception:
            payload = None
        if payload is not None:
            return True, payload
        now = time.time()
        if now - last_hb >= heartbeat:
            note("等待 %s … 已等 %ds / 上限 %ds" % (label, int(now - (deadline - timeout)), int(timeout)), label=label)
            last_hb = now
        if now >= deadline:
            return False, None
        time.sleep(interval)
