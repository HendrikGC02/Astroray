#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GPU vs CPU test classification (latency-lever item 6, open-model-research-2026-08).

Splits the test suite so the CPU-only subset can run under pytest-xdist
(``-n auto``) while every test that actually drives CUDA stays strictly serial.
The serial requirement is not cosmetic: memory ``cuda_verifier_concurrency``
documents false-positive ``illegal memory access`` crashes when two CUDA-heavy
workloads run at once on this RTX, and the autouse ``cuda_cleanup_and_error_check``
fixture in conftest assumes serialized, single-context GPU access.

Three classes:
  * ``gpu``    — drives real CUDA; must run serial in a single GPU context.
  * ``serial`` — CPU-only but NOT xdist-safe (spawns real headless Blender,
                 which fights the shared test_results/ dir under concurrent load
                 on this Windows+OneDrive box; measured rmtree file-lock flake).
  * ``cpu``    — parallel-safe; runs under pytest-xdist ``-n auto``.

The runner treats the split as parallel (``-m cpu``) vs serial (``-m "not cpu"``),
so ``gpu`` and ``serial`` both land in the serial pass.

Design contract (see conftest.pytest_collection_modifyitems):
  * The classification is deliberately CONSERVATIVE — biased toward serial.
    A false positive (a parallel-safe test run serial) only costs a little
    wall time. A false negative (a GPU or file-fragile test run in parallel)
    reintroduces exactly the concurrent-CUDA / file-lock flake this split
    exists to prevent. So when in doubt, do NOT mark ``cpu``.

This module imports nothing from pytest so the audit dump
(``python tests/_gpu_classification.py``) and scripts/test/select_impacted.py
can reuse it.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

# --- Source triggers: presence of any of these means the test launches / probes
#     real CUDA work and MUST run serial. Regexes, matched against file text. ---
_SOURCE_TRIGGERS = [
    r"\b_gpu_[a-z]\w*",              # real GPU bindings: _gpu_photon_emit_sphere, _gpu_tlas_identity_parity, ...
    r"set_use_gpu\s*\(\s*(?:True|1)\b",  # opts a renderer onto the GPU (mock false-positives accepted as safe)
    r"\bgpu\s*=\s*True\b",           # gpu=True kwarg opts an in-process render onto CUDA (e.g. runner.run(..., gpu=True) via _try_set_gpu->set_use_gpu(True)); word-boundary avoids matching `_use_gpu = True`
    r"\bfind_standalone_executable\b",  # subprocess-invokes the standalone exe, which defaults to device=auto -> CUDA on a GPU box (apps/main.cpp)
    r"\bupload_scene\s*\(",          # GPU scene-upload path (parity suites)
    r"\bCUDARenderer\b",
    r"\bcudart\w*\b",                # direct CUDA runtime (ctypes) use
    r"__features__[\s\S]{0,60}?cuda",   # build-feature gate on the cuda feature
    r"(?:skip|skipif)[\s\S]{0,100}?\bCUDA\b",  # module-level skip when CUDA absent
]

# --- Filename triggers: some GPU suites drive CUDA through helpers whose text
#     the source scan might not catch. These stems are unambiguously GPU. ---
_FILENAME_TRIGGERS = [
    "gpu", "cuda", "tlas", "wavefront", "optix", "prewarm", "sms_attempt",
]

# --- Serial (but CPU-only) triggers: not xdist-safe. Tests that shell out to a
#     real headless Blender destructively manage a shared test_results/ dir and
#     flake on Windows file locks under concurrent load. ---
_SERIAL_TRIGGERS = [
    r"\bBLENDER_EXE\b",
]

_SOURCE_RE = re.compile("|".join(_SOURCE_TRIGGERS))
_SERIAL_RE = re.compile("|".join(_SERIAL_TRIGGERS))
# Avoid matching the build directory name "build_cuda" as a cuda trigger.
_BUILD_DIR_NOISE = re.compile(r"build_cuda")


@lru_cache(maxsize=None)
def classify_source(text: str, filename: str) -> str:
    """Return 'gpu', 'serial', or 'cpu' for a test module (source + filename)."""
    stem = Path(filename).stem.lower()
    if any(tok in stem for tok in _FILENAME_TRIGGERS):
        return "gpu"
    # Strip the build-dir path noise so `sys.path.insert(0, 'build_cuda/...')`
    # does not read as a CUDA trigger.
    scrubbed = _BUILD_DIR_NOISE.sub("", text)
    if _SOURCE_RE.search(scrubbed):
        return "gpu"
    if _SERIAL_RE.search(scrubbed):
        return "serial"
    return "cpu"


def classify_path(path: str | Path) -> str:
    """Classify a test file on disk. Missing/unreadable files default to 'gpu'
    (the safe, serial side)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "gpu"
    return classify_source(text, p.name)


def classify_tree(tests_dir: str | Path) -> dict[str, str]:
    """Classify every test_*.py under tests_dir. Returns {relpath: 'gpu'|'cpu'}."""
    root = Path(tests_dir)
    out: dict[str, str] = {}
    for f in sorted(root.rglob("test_*.py")):
        out[str(f.relative_to(root)).replace("\\", "/")] = classify_path(f)
    return out


def _main() -> int:
    tests_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    result = classify_tree(tests_dir)
    gpu = [k for k, v in result.items() if v == "gpu"]
    serial = [k for k, v in result.items() if v == "serial"]
    cpu = [k for k, v in result.items() if v == "cpu"]
    print(f"# CPU/GPU test classification for {tests_dir}")
    print(f"# total={len(result)}  gpu={len(gpu)} + serial={len(serial)} (serial pass)"
          f"  cpu={len(cpu)} (parallel pass)\n")
    print("## GPU (serial):")
    for k in gpu:
        print(f"  gpu     {k}")
    print("\n## SERIAL — CPU-only but not xdist-safe:")
    for k in serial:
        print(f"  serial  {k}")
    print("\n## CPU (parallel):")
    for k in cpu:
        print(f"  cpu     {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
