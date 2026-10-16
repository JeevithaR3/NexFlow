"""Generate (or regenerate) the demonstration SUMO network, route file and configuration."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.errors import NexFlowError  # noqa: E402
from app.sumo.netgen import generate_demo_files  # noqa: E402

if __name__ == "__main__":
    try:
        for k, v in generate_demo_files().items():
            print(f"{k:10s} {v}")
    except NexFlowError as exc:
        print(f"ERROR: {exc.message}\n{exc.hint or ''}")
        sys.exit(1)
