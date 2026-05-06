#!/usr/bin/env python
"""Run Astroray pytest with the right build, DLL, and temp-dir setup."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run pytest against an Astroray build directory."
    )
    parser.add_argument(
        "--build-dir",
        default=os.environ.get("ASTRORAY_BUILD_DIR", str(REPO_ROOT / "build_tcnn")),
        help="CMake build directory to test, default: ./build_tcnn",
    )
    parser.add_argument(
        "--temp-dir",
        default=os.environ.get("ASTRORAY_TEST_TEMP_DIR", str(REPO_ROOT / "test_results" / "tmp")),
        help="Scratch directory for pytest/tempfile, default: ./test_results/tmp",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to pytest. Prefix with -- to separate them.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    build_dir = Path(args.build_dir).resolve()
    temp_dir = Path(args.temp_dir).resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)

    os.environ["ASTRORAY_BUILD_DIR"] = str(build_dir)
    os.environ["ASTRORAY_TEST_TEMP_DIR"] = str(temp_dir)
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)

    sys.path.insert(0, str(TESTS_DIR))
    from runtime_setup import configure_test_imports  # noqa: PLC0415

    configure_test_imports()

    import pytest  # noqa: PLC0415

    pytest_args = list(args.pytest_args)
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    if not pytest_args:
        pytest_args = ["tests", "-v", "--tb=short"]
    if not any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in pytest_args):
        pytest_args.extend(["--basetemp", str(temp_dir)])
    return pytest.main(pytest_args)


if __name__ == "__main__":
    raise SystemExit(main())
