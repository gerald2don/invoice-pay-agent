"""Ad Boosting screens — PayPal inside the app (rail 2).

Boosting means paying an ad platform to show a post to more people. This
store's rule, from the Marketing module design: only a pattern the store's
own post results have already *proven* can be boosted — untested posts
can't be, so ad money never follows a hunch. The tracker below is the
store's own results record; it decides what is eligible. The manager picks
a proven pattern, sets the budget and the number of days, approves, and
PayPal pays the ad platform. The boost lands in the same hash-linked
ledger as every other dollar.
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


@router.get("/boost")
def boost_page(request: Request, boosted: str = ""):
    return templates.TemplateResponse(request, "boost.html", {
        "patterns": data.BOOST_PATTERNS,
        "boosts": list(reversed(data.BOOSTS)),
        "budgets": BUDGET_PRESETS,
        "durations": DURATION_PRESETS,
        "boosted_id": boosted,
        "paypal_configured": paypal_client.configured(),
    })


@router.post("/boost/{pattern_id}/pay")
def boost_pay(pattern_id: str, budget: int = Form(...), days: int = Form(...)):
    pat = data.pattern_by_id(pattern_id)
    if pat is None or not pat["proven"]:
        # The rule is enforced here, not just shown: an unproven pattern
        # cannot be boosted, whatever the form says.
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
        note=(f"Boost of proven pattern '{pat['pattern']}' — "
              f"${budget} over {days} days"),
    )
    nums = [int(b["id"].split("-")[-1]) for b in data.BOOSTS
            if b["id"].split("-")[-1].isdigit()]
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
    }
    data.BOOSTS.append(bst)
    data.save_boosts()
    ledger.safe_record(
        "AD_BOOST_PAID",
        f"Ad boost paid via {record['provider']} — ${budget:.2f} to "
        f"{AD_PLATFORM['name']} to boost the proven pattern "
        f"'{pat['pattern']}' for {days} days (batch "
        f"{record['reference']}). The pattern earned this spend: "
        f"{pat['reach']:,} reach and {pat['store_visits']} store visits "
        f"the last time it ran.",
        actor="Store manager",
        rail="ad_boost", boost_id=bst["id"], pattern_id=pat["id"],
        amount=float(budget), days=days, reference=record["reference"],
        provider=record["provider"],
    )
    return RedirectResponse(f"/boost?boosted={bst['id']}", status_code=303)
