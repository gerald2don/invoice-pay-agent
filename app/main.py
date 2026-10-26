"""Invoice Pay Agent — FastAPI app: manager pay flow, Shelf Guide, dashboard."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import dashboard, guide, manager

app = FastAPI(title="Invoice Pay Agent")

_static = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")

app.include_router(manager.router)
app.include_router(guide.router)
app.include_router(dashboard.router)
