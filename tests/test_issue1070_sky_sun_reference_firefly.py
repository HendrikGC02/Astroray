"""#1070 -- v2_sky_sun chrome_reflection ROI read r 0.81 / g 0.91 of Cycles.

Root cause (lane g2, 2026-10-06): not an Astroray transport gap. The committed 1024 spp Cycles
reference holds one caustic firefly inside the ROI (row 136, col 127: rgb 1.62/0.76/0.22 against
~0.08 neighbours, a sun -> chrome -> pillar path); it adds +6 % r / +3 % g to the 169-pixel ROI
mean and +19 % r to its pillar half. A fresh Cycles render (512 spp, seed 278) of the same pixels
agrees with Astroray to 0.99; the pillar face agrees per pixel. The ROI is trimmed by that row.

Gate: no pixel of a gated v2_sky_sun ROI may be an isolated reference outlier (> 8x the median of
its 8 neighbours and > 0.5), otherwise the ROI mean measures one reference sample, not transport.
"""
from pathlib import Path

import numpy as np
import pytest
import tomllib

from benchmarks.reference_corpus import mc_tolerance as MC

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "reference_corpus"
SCENE = "v2_sky_sun"
# ROIs checked: the pillar/chrome ROI of #1070 (the ground ROI spans caustic speckle by design).
ROIS = ("chrome_reflection",)


def _outliers(ref, rect):
    h, w = ref.shape[:2]
    x0, y0, x1, y1 = rect
    ys, ye, xs, xe = round(y0 * h), round(y1 * h), round(x0 * w), round(x1 * w)
    lum = ref @ MC.LUM
    bad = []
    for y in range(ys, ye):
        for x in range(xs, xe):
            win = lum[max(y - 1, 0):y + 2, max(x - 1, 0):x + 2].copy()
            win[y - max(y - 1, 0), x - max(x - 1, 0)] = np.nan
            med = np.nanmedian(win)
            if lum[y, x] > 0.5 and lum[y, x] > 8.0 * med:
                bad.append((y, x, float(lum[y, x]), float(med)))
    return bad


@pytest.mark.cpu
@pytest.mark.parametrize("roi_name", ROIS)
def test_reference_roi_has_no_isolated_firefly(roi_name):
    gates = tomllib.loads((CORPUS / "gates_v2.toml").read_text(encoding="utf-8"))
    scene = gates["scenes"][SCENE]
    roi = next(r for r in scene["roi"] if r["name"] == roi_name)
    ref = MC.read_exr(CORPUS.parents[1] / scene["reference"])
    assert not _outliers(ref, roi["rect"]), f"{SCENE}/{roi_name}: reference firefly inside the ROI"


@pytest.mark.cpu
def test_outlier_detector_flags_the_old_rect():
    """The detector fires on the pre-#1070 rect (last row included) and on nothing else."""
    scene = tomllib.loads((CORPUS / "gates_v2.toml").read_text(encoding="utf-8"))["scenes"][SCENE]
    ref = MC.read_exr(CORPUS.parents[1] / scene["reference"])
    bad = _outliers(ref, [0.378, 0.6891, 0.418, 0.7602])
    assert [(y, x) for y, x, _, _ in bad] == [(136, 127)]


@pytest.mark.cpu
def test_manifest_crop_matches_gate_rect():
    gates = tomllib.loads((CORPUS / "gates_v2.toml").read_text(encoding="utf-8"))
    import json
    crops = json.loads((CORPUS / "scenes" / "manifest.json").read_text(encoding="utf-8"))["scenes"][SCENE]["crops"]
    roi = next(r for r in gates["scenes"][SCENE]["roi"] if r["name"] == "chrome_reflection")
    assert crops["chrome_reflection"] == pytest.approx(roi["rect"], abs=1e-4)
