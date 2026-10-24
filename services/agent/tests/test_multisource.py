"""Multi-source Scout tests: the sweep mirrors the production AI News
pipeline (viral_watch.py) — HN front page + query search, Reddit (Arctic
Shift), GDELT artlist, Google Trends RSS, editorial RSS — all merged with
dedupe + corroboration. Network is fully mocked via scout._get; copy
tests pin the 'never quote the rubric score in public copy' rule and the
carousel contents word-boundary fit."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import makers, scout  # noqa: E402
from app.graph import score_candidate  # noqa: E402
from app.playbooks import load_playbook  # noqa: E402

GPT6 = "OpenAI launches GPT-6 with agentic browsing"
GPT6_URL = "https://example.com/openai-gpt6"
SCORE_EXPL = ('"Story" scored 63.9/100 (Audience Heat 7.9/40, Consequence 20/20, '
              'Verification 18/20, Novelty 18/20) across 6 candidates, with 412 points '
              'and 188 comments of live discussion.')
ARTICLE_HTML = ("<html><body><p>Full article body: the release ships today with "
                "benchmarks, pricing details and a migration guide for teams. "
                "Developers can use it in production immediately after a short "
                "review of the changelog and the safety notes.</p></body></html>")

TRENDS_XML = """<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
<channel>
<item><title>openai gpt-6</title><link>https://trends.google.com/trending?geo=US</link>
<pubDate>Fri, 24 Oct 2026 12:00:00 +0000</pubDate>
<ht:approx_traffic>500,000+</ht:approx_traffic>
<ht:news_item><ht:news_item_title>OpenAI launches GPT-6 with agentic browsing</ht:news_item_title>
<ht:news_item_url>https://example.com/openai-gpt6</ht:news_item_url>
<ht:news_item_source>Example News</ht:news_item_source></ht:news_item></item>
<item><title>sec games today</title><link>https://trends.google.com/trending?geo=US</link>
<ht:approx_traffic>200,000+</ht:approx_traffic></item>
</channel></rss>"""

TLDR_XML = f"""<rss version="2.0"><channel>
<item><title>{GPT6}</title><link>{GPT6_URL}</link>
<description>OpenAI shipped GPT-6 with agentic browsing built in.</description>
<pubDate>Fri, 24 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>DeepSeek releases a new reasoning model</title>
<link>https://example.com/deepseek</link>
<description>DeepSeek published a reasoning model with open weights and a full
technical report covering training, benchmarks and deployment notes.</description>
<pubDate>Fri, 24 Oct 2026 08:00:00 +0000</pubDate></item>
</channel></rss>"""

ATOM_XML = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Notes on agentic coding tools</title>
<link href="https://example.com/sw-notes"/>
<published>2026-10-24T10:00:00Z</published>
<summary>Agents and coding tools roundup.</summary></entry></feed>"""


class FakeResp:
    def __init__(self, json_data=None, text="", status=200, ctype=None):
        self._json = json_data
        self.text = text
        self.status_code = status
        self.headers = {"content-type": ctype or ("text/html" if text else "application/json")}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture()
def net(monkeypatch):
    """Mock scout._get with a router over canned per-source payloads.
    Returns the list of (url, params) the sweep actually requested."""
    requested = []

    def fake_get(url, **kw):
        params = kw.get("params") or {}
        requested.append((url, params))
        if "hn.algolia.com" in url:
            if params.get("tags") == "front_page":
                return FakeResp({"hits": [
                    {"title": "A new open model for AI agents ships today",
                     "url": "https://example.com/fp-model", "points": 250,
                     "num_comments": 40, "story_text": "", "created_at": "2026-10-24T08:00:00Z",
                     "objectID": "fp1"},
                    {"title": "Show HN: A CSS framework for dashboards",
                     "url": "https://example.com/css", "points": 90,
                     "num_comments": 12, "story_text": "", "created_at": "2026-10-24T08:00:00Z",
                     "objectID": "fp2"},
                ]})
            return FakeResp({"hits": [
                {"title": GPT6, "url": GPT6_URL, "points": 300, "num_comments": 120,
                 "story_text": "OpenAI shipped GPT-6 today. The model browses "
                               "agents natively and tops the launch charts.",
                 "created_at": "2026-10-24T07:00:00Z", "objectID": "s1"},
                {"title": "Anthropic ships Claude SDK update",
                 "url": "https://example.com/claude-sdk", "points": 180,
                 "num_comments": 55, "story_text": "",
                 "created_at": "2026-10-24T07:30:00Z", "objectID": "s2"},
            ]})
        if "arctic-shift" in url:
            sub = params.get("subreddit")
            data = {
                "singularity": [
                    {"id": "r1", "title": GPT6, "url": GPT6_URL,
                     "permalink": "/r/singularity/comments/r1/x/", "score": 800,
                     "num_comments": 300, "selftext": "", "created_utc": 1792800000},
                    {"id": "r2", "title": "I asked ChatGPT to plan my week",
                     "url": "https://www.reddit.com/r/singularity/comments/r2/x/",
                     "permalink": "/r/singularity/comments/r2/x/", "score": 150,
                     "num_comments": 80, "selftext": "It planned everything.",
                     "created_utc": 1792800000},
                ],
                "LocalLLaMA": [
                    {"id": "r3", "title": "New local LLM beats GPT at coding tasks",
                     "url": "https://example.com/local-model",
                     "permalink": "/r/LocalLLaMA/comments/r3/x/", "score": 350,
                     "num_comments": 140,
                     "selftext": "Ran the benchmarks locally on a single GPU and the "
                                 "new open model held its own against hosted APIs "
                                 "across the full coding suite we tried.",
                     "created_utc": 1792800000},
                ],
            }.get(sub, [])
            return FakeResp({"data": data})
        if "api.gdeltproject.org" in url:
            q = params.get("query") or ""
            if "Nvidia" in q:
                raise RuntimeError("HTTP 429")
            arts = {
                "OpenAI": [{"title": "OpenAI valued at record high as agent race heats up",
                            "url": "https://example.com/openai-valuation",
                            "domain": "example.com", "seendate": "20261024T120000Z"}],
                "artificial intelligence": [
                    {"title": "AI regulation bill advances in the Senate",
                     "url": "https://example.com/ai-bill",
                     "domain": "example.com", "seendate": "20261024T110000Z"}],
                "Anthropic": [{"title": "Anthropic ships Claude SDK update",
                               "url": "https://example.com/claude-sdk",
                               "domain": "example.com", "seendate": "20261024T100000Z"}],
            }
            key = next((k for k in arts if k in q), None)
            return FakeResp({"articles": arts.get(key, [])})
        if "trends.google.com" in url:
            return FakeResp(text=TRENDS_XML, ctype="application/rss+xml")
        if "tldr.tech" in url:
            return FakeResp(text=TLDR_XML, ctype="application/rss+xml")
        if "simonwillison.net" in url:
            return FakeResp(text=ATOM_XML, ctype="application/atom+xml")
        if "latent.space" in url or "therundown.ai" in url:
            return FakeResp(text="<rss version='2.0'><channel></channel></rss>",
                            ctype="application/rss+xml")
        if url.startswith("https://example.com/"):
            return FakeResp(text=ARTICLE_HTML)
        raise RuntimeError(f"unexpected URL in mock: {url}")

    monkeypatch.setattr(scout, "_get", fake_get)
    monkeypatch.setattr(scout.time, "sleep", lambda *_a: None)
    return requested


def _research(playbook_id="ai-news-gtm"):
    research = dict(load_playbook(playbook_id)["research"])
    research["gdelt"] = {**research["gdelt"], "pacing": 0}
    research["reddit"] = {**research["reddit"], "pacing": 0}
    return research


# ---------------------------------------------------------------- fetchers

def test_fetch_hn_frontpage(net):
    items = scout.fetch_hn_frontpage(60)
    assert items and all(i["source"] == "Hacker News" for i in items)
    assert any(tags == "front_page" for _, p in net for tags in [p.get("tags")])
    assert {"title", "url", "source", "points", "num_comments", "snippet",
            "created_at"} <= set(items[0])


def test_fetch_reddit(net):
    items = scout.fetch_reddit(["singularity"], 40, pacing=0)
    assert items[0]["source"] == "reddit:r/singularity"
    assert items[0]["url"] == GPT6_URL  # external link preferred over permalink
    assert items[0]["points"] == 800


def test_fetch_gdelt_failure_isolated(net):
    items = scout.fetch_gdelt(["OpenAI", "Nvidia", "Anthropic"], pacing=0)
    urls = {i["url"] for i in items}
    assert "https://example.com/openai-valuation" in urls  # survivors present
    assert "https://example.com/claude-sdk" in urls
    assert all(i["source"] == "gdelt" and i["title"] for i in items)


def test_fetch_trends(net):
    items = scout.fetch_trends("US")
    top = items[0]
    assert top["source"] == "trends" and top["points"] == 500  # 500K+ traffic
    assert top["url"] == GPT6_URL  # nested news item URL, not the trends page
    assert "agentic browsing" in top["snippet"]


def test_fetch_editorial_rss_and_atom(net):
    items = scout.fetch_editorial(load_playbook("ai-news-gtm")["research"]["editorial"])
    by_src = {i["source"] for i in items}
    assert "tldr-ai" in by_src and "simon-willison" in by_src
    assert all(i["url"].startswith("http") for i in items)


# ------------------------------------------------------------------- merge

def test_merge_dedupes_and_counts_corroboration():
    a = [{"title": GPT6, "url": GPT6_URL, "source": "Hacker News", "points": 300,
          "num_comments": 10, "snippet": "short", "created_at": None}]
    b = [{"title": GPT6, "url": GPT6_URL, "source": "reddit:r/singularity",
          "points": 800, "num_comments": 300, "snippet": "a much longer snippet",
          "created_at": None},
         {"title": "OpenAI launches GPT-6 with agentic browsing!",
          "url": "https://other.example.com/gpt6-news", "source": "gdelt",
          "points": 0, "num_comments": 0, "snippet": "", "created_at": None}]
    merged = scout.merge_candidates([a, b])
    assert len(merged) == 1, "same URL + near-identical title must dedupe to one"
    m = merged[0]
    assert m["corroboration"] == 3
    assert m["points"] == 800 and m["snippet"] == "a much longer snippet"
    for label in ("Hacker News", "reddit:r/singularity", "gdelt"):
        assert label in m["source"]


def test_prefilter_word_boundaries():
    kw = ["ai", "openai"]
    assert scout._relevant("OpenAI ships a model", kw)
    assert scout._relevant("New AI framework", kw)
    assert not scout._relevant("He said the train arrived", kw)  # 'ai' in 'said'


# ------------------------------------------------------------------- sweep

def test_scout_search_queries_all_sources(net):
    candidates, calls, stats = scout.scout_search(
        "agentic AI systems", _research(), ["hn-frontpage", "reddit", "gdelt"])
    families = {f for f in ("hn", "reddit", "gdelt", "trends", "editorial")
                if stats.get(f)}
    assert families == {"hn", "reddit", "gdelt", "trends", "editorial"}, stats
    assert stats["merged_total"] == len(candidates) < sum(
        stats[f] for f in families), "merge must dedupe across sources"
    gpt6 = next(c for c in candidates if c["url"] == GPT6_URL)
    assert gpt6["corroboration"] >= 3, gpt6["source"]
    assert "trends" in gpt6["source"] and "tldr-ai" in gpt6["source"]
    titles = [c["title"] for c in candidates]
    assert not any("sec games" in t for t in titles), "non-AI trend must be prefiltered"
    assert not any("CSS framework" in t for t in titles), "non-AI front-page item prefiltered"
    sdk = next(c for c in candidates if c["url"] == "https://example.com/claude-sdk")
    assert sdk["corroboration"] == 2, "HN + GDELT carry the SDK story"
    fp = next(c for c in candidates if c["url"] == "https://example.com/fp-model")
    assert len(fp["snippet"]) > 100, "thin front-page snippet must be page-enriched"
    assert any("hn-frontpage" in c for c in calls) and any("gdelt" in c for c in calls)


def test_scout_search_is_data_driven(net):
    research = _research("travel-news")
    candidates, calls, stats = scout.scout_search("travel deals", research, [])
    subs = {p.get("subreddit") for u, p in net if "arctic-shift" in u}
    assert subs == {"travel", "solotravel", "TravelHacks", "digitalnomad"}, subs


def test_scout_search_fixture_fallback(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(scout, "_get", boom)
    monkeypatch.setattr(scout.time, "sleep", lambda *_a: None)
    candidates, calls, _stats = scout.scout_search("anything", _research(), [])
    assert candidates and "fixture" in candidates[0]["source"]
    assert any("recorded-fixture" in c for c in calls)


def test_enrich_fills_thin_snippets(net):
    cands = [{"title": "A story", "url": "https://example.com/deep-dive",
              "source": "gdelt", "points": 0, "num_comments": 0,
              "snippet": "", "created_at": None},
             {"title": "HN thread", "url": "https://news.ycombinator.com/item?id=1",
              "source": "Hacker News", "points": 5, "num_comments": 1,
              "snippet": "", "created_at": None}]
    scout._enrich(cands)
    assert "Full article body" in cands[0]["snippet"]
    assert cands[1]["snippet"] == "", "discussion URLs are never enriched"


# ------------------------------------------------------- playbooks + curator

def test_playbook_research_config():
    ai = load_playbook("ai-news-gtm")
    r = ai["research"]
    assert r["reddit"]["subreddits"] == ["singularity", "LocalLLaMA", "artificial", "ChatGPT"]
    assert set(r["gdelt"]["keywords"]) == {"OpenAI", '"artificial intelligence"',
                                           "Anthropic", "Nvidia"}
    assert [f["name"] for f in r["editorial"]] == [
        "TLDR AI", "The Rundown AI", "Simon Willison", "Latent Space"]
    assert r["hn_frontpage"]["limit"] == 60 and r["trends"]["geo"] == "US"
    assert "reddit" in ai["sources"] and "gdelt" in ai["sources"]

    tv = load_playbook("travel-news")["research"]
    assert tv["reddit"]["subreddits"] == ["travel", "solotravel", "TravelHacks", "digitalnomad"]
    assert any("airfare" in k for k in tv["gdelt"]["keywords"])
    assert [f["name"] for f in tv["editorial"]] == [
        "The Points Guy", "Skift", "Travel Off Path"]


def test_corroboration_boosts_verification():
    rubric = load_playbook("ai-news-gtm")["rubric"]
    base = {"title": "OpenAI launches a thing", "url": "https://x.example.com",
            "points": 100, "num_comments": 10, "snippet": ""}
    single = score_candidate({**base, "corroboration": 1}, rubric, set(), set())
    assert single["verification"] == 18.0, "single source tops out at 0.9 x 20"
    corr = score_candidate({**base, "corroboration": 3}, rubric, set(), set())
    assert corr["verification"] == 20.0, "corroborated story can max verification"


# ------------------------------------------------------------ copy quality

def _maker_ctx():
    pb = load_playbook("ai-news-gtm")
    cand = {"title": "OpenAI launches GPT-6 with agentic browsing", "url": GPT6_URL,
            "source": "Hacker News", "points": 412, "num_comments": 188,
            "snippet": "OpenAI shipped GPT-6 today with agentic browsing built in."}
    return {"run_id": "copy-test", "playbook": pb, "picked": cand,
            "candidates": [cand] * 6, "evidence": [cand],
            "scores": {"total": 63.9}, "score_explanation": SCORE_EXPL,
            "topic": "AI agents", "tone": "clear", "review_notes": ""}


@pytest.fixture()
def fallback_llm(monkeypatch):
    class _Stub:
        mode = "fallback"

    monkeypatch.setattr(makers, "get_llm", lambda: _Stub())


def test_public_copy_never_quotes_score(fallback_llm):
    ctx = _maker_ctx()
    public = [makers.make_linkedin_post(ctx), makers.make_instagram_caption(ctx),
              makers.make_email(ctx), makers.make_reel_script(ctx)]
    for art in public:
        assert "63.9" not in art["content"], art["type"]
        assert not re.search(r"\d+(?:\.\d+)?\s*/\s*100", art["content"]), art["type"]
    briefing = makers.make_briefing(ctx)
    assert "63.9" in briefing["content"], "score belongs in the briefing"


def test_no_score_rule_in_public_prompts_only():
    assert "NEVER quote the internal rubric score" in makers._system_prompt(
        "linkedin_post", "clear")
    assert "NEVER quote" not in makers._system_prompt("briefing", "clear")
    assert "63.9/100" not in makers._scrub_scores(SCORE_EXPL)
    assert "topped the playbook rubric" in makers._scrub_scores(SCORE_EXPL)


def test_cap_truncates_at_word_boundary():
    assert makers._cap("aaaa bbbb cccc dddd", 10) == "aaaa…"
    long_title = ("An extraordinarily long headline about composable middleware "
                  "platforms for inference optimization at scale today")
    capped = makers._cap(long_title, 64)
    assert capped.endswith("…") and long_title.startswith(capped[:-1])
    assert long_title[len(capped) - 1] == " ", "cut must land on a word boundary"


def test_carousel_contents_heads_fit(fallback_llm):
    pb = load_playbook("ai-news-gtm")
    long_title = ("An extraordinarily long headline about composable middleware "
                  "platforms for inference optimization at scale today")
    cands = [{"title": long_title, "url": f"https://example.com/s{i}",
              "source": "Hacker News", "points": 400 - i * 10, "num_comments": 20,
              "snippet": ("A concrete development shipped today for developers. "
                          "It matters because teams were blocked on this problem. "
                          "Benchmarks and pricing are included in the release.")}
             for i in range(6)]
    ctx = {"run_id": "fit-test", "playbook": pb, "picked": cands[0],
           "candidates": cands, "evidence": cands[:5], "scores": {"total": 63.9},
           "score_explanation": SCORE_EXPL, "topic": "AI agents",
           "tone": "clear", "review_notes": ""}
    spec = makers._carousel_spec(ctx)
    for entry in spec["contents"]:
        head = entry["head"]
        assert len(head) <= 64
        if head.endswith("…"):
            assert long_title.startswith(head[:-1])
            assert long_title[len(head) - 1] == " ", f"mid-word cut in {head!r}"
    assert "/100" not in spec["slides"][0]["verdict"]
    assert "/100" not in spec["recap"]["take_sub"]
