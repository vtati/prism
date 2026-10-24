"""Per-playbook edition counter + v3 skin rotation.

The AI Dev Digest format v3 rotates skins by edition:
    skin = ROTATION[(edition - 1) % 5]
over [frontpage, terminal, neon-grid, poster, aurora] (statdeck is
rejected — never in the rotation). The counter persists in the data dir
(editions.json) so editions keep advancing across runs and restarts.
One edition is assigned per RUN: the first carousel build for a run_id
claims the next edition; reviewer-loop rebuilds of the same run reuse it.
"""
from __future__ import annotations

import json
import threading

from .config import DATA_DIR

ROTATION = ["frontpage", "terminal", "neon-grid", "poster", "aurora"]
_STORE = DATA_DIR / "editions.json"
_lock = threading.Lock()
_run_editions: dict[str, tuple[str, int]] = {}


def skin_for_edition(edition: int) -> str:
    return ROTATION[(edition - 1) % len(ROTATION)]


def _load() -> dict:
    try:
        return json.loads(_STORE.read_text())
    except Exception:
        return {}


def assign_edition(run_id: str, playbook_id: str) -> int:
    """Claim (or recall) the edition number for this run + playbook."""
    with _lock:
        if run_id in _run_editions and _run_editions[run_id][0] == playbook_id:
            return _run_editions[run_id][1]
        counts = _load()
        edition = int(counts.get(playbook_id, 0)) + 1
        counts[playbook_id] = edition
        try:
            _STORE.write_text(json.dumps(counts, indent=2))
        except Exception:
            pass  # counter persistence must never block a run
        _run_editions[run_id] = (playbook_id, edition)
        return edition


def current_edition(playbook_id: str) -> int:
    return int(_load().get(playbook_id, 0))
