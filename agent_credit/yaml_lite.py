"""Minimal YAML loader for catalog.yaml (maps, lists, scalars)."""

from __future__ import annotations

from typing import Any


def load_yaml(text: str) -> Any:
    lines = text.replace("\r\n", "\n").split("\n")
    filtered: list[tuple[int, str]] = []
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        filtered.append((indent, raw.strip()))
    value, _ = _parse_block(filtered, 0, 0)
    return value


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    if i >= len(lines):
        return None, i
    cur_indent, content = lines[i]
    if cur_indent < indent:
        return None, i
    if content.startswith("- "):
        return _parse_list(lines, i, cur_indent)
    return _parse_map(lines, i, cur_indent)


def _parse_map(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent or content.startswith("- "):
            break
        if cur_indent != indent:
            raise ValueError(f"bad indent at: {content}")
        if ":" not in content:
            raise ValueError(f"expected key: {content}")
        key, rest = content.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        i += 1
        if rest == "":
            if i < len(lines) and lines[i][0] > indent:
                value, i = _parse_block(lines, i, lines[i][0])
            else:
                value = None
        else:
            value = _parse_scalar(rest)
        result[key] = value
    return result, i


def _parse_list(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while i < len(lines):
        cur_indent, content = lines[i]
        if cur_indent < indent or not content.startswith("- "):
            break
        if cur_indent != indent:
            raise ValueError(f"bad list indent at: {content}")
        item = content[2:].strip()
        i += 1
        if item == "":
            if i < len(lines) and lines[i][0] > indent:
                value, i = _parse_block(lines, i, lines[i][0])
            else:
                value = None
        elif item.endswith(":") and ":" in item:
            key, rest = item.split(":", 1)
            nested: dict[str, Any] = {key.strip(): _parse_scalar(rest.strip()) if rest.strip() else None}
            if i < len(lines) and lines[i][0] > indent:
                extra, i = _parse_map(lines, i, lines[i][0])
                if nested[key.strip()] is None:
                    nested[key.strip()] = extra
                else:
                    nested.update(extra)
            value = nested
        elif ":" in item and not item.startswith("[") and not item.startswith('"'):
            key, rest = item.split(":", 1)
            nested = {key.strip(): _parse_scalar(rest.strip()) if rest.strip() else None}
            if i < len(lines) and lines[i][0] > indent:
                extra, i = _parse_map(lines, i, lines[i][0])
                nested.update(extra)
            value = nested
        else:
            value = _parse_scalar(item)
        result.append(value)
    return result, i


def _parse_scalar(token: str) -> Any:
    if token in ("null", "~", ""):
        return None
    if token in ("true", "True"):
        return True
    if token in ("false", "False"):
        return False
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if token.startswith("{") and token.endswith("}"):
        inner = token[1:-1].strip()
        if not inner:
            return {}
        obj: dict[str, Any] = {}
        for part in inner.split(","):
            k, v = part.split(":", 1)
            obj[k.strip()] = _parse_scalar(v.strip())
        return obj
    try:
        if token.startswith("0") and token != "0" and not token.startswith("0."):
            return token
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return token
