#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg201 Stage 3 (Finding A) — GPU wavefront per-type bounce-limit honour.

The GPU shade kernel (shadePathSlot) mirrors the CPU pathTraceSpectral per-type
check via a __constant__ c_wfBounceLimit + the packed per_type_bounce SoA
counter. These tests confirm the GPU honours the limits (monotone energy vs
per-type depth) and that the all-unlimited default is inert (fleet path).

Requires CUDA hardware. Runs the closed diffuse Cornell box on the GPU wavefront.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from base_helpers import create_cornell_box, setup_camera  # noqa: E402

import astroray  # noqa: E402

pytestmark = pytest.mark.skipif(
    not bool(astroray.__features__.get("cuda", False)),
    reason="pkg201 GPU per-type bounce honour needs a CUDA build",
)

SPP = 24
MAX_DEPTH = 12
SEED = 7
W, H = 160, 120


def _render_gpu(diffuse=-1, glossy=-1, transmission=-1):
    r = astroray.Renderer()
    create_cornell_box(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=W, height=H)
    r.set_integrator("path_tracer")
    r.set_seed(SEED)
    r.set_use_gpu(True)
    px = r.render(SPP, MAX_DEPTH, None, False, diffuse, glossy, transmission)
    return np.asarray(px, dtype=np.float32)


def _mean_lum(img):
    return float(np.mean(img @ np.array([0.2126, 0.7152, 0.0722], np.float32)))


def test_gpu_diffuse_bounces_monotone_energy():
    """GPU: diffuse_bounces 0 (direct only) < 8 (deep interreflection)."""
    a = _mean_lum(_render_gpu(diffuse=0))
    b = _mean_lum(_render_gpu(diffuse=8))
    assert b > a * 1.01, f"GPU diffuse_bounces not honoured: 0->{a:.5g} 8->{b:.5g}"


def test_gpu_diffuse_cap_below_unlimited():
    """GPU: capping diffuse bounces at 0 loses energy vs unlimited."""
    capped = _mean_lum(_render_gpu(diffuse=0))
    full = _mean_lum(_render_gpu(diffuse=-1))
    assert capped < full * 0.99, f"GPU cap inert: 0->{capped:.5g} inf->{full:.5g}"


def _render_gpu_plain():
    r = astroray.Renderer()
    create_cornell_box(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=W, height=H)
    r.set_integrator("path_tracer")
    r.set_seed(SEED)
    r.set_use_gpu(True)
    return np.asarray(r.render(SPP, MAX_DEPTH, None, False), dtype=np.float32)


def test_gpu_default_unlimited_is_inert():
    """GPU: passing -1 (unlimited) per-type args must be inert — the fleet
    <...> shade kernel path (the per-type block's `if(limit>=0)` branch is not
    taken). The GPU wavefront is NOT bit-exact run-to-run (unordered atomic
    radiance accumulation), so 'inert' means: the -1-args-vs-plain difference is
    no larger than the intrinsic plain-vs-plain run-to-run noise. (The compiled
    machine-code byte-identity is covered separately by the cuobjdump register
    probe.)"""
    plain_a = _render_gpu_plain()
    plain_b = _render_gpu_plain()
    with_args = _render_gpu(diffuse=-1, glossy=-1, transmission=-1)

    noise_floor = float(np.max(np.abs(plain_a - plain_b)))
    feature_diff = float(np.max(np.abs(plain_a - with_args)))
    # Allow a tiny multiple of the noise floor (+ an absolute ULP epsilon for the
    # degenerate case where the two plain renders happen to match exactly).
    assert feature_diff <= max(noise_floor * 2.0, 1e-5), (
        f"unlimited per-type args exceeded GPU noise floor: "
        f"feature_diff={feature_diff:.3g} noise_floor={noise_floor:.3g}")
