"""Fetch candidate news articles for the week.

Source 1: Tagesschau homepage API (no key, returns clean JSON).
Source 2: RSS from one of ZDF heute / Deutschlandfunk / SZ / ZEIT (rotating).

Output: a dict with two lists of `Candidate` dicts ready for the topic selector.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

ROOT = Path(__file__).resolve().parents[1]

TAGESSCHAU_API = "https://www.tagesschau.de/api2u/homepage/"

RSS_FEEDS: dict[str, str] = {
    "ZDF heute":       "https://www.zdf.de/rss/zdf/nachrichten",
    "Deutschlandfunk": "https://www.deutschlandfunk.de/nachrichten-100.rss",
    "Sueddeutsche":    "https://rss.sueddeutsche.de/rss/Topthemen",
    "ZEIT":            "https://newsfeed.zeit.de/index",
}

# Tagesschau ressort -> our category mapping
RESSORT_TO_CATEGORY = {
    "inland":        "Inland",
    "ausland":       "International",
    "wirtschaft":    "Wirtschaft",
    "wissen":        "Gesellschaft",
    "investigativ":  "Inland",
}

# Drop these - not appropriate for a politics-focused worksheet.
EXCLUDED_RESSORTS = {"sport", "kultur", "wetter"}

USER_AGENT = "nachrichten-ueberblick/0.1 (school worksheet automation)"
MAX_AGE_DAYS = 14


@dataclass
class Candidate:
    medium: str
    title: str
    topline: str
    first_sentence: str
    category: str
    url: str
    date: str  # YYYY-MM-DD


def _within_window(dt: datetime, *, days: int = MAX_AGE_DAYS) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff


def _http_get(url: str, *, timeout: float = 15.0) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)


def fetch_tagesschau(limit: int = 25) -> list[Candidate]:
    resp = _http_get(TAGESSCHAU_API)
    resp.raise_for_status()
    data = resp.json()
    out: list[Candidate] = []
    for item in data.get("news", []):
        ressort = (item.get("ressort") or "").lower()
        if ressort in EXCLUDED_RESSORTS:
            continue
        url = item.get("shareURL") or item.get("detailsweb")
        date_raw = item.get("date")
        if not url or not date_raw:
            continue
        try:
            dt = date_parser.isoparse(date_raw)
        except (ValueError, TypeError):
            continue
        if not _within_window(dt):
            continue
        out.append(Candidate(
            medium="Tagesschau",
            title=item.get("title", "").strip(),
            topline=(item.get("topline") or "").strip(),
            first_sentence=(item.get("firstSentence") or "").strip(),
            category=RESSORT_TO_CATEGORY.get(ressort, "Sonstiges"),
            url=url,
            date=dt.date().isoformat(),
        ))
        if len(out) >= limit:
            break
    return out


def fetch_rss(medium: str, feed_url: str, limit: int = 15) -> list[Candidate]:
    parsed = feedparser.parse(feed_url, agent=USER_AGENT)
    out: list[Candidate] = []
    for entry in parsed.entries[: limit * 2]:
        url = entry.get("link")
        if not url:
            continue
        published = entry.get("published") or entry.get("updated")
        if not published:
            continue
        try:
            dt = date_parser.parse(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if not _within_window(dt):
            continue
        title = (entry.get("title") or "").strip()
        summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)
        out.append(Candidate(
            medium=medium,
            title=title,
            topline="",
            first_sentence=summary[:280],
            category="",  # category resolved later by the selector
            url=url,
            date=dt.date().isoformat(),
        ))
        if len(out) >= limit:
            break
    return out


def fetch_secondary(feed_names: Iterable[str] | None = None) -> dict[str, list[Candidate]]:
    """Pull from all configured RSS feeds (or a subset). Failures are skipped, not raised."""
    names = list(feed_names) if feed_names else list(RSS_FEEDS.keys())
    out: dict[str, list[Candidate]] = {}
    for name in names:
        try:
            out[name] = fetch_rss(name, RSS_FEEDS[name])
        except Exception as exc:
            print(f"[warn] {name}: {exc}", file=sys.stderr)
            out[name] = []
    return out


def fetch_article_text(url: str, *, max_chars: int = 6000) -> str:
    """Best-effort article body scrape. Returns concatenated <p> text."""
    try:
        resp = _http_get(url, timeout=15.0)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"[fetch failed: {exc}]"
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paragraphs if len(p) > 40)
    return text[:max_chars]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "candidates.json")
    args = parser.parse_args()

    primary = fetch_tagesschau()
    secondary = fetch_secondary()
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "tagesschau": [asdict(c) for c in primary],
        "secondary": {name: [asdict(c) for c in items] for name, items in secondary.items()},
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out} - tagesschau:{len(primary)} secondary:{sum(len(v) for v in secondary.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
