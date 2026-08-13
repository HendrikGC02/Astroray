# -*- coding: utf-8 -*-
"""pkg200 — unit tests for the honour-matrix contract layer.

Import-safe: no bpy, no GPU, no cv2. Proves the Stage-0 completeness gate and
the per-row predicate logic on synthetic LegStats so the GPU render sweep only
has to supply real numbers, not re-litigate the pass/fail thresholds.
"""
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

import pkg200_honour_matrix as M  # noqa: E402


def _stats(mean=(0.2, 0.2, 0.2), maxv=(0.5, 0.5, 0.5), var=(0.01, 0.01, 0.01),
           alpha=1.0, grad=0.02, hi=0.4, shape=(96, 96)):
    lum = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
    lmax = 0.2126 * maxv[0] + 0.7152 * maxv[1] + 0.0722 * maxv[2]
    lvar = 0.2126 * var[0] + 0.7152 * var[1] + 0.0722 * var[2]
    return M.LegStats(mean, maxv, var, lum, lmax, lvar, alpha, grad, hi, shape)


# --------------------------------------------------------------------------- #
# Stage-0 acceptance: the matrix is generated from the pkg176 contract.
# --------------------------------------------------------------------------- #
def test_completeness_gate_passes():
    M.check_completeness()  # raises on drift


def test_every_plumbed_prop_has_a_row():
    surface = set(M.enumerate_direct_surface())
    assert len(surface) >= 20, surface
    # use_light_tree is a KNOWN GAP, never part of the plumbed surface.
    assert "use_light_tree" not in surface
    assert "use_light_tree" in M.KNOWN_GAPS


def test_drift_detected_when_a_row_is_removed(monkeypatch):
    trimmed = [r for r in M.MATRIX if r.name != "film_exposure"]
    monkeypatch.setattr(M, "MATRIX", trimmed)
    with pytest.raises(AssertionError, match="DRIFT"):
        M.check_completeness()


def test_dropped_rows_are_not_in_surface():
    surface = set(M.enumerate_direct_surface())
    for dropped in ("use_adaptive_sampling", "use_fast_gi", "sample_offset"):
        assert dropped not in surface


# --------------------------------------------------------------------------- #
# Predicate logic on synthetic stats.
# --------------------------------------------------------------------------- #
def test_monotone_energy():
    a = _stats(mean=(0.10, 0.10, 0.10))
    b = _stats(mean=(0.20, 0.20, 0.20))
    assert M.p_monotone_energy(a, b, None)[0] == M.PASS
    assert M.p_monotone_energy(b, a, None)[0] == M.HONEST_FAIL  # non-responsive
    assert M.p_monotone_energy(a, a, None)[0] == M.HONEST_FAIL


def test_exposure_scale():
    a = _stats(mean=(0.20, 0.10, 0.05))
    b = _stats(mean=(0.40, 0.20, 0.10))
    assert M.p_exposure_scale(a, b, None)[0] == M.PASS
    b_bad = _stats(mean=(0.24, 0.12, 0.06))  # only 1.2x
    assert M.p_exposure_scale(a, b_bad, None)[0] == M.HONEST_FAIL


def test_clamp():
    a = _stats(maxv=(4.0, 4.0, 4.0), hi=3.0)
    b = _stats(maxv=(1.0, 1.0, 1.0), hi=0.9)
    assert M.p_clamp(a, b, None)[0] == M.PASS
    assert M.p_clamp(a, a, None)[0] == M.HONEST_FAIL


def test_variance_falls():
    a = _stats(mean=(0.2, 0.2, 0.2), var=(0.04, 0.04, 0.04))
    b = _stats(mean=(0.2, 0.2, 0.2), var=(0.01, 0.01, 0.01))
    assert M.p_variance_falls(a, b, None)[0] == M.PASS
    b_drift = _stats(mean=(0.4, 0.4, 0.4), var=(0.01, 0.01, 0.01))
    assert M.p_variance_falls(a, b_drift, None)[0] == M.HONEST_FAIL


def test_seed_distinct_and_repeat():
    a = _stats(mean=(0.2, 0.2, 0.2))
    b = _stats(mean=(0.2, 0.2, 0.2))
    c_diff = M.Cross(lum_abs_diff_mean=0.01, lum_abs_diff_max=0.2, identical=False)
    c_same = M.Cross(lum_abs_diff_mean=0.0, lum_abs_diff_max=1e-6, identical=True)
    assert M.p_seed_distinct(a, b, c_diff)[0] == M.PASS
    assert M.p_seed_distinct(a, b, c_same)[0] == M.HONEST_FAIL
    assert M.p_seed_repeat(a, b, c_same)[0] == M.PASS
    assert M.p_seed_repeat(a, b, c_diff)[0] == M.HONEST_FAIL


def test_alpha_transparent():
    a = _stats(alpha=0.05)   # film_transparent ON
    b = _stats(alpha=1.0)    # opaque
    assert M.p_alpha_transparent(a, b, None)[0] == M.PASS
    assert M.p_alpha_transparent(b, b, None)[0] == M.HONEST_FAIL


def test_grad_sharper():
    a = _stats(grad=0.05)  # BOX / narrow
    b = _stats(grad=0.02)  # wide gaussian
    assert M.p_grad_sharper(a, b, None)[0] == M.PASS
    assert M.p_grad_sharper(b, a, None)[0] == M.HONEST_FAIL


def test_resolution():
    a = _stats(shape=(64, 64))
    b = _stats(shape=(96, 96))
    assert M.p_resolution(a, b, None)[0] == M.PASS
    assert M.p_resolution(a, a, None)[0] == M.HONEST_FAIL


def test_limitation_rows():
    a = b = _stats()
    for name in ("preview_samples", "use_preview_denoising"):
        row = M.get_row(name)
        assert row.kind == "limitation"
        assert row.predicate(a, b, None)[0] == M.LIMITATION


def test_denoise_variance():
    noisy = _stats(var=(0.05, 0.05, 0.05))
    clean = _stats(var=(0.01, 0.01, 0.01))
    assert M.p_denoise_variance(noisy, clean, None)[0] == M.PASS


# --------------------------------------------------------------------------- #
# Degradation-honesty leg (spec): a sample of DROPPED controls set off-default
# must produce the consolidated WARNING naming them — zero silently-ignored
# controls on adopted panels (pkg176 acceptance). bpy-free: fake datablocks.
# --------------------------------------------------------------------------- #
import types  # noqa: E402

sys.path.insert(0, str(_REPO / "blender_addon"))
import native_settings as NS  # noqa: E402


def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _scene(cam_data=None, lights=()):
    cam = _ns(data=cam_data) if cam_data is not None else None
    objs = [_ns(type="LIGHT", data=ld, name=n) for n, ld in lights]
    return _ns(camera=cam, objects=objs)


def test_degradation_honesty_camera_and_light():
    # ORTHO projection + non-default clip + polygonal bokeh + anamorphic + a
    # per-light specular_factor: all DROPPED, all must be named.
    dof = _ns(use_dof=True, aperture_blades=6, aperture_rotation=0.0, aperture_ratio=1.5)
    cam_data = _ns(type="ORTHO", clip_start=0.5, clip_end=500.0, dof=dof)
    scene = _scene(cam_data=cam_data, lights=[("Key", _ns(specular_factor=0.3))])
    msgs = NS.report_unsupported_native_controls(scene, report=None, emit=False)
    joined = " ".join(msgs).lower()
    assert "ortho" in joined
    assert "clip" in joined
    assert "bokeh" in joined or "aperture" in joined
    assert "specular" in joined
    assert "Key" in " ".join(msgs)


def test_degradation_honesty_quiet_on_defaults():
    # Untouched (default) controls must NOT warn — only actual steering warns.
    dof = _ns(use_dof=False, aperture_blades=0, aperture_rotation=0.0, aperture_ratio=1.0)
    cam_data = _ns(type="PERSP", clip_start=0.1, clip_end=1000.0, dof=dof)
    scene = _scene(cam_data=cam_data, lights=[("Key", _ns(specular_factor=1.0))])
    msgs = NS.report_unsupported_native_controls(scene, report=None, emit=False)
    assert msgs == []


def test_degradation_honesty_emit_calls_report():
    captured = []
    dof = _ns(use_dof=False, aperture_blades=0, aperture_rotation=0.0, aperture_ratio=1.0)
    cam_data = _ns(type="PANO", clip_start=0.1, clip_end=1000.0, dof=dof)
    scene = _scene(cam_data=cam_data, lights=())
    NS.report_unsupported_native_controls(
        scene, report=lambda level, msg: captured.append((level, msg)), emit=True)
    assert captured and "PANO" in captured[0][1]
