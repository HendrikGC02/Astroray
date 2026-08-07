#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Two-pass CPU/GPU test runner (open-model-research-2026-08 latency lever 6).

Pass 1 (CPU): ``pytest -m cpu -n auto`` — the CPU-only subset in parallel via
              pytest-xdist. OMP_NUM_THREADS is left UNSET by default (all cores):
              pinning it starves the few OpenMP-heavy reference renders and the
              slowest single-threaded test dominates the tail. Pin explicitly
              with ``--omp N`` / ASTRORAY_TEST_OMP_THREADS after measuring.
Pass 2 (GPU): ``pytest -m "not cpu" -p no:xdist`` — everything not positively
              classified CPU, run strictly serial in a single GPU context.
              Anything left unclassified falls here (the SAFE side): memory
              cuda_verifier_concurrency documents false-positive illegal-access
              crashes from concurrent CUDA on this RTX.

Usage:
    python scripts/test/run_split.py                 # both passes, report wall time
    python scripts/test/run_split.py --cpu-only      # just the parallel CPU pass
    python scripts/test/run_split.py --gpu-only      # just the serial GPU pass
    python scripts/test/run_split.py --jobs 8        # override -n auto
    python scripts/test/run_split.py -- -x -q tests/test_foo.py   # extra pytest args

Extra pytest args after ``--`` are forwarded to BOTH passes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(label: str, marker: str, *, parallel: bool, jobs: str,
         omp: str | None, extra: list[str]) -> tuple[int, float]:
    cmd = [sys.executable, "-m", "pytest", "-m", marker]
    if parallel:
        cmd += ["-n", jobs]
    else:
        cmd += ["-p", "no:xdist"]
    cmd += extra

    env = dict(os.environ)
    omp_note = ""
    if parallel and omp:
        # OpenMP is left at its default (all cores) by design: the CPU subset
        # is a few OpenMP-heavy reference renders plus many fast tests. Pinning
        # OMP_NUM_THREADS=1 starves those renders of threads and the slowest
        # single-threaded test dominates the tail (measured: >600s). Only pin
        # if the caller asks (e.g. --omp 2) after measuring their own hardware.
        env["OMP_NUM_THREADS"] = omp
        omp_note = f"  (OMP_NUM_THREADS={omp})"

    print(f"\n{'=' * 70}\n[{label}] {' '.join(cmd)}{omp_note}\n{'=' * 70}",
          flush=True)
    start = time.perf_counter()
    rc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env).returncode
    elapsed = time.perf_counter() - start
    print(f"[{label}] exit={rc}  wall={elapsed:.1f}s", flush=True)
    return rc, elapsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpu-only", action="store_true", help="run only the parallel CPU pass")
    ap.add_argument("--gpu-only", action="store_true", help="run only the serial GPU pass")
    ap.add_argument("--jobs", default="auto", help="xdist worker count for the CPU pass (default: auto)")
    ap.add_argument("--omp", default=os.environ.get("ASTRORAY_TEST_OMP_THREADS"),
                    help="pin OMP_NUM_THREADS for the CPU pass (default: unset = all "
                         "cores; OpenMP-heavy reference renders need their threads)")
    ap.add_argument("pytest_args", nargs="*", help="extra args forwarded to pytest (prefix with --)")
    args = ap.parse_args()

    extra = list(args.pytest_args)
    if extra and extra[0] == "--":
        extra = extra[1:]

    results: list[tuple[str, int, float]] = []
    total = 0.0

    if not args.gpu_only:
        rc, el = _run("CPU/parallel", "cpu", parallel=True,
                      jobs=args.jobs, omp=args.omp, extra=extra)
        results.append(("CPU/parallel", rc, el))
        total += el

    if not args.cpu_only:
        rc, el = _run("GPU/serial", "not cpu", parallel=False,
                      jobs=args.jobs, omp=args.omp, extra=extra)
        results.append(("GPU/serial", rc, el))
        total += el

    print(f"\n{'#' * 70}\n# SPLIT-SUITE SUMMARY\n{'#' * 70}")
    for label, rc, el in results:
        status = "PASS" if rc == 0 else ("NO-TESTS" if rc == 5 else f"FAIL(exit={rc})")
        print(f"#   {label:<14} {status:<14} {el:8.1f}s")
    print(f"#   {'TOTAL wall':<14} {'':<14} {total:8.1f}s\n{'#' * 70}")

    # rc 5 = "no tests collected"; treat as non-fatal (e.g. --gpu-only when a
    # CUDA-less build skips every GPU module). Any other non-zero is a failure.
    return 0 if all(rc in (0, 5) for _, rc, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
