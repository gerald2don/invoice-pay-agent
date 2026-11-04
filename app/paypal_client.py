"""PayPal sandbox payment leg.

Reads credentials from the environment only (PAYPAL_CLIENT_ID /
PAYPAL_CLIENT_SECRET / PAYPAL_ENV). With no credentials configured the agent
runs in a clearly-labeled SIMULATED mode so the full approve -> pay -> record
flow can be reviewed end to end. With sandbox credentials, approval sends a
real sandbox payout via the PayPal Payouts API.

One rail, three loops: supplier pay (pay_supplier), ad boosting, and Quick
Runs all send through pay_payee — the same token, the same Payouts API, the
same record shape — so every dollar out of the store moves the same way.
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


def pay_payee(*, payee_name, payee_email, amount, ref, subject, note):
    """Pay any payee through the PayPal Payouts API. Returns a payment
    record dict — the same shape every rail in this app records."""
    if not configured():
        return {
            "status": "simulated",
            "provider": "PayPal sandbox (not configured — simulated)",
            "reference": "SIM-" + uuid.uuid4().hex[:12].upper(),
            "amount": amount,
            "payee": payee_name,
        }
    token = _access_token()
    batch_id = ref.replace("/", "-")
    payload = {
        "sender_batch_header": {
            "sender_batch_id": batch_id + "-" + uuid.uuid4().hex[:8],
            "email_subject": subject,
        },
        "items": [
            {
                "recipient_type": "EMAIL",
                "amount": {"value": f"{amount:.2f}", "currency": "USD"},
                "receiver": payee_email,
                "note": note,
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
        "payee": payee_name,
    }


def pay_supplier(*, supplier, amount, invoice_ref):
    """Pay a supplier for an approved bill (rail 1: Supplier Pay)."""
    return pay_payee(
        payee_name=supplier["name"],
        payee_email=supplier["paypal_email"],
        amount=amount,
        ref="INV-" + invoice_ref,
        subject=f"Payment for invoice {invoice_ref}",
        note=f"Invoice {invoice_ref}",
    )
