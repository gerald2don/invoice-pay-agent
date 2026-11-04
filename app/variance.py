"""Variance diagnosis + vendor-claim recovery.

When a physical count disagrees with system stock, this module walks the
evidence chain — ordered -> billed -> received -> entered -> sold /
transferred -> counted — and names the most likely cause in plain language,
with the trail to back it up. Four causes:

- transfer ghost: the missing units are sitting at the other store (its
  count is over by the same amount and no transfer was ever logged);
- vendor short: the goods were billed but there is no receiving record —
  the case never arrived, so the store claims the money back;
- entry error: the goods were received but never (fully) entered;
- unexplained: every record checks out, so what is left is a loss window
  between the last clean count and this count.

Claims are the physical follow-through for a vendor short: the manager
approves, the claim email goes to the supplier's rep, and a watchdog keeps
watching incoming invoices until the promised credit memo actually shows
up as a credit line. When it does, the credit nets against that supplier's
next payable invoice — the next PayPal payout goes out reduced by the
credit, which is how vendor credits really come back. The claim closes
only when the money has actually moved: "recovered via PayPal".
"""
from datetime import date

from . import data, ledger

OVERDUE_DAYS = 14
STORE_NAME = "Maple Street Market"


def _d(iso):
    return date.fromisoformat(iso) if iso else None


# ---------------------------------------------------------------- diagnosis

def _window_records(sku, store, start, end):
    """Evidence records for one item/store inside the count window."""
    ev = data.EVIDENCE
    in_window = lambda r: start < r["date"] <= end

    orders = [o for o in ev["orders"]
              if o["sku"] == sku and o["store"] == store and in_window(o)]
    billed = []
    for inv in data.INVOICES:
        if not (start < (inv.get("date") or "") <= end):
            continue
        for line in inv["lines"]:
            if line.get("matched_sku") == sku:
                billed.append({"invoice": inv, "line": line})
    billed_ids = {b["invoice"]["id"] for b in billed}
    receiving = [r for r in ev["receiving"]
                 if r["sku"] == sku and r["store"] == store and in_window(r)]
    entries = [e for e in ev["entries"]
               if e["sku"] == sku and e["store"] == store and in_window(e)]
    transfers = [t for t in ev["transfers"]
                 if t["sku"] == sku and in_window(t)
                 and store in (t["from_store"], t["to_store"])]
    sold = sum(s["qty"] for s in ev["sales"]
               if s["sku"] == sku and s["store"] == store
               and s["from"] >= start and s["to"] <= end)
    return {
        "orders": orders, "billed": billed, "billed_ids": billed_ids,
        "receiving": receiving, "entries": entries,
        "transfers": transfers, "sold": sold,
    }


def _other_store_count(sku, store, count_date):
    """The other store's count of the same item (same count round)."""
    others = [c for c in data.COUNTS
              if c["sku"] == sku and c["store"] != store and c["date"] == count_date]
    if not others:
        return None
    c = others[0]
    inv = data.inventory_for(sku, c["store"])
    return {"count": c, "system_qty": inv["on_hand"] if inv else 0,
            "overage": c["counted_qty"] - (inv["on_hand"] if inv else 0)}


def diagnose(count):
    """Full variance analysis for one count record.

    Returns the alert row shape used by the templates: system vs counted,
    variance, dollars at cost, the evidence chain (each link present or
    missing, with its detail), a ranked diagnosis with plain-language
    reasons, and the resolution/claim state.
    """
    sku, store = count["sku"], count["store"]
    item = data.ITEM_MASTER.get(sku, {})
    inv_row = data.inventory_for(sku, store) or {}
    system_qty = inv_row.get("on_hand", 0)
    case_pack = inv_row.get("case_pack", 1)
    unit_cost = inv_row.get("unit_cost", 0.0)
    variance = count["counted_qty"] - system_qty
    missing = -variance
    case_multiple = case_pack > 1 and variance != 0 and variance % case_pack == 0

    start, end = count["prior"]["date"], count["date"]
    rec = _window_records(sku, store, start, end)
    billed_qty = sum(b["line"]["qty"] for b in rec["billed"])
    received_qty = sum(r["qty"] for r in rec["receiving"])
    entered_qty = sum(e["qty"] for e in rec["entries"])
    other = _other_store_count(sku, store, end)

    chain = [
        {"link": "Ordered",
         "ok": bool(rec["orders"]),
         "detail": ("; ".join(f"{o['id']} · {o['qty']} units on {o['date']}"
                              for o in rec["orders"])
                    or "no order record in the window")},
        {"link": "Billed",
         "ok": bool(rec["billed"]),
         "detail": ("; ".join(
             f"invoice {b['invoice']['number']} ({b['invoice']['date']}) · "
             f"{b['line']['qty']} units @ ${b['line']['unit_cost']:.2f}"
             for b in rec["billed"])
             or "no invoice line for this item in the window")},
        {"link": "Received",
         "ok": received_qty > 0,
         "detail": ("; ".join(f"{r['id']} · {r['qty']} units signed by "
                              f"{r['signed_by']} on {r['date']}"
                              for r in rec["receiving"])
                    or "NO receiving record — no dock check-in in the window")},
        {"link": "Entered",
         "ok": entered_qty > 0,
         "detail": ("; ".join(f"{e['id']} · {e['qty']} units entered by "
                              f"{e['entered_by']} on {e['date']}"
                              for e in rec["entries"])
                    or "no receiving-desk entry — stock was posted from the "
                       "invoice alone, never verified against a delivery")},
        {"link": "Sold",
         "ok": True,
         "detail": f"{rec['sold']} units sold in the window (already out of system stock)"},
        {"link": "Transferred",
         "ok": True,
         "detail": ("; ".join(f"{t['id']} · {t['qty']} units {t['from_store']} → "
                              f"{t['to_store']} on {t['date']}"
                              for t in rec["transfers"])
                    or "no transfer logged for this item in the window")},
        {"link": "Counted",
         "ok": True,
         "detail": (f"{count['counted_qty']} on the shelf on {end} "
                    f"(counted by {count['counter']}); last clean count "
                    f"{count['prior']['qty']} on {start}")},
    ]

    reasons = []
    cause = label = supplier_id = None
    claim_invoice = None
    if variance < 0:
        ghost_transfer = [t for t in rec["transfers"]
                          if t["from_store"] == store and t["qty"] >= missing]
        if (other and other["overage"] >= missing and not ghost_transfer):
            cause = "transfer_ghost"
            label = "Transfer ghost — product found at the other store"
            reasons = [
                f"{other['count']['store']} counted {other['count']['counted_qty']} "
                f"against a system {other['system_qty']} — over by exactly "
                f"{other['overage']}, the amount missing here.",
                "No transfer was logged for this item in the window, so the "
                "books never followed the product.",
                "The case was received and entered here (see the chain), so it "
                "existed — it just changed stores on paper nowhere.",
            ]
        elif billed_qty >= missing and received_qty == 0 and rec["billed"]:
            cause = "vendor_short"
            label = "Vendor short — billed, never received"
            first = rec["billed"][0]
            claim_invoice = first["invoice"]
            supplier_id = claim_invoice["supplier_id"]
            reasons = [
                f"Invoice {claim_invoice['number']} billed {billed_qty} units "
                f"on {claim_invoice['date']} — exactly the amount missing, "
                f"one full case of {case_pack}.",
                "There is no receiving record and no dock entry for that "
                "delivery: nobody ever checked a case in.",
                f"Sales in the window were {rec['sold']} units, so the shelf "
                f"should hold {system_qty}; it holds {count['counted_qty']}.",
                "Conclusion: the case was paid for on paper but never "
                "physically arrived. The money comes back as a vendor credit.",
            ]
        elif received_qty > 0 and entered_qty < received_qty \
                and received_qty - entered_qty >= missing:
            cause = "entry_error"
            label = "Entry error — received, never entered"
            reasons = [
                f"The dock signed for {received_qty} units, but only "
                f"{entered_qty} were ever entered into stock.",
                "The goods are most likely in the back room or on a shelf "
                "the system doesn't know about — recount before adjusting.",
            ]
        else:
            cause = "unexplained"
            label = "Unexplained — loss window"
            reasons = [
                "Every record checks out: what was billed was received and "
                "entered, and no other store is holding it.",
                f"That leaves a loss window: last clean count {start} "
                f"({count['prior']['qty']} units) to this count on {end}.",
                "The packet narrows any investigation to that window instead "
                "of 'sometime this year'.",
            ]
    elif variance > 0:
        short_side = None
        if other and other["overage"] < 0 and -other["overage"] >= variance:
            short_side = other
        if short_side:
            cause = "transfer_ghost"
            label = "Transfer ghost — this store is holding the other store's case"
            reasons = [
                f"{short_side['count']['store']} is short exactly "
                f"{-short_side['overage']} units of this item and no transfer "
                "was logged — this overage is almost certainly that case.",
                "Confirm on the shortage side to close both counts at once.",
            ]
        else:
            cause = "unexplained"
            label = "Overage — unexplained"
            reasons = [
                "More on the shelf than the system expects, and no other "
                "store is short this item. Likely an entry or count slip — "
                "recount before adjusting up.",
            ]

    resolution = data.RESOLUTIONS.get(count["id"])
    claim = claim_for_variance(count["id"])
    return {
        "id": count["id"], "count": count, "item": item, "sku": sku,
        "store": store, "system_qty": system_qty,
        "counted_qty": count["counted_qty"], "variance": variance,
        "dollars": round(abs(variance) * unit_cost, 2),
        "unit_cost": unit_cost, "case_pack": case_pack,
        "case_multiple": case_multiple,
        "chain": chain,
        "diagnosis": {"cause": cause, "label": label, "reasons": reasons,
                      "supplier_id": supplier_id,
                      "claim_invoice": claim_invoice},
        "claim": claim,
        "resolution": resolution,
        "resolved": bool(resolution) or bool(claim and claim.get("recovery")),
    }


def all_variances():
    """Every count that disagrees with system stock, worst dollars first."""
    rows = [diagnose(c) for c in data.COUNTS]
    rows = [r for r in rows if r["variance"] != 0]
    return sorted(rows, key=lambda r: -r["dollars"])


def variance_by_id(variance_id):
    count = data.count_by_id(variance_id)
    return diagnose(count) if count else None


# ------------------------------------------------------------------- claims

def claim_for_variance(variance_id):
    for c in data.CLAIMS:
        if c.get("variance_id") == variance_id:
            return c
    return None


def claim_status(claim):
    """Live status: recovered > credit applied > overdue > sent."""
    if claim.get("recovery"):
        return {"key": "recovered", "chip": "ok",
                "label": "Credit recovered via PayPal"}
    if claim.get("credit"):
        return {"key": "applied", "chip": "ok",
                "label": "Credit applied — nets against the next invoice"}
    age = (_d(data.today()) - _d(claim["sent_date"])).days
    if age > OVERDUE_DAYS:
        return {"key": "overdue", "chip": "low",
                "label": f"Overdue — follow-up sent (day {age}, no credit yet)"}
    return {"key": "sent", "chip": "mid",
            "label": "Claim sent — watchdog is watching for the credit"}


def _claim_email(var, claim_id):
    diag = var["diagnosis"]
    inv = diag["claim_invoice"]
    supplier = data.SUPPLIERS[diag["supplier_id"]]
    item = var["item"]
    amount = var["dollars"]
    billed_qty = sum(b["line"]["qty"] for b in
                     _window_records(var["sku"], var["store"],
                                     var["count"]["prior"]["date"],
                                     var["count"]["date"])["billed"]
                     if b["invoice"]["id"] == inv["id"])
    subject = (f"Credit request — short shipment on invoice {inv['number']}")
    body = (
        f"Hello {supplier['name']} team,\n\n"
        f"On invoice {inv['number']} ({inv['date']}), we were billed for "
        f"{billed_qty} units of {item['name']} at ${var['unit_cost']:.2f} — "
        f"${amount:.2f}. Our receiving records show the case never arrived: "
        f"there is no dock check-in for it, and our physical count on "
        f"{var['count']['date']} confirms it is not in the store.\n\n"
        f"Please issue a credit memo for ${amount:.2f} against invoice "
        f"{inv['number']} on our next invoice, or send a replacement case on "
        f"the next delivery.\n\n"
        f"Thank you,\nStore Manager, {STORE_NAME} ({var['store']})\n"
        f"Claim reference: {claim_id}"
    )
    return subject, body


def create_claim(var):
    """Create the claim for a vendor-short variance (manager-approved)."""
    existing = claim_for_variance(var["id"])
    if existing:
        return existing
    nums = [int(c["id"].split("-")[-1]) for c in data.CLAIMS
            if c["id"].split("-")[-1].isdigit()]
    claim_id = f"CLM-{max(nums, default=1001) + 1}"
    subject, body = _claim_email(var, claim_id)
    diag = var["diagnosis"]
    inv = diag["claim_invoice"]
    billed_qty = sum(b["line"]["qty"] for b in
                     _window_records(var["sku"], var["store"],
                                     var["count"]["prior"]["date"],
                                     var["count"]["date"])["billed"]
                     if b["invoice"]["id"] == inv["id"])
    claim = {
        "id": claim_id, "variance_id": var["id"],
        "supplier_id": diag["supplier_id"],
        "invoice_number": inv["number"], "invoice_date": inv["date"],
        "item_sku": var["sku"], "item_name": var["item"]["name"],
        "billed_qty": billed_qty, "received_qty": 0,
        "unit_cost": var["unit_cost"], "amount": var["dollars"],
        "sent_date": var["count"]["date"],
        "email_subject": subject, "email_body": body,
        "credit": None, "recovery": None,
    }
    data.CLAIMS.append(claim)
    data.save_claims()
    return claim


def watchdog():
    """Match promised credits to credit lines on invoices that have since
    entered the system. Idempotent; run before anything renders claims."""
    for claim in data.CLAIMS:
        if claim.get("credit") or claim.get("recovery"):
            continue
        for inv in data.INVOICES:
            if inv["supplier_id"] != claim["supplier_id"]:
                continue
            for line in inv.get("credit_lines") or []:
                if line.get("for_invoice") == claim["invoice_number"] \
                        and abs(line.get("amount", 0) - claim["amount"]) < 0.005:
                    claim["credit"] = {
                        "invoice_id": inv["id"],
                        "invoice_number": inv["number"],
                        "memo": line.get("memo"),
                        "date": inv.get("date"),
                    }
                    ledger.safe_record(
                        "CREDIT_APPLIED",
                        f"Credit applied — memo {line.get('memo')} for "
                        f"${claim['amount']:.2f} matched claim {claim['id']} "
                        f"on invoice {inv['number']}. It now nets against "
                        f"the supplier's next payable invoice.",
                        actor="Watchdog",
                        claim_id=claim["id"],
                        variance_id=claim.get("variance_id"),
                        invoice_id=inv["id"], invoice_number=inv["number"],
                        credit_memo=line.get("memo"),
                        amount=claim["amount"],
                    )
                    data.save_claims()
                    break
            if claim.get("credit"):
                break


def pending_credit(supplier_id, for_invoice):
    """A supplier credit waiting to net against this invoice, if any.

    Real-world rule: the credit memo nets against the vendor's NEXT
    invoice — a later-dated bill from the same supplier, never the
    credited invoice itself and never the invoice carrying the memo.
    """
    for claim in data.CLAIMS:
        if claim["supplier_id"] != supplier_id:
            continue
        if not claim.get("credit") or claim.get("recovery"):
            continue
        credit = claim["credit"]
        if for_invoice["id"] == credit["invoice_id"]:
            continue
        if for_invoice.get("credit_lines"):
            continue
        if (for_invoice.get("date") or "") > (credit["date"] or ""):
            return claim
    return None


def mark_recovered(claim, payment_record, invoice):
    """Close the loop once the netted payout has gone out."""
    claim["recovery"] = {
        "payout_reference": payment_record["reference"],
        "provider": payment_record["provider"],
        "invoice_id": invoice["id"],
        "invoice_number": invoice["number"],
        "invoice_total": payment_record.get("invoice_total"),
        "amount_paid": payment_record["amount"],
        "date": data.today(),
    }
    return claim


def confirm_found(var):
    """Resolve a transfer ghost: product confirmed at the other store.

    Both counts close together — the shortage and its mirror overage —
    and a retroactive transfer note is recorded so the trail stays honest.
    """
    note = (f"Case confirmed at the other store on {data.today()}; variance "
            f"closed as a transfer ghost and a retroactive transfer "
            f"(case of {var['case_pack']}) logged after the fact.")
    ledger.safe_record(
        "VARIANCE_RESOLVED",
        f"Variance resolved — {var['item'].get('name', var['sku'])}: the "
        f"missing case ({abs(var['variance'])} units) was confirmed at the "
        f"other store; transfer ghost closed and a retroactive transfer "
        f"logged.",
        actor="Store manager",
        variance_id=var["id"], sku=var["sku"], store=var["store"],
        qty=abs(var["variance"]), cause="transfer_ghost",
    )
    data.RESOLUTIONS[var["id"]] = {"type": "found", "note": note}
    for c in data.COUNTS:
        if c["sku"] == var["sku"] and c["id"] != var["id"] \
                and c["date"] == var["count"]["date"]:
            data.RESOLUTIONS[c["id"]] = {"type": "found", "note": note}
    data.save_runtime_state()
    return note


# ------------------------------------------------------------------- digest

def owner_digest():
    """Dashboard owner digest: recovered dollars, open claims, and the
    per-vendor error leaderboard (vendor mistakes stop being invisible)."""
    recovered = []
    open_claims = 0
    for claim in data.CLAIMS:
        status = claim_status(claim)
        if claim.get("recovery"):
            recovered.append({
                "claim_id": claim["id"], "amount": claim["amount"],
                "supplier": data.SUPPLIERS[claim["supplier_id"]]["name"],
                "payout_reference": claim["recovery"]["payout_reference"],
            })
        elif status["key"] in ("sent", "overdue", "applied"):
            open_claims += 1

    board = {}
    for claim in data.CLAIMS:
        row = board.setdefault(claim["supplier_id"], {
            "supplier": data.SUPPLIERS[claim["supplier_id"]]["name"],
            "errors": 0, "amount": 0.0})
        row["errors"] += 1
        row["amount"] += claim["amount"]
    claimed_vars = {c.get("variance_id") for c in data.CLAIMS}
    for var in all_variances():
        if var["diagnosis"]["cause"] == "vendor_short" \
                and var["id"] not in claimed_vars:
            sid = var["diagnosis"]["supplier_id"]
            row = board.setdefault(sid, {
                "supplier": data.SUPPLIERS[sid]["name"],
                "errors": 0, "amount": 0.0})
            row["errors"] += 1
            row["amount"] += var["dollars"]
    leaderboard = sorted(board.values(), key=lambda r: (-r["errors"], -r["amount"]))
    for row in leaderboard:
        row["amount"] = round(row["amount"], 2)

    return {
        "recovered": recovered,
        "recovered_total": round(sum(r["amount"] for r in recovered), 2),
        "open_claims": open_claims,
        "leaderboard": leaderboard,
    }
