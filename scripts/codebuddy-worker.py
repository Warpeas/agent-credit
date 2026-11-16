"""codebuddy 队列 worker：由计划任务在**当前用户会话**（非沙箱）里拉起。

为什么不在派单进程里直接起 codebuddy：受限沙箱里它写不了
%USERPROFILE%\\.codebuddy，2~3 秒就退出。这个脚本由任务计划程序执行，
继承的是正常用户会话，家目录可写。

协议（与 doc/ledger-lock-and-scheduled-dispatch.md §2 一致）：
  data/codebuddy-taskbox/pending/<id>.json   等待认领（适配器写入）
  data/codebuddy-taskbox/running/<id>.json   已认领、执行中
  data/codebuddy-taskbox/results/<id>.json   结果，适配器读走后删除

一次运行只认领一单（IgnoreNew 保证同时只有一个实例），没有待办就立刻退出。
worker 不写账本：账本由派单的前台进程持锁写入，避免两个写者。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_credit.dispatch.adapters._cli_json import parse_result_json, parse_usage_detail  # noqa: E402
from agent_credit.dispatch.base import usage_failed  # noqa: E402

BOX = Path(os.environ.get("AGENT_CREDIT_CODEBUDDY_BOX") or (ROOT / "data" / "codebuddy-taskbox"))
LOG_PATH = ROOT / "logs" / "codebuddy-worker.log"
ORPHAN_AGE_S = 86400  # running/results 超过 24h 视为孤儿

_STARTUP_MARKERS = ("enoent", "eperm", "eacces")


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [pid {os.getpid()}] {message}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _first_line(raw: str) -> str:
    for line in (raw or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def run_task(task: dict) -> dict:
    binary = str(task.get("binary") or "codebuddy")
    path = shutil.which(binary) or binary
    cmd = [
        path,
        "-p",
        " ".join(str(task.get("text") or "").splitlines()),
        "--output-format",
        "json",
        "--permission-mode",
        str(task.get("permission_mode") or "bypassPermissions"),
    ]
    # 派单主题由适配器随 payload 传下来（worker 不自己读仓库文件，避免两边内容漂移）；
    # 与直连一致，必须折叠成单行再交给 .cmd shim。
    theme = " ".join(str(task.get("append_system_prompt") or "").split())
    if theme:
        cmd += ["--append-system-prompt", theme]
    timeout = float(task.get("timeout_s") or 600)
    cwd = task.get("cwd") or str(ROOT)
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", cwd=str(cwd),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "text": "", "note": f"超时 {timeout}s",
                "raw_tail": "", "elapsed_s": round(time.time() - started, 1),
                "usage": usage_failed(f"超时 {timeout}s，未取得用量")}
    except OSError as exc:
        return {"ok": False, "exit_code": 126, "text": "", "note": f"启动失败: {exc}",
                "raw_tail": "", "elapsed_s": round(time.time() - started, 1),
                "usage": usage_failed(f"未执行：启动失败（{exc}）")}

    text, error = parse_result_json(proc.stdout)
    haystack = f"{proc.stderr}\n{error}".lower()
    startup_fail = any(marker in haystack for marker in _STARTUP_MARKERS)
    if startup_fail:
        if not error:
            error = _first_line(proc.stderr or text) or "启动期写入失败（ENOENT/EPERM）"
        text = ""
    elif not error and not text.strip():
        error = "无正文"
    ok = proc.returncode == 0 and bool(text) and not error
    if ok:
        exit_code = 0
    elif proc.returncode != 0:
        exit_code = proc.returncode
    elif startup_fail:
        exit_code = 126
    else:
        exit_code = 1
    note = f"exit={proc.returncode}" + (f", {error[:200]}" if error else "")
    return {
        "ok": ok,
        "exit_code": exit_code,
        "text": text,
        "note": note,
        "raw_tail": (proc.stderr or proc.stdout or "")[-400:],
        "elapsed_s": round(time.time() - started, 1),
        # 用量在 worker 侧解析后随结果回传；拿不到也是 status=failed 的字典。
        "usage": parse_usage_detail(proc.stdout),
    }


def cleanup_orphans() -> None:
    now = time.time()
    for sub in ("running", "results"):
        for path in (BOX / sub).glob("*.json"):
            try:
                if now - path.stat().st_mtime > ORPHAN_AGE_S:
                    path.unlink()
                    log(f"清理孤儿 {sub}/{path.name}")
            except OSError:
                pass


def main() -> int:
    for sub in ("pending", "running", "results"):
        (BOX / sub).mkdir(parents=True, exist_ok=True)
    cleanup_orphans()

    pending = sorted(
        (BOX / "pending").glob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not pending:
        log("无待办，退出")
        return 0

    src = pending[0]
    running = BOX / "running" / src.name
    try:
        os.replace(src, running)  # 原子认领：并发实例只有一个能成功
    except OSError:
        log(f"任务 {src.name} 已被其它实例认领")
        return 0

    task_id = src.stem
    try:
        task = json.loads(running.read_text(encoding="utf-8"))
        task_id = str(task.get("id") or task_id)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "exit_code": 1, "text": "",
                  "note": f"任务文件损坏: {exc}", "raw_tail": "", "elapsed_s": 0.0,
                  "usage": usage_failed(f"未执行：任务文件损坏（{exc}）")}
    else:
        log(f"执行 {task_id} capability={task.get('capability')} timeout={task.get('timeout_s')}")
        result = run_task(task)

    result.update({
        "id": task_id,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "worker_pid": os.getpid(),
    })
    target = BOX / "results" / f"{task_id}.json"
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        log(f"写回结果失败: {exc}")
        return 2
    try:
        running.unlink(missing_ok=True)
    except OSError:
        pass
    log(f"完成 {task_id}: ok={result.get('ok')} exit={result.get('exit_code')} "
        f"dur={result.get('elapsed_s')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
