"""Filesystem paths for the app's data layer.

SEED_DIR is the data/ folder bundled in the repo — the demo's seeded
state. DATA_DIR is where the running app reads and writes: it defaults
to SEED_DIR for local runs, and on a hosted deploy it is set (env var
DATA_DIR) to a persistent disk mount so state survives restarts.

On first boot with a separate DATA_DIR, ensure_data_dir() copies the
seed files over; after that the disk copy is the source of truth and
the repo's seed files are never touched.
"""
import os
import shutil
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("DATA_DIR") or SEED_DIR)


def ensure_data_dir():
    """Seed DATA_DIR from the bundled repo data on first boot."""
    if DATA_DIR == SEED_DIR:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for seed in SEED_DIR.glob("*.json"):
        target = DATA_DIR / seed.name
        if not target.exists():
            shutil.copy2(seed, target)
    seed_samples = SEED_DIR / "sample_invoices"
    target_samples = DATA_DIR / "sample_invoices"
    if seed_samples.is_dir() and not target_samples.exists():
        shutil.copytree(seed_samples, target_samples)
