from __future__ import annotations

import os
from pathlib import Path


def _find_root() -> Path:
    """Locate the Prism repo root by walking up from this file looking for
    a playbooks/ directory — robust to being run from the repo root or
    deployed standalone with services/agent as the service root."""
    if os.environ.get("PRISM_ROOT"):
        return Path(os.environ["PRISM_ROOT"])
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "playbooks").is_dir():
            return parent
    return here.parents[3]


PRISM_ROOT = _find_root()
PLAYBOOKS_DIR = PRISM_ROOT / "playbooks"
CAROUSEL_DIR = PRISM_ROOT / "mcp_servers" / "carousel"
# Standalone deployment fallback: if the full repo isn't present, the
# carousel renderer may be vendored beside the service.
if not CAROUSEL_DIR.is_dir():
    alt = Path(__file__).resolve().parents[2] / "mcp_servers" / "carousel"
    if alt.is_dir():
        CAROUSEL_DIR = alt
DATA_DIR = Path(os.environ.get("PRISM_DATA_DIR", PRISM_ROOT / "data"))
RUNS_DIR = DATA_DIR / "runs"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"
PAST_RUNS_FILE = DATA_DIR / "past-runs.json"

for _d in (DATA_DIR, RUNS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Server bind config is env-only: uvicorn --host 0.0.0.0 --port ${PORT:-8077}
PORT = int(os.environ.get("PORT", "8077"))
