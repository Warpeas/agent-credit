from __future__ import annotations

import importlib
import os
import pkgutil
from pathlib import Path
from typing import Any

from ..paths import ROOT
from ..yaml_lite import load_yaml
from .base import Provider

PROVIDERS_PATH = Path(os.environ.get("AGENT_CREDIT_PROVIDERS", ROOT / "providers.yaml"))


def load_config() -> dict[str, Any]:
    if not PROVIDERS_PATH.exists():
        return {"providers": {}}
    data = load_yaml(PROVIDERS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid providers config: {PROVIDERS_PATH}")
    return data


def discover() -> list[type[Provider]]:
    """自动发现 adapters/ 下的适配器，新增文件不需要改这里。"""
    from . import adapters as adapters_pkg

    found: list[type[Provider]] = []
    for info in pkgutil.iter_modules(adapters_pkg.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{adapters_pkg.__name__}.{info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, Provider)
                and obj is not Provider
                and getattr(obj, "name", "")
                and obj.__module__ == module.__name__
            ):
                found.append(obj)
    return found


def build() -> list[Provider]:
    """按配置实例化所有已发现适配器，并按 (priority, name) 排序。"""
    config = load_config().get("providers") or {}
    instances = []
    for cls in discover():
        instances.append(cls(config.get(cls.name) or {}))
    instances.sort(key=lambda p: (p.priority, p.name))
    return instances
