"""Build the frontend when requested, then run the local Python server."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-frontend", action="store_true")
    args = parser.parse_args()
    if args.build_frontend:
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True)
    environment = os.environ.copy()
    environment.setdefault("AUTODEPLOY_DATA_DIR", str(ROOT / ".runtime" / "data"))
    environment.setdefault("AUTODEPLOY_ENV_FILE", str(ROOT / ".env"))
    os.execve(sys.executable, [sys.executable, "-m", "webapp"], environment)


if __name__ == "__main__":
    main()
