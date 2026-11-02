"""Ledger screen: the hash-linked chain of custody for every dollar."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from .. import ledger

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


@router.get("/ledger")
def ledger_page(request: Request, verify: int = 0):
    result = None
    if verify:
        ok, count, bad = ledger.verify()
        result = {"ok": ok, "count": count, "bad": bad}
    return templates.TemplateResponse(request, "ledger.html", {
        "events": ledger.list_events(),
        "verify": result,
    })
