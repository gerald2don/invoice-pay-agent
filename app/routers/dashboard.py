"""Dashboard: trending x stock lists + the marketing draft queue."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from .. import data

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"t": data.TRENDING})
