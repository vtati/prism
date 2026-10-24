from __future__ import annotations

import json

import yaml

from .config import PAST_RUNS_FILE, PLAYBOOKS_DIR


def load_playbook(playbook_id: str) -> dict:
    path = PLAYBOOKS_DIR / f"{playbook_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"playbook not found: {playbook_id}")
    with open(path) as f:
        data = yaml.safe_load(f)
    pb = data["playbook"]
    pb["_path"] = str(path)
    return pb


def list_playbooks() -> list[dict]:
    out = []
    for path in sorted(PLAYBOOKS_DIR.glob("*.yaml")):
        with open(path) as f:
            pb = yaml.safe_load(f)["playbook"]
        out.append({
            "id": pb["id"], "name": pb["name"], "domain": pb.get("domain"),
            "theme": pb.get("theme"), "audience": pb.get("audience"),
            "rubric": pb.get("rubric"), "makers": pb.get("makers"),
            "sources": pb.get("sources"),
        })
    return out


def brand_voice() -> str:
    p = PLAYBOOKS_DIR / "knowledge" / "brand-voice.md"
    return p.read_text() if p.exists() else ""


def load_past_runs() -> list[dict]:
    if PAST_RUNS_FILE.exists():
        try:
            return json.loads(PAST_RUNS_FILE.read_text())
        except Exception:
            return []
    seed = PLAYBOOKS_DIR / "knowledge" / "past-runs.json"
    if seed.exists():
        try:
            return json.loads(seed.read_text())
        except Exception:
            return []
    return []


def record_past_run(entry: dict) -> None:
    runs = load_past_runs()
    runs.append(entry)
    PAST_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAST_RUNS_FILE.write_text(json.dumps(runs, indent=2))
