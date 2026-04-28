"""Demo dashboard exercising every view type.

Run:

    uvicorn dashboard:app --port 8081 --reload

Then open http://localhost:8081/
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from mindframe import serve
import demo_pack

app = serve(
    systems_path=HERE / "systems.json",
    packs={"demo": demo_pack},
    poll_interval=15,
    title="Mindframe — View Types Demo",
)
