from __future__ import annotations

from .apps import find_exe
from .catalog import accounts


def report() -> list[dict]:
    rows = []
    for acc in accounts():
        exe = find_exe(acc["id"])
        command = (acc.get("command") or "").strip()
        mode = acc.get("claim_mode")
        if command:
            adapter = f"external: {command}"
        elif mode == "ui":
            adapter = "UI 自动化（本机客户端）"
        elif mode == "manual":
            adapter = "手签"
        elif mode == "external":
            adapter = "external 未配 command → 手签"
        else:
            adapter = str(mode)
        rows.append(
            {
                "id": acc["id"],
                "name": acc["name"],
                "policy": acc.get("claim_policy"),
                "adapter": adapter,
                "exe": str(exe) if exe else "",
                "installed": bool(exe),
            }
        )
    return rows


def format_report(rows: list[dict]) -> str:
    lines = ["探测本机安装与适配器：", ""]
    for row in rows:
        flag = "已装" if row["installed"] else "未装"
        lines.append(f"{row['id']:<18} {flag}  {row['adapter']}")
        if row["exe"]:
            lines.append(f"{'':18} {row['exe']}")
    lines.append("")
    lines.append("说明：claim_mode=ui 的每日必签会启动已装客户端并尝试点「签到」。")
    lines.append("      找不到按钮则 pending，不入账。当日清零软件不会被唤醒。")
    return "\n".join(lines)
