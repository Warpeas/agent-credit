from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = Path(os.environ.get("AGENT_CREDIT_CATALOG", ROOT / "catalog.yaml"))
DATA_DIR = Path(os.environ.get("AGENT_CREDIT_DATA", ROOT / "data"))
LEDGER_PATH = DATA_DIR / "ledger.json"
LOG_DIR = ROOT / "logs"
