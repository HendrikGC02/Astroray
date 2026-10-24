"""pkg306 -- heavy-tail gates for v2_media and v2_dispersion_caustics, plus a fast self-test of
``mc_tolerance.tail_stats`` (the ``--tail-report`` metrics) on synthetic arrays.

Render gates: 5 seeds (278-282) x spp_gate of each scene on the Cycles CPU and Astroray legs, cached as
``<scene>_<leg>_s<seed>.npy`` in ``PKG306_WORK`` (default test_results/_runs/parity/firefly-tail-work; an
``mc_tolerance.py --legs cycles cpu`` work dir can be pointed at directly). Metrics: luminance, across-seed
variance, pixels with 1024 spp Cycles reference luminance > 0.01 (``tail_stats``). The failing gates are strict
xfails carrying the 2026-10-25 CPU measurement and owner (``.astroray_plan/docs/pkg306-tail-attribution.md``);
Phase 1 flips them. Needs headless Blender 5.2 and an Astroray addon build (``ASTRORAY_PYD_DIR``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from benchmarks.reference_corpus import mc_tolerance as MC
from results_layout import results_dir

SEEDS = (278, 279, 280, 281, 282)
WORK = Path(os.environ.get("PKG306_WORK", str(results_dir("parity", "firefly-tail-work", create=False))))
_cache: dict = {}


# --------------------------------------------------------------------------------------------------
# tail_stats self-test (pure numpy)
# --------------------------------------------------------------------------------------------------

def _noise(seeds=5, hw=(40, 50), level=0.5, sigma=0.01, rng_seed=1):
    rng = np.random.default_rng(rng_seed)
    return level + sigma * rng.standard_normal((seeds, *hw, 1)) * np.ones(3)


def test_tail_stats_attributes_a_single_firefly():
    a, c = _noise(rng_seed=1), _noise(rng_seed=2)  # 2000 px: the top 0.1 % is 2 pixels
    a[4, 7, 9] += 500.0  # one seed, one pixel: a 1-in-N firefly
    crops = {"left": [0.0, 0.0, 0.5, 1.0], "right": [0.5, 0.0, 1.0, 1.0]}
    st = MC.tail_stats(a, c, crops)
    assert st["k_tail"] == 2
    assert st["share"] > 0.99 and st["share_ref_same"] < 0.01
    assert st["tail_rois"].get("left", 0) >= 1
    w = st["worst"][0]
    assert (w["x"], w["y"], w["roi"]) == (9, 7, "left")
    assert w["max_frac"] > 0.99  # 1-in-N firefly, not a stable bright pixel
    assert st["full"] > 100.0 and 0.5 < st["trimmed"] < 2.0 and 0.5 < st["bulk"] < 2.0


def test_tail_stats_stable_bright_pixel_is_not_a_firefly():
    a, c = _noise(rng_seed=3), _noise(rng_seed=4)
    a[:, 3, 3] = np.array([40.0, 60.0, 50.0, 45.0, 55.0])[:, None]  # bright in every seed
    w = MC.tail_stats(a, c, {"all": [0.0, 0.0, 1.0, 1.0]})["worst"][0]
    assert (w["x"], w["y"]) == (3, 3) and w["max_frac"] < 0.3


def test_tail_stats_reference_floor_and_roi_z():
    a, c = _noise(rng_seed=5), _noise(rng_seed=6)
    ref = np.full(a.shape[1:], 0.5)
    ref[:, :25] = 0.0  # left half below the floor: excluded
    a[2, 5, 5] += 1000.0  # firefly in the excluded half: no effect
    st = MC.tail_stats(a, c, {"right": [0.5, 0.0, 1.0, 1.0]}, ref=ref, baseline=a * 1.10)
    assert st["n_px"] == 1000 and st["full"] < 2.0
    r = st["rois"]["right"]
    assert abs(r["z"]) < 4.0 and r["z_vs_baseline"] < -20.0  # a 10 % mean shift is detected


def test_tail_report_cli_reads_seed_renders(tmp_path, monkeypatch, capsys):
    """--tail-report over a work dir of per-seed .npy renders (synthetic stand-ins, no Blender)."""
    sid = "v2_dispersion_caustics"
    shape = (180, 320, 3)
    rng = np.random.default_rng(7)
    for s in SEEDS:
        np.save(tmp_path / f"{sid}_cycles_s{s}.npy", (0.2 + 0.01 * rng.standard_normal(shape)).astype(np.float32))
        img = (0.2 + 0.01 * rng.standard_normal(shape)).astype(np.float32)
        if s == 282:
            img[98, 177] = 1000.0
        np.save(tmp_path / f"{sid}_cpu_s{s}.npy", img)
    monkeypatch.setattr(MC, "exr_path", lambda _sid: tmp_path / "no_reference.exr")
    monkeypatch.setattr("sys.argv", ["mc_tolerance.py", "--tail-report", "--scenes", sid, "--legs", "cycles", "cpu",
                                     "--work-dir", str(tmp_path)])
    MC.main()
    out = json.loads((tmp_path / "tail_report.json").read_text())["scenes"][sid]["cpu"]
    assert out["worst"][0]["x"] == 177 and out["worst"][0]["y"] == 98 and out["share"] > 0.9
    assert "top-0.1% share" in capsys.readouterr().out


# --------------------------------------------------------------------------------------------------
# render gates
# --------------------------------------------------------------------------------------------------

def _stack(sid: str, leg: str) -> np.ndarray:
    key = (sid, leg)
    if key not in _cache:
        if not MC.BLENDER.is_file() or not os.environ.get("ASTRORAY_PYD_DIR"):
            pytest.skip("needs Blender 5.2 (ASTRORAY_BLENDER) and an Astroray addon build (ASTRORAY_PYD_DIR)")
        spp = json.loads(MC.MANIFEST.read_text(encoding="utf-8"))["scenes"][sid]["v2"]["spp_gate"]
        imgs = []
        for s in SEEDS:
            stem = WORK / f"{sid}_{leg}_s{s}"
            imgs.append(np.load(stem.with_suffix(".npy")) if stem.with_suffix(".npy").is_file()
                        else MC.render(sid, leg, s, spp, stem))
        _cache[key] = np.stack(imgs)
    return _cache[key]


def _stats(sid: str, leg: str) -> dict:
    key = ("stats", sid, leg)
    if key not in _cache:
        crops = MC.scene_entry(json.loads(MC.MANIFEST.read_text(encoding="utf-8")), sid)["crops"]
        _cache[key] = MC.tail_stats(_stack(sid, leg), _stack(sid, "cycles"), crops, ref=MC.read_exr(MC.exr_path(sid)))
    return _cache[key]


_LEGS = [pytest.param("cpu", marks=pytest.mark.serial, id="cpu"),
         pytest.param("gpu", marks=[pytest.mark.gpu,
                                    pytest.mark.xfail(strict=False, reason="pkg306: GPU leg not measured yet (BUILD REQUEST)")],
                      id="gpu")]


@pytest.mark.parametrize("leg", [
    pytest.param("cpu", marks=[pytest.mark.serial, pytest.mark.xfail(
        strict=True, reason="pkg306 2026-10-25 CPU: full relVar 4.27x Cycles. Owner: medium segment direct light "
                            "distance strategy (smoke_plume 83x, shaft 14x; drop_voldirect 0.52x / 0.09x), #1032")], id="cpu"),
    _LEGS[1]])
def test_media_full_relvar_within_3x_cycles(leg):
    assert _stats("v2_media", leg)["full"] <= 3.0


@pytest.mark.parametrize("leg", _LEGS)
def test_media_tail_share_within_2x_cycles_same_pixels(leg):
    st = _stats("v2_media", leg)  # 2026-10-25 CPU: 0.500 vs Cycles 0.484 on the same pixels (#961/#1019)
    assert st["share"] <= 2.0 * st["share_ref_same"]


@pytest.mark.parametrize("leg", _LEGS)
def test_media_roi_means_within_3_sigma_of_cycles(leg):
    bad = {n: round(r["z"], 2) for n, r in _stats("v2_media", leg)["rois"].items() if abs(r["z"]) > 3.0}
    assert not bad, f"ROI means outside 3 sigma of Cycles: {bad}"  # 2026-10-25 CPU: max |z| 2.28 (fog_floor_lit)


@pytest.mark.parametrize("leg", [
    pytest.param("cpu", marks=[pytest.mark.serial, pytest.mark.xfail(
        strict=True, reason="pkg306 2026-10-25 CPU: trimmed relVar 80.5x Cycles. Owners: spot light-tree cone "
                            "theta_o = theta_e (src/lights/spot_light.cpp, 80.5x -> 25x with Cycles' cone) and the "
                            "photon-map caustic floor Cycles does not render (Mitsuba arbitration, pkg307)")], id="cpu"),
    _LEGS[1]])
def test_dispersion_trimmed_relvar_within_5x_cycles(leg):
    assert _stats("v2_dispersion_caustics", leg)["trimmed"] <= 5.0
