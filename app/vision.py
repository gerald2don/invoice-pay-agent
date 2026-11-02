"""Photo -> text: the vision step of the photo-first pipeline.

Production runs an OCR/vision model here. This demo build is
fixture-backed behind the same interface, so the whole flow runs with no
extra keys: data/sample_invoices/<fixture-id>.jpg are the sample photos of
the ground-truth fixtures in data/extraction_fixtures.json (rendered by
tools/make_sample_photos.py). An uploaded photo is recognized by content
hash — exact SHA-256 first, then a perceptual hash so a re-saved or
lightly resized copy still matches — and read as that fixture's verified
raw invoice text, the same text app/extraction.py is checked against.

A photo that matches no sample returns None. Nothing is guessed: the
manager is routed to the paste door with the photo unrecognized.
"""
import hashlib
import io
import json

from PIL import Image

from . import data

SAMPLE_DIR = data.DATA_DIR / "sample_invoices"
_AHASH_SIZE = 16
_AHASH_MAX_DISTANCE = 26  # of 256 bits (~10%) — re-encodes pass, others don't


def _fixtures():
    with open(data.DATA_DIR / "extraction_fixtures.json", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def _ahash(image_bytes):
    """256-bit average hash of an image, or None if it cannot be read."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:
        return None
    img = img.resize((_AHASH_SIZE, _AHASH_SIZE))
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return bits


def _samples():
    """Sample photo registry: fixture id -> photo path + expected summary."""
    out = []
    for fx in _fixtures():
        path = SAMPLE_DIR / f"{fx['id']}.jpg"
        if not path.exists():
            continue
        exp = fx["expected"]
        supplier = data.SUPPLIERS.get(fx["supplier_id"], {})
        out.append({
            "fixture_id": fx["id"],
            "filename": path.name,
            "path": path,
            "raw_text": fx["raw_invoice_text"],
            "number": exp.get("number"),
            "total": exp.get("total"),
            "supplier_name": supplier.get("name"),
        })
    return out


def sample_photos():
    """Public sample list for the extract screen (no filesystem paths)."""
    return [{k: s[k] for k in ("fixture_id", "filename", "number", "total",
                               "supplier_name")}
            for s in _samples()]


def sample_path(filename):
    """Resolve a sample photo filename to its path, or None."""
    for s in _samples():
        if s["filename"] == filename:
            return s["path"]
    return None


def read_invoice_photo(image_bytes):
    """Recognize an invoice photo and return its raw invoice text.

    Returns {"fixture_id", "raw_text", "method"} where method is "exact"
    (byte-identical sample photo) or "perceptual" (re-saved copy matched
    by image hash) — or None when the photo matches no sample invoice.
    """
    if not image_bytes:
        return None
    samples = _samples()
    digest = hashlib.sha256(image_bytes).hexdigest()
    for s in samples:
        if hashlib.sha256(s["path"].read_bytes()).hexdigest() == digest:
            return {"fixture_id": s["fixture_id"],
                    "raw_text": s["raw_text"], "method": "exact"}
    probe = _ahash(image_bytes)
    if probe is None:
        return None
    best, best_dist = None, None
    for s in samples:
        ref = _ahash(s["path"].read_bytes())
        if ref is None:
            continue
        dist = bin(probe ^ ref).count("1")
        if best_dist is None or dist < best_dist:
            best, best_dist = s, dist
    if best is not None and best_dist <= _AHASH_MAX_DISTANCE:
        return {"fixture_id": best["fixture_id"],
                "raw_text": best["raw_text"], "method": "perceptual"}
    return None
