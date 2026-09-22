from __future__ import annotations

from functools import lru_cache
from typing import Any

from .paths import CATALOG_PATH
from .yaml_lite import load_yaml


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    text = CATALOG_PATH.read_text(encoding="utf-8")
    data = load_yaml(text)
    if not isinstance(data, dict) or "accounts" not in data:
        raise ValueError(f"invalid catalog: {CATALOG_PATH}")
    return data


def accounts() -> list[dict[str, Any]]:
    return list(load_catalog()["accounts"])


def calendar_items() -> list[dict[str, Any]]:
    return list(load_catalog().get("calendar") or [])


def threshold_ratio() -> float:
    return float(load_catalog().get("claim_threshold_ratio") or 0.3)


def find_account(key: str) -> dict[str, Any]:
    needle = key.strip().lower()
    for acc in accounts():
        aliases = [str(a).lower() for a in (acc.get("aliases") or [])]
        if acc["id"] == needle or acc["name"].lower() == needle or needle in aliases:
            return acc
    raise KeyError(f"unknown account: {key}")


def account_by_id(account_id: str) -> dict[str, Any]:
    for acc in accounts():
        if acc["id"] == account_id:
            return acc
    raise KeyError(account_id)
