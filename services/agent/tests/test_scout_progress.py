"""Scout must report progress per source family during the sweep.

Incident (2026-10-24): the multi-source sweep ran 130-370s while emitting
zero events, so the UI stream looked dead. scout_search now accepts a
progress callback invoked as each source family completes (and around the
merge/enrich steps), so the graph can stream real progress.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import scout  # noqa: E402


def _cand(title, url, source="hn"):
    return {"title": title, "url": url, "source": source, "points": 10,
            "num_comments": 1, "snippet": "x" * 200, "created_at": ""}


def _mock_all(monkeypatch):
    monkeypatch.setattr(scout, "fetch_tavily", lambda q, limit=8: [])
    monkeypatch.setattr(scout, "fetch_hn_frontpage",
                        lambda limit=60: [_cand("AI front", "https://ex.com/fp")])
    monkeypatch.setattr(scout, "fetch_hn",
                        lambda q, limit=12: [_cand("AI search", "https://ex.com/hn")])
    monkeypatch.setattr(scout, "fetch_reddit",
                        lambda subs, limit=40, pacing=0: [_cand("AI reddit", "https://ex.com/rd", "reddit")])
    monkeypatch.setattr(scout, "fetch_gdelt",
                        lambda kw, ts, mr, pacing=0: [_cand("AI gdelt", "https://ex.com/gd", "gdelt")])
    monkeypatch.setattr(scout, "fetch_trends",
                        lambda geo="US": [_cand("AI trends", "https://ex.com/tr", "trends")])
    monkeypatch.setattr(scout, "fetch_editorial",
                        lambda cfg: [_cand("AI editorial", "https://ex.com/ed", "tldr-ai")])


_RESEARCH = {
    "prefilter_keywords": ["ai"],
    "tavily": True,
    "hn_frontpage": {"limit": 60},
    "hn_search": {"limit": 12},
    "reddit": {"subreddits": ["artificial"], "limit": 40, "pacing": 0},
    "gdelt": {"keywords": ["OpenAI"], "timespan": "24h", "maxrecords": 50, "pacing": 0},
    "trends": {"geo": "US"},
    "editorial": [{"name": "TLDR AI", "url": "https://tldr.tech/api/rss/ai"}],
}


def test_progress_reports_each_source_family(monkeypatch):
    _mock_all(monkeypatch)
    seen: list[tuple[str, int]] = []
    candidates, _calls, _stats = scout.scout_search(
        "ai news", _RESEARCH, [], progress=lambda ch, n: seen.append((ch, n)))
    channels = [ch for ch, _n in seen]
    for expected in ("hn-frontpage", "hn-algolia", "reddit", "gdelt",
                     "trends", "editorial"):
        assert expected in channels, seen
    assert all(isinstance(n, int) and n >= 0 for _ch, n in seen)
    # progress ends with the merged total, matching the returned pool
    assert seen[-1][1] == len(candidates), seen


def test_progress_is_optional(monkeypatch):
    _mock_all(monkeypatch)
    candidates, _calls, _stats = scout.scout_search("ai news", _RESEARCH, [])
    assert candidates, "sweep must still work without a progress callback"
