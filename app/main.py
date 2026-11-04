"""Invoice Pay Agent — FastAPI app: three PayPal rails (supplier pay, ad
boosting, Quick Runs), breakage/loss reporting, Shelf Guide, dashboard."""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import boost, breakage, dashboard, guide, ledger, manager, quick_runs, variance

# Load repo-root .env (PayPal sandbox credentials) when present.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="Invoice Pay Agent")

_static = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")

app.include_router(manager.router)
app.include_router(boost.router)
app.include_router(quick_runs.router)
app.include_router(breakage.router)
app.include_router(guide.router)
app.include_router(dashboard.router)
app.include_router(variance.router)
app.include_router(ledger.router)
