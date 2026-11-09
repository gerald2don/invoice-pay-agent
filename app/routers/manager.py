"""Manager screens: invoice inbox, bill review, approve & pay (PayPal)."""
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import data, extraction, ledger, paypal_client, variance, vision, vision_model

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


@router.get("/")
def inbox(request: Request):
    rows = []
    for inv in data.INVOICES:
        rows.append({
            "inv": inv,
            "supplier": data.SUPPLIERS[inv["supplier_id"]],
            "total": data.invoice_total(inv),
            "payment": data.PAYMENTS.get(inv["id"]),
        })
    return templates.TemplateResponse(request, "manager.html", {"rows": rows})


@router.get("/bill/{invoice_id}")
def bill(request: Request, invoice_id: str):
    inv = data.invoice_by_id(invoice_id)
    if inv is None:
        return RedirectResponse("/", status_code=303)
    lines = []
    for line in inv["lines"]:
        item = data.ITEM_MASTER.get(line.get("matched_sku") or "", {})
        lines.append({"line": line, "item_name": item.get("name", "—")})
    variance.watchdog()
    credit_claim = None
    if invoice_id not in data.PAYMENTS:
        claim = variance.pending_credit(inv["supplier_id"], inv)
        if claim is not None:
            total = data.invoice_total(inv)
            credit_claim = {
                "claim": claim, "amount": claim["amount"],
                "net": round(total - claim["amount"], 2),
            }
    return templates.TemplateResponse(request, "bill.html", {
        "inv": inv,
        "supplier": data.SUPPLIERS[inv["supplier_id"]],
        "lines": lines,
        "total": data.invoice_total(inv),
        "payment": data.PAYMENTS.get(inv["id"]),
        "paypal_configured": paypal_client.configured(),
        "credit_claim": credit_claim,
        "chain_events": ledger.for_ref(invoice_id=invoice_id),
    })


def _extract_ctx(**kw):
    """extract.html context — every render carries the photo-door state."""
    ctx = {"result": None, "raw_text": "", "lines": [], "supplier_name": None,
           "samples": vision.sample_photos(), "photo_match": None,
           "photo_error": None}
    ctx.update(kw)
    return ctx


def _result_ctx(result, raw_text, **kw):
    supplier = data.SUPPLIERS.get(result["supplier_id"] or "", {})
    lines = []
    for line in result["lines"]:
        item = data.ITEM_MASTER.get(line.get("matched_sku") or "", {})
        lines.append({"line": line, "item_name": item.get("name", "—")})
    return _extract_ctx(result=result, raw_text=raw_text, lines=lines,
                        supplier_name=supplier.get("name"), **kw)


@router.get("/vision-status")
def vision_status():
    """Diagnostic: is the vision model configured, and what did it last say?"""
    return JSONResponse({
        "configured": vision_model.configured(),
        "model": vision_model.model_name(),
        "last_error": vision.last_model_error(),
        "available": vision_model.list_generate_models(),
    })


@router.get("/vision-probe")
def vision_probe():
    """Diagnostic: raw generateContent variant results for this key."""
    return JSONResponse(vision_model.probe_variants())


@router.get("/extract")
def extract_form(request: Request):
    return templates.TemplateResponse(request, "extract.html", _extract_ctx())


@router.post("/extract")
def extract_run(request: Request, invoice_text: str = Form(...)):
    result = extraction.extract_invoice(invoice_text)
    return templates.TemplateResponse(
        request, "extract.html", _result_ctx(result, invoice_text))


@router.post("/extract/photo")
async def extract_photo(request: Request, photo: UploadFile = File(...)):
    found = vision.read_invoice_photo(await photo.read())
    if found is None:
        return templates.TemplateResponse(request, "extract.html",
                                          _extract_ctx(photo_error=(
            "That photo could not be read as an invoice, so nothing was "
            "extracted from it. Try one of the sample invoice photos "
            "below — or paste the invoice text instead.")))
    result = extraction.extract_invoice(found["raw_text"])
    return templates.TemplateResponse(
        request, "extract.html",
        _result_ctx(result, found["raw_text"], photo_match=found))


@router.get("/sample-invoices/{filename}")
def sample_invoice(filename: str):
    path = vision.sample_path(filename)
    if path is None:
        return RedirectResponse("/extract", status_code=303)
    return FileResponse(path, media_type="image/jpeg", filename=filename)


@router.post("/extract/add")
def extract_add(invoice_text: str = Form(...)):
    result = extraction.extract_invoice(invoice_text)
    if result["supplier_id"] is None or not result["lines"]:
        return RedirectResponse("/extract", status_code=303)
    nums = [int(i["id"].split("-")[-1]) for i in data.INVOICES
            if i["id"].split("-")[-1].isdigit()]
    inv = {
        "id": f"inv-{max(nums, default=2042) + 1}",
        "number": result["number"] or "DRAFT",
        "date": result["date"] or "",
        "supplier_id": result["supplier_id"],
        "status": "awaiting_approval",
        "lines": result["lines"],
        "flags": result["flags"],
        "dropped_lines": result["dropped_lines"],
        "credit_lines": result["credit_lines"],
        "stated_total": result["stated_total"],
    }
    data.INVOICES.append(inv)
    data.save_invoices()
    supplier = data.SUPPLIERS[inv["supplier_id"]]
    ledger.safe_record(
        "INVOICE_RECEIVED",
        f"Invoice {inv['number']} from {supplier['name']} received via "
        f"the paste/extract door — total ${data.invoice_total(inv):.2f}.",
        actor="Invoice Pay Agent",
        invoice_id=inv["id"], invoice_number=inv["number"],
        supplier_id=inv["supplier_id"], supplier=supplier["name"],
        total=data.invoice_total(inv), source="extract",
    )
    return RedirectResponse(f"/bill/{inv['id']}", status_code=303)


@router.post("/bill/{invoice_id}/pay")
def pay(invoice_id: str):
    inv = data.invoice_by_id(invoice_id)
    if inv is None or invoice_id in data.PAYMENTS:
        return RedirectResponse(f"/bill/{invoice_id}", status_code=303)
    supplier = data.SUPPLIERS[inv["supplier_id"]]
    total = data.invoice_total(inv)
    # Vendor credits net against the next invoice: an applied claim reduces
    # this payout by the credit amount (never below a payable remainder).
    variance.watchdog()
    claim = variance.pending_credit(inv["supplier_id"], inv)
    credit = claim["amount"] if claim and claim["amount"] < total else 0.0
    record = paypal_client.pay_supplier(
        supplier=supplier,
        amount=round(total - credit, 2),
        invoice_ref=inv["number"],
    )
    record["invoice_total"] = total
    if credit:
        record["credit_applied"] = credit
        record["credit_claim_id"] = claim["id"]
        record["credit_memo"] = claim["credit"]["memo"]
        variance.mark_recovered(claim, record, inv)
    data.PAYMENTS[invoice_id] = record
    inv["status"] = "paid"
    data.save_runtime_state()
    data.save_invoices()
    data.save_claims()
    _summary = (f"Payment sent via {record['provider']} — "
                f"${record['amount']:.2f} to {supplier['name']} for invoice "
                f"{inv['number']} (batch {record['reference']})")
    _payload = {"invoice_id": inv["id"], "invoice_number": inv["number"],
                "supplier_id": inv["supplier_id"], "supplier": supplier["name"],
                "amount": record["amount"], "reference": record["reference"],
                "provider": record["provider"]}
    if credit:
        _summary += (f"; invoice total ${total:.2f} less the "
                     f"${credit:.2f} vendor credit from claim {claim['id']}")
        _payload.update({"credit_amount": credit, "claim_id": claim["id"],
                         "credit_memo": claim["credit"]["memo"],
                         "invoice_total": total})
        _payload["variance_id"] = claim.get("variance_id")
    ledger.safe_record("PAYMENT_SENT", _summary, actor="Store manager",
                       **_payload)
    if credit:
        ledger.safe_record(
            "CREDIT_RECOVERED_VIA_PAYPAL",
            f"Credit recovered via PayPal — claim {claim['id']} closed: "
            f"the ${credit:.2f} vendor credit (memo "
            f"{claim['credit']['memo']}) came back by netting it against "
            f"payout {record['reference']}.",
            actor="Invoice Pay Agent",
            claim_id=claim["id"], variance_id=claim.get("variance_id"),
            invoice_id=inv["id"], invoice_number=inv["number"],
            reference=record["reference"], amount=credit,
            credit_memo=claim["credit"]["memo"],
        )
    return RedirectResponse(f"/bill/{invoice_id}?paid=1", status_code=303)
