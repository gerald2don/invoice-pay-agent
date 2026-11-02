"""Variance & claims screens: diagnosis packets, credit claims, watchdog."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import data, ledger, variance

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


def _demo_doc(kind, variance_id):
    doc = data.EVIDENCE.get("demo_documents", {}).get(kind)
    if doc and doc.get("for_variance") == variance_id:
        return doc["text"]
    return None


@router.get("/variance")
def variance_list(request: Request):
    variance.watchdog()
    return templates.TemplateResponse(request, "variance.html", {
        "rows": variance.all_variances(),
    })


@router.get("/variance/{variance_id}")
def variance_detail(request: Request, variance_id: str):
    variance.watchdog()
    var = variance.variance_by_id(variance_id)
    if var is None:
        return RedirectResponse("/variance", status_code=303)
    claim = var["claim"]
    return templates.TemplateResponse(request, "variance_detail.html", {
        "var": var,
        "supplier": (data.SUPPLIERS[var["diagnosis"]["supplier_id"]]
                     if var["diagnosis"]["supplier_id"] else None),
        "claim": claim,
        "claim_status": variance.claim_status(claim) if claim else None,
        "credit_text": _demo_doc("credit_invoice", variance_id),
        "chain_events": ledger.for_ref(
            claim_id=claim["id"] if claim else None,
            variance_id=variance_id),
    })


@router.post("/variance/{variance_id}/claim")
def approve_claim(variance_id: str):
    var = variance.variance_by_id(variance_id)
    if var is None or var["diagnosis"]["cause"] != "vendor_short" or var["claim"]:
        return RedirectResponse(f"/variance/{variance_id}", status_code=303)
    claim = variance.create_claim(var)
    supplier = data.SUPPLIERS[claim["supplier_id"]]
    ledger.safe_record(
        "CLAIM_SENT",
        f"Claim {claim['id']} sent to {supplier['name']} — "
        f"${claim['amount']:.2f} for invoice {claim['invoice_number']}: "
        f"billed {claim['billed_qty']} units, received "
        f"{claim['received_qty']}.",
        actor="Store manager",
        claim_id=claim["id"], variance_id=variance_id,
        supplier_id=claim["supplier_id"], supplier=supplier["name"],
        invoice_number=claim["invoice_number"], amount=claim["amount"],
    )
    return RedirectResponse(f"/variance/{variance_id}", status_code=303)


@router.post("/variance/{variance_id}/confirm-found")
def confirm_found(variance_id: str):
    var = variance.variance_by_id(variance_id)
    if var is None or var["diagnosis"]["cause"] != "transfer_ghost" or var["resolved"]:
        return RedirectResponse(f"/variance/{variance_id}", status_code=303)
    variance.confirm_found(var)
    return RedirectResponse(f"/variance/{variance_id}", status_code=303)


@router.get("/claims")
def claims(request: Request):
    variance.watchdog()
    rows = []
    for claim in data.CLAIMS:
        status = variance.claim_status(claim)
        rows.append({
            "claim": claim,
            "supplier": data.SUPPLIERS[claim["supplier_id"]],
            "status": status,
            "credit_text": (_demo_doc("credit_invoice", claim.get("variance_id"))
                            if status["key"] == "sent" else None),
            "next_text": (_demo_doc("next_invoice", claim.get("variance_id"))
                          if status["key"] == "applied" else None),
        })
    return templates.TemplateResponse(request, "claims.html", {"rows": rows})
