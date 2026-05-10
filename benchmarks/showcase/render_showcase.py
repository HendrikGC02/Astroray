"""Compatibility CLI for the pkg74 showcase runner."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from .runner import main
except ImportError:  # pragma: no cover - direct script execution
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from benchmarks.showcase.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
