"""Dump every text span in the template PDF with its bbox.

Run once to map field labels to (x, y) coordinates. Output goes to
tests/template_layout.txt - used to author config/field_coords.json by hand.
"""
import fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "template" / "vorlage_nachrichten.pdf"
OUT = ROOT / "tests" / "template_layout.txt"


def main() -> None:
    doc = fitz.open(TEMPLATE)
    lines = []
    for i, page in enumerate(doc):
        lines.append(f"=== Page {i} ({page.rect.width:.1f} x {page.rect.height:.1f}) ===")
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    t = span["text"].rstrip()
                    if not t:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    lines.append(f"p{i}  x={x0:6.1f}  y={y0:6.1f}  w={x1-x0:5.1f}  h={y1-y0:4.1f}  | {t}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(lines)} lines to {OUT}")


if __name__ == "__main__":
    main()
