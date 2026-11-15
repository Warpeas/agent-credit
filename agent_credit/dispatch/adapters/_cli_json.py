"""CLI JSON 输出解析（供多个适配器共用）。

CodeBuddy / Qoder 这类 CLI 即使执行失败也常常 exit 0，把错误写进 JSON 的
is_error / subtype / errors 里，所以判断成败不能只看返回码。
"""

from __future__ import annotations

import json

_TEXT_KEYS = ("result", "response", "text", "content", "output", "final", "message")


def parse_result_json(stdout: str) -> tuple[str, str]:
    """返回 (正文, 错误)。非 JSON 输出整段当正文；识别不出正文时给错误说明。

    兼容三种形态：单个 result 对象（qoder）、消息数组（codebuddy 会把整段
    transcript 打出来，最后一项才是 type=result）、以及裸文本。
    """
    raw = stdout.strip()
    if not raw:
        return "", ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw, ""
    if isinstance(data, str):
        return data, ""
    if isinstance(data, list):
        for item in reversed(data):
            if isinstance(item, dict) and item.get("type") == "result":
                return _from_dict(item)
        return "", "输出是消息数组但没有 result 项"
    if isinstance(data, dict):
        return _from_dict(data)
    return raw, ""


def _from_dict(data: dict) -> tuple[str, str]:
    if data.get("is_error") or str(data.get("subtype") or "").startswith("error"):
        errors = data.get("errors") or []
        detail = "; ".join(str(e) for e in errors) or str(data.get("subtype") or "is_error")
        return "", detail
    for key in _TEXT_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), ""
    nested = data.get("data")
    if isinstance(nested, dict):
        return _from_dict(nested)
    return "", "输出里没有可识别的正文"
