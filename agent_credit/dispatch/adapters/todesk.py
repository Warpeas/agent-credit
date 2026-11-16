from __future__ import annotations

import ctypes
import os
import subprocess
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from ..base import Preflight, Provider, Result, Task, usage_failed
from ...paths import DATA_DIR

# ToDesk AI 的品牌里带空格，窗口标题与进程名都要精确匹配：
# 悬浮球窗口的标题是「ToDesk AI 悬浮球」，主窗口才是「ToDesk AI」。
_WINDOW_CLASS = "Tauri Window"
_WINDOW_TITLE = "ToDesk AI"
_IMAGE_NAME = "ToDeskAI.exe"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

_VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B,
    "escape": 0x1B, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}

_user32 = ctypes.windll.user32 if os.name == "nt" else None
_kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None

# 64 位句柄必须显式声明 restype，否则被截断成 32 位 int，GlobalLock 返回野指针。
if os.name == "nt":
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalFree.restype = wintypes.HANDLE
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]


# ---------- 无依赖的键鼠/剪贴板（不用 pyautogui，省掉一条 pip 依赖） ----------


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _vk(key: str) -> int:
    name = key.strip().lower()
    if name in _VK:
        return _VK[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    raise ValueError(f"不认识的按键: {key}")


def _key_down_up(code: int, up: bool) -> None:
    event = _INPUT(type=INPUT_KEYBOARD)
    event.ki.wVk = code
    event.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    _user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))


def send_hotkey(combo: str) -> None:
    """按一个组合键，例如 alt+space / ctrl+alt+n / enter / ctrl+v。"""
    keys = [_vk(part) for part in combo.split("+") if part.strip()]
    if not keys:
        raise ValueError("空热键")
    for code in keys[:-1]:
        _key_down_up(code, up=False)
        time.sleep(0.02)
    _key_down_up(keys[-1], up=False)
    time.sleep(0.04)
    _key_down_up(keys[-1], up=True)
    for code in reversed(keys[:-1]):
        time.sleep(0.02)
        _key_down_up(code, up=True)
    time.sleep(0.06)


def clipboard_set(text: str) -> None:
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not _user32.OpenClipboard(None):
        raise OSError("OpenClipboard 失败（剪贴板被其它进程占用）")
    try:
        _user32.EmptyClipboard()
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise OSError("GlobalAlloc 失败")
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            _kernel32.GlobalFree(handle)
            raise OSError("GlobalLock 失败")
        ctypes.memmove(ptr, data, len(data))
        _kernel32.GlobalUnlock(handle)
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            _kernel32.GlobalFree(handle)
            raise OSError("SetClipboardData 失败")
    finally:
        _user32.CloseClipboard()


def clipboard_get() -> str:
    if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return ""
    if not _user32.OpenClipboard(None):
        return ""
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def _idle_seconds() -> float:
    """距离上一次键鼠输入过了多少秒；取不到就返回 0（按「刚动过」处理，宁可不派单）。"""
    if os.name != "nt":
        return 0.0
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not _user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return max(0.0, (_kernel32.GetTickCount() - info.dwTime) / 1000.0)
    except (AttributeError, OSError):
        return 0.0


def _foreground_title() -> str:
    if os.name != "nt":
        return ""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        buffer = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(hwnd, buffer, 512)
        return buffer.value
    except (AttributeError, OSError):
        return ""


def _main_window_exists() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(_user32.FindWindowW(_WINDOW_CLASS, _WINDOW_TITLE))
    except (AttributeError, OSError):
        return False


def _process_running() -> bool:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {_IMAGE_NAME}", "/NH"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return _IMAGE_NAME.lower() in (proc.stdout or "").lower()


class ToDeskProvider(Provider):
    """ToDesk AI 桌面客户端（GUI 键鼠通道）。

    为什么不是 CLI/HTTP：客户端没有对外接口（rag 知识库里也没有开放平台），
    内部 127.0.0.1:8909 只回 404（私有 RPC），凭据在 Program Files 的 config.ini 里——
    复用它等于同时踩契约 §9.1（不碰他人凭据）和 §9.2（不绕过鉴权），所以只能走界面。

    两条硬限制决定了实现方式：
    1. 它是 Tauri/WebView2 应用，UIA 只暴露一个空的「Web 内容」Pane，定位不到输入框、
       也读不到回答正文（2026-11-16 实测）。因此靠官方全局快捷键 + 剪贴板输入，
       靠「让 AI 把结果写到文件」回传，不解析界面。
    2. 单实例、会抢焦点。所以 preflight 做空闲检查，dispatch 全程校验前台窗口标题，
       被用户切走就中止——宁可失败回退，也不把字打到别人的窗口里。

    额度：按积分计费（catalog.yaml 记 500/天、当天过期），客户端不返回 token/credits，
    也没有查询接口，所以 supports_balance=False、usage 一律 failed（契约 §7.2 允许）。
    """

    name = "todesk"
    capabilities = {"text", "office", "explain"}
    supports_balance = False

    # ---------- 配置 ----------

    def _cfg_num(self, key: str, default, cast=int):
        """0 是有效值（例如 require_idle_s: 0 表示关闭空闲保护），不能用 or 兜底。"""
        raw = self.config.get(key)
        if raw is None or raw == "":
            return default
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default

    @property
    def exe(self) -> Path:
        raw = self.config.get("exe") or r"C:\Program Files\ToDesk AI\ToDeskAI.exe"
        return Path(str(raw))

    @property
    def taskbox(self) -> Path:
        raw = self.config.get("taskbox")
        return Path(str(raw)) if raw else DATA_DIR / "todesk-taskbox"

    @property
    def wake_hotkey(self) -> str:
        return str(self.config.get("wake_hotkey") or "alt+space")

    @property
    def new_session_hotkey(self) -> str:
        return str(self.config.get("new_session_hotkey") or "ctrl+alt+n")

    @property
    def answer_timeout_s(self) -> int:
        return self._cfg_num("answer_timeout_s", 240)

    @property
    def require_idle_s(self) -> int:
        return self._cfg_num("require_idle_s", 60)

    @property
    def poll_interval_s(self) -> float:
        return self._cfg_num("poll_interval_s", 1.0, float)

    @property
    def lock_stale_s(self) -> int:
        return self.answer_timeout_s + 120

    # ---------- 预检 ----------

    def preflight(self, task: Task) -> Preflight:
        if os.name != "nt":
            return Preflight(available=False, reason="GUI 通道仅支持 Windows")
        if not self.exe.exists():
            return Preflight(available=False, reason=f"找不到客户端 {self.exe}（改配置里的 exe）")
        if not _process_running():
            return Preflight(available=False, reason=f"{_IMAGE_NAME} 未运行，先启动 ToDesk AI 客户端")
        if not _main_window_exists():
            return Preflight(
                available=False,
                reason=f"主窗口「{_WINDOW_TITLE}」不存在（可能被关到托盘），GUI 通道无法定位输入框",
            )
        lock = self.taskbox / ".gui.lock"
        if lock.exists():
            age = time.time() - lock.stat().st_mtime
            if age < self.lock_stale_s:
                return Preflight(available=False, reason=f"GUI 通道被占用（锁 {age:.0f}s 前写入）")
        if self.require_idle_s > 0:
            idle = _idle_seconds()
            if idle < self.require_idle_s:
                return Preflight(
                    available=False,
                    reason=(
                        f"用户 {idle:.0f}s 前有键鼠输入，未满 {self.require_idle_s}s 空闲保护"
                        "（派单会抢焦点，改 require_idle_s 可放松）"
                    ),
                )
        return Preflight(
            available=True,
            balance_note="积分余额只能界面查看，本适配器不查（supports_balance=False）",
        )

    def read_balance(self) -> tuple[int | None, str]:
        return None, "客户端无积分查询接口，只能人工在界面看；不猜、不读界面"

    # ---------- 执行 ----------

    def dispatch(self, task: Task) -> Result:
        started = time.time()
        self.taskbox.mkdir(parents=True, exist_ok=True)
        out_path = self.taskbox / f"{uuid.uuid4().hex[:12]}.out.md"
        prompt = (
            f"{task.text.strip()}\n\n"
            "——\n"
            f"执行约束：把最终结果原文写入文件 {out_path}（UTF-8，纯正文，"
            "不要用代码块包裹，不要附加解读）。写完即可，不必再回复内容。"
        )

        if not self._acquire_lock():
            return self._fail(started, 1, "GUI 通道被另一单占用，未执行")

        backup = ""
        try:
            try:
                backup = clipboard_get()
            except OSError:
                backup = ""

            problem = self._focus_window()
            if problem:
                return self._fail(started, 126, problem)

            send_hotkey(self.new_session_hotkey)
            time.sleep(0.8)
            if _foreground_title() != _WINDOW_TITLE:
                return self._fail(started, 126, "新建会话后主窗口失去前台，已中止")

            clipboard_set(prompt)
            send_hotkey("ctrl+v")
            time.sleep(0.5)
            send_hotkey("enter")

            text, problem = self._wait_answer(out_path, task.timeout_s)
            if problem == "timeout":
                budget = min(task.timeout_s, self.answer_timeout_s)
                return Result(
                    ok=False, exit_code=124, duration_s=time.time() - started,
                    note=(
                        f"已粘贴并回车，{budget}s 内未见结果文件"
                        "（多半是客户端没自动允许写文件，卡在「允许/禁止」授权）"
                    ),
                    raw_tail=f"out={out_path} 不存在或为空；会话可能停在授权弹窗",
                    route="gui",
                    usage=usage_failed("未执行完：GUI 通道超时，客户端不返回用量"),
                )
            if problem:
                return self._fail(started, 126, problem)

            return Result(
                ok=True,
                exit_code=0,
                text=text,
                duration_s=time.time() - started,
                note=(
                    f"gui 通道；结果 {len(text)} 字符，取自 {out_path.name}；"
                    "积分消耗以客户端账单为准"
                ),
                route="gui",
                usage=usage_failed(
                    "ToDesk 按积分计费，客户端不暴露 token/credits，适配器取不到结构化用量"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 契约要求不抛异常
            return self._fail(started, 1, f"异常 {type(exc).__name__}: {exc}")
        finally:
            if backup:
                try:
                    clipboard_set(backup)
                except OSError:
                    pass
            self._release_lock()

    # ---------- 内部 ----------

    def _focus_window(self) -> str:
        for attempt in range(3):
            if _foreground_title() == _WINDOW_TITLE:
                return ""
            send_hotkey(self.wake_hotkey)
            time.sleep(0.9 * (attempt + 1))
        return f"按 {self.wake_hotkey} 三次仍未唤起主窗口（前台是「{_foreground_title()}」）"

    def _wait_answer(self, out_path: Path, timeout_s: int) -> tuple[str, str]:
        deadline = time.time() + min(timeout_s, self.answer_timeout_s)
        last_size = -1
        while time.time() < deadline:
            time.sleep(self.poll_interval_s)
            if not out_path.exists():
                continue
            size = out_path.stat().st_size
            if size == 0 or size != last_size:   # 还在写，等它稳定两轮
                last_size = size
                continue
            text = self._read_text(out_path).strip()
            if text:
                return text, ""
            return "", f"结果文件为空：{out_path.name}"
        return "", "timeout"

    @staticmethod
    def _read_text(path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-16", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    def _acquire_lock(self) -> bool:
        lock = self.taskbox / ".gui.lock"
        if lock.exists():
            age = time.time() - lock.stat().st_mtime
            if age < self.lock_stale_s:
                return False
        lock.write_text(f"{os.getpid()} {int(time.time())}", encoding="utf-8")
        return True

    def _release_lock(self) -> None:
        try:
            (self.taskbox / ".gui.lock").unlink()
        except OSError:
            pass

    @staticmethod
    def _fail(started: float, code: int, reason: str) -> Result:
        note = reason if reason.startswith("未执行") else f"未执行：{reason}"
        return Result(
            ok=False,
            exit_code=code,
            duration_s=time.time() - started,
            note=note,
            raw_tail=reason[-400:],
            route="gui",
            usage=usage_failed(note),
        )