"""Loads the demo data layer (data/*.json) and holds runtime payment state.

The pay flow runs on fictional sample data (see README). The Shelf Guide
locations are the pilot store's real, verified product locations.
"""
import json

from . import paths
from .paths import DATA_DIR

paths.ensure_data_dir()


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _save(name, obj):
    with open(DATA_DIR / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


SUPPLIERS = {s["id"]: s for s in _load("suppliers.json")}
ITEM_MASTER = {i["sku"]: i for i in _load("item_master.json")}
INVOICES = _load("invoices.json")
GUIDE_LOCATIONS = _load("guide_locations.json")
TRENDING = _load("trending.json")

# Variance & claims layer: system stock, physical counts, the evidence
# records a diagnosis walks, and vendor credit claims (seeded history plus
# claims created this session — same append-in-memory pattern as INVOICES).
INVENTORY = _load("inventory.json")
COUNTS = _load("counts.json")
EVIDENCE = _load("evidence.json")
CLAIMS = _load("claims.json")

# Runtime state, persisted to DATA_DIR/runtime_state.json so payments and
# resolutions survive a restart on a hosted deploy (on the seeded first
# boot the file does not exist yet and both start empty).
def _load_runtime_state():
    try:
        with open(DATA_DIR / "runtime_state.json", encoding="utf-8") as f:
            state = json.load(f)
        return state.get("payments", {}), state.get("resolutions", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, {}


# Payments made, keyed by invoice id.
PAYMENTS, RESOLUTIONS = _load_runtime_state()


def save_runtime_state():
    _save("runtime_state.json",
          {"payments": PAYMENTS, "resolutions": RESOLUTIONS})


def save_invoices():
    _save("invoices.json", INVOICES)


def save_claims():
    _save("claims.json", CLAIMS)


def inventory_for(sku, store):
    for row in INVENTORY:
        if row["sku"] == sku and row["store"] == store:
            return row
    return None


def count_by_id(count_id):
    for c in COUNTS:
        if c["id"] == count_id:
            return c
    return None


def today():
    """The demo's 'today': the latest dated store activity on file."""
    dates = [c["date"] for c in COUNTS] + [i["date"] for i in INVOICES if i.get("date")]
    return max(dates) if dates else "2026-10-29"


def invoice_by_id(invoice_id):
    for inv in INVOICES:
        if inv["id"] == invoice_id:
            return inv
    return None


def invoice_total(inv):
    return round(sum(l["qty"] * l["unit_cost"] for l in inv["lines"]), 2)


def guide_by_slug(slug):
    for loc in GUIDE_LOCATIONS:
        if loc["slug"] == slug:
            return loc
    return None
