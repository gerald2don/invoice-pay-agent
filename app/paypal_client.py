"""PayPal sandbox payment leg.

Reads credentials from the environment only (PAYPAL_CLIENT_ID /
PAYPAL_CLIENT_SECRET / PAYPAL_ENV). With no credentials configured the agent
runs in a clearly-labeled SIMULATED mode so the full approve -> pay -> record
flow can be reviewed end to end. With sandbox credentials, approval sends a
real sandbox payout via the PayPal Payouts API.
"""
import os
import uuid

import httpx

_BASE = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


def configured():
    return bool(os.getenv("PAYPAL_CLIENT_ID") and os.getenv("PAYPAL_CLIENT_SECRET"))


def _base():
    return _BASE.get(os.getenv("PAYPAL_ENV", "sandbox"), _BASE["sandbox"])


def _access_token():
    resp = httpx.post(
        f"{_base()}/v1/oauth2/token",
        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def pay_supplier(*, supplier, amount, invoice_ref):
    """Pay a supplier for an approved bill. Returns a payment record dict."""
    if not configured():
        return {
            "status": "simulated",
            "provider": "PayPal sandbox (not configured — simulated)",
            "reference": "SIM-" + uuid.uuid4().hex[:12].upper(),
            "amount": amount,
            "payee": supplier["name"],
        }
    token = _access_token()
    batch_id = "INV-" + invoice_ref.replace("/", "-")
    payload = {
        "sender_batch_header": {
            "sender_batch_id": batch_id + "-" + uuid.uuid4().hex[:8],
            "email_subject": f"Payment for invoice {invoice_ref}",
        },
        "items": [
            {
                "recipient_type": "EMAIL",
                "amount": {"value": f"{amount:.2f}", "currency": "USD"},
                "receiver": supplier["paypal_email"],
                "note": f"Invoice {invoice_ref}",
                "sender_item_id": batch_id,
            }
        ],
    }
    resp = httpx.post(
        f"{_base()}/v1/payments/payouts",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    return {
        "status": "paid",
        "provider": "PayPal sandbox",
        "reference": body["batch_header"]["payout_batch_id"],
        "amount": amount,
        "payee": supplier["name"],
    }
