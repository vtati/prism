"""Per-playbook edition counter + v3 skin selection.

CURRENT SKIN RULE (Venugopal, locked 2026-10-16–20, superseding the
original Oct 14 rotation): for the daily AI Dev Digest, POSTER is the
standing default skin for every edition — light background, colored
per-slot vertical bars. frontpage is an alternate light skin on request
only; dark skins (terminal, neon-grid, aurora) are special-occasion only.

A playbook declares its skin in its `carousel` section:
    skin: poster        # the fixed skin used for every run
    skin_mode: fixed    # default; "rotation" opts back into the legacy
                        # edition rotation below — no shipped playbook
                        # sets it by default.
The rotation table is kept for that explicit opt-in and for the
special-occasion skins:
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


def skin_for_playbook(playbook: dict, edition: int) -> str:
    """Resolve the carousel skin a playbook asks for.

    skin_mode: rotation (explicit opt-in only) -> legacy edition rotation.
    Anything else -> the playbook's fixed carousel.skin (poster when a
    playbook declares none — the standing Digest default)."""
    car = (playbook or {}).get("carousel") or {}
    if car.get("skin_mode") == "rotation":
        return skin_for_edition(edition)
    return car.get("skin") or "poster"


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
