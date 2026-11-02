"""Append-only, hash-linked event ledger — a chain of custody for every dollar.

Every money event in the app — an invoice received, a count recorded, a
variance diagnosed, a claim sent, a credit applied, a PayPal payout, a
credit recovered — is written here as one event in a single ordered log.
Each event stores the SHA-256 hash of the event before it, and its own hash
is computed over that previous hash plus a canonical serialization of its
own fields. Editing, deleting, or reordering any event after the fact
changes the hashes downstream, and verify() catches it at the exact seq
where the chain breaks.

This is deliberately NOT a public blockchain: there is no network, no
token, no mining — it is the same tamper-evidence idea implemented as one
honest local log. Because every event is already hash-linked, the log is
chain-ready by design: the history (or just its head hash) could later be
anchored to a public chain without changing the event format.

Storage: data/ledger.json, a JSON list that is only ever appended to. On
first run (file missing or empty) the demo scenario's history on file is
seeded in chronological order, marked payload seeded=true.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "ledger.json"
GENESIS_PREV = "0" * 64

_EVENTS = None  # in-memory cache; the file is the source of truth


def _canonical(event):
    """Canonical JSON of the fields the hash covers (all but prev_hash/hash)."""
    body = {k: event[k] for k in ("seq", "ts", "type", "actor", "summary", "payload")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _hash(prev_hash, event):
    return hashlib.sha256((prev_hash + _canonical(event)).encode("utf-8")).hexdigest()


def _append(events, ts, type_, actor, summary, payload):
    prev_hash = events[-1]["hash"] if events else GENESIS_PREV
    event = {
        "seq": len(events),
        "ts": ts,
        "type": type_,
        "actor": actor,
        "summary": summary,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    event["hash"] = _hash(prev_hash, event)
    events.append(event)
    return event


def _seed_events():
    """The demo scenario's history, in chronological order (all fictional)."""
    events = []
    _append(events, "2026-10-01T09:00:00+00:00", "GENESIS", "system",
            "Ledger opened — the chain of custody for every dollar begins "
            "here. Each event below is hash-linked to the one before it.",
            {"seeded": True})
    _append(events, "2026-10-08T09:00:00+00:00", "CLAIM_SENT", "Store manager",
            "Claim CLM-1001 sent to Heartland Grocery Wholesale — $81.60 "
            "for Paper Towels 6pk billed on invoice HG-31077 that never "
            "arrived.",
            {"seeded": True, "claim_id": "CLM-1001",
             "supplier_id": "sup-heartland",
             "supplier": "Heartland Grocery Wholesale",
             "invoice_number": "HG-31077", "amount": 81.60})
    _append(events, "2026-10-22T08:30:00+00:00", "INVOICE_RECEIVED",
            "Invoice Pay Agent",
            "Invoice PS-88510 from Prairie State Beverage Co. received and "
            "extracted (paste/extract door) — total $256.68.",
            {"seeded": True, "invoice_id": "inv-2050",
             "invoice_number": "PS-88510", "supplier_id": "sup-prairie",
             "supplier": "Prairie State Beverage Co.", "total": 256.68,
             "source": "extract"})
    _append(events, "2026-10-29T10:15:00+00:00", "COUNT_RECORDED", "Dana W.",
            "Count recorded at Store A — Cold Brew Concentrate 32oz "
            "(CB-1301): system says 14, shelf holds 2.",
            {"seeded": True, "variance_id": "cnt-101", "sku": "CB-1301",
             "store": "Store A", "system_qty": 14, "counted_qty": 2,
             "variance": -12})
    _append(events, "2026-10-29T10:20:00+00:00", "VARIANCE_DIAGNOSED",
            "Invoice Pay Agent",
            "Variance on Cold Brew Concentrate 32oz (Store A) diagnosed: "
            "vendor short — one case billed on invoice PS-88510, no "
            "receiving record. $186.00 at cost.",
            {"seeded": True, "variance_id": "cnt-101", "sku": "CB-1301",
             "cause": "vendor_short", "invoice_number": "PS-88510",
             "amount": 186.00})
    return events


def _save(events):
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=1, ensure_ascii=False)


def _load():
    global _EVENTS
    if _EVENTS is not None:
        return _EVENTS
    events = []
    if LEDGER_PATH.exists():
        with open(LEDGER_PATH, encoding="utf-8") as f:
            events = json.load(f)
    if not events:
        events = _seed_events()
        _save(events)
    _EVENTS = events
    return _EVENTS


def record(type_, summary, actor="manager", **payload):
    """Append one event and persist. Payload values must be JSON-safe
    (ids, numbers, short strings) — they are part of the hashed record."""
    events = _load()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    event = _append(events, ts, type_, actor, summary, payload)
    _save(events)
    return event


def safe_record(type_, summary, actor="manager", **payload):
    """record() for the live flows: a ledger hiccup must never break an
    invoice, payment, or claim that already succeeded."""
    try:
        return record(type_, summary, actor=actor, **payload)
    except Exception:
        return None


def list_events():
    return list(_load())


def for_ref(claim_id=None, invoice_id=None, variance_id=None):
    """Events whose payload references any of the given ids, in chain order —
    the mini 'chain of custody' strips on the bill and variance pages."""
    out = []
    for e in _load():
        p = e["payload"]
        if (claim_id and p.get("claim_id") == claim_id) \
                or (invoice_id and p.get("invoice_id") == invoice_id) \
                or (variance_id and p.get("variance_id") == variance_id):
            out.append(e)
    return out


def verify_chain(events):
    """Recompute a chain end to end. Returns (ok, count, first_bad_seq).

    A chain is intact when seqs are gapless from 0, every prev_hash points
    at the previous event's hash, and every hash recomputes exactly.
    """
    prev_hash = GENESIS_PREV
    for i, event in enumerate(events):
        if event.get("seq") != i or event.get("prev_hash") != prev_hash:
            return False, len(events), i
        if _hash(prev_hash, event) != event.get("hash"):
            return False, len(events), i
        prev_hash = event["hash"]
    return True, len(events), None


def verify():
    """Verify the ledger on file. Returns (ok, count, first_bad_seq_or_None)."""
    return verify_chain(_load())
