"""Manager screens: invoice inbox, bill review, approve & pay (PayPal)."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import data, paypal_client

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
    return templates.TemplateResponse(request, "bill.html", {
        "inv": inv,
        "supplier": data.SUPPLIERS[inv["supplier_id"]],
        "lines": lines,
        "total": data.invoice_total(inv),
        "payment": data.PAYMENTS.get(inv["id"]),
        "paypal_configured": paypal_client.configured(),
    })


@router.post("/bill/{invoice_id}/pay")
def pay(invoice_id: str):
    inv = data.invoice_by_id(invoice_id)
    if inv is None or invoice_id in data.PAYMENTS:
        return RedirectResponse(f"/bill/{invoice_id}", status_code=303)
    supplier = data.SUPPLIERS[inv["supplier_id"]]
    record = paypal_client.pay_supplier(
        supplier=supplier,
        amount=data.invoice_total(inv),
        invoice_ref=inv["number"],
    )
    data.PAYMENTS[invoice_id] = record
    inv["status"] = "paid"
    return RedirectResponse(f"/bill/{invoice_id}?paid=1", status_code=303)
