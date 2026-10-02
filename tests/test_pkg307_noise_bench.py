"""pkg307 -- noise-per-time benchmark self-test: metric definitions on synthetic arrays and the spp-differencing
timer. Pure numpy, no renderer. The optional fresh-render check (sky ROI relVar vs the 2026-09-29 research) runs
only with ASTRORAY_PKG307_FRESH=1 and a Blender 5.x + astroray .pyd (ASTRORAY_PYD_DIR)."""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from benchmarks.reference_corpus import mc_tolerance as MC
from benchmarks.reference_corpus.arbitration import mitsuba_scenes as MS

FULL = [0.0, 0.0, 1.0, 1.0]


def _stack(mean, sigma, seeds=5, hw=(32, 32), rng_seed=1):
    rng = np.random.default_rng(rng_seed)
    ref = np.broadcast_to(np.asarray(mean, float), (*hw, 3)).copy()
    return ref + sigma * rng.standard_normal((seeds, *hw, 3)) * np.asarray(mean, float), ref


def test_relvar_matches_known_gaussian_noise():
    # per-channel noise of 5 % of the mean: relVar 0.0025 per channel; luminance (weights sum 1, independent
    # channels) is sum w_c^2 * 0.0025 * m_c^2 / L^2 -- for a grey pixel that is sum w^2 * 0.0025.
    st, ref = _stack([0.5, 0.5, 0.5], 0.05, seeds=64, hw=(64, 64))
    m = MC.noise_metrics(st, ref, FULL)
    assert m["relvar_rgb"] == pytest.approx([0.0025] * 3, rel=0.05)
    assert m["relvar_lum"] == pytest.approx(0.0025 * float(np.sum(MC.LUM ** 2)), rel=0.05)
    assert m["bias2"] == pytest.approx(0.0, abs=1e-6)
    assert m["relmse"] == pytest.approx(m["relvar_lum"] + m["bias2"])


def test_bias_is_separated_from_variance_and_seed_noise_is_subtracted():
    st, ref = _stack([0.4, 0.4, 0.4], 0.02, seeds=8)
    unbiased = MC.noise_metrics(st, ref, FULL)
    biased = MC.noise_metrics(st * 1.10, ref, FULL)  # +10 % offset
    assert unbiased["bias2"] < 1e-4  # seed noise of the ROI mean is subtracted, not reported as bias
    assert biased["bias2"] == pytest.approx(0.01, rel=0.05)  # (0.1 L)^2 / L^2
    assert biased["relvar_lum"] == pytest.approx(unbiased["relvar_lum"] * 1.21, rel=1e-6)  # variance scales, not bias


def test_chroma_is_zero_for_pure_gain_noise_and_positive_for_colour_noise():
    rng = np.random.default_rng(3)
    ref = np.full((24, 24, 3), 0.3)
    gain = 1.0 + 0.2 * rng.standard_normal((6, 24, 24, 1))  # same factor on r, g, b: luminance noise only
    m = MC.noise_metrics(ref * gain, ref, FULL)
    assert m["chroma"] == pytest.approx(0.0, abs=1e-9)
    assert m["relvar_lum"] > 0.01
    colour = ref * (1.0 + 0.2 * rng.standard_normal((6, 24, 24, 3)))
    assert MC.noise_metrics(colour, ref, FULL)["chroma"] > 0.01


def test_tail_share_sees_a_single_firefly():
    st, ref = _stack([0.5, 0.5, 0.5], 0.01, seeds=5, hw=(40, 50))  # 2000 px, top 0.1 % = 2 px
    st[0, 7, 9] += 500.0
    st[3, 7, 9] += 300.0
    m = MC.noise_metrics(st, ref, FULL)
    assert m["tail_share"] > 0.99
    assert MC.noise_metrics(_stack([0.5] * 3, 0.01, hw=(40, 50))[0], ref, FULL)["tail_share"] < 0.05


def test_image_floor_masks_dark_pixels_and_roi_rect_crops():
    ref = np.zeros((20, 20, 3))
    ref[:, 10:] = 0.5
    st = np.broadcast_to(ref, (4, 20, 20, 3)).copy()
    st[:, :, :10] += np.random.default_rng(0).standard_normal((4, 20, 10, 3))  # noise only in the dark half
    assert MC.noise_metrics(st, ref, FULL, floor=0.01)["relvar_lum"] == pytest.approx(0.0, abs=1e-12)
    assert MC.noise_metrics(st, ref, [0.5, 0.0, 1.0, 1.0])["n_px"] == 200


def test_efficiency_is_inverse_relmse_time_product():
    assert MC.efficiency(0.004, 2.5) == pytest.approx(100.0)
    assert math.isnan(MC.efficiency(0.0, 1.0))


def test_per_sample_time_removes_fixed_cost():
    fixed, per = 2.0, 0.0207  # Blender start-up + scene sync + kernel load, then a linear regime
    t = MC.per_sample_time(fixed + per * 64, fixed + per * 320, 64, 320)
    assert t == pytest.approx(per)


def test_paired_timing_survives_a_clock_drift_that_biases_independent_minima():
    # rep 1 ran in a slow clock state (x1.3); rep 2's SMALL render caught a boost spike (x0.6); reps 3-5 are clean.
    fixed, per = 2.0, 0.02
    small, large = fixed + per * 64, fixed + per * 320
    raw = [[1, 64, small * 1.3], [1, 320, large * 1.3], [2, 64, small * 0.6], [2, 320, large],
           [3, 64, small], [3, 320, large], [4, 64, small], [4, 320, large], [5, 64, small], [5, 320, large]]
    independent = MC.per_sample_time(min(t for _, n, t in raw if n == 64), min(t for _, n, t in raw if n == 320), 64, 320)
    assert independent / per - 1 > 0.2  # independent minima: the spiked small render inflates the slope by > 20 %
    assert MC.paired_per_sample_time(raw, 64, 320) == pytest.approx(per)  # median of paired slopes is not fooled


def test_black_or_empty_reference_roi_fails_closed():
    ref = np.zeros((16, 16, 3))
    st = np.random.default_rng(0).random((4, 16, 16, 3))
    m = MC.noise_metrics(st, ref, FULL)
    assert math.isnan(m["relvar_lum"]) and math.isnan(m["relmse"]) and math.isnan(m["tail_share"])
    assert math.isnan(MC.noise_metrics(st, ref + 0.5, FULL, floor=1.0)["relmse"])  # floor removes every pixel


def test_equal_time_spp_rounds_down_to_a_power_of_two():
    assert MC.floor_pow2(100.0) == 64 and MC.floor_pow2(64.0) == 64 and MC.floor_pow2(0.9) is None
    assert MC.equal_time_spp(10.0, 0.0207) == 256  # 483 -> 256
    assert MC.equal_time_spp(2.0, 4.3) is None  # below one sample
    assert MC.equal_time_spp(1e6, 0.001) == MC.NB_SPP_MAX
    plan = MC.nb_spp_plan(0.0207, [2.0, 10.0, 60.0], [16, 64, 256])
    assert plan[64] == ["spp64", "2s"] and plan[256] == ["spp256", "10s"] and plan[2048] == ["60s"]


def test_nvar_slope_separates_white_noise_from_stratified():
    n = np.array([16, 64, 256])
    assert MC.nvar_slope(n, 0.3 / n) == pytest.approx(0.0, abs=1e-9)  # variance ~ 1/N
    assert MC.nvar_slope(n, 0.3 / n ** 1.5) == pytest.approx(-0.5, abs=1e-9)  # QMC-like
    assert math.isnan(MC.nvar_slope([64], [0.1]))


@pytest.mark.skipif(os.environ.get("ASTRORAY_PKG307_FRESH") != "1", reason="fresh-render check is opt-in (Blender + .pyd)")
def test_sky_roi_relvar_reproduces_the_research_from_fresh_renders(tmp_path):
    """v2_sky_sun sky_upper, Astroray CPU, 64 spp, seeds 278-282: R/B relVar 0.0024 / 0.0026 within 30 %
    (.astroray_plan/docs/research-noise-2026-09-29.md, headline 3: measured R 0.0024, B 0.0026)."""
    import json
    manifest = json.loads(MC.MANIFEST.read_text(encoding="utf-8"))
    entry = MC.scene_entry(manifest, "v2_sky_sun")
    st = np.stack([MC.render("v2_sky_sun", "cpu", s, 64, tmp_path / f"sky_s{s}") for s in range(278, 283)])
    m = MC.noise_metrics(st, MC.read_exr(MC.exr_path("v2_sky_sun")), entry["crops"]["sky_upper"])
    assert m["relvar_rgb"][0] == pytest.approx(0.0024, rel=0.30)
    assert m["relvar_rgb"][2] == pytest.approx(0.0026, rel=0.30)


# --- Phase 2: arbitration scenes (pure geometry/parameter checks; Mitsuba-gated smoke) -----------------------------------

def test_arbitration_prism_is_a_closed_outward_oriented_equilateral_prism():
    p = MS.PARAMS["arb_prism_sun"]["prism"]
    tris = MS.prism_triangles(p)
    assert len(tris) == 8
    vol = 0.0
    cen = np.mean([v for t in tris for v in t], axis=0)
    for a, b, c in tris:
        a, b, c = map(np.asarray, (a, b, c))
        n = np.cross(b - a, c - a)
        assert n @ ((a + b + c) / 3 - cen) > 0  # outward winding
        vol += a @ np.cross(b, c) / 6.0  # divergence theorem: signed volume of the closed mesh
    assert vol == pytest.approx(math.sqrt(3) / 4 * p["side"] ** 2 * p["length"], rel=1e-9)


def test_arbitration_sun_direction_is_a_unit_vector_travelling_down():
    d = MS.sun_direction(MS.PARAMS["arb_prism_sun"]["sun"])
    assert np.linalg.norm(d) == pytest.approx(1.0) and d[2] < 0


def test_arbitration_anchor_rois_exist_and_the_builder_matches_the_params():
    from benchmarks.reference_corpus.arbitration import build_arbitration as BA
    assert set(BA.ROIS) == set(MS.PARAMS)
    for sid, p in MS.PARAMS.items():
        assert p["anchor"]["roi"] in {name for name, _, _ in BA.ROIS[sid]}
        assert p["anchor"]["leg"] in MC.NB_LEGS


MITSUBA_PY = MC.MITSUBA_PY


@pytest.mark.skipif(not MITSUBA_PY.is_file(), reason="Mitsuba venv not installed")
@pytest.mark.parametrize("sid", MS.SCENES)
def test_mitsuba_scenes_load_and_render_on_the_cpu(sid, tmp_path):
    out = subprocess.run([str(MITSUBA_PY), str(Path(MS.__file__)), "--scene", sid, "--spp", "2", "--out", str(tmp_path / sid),
                          "--res-percent", "10", "--variant", "scalar_spectral"], capture_output=True, text=True,
                         timeout=300, check=False)
    assert "PKG119B_LEG PASS" in out.stdout, out.stdout[-800:] + out.stderr[-800:]
    assert (tmp_path / f"{sid}.f32").stat().st_size == 4 * 3 * 32 * 18
