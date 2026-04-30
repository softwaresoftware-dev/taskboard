"""Smallest possible taskboard dashboard.

Run:

    uvicorn dashboard:app --port 8080 --reload

Then open http://localhost:8080/
"""
from pathlib import Path

from taskboard import serve

HERE = Path(__file__).parent

app = serve(
    systems_path=HERE / "systems.json",
    poll_interval=15,
    title="Taskboard — Minimal Example",
)
