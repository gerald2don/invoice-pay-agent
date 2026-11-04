"""Breakage screens — loss reporting (the honest-losses bucket).

Something breaks in a store every week: a case dropped in the back room,
a bottle burst in the cooler. Today that loss usually lives in someone's
memory until a count comes up short — and then it gets lumped in with
theft, which poisons the shrink number the owner actually watches. Here
it takes seconds to log, two doors in:

- By hand: pick the product, the quantity, and what happened.
- By photo: snap the damage; the vision step (the same fixture-backed
  hash matching as the invoice door) identifies the product against
  the item master, and a person confirms the quantity.

Either way the product comes out of inventory on the spot, the loss is
priced at cost, and a BREAKAGE_LOGGED event lands in the same
hash-linked ledger as every dollar. Both doors also ask for a generic
reason (dropped, leaked, damaged on arrival, ...) — some companies
require one on every write-off — and the reason rides on the record
and into the ledger payload.

Two refinements keep the counts honest:

- The salvage loop. When the broken product is a package that breaks
  down into singles, the logger says how many singles survived; those
  go back into singles stock in the same touch that minuses the
  package, and only the destroyed units are priced as the loss. It is
  the standing kit-breakdown law — singles added but the package never
  minused is how counts drift into fiction — applied to a wreck.
- The defective fork. A defective item leaves inventory the same way,
  but it is routed to returns — it goes back to the vendor instead of
  into the breakage bucket.

What is left unexplained after these known losses is the shrink worth
chasing.
"""
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import data, ledger, vision

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()

# The demo store — the same store the counts and variance screens serve.
STORE = "Store A"
CONDITIONS = [
    ("broke_in_store", "Broke in store"),
    ("defective", "Defective — will return to vendor"),
]
CONDITION_LABELS = dict(CONDITIONS)

# The generic reason prompt — company-agnostic on purpose: wherever a
# company requires a reason on a write-off, the pick-list has one that
# fits, and the free-text note carries anything more specific.
REASONS = [
    ("dropped_broken", "Dropped / broken"),
    ("leaked_burst", "Leaked or burst"),
    ("damaged_on_arrival", "Damaged on arrival"),
    ("defective", "Defective"),
    ("expired_pulled", "Expired — pulled"),
    ("other", "Taken out — other reason"),
]
REASON_LABELS = dict(REASONS)


def _products():
    """Item-master products carried at the demo store, with live counts
    and any pack-breakdown mapping (for the salvage question)."""
    rows = []
    for inv in data.INVENTORY:
        if inv["store"] != STORE:
            continue
        item = data.ITEM_MASTER.get(inv["sku"], {})
        mapping = data.breakdown_for(inv["sku"])
        singles = None
        if mapping:
            s_item = data.ITEM_MASTER.get(mapping["singles_sku"], {})
            singles = {"sku": mapping["singles_sku"],
                       "name": s_item.get("name", mapping["singles_sku"]),
                       "units_per_pack": mapping["units_per_pack"]}
        rows.append({"sku": inv["sku"],
                     "name": item.get("name", inv["sku"]),
                     "dept": item.get("dept", ""),
                     "on_hand": inv["on_hand"],
                     "unit_cost": inv["unit_cost"],
                     "singles": singles})
    rows.sort(key=lambda r: r["name"])
    return rows


def _page(request, **kw):
    # Losses logged before the reason prompt / salvage loop existed
    # render with empty defaults rather than missing keys.
    for loss in data.LOSSES:
        loss.setdefault("reason_label", "")
        loss.setdefault("note", "")
        loss.setdefault("salvage", None)
    ctx = {
        "products": _products(),
        "conditions": CONDITIONS,
        "reasons": REASONS,
        "losses": list(reversed(data.LOSSES)),
        "known_total": round(sum(l["cost"] for l in data.LOSSES), 2),
        "samples": vision.breakage_sample_photos(),
        "identified": None,
        "photo_error": None,
        "logged": None,
        "error": None,
    }
    ctx.update(kw)
    return templates.TemplateResponse(request, "breakage.html", ctx)


def _validate(sku, qty, condition, reason, survivors=0):
    if condition not in CONDITION_LABELS:
        return "Pick what happened — broke in store, or defective."
    if reason not in REASON_LABELS:
        return ("Pick a reason — why it broke or was taken out. A reason "
                "is required on every loss.")
    row = data.inventory_for(sku, STORE)
    if row is None:
        return "That product is not in this store's inventory."
    if qty < 1:
        return "Quantity must be at least 1."
    if qty > row["on_hand"]:
        return (f"Only {row['on_hand']} on hand for that product — a loss "
                f"can't take out more than the system says is there.")
    mapping = data.breakdown_for(sku)
    if mapping and not 0 <= survivors <= mapping["units_per_pack"]:
        return (f"Survivors must be between 0 and "
                f"{mapping['units_per_pack']} — a pack only holds that "
                f"many singles.")
    return None


def _apply_loss(sku, qty, condition, reason, note, source, photo=None,
                survivors=0):
    """Decrement inventory, file the loss record, write the ledger event.

    For a mapped package the quantity means packages broken: the package
    count drops, the surviving singles go into singles stock, and only
    the destroyed units are priced as the loss.
    """
    row = data.inventory_for(sku, STORE)
    item = data.ITEM_MASTER.get(sku, {})
    mapping = data.breakdown_for(sku)
    note = (note or "").strip()
    salvage = None
    if mapping:
        singles_row = data.inventory_for(mapping["singles_sku"], STORE)
        s_item = data.ITEM_MASTER.get(mapping["singles_sku"], {})
        before = row["on_hand"]
        after = before - qty
        row["on_hand"] = after
        recovered = survivors * qty
        s_before = singles_row["on_hand"]
        s_after = s_before + recovered
        singles_row["on_hand"] = s_after
        destroyed = (mapping["units_per_pack"] - survivors) * qty
        unit_cost = singles_row["unit_cost"]
        cost = round(destroyed * unit_cost, 2)
        salvage = {
            "singles_sku": mapping["singles_sku"],
            "singles_product": s_item.get("name", mapping["singles_sku"]),
            "units_per_pack": mapping["units_per_pack"],
            "survivors_per_pack": survivors,
            "recovered": recovered,
            "destroyed": destroyed,
            "singles_before": s_before,
            "singles_after": s_after,
        }
    else:
        before = row["on_hand"]
        after = before - qty
        row["on_hand"] = after
        unit_cost = row["unit_cost"]
        cost = round(qty * unit_cost, 2)
    nums = [int(l["id"].split("-")[-1]) for l in data.LOSSES
            if l["id"].split("-")[-1].isdigit()]
    loss = {
        "id": f"loss-{max(nums, default=500) + 1}",
        "date": data.today(),
        "sku": sku,
        "product": item.get("name", sku),
        "store": STORE,
        "qty": qty,
        "condition": condition,
        "condition_label": CONDITION_LABELS[condition],
        "reason": reason,
        "reason_label": REASON_LABELS[reason],
        "note": note,
        "unit_cost": unit_cost,
        "cost": cost,
        "before": before,
        "after": after,
        "source": source,
        "photo": photo,
        "salvage": salvage,
    }
    data.LOSSES.append(loss)
    data.save_losses()
    data.save_inventory()
    how = "from a photo" if source == "photo" else "by hand"
    routed = (", routed to returns, to go back to the vendor"
              if condition == "defective" else "")
    if salvage:
        summary = (
            f"Breakage logged {how} — {qty} × {loss['product']} ({sku}) "
            f"{loss['reason_label'].lower()} at {STORE}: package "
            f"{before} → {after} on hand; {salvage['recovered']} unbroken "
            f"singles recovered to singles stock "
            f"({salvage['singles_product']}, {salvage['singles_sku']}: "
            f"{salvage['singles_before']} → {salvage['singles_after']}); "
            f"{salvage['destroyed']} destroyed, ${cost:.2f} at cost — a "
            f"known, priced loss{routed}, kept separate from unexplained "
            f"shrink.")
    elif condition == "defective":
        summary = (
            f"Loss logged {how} — {qty} × {loss['product']} ({sku}) "
            f"defective at {STORE} ({loss['reason_label'].lower()}): "
            f"routed to returns, to go back to the vendor. ${cost:.2f} at "
            f"cost removed from inventory ({before} → {after} on hand).")
    else:
        summary = (
            f"Breakage logged {how} — {qty} × {loss['product']} ({sku}) "
            f"at {STORE} ({loss['reason_label'].lower()}): ${cost:.2f} at "
            f"cost removed from inventory ({before} → {after} on hand). "
            f"A known, priced loss — kept separate from unexplained "
            f"shrink.")
    payload = dict(
        loss_id=loss["id"], sku=sku, product=loss["product"], store=STORE,
        qty=qty, condition=condition, reason=reason, note=note,
        cost=cost, unit_cost=unit_cost, before=before, after=after,
        source=source, photo=photo)
    if salvage:
        payload.update(
            salvage=True, singles_sku=salvage["singles_sku"],
            units_per_pack=salvage["units_per_pack"],
            survivors_per_pack=salvage["survivors_per_pack"],
            recovered=salvage["recovered"], destroyed=salvage["destroyed"],
            singles_before=salvage["singles_before"],
            singles_after=salvage["singles_after"])
    ledger.safe_record("BREAKAGE_LOGGED", summary, actor="Store manager",
                       **payload)
    return loss


@router.get("/breakage")
def breakage_page(request: Request, logged: str = ""):
    logged_loss = next((l for l in data.LOSSES if l["id"] == logged), None)
    return _page(request, logged=logged_loss)


@router.post("/breakage/log")
def breakage_log(request: Request, sku: str = Form(...),
                 qty: int = Form(...), condition: str = Form(...),
                 reason: str = Form(""), note: str = Form(""),
                 survivors: int = Form(0)):
    error = _validate(sku, qty, condition, reason, survivors)
    if error:
        return _page(request, error=error)
    loss = _apply_loss(sku, qty, condition, reason, note, source="manual",
                       survivors=survivors)
    return RedirectResponse(f"/breakage?logged={loss['id']}", status_code=303)


@router.post("/breakage/photo")
async def breakage_photo(request: Request, photo: UploadFile = File(...)):
    found = vision.read_breakage_photo(await photo.read())
    if found is None:
        return _page(request, photo_error=(
            "That photo did not match any sample breakage photo in this "
            "demo, so nothing was logged from it. Download the sample "
            "breakage photo below and upload it — or log the loss by "
            "hand instead."))
    row = data.inventory_for(found["sku"], STORE)
    identified = dict(found)
    identified["on_hand"] = row["on_hand"] if row else 0
    identified["unit_cost"] = row["unit_cost"] if row else 0.0
    mapping = data.breakdown_for(found["sku"])
    if mapping:
        s_item = data.ITEM_MASTER.get(mapping["singles_sku"], {})
        s_row = data.inventory_for(mapping["singles_sku"], STORE)
        identified["units_per_pack"] = mapping["units_per_pack"]
        identified["singles_name"] = s_item.get("name",
                                                mapping["singles_sku"])
        identified["singles_on_hand"] = s_row["on_hand"] if s_row else 0
    return _page(request, identified=identified)


@router.post("/breakage/photo/confirm")
def breakage_photo_confirm(request: Request, sku: str = Form(...),
                           qty: int = Form(...), condition: str = Form(...),
                           reason: str = Form(""), note: str = Form(""),
                           survivors: int = Form(0),
                           photo: str = Form("")):
    error = _validate(sku, qty, condition, reason, survivors)
    if error:
        return _page(request, error=error)
    # The evidence photo only counts if it is a registered sample photo
    # for this product — the same registry the photo door matched against.
    evidence = None
    sample = next((s for s in vision.breakage_sample_photos()
                   if s["filename"] == photo and s["sku"] == sku), None)
    if sample is not None:
        evidence = sample["filename"]
    loss = _apply_loss(sku, qty, condition, reason, note, source="photo",
                       photo=evidence, survivors=survivors)
    return RedirectResponse(f"/breakage?logged={loss['id']}", status_code=303)


@router.get("/breakage-photos/{filename}")
def breakage_photo_file(filename: str):
    path = vision.breakage_sample_path(filename)
    if path is None:
        return RedirectResponse("/breakage", status_code=303)
    return FileResponse(path, media_type="image/jpeg", filename=filename)
