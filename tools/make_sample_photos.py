"""Generate the sample invoice photos used by the photo-first demo.

Each fixture in data/extraction_fixtures.json is rendered as a plain
paper-style JPEG in data/sample_invoices/<fixture-id>.jpg — the photo a
manager would snap of the supplier's paper invoice. The demo vision step
(app/vision.py) recognizes these photos and reads them as the fixture's
verified raw text. Fictional data only.

Run:  python3 tools/make_sample_photos.py
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sample_invoices"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def render(raw_text, out_path):
    lines = raw_text.splitlines()
    font = _font(FONT_PATH, 30)
    font_head = _font(FONT_BOLD, 34)
    font_foot = _font(FONT_PATH, 20)
    width = 1240
    line_h = 52
    height = 150 + line_h * len(lines) + 90
    img = Image.new("RGB", (width, height), (253, 253, 248))
    draw = ImageDraw.Draw(img)
    draw.rectangle([18, 18, width - 18, height - 18], outline=(180, 180, 170), width=3)
    y = 70
    for i, line in enumerate(lines):
        draw.text((70, y), line, fill=(25, 25, 25),
                  font=font_head if i == 0 else font)
        y += line_h
    draw.text((70, height - 62),
              "Sample invoice photo (fictional) - Invoice Pay Agent demo",
              fill=(130, 130, 120), font=font_foot)
    img.save(out_path, "JPEG", quality=90)
    return out_path


def main():
    fixtures = json.loads(
        (ROOT / "data" / "extraction_fixtures.json").read_text(encoding="utf-8")
    )["fixtures"]
    OUT_DIR.mkdir(exist_ok=True)
    for fx in fixtures:
        out = render(fx["raw_invoice_text"], OUT_DIR / f"{fx['id']}.jpg")
        print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
