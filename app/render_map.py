"""Store map renderer for the Shelf Guide.

Drawn from the pilot store manager's own hand sketch (worker's POV: behind
the counter looking out). Six gondola runs, the Beer Cave walk-in at the
northwest corner, the west-wall door bank, and the register front. A zone
key places the finder dot. The store's owners have cleared this
layout/location material for the demo.
"""
import io
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

W, H = 1400, 1050
BAR_W, BAR_GAP, BAR_X0, BAR_Y1 = 148, 48, 210, 700

# (key, label, top_y, cave-end note, face note, front-end note)
BARS = [
    ("tequila",  "TEQUILA / MIXER", 300, "", "W face: Mixer - E face: Tequila", "On The Rocks RTD endcap at this end"),
    ("vodka",    "VODKA / BOURBON", 300, "", "W face: Vodka - E face: Bourbon 1", ""),
    ("bourbon",  "BOURBON / RYE", 290, "flavored / moonshine at this end", "W face: Bourbon 2 - E face: Rye", ""),
    ("import",   "IMPORT / GIN-RUM", 280, "", "W face: Import (scotch + world) - E face: Gin + Rum", "minis endcap at this end"),
    ("liqueurs", "LIQUEURS / RED WINE", 265, "", "W face: Liqueurs (cordials) - E face: Red wine", "boxed wine at front end"),
    ("wine",     "WHITE WINE / FRUITY-LOCAL", 235, "sparkling at this end", "W face: White wine - E face: Fruity / Local", ""),
]
WEST_DOORS = ["SODA", "ENERGY", "SPORTS / JUICE", "NA", "EMPTY (ex-THC)", "EMPTY (ex-THC)"]
STRIP_X0, STRIP_X1, STRIP_Y0, STRIP_Y1 = 40, 172, 185, 700
CELL_H = (STRIP_Y1 - STRIP_Y0) / len(WEST_DOORS)


def _bar_x(i):
    return BAR_X0 + i * (BAR_W + BAR_GAP)


def _west_center(i):
    return ((STRIP_X0 + STRIP_X1) // 2, int(STRIP_Y1 - CELL_H * (i + 0.5)))


def _face(i, side, ty=None, y=None):
    x = _bar_x(i) + BAR_W // 2 + (-34 if side == "W" else 34)
    if y is None:
        top = BARS[i][2] if ty is None else ty
        y = (top + BAR_Y1) // 2
    return (x, y)


ZONES = {}
for _i, (_key, _l, _ty, *_r) in enumerate(BARS):
    ZONES[_key] = (_bar_x(_i) + BAR_W // 2, (_ty + BAR_Y1) // 2)
ZONES.update({
    "mixer": _face(0, "W"), "tequila": _face(0, "E"),
    "vodka": _face(1, "W"), "bourbon": _face(2, "W"), "rye": _face(2, "E"),
    "bourbon_east": _face(1, "E"), "jimbeam": _face(1, "E"),
    "import": _face(3, "W"), "scotch": _face(3, "W"), "ginrum": _face(3, "E"),
    "liqueurs": _face(4, "W"), "cordials": _face(4, "W"), "redwine": _face(4, "E"),
    "whitewine": _face(5, "W"), "fruity": _face(5, "E"),
    "sparkling": _face(5, "E", y=235 + 70),
    "boxed": (_bar_x(4) + BAR_W // 2, BAR_Y1 - 70),
    "moonshine": (_bar_x(2) + BAR_W // 2, 290 + 70),
    "otr": (_bar_x(0) + BAR_W // 2, BAR_Y1 - 70),
    "minis": (_bar_x(3) + BAR_W // 2, BAR_Y1 - 70),
    "cave_soda": _west_center(0), "cave_energy": _west_center(1),
    "cave_juice": _west_center(2), "cave_na": _west_center(3),
    "cave_import": (445, 118), "cave_domestic": (272, 118),
    "cave_seltzer": (930, 118), "cave_craft": (1230, 118),
    "cave_fmb": (1090, 118), "cave_singles": (560, 118),
    "front": (700, 905), "behind_counter": (1130, 905), "entrance": (200, 905),
})


def _font(sz, bold=True):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(p, sz)
    except Exception:
        return ImageFont.load_default()


def _wrap(d, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


@lru_cache(maxsize=64)
def render_map(zone=None):
    """Render the store map PNG (bytes), with the finder dot on `zone`."""
    img = Image.new("RGB", (W, H), (24, 28, 34))
    d = ImageDraw.Draw(img)
    d.text((44, 20), "A1 LIQUORS - DOWNTOWN  -  STORE MAP (worker's POV)", font=_font(27), fill=(255, 255, 255))

    # Back wall: Beer Cave walk-in at the far west, then the cooler doors.
    d.polygon([(40, 165), (40, 70), (360, 70), (280, 165)], fill=(64, 78, 98), outline=(255, 214, 120))
    d.rounded_rectangle([40, 70, 360, 165], radius=12, outline=(255, 214, 120), width=2)
    d.text((62, 88), "BEER CAVE", font=_font(26), fill=(255, 214, 120))
    d.text((62, 124), "walk-in - case stacks", font=_font(15, bold=False), fill=(255, 214, 120))
    d.rounded_rectangle([375, 70, 1360, 165], radius=12, fill=(52, 64, 82), outline=(150, 165, 185), width=2)
    d.text((400, 88), "BEER & RTD COOLER DOORS - BACK WALL", font=_font(23), fill=(255, 255, 255))
    d.text((400, 124), "imports - domestic packs - seltzer / RTD - canned cocktails - cider / FMB - craft", font=_font(18, bold=False), fill=(200, 210, 225))

    # West wall door bank
    for i, name in enumerate(WEST_DOORS):
        y1 = STRIP_Y1 - CELL_H * i
        y0 = y1 - CELL_H
        fill = (58, 70, 88) if name != "NA" else (74, 88, 60)
        d.rounded_rectangle([STRIP_X0, y0 + 3, STRIP_X1, y1 - 3], radius=8, fill=fill,
                            outline=(255, 214, 120) if name == "NA" else (150, 165, 185),
                            width=3 if name == "NA" else 2)
        lines = _wrap(d, name, _font(16), STRIP_X1 - STRIP_X0 - 12)
        ly = (y0 + y1) / 2 - 11 * len(lines)
        for line in lines:
            d.text(((STRIP_X0 + STRIP_X1) / 2, ly), line, font=_font(16), fill=(255, 255, 255), anchor="ma")
            ly += 22
    d.text((STRIP_X0, STRIP_Y1 + 8), "west wall doors - humidor near front", font=_font(14, bold=False), fill=(170, 182, 200))

    for i, (key, label, ty, cave_note, face_note, front_note) in enumerate(BARS):
        x0 = _bar_x(i)
        d.rounded_rectangle([x0, ty, x0 + BAR_W, BAR_Y1], radius=12, fill=(70, 84, 104), outline=(150, 165, 185), width=2)
        ly = ty + 120
        for line in _wrap(d, label, _font(21), BAR_W - 14):
            d.text((x0 + BAR_W // 2, ly), line, font=_font(21), fill=(255, 255, 255), anchor="ma")
            ly += 27
        if cave_note:
            ny = ty + 14
            for line in _wrap(d, cave_note, _font(14, bold=False), BAR_W - 12):
                d.text((x0 + BAR_W // 2, ny), line, font=_font(14, bold=False), fill=(255, 214, 120), anchor="ma")
                ny += 18
        if face_note:
            lines = _wrap(d, face_note, _font(15, bold=False), BAR_W - 12)
            ny = (ty + BAR_Y1) // 2 + 55
            for line in lines:
                d.text((x0 + BAR_W // 2, ny), line, font=_font(15, bold=False), fill=(200, 210, 225), anchor="ma")
                ny += 20
        if front_note:
            lines = _wrap(d, front_note, _font(14, bold=False), BAR_W - 12)
            ny = BAR_Y1 - 14 - 18 * len(lines)
            for line in lines:
                d.text((x0 + BAR_W // 2, ny), line, font=_font(14, bold=False), fill=(190, 205, 225), anchor="ma")
                ny += 18

    # Front: entrance / register+BuzzBallz / cups-tobacco-snacks wall
    d.rounded_rectangle([40, 845, 1360, 950], radius=12, fill=(52, 64, 82), outline=(150, 165, 185), width=2)
    d.text((60, 862), "ENTRANCE", font=_font(20), fill=(255, 255, 255))
    d.text((60, 892), "behind counter: pints - minis tower", font=_font(16, bold=False), fill=(200, 210, 225))
    d.text((430, 862), "REGISTER  +  BuzzBallz rack", font=_font(20), fill=(255, 255, 255))
    d.text((430, 892), "counter island, worker's POV looking out", font=_font(16, bold=False), fill=(200, 210, 225))
    d.text((940, 862), "CUPS / TOBACCO / SNACKS", font=_font(20), fill=(255, 255, 255))
    d.text((940, 892), "back wall, worker's right of the register", font=_font(16, bold=False), fill=(200, 210, 225))

    if zone in ZONES:
        cx, cy = ZONES[zone]
        for r in (30, 19):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 235, 0), width=5)
        d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(255, 60, 40), outline=(255, 255, 255), width=3)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
