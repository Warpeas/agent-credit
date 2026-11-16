"""CLI JSON 输出解析（供多个适配器共用）。

CodeBuddy / Qoder 这类 CLI 即使执行失败也常常 exit 0，把错误写进 JSON 的
is_error / subtype / errors 里，所以判断成败不能只看返回码。
"""

from __future__ import annotations

import json
from datetime import datetime

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


def _load(stdout: str) -> tuple[bool, object]:
    raw = stdout.strip()
    if not raw:
        return False, None
    try:
        return True, json.loads(raw)
    except json.JSONDecodeError:
        return False, None


def _result_item(data: object) -> dict | None:
    """定位 result 项：消息数组取最后一项 type=result，单个对象就是它自己。"""
    if isinstance(data, list):
        for item in reversed(data):
            if isinstance(item, dict) and item.get("type") == "result":
                return item
        return None
    if isinstance(data, dict):
        if (
            data.get("type") == "result"
            or "rawUsage" in data
            or data.get("is_error")
            or any(key in data for key in _TEXT_KEYS)
        ):
            return data
        nested = data.get("data")
        if isinstance(nested, dict):
            return _result_item(nested)
    return None


def _num(value: object) -> float | None:
    """数值才认；布尔、空串、嵌套结构一律不给值（缺项用 null，不补 0）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _int(value: object) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _reset_at(value: object) -> str | None:
    """quota.reset_at 是秒级 epoch 字符串；转成本地 ISO 时间便于人读。

    不是数字就原样保留（各版本口径不同，不猜）；转换失败也给原值。
    """
    number = _num(value)
    if number is None:
        text = str(value).strip() if value is not None else ""
        return text or None
    if number > 1e11:  # 毫秒
        number /= 1000
    try:
        return datetime.fromtimestamp(number).astimezone().isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return str(value)


def _iter_assistant_payloads(data: object) -> list[dict]:
    """消息数组里每条 assistant 消息的 providerData（含 rawUsage / model）。"""
    entries = data if isinstance(data, list) else [data]
    payloads: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        provider = entry.get("providerData")
        if not isinstance(provider, dict):
            continue
        if entry.get("type") == "message" and entry.get("role") == "assistant":
            payloads.append(provider)
    return payloads


def parse_usage_detail(stdout: str) -> dict:
    """把 CLI 输出解析成结构化用量；拿不到的字段一律 null。

    2026-11-15 实测 codebuddy 2.184.0 的真实形态：
      - 最后一项 `type=result` 的 `usage.input_tokens / output_tokens` 是
        本轮账单口径的 token 合计；
      - assistant 消息的 `providerData.rawUsage` 才有 `credit`、`quota.percent`
        和 `quota.reset_at`，模型名在 `providerData.model`；
      - `total_cost_usd` 恒为 0，不是额度，不能拿来当消耗。
    因此 token 优先取 result.usage，取不到再退回最后一条 rawUsage 的
    prompt/completion_tokens；credit 按各次模型调用求和。
    """
    usage: dict = {
        "status": "failed",
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "credits": None,
        "remaining_percent": None,
        "reset_at": None,
    }
    ok, data = _load(stdout)
    if not ok:
        usage["error"] = "stdout 不是 JSON，无法解析用量"
        return usage

    item = _result_item(data)
    payloads = _iter_assistant_payloads(data)
    raws = [p["rawUsage"] for p in payloads if isinstance(p.get("rawUsage"), dict)]
    if item is not None and isinstance(item.get("rawUsage"), dict):
        raws.append(item["rawUsage"])

    if item is not None and isinstance(item.get("usage"), dict):
        usage["input_tokens"] = _int(item["usage"].get("input_tokens"))
        usage["output_tokens"] = _int(item["usage"].get("output_tokens"))
    if usage["input_tokens"] is None and raws:
        usage["input_tokens"] = _int(raws[-1].get("prompt_tokens"))
    if usage["output_tokens"] is None and raws:
        usage["output_tokens"] = _int(raws[-1].get("completion_tokens"))

    credits = [value for raw in raws
               if (value := _num(raw.get("credit"))) is not None]
    if credits:
        usage["credits"] = round(sum(credits), 4)

    for raw in reversed(raws):
        quota = raw.get("quota")
        if not isinstance(quota, dict):
            continue
        usage["remaining_percent"] = _num(quota.get("percent"))
        usage["reset_at"] = _reset_at(quota.get("reset_at"))
        break

    model = next((p.get("model") for p in reversed(payloads) if p.get("model")), None)
    if not model:
        model = next((raw.get("quota", {}).get("model") for raw in reversed(raws)
                      if isinstance(raw.get("quota"), dict) and raw["quota"].get("model")), None)
    usage["model"] = str(model) if model else None

    filled = [usage[key] for key in
              ("input_tokens", "output_tokens", "credits", "remaining_percent", "reset_at")]
    if all(value is not None for value in filled):
        usage["status"] = "ok"
    elif any(value is not None for value in filled):
        usage["status"] = "partial"
    else:
        usage["error"] = "输出里没有可识别的 usage / rawUsage 字段"
    return usage


def format_usage_summary(usage: dict) -> str:
    """把结构化用量拼成一行人读摘要，写进 Result.note。"""
    if not usage:
        return ""
    parts = [f"usage={usage.get('status') or 'failed'}"]
    if usage.get("model"):
        parts.append(f"model={usage['model']}")
    for key, label in (("input_tokens", "in"), ("output_tokens", "out"),
                       ("credits", "credit"), ("remaining_percent", "left%")):
        if usage.get(key) is not None:
            parts.append(f"{label}={usage[key]}")
    if usage.get("reset_at"):
        parts.append(f"reset={usage['reset_at']}")
    if usage.get("error"):
        parts.append(f"error={usage['error']}")
    return ", ".join(parts)
