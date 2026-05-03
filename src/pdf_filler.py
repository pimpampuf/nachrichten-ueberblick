"""Fill the school worksheet template by overlaying text via PyMuPDF.

Topic 3 and the personal reflection on page 3 are intentionally left blank.

Usage:
    python -m src.pdf_filler --static                          # smoke test
    python -m src.pdf_filler --json data.json --out output.pdf
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

# Whiteout disabled by user request: the printed underlines and "(Medium, Datum)"
# placeholders stay visible — text is written on top of them, matching the look
# of a handwritten/typed worksheet.
WHITEOUT_FIELDS: set[str] = set()


def _load_coords() -> dict[str, Any]:
    return json.loads(COORDS.read_text(encoding="utf-8"))


def _join_lines(items: list[str]) -> str:
    return "\n".join(s.strip() for s in items if s.strip())


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
        rect, text,
        fontsize=size,
        fontname=spec.get("font", "helv"),
        color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT,
    )
    if res < 0:
        # Overflow — shrink and retry once.
        page.insert_textbox(
            rect, text,
            fontsize=max(size - 1.5, 8.0),
            fontname=spec.get("font", "helv"),
            color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT,
        )


def _check_box(page: fitz.Page, spec: dict[str, Any]) -> None:
    """Draw an X through the checkbox, matching the example worksheet style."""
    cx, cy = spec["center"]
    r = spec["radius"]
    page.draw_line(fitz.Point(cx - r, cy - r), fitz.Point(cx + r, cy + r), color=(0, 0, 0), width=1.0)
    page.draw_line(fitz.Point(cx - r, cy + r), fitz.Point(cx + r, cy - r), color=(0, 0, 0), width=1.0)


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

        draw("title",      spec["title"],      topic["title"])
        draw("facts",      spec["facts"],      _join_lines(topic["facts"]))
        draw("relevance",  spec["relevance"],  topic["relevance"])
        draw("position_a", spec["position_a"], topic["position_a"])
        draw("position_b", spec["position_b"], topic["position_b"])

        # Sources: medium name in the meta slot, URL on the line below
        s1, s2 = topic["sources"][0], topic["sources"][1]
        draw("source1_meta", spec["source1_meta"], s1["medium"])
        draw("source1_url",  spec["source1_url"],  s1["url"])
        draw("source2_meta", spec["source2_meta"], s2["medium"])
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
        "name": "Pau Burmeister",
        "week_start": monday.isoformat(),
        "week_end": sunday.isoformat(),
        "topics": [
            {
                "title": "Reform der Krankenkasse",
                "category": "Inland",
                "facts": [
                    "Die Krankenkassen sollen reformiert werden.",
                    "Urspruenglich sollten 20 Mrd. eingespart werden, jetzt nur noch 16.",
                    "Aerzte, Krankenhaeuser und Konsumenten muessen einsparen.",
                ],
                "relevance": "Weil die Krankenkassen in Deutschland zu wenig Geld haben.",
                "position_a": "Die Regierung (CDU und SPD) wollen die gesetzliche Krankenversicherung entlasten.",
                "position_b": "Die Opposition meint, die Reformen belasten die Buerger zu stark und gefaehrden die Versorgung.",
                "sources": [
                    {"medium": "Tagesschau", "date": "2026-05-04", "title": "Reform der Krankenkasse",
                     "url": "https://www.tagesschau.de/inland/krankenkasse-100.html"},
                    {"medium": "ZDF heute", "date": "2026-05-04", "title": "Streit um Krankenkassen-Reform",
                     "url": "https://www.zdf.de/nachrichten/wirtschaft/krankenkasse-100.html"},
                ],
                "open_question": "Wie sollen die geplanten Einsparungen konkret finanziert werden?",
                "presentation_blurb": "Die Regierung plant Kuerzungen bei der Krankenversicherung. Statt 20 Mrd. werden 16 Mrd. eingespart.",
            },
            {
                "title": "Konjunktur Deutschland",
                "category": "Wirtschaft",
                "facts": [
                    "Das Bundeswirtschaftsministerium hat die Konjunkturprognose halbiert.",
                    "Das geschaetzte Wachstum liegt nur noch bei rund 0,5 Prozent.",
                    "Hauptgrund ist laut Ministerin Reiche der Krieg im Iran.",
                ],
                "relevance": "Weniger Wirtschaftsleistung bedeutet mehr Druck fuer die Politik und die Wirtschaft.",
                "position_a": "Die CDU verweist auf externe Geschehnisse wie den Iran-Krieg und will keine neuen Schulden aufnehmen.",
                "position_b": "Die SPD fordert staerkere Regulierung und Entlastungsprogramme fuer die Verbraucher.",
                "sources": [
                    {"medium": "Tagesschau", "date": "2026-05-03", "title": "Konjunkturprognose halbiert",
                     "url": "https://www.tagesschau.de/wirtschaft/konjunktur-100.html"},
                    {"medium": "Deutschlandfunk", "date": "2026-05-03", "title": "Bundesregierung halbiert Konjunkturprognose",
                     "url": "https://www.deutschlandfunk.de/bundesregierung-halbiert-konjunkturprognose-110.html"},
                ],
                "open_question": "Welche konkreten Entlastungsprogramme schlaegt die SPD vor?",
                "presentation_blurb": "Die Konjunkturprognose wurde halbiert. CDU sieht externe Gruende, SPD will mehr Entlastung.",
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    parser.add_argument("--json",   type=Path)
    parser.add_argument("--out",    type=Path, default=ROOT / "tests" / "output_static.pdf")
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
