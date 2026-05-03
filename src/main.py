"""End-to-end orchestrator: fetch -> select -> generate -> fill PDF.

Splits the run into two CLI subcommands so the GitHub Action can commit the PDF
between them (PDF must exist on raw.githubusercontent.com BEFORE n8n is poked):

    python -m src.main build        # produces output/<date>.pdf and content.json
    python -m src.main notify       # POSTs to n8n with the PDF URL
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"

sys.path.insert(0, str(ROOT))

from src import content_generator, news_fetcher, pdf_filler, topic_selector, webhook_sender  # noqa: E402


def _week_start(today: date | None = None) -> date:
    today = today or date.today()
    from datetime import timedelta
    return today - timedelta(days=today.weekday())


def cmd_build() -> int:
    name = os.environ.get("STUDENT_NAME", "Pau")
    today = date.today()
    week = _week_start(today)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[build] week starting {week.isoformat()}")

    print("[build] fetching news...")
    candidates = {
        "fetched_at": today.isoformat(),
        "tagesschau": [c.__dict__ for c in news_fetcher.fetch_tagesschau()],
        "secondary": {
            name_: [c.__dict__ for c in items]
            for name_, items in news_fetcher.fetch_secondary().items()
        },
    }
    if len(candidates["tagesschau"]) < 4:
        raise SystemExit(f"too few Tagesschau candidates: {len(candidates['tagesschau'])}")

    print("[build] selecting topics...")
    picks = topic_selector.select_topics(candidates)
    for p in picks:
        print(f"  - TS[{p.tagesschau_index}] + {p.second_medium}[{p.second_index}] - {p.reason}")

    print("[build] scraping article text + validating URLs...")
    pairs = topic_selector.build_article_pairs(candidates, picks)

    print("[build] generating worksheet content...")
    worksheet = content_generator.generate_worksheet(pairs, name=name, today=today)

    content_path = OUTPUT_DIR / f"{week.isoformat()}.json"
    pdf_path = OUTPUT_DIR / f"{week.isoformat()}.pdf"
    content_path.write_text(json.dumps(worksheet, indent=2, ensure_ascii=False), encoding="utf-8")
    pdf_filler.fill_pdf(worksheet, pdf_path)
    print(f"[build] wrote {content_path}")
    print(f"[build] wrote {pdf_path}")
    return 0


def cmd_notify() -> int:
    week = _week_start()
    content_path = OUTPUT_DIR / f"{week.isoformat()}.json"
    if not content_path.exists():
        raise SystemExit(f"missing {content_path} - run `build` first")
    worksheet = json.loads(content_path.read_text(encoding="utf-8"))

    template = os.environ.get("PDF_URL_TEMPLATE")
    if not template:
        raise SystemExit("PDF_URL_TEMPLATE env var required for notify")
    pdf_url = template.format(date=worksheet["week_start"])

    webhook = os.environ.get("N8N_WEBHOOK_URL")
    if not webhook:
        raise SystemExit("N8N_WEBHOOK_URL env var required for notify")

    payload = webhook_sender.build_payload(worksheet, pdf_url)
    resp = webhook_sender.send(payload, webhook)
    print(f"[notify] posted to n8n status:{resp.status_code}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="Fetch, select, generate, and fill PDF.")
    sub.add_parser("notify", help="POST the existing worksheet to n8n.")
    args = parser.parse_args()

    if args.cmd == "build":
        return cmd_build()
    if args.cmd == "notify":
        return cmd_notify()
    return 2


if __name__ == "__main__":
    sys.exit(main())
