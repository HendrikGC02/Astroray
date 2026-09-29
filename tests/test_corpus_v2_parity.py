"""pkg284 Phase 2 -- Cycles-parity corpus v2 gate.

One case per (scene, backend, ROI, channel). One Blender render per (scene, backend), cached
per module; every case is a single assertion, so a ``provisional`` row is a strict xfail on
that case alone (never ``pytest.xfail()``) and never hides a sibling check.

Backends
  cpu      Astroray CPU seed 278 @ spp_gate vs the committed 1024 spp Cycles CPU reference (EXR).
  gpu      Astroray GPU, same comparison (skipped until ``gpu_tol`` is banded in gates_v2.toml).
  gpu_cpu  GPU vs CPU renders of this session, +-5 % floor (pkg271 convention).
Channels: r, g, b, L (Rec.709 luminance of the ROI mean); dark channels (Cycles mean < 0.01)
are not generated. Bands: gates_v2.toml (mc_tolerance.py, never hand-typed). Rows the owner
declared documented divergences (``expected_divergence``: Astroray physically right, Cycles
differs) pin Astroray against its own 5-seed mean instead of Cycles. Provisional rows:
provisional_v2.toml (each tied to an issue; flip in the fixing PR, strict xfail).

Needs headless Blender 5.2 and an OpenMP-OFF staged addon (``ASTRORAY_PYD_DIR``, e.g.
``dist/astroray``); skipped otherwise. Re-bless rule: benchmarks/reference_corpus/README.md.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import tomllib

from benchmarks.reference_corpus import mc_tolerance as MC
from results_layout import results_dir

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "reference_corpus"
GATES = tomllib.loads((CORPUS / "gates_v2.toml").read_text(encoding="utf-8"))
PROVISIONAL = tomllib.loads((CORPUS / "provisional_v2.toml").read_text(encoding="utf-8")).get("row", [])
CHANNELS = MC.CH
GATED = {sid: s for sid, s in GATES.get("scenes", {}).items() if s["render_gate"]}

WORK = Path(os.environ.get("PKG284_WORK", str(results_dir("parity", "corpus-v2-work", create=False))))
_LEG = {"cpu": "cpu", "gpu": "gpu"}
_cache: dict = {}


def _prov(scene, backend, roi, ch):
    for row in PROVISIONAL:
        if (row["scene"], row["backend"], row["roi"]) == (scene, backend, roi) and ch in row["channels"]:
            return row
    return None


def _cases():
    out = []
    for sid, scene in sorted(GATED.items()):
        for roi in scene["roi"]:
            for backend, tol_key in (("cpu", "cpu_tol"), ("gpu", "gpu_tol"), ("gpu_cpu", "gpu_cpu_tol")):
                tol = roi.get(tol_key)
                for c, ch in enumerate(CHANNELS):
                    if roi["excluded"][c]:
                        continue
                    marks = [pytest.mark.gpu] if backend != "cpu" else [pytest.mark.serial]
                    if tol is None:  # leg not banded yet (GPU not measured): visible skip
                        marks.append(pytest.mark.skip(reason=f"{backend} band not measured yet ({tol_key} absent)"))
                    row = _prov(sid, backend, roi["name"], ch)
                    if row:
                        marks.append(pytest.mark.xfail(strict=True, reason=f"{row['issue']}: {row['reason']}"))
                    out.append(pytest.param(sid, backend, roi, c, marks=marks,
                                            id=f"{sid}-{backend}-{roi['name']}-{ch}"))
    return out


def _render(sid, leg):
    key = (sid, leg)
    if key not in _cache:
        if not MC.BLENDER.is_file() or not os.environ.get("ASTRORAY_PYD_DIR"):
            pytest.skip("needs Blender 5.2 (ASTRORAY_BLENDER) and an OpenMP-OFF staged addon (ASTRORAY_PYD_DIR)")
        s = GATED[sid]
        stem = WORK / f"{sid}_{leg}"
        _cache[key] = MC.render(sid, leg, s["seed"], s["spp_gate"], stem)
    return _cache[key]


def _means(sid, leg, roi):
    return MC.roi_means(_render(sid, leg), roi["rect"])


def _ref_means(sid, roi):
    return MC.roi_means(MC.read_exr(CORPUS.parents[1] / GATED[sid]["reference"]), roi["rect"])


@pytest.mark.parametrize("sid,backend,roi,c", _cases())
def test_corpus_v2_parity(sid, backend, roi, c):
    ch = CHANNELS[c]
    if backend == "gpu_cpu":
        num, den, tol = _means(sid, "gpu", roi)[c], _means(sid, "cpu", roi)[c], roi["gpu_cpu_tol"][c]
        what = "GPU/CPU"
    else:
        leg = _LEG[backend]
        num = _means(sid, leg, roi)[c]
        if "expected_divergence" in roi:  # Astroray pinned against itself, not Cycles
            den, tol = roi[f"{leg}_mean"][c], roi[f"{leg}_pin_tol"][c]
            what = f"Astroray {backend.upper()}/pin ({roi['expected_divergence'][:60]})"
        else:
            den, tol = roi["cycles_mean"][c], roi[f"{leg}_tol"][c]
            what = f"Astroray {backend.upper()}/Cycles"
    ratio = num / den
    assert abs(ratio - 1.0) <= tol, (
        f"{sid} {roi['name']} {ch}: {what} ratio {ratio:.4f} outside 1 +- {tol:.4f} (num {num:.5g}, den {den:.5g})")


def test_gates_are_measured_and_complete():
    assert GATES["meta"]["seed"] == 278 and GATES["meta"]["adaptive_sampling"] is False
    assert len(GATES["meta"]["mc_seeds"]) >= 5, "spec pkg284: bands from >= 5 seeds"
    for sid, scene in GATED.items():
        assert (CORPUS.parents[1] / scene["reference"]).is_file(), f"{sid}: reference EXR missing"
        for roi in scene["roi"]:
            assert "cpu_tol" in roi and "cycles_sigma" in roi, f"{sid}/{roi['name']}: unbanded"
            for c in range(4):
                if not roi["excluded"][c]:
                    assert roi["cpu_tol"][c] >= MC.BAND_FLOOR - 1e-9


def test_provisional_rows_reference_real_cases_and_issues():
    ids = {p.id for p in _cases()}
    for row in PROVISIONAL:
        assert re.fullmatch(r"#\d+", row["issue"]), f"provisional row without an issue id: {row}"
        for ch in row["channels"]:
            key = f"{row['scene']}-{row['backend']}-{row['roi']}-{ch}"
            assert key in ids, f"provisional row matches no case: {key}"
