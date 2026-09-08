from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_documentation_links_and_corporate_isolation() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
