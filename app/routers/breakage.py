"""Breakage screens — loss reporting (the honest-losses bucket).

Something breaks in a store every week: a case dropped in the back room,
a bottle burst in the cooler. Today that loss usually lives in someone's
memory until a count comes up short — and then it gets lumped in with
theft, which poisons the shrink number the owner actually watches. Here
it takes seconds to log, two doors in:

- By hand: pick the product, the quantity, and what happened.
- By photo: snap the damage; the vision step (the same fixture-backed
  hash matching as the invoice door) identifies the product against the
  item master, and a person confirms the quantity.

Either way the product comes out of inventory on the spot, the loss is
priced at cost, and a BREAKAGE_LOGGED event lands in the same
hash-linked ledger as every dollar. A defective item forks at the same
door: it leaves inventory the same way, but it is routed to returns —
it goes back to the vendor instead of into the breakage bucket. What is
left unexplained after these known losses is the shrink worth chasing.
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


def _products():
    """Item-master products carried at the demo store, with live counts."""
    rows = []
    for inv in data.INVENTORY:
        if inv["store"] != STORE:
            continue
        item = data.ITEM_MASTER.get(inv["sku"], {})
        rows.append({"sku": inv["sku"],
                     "name": item.get("name", inv["sku"]),
                     "dept": item.get("dept", ""),
                     "on_hand": inv["on_hand"],
                     "unit_cost": inv["unit_cost"]})
    rows.sort(key=lambda r: r["name"])
    return rows


def _page(request, **kw):
    ctx = {
        "products": _products(),
        "conditions": CONDITIONS,
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


def _validate(sku, qty, condition):
    if condition not in CONDITION_LABELS:
        return "Pick what happened — broke in store, or defective."
    row = data.inventory_for(sku, STORE)
    if row is None:
        return "That product is not in this store's inventory."
    if qty < 1:
        return "Quantity must be at least 1."
    if qty > row["on_hand"]:
        return (f"Only {row['on_hand']} on hand for that product — a loss "
                f"can't take out more than the system says is there.")
    return None


def _apply_loss(sku, qty, condition, source, photo=None):
    """Decrement inventory, file the loss record, write the ledger event."""
    row = data.inventory_for(sku, STORE)
    item = data.ITEM_MASTER.get(sku, {})
    before = row["on_hand"]
    after = before - qty
    row["on_hand"] = after
    cost = round(qty * row["unit_cost"], 2)
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
        "unit_cost": row["unit_cost"],
        "cost": cost,
        "before": before,
        "after": after,
        "source": source,
        "photo": photo,
    }
    data.LOSSES.append(loss)
    data.save_losses()
    data.save_inventory()
    how = "from a photo" if source == "photo" else "by hand"
    if condition == "defective":
        summary = (
            f"Loss logged {how} — {qty} × {loss['product']} ({sku}) "
            f"defective at {STORE}: routed to returns, to go back to the "
            f"vendor. ${cost:.2f} at cost removed from inventory "
            f"({before} → {after} on hand).")
    else:
        summary = (
            f"Breakage logged {how} — {qty} × {loss['product']} ({sku}) "
            f"broke in store at {STORE}: ${cost:.2f} at cost removed from "
            f"inventory ({before} → {after} on hand). A known, priced "
            f"loss — kept separate from unexplained shrink.")
    ledger.safe_record(
        "BREAKAGE_LOGGED", summary, actor="Store manager",
        loss_id=loss["id"], sku=sku, product=loss["product"], store=STORE,
        qty=qty, condition=condition, cost=cost,
        unit_cost=row["unit_cost"], before=before, after=after,
        source=source, photo=photo,
    )
    return loss


@router.get("/breakage")
def breakage_page(request: Request, logged: str = ""):
    logged_loss = next((l for l in data.LOSSES if l["id"] == logged), None)
    return _page(request, logged=logged_loss)


@router.post("/breakage/log")
def breakage_log(request: Request, sku: str = Form(...),
                 qty: int = Form(...), condition: str = Form(...)):
    error = _validate(sku, qty, condition)
    if error:
        return _page(request, error=error)
    loss = _apply_loss(sku, qty, condition, source="manual")
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
    return _page(request, identified=identified)


@router.post("/breakage/photo/confirm")
def breakage_photo_confirm(request: Request, sku: str = Form(...),
                           qty: int = Form(...), condition: str = Form(...),
                           photo: str = Form("")):
    error = _validate(sku, qty, condition)
    if error:
        return _page(request, error=error)
    # The evidence photo only counts if it is a registered sample photo
    # for this product — the same registry the photo door matched against.
    evidence = None
    sample = next((s for s in vision.breakage_sample_photos()
                   if s["filename"] == photo and s["sku"] == sku), None)
    if sample is not None:
        evidence = sample["filename"]
    loss = _apply_loss(sku, qty, condition, source="photo", photo=evidence)
    return RedirectResponse(f"/breakage?logged={loss['id']}", status_code=303)


@router.get("/breakage-photos/{filename}")
def breakage_photo_file(filename: str):
    path = vision.breakage_sample_path(filename)
    if path is None:
        return RedirectResponse("/breakage", status_code=303)
    return FileResponse(path, media_type="image/jpeg", filename=filename)
