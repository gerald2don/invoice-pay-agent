"""Photo -> facts: the vision step of the photo-first pipeline.

Two readers sit behind this one interface, in order:

1. THE MODEL (app/vision_model.py) — when GEMINI_API_KEY is configured,
   the photo is read live by Google's Gemini vision model, which
   returns the invoice's structured content; that read is serialized
   into the pipeline's invoice text and handed to app/extraction.py.
   The model perceives; every decision after that (item-master
   matching, confidence, flags, approval, payment) is the project's
   own layer, unchanged.
2. THE FIXTURE FALLBACK — with no key configured, or whenever the model
   read fails, the photo is matched against the demo's sample invoices
   by content hash, exact SHA-256 first, then a perceptual hash so a
   re-saved or lightly resized copy still matches:
   data/sample_invoices/<fixture-id>.jpg are the sample photos of the
   ground-truth fixtures in data/extraction_fixtures.json (rendered by
   tools/make_sample_photos.py), read as the fixture's verified raw
   invoice text, the same text app/extraction.py is checked against.

So the whole flow runs with no extra keys, and the model path can never
break the hosted demo: worst case it falls back to the samples.

A photo neither reader can read returns None. Nothing is guessed: the
manager is routed to the paste door with the photo unrecognized.

The same mechanism backs the breakage photo door (/breakage):
data/sample_breakage/<fixture-id>.jpg are the sample loss photos in
data/breakage_fixtures.json (rendered by tools/make_breakage_photo.py),
each mapped to the item-master SKU in the picture. An uploaded photo is
matched the same way and identifies the product that was lost — the
count itself is always confirmed by a person before inventory moves.
"""
import hashlib
import io
import json

from PIL import Image

from . import data, vision_model

SAMPLE_DIR = data.DATA_DIR / "sample_invoices"
BREAKAGE_DIR = data.DATA_DIR / "sample_breakage"
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


def _match_photo(image_bytes, paths):
    """Which of the sample photos an upload matches: (index, method) with
    method "exact" (byte-identical) or "perceptual" (re-saved copy matched
    by image hash) — or None when it matches no sample."""
    if not image_bytes:
        return None
    digest = hashlib.sha256(image_bytes).hexdigest()
    for i, path in enumerate(paths):
        if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            return i, "exact"
    probe = _ahash(image_bytes)
    if probe is None:
        return None
    best, best_dist = None, None
    for i, path in enumerate(paths):
        ref = _ahash(path.read_bytes())
        if ref is None:
            continue
        dist = bin(probe ^ ref).count("1")
        if best_dist is None or dist < best_dist:
            best, best_dist = i, dist
    if best is not None and best_dist <= _AHASH_MAX_DISTANCE:
        return best, "perceptual"
    return None


_LAST_MODEL_ERROR = {"msg": None}


def last_model_error():
    """The most recent vision-model failure message, or None."""
    return _LAST_MODEL_ERROR["msg"]


def read_invoice_photo(image_bytes):
    """Read an invoice photo and return its raw invoice text.

    The vision model reads first when it is configured (method "model",
    with the model name and the model's structured read attached); the
    fixture hash match is the automatic fallback — and the only path
    when no model key is set. Fixture reads return method "exact"
    (byte-identical sample photo) or "perceptual" (re-saved copy
    matched by image hash). Returns None when neither reader can read
    the photo.
    """
    if image_bytes and vision_model.configured():
        try:
            read = vision_model.read_invoice(image_bytes)
            _LAST_MODEL_ERROR["msg"] = None
            return {"fixture_id": None, "raw_text": read["raw_text"],
                    "method": "model", "model": read["model"],
                    "structured": read["structured"]}
        except vision_model.ModelVisionError as exc:
            _LAST_MODEL_ERROR["msg"] = str(exc)
            pass  # fall through to the fixture fallback below
    samples = _samples()
    match = _match_photo(image_bytes, [s["path"] for s in samples])
    if match is None:
        return None
    s, method = samples[match[0]], match[1]
    return {"fixture_id": s["fixture_id"],
            "raw_text": s["raw_text"], "method": method}


def _breakage_fixtures():
    try:
        with open(data.DATA_DIR / "breakage_fixtures.json", encoding="utf-8") as f:
            return json.load(f)["fixtures"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def _breakage_samples():
    """Breakage photo registry: fixture id -> photo path + the SKU in it."""
    out = []
    for fx in _breakage_fixtures():
        path = BREAKAGE_DIR / f"{fx['id']}.jpg"
        if not path.exists():
            continue
        item = data.ITEM_MASTER.get(fx["sku"], {})
        out.append({
            "fixture_id": fx["id"],
            "filename": path.name,
            "path": path,
            "sku": fx["sku"],
            "product": item.get("name", fx["sku"]),
            "description": fx.get("description", ""),
        })
    return out


def breakage_sample_photos():
    """Public sample list for the breakage screen (no filesystem paths)."""
    return [{k: s[k] for k in ("fixture_id", "filename", "sku", "product",
                               "description")}
            for s in _breakage_samples()]


def breakage_sample_path(filename):
    """Resolve a sample breakage photo filename to its path, or None."""
    for s in _breakage_samples():
        if s["filename"] == filename:
            return s["path"]
    return None


def read_breakage_photo(image_bytes):
    """Recognize a breakage photo and identify the product in it.

    Returns {"fixture_id", "filename", "sku", "product", "method"} — the
    same exact/perceptual hash matching as the invoice door — or None
    when the photo matches no sample breakage photo.
    """
    samples = _breakage_samples()
    match = _match_photo(image_bytes, [s["path"] for s in samples])
    if match is None:
        return None
    s, method = samples[match[0]], match[1]
    return {"fixture_id": s["fixture_id"], "filename": s["filename"],
            "sku": s["sku"], "product": s["product"], "method": method}
