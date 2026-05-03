"""Generate the worksheet JSON via Claude (sonnet-4-6) from two pre-selected articles per topic.

Input shape (per topic, both required):
  {
    "tagesschau": {"title": str, "date": "YYYY-MM-DD", "url": str, "text": str},
    "second":     {"medium": str, "title": str, "date": "YYYY-MM-DD", "url": str, "text": str}
  }

Output: dict matching the JSON schema documented in the project plan.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.prompts import BANNED_PHRASES, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE  # noqa: E402

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4000

# Per-field hard caps (mirror the prompt; we enforce them in code regardless).
MAX_CHARS = {
    "title":              60,
    "facts_item":         95,
    "relevance":          160,
    "position":           200,
    "open_question":      140,
    "presentation_blurb": 280,
}


class Source(BaseModel):
    medium: str
    date: str  # YYYY-MM-DD
    title: str
    url: str


class Topic(BaseModel):
    title: str
    category: str  # one of the six categories
    facts: list[str] = Field(min_length=2, max_length=4)
    relevance: str
    position_a: str
    position_b: str
    sources: list[Source] = Field(min_length=2, max_length=2)
    open_question: str
    presentation_blurb: str


class Worksheet(BaseModel):
    topics: list[Topic] = Field(min_length=2, max_length=2)


def _truncate_at_word(text: str, max_chars: int) -> str:
    """Truncate at the last whole word boundary; no ellipsis. Preserves trailing punctuation."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    space = cut.rfind(" ")
    if space > max_chars * 0.5:
        cut = cut[:space]
    cut = cut.rstrip(",;:")
    if cut and cut[-1] not in ".!?":
        cut += "."
    return cut


def _enforce_caps(topic: dict[str, Any]) -> dict[str, Any]:
    topic["title"] = _truncate_at_word(topic["title"], MAX_CHARS["title"]).rstrip(".")
    topic["facts"] = [_truncate_at_word(f, MAX_CHARS["facts_item"]) for f in topic["facts"]]
    topic["relevance"]          = _truncate_at_word(topic["relevance"],          MAX_CHARS["relevance"])
    topic["position_a"]         = _truncate_at_word(topic["position_a"],         MAX_CHARS["position"])
    topic["position_b"]         = _truncate_at_word(topic["position_b"],         MAX_CHARS["position"])
    topic["open_question"]      = _truncate_at_word(topic["open_question"],      MAX_CHARS["open_question"])
    topic["presentation_blurb"] = _truncate_at_word(topic["presentation_blurb"], MAX_CHARS["presentation_blurb"])
    return topic


def _check_banned(text: str) -> list[str]:
    return [phrase for phrase in BANNED_PHRASES if phrase.lower() in text.lower()]


def _build_user_prompt(today: date, week_start: date, week_end: date, articles: list[dict]) -> str:
    a1, a2 = articles
    return USER_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        t1_s1_title=a1["tagesschau"]["title"],
        t1_s1_date=a1["tagesschau"]["date"],
        t1_s1_url=a1["tagesschau"]["url"],
        t1_s1_text=textwrap.shorten(a1["tagesschau"]["text"], width=4000, placeholder=" [...]"),
        t1_s2_medium=a1["second"]["medium"],
        t1_s2_title=a1["second"]["title"],
        t1_s2_date=a1["second"]["date"],
        t1_s2_url=a1["second"]["url"],
        t1_s2_text=textwrap.shorten(a1["second"]["text"], width=4000, placeholder=" [...]"),
        t2_s1_title=a2["tagesschau"]["title"],
        t2_s1_date=a2["tagesschau"]["date"],
        t2_s1_url=a2["tagesschau"]["url"],
        t2_s1_text=textwrap.shorten(a2["tagesschau"]["text"], width=4000, placeholder=" [...]"),
        t2_s2_medium=a2["second"]["medium"],
        t2_s2_title=a2["second"]["title"],
        t2_s2_date=a2["second"]["date"],
        t2_s2_url=a2["second"]["url"],
        t2_s2_text=textwrap.shorten(a2["second"]["text"], width=4000, placeholder=" [...]"),
    )


def _attempt_generation(client: Anthropic, user_prompt: str, retry_note: str = "") -> Worksheet:
    system = SYSTEM_PROMPT
    if retry_note:
        system += "\n\nKORREKTURHINWEIS:\n" + retry_note
    response = client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=Worksheet,
    )
    return response.parsed_output


def generate_worksheet(
    articles: list[dict],
    *,
    name: str,
    today: date | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
    user_prompt = _build_user_prompt(today, monday, sunday, articles)

    worksheet = _attempt_generation(client, user_prompt)

    flat = json.dumps(worksheet.model_dump(), ensure_ascii=False)
    bad = _check_banned(flat)
    if bad:
        worksheet = _attempt_generation(
            client, user_prompt,
            retry_note=f"Vermeide unbedingt diese Begriffe: {', '.join(bad)}.",
        )

    out = {
        "name": name,
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "week_number": monday.isocalendar().week,
        "topics": [_enforce_caps(t.model_dump()) for t in worksheet.topics],
    }
    # Pin source URLs and dates back to the input articles (defensive: if the model
    # rewrote a URL, restore the originals).
    for idx, art in enumerate(articles):
        src1 = out["topics"][idx]["sources"][0]
        src2 = out["topics"][idx]["sources"][1]
        src1["medium"] = "Tagesschau"
        src1["url"] = art["tagesschau"]["url"]
        src1["date"] = art["tagesschau"]["date"]
        src2["medium"] = art["second"]["medium"]
        src2["url"] = art["second"]["url"]
        src2["date"] = art["second"]["date"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock-articles", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "generated_content.json")
    parser.add_argument("--name", default=os.environ.get("STUDENT_NAME", "Pau"))
    args = parser.parse_args()

    articles = json.loads(args.mock_articles.read_text(encoding="utf-8"))
    data = generate_worksheet(articles, name=args.name)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
