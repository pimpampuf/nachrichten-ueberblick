"""Pick 2 Tagesschau topics + a matching secondary article each, via Claude.

Inputs:  the dict produced by news_fetcher (`tagesschau` + `secondary` lists).
Outputs: a list of two `{tagesschau, second}` article pairs ready for content_generator,
         each with full article text scraped on demand.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from anthropic import Anthropic
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.news_fetcher import fetch_article_text  # noqa: E402

MODEL = "claude-sonnet-4-6"

SELECTION_SYSTEM = """Du hilfst, zwei aktuelle politische Themen fuer ein Schul-Arbeitsblatt der 11. Klasse auszuwaehlen.

Auswahl-Kriterien:
1. Politische Relevanz (Gesellschaft, Staat, Wirtschaft, Klima, Migration, Sicherheit, Bildung, EU/International).
2. Mehrere Sichtweisen sichtbar (Regierung vs. Opposition, EU-Kommission vs. Mitgliedstaat, Industrie vs. Verband, ...).
3. In 1-2 Minuten in der Klasse erklaerbar.
4. Zwei UNTERSCHIEDLICHE Themen (nicht zweimal dasselbe aus verschiedenen Winkeln).

Vermeiden:
- Reine Live-Ticker-Eintraege (oft mit '++' am Anfang).
- Promi-, Sport-, Lokal-Nachrichten ohne politische Tragweite.
- Themen, zu denen keine zweite serioese Quelle gefunden wurde.

Du bekommst eine Liste Tagesschau-Artikel und Artikel aus ZDF heute, Deutschlandfunk, SZ und ZEIT. Waehle:
- 2 Tagesschau-Artikel als Hauptquelle (Index in der Tagesschau-Liste angeben).
- Pro Thema 1 passenden Artikel aus den anderen Quellen, der dasselbe Ereignis behandelt (Medium + Index angeben).
"""


class Pick(BaseModel):
    tagesschau_index: int = Field(description="0-basierter Index in der Tagesschau-Liste.")
    second_medium: str = Field(description="Eines von: 'ZDF heute', 'Deutschlandfunk', 'Sueddeutsche', 'ZEIT'.")
    second_index: int = Field(description="0-basierter Index in der Liste des gewaehlten Mediums.")
    reason: str = Field(description="1 Satz Begruendung.")


class Selection(BaseModel):
    picks: list[Pick] = Field(min_length=2, max_length=2)


def _format_candidates(items: list[dict], label: str) -> str:
    lines = [f"--- {label} ---"]
    for i, c in enumerate(items):
        topline = f" | {c['topline']}" if c.get("topline") else ""
        cat = f" [{c['category']}]" if c.get("category") else ""
        lines.append(
            f"[{i}]{cat} {c['date']} | {c['title']}{topline}\n"
            f"     {c.get('first_sentence', '')[:200]}\n"
            f"     {c['url']}"
        )
    return "\n".join(lines)


def select_topics(candidates: dict, *, api_key: str | None = None) -> list[Pick]:
    client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    blocks = [_format_candidates(candidates["tagesschau"], "Tagesschau")]
    for medium, items in candidates["secondary"].items():
        if items:
            blocks.append(_format_candidates(items, medium))
    user_prompt = "\n\n".join(blocks)

    response = client.messages.parse(
        model=MODEL,
        max_tokens=1500,
        system=SELECTION_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=Selection,
    )
    return response.parsed_output.picks


def _url_alive(url: str) -> bool:
    try:
        r = requests.head(url, allow_redirects=True, timeout=8.0,
                          headers={"User-Agent": "nachrichten-ueberblick/0.1"})
        if r.status_code == 405:  # some sites disallow HEAD
            r = requests.get(url, allow_redirects=True, timeout=8.0, stream=True,
                             headers={"User-Agent": "nachrichten-ueberblick/0.1"})
        return 200 <= r.status_code < 400
    except requests.RequestException:
        return False


def _date_recent(iso_date: str, *, max_days: int = 14) -> bool:
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        return False
    return (date.today() - d) <= timedelta(days=max_days)


def build_article_pairs(candidates: dict, picks: list[Pick]) -> list[dict]:
    pairs: list[dict] = []
    for pick in picks:
        ts = candidates["tagesschau"][pick.tagesschau_index]
        secondary_list = candidates["secondary"][pick.second_medium]
        sec = secondary_list[pick.second_index]

        for tag, candidate in (("Tagesschau", ts), (pick.second_medium, sec)):
            if not _url_alive(candidate["url"]):
                raise RuntimeError(f"URL nicht erreichbar ({tag}): {candidate['url']}")
            if not _date_recent(candidate["date"]):
                raise RuntimeError(f"Datum > 14 Tage ({tag}): {candidate['date']} {candidate['url']}")

        pairs.append({
            "tagesschau": {
                "title": ts["title"],
                "date": ts["date"],
                "url": ts["url"],
                "text": fetch_article_text(ts["url"]),
            },
            "second": {
                "medium": pick.second_medium,
                "title": sec["title"],
                "date": sec["date"],
                "url": sec["url"],
                "text": fetch_article_text(sec["url"]),
            },
        })
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=ROOT / "tests" / "candidates.json")
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "article_pairs.json")
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    picks = select_topics(candidates)
    for p in picks:
        print(f"  pick: TS[{p.tagesschau_index}] + {p.second_medium}[{p.second_index}] - {p.reason}")
    pairs = build_article_pairs(candidates, picks)
    args.out.write_text(json.dumps(pairs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
