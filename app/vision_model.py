"""The real vision model behind the photo door: photo -> structured facts.

app/vision.py owns the door; this module is the perception step it calls
first whenever a model key is configured. The model (Google Gemini, via
its REST API — no SDK, just the httpx the app already ships) reads the
uploaded invoice photo and returns the invoice's structured content:
vendor, invoice number, date, line items, surcharges, credit lines, and
the printed total.

That structured read is then serialized into the canonical invoice-text
format app/extraction.py parses, so everything downstream — fuzzy
item-master matching, per-line confidence, surcharge/credit handling,
manager approval, the ledger, the PayPal payout — is the project's own
decision layer, unchanged. The model perceives; the agent decides.

Configuration (environment):
- GEMINI_API_KEY — enables this path. Without it, configured() is False
  and vision.py stays on its fixture-hash fallback, so the hosted demo
  runs with no extra keys and can never break on a missing key.
- GEMINI_MODEL — optional; defaults to gemini-2.5-flash.

Any failure here (no key, HTTP error, malformed or incomplete JSON)
raises ModelVisionError and vision.py falls back to fixture matching.
Nothing is guessed: a read that fails validation is a failed read.
"""
import base64
import io
import json
import os

import httpx
from PIL import Image

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"
_TIMEOUT_SECONDS = 60
_MAX_IMAGE_DIM = 2048  # px — downscale phone photos before upload

PROMPT = """You are the perception step of an invoice-processing agent.
Transcribe the supplier invoice in this photo into JSON. Transcribe
exactly what is printed — do not correct arithmetic, do not invent
values, and do not omit lines.

Return ONLY a JSON object with this shape:
{
  "vendor_name": "the supplier/vendor name printed on the invoice",
  "invoice_number": "the invoice number as printed, or null",
  "date": "the invoice date as M/D/YYYY, or null",
  "lines": [
    {"description": "full product description as printed",
     "quantity": quantity from the quantity column (number),
     "unit_cost": price per that quantity unit, after discounts if a
                  net price column is printed (number),
     "extended": line total as printed (number)}
  ],
  "surcharges": [{"label": "e.g. FUEL SURCHARGE", "amount": number}],
  "credits": [{"description": "credit line text",
               "memo": "credit memo number if printed, else null",
               "amount": number}],
  "printed_total": the invoice's printed amount due / total (number),
                   or null if not visible
}

Rules:
- Every product line on the invoice appears once in "lines", in order.
- Surcharges, fees, and taxes are NOT product lines: put them in
  "surcharges".
- Credit-memo / vendor-credit lines are NOT product lines: put them in
  "credits".
- If a value is not printed or not legible, use null for it rather
  than guessing."""


class ModelVisionError(Exception):
    """The model path failed; vision.py falls back to fixture matching."""


def configured():
    """True when a Gemini API key is present in the environment."""
    return bool(os.environ.get("GEMINI_API_KEY"))


def model_name():
    return os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def _prepare_image(image_bytes):
    """(mime_type, base64) for the upload, downscaling very large photos."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        fmt = (img.format or "JPEG").upper()
        if max(img.size) > _MAX_IMAGE_DIM or fmt not in ("JPEG", "PNG"):
            img = img.convert("RGB")
            img.thumbnail((_MAX_IMAGE_DIM, _MAX_IMAGE_DIM))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return "image/jpeg", base64.b64encode(buf.getvalue()).decode()
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        return mime, base64.b64encode(image_bytes).decode()
    except Exception as exc:
        raise ModelVisionError(f"uploaded photo could not be read: {exc}")


def _money(value):
    return round(float(value), 2)


def _validate(payload):
    """Validate the model's JSON into a clean structured read.

    Strict on the fields the pipeline depends on — a partial or sloppy
    read is rejected whole rather than half-trusted.
    """
    if not isinstance(payload, dict):
        raise ModelVisionError("model did not return a JSON object")
    vendor = payload.get("vendor_name")
    if not vendor or not isinstance(vendor, str):
        raise ModelVisionError("model read has no vendor name")
    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ModelVisionError("model read has no line items")
    lines = []
    for i, ln in enumerate(raw_lines):
        if not isinstance(ln, dict):
            raise ModelVisionError(f"line {i + 1} is not an object")
        desc = ln.get("description")
        qty, unit = ln.get("quantity"), ln.get("unit_cost")
        if not desc or not isinstance(desc, str):
            raise ModelVisionError(f"line {i + 1} has no description")
        if not isinstance(qty, (int, float)) or not float(qty).is_integer() \
                or float(qty) <= 0:
            raise ModelVisionError(f"line {i + 1} has no valid quantity")
        if not isinstance(unit, (int, float)) or float(unit) < 0:
            raise ModelVisionError(f"line {i + 1} has no valid unit cost")
        ext = ln.get("extended")
        if not isinstance(ext, (int, float)):
            ext = int(qty) * float(unit)
        lines.append({"description": " ".join(desc.split()),
                      "quantity": int(qty),
                      "unit_cost": _money(unit),
                      "extended": _money(ext)})
    surcharges = []
    for s in payload.get("surcharges") or []:
        if isinstance(s, dict) and isinstance(s.get("amount"), (int, float)):
            label = " ".join(str(s.get("label") or "SURCHARGE").split())
            if "SURCHARGE" not in label.upper():
                label += " SURCHARGE"
            surcharges.append({"label": label, "amount": _money(s["amount"])})
    credits = []
    for c in payload.get("credits") or []:
        if isinstance(c, dict) and isinstance(c.get("amount"), (int, float)):
            credits.append({
                "description": " ".join(
                    str(c.get("description") or "VENDOR CREDIT").split()),
                "memo": c.get("memo") or None,
                "amount": _money(c["amount"])})
    total = payload.get("printed_total")
    return {
        "vendor_name": " ".join(vendor.split()),
        "invoice_number": payload.get("invoice_number") or None,
        "date": payload.get("date") or None,
        "lines": lines,
        "surcharges": surcharges,
        "credits": credits,
        "printed_total": _money(total) if isinstance(total, (int, float))
        else None,
    }


def to_pipeline_text(read):
    """Serialize a structured read into extraction.py's invoice text.

    Mirrors the verified fixture format exactly: vendor header line,
    invoice-number/date line, one "DESC  QTY  UNIT  EXTENDED" row per
    line, surcharge and credit rows in the shapes the parser routes to
    its dropped/credit handling, and the TOTAL row.
    """
    rows = [read["vendor_name"]]
    head = []
    if read["invoice_number"]:
        head.append(f"INVOICE NO. {read['invoice_number']}")
    if read["date"]:
        head.append(f"DATE {read['date']}")
    if head:
        rows.append("  ".join(head))
    for ln in read["lines"]:
        rows.append(f"{ln['description']}  {ln['quantity']}  "
                    f"{ln['unit_cost']:.2f}  {ln['extended']:.2f}")
    for s in read["surcharges"]:
        rows.append(f"{s['label']}  {s['amount']:.2f}")
    for c in read["credits"]:
        row = f"CREDIT {c['description']}"
        if c["memo"]:
            row += f" {c['memo']}"
        if read["invoice_number"]:
            row += f" FOR INVOICE {read['invoice_number']}"
        rows.append(f"{row}  {c['amount']:.2f}")
    if read["printed_total"] is not None:
        rows.append(f"TOTAL {read['printed_total']:.2f}")
    return "\n".join(rows)


def list_generate_models():
    """Diagnostic: which models this key can actually call generateContent on."""
    api_key=<redacted>
    if not api_key:
        return {"error": "GEMINI_API_KEY is not configured"}
    try:
        resp = httpx.get(API_ROOT, params={"pageSize": 200},
                         headers={"x-goog-api-key": api_key}, timeout=30)
        resp.raise_for_status()
        names = []
        for m in resp.json().get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                names.append((m.get("name") or "").removeprefix("models/"))
        return {"models": names}
    except Exception as exc:
        return {"error": f"model list failed: {exc}"}


def read_invoice(image_bytes):
    """Read an invoice photo with the vision model.

    Returns {"structured": <validated read>, "raw_text": <pipeline
    text>, "model": <model name>}. Raises ModelVisionError on any
    failure — the caller falls back, never guesses.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ModelVisionError("GEMINI_API_KEY is not configured")
    mime, b64 = _prepare_image(image_bytes)
    model = model_name()
    try:
        resp = httpx.post(
            f"{API_ROOT}/{model}:generateContent",
            headers={"x-goog-api-key": api_key,
                     "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]}],
                "generationConfig": {"temperature": 0,
                                     "responseMimeType": "application/json"},
            },
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        body = resp.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        structured = _validate(json.loads(text))
    except ModelVisionError:
        raise
    except Exception as exc:
        raise ModelVisionError(f"vision model read failed: {exc}")
    return {"structured": structured,
            "raw_text": to_pipeline_text(structured),
            "model": model}
