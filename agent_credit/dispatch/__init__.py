"""派单调度：适配器发现、预检、串行执行、失败回退。"""

from .base import Preflight, Provider, Result, Task
from .registry import build, load_config
from .scheduler import Attempt, Outcome, candidates, run

__all__ = [
    "Attempt",
    "Outcome",
    "Preflight",
    "Provider",
    "Result",
    "Task",
    "build",
    "candidates",
    "load_config",
    "run",
]
