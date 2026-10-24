"""Scout tools — multi-source research sweep mirroring the production
AI News pipeline (~/workspace/ai-reel/detect/viral_watch.py). Key-free
sources, all failure-isolated (a dead source logs and the sweep moves on):

  - Hacker News front page (Algolia, tags=front_page) + HN query search
  - Reddit via the Arctic Shift archive API (per-playbook subreddits)
  - GDELT Doc API artlist (per-playbook keywords, real article titles/URLs)
  - Google Trends RSS (US) with approx_traffic
  - Editorial RSS/Atom feeds (per-playbook: TLDR AI, The Rundown, …)

Tavily is used only when TAVILY_API_KEY is present. Which sources run, and
with what subreddits / keywords / feeds / prefilter, is DATA from the
playbook's `research:` block — never hardcoded per playbook here.

Candidates from every source share one dict shape and are merged:
the same story seen by 2+ independent channels is deduplicated into one
candidate whose `source` lists every channel and whose `corroboration`
count feeds the Curator's Verification score (see graph.score_candidate).

Tools are also registered as LangChain tools and, where feasible, loaded
via MCP (langchain-mcp-adapters) — see load_mcp_tools(). A recorded
fixture is the last-resort fallback so the graph still runs offline.
"""
from __future__ import annotations

import html
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

FIXTURE = [
    {
        "title": "Show HN: An open-source multi-agent framework hits 1.0",
        "url": "https://news.ycombinator.com/item?id=40000001",
        "source": "Hacker News (recorded fixture)",
        "points": 412, "num_comments": 188,
        "snippet": "Recorded fixture candidate used only when live search returns nothing.",
        "created_at": "2026-10-24T00:00:00Z",
    },
    {
        "title": "AI agents move from demos to production workflows, teams report",
        "url": "https://news.ycombinator.com/item?id=40000002",
        "source": "Hacker News (recorded fixture)",
        "points": 296, "num_comments": 121,
        "snippet": "Recorded fixture candidate used only when live search returns nothing.",
        "created_at": "2026-10-24T00:00:00Z",
    },
]

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _proxy() -> str | None:
    # NOTE: this environment's NO_PROXY contains bracketed IPv6 entries that
    # crash httpx's env parsing — pass the egress proxy explicitly instead.
    return (os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
            or os.environ.get("http_proxy") or None)


def _get(url, **kw):
    return httpx.get(url, proxy=_proxy(), **kw)


def _log(msg: str) -> None:
    print(f"[prism-scout] {msg}", flush=True)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _iso_from_ts(ts) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _date_to_ts(s: str) -> float:
    """RSS/Atom date string -> epoch seconds (0 when unparseable)."""
    if not s:
        return 0
    s = s.strip()
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt.timestamp()
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.replace("Z", "+0000") if fmt.endswith("%z") else s, fmt) \
                .replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return 0


def _relevant(text: str, keywords: list[str]) -> bool:
    """Playbook-driven relevance prefilter (word-boundary match, so the
    keyword 'ai' does not fire inside 'said'). Empty list = keep all."""
    if not keywords:
        return True
    t = (text or "").lower()
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and re.search(r"\b" + re.escape(k) + r"\b", t):
            return True
    return False


# ---------------------------------------------------------------------------
# Source: Hacker News (Algolia) — front page poll + query search
# ---------------------------------------------------------------------------

def _hn_candidate(h: dict) -> dict:
    url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
    return {
        "title": h.get("title") or "(untitled)",
        "url": url,
        "source": "Hacker News",
        "points": h.get("points") or 0,
        "num_comments": h.get("num_comments") or 0,
        "snippet": _strip_html(h.get("story_text") or "")[:400],
        "created_at": h.get("created_at"),
    }


def fetch_hn(query: str, limit: int = 12) -> list[dict]:
    try:
        r = _get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": query, "tags": "story", "hitsPerPage": limit},
            timeout=20,
        )
        r.raise_for_status()
        return [_hn_candidate(h) for h in r.json().get("hits", [])]
    except Exception as exc:
        _log(f"HN search failed ({exc}); continuing")
        return []


def fetch_hn_frontpage(limit: int = 60) -> list[dict]:
    """The production sweep polls the HN front page (tags=front_page,
    hitsPerPage=60), not just query search — mirror that here."""
    try:
        r = _get(
            "https://hn.algolia.com/api/v1/search",
            params={"tags": "front_page", "hitsPerPage": limit},
            timeout=20,
        )
        r.raise_for_status()
        return [_hn_candidate(h) for h in r.json().get("hits", [])]
    except Exception as exc:
        _log(f"HN front page failed ({exc}); continuing")
        return []


# ---------------------------------------------------------------------------
# Source: Reddit via Arctic Shift (key-free archive API)
# ---------------------------------------------------------------------------

def fetch_reddit(subreddits: list[str], limit: int = 40, pacing: float = 1.0) -> list[dict]:
    out: list[dict] = []
    for i, sub in enumerate(subreddits or []):
        if i:
            time.sleep(pacing)  # be gentle: 1s between subreddit queries
        url = "https://arctic-shift.photon-reddit.com/api/posts/search"
        params = {"subreddit": sub, "limit": limit, "sort": "desc"}
        posts = None
        for attempt in (1, 2):
            try:
                r = _get(url, params=params, timeout=20, headers=_UA)
                r.raise_for_status()
                posts = r.json().get("data", [])
                break
            except Exception as exc:
                # Arctic Shift intermittently errors; one retry after a
                # short pause recovers most transient failures (donor rule).
                _log(f"Reddit r/{sub} attempt {attempt} failed ({exc})")
                if attempt == 1:
                    time.sleep(3)
        if posts is None:
            continue
        for p in posts:
            permalink = p.get("permalink") or ""
            ext = p.get("url") or ""
            link = ext if (ext.startswith("http") and "reddit.com" not in ext) \
                else (f"https://www.reddit.com{permalink}" if permalink else ext)
            out.append({
                "title": p.get("title") or "(untitled)",
                "url": link,
                "source": f"reddit:r/{sub}",
                "points": p.get("score") or 0,
                "num_comments": p.get("num_comments") or 0,
                "snippet": _strip_html(p.get("selftext") or "")[:400],
                "created_at": _iso_from_ts(p.get("created_utc")),
            })
    return out


# ---------------------------------------------------------------------------
# Source: GDELT Doc API — artlist of real articles per keyword
# ---------------------------------------------------------------------------

def fetch_gdelt(keywords: list[str], timespan: str = "24h", maxrecords: int = 50,
                pacing: float = 5.0) -> list[dict]:
    out: list[dict] = []
    for i, kw in enumerate(keywords or []):
        if i:
            time.sleep(pacing)  # GDELT asks >=5s between requests
        arts = None
        for attempt in (1, 2):
            try:
                r = _get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={"query": kw, "mode": "artlist", "format": "json",
                            "timespan": timespan, "maxrecords": maxrecords,
                            "sort": "datedesc"},
                    timeout=30,
                )
                r.raise_for_status()
                arts = r.json().get("articles", [])
                break
            except Exception as exc:
                # GDELT is 429-prone from shared egress IPs (donor note);
                # one paced retry, then the keyword is skipped, isolated.
                _log(f"GDELT '{kw}' attempt {attempt} failed ({exc})")
                if attempt == 1:
                    time.sleep(pacing)
        if arts is None:
            continue
        for a in arts:
            if not a.get("url") or not a.get("title"):
                continue
            created = None
            sd = a.get("seendate") or ""
            try:
                created = datetime.strptime(sd, "%Y%m%dT%H%M%SZ") \
                    .replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                created = sd or None
            out.append({
                "title": a.get("title") or "(untitled)",
                "url": a.get("url"),
                "source": "gdelt",
                "points": 0, "num_comments": 0,
                "snippet": "",
                "created_at": created,
            })
    return out


# ---------------------------------------------------------------------------
# Sources: Google Trends RSS + editorial RSS/Atom feeds
# ---------------------------------------------------------------------------

def _parse_feed(xml_text: str) -> list[dict]:
    """Minimal RSS2/Atom parser -> [{title, link, ts, desc, traffic,
    news_title, news_url, news_source}]. Mirrors the donor's parser and
    additionally surfaces Google Trends' nested news items."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for it in root.iter("item"):
        d = {"title": (it.findtext("title") or "").strip(),
             "link": (it.findtext("link") or "").strip(),
             "desc": _strip_html(it.findtext("description") or ""),
             "ts": _date_to_ts(it.findtext("pubDate") or ""),
             "traffic": 0, "news_title": "", "news_url": "", "news_source": ""}
        for child in it:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "approx_traffic":
                m = re.search(r"([\d,]+)", child.text or "")
                if m:
                    d["traffic"] = int(m.group(1).replace(",", ""))
            elif tag == "news_item":
                for sub in child:
                    stag = sub.tag.rsplit("}", 1)[-1]
                    if stag == "news_item_title" and not d["news_title"]:
                        d["news_title"] = _strip_html(sub.text or "")
                    elif stag == "news_item_url" and not d["news_url"]:
                        d["news_url"] = (sub.text or "").strip()
                    elif stag == "news_item_source" and not d["news_source"]:
                        d["news_source"] = _strip_html(sub.text or "")
        items.append(d)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for e in root.findall("a:entry", ns):
        title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = e.find("a:link", ns)
        link = (link_el.get("href") if link_el is not None else "").strip()
        pub = e.findtext("a:published", default="", namespaces=ns) or \
            e.findtext("a:updated", default="", namespaces=ns)
        summ = _strip_html(e.findtext("a:summary", default="", namespaces=ns) or "")
        items.append({"title": title, "link": link, "desc": summ,
                      "ts": _date_to_ts(pub), "traffic": 0,
                      "news_title": "", "news_url": "", "news_source": ""})
    return items


def fetch_trends(geo: str = "US") -> list[dict]:
    try:
        r = _get(f"https://trends.google.com/trending/rss?geo={geo}", timeout=20,
                 headers=_UA, follow_redirects=True)
        r.raise_for_status()
        items = _parse_feed(r.text)
    except Exception as exc:
        _log(f"Google Trends RSS failed ({exc}); continuing")
        return []
    out = []
    for it in items:
        if not it["title"]:
            continue
        snippet = it["news_title"]
        if it["news_source"]:
            snippet = f"{snippet} — via {it['news_source']}" if snippet else ""
        out.append({
            "title": it["title"],
            "url": it["news_url"] or it["link"],
            "source": "trends",
            # approx_traffic ("200K+") scaled onto the points axis Curator
            # heat expects; capped so one mega-trend can't swamp the pool.
            "points": min(600, (it["traffic"] or 0) // 1000),
            "num_comments": 0,
            "snippet": snippet[:400],
            "created_at": _iso_from_ts(it["ts"]) if it["ts"] else None,
        })
    return out


def _feed_label(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "feed").lower()).strip("-")


def fetch_editorial(feeds: list, per_feed: int = 25) -> list[dict]:
    out: list[dict] = []
    for feed in feeds or []:
        if isinstance(feed, dict):
            name, url = feed.get("name") or "Feed", feed.get("url") or ""
        else:
            name, url = str(feed), str(feed)
        if not url:
            continue
        try:
            r = _get(url, timeout=20, headers=_UA, follow_redirects=True)
            r.raise_for_status()
            items = _parse_feed(r.text)
        except Exception as exc:
            _log(f"Editorial feed {name} failed ({exc}); continuing")
            continue
        for it in items[:per_feed]:
            if not it["title"] or not it["link"]:
                continue
            out.append({
                "title": it["title"],
                "url": it["link"],
                "source": _feed_label(name),
                "points": 0, "num_comments": 0,
                "snippet": (it["desc"] or "")[:400],
                "created_at": _iso_from_ts(it["ts"]) if it["ts"] else None,
            })
    return out


# ---------------------------------------------------------------------------
# Source: Tavily (only when a key is configured)
# ---------------------------------------------------------------------------

def fetch_tavily(query: str, limit: int = 8) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    try:
        r = httpx.post(
            "https://api.tavily.com/search", proxy=_proxy(),
            json={"api_key": key, "query": query, "max_results": limit,
                  "topic": "news", "search_depth": "basic"},
            timeout=25,
        )
        r.raise_for_status()
        return [{
            "title": x.get("title") or "(untitled)",
            "url": x.get("url"),
            "source": "Tavily News",
            "points": int((x.get("score") or 0) * 500),
            "num_comments": 0,
            "snippet": (x.get("content") or "")[:400],
            "created_at": x.get("published_date"),
        } for x in r.json().get("results", []) if x.get("url")]
    except Exception:
        return []


def fetch_page_text(url: str, limit: int = 1200) -> str:
    try:
        r = _get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "PrismScout/0.1"})
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return _strip_html(r.text)[:limit]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Merge: dedupe + corroboration across channels
# ---------------------------------------------------------------------------

def _channel(label: str) -> str:
    """Map a source label to its independent channel (the production sweep
    counts HN / Reddit / GDELT / Trends / editorial as separate sources;
    every editorial feed together counts as the editorial channel)."""
    l = (label or "").lower()
    if l.startswith("hacker news"):
        return "hn"
    if l.startswith("reddit"):
        return "reddit"
    if l.startswith("gdelt"):
        return "gdelt"
    if l.startswith("trends"):
        return "trends"
    if l.startswith("tavily"):
        return "tavily"
    if "fixture" in l:
        return "fixture"
    return "editorial"


def _norm_url(url: str) -> str:
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("#", 1)[0].rstrip("/")
    if "?" in u:
        base, qs = u.split("?", 1)
        keep = [p for p in qs.split("&") if not p.startswith(("utm_", "ref=", "source="))]
        u = base + ("?" + "&".join(sorted(keep)) if keep else "")
    return u


def _title_tokens(title: str) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", (title or "").lower()).split())


def _is_discussion_url(url: str) -> bool:
    return "news.ycombinator.com/item" in (url or "") or "reddit.com" in (url or "")


def _merge_into(base: dict, extra: dict) -> None:
    for lab in (extra.get("source") or "").split(" + "):
        if lab and lab not in base["_labels"]:
            base["_labels"].append(lab)
    base["points"] = max(base.get("points", 0), extra.get("points", 0))
    base["num_comments"] = max(base.get("num_comments", 0), extra.get("num_comments", 0))
    if len(extra.get("snippet") or "") > len(base.get("snippet") or ""):
        base["snippet"] = extra["snippet"]
    if len(extra.get("title") or "") > len(base.get("title") or ""):
        base["title"] = extra["title"]
        base["_toks"] = _title_tokens(base["title"])
    # prefer a direct article URL over a discussion-thread URL as evidence
    if _is_discussion_url(base.get("url")) and not _is_discussion_url(extra.get("url")):
        base["url"] = extra["url"]
    if not base.get("created_at"):
        base["created_at"] = extra.get("created_at")


def merge_candidates(groups: list[list[dict]]) -> list[dict]:
    """Dedupe the same story across sources: same normalized URL, or
    near-identical normalized title (token Jaccard >= 0.8). A merged
    candidate's `source` lists every label that carried it and its
    `corroboration` counts the independent channels — the signal the
    Curator's Verification score rewards."""
    merged: list[dict] = []
    by_url: dict[str, dict] = {}
    for group in groups:
        for cand in group:
            if not cand.get("title"):
                continue
            key = _norm_url(cand.get("url") or "")
            match = by_url.get(key) if key else None
            if match is None:
                toks = _title_tokens(cand["title"])
                for m in merged:
                    mt = m["_toks"]
                    if toks and mt and len(toks & mt) / len(toks | mt) >= 0.8:
                        match = m
                        break
            if match is None:
                c = dict(cand)
                c["_labels"] = [cand.get("source") or ""]
                c["_toks"] = _title_tokens(cand["title"])
                merged.append(c)
                if key:
                    by_url[key] = c
            else:
                _merge_into(match, cand)
                k2 = _norm_url(match.get("url") or "")
                if k2:
                    by_url.setdefault(k2, match)
    for m in merged:
        labels = [l for l in m.pop("_labels") if l]
        m.pop("_toks", None)
        m["source"] = " + ".join(labels)
        channels = sorted({_channel(l) for l in labels})
        m["channels"] = channels
        m["corroboration"] = len(channels)
    merged.sort(key=lambda c: (c.get("points", 0), c.get("num_comments", 0)), reverse=True)
    return merged


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def scout_search(query: str, research: dict | None = None,
                 sources: list[str] | None = None) -> tuple[list[dict], list[str], dict]:
    """Returns (candidates, tool_calls_made, per-source counts).

    With a playbook `research:` block, query EVERY configured source
    family, merge + dedupe with corroboration, then enrich the top
    candidates' thin snippets with fetched page text. Without one, the
    legacy behaviour (Tavily-if-listed, else HN query search) applies.
    The recorded fixture is the last-resort fallback either way.
    """
    calls: list[str] = []
    stats: dict[str, int] = {}

    if not research:
        candidates: list[dict] = []
        if sources and any("tavily" in s for s in sources):
            candidates = fetch_tavily(query)
            calls.append("mcp:tavily-search" if candidates else "mcp:tavily-search (no key/results)")
            stats["tavily"] = len(candidates)
        if not candidates:
            candidates = fetch_hn(query)
            calls.append("hn-algolia")
            stats["hn"] = len(candidates)
        if not candidates:  # retry via second source with a broader query
            broader = query.split()[0] if query.split() else query
            candidates = fetch_hn(broader)
            calls.append("hn-algolia (retry, broader query)")
            stats["hn"] = len(candidates)
        if not candidates:
            candidates = merge_candidates([[dict(c) for c in FIXTURE]])
            calls.append("recorded-fixture (offline fallback)")
            stats["fixture"] = len(candidates)
        _enrich(candidates)
        return candidates, calls, stats

    keywords = research.get("prefilter_keywords") or []
    groups: list[list[dict]] = []

    def _add(channel: str, call: str, items: list[dict]) -> None:
        calls.append(f"{call} ×{len(items)}")
        stats[channel] = stats.get(channel, 0) + len(items)
        if items:
            groups.append(items)

    if research.get("tavily", True):
        items = fetch_tavily(query)
        calls.append("tavily-search" if items else "tavily-search (no key/results)")
        stats["tavily"] = len(items)
        if items:
            groups.append(items)

    fp_cfg = research.get("hn_frontpage")
    if fp_cfg:
        limit = fp_cfg.get("limit", 60) if isinstance(fp_cfg, dict) else 60
        raw = fetch_hn_frontpage(limit)
        items = [c for c in raw if _relevant(f"{c['title']} {c.get('snippet', '')}", keywords)]
        _add("hn", "hn-frontpage", items)

    hs_cfg = research.get("hn_search")
    if hs_cfg:
        limit = hs_cfg.get("limit", 12) if isinstance(hs_cfg, dict) else 12
        _add("hn", "hn-algolia", fetch_hn(query, limit))

    rd_cfg = research.get("reddit")
    if rd_cfg:
        subs = rd_cfg.get("subreddits") or []
        raw = fetch_reddit(subs, rd_cfg.get("limit", 40), rd_cfg.get("pacing", 1.0))
        items = [c for c in raw if _relevant(f"{c['title']} {c.get('snippet', '')}", keywords)]
        _add("reddit", "reddit", items)

    gd_cfg = research.get("gdelt")
    if gd_cfg:
        items = fetch_gdelt(gd_cfg.get("keywords") or [],
                            gd_cfg.get("timespan", "24h"),
                            gd_cfg.get("maxrecords", 50),
                            gd_cfg.get("pacing", 5.0))
        _add("gdelt", "gdelt", items)

    tr_cfg = research.get("trends")
    if tr_cfg:
        geo = tr_cfg.get("geo", "US") if isinstance(tr_cfg, dict) else "US"
        raw = fetch_trends(geo)
        items = [c for c in raw if _relevant(f"{c['title']} {c.get('snippet', '')}", keywords)]
        _add("trends", "trends", items)

    ed_cfg = research.get("editorial")
    if ed_cfg:
        raw = fetch_editorial(ed_cfg)
        items = [c for c in raw if _relevant(f"{c['title']} {c.get('snippet', '')}", keywords)]
        _add("editorial", "editorial", items)

    candidates = merge_candidates(groups)
    if not candidates:
        candidates = merge_candidates([[dict(c) for c in FIXTURE]])
        calls.append("recorded-fixture (offline fallback)")
        stats["fixture"] = len(candidates)
    stats["merged_total"] = len(candidates)
    stats["corroborated"] = sum(1 for c in candidates if (c.get("corroboration") or 1) >= 2)
    _enrich(candidates)
    return candidates, calls, stats


def _enrich(candidates: list[dict], top: int = 6) -> None:
    """Evidence enrichment: fill thin snippets of the top candidates with
    fetched page text — richer snippets drive maker copy quality.
    Discussion-thread URLs are skipped (their text is comments, not the
    story); any fetch failure simply leaves the snippet as-is."""
    for c in candidates[:top]:
        if len(c.get("snippet") or "") >= 150:
            continue
        url = c.get("url") or ""
        if not url or _is_discussion_url(url):
            continue
        text = fetch_page_text(url, 600)
        if len(text) > len(c.get("snippet") or ""):
            c["snippet"] = text[:500]


async def load_mcp_tools() -> list:
    """Load the Prism carousel MCP server's tools via langchain-mcp-adapters.
    Returns [] when MCP loading is unavailable — callers fall back to the
    in-process renderer module (server file remains present and runnable)."""
    try:
        import sys

        from langchain_mcp_adapters.client import MultiServerMCPClient

        from .config import CAROUSEL_DIR

        client = MultiServerMCPClient({
            "prism-carousel": {
                "command": sys.executable,
                "args": [str(CAROUSEL_DIR / "server.py")],
                "transport": "stdio",
            }
        })
        return await client.get_tools()
    except Exception:
        return []
