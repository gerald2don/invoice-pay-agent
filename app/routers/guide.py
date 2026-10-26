"""Shelf Guide: staff product finder — map dot + verified shelf location."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .. import data
from ..render_map import render_map

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()


@router.get("/guide")
def guide_home(request: Request, q: str = ""):
    results = data.GUIDE_LOCATIONS
    if q:
        ql = q.lower()
        results = [l for l in results if ql in l["name"].lower()]
    return templates.TemplateResponse(request, "guide.html", {"results": results, "q": q})


@router.get("/guide/{slug}")
def guide_detail(request: Request, slug: str):
    loc = data.guide_by_slug(slug)
    if loc is None:
        return RedirectResponse("/guide", status_code=303)
    photo = Path(__file__).resolve().parent.parent / "static" / "photos" / f"{slug}.jpg"
    return templates.TemplateResponse(request, "guide_detail.html", {
        "loc": loc,
        "has_photo": photo.exists(),
    })


@router.get("/map/{zone}.png")
def map_png(zone: str):
    return Response(content=render_map(zone), media_type="image/png")
