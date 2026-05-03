"""Fill the school worksheet template by overlaying text via PyMuPDF.

Topic 3 and the personal reflection on page 3 are intentionally left blank.

Usage:
    python -m src.pdf_filler --static                          # smoke test with hardcoded German content
    python -m src.pdf_filler --json data.json --out output.pdf # fill with real content
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "template" / "vorlage_nachrichten.pdf"
COORDS = ROOT / "config" / "field_coords.json"

BULLET = "- "  # ASCII so it renders in built-in Helvetica (Latin-1) without the bullet -> ? fallback

# Fields whose rect overlaps printed placeholder text on the template
# (underlines, "(Medium, Datum)" hint, etc.). We draw a white backdrop first.
WHITEOUT_FIELDS = {
    "name", "week_start", "week_end",
    "title", "source1_meta", "source1_url", "source2_meta", "source2_url",
}


def _load_coords() -> dict[str, Any]:
    return json.loads(COORDS.read_text(encoding="utf-8"))


def _bullets(items: list[str]) -> str:
    return "\n".join(f"{BULLET}{s.strip()}" for s in items if s.strip())


def _draw_text(
    page: fitz.Page,
    spec: dict[str, Any],
    text: str,
    *,
    default_size: float,
    whiteout: bool = False,
) -> None:
    rect = fitz.Rect(*spec["rect"])
    if whiteout:
        page.draw_rect(rect, color=None, fill=(1, 1, 1), width=0)
    size = spec.get("font_size", default_size)
    res = page.insert_textbox(
        rect,
        text,
        fontsize=size,
        fontname=spec.get("font", "helv"),
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT,
    )
    if res < 0:
        # Negative return = overflow. Shrink and retry once.
        page.insert_textbox(
            rect,
            text,
            fontsize=max(size - 1.5, 7.0),
            fontname=spec.get("font", "helv"),
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT,
        )


def _check_box(page: fitz.Page, spec: dict[str, Any]) -> None:
    cx, cy = spec["center"]
    r = spec["radius"]
    page.draw_circle(fitz.Point(cx, cy), r, color=(0, 0, 0), fill=(0, 0, 0), width=0.5)


def _format_position(actor: str, statement: str) -> str:
    return f"{actor.strip()}: {statement.strip()}"


def _format_source_meta(source: dict[str, str]) -> str:
    return f"{source['medium']}, {source['date']} - {source['title']}"


def _draw_field(page: fitz.Page, spec: dict[str, Any], text: str, *, default_size: float, name: str) -> None:
    _draw_text(page, spec, text, default_size=default_size, whiteout=name in WHITEOUT_FIELDS)


def fill_pdf(data: dict[str, Any], out_path: Path) -> Path:
    coords = _load_coords()
    default_size = coords["default_font_size"]
    doc = fitz.open(TEMPLATE)

    def draw(field_name: str, spec: dict[str, Any], text: str) -> None:
        _draw_field(doc[spec["page"]], spec, text, default_size=default_size, name=field_name)

    # Header
    h = coords["header"]
    draw("name",       h["name"],       data.get("name", ""))
    draw("week_start", h["week_start"], data["week_start"])
    draw("week_end",   h["week_end"],   data["week_end"])

    for idx, key in enumerate(("topic1", "topic2"), start=0):
        topic = data["topics"][idx]
        spec = coords[key]

        cat = topic["category"]
        cat_specs = coords["category_checkboxes"][key]
        if cat in cat_specs:
            _check_box(doc[cat_specs[cat]["page"]], cat_specs[cat])

        draw("title",     spec["title"],     topic["title"])
        draw("facts",     spec["facts"],     _bullets(topic["facts"]))
        draw("relevance", spec["relevance"], _bullets(topic["relevance"]))
        draw("position_a", spec["position_a"], _format_position(topic["position_a"]["actor"], topic["position_a"]["statement"]))
        draw("position_b", spec["position_b"], _format_position(topic["position_b"]["actor"], topic["position_b"]["statement"]))

        s1, s2 = topic["sources"][0], topic["sources"][1]
        draw("source1_meta", spec["source1_meta"], _format_source_meta(s1))
        draw("source1_url",  spec["source1_url"],  s1["url"])
        draw("source2_meta", spec["source2_meta"], _format_source_meta(s2))
        draw("source2_url",  spec["source2_url"],  s2["url"])

        draw("open_question", spec["open_question"], topic["open_question"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path, deflate=True)
    doc.close()
    return out_path


def _example_data() -> dict[str, Any]:
    today = date(2026, 5, 6)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return {
        "name": "Pau",
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "topics": [
            {
                "title": "Bundesregierung beschliesst neues Klimapaket",
                "category": "Inland",
                "facts": [
                    "Kabinett hat ein neues Klimapaket beschlossen.",
                    "Geplant sind hoehere Foerderungen fuer Waermepumpen.",
                    "Industrie soll bis 2030 zusaetzliche CO2-Vorgaben erfuellen.",
                    "Das Paket muss noch durch Bundestag und Bundesrat.",
                ],
                "relevance": [
                    "Betrifft Heizkosten und Industrie in ganz Deutschland.",
                    "Wichtig fuer das Erreichen der Klimaziele bis 2030.",
                    "Loest Streit zwischen Koalitionspartnern aus.",
                ],
                "position_a": {
                    "actor": "Bundesregierung",
                    "statement": "Das Paket sei noetig, um die Klimaziele realistisch zu erreichen.",
                },
                "position_b": {
                    "actor": "Opposition (CDU/CSU)",
                    "statement": "Die Massnahmen seien zu teuer und belasteten Mittelstand und Familien.",
                },
                "sources": [
                    {
                        "medium": "Tagesschau",
                        "date": "2026-05-04",
                        "title": "Kabinett beschliesst neues Klimapaket",
                        "url": "https://www.tagesschau.de/inland/klimapaket-100.html",
                    },
                    {
                        "medium": "ZDF heute",
                        "date": "2026-05-04",
                        "title": "Streit um neue Klimaregeln",
                        "url": "https://www.zdf.de/nachrichten/politik/klimapaket-100.html",
                    },
                ],
                "open_question": "Wie genau sollen die hoeheren Foerderungen finanziert werden?",
                "presentation_blurb": "Die Regierung plant ein neues Klimapaket mit mehr Foerderung fuer Waermepumpen. Die Opposition haelt das fuer zu teuer.",
            },
            {
                "title": "EU-Gipfel zu Migrationspolitik in Bruessel",
                "category": "International",
                "facts": [
                    "Staats- und Regierungschefs der EU haben in Bruessel getagt.",
                    "Im Mittelpunkt stand die Reform der gemeinsamen Migrationspolitik.",
                    "Strittig sind die Verteilung von Gefluechteten und Aussengrenzschutz.",
                    "Eine Einigung wurde vertagt.",
                ],
                "relevance": [
                    "Migration ist eines der wichtigsten politischen Themen in Europa.",
                    "Beeinflusst Wahlen in mehreren EU-Laendern.",
                    "Zeigt, wie schwer EU-Staaten gemeinsame Loesungen finden.",
                ],
                "position_a": {
                    "actor": "EU-Kommission",
                    "statement": "Es brauche eine solidarische Verteilung und gemeinsame Standards.",
                },
                "position_b": {
                    "actor": "Mehrere osteuropaeische Regierungen",
                    "statement": "Sie lehnen verpflichtende Aufnahmequoten ab.",
                },
                "sources": [
                    {
                        "medium": "Tagesschau",
                        "date": "2026-05-03",
                        "title": "EU-Gipfel zu Migration ohne Einigung",
                        "url": "https://www.tagesschau.de/ausland/europa/eu-gipfel-migration-100.html",
                    },
                    {
                        "medium": "Deutschlandfunk",
                        "date": "2026-05-03",
                        "title": "EU streitet weiter ueber Migration",
                        "url": "https://www.deutschlandfunk.de/eu-migrationspolitik-100.html",
                    },
                ],
                "open_question": "Welche Position vertritt Deutschland konkret bei der Verteilungsfrage?",
                "presentation_blurb": "Beim EU-Gipfel ging es um eine Reform der Migrationspolitik. Streitpunkt ist die Verteilung von Gefluechteten zwischen den Mitgliedsstaaten.",
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", help="Fill with built-in example data.")
    parser.add_argument("--json", type=Path, help="Path to JSON file with worksheet data.")
    parser.add_argument("--out",  type=Path, default=ROOT / "tests" / "output_static.pdf")
    args = parser.parse_args()

    if args.static:
        data = _example_data()
    elif args.json:
        data = json.loads(args.json.read_text(encoding="utf-8"))
    else:
        parser.error("Pass --static or --json")
        return 2

    out = fill_pdf(data, args.out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
