"""Verify the vision wiring: fixture regression + model path (mocked/live).

Run:  .venv/bin/python tools/test_vision_model.py

A. Regression — with GEMINI_API_KEY unset, the photo door behaves
   exactly as the accuracy-study baseline: all 3 sample invoice photos
   resolve to their fixtures and extraction reproduces every expected
   field (11 lines, zero deviations).
B. Mocked model — a canned Gemini response is pushed through
   vision.read_invoice_photo -> extraction.extract_invoice and checked
   for supplier match, duplicate flag, surcharge drop, credit capture.
C. Live model — only when GEMINI_API_KEY is set in the environment:
   the Oct 14, 2026 Heartland Coca-Cola invoice photo (a real A1
   invoice, transcribed and verified to the cent — see
   ~/workspace/retailzpos/invoices/2026-10-14-coke-54704884034.md) is
   read by the model and scored field-by-field against ground truth.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("GEMINI_API_KEY", None)  # A and B start key-free

from app import extraction, vision, vision_model  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


# ---------------------------------------------------------------- A
print("A. Fixture regression (no key — the study baseline)")
fixtures = json.loads((vision.SAMPLE_DIR.parent / "extraction_fixtures.json")
                      .read_text())["fixtures"]
total_lines = 0
for fx in fixtures:
    photo = (vision.SAMPLE_DIR / f"{fx['id']}.jpg").read_bytes()
    found = vision.read_invoice_photo(photo)
    check(f"{fx['id']} photo resolves", found is not None
          and found["fixture_id"] == fx["id"]
          and found["raw_text"] == fx["raw_invoice_text"],
          f"method={found and found['method']}")
    result = extraction.extract_invoice(found["raw_text"])
    exp = fx["expected"]
    total_lines += len(result["lines"])
    check(f"{fx['id']} header", result["number"] == exp["number"]
          and result["date"] == exp["date"]
          and result["supplier_id"] == fx["supplier_id"],
          f"{result['number']} {result['date']} {result['supplier_id']}")
    lines_ok = len(result["lines"]) == len(exp["lines"]) and all(
        r["qty"] == e["qty"] and r["unit_cost"] == e["unit_cost"]
        and r["matched_sku"] == e["matched_sku"]
        and r["raw_text"] == e["raw_text"]
        and r["confidence"] >= e["min_confidence"]
        for r, e in zip(result["lines"], exp["lines"]))
    check(f"{fx['id']} lines ({len(exp['lines'])})", lines_ok)
    check(f"{fx['id']} total + dropped + flags",
          result["total"] == exp["total"]
          and [d["amount"] for d in result["dropped_lines"]]
          == [d["amount"] for d in exp["dropped_lines"]]
          and result["flags"] == exp["flags"],
          f"total={result['total']}")
check("11 baseline lines scored", total_lines == 11, f"got {total_lines}")

# ---------------------------------------------------------------- B
print("B. Model path (mocked Gemini response)")
os.environ["GEMINI_API_KEY"] = "test-key-not-real"
CANNED = {
    "vendor_name": "PRAIRIE STATE BEVERAGE CO.",
    "invoice_number": "PS-88501",
    "date": "10/26/2026",
    "lines": [
        {"description": "COLA 12PK CAN 12/12OZ", "quantity": 20,
         "unit_cost": 5.89, "extended": 117.80},
        {"description": "COLA 12PK CAN 12/12OZ", "quantity": 20,
         "unit_cost": 5.89, "extended": 117.80},
        {"description": "SPRK WTR LIME", "quantity": 8,
         "unit_cost": 4.25, "extended": 34.00},
    ],
    "surcharges": [{"label": "FUEL SURCHARGE", "amount": 12.50}],
    "credits": [{"description": "COLA 12PK CAN CASES RETURNED",
                 "memo": "CM-104", "amount": 117.80}],
    "printed_total": 282.10,
}


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"candidates": [{"content": {"parts": [
            {"text": json.dumps(CANNED)}]}}]}


import io  # a real (tiny) JPEG so the model path's image prep accepts it

from PIL import Image as _Image
_buf = io.BytesIO()
_Image.new("RGB", (64, 64), "white").save(_buf, format="JPEG")
PHOTO = _buf.getvalue()

vision_model.httpx.post = lambda *a, **k: _Resp()
found = vision.read_invoice_photo(PHOTO)
check("model read returned", found is not None
      and found["method"] == "model", f"method={found and found['method']}")
result = extraction.extract_invoice(found["raw_text"])
check("supplier matched from model header",
      result["supplier_id"] == "sup-prairie", str(result["supplier_id"]))
check("number + date from model read",
      result["number"] == "PS-88501" and result["date"] == "2026-10-26")
check("3 lines extracted", len(result["lines"]) == 3)
check("duplicate flagged", "duplicate line present" in result["flags"])
check("surcharge dropped, not billed",
      [d["amount"] for d in result["dropped_lines"]] == [12.50]
      and result["total"] == 269.60, f"total={result['total']}")
check("credit captured with memo + ref",
      len(result["credit_lines"]) == 1
      and result["credit_lines"][0]["memo"] == "CM-104"
      and result["credit_lines"][0]["for_invoice"] == "PS-88501"
      and result["credit_lines"][0]["amount"] == 117.80)
check("totals check explains surcharge",
      result["totals_check"]["explained_by_dropped"] is True)


def _boom(*a, **k):
    raise RuntimeError("simulated model outage")


vision_model.httpx.post = _boom
fx0 = fixtures[0]
photo = (vision.SAMPLE_DIR / f"{fx0['id']}.jpg").read_bytes()
found = vision.read_invoice_photo(photo)
check("model outage -> fixture fallback", found is not None
      and found["fixture_id"] == fx0["id"], f"method={found and found['method']}")
check("model outage -> unknown photo returns None",
      vision.read_invoice_photo(PHOTO) is None)
del os.environ["GEMINI_API_KEY"]

# ---------------------------------------------------------------- C
print("C. Live model test (real A1 invoice photo)")
if os.environ.get("GEMINI_API_KEY_LIVE"):
    os.environ["GEMINI_API_KEY"] = os.environ["GEMINI_API_KEY_LIVE"]
    photo_path = Path.home() / ("workspace/user/files/"
                                "f7553dfc-218c-467c-89d0-0312b33ab8bd_6_qrih.jpg")
    GT = [  # (desc tokens, cases, net/case, extended) — verified transcription
        ("PA ZRO MXD BRY 28OZ", 1, 24.63, 24.63),
        ("PA MTBRYBLST 28OZ", 1, 24.63, 24.63),
        ("PA LMN LIM 28OZ", 1, 24.63, 24.63),
        ("PA FRPN 28OZ", 2, 24.63, 49.26),
        ("PA GRP 28OZ", 1, 24.63, 24.63),
        ("PA ORG 28OZ", 1, 24.63, 24.63),
        ("JAV MON LOMO 15OZ", 2, 28.88, 57.76),
        ("MON ENG JV BRY 16OZ", 2, 45.16, 90.32),
        ("SPRITE 20OZ", 2, 38.35, 76.70),
        ("DT COKE 20OZ", 1, 38.35, 38.35),
        ("DT COKE 2L", 1, 25.16, 25.16),
        ("COKE 7.5OZ 10PK", 1, 21.35, 21.35),
    ]

    def _toks(s):
        return set(s.upper().replace(".", " ").split())

    read = vision_model.read_invoice(photo_path.read_bytes())
    s = read["structured"]
    print(f"  model={read['model']} vendor={s['vendor_name']!r} "
          f"number={s['invoice_number']} lines={len(s['lines'])} "
          f"printed_total={s['printed_total']}")
    check("vendor is Heartland Coca-Cola",
          "COCA" in s["vendor_name"].upper()
          and "COLA" in s["vendor_name"].upper(), s["vendor_name"])
    check("invoice number exact",
          (s["invoice_number"] or "").replace(" ", "") == "54704884034",
          str(s["invoice_number"]))
    check("printed total 482.05", s["printed_total"] == 482.05,
          str(s["printed_total"]))
    used, agreed = set(), 0
    for gt_desc, gt_qty, gt_unit, gt_ext in GT:
        gt_toks = _toks(gt_desc)
        best, best_ov = None, 0.0
        for i, ln in enumerate(s["lines"]):
            if i in used:
                continue
            ov = len(gt_toks & _toks(ln["description"])) / max(1, len(gt_toks))
            if ov > best_ov:
                best, best_ov = i, ov
        if best is None or best_ov < 0.4:
            print(f"  [MISS] no model line matched {gt_desc}")
            continue
        used.add(best)
        ln = s["lines"][best]
        ok = (ln["quantity"] == gt_qty and abs(ln["unit_cost"] - gt_unit) <= 0.01
              and abs(ln["extended"] - gt_ext) <= 0.01)
        agreed += ok
        print(f"  [{'OK ' if ok else 'DIFF'}] {gt_desc}: model qty={ln['quantity']} "
              f"unit={ln['unit_cost']} ext={ln['extended']} "
              f"(GT {gt_qty}/{gt_unit}/{gt_ext}) — {ln['description']!r}")
    check(f"line agreement {agreed}/12 (qty+unit+extended)",
          agreed >= 10, f"{agreed}/12")
else:
    print("  skipped — set GEMINI_API_KEY_LIVE to run the live read")

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL CHECKS PASSED")
