"""Quick Runs screens — the errand loop (rail 3 on the PayPal connection).

A store runs out of things its distributors don't bring: cleaning supplies,
bags, cups, receipt tape. The shift checklist flags the need, the agent
builds the cart at the store's usual spot-buy source, a manager approves —
or the owner's standing small-dollar rule pre-approves a routine run — and
PayPal pays. Delivery is tracked and the receipt files into the same books
as an invoice: the paid run is written to the hash-linked ledger, and its
receipt is listed on this page with the payout reference.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import data, ledger, paypal_client

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


def _items_short(run):
    return ", ".join(f"{i['qty']}× {i['name']}" for i in run["items"])


@router.get("/quick-runs")
def quick_runs_page(request: Request, paid: str = ""):
    runs = [{"run": run, "total": data.run_total(run)} for run in data.QUICK_RUNS]
    receipts = [{"run": run, "total": data.run_total(run)}
                for run in data.QUICK_RUNS if run.get("payment")]
    return templates.TemplateResponse(request, "quick_runs.html", {
        "runs": runs,
        "receipts": receipts,
        "paid_id": paid,
        "limit": data.AUTO_APPROVE_LIMIT,
        "paypal_configured": paypal_client.configured(),
    })


@router.post("/quick-runs/{run_id}/build")
def build_run(run_id: str):
    run = data.run_by_id(run_id)
    if run is None or run["status"] != "flagged":
        return RedirectResponse("/quick-runs", status_code=303)
    total = data.run_total(run)
    source = run["source"]["name"]
    if total <= data.AUTO_APPROVE_LIMIT:
        # The owner's standing yes: at or under the limit the run is
        # pre-approved — it goes on its own, notice after the fact.
        run["status"] = "auto_approved"
        run["auto_approved"] = True
        ledger.safe_record(
            "QUICK_RUN_AUTO_APPROVED",
            f"Quick Run {run['id']} auto-approved under the owner's "
            f"${data.AUTO_APPROVE_LIMIT:.2f} rule — cart total "
            f"${total:.2f} at {source} is at or under the limit, so no "
            f"tap was needed; the manager gets the notice after the fact.",
            actor="Invoice Pay Agent",
            rail="quick_run", run_id=run["id"], amount=total, source=source,
        )
    else:
        run["status"] = "awaiting_approval"
        ledger.safe_record(
            "QUICK_RUN_BUILT",
            f"Quick Run {run['id']} built — cart total ${total:.2f} at "
            f"{source} is over the owner's "
            f"${data.AUTO_APPROVE_LIMIT:.2f} auto-approve limit, so it "
            f"waits for a manager's approval.",
            actor="Invoice Pay Agent",
            rail="quick_run", run_id=run["id"], amount=total, source=source,
        )
    data.save_quick_runs()
    return RedirectResponse("/quick-runs", status_code=303)


@router.post("/quick-runs/{run_id}/pay")
def pay_run(run_id: str):
    run = data.run_by_id(run_id)
    if run is None or run.get("payment") \
            or run["status"] not in ("awaiting_approval", "auto_approved"):
        return RedirectResponse("/quick-runs", status_code=303)
    total = data.run_total(run)
    source = run["source"]
    record = paypal_client.pay_payee(
        payee_name=source["name"],
        payee_email=source["paypal_email"],
        amount=total,
        ref="QR-" + run["id"].upper(),
        subject=f"Quick Run {run['id']} — store supplies order",
        note=f"Quick Run {run['id']}: {_items_short(run)}",
    )
    run["payment"] = record
    run["status"] = "paid"
    run["delivery"] = ("Ordered — delivery from the spot-buy source is "
                       "expected today; this page tracks it until it lands.")
    data.save_quick_runs()
    ledger.safe_record(
        "QUICK_RUN_PAID",
        f"Quick Run {run['id']} paid via {record['provider']} — "
        f"${total:.2f} to {source['name']} for {_items_short(run)} "
        f"(batch {record['reference']}). The receipt files here, in the "
        f"same books as an invoice.",
        actor="Store manager",
        rail="quick_run", run_id=run["id"], amount=total,
        reference=record["reference"], provider=record["provider"],
        source=source["name"],
    )
    return RedirectResponse(f"/quick-runs?paid={run_id}", status_code=303)
