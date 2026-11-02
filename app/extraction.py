"""Invoice text extraction: OCR-style raw invoice text in, structured bill out.

This is the deterministic core of the photo-first pipeline. A photographed
invoice is OCR'd into raw text (data/extraction_fixtures.json holds the
ground truth this module is verified against); this module parses the line
items, fuzzy-matches each description against the item master, and scores a
per-line confidence so the bill review can flag what needs a human look.

House rules encoded here (from the fixtures):
- Fuel surcharge lines are never bill lines: they are dropped and noted,
  and the bill total excludes them — the difference against the printed
  total is shown, not hidden.
- A line with no item-master match stays unmatched (confidence 0) and is
  flagged for the manager instead of guessing a SKU.
- If the master item is a pack (e.g. 8pk) and the invoice never printed a
  pack size, the match is kept but confidence is docked and flagged.
- Exact duplicate lines are flagged, never silently merged or double-paid.
- Vendor credit-memo lines are not bill lines either: they are captured as
  credit_lines (amount, memo number, the invoice they credit) so the claims
  watchdog can match them, and the totals check credits them openly.
"""
import re
from difflib import SequenceMatcher

# Supplier abbreviations seen on real invoice printouts -> master wording.
ABBREVIATIONS = {
    "cig": "cigarette",
    "org": "orange",
    "pot": "potato",
    "pty": "party",
    "sz": "size",
    "disp": "display",
    "wtr": "water",
    "sprk": "sparkling",
    "btl": "bottle",
    "lem": "lemon",
    "twl": "towel",
}

MATCH_THRESHOLD = 0.55   # best score below this -> no SKU match
PACK_MISSING_PENALTY = 0.15

_MONEY = re.compile(r"^\$?\d+\.\d{2}$")
_INT = re.compile(r"^\d+$")
_UNIT_WORD = re.compile(r"^[A-Za-z]{1,4}$")  # CTN, CS, EA ... between qty and price
_NUMBER = re.compile(r"\b([A-Z]{2,3}-\d{3,})\b")
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_PACK = re.compile(r"(\d+)\s*(pk|ct)\b", re.IGNORECASE)
_MEMO = re.compile(r"\bCM-\d+\b")


def _tokens(text):
    """Lowercase word/number tokens, splitting glued units (36CT -> 36, ct)."""
    toks = []
    for raw in re.sub(r"[^a-z0-9]+", " ", text.lower()).split():
        toks.extend(re.findall(r"\d+|[a-z]+", raw))
    return toks


def _singular(tok):
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _match_form(text):
    """(token set, joined string) normalized for description matching."""
    toks = [_singular(ABBREVIATIONS.get(t, t)) for t in _tokens(text)]
    return set(toks), " ".join(toks)


def _score(inv_toks, inv_str, item_toks, item_str):
    """Blend of master-token coverage, token F1, and raw string similarity.

    Coverage-heavy so extra printed detail on the invoice (case sizes like
    12/12OZ) does not tank an otherwise exact match.
    """
    inter = len(inv_toks & item_toks)
    if not inter:
        return 0.0
    coverage = inter / len(item_toks)
    f1 = 2 * inter / (len(inv_toks) + len(item_toks))
    ratio = SequenceMatcher(None, inv_str, item_str).ratio()
    return max(ratio, 0.65 * coverage + 0.35 * f1)


def _pack_descriptor(item_name):
    """'Sparkling Water Lime 8pk' -> ('8', '8pk'); None when not a pack."""
    m = _PACK.search(item_name)
    if not m:
        return None
    return m.group(1), f"{m.group(1)}{m.group(2).lower()}"


def match_item(description, items):
    """Best item-master match for one invoice description.

    Returns (item, confidence, flags). Item is None when nothing clears the
    threshold — the line stays unmatched and flagged rather than guessed.
    """
    inv_toks, inv_str = _match_form(description)
    best, best_score = None, 0.0
    for item in items:
        item_toks, item_str = _match_form(item["name"])
        score = _score(inv_toks, inv_str, item_toks, item_str)
        if score > best_score:
            best, best_score = item, score
    if best is None or best_score < MATCH_THRESHOLD:
        return None, 0.0, ["no item-master match - manager must map or skip"]

    confidence = best_score
    flags = []
    pack = _pack_descriptor(best["name"])
    if pack and pack[0] not in re.findall(r"\d+", description):
        confidence -= PACK_MISSING_PENALTY
        flags.append(f"pack size not printed on invoice ({pack[1]} assumed from master)")
    return best, round(max(0.0, min(1.0, confidence)), 2), flags


def _match_supplier(header, suppliers):
    """Match the invoice's header line to a supplier by name overlap."""
    head_toks = set(_tokens(header))
    best_id, best_cov = None, 0.0
    for sup in suppliers:
        sup_toks = set(_tokens(sup["name"]))
        if not sup_toks:
            continue
        cov = len(head_toks & sup_toks) / len(sup_toks)
        if cov > best_cov:
            best_id, best_cov = sup["id"], cov
    return best_id if best_cov >= 0.75 else None


def _parse_item_line(line):
    """'DESC  QTY [UNIT]  UNIT_COST  EXT' -> (desc, qty, unit_cost) or None."""
    toks = line.split()
    if len(toks) < 4 or not _MONEY.match(toks[-1]) or not _MONEY.match(toks[-2]):
        return None
    unit_cost = float(toks[-2].lstrip("$"))
    rest = toks[:-2]
    if len(rest) >= 2 and _UNIT_WORD.match(rest[-1]) and _INT.match(rest[-2]):
        rest = rest[:-1]  # carton/each wording between qty and price
    if not _INT.match(rest[-1]):
        return None
    qty = int(rest[-1])
    desc = " ".join(rest[:-1])
    return (desc, qty, unit_cost) if desc else None


def extract_invoice(raw_text, items=None, suppliers=None):
    """Extract a structured bill from raw invoice text.

    Returns the fixture-shaped dict: number, date, supplier_id, lines
    (raw_text, qty, unit_cost, matched_sku, confidence, flags),
    dropped_lines, invoice-level flags, the bill total (extracted lines
    only), the printed total, and a totals_check comparing the two.
    """
    if items is None or suppliers is None:
        from . import data
        items = items if items is not None else list(data.ITEM_MASTER.values())
        suppliers = suppliers if suppliers is not None else list(data.SUPPLIERS.values())

    rows = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    number_m = _NUMBER.search(raw_text)
    date_m = _DATE.search(raw_text)

    lines, dropped, credits, flags = [], [], [], []
    stated_total = None
    seen = {}
    for row in rows:
        toks = row.split()
        if toks and toks[0].upper() == "TOTAL":
            amounts = re.findall(r"\d+\.\d{2}", row)
            if amounts:
                stated_total = float(amounts[-1])
            continue
        parsed = _parse_item_line(row)
        if parsed is None:
            if "CREDIT" in row.upper():
                amounts = re.findall(r"\d+\.\d{2}", row)
                memo_m = _MEMO.search(row)
                refs = [m for m in _NUMBER.findall(row)
                        if not (memo_m and m == memo_m.group(0))]
                item, _conf, _fl = match_item(row, items)
                credits.append({
                    "raw_text": row,
                    "amount": float(amounts[-1]) if amounts else 0.0,
                    "memo": memo_m.group(0) if memo_m else None,
                    "for_invoice": refs[0] if refs else None,
                    "matched_sku": item["sku"] if item else None,
                })
                continue
            if "SURCHARGE" in row.upper():
                amounts = re.findall(r"\d+\.\d{2}", row)
                dropped.append({
                    "raw_text": re.sub(r"\s*\$?\d+\.\d{2}\s*$", "", row),
                    "amount": float(amounts[-1]) if amounts else 0.0,
                    "reason": "fuel surcharges are never entered as bill lines",
                })
            continue
        desc, qty, unit_cost = parsed
        item, confidence, line_flags = match_item(desc, items)
        key = (desc.upper(), qty, unit_cost)
        if key in seen:
            line_flags = line_flags + [
                "exact duplicate line on the same invoice - flag, "
                "do not silently merge or double-pay"
            ]
            if "duplicate line present" not in flags:
                flags.append("duplicate line present")
        seen[key] = True
        lines.append({
            "raw_text": desc,
            "qty": qty,
            "unit_cost": unit_cost,
            "matched_sku": item["sku"] if item else None,
            "confidence": confidence,
            "flags": line_flags,
        })

    computed_total = round(sum(l["qty"] * l["unit_cost"] for l in lines), 2)
    dropped_total = round(sum(d["amount"] for d in dropped), 2)
    credit_total = round(sum(c["amount"] for c in credits), 2)
    difference = None
    explained = False
    explained_credit = False
    if stated_total is not None:
        difference = round(stated_total - computed_total, 2)
        explained = abs(difference - dropped_total) < 0.005 and dropped_total > 0
        explained_credit = abs(difference + credit_total) < 0.005 and credit_total > 0
        if abs(difference) >= 0.005:
            flags.append(
                "total mismatch vs printed invoice is fully explained by the dropped surcharge"
                if explained else
                "total difference vs printed invoice is fully explained by the vendor credit line"
                if explained_credit else
                "total mismatch vs printed invoice - verify before paying"
            )

    return {
        "number": number_m.group(1) if number_m else None,
        "date": (f"{date_m.group(3)}-{int(date_m.group(1)):02d}-{int(date_m.group(2)):02d}"
                 if date_m else None),
        "supplier_id": _match_supplier(rows[0], suppliers) if rows else None,
        "lines": lines,
        "dropped_lines": dropped,
        "credit_lines": credits,
        "flags": flags,
        "total": computed_total,
        "stated_total": stated_total,
        "totals_check": {
            "computed_total": computed_total,
            "stated_total": stated_total,
            "difference": difference,
            "dropped_total": dropped_total,
            "credit_total": credit_total,
            "explained_by_dropped": explained,
            "explained_by_credit": explained_credit,
            "matches": (stated_total is None or abs(difference) < 0.005
                        or explained or explained_credit),
        },
    }
