"""Full-flow smoke test with the model path active (mocked Gemini).

Run:  .venv/bin/python tools/test_full_flow.py

Boots the real FastAPI app against a THROWAWAY data dir (the repo's
seed state and the hosted ledger are never touched), uploads a photo
through the photo door with the vision model mocked on, adds the bill
from the exact text the door produced, approves & pays (PayPal runs in
its clearly-labeled SIMULATED mode here — credentials are deliberately
unset), and asserts the payout event landed on the hash-linked ledger.
"""
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="ipa-flow-")
os.environ["DATA_DIR"] = _TMP
os.environ["GEMINI_API_KEY"] = "test-key-not-real"

from PIL import Image  # noqa: E402

from app import vision_model  # noqa: E402
from app.main import app  # noqa: E402

# Force PayPal SIMULATED mode for this test: no sandbox call is made.
os.environ.pop("PAYPAL_CLIENT_ID", None)
os.environ.pop("PAYPAL_CLIENT_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

CANNED = {
    "vendor_name": "PRAIRIE STATE BEVERAGE CO.",
    "invoice_number": "PS-88501",
    "date": "10/26/2026",
    "lines": [
        {"description": "COLA 12PK CAN 12/12OZ", "quantity": 20,
         "unit_cost": 5.89, "extended": 117.80},
        {"description": "SPRK WTR LIME", "quantity": 8,
         "unit_cost": 4.25, "extended": 34.00},
        {"description": "PREMIUM TONIC 4PK GLASS BTL", "quantity": 6,
         "unit_cost": 6.40, "extended": 38.40},
    ],
    "surcharges": [{"label": "FUEL SURCHARGE", "amount": 12.50}],
    "credits": [],
    "printed_total": 202.70,
}


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"candidates": [{"content": {"parts": [
            {"text": json.dumps(CANNED)}]}}]}


vision_model.httpx.post = lambda *a, **k: _Resp()

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


buf = io.BytesIO()
Image.new("RGB", (64, 64), "white").save(buf, format="JPEG")

with TestClient(app) as client:
    r = client.get("/")
    check("app boots, dashboard renders", r.status_code == 200)

    r = client.post("/extract/photo",
                    files={"photo": ("invoice.jpg", buf.getvalue(),
                                     "image/jpeg")})
    check("photo door accepts upload", r.status_code == 200)
    check("model read is what the page reports",
          "vision model" in r.text and "gemini" in r.text.lower())
    m = re.search(r'name="invoice_text"[^>]*>(.*?)</textarea>',
                  r.text, re.S)
    raw_text = m.group(1).strip() if m else ""
    check("door produced pipeline text", "PRAIRIE STATE" in raw_text
          and "FUEL SURCHARGE" in raw_text)

    r = client.post("/extract/add", data={"invoice_text": raw_text},
                    follow_redirects=False)
    check("bill created from the model's text", r.status_code == 303
          and r.headers["location"].startswith("/bill/"),
          r.headers.get("location", ""))
    bill_url = r.headers["location"]
    inv_id = bill_url.rsplit("/", 1)[-1]

    r = client.get(bill_url)
    check("bill page shows the model's invoice",
          r.status_code == 200 and "PS-88501" in r.text
          and "$190.20" in r.text, "total excludes the surcharge")

    r = client.post(f"/bill/{inv_id}/pay", follow_redirects=False)
    check("approve & pay accepted", r.status_code == 303)

    ledger = json.loads((Path(_TMP) / "ledger.json").read_text())
    events = ledger["events"] if isinstance(ledger, dict) else ledger
    kinds = [e.get("event") or e.get("type") or e.get("kind")
             for e in events]
    summaries = " ".join(str(e.get("summary", "")) for e in events)
    check("INVOICE_RECEIVED on the ledger",
          "INVOICE_RECEIVED" in kinds, str(kinds))
    check("payment event on the ledger",
          any("PAY" in str(k).upper() for k in kinds)
          and "PS-88501" in summaries, str(kinds))
    check("payment recorded as simulated (no sandbox call)",
          "simulated" in summaries.lower())

    r = client.get("/ledger/verify") if client.get("/ledger").status_code else None
    check("ledger page renders after the flow",
          client.get("/ledger").status_code == 200)

print(f"\nData dir used (throwaway): {_TMP}")
if FAILURES:
    print(f"FAILED: {FAILURES}")
    sys.exit(1)
print("FULL FLOW PASSED")
