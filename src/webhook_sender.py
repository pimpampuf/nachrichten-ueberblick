"""POST the worksheet metadata + PDF URL to the n8n webhook.

Reads N8N_WEBHOOK_URL and the worksheet JSON from disk, builds the payload, and posts.
n8n then sends Telegram messages and downloads the PDF from the URL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PDF_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/USER/nachrichten-ueberblick/main/output/{date}.pdf"
)


def build_payload(worksheet: dict, pdf_url: str) -> dict:
    return {
        "week_start": worksheet["week_start"],
        "week_end": worksheet["week_end"],
        "week_number": worksheet["week_number"],
        "name": worksheet["name"],
        "pdf_url": pdf_url,
        "topics": [
            {
                "title": t["title"],
                "category": t["category"],
                "presentation_blurb": t["presentation_blurb"],
                "sources": [
                    {"medium": s["medium"], "url": s["url"], "date": s["date"]}
                    for s in t["sources"]
                ],
            }
            for t in worksheet["topics"]
        ],
    }


def send(payload: dict, webhook_url: str, *, timeout: float = 30.0) -> requests.Response:
    resp = requests.post(webhook_url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worksheet", type=Path, required=True,
                        help="Path to the worksheet JSON written by content_generator.")
    parser.add_argument("--pdf-url", type=str, default=None,
                        help="Public URL of the generated PDF. Defaults to PDF_URL_TEMPLATE env or built-in pattern.")
    parser.add_argument("--webhook-url", type=str, default=os.environ.get("N8N_WEBHOOK_URL"))
    parser.add_argument("--dry-run", action="store_true", help="Print the payload instead of POSTing.")
    args = parser.parse_args()

    worksheet = json.loads(args.worksheet.read_text(encoding="utf-8"))

    template = os.environ.get("PDF_URL_TEMPLATE", DEFAULT_PDF_URL_TEMPLATE)
    pdf_url = args.pdf_url or template.format(date=worksheet["week_start"])
    payload = build_payload(worksheet, pdf_url)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not args.webhook_url:
        print("ERROR: --webhook-url or N8N_WEBHOOK_URL required.", file=sys.stderr)
        return 2

    resp = send(payload, args.webhook_url)
    print(f"posted to n8n - status:{resp.status_code} body_len:{len(resp.text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
