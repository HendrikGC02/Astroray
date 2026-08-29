#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg201 Stage 3 (Finding A) — CPU per-type bounce-limit honour.

The CPU pathTraceSpectral is the parity oracle the GPU wavefront mirrors. Prior
to pkg201 Stage 3 the per-type bounce args were accepted by render() and then
(void)-discarded, so NEITHER backend honoured them. These tests pin the CPU
behaviour: raising a per-type bounce limit must monotonically raise that lobe
type's interreflected energy (Cycles max_diffuse/glossy/transmission_bounce
semantics), and the default (-1, unlimited) must be byte-identical to a plain
render with no per-type args.

Scenes are the pure-astroray Cornell box (diffuse interreflection) — no Blender,
no GPU, so this runs fast in CI.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from base_helpers import create_cornell_box, setup_camera  # noqa: E402

import astroray  # noqa: E402

SPP = 16
MAX_DEPTH = 12
SEED = 7
W, H = 160, 120


def _render(diffuse=-1, glossy=-1, transmission=-1):
    r = astroray.Renderer()
    create_cornell_box(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=W, height=H)
    r.set_integrator("path_tracer")
    r.set_seed(SEED)
    # apply_gamma=False → linear energy so ratios are meaningful.
    px = r.render(SPP, MAX_DEPTH, None, False, diffuse, glossy, transmission)
    return np.asarray(px, dtype=np.float32)


def _mean_lum(img):
    return float(np.mean(img @ np.array([0.2126, 0.7152, 0.0722], np.float32)))


def test_diffuse_bounces_monotone_energy():
    """diffuse_bounces 0 (direct only) < 8 (deep interreflection)."""
    a = _mean_lum(_render(diffuse=0))
    b = _mean_lum(_render(diffuse=8))
    assert b > a * 1.01, f"diffuse_bounces not honoured: 0->{a:.5g} 8->{b:.5g}"


def test_diffuse_bounces_zero_below_unlimited():
    """Capping diffuse bounces at 0 must lose energy vs unlimited."""
    capped = _mean_lum(_render(diffuse=0))
    full = _mean_lum(_render(diffuse=-1))
    assert capped < full * 0.99, f"cap had no effect: 0->{capped:.5g} inf->{full:.5g}"


def test_default_unlimited_is_inert():
    """-1 (the default) must reproduce a plain no-per-type-arg render exactly.

    This is the byte-identical invariant: the honour code must be a strict no-op
    when every limit is unlimited, so all existing renders are unchanged.
    """
    r0 = astroray.Renderer()
    create_cornell_box(r0)
    setup_camera(r0, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=W, height=H)
    r0.set_integrator("path_tracer")
    r0.set_seed(SEED)
    plain = np.asarray(r0.render(SPP, MAX_DEPTH, None, False), dtype=np.float32)

    with_args = _render(diffuse=-1, glossy=-1, transmission=-1)
    np.testing.assert_array_equal(
        plain, with_args,
        "unlimited per-type args changed the render (not byte-identical)")
