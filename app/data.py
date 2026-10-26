"""Loads the demo data layer (data/*.json) and holds runtime payment state.

The pay flow runs on fictional sample data (see README). The Shelf Guide
locations are the pilot store's real, verified product locations.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


SUPPLIERS = {s["id"]: s for s in _load("suppliers.json")}
ITEM_MASTER = {i["sku"]: i for i in _load("item_master.json")}
INVOICES = _load("invoices.json")
GUIDE_LOCATIONS = _load("guide_locations.json")
TRENDING = _load("trending.json")

# Runtime state (skeleton): payments made this session, keyed by invoice id.
PAYMENTS = {}


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
