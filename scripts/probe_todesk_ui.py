r"""探测某个 Tauri / WebView2 应用的 UIA 控件树，判断能不能用脚本定位控件。

只读：枚举窗口与子控件，不点击、不输入、不改任何状态。

为什么需要它：Tauri / WebView2 应用常把整个界面塞进一个 "Web 内容" Pane，
UIA 里拿不到 Edit / Button，于是"抓控件文本"或"按控件名点按钮"的方案直接作废，
只能退到全局快捷键 + 剪贴板 + 结果文件回传（ToDesk 适配器就是这么定的）。

用法：
    python scripts\probe_todesk_ui.py            # 默认标题含 ToDesk，深度 3
    python scripts\probe_todesk_ui.py 2 微信      # 深度 2，标题含"微信"

依赖：pywinauto。目前只有 ToDesk AI 自带的 agent-runtime python 装了它：
    C:\Users\<user>\AppData\Local\ToDesk AI\agent-runtime\current\python\python.exe
其它解释器先 `pip install pywinauto`。
"""
from __future__ import annotations

import sys

from pywinauto import Desktop


def walk(ctrl, depth: int, max_depth: int, out: list[str], prefix: str = "") -> None:
    if depth > max_depth:
        return
    try:
        children = ctrl.children()
    except Exception as exc:  # noqa: BLE001 - 枚举失败不该中断整棵树
        out.append(f"{prefix}[children failed: {exc}]")
        return
    for child in children:
        try:
            name = child.window_text()
            ctype = child.friendly_class_name()
            auto = child.automation_id()
        except Exception as exc:  # noqa: BLE001
            out.append(f"{prefix}[?] {exc}")
            continue
        out.append(f"{prefix}{ctype!r} auto_id={(auto or '')[:40]!r} name={name[:60]!r}")
        walk(child, depth + 1, max_depth, out, prefix + "    ")


def main(argv: list[str]) -> int:
    max_depth = int(argv[1]) if len(argv) > 1 else 3
    keyword = argv[2] if len(argv) > 2 else "ToDesk"
    wins = [w for w in Desktop(backend="uia").windows() if keyword in (w.window_text() or "")]
    print(f"标题含 {keyword!r} 的窗口 {len(wins)} 个")
    for w in wins:
        try:
            print(
                f"\n== {w.window_text()!r} class={w.class_name()!r} "
                f"rect={w.rectangle()} visible={w.is_visible()} enabled={w.is_enabled()}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"\n== [window intro failed: {exc}]")
            continue
        lines: list[str] = []
        walk(w, 1, max_depth, lines)
        print("\n".join(lines[:400]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))