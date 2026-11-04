"""Generate the sample breakage photo used by the loss-reporting demo.

The photo door of /breakage works like the invoice photo door: the demo
vision step (app/vision.py) recognizes sample photos by content hash and
identifies them against a fixture registry (data/breakage_fixtures.json).
This renders the one sample — a case of Spring Water 24pk (WA-8101)
dropped in the back room, bottles burst on the concrete — as a simple
drawn "photo" in data/sample_breakage/<fixture-id>.jpg. Fictional data
only.

Run:  python3 tools/make_breakage_photo.py
"""
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sample_breakage"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _bottle(draw, x, y, scale=1.0, burst=False):
    """One water bottle standing at (x, y) — y is the base."""
    w, h = int(46 * scale), int(150 * scale)
    body = [x - w // 2, y - h, x + w // 2, y]
    if burst:
        # Jagged broken body, no cap — it burst on the concrete.
        pts = [(body[0], y), (body[0], y - int(h * 0.45)),
               (x - int(w * 0.15), y - int(h * 0.28)),
               (x + int(w * 0.1), y - int(h * 0.52)),
               (body[2], y - int(h * 0.38)), (body[2], y)]
        draw.polygon(pts, fill=(168, 208, 234), outline=(90, 130, 165))
        return
    draw.rounded_rectangle(body, radius=int(10 * scale),
                           fill=(168, 208, 234), outline=(90, 130, 165), width=2)
    draw.rectangle([x - int(w * 0.22), y - h - int(26 * scale),
                    x + int(w * 0.22), y - h + int(6 * scale)],
                   fill=(168, 208, 234), outline=(90, 130, 165))
    draw.rectangle([x - int(w * 0.26), y - h - int(38 * scale),
                    x + int(w * 0.26), y - h - int(24 * scale)],
                   fill=(28, 74, 140))
    draw.rectangle([x - int(w * 0.3), y - int(h * 0.62),
                    x + int(w * 0.3), y - int(h * 0.34)],
                   fill=(240, 246, 250))


def _bottle_down(draw, x, y, scale=1.0):
    """One bottle lying on its side at (x, y)."""
    w, h = int(150 * scale), int(46 * scale)
    draw.rounded_rectangle([x, y - h // 2, x + w, y + h // 2],
                           radius=int(10 * scale), fill=(168, 208, 234),
                           outline=(90, 130, 165), width=2)
    draw.rectangle([x + w, y - int(h * 0.22), x + w + int(28 * scale),
                    y + int(h * 0.22)], fill=(28, 74, 140))


def render(out_path):
    W, H = 1240, 930
    rng = random.Random(401)
    img = Image.new("RGB", (W, H), (196, 194, 188))
    draw = ImageDraw.Draw(img, "RGBA")
    # Back wall and concrete floor.
    draw.rectangle([0, 0, W, 600], fill=(172, 170, 164))
    draw.rectangle([0, 600, W, H], fill=(148, 146, 140))
    for _ in range(900):  # concrete speckle
        x, y = rng.randrange(W), rng.randrange(600, H)
        shade = rng.randrange(120, 175)
        draw.point((x, y), fill=(shade, shade, shade - 4))
    draw.line([0, 600, W, 600], fill=(110, 108, 102), width=3)

    # The puddle from the burst bottles.
    draw.ellipse([560, 700, 1130, 850], fill=(120, 170, 215, 150))
    draw.ellipse([640, 730, 1010, 820], fill=(105, 158, 205, 150))

    # Cardboard case, tipped, on the left.
    draw.polygon([(120, 690), (470, 690), (520, 790), (90, 790)],
                 fill=(178, 138, 84), outline=(120, 90, 50))
    draw.polygon([(120, 690), (470, 690), (420, 620), (170, 620)],
                 fill=(196, 156, 98), outline=(120, 90, 50))
    draw.polygon([(120, 690), (90, 790), (60, 660), (95, 610)],
                 fill=(160, 122, 72), outline=(120, 90, 50))  # torn flap
    # Case label.
    draw.rectangle([185, 700, 415, 762], fill=(242, 240, 232))
    draw.text((200, 712), "SPRING WATER 24PK", fill=(30, 30, 30),
              font=_font(FONT_BOLD, 25))
    draw.text((200, 738), "WA-8101", fill=(90, 90, 90), font=_font(FONT_PATH, 19))

    # Bottles still standing in the case, a few down, two burst.
    for bx in (215, 290, 365):
        _bottle(draw, bx, 690)
    _bottle_down(draw, 600, 700)
    _bottle_down(draw, 760, 780, scale=0.92)
    _bottle(draw, 700, 800, burst=True)
    _bottle(draw, 880, 815, burst=True)
    _bottle(draw, 1020, 760)

    # Footer strip, same convention as the invoice sample photos.
    draw.rectangle([0, H - 58, W, H], fill=(24, 28, 34))
    draw.text((36, H - 42),
              "Sample breakage photo (fictional) - Invoice Pay Agent demo",
              fill=(220, 224, 230), font=_font(FONT_PATH, 22))
    img.save(out_path, "JPEG", quality=90)
    return out_path


def main():
    fixtures = json.loads(
        (ROOT / "data" / "breakage_fixtures.json").read_text(encoding="utf-8")
    )["fixtures"]
    OUT_DIR.mkdir(exist_ok=True)
    for fx in fixtures:
        out = render(OUT_DIR / f"{fx['id']}.jpg")
        print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
