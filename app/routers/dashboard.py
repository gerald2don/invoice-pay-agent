"""Dashboard: trending x stock lists + the marketing draft queue."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from .. import data, variance

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request):
    variance.watchdog()
    return templates.TemplateResponse(request, "dashboard.html", {
        "t": data.TRENDING,
        "digest": variance.owner_digest(),
    })
