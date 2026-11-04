"""Ad Boosting screens — PayPal inside the app (rail 2).

Boosting means paying an ad platform to show a post to more people. Every
one of the store's posts can be boosted — there is no eligibility gate.
What the app adds is homework: it *rates* each post from the store's own
results record and shows an *estimate* of what a boost would likely do,
computed from that post's organic reach and engagement. The estimate is a
guide, not a promise, and the manager makes the call: pick any post, set
the budget and the number of days, approve, and PayPal pays the ad
platform. Boosts are managed from this one screen — started, listed, and
ended here — and every dollar lands in the same hash-linked ledger as
supplier pay and Quick Runs.
"""
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import data, ledger, paypal_client

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()

# The ad platform the store's boosts run on — paid through the same PayPal
# connection as supplier pay and Quick Runs.
AD_PLATFORM = {"name": "Meta Ads (Facebook & Instagram)",
               "paypal_email": "billing@metaads.example"}
BUDGET_PRESETS = [10, 20, 35, 50]
DURATION_PRESETS = [3, 5, 7]

# The reference boost every pattern card is estimated at. The estimate
# scales from here when the manager picks a different budget or run.
REFERENCE_BUDGET = 20
REFERENCE_DAYS = 5

# Rating tiers, from the post's own organic numbers. Thresholds are plain
# and shown on the page: reach says how many people the post already
# found, engagement rate says how they reacted, and store visits per
# 1,000 reach says how many of them walked in.
def rate_pattern(pat):
    """Plain-language rating from a pattern's organic stats."""
    reach = pat["reach"]
    eng_rate = pat["engagement"] / reach if reach else 0.0
    visits_per_1k = pat["store_visits"] * 1000 / reach if reach else 0.0
    if reach < 1000:
        return "Too new to tell"
    if reach >= 10000 and eng_rate >= 0.06 and visits_per_1k >= 10:
        return "Strong"
    if reach >= 5000 and eng_rate >= 0.04 and visits_per_1k >= 6:
        return "Decent"
    return "Light"


# How much extra reach a boost is estimated to buy, as a multiple of the
# post's organic reach at the reference budget. Stronger posts earn wider
# multiples: the platform's delivery steers paid reach toward the people
# most likely to respond, and a post that already gets responses gives it
# more to steer with. A post with barely any organic signal gets the
# narrowest, roughest band.
_ESTIMATE_BANDS = {
    "Strong": (1.6, 2.4),
    "Decent": (1.2, 1.8),
    "Light": (0.6, 1.1),
    "Too new to tell": (0.3, 0.8),
}


def _round_estimate(x):
    if x >= 1000:
        return int(round(x / 100.0)) * 100
    return int(round(x / 10.0)) * 10


def estimate_boost(pat, budget=REFERENCE_BUDGET, days=REFERENCE_DAYS):
    """Estimated extra reach (and store visits) a boost would buy.

    Computed from the pattern's own organic numbers: the rating band's
    multiple of organic reach, scaled linearly with budget and with the
    square root of the run length (longer runs spread the same money
    thinner). Returns (reach_low, reach_high, visits_low, visits_high,
    rough) where rough flags a low-signal post whose numbers are a
    rougher guide.
    """
    rating = rate_pattern(pat)
    low_f, high_f = _ESTIMATE_BANDS[rating]
    scale = (budget / REFERENCE_BUDGET) * (days / REFERENCE_DAYS) ** 0.5
    reach_low = _round_estimate(pat["reach"] * low_f * scale)
    reach_high = _round_estimate(pat["reach"] * high_f * scale)
    # Visits scale with reach at the post's own organic visit rate.
    visit_rate = pat["store_visits"] / pat["reach"] if pat["reach"] else 0.0
    visits_low = int(round(reach_low * visit_rate))
    visits_high = int(round(reach_high * visit_rate))
    rough = rating in ("Light", "Too new to tell")
    return reach_low, reach_high, visits_low, visits_high, rough


def _pattern_view(pat):
    view = dict(pat)
    view["rating"] = rate_pattern(pat)
    low, high, vlow, vhigh, rough = estimate_boost(pat)
    view["est_reach_low"] = low
    view["est_reach_high"] = high
    view["est_visits_low"] = vlow
    view["est_visits_high"] = vhigh
    view["est_rough"] = rough
    return view


@router.get("/boost")
def boost_page(request: Request, boosted: str = "", ended: str = ""):
    return templates.TemplateResponse(request, "boost.html", {
        "patterns": [_pattern_view(p) for p in data.BOOST_PATTERNS],
        "boosts": list(reversed(data.BOOSTS)),
        "budgets": BUDGET_PRESETS,
        "durations": DURATION_PRESETS,
        "ref_budget": REFERENCE_BUDGET,
        "ref_days": REFERENCE_DAYS,
        "boosted_id": boosted,
        "ended_id": ended,
        "paypal_configured": paypal_client.configured(),
    })


@router.post("/boost/{pattern_id}/pay")
def boost_pay(pattern_id: str, budget: int = Form(...), days: int = Form(...)):
    pat = data.pattern_by_id(pattern_id)
    if pat is None:
        return RedirectResponse("/boost", status_code=303)
    if budget not in BUDGET_PRESETS:
        budget = BUDGET_PRESETS[1]
    if days not in DURATION_PRESETS:
        days = DURATION_PRESETS[1]
    record = paypal_client.pay_payee(
        payee_name=AD_PLATFORM["name"],
        payee_email=AD_PLATFORM["paypal_email"],
        amount=float(budget),
        ref="BOOST-" + pattern_id.upper(),
        subject=f"Ad boost — {pat['title']}",
        note=(f"Boost of '{pat['pattern']}' — "
              f"${budget} over {days} days"),
    )
    nums = [int(b["id"].split("-")[-1]) for b in data.BOOSTS
            if b["id"].split("-")[-1].isdigit()]
    low, high, vlow, vhigh, rough = estimate_boost(pat, budget, days)
    bst = {
        "id": f"bst-{max(nums, default=300) + 1}",
        "pattern_id": pat["id"],
        "title": pat["title"],
        "pattern": pat["pattern"],
        "budget": budget,
        "days": days,
        "status": "active",
        "started": data.today(),
        "payment": record,
        "rating": rate_pattern(pat),
        "estimate": {
            "reach_low": low,
            "reach_high": high,
            "visits_low": vlow,
            "visits_high": vhigh,
            "rough": rough,
        },
    }
    data.BOOSTS.append(bst)
    data.save_boosts()
    ledger.safe_record(
        "AD_BOOST_PAID",
        f"Ad boost paid via {record['provider']} — ${budget:.2f} to "
        f"{AD_PLATFORM['name']} to boost '{pat['pattern']}' for {days} "
        f"days (batch {record['reference']}). The app rated the post "
        f"{bst['rating']} from its own results "
        f"({pat['reach']:,} reach, {pat['store_visits']} store visits) "
        f"and estimated +{low:,} to +{high:,} reach on this spend; the "
        f"manager made the call.",
        actor="Store manager",
        rail="ad_boost", boost_id=bst["id"], pattern_id=pat["id"],
        amount=float(budget), days=days, reference=record["reference"],
        provider=record["provider"],
    )
    return RedirectResponse(f"/boost?boosted={bst['id']}", status_code=303)


@router.post("/boost/{boost_id}/end")
def boost_end(boost_id: str):
    bst = next((b for b in data.BOOSTS if b["id"] == boost_id), None)
    if bst is None or bst["status"] != "active":
        return RedirectResponse("/boost", status_code=303)
    bst["status"] = "ended"
    bst["ended"] = data.today()
    data.save_boosts()
    ledger.safe_record(
        "AD_BOOST_ENDED",
        f"Ad boost {bst['id']} ended by the manager — '{bst['pattern']}' "
        f"was boosted at ${bst['budget']:.2f} over {bst['days']} days "
        f"(started {bst['started']}, payout reference "
        f"{bst['payment']['reference']}). The boost stays on the books "
        f"as history.",
        actor="Store manager",
        rail="ad_boost", boost_id=bst["id"], pattern_id=bst["pattern_id"],
        reference=bst["payment"]["reference"],
    )
    return RedirectResponse(f"/boost?ended={bst['id']}", status_code=303)
