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

# Rails 2 and 3 on the same PayPal connection: Ad Boosting and Quick Runs.
# Same DATA_DIR JSON persistence as invoices/claims — seeded from data/*.json
# on first boot, written back on every change, so a paid run or an active
# boost survives a restart.
QUICK_RUNS = _load("quick_runs.json")
BOOST_PATTERNS = _load("boost_patterns.json")
BOOSTS = _load("boosts.json")

# Breakage / loss reporting: every logged loss (manual or photo door),
# priced at cost, with the inventory counts it moved. Same DATA_DIR JSON
# persistence — a loss logged before a restart is still on the books
# after it, and the inventory decrement it made stays made.
LOSSES = _load("losses.json")

# The owner's standing small-dollar rule for Quick Runs: at or under this
# total a routine run is pre-approved — it goes on its own and the manager
# gets the notice after the fact. Above it, the run waits for a tap, like
# everything else in the platform.
AUTO_APPROVE_LIMIT = 25.00

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


def save_quick_runs():
    _save("quick_runs.json", QUICK_RUNS)


def save_boosts():
    _save("boosts.json", BOOSTS)


def save_losses():
    _save("losses.json", LOSSES)


def save_inventory():
    _save("inventory.json", INVENTORY)


def run_by_id(run_id):
    for run in QUICK_RUNS:
        if run["id"] == run_id:
            return run
    return None


def run_total(run):
    return round(sum(i["qty"] * i["price"] for i in run["items"]), 2)


def pattern_by_id(pattern_id):
    for pat in BOOST_PATTERNS:
        if pat["id"] == pattern_id:
            return pat
    return None


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
