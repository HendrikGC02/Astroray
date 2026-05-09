#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg63 — World / HDRI parity tests.

Covers:
  (a) HDRI rotation: env rotated 90° about Y produces a different chromaticity
      at a fixed lookup direction (Y-axis chosen because it cleanly shifts
      azimuth on the equator without crossing a pole).
  (b) Grayscale color tint: tint=(0.5, 0.5, 0.5) halves the spectral env
      radiance per stratum (RGBUnboundedSpectrum collapses to a flat scalar
      for grayscale; chromatic-tint parity vs the RGB path is left to a
      follow-up — see review notes).
  (c) GPU vs CPU SSIM ≥ 0.97 on an HDRI scene at 64 spp (skipped without CUDA).

Reference: Cycles `intern/cycles/blender/shader.cpp` (Apache-2.0) for Mapping
node XYZ Euler order and Background Color tint composition. Detailed research
note: `.astroray_plan/docs/cycles-world-parity-research.md`.

Test HDRI is generated procedurally at write time (32x16, gradient + bright
spot) so the test stays self-contained and does not depend on samples/.
"""
import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import setup_camera  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


# ---------------------------------------------------------------------------
# Synthetic HDRI helper
# ---------------------------------------------------------------------------

def _write_radiance_hdr(path, img):
    """Minimal Radiance .hdr writer (RGBE encoding).

    Reference: Greg Ward, "Real Pixels", Graphics Gems II (1991). Standard
    32-bits-per-pixel format consumed by stbi_loadf in raytracer.h.
    """
    img = np.asarray(img, dtype=np.float32)
    height, width = img.shape[:2]
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    m = np.max(img, axis=2)
    valid = m > 1e-32
    # frexp: m = mantissa * 2^exp; mantissa in [0.5, 1) for nonzero m.
    mant, exp = np.frexp(np.where(valid, m, 1.0))
    scale = np.where(valid, mant * 256.0 / np.where(m > 0, m, 1.0), 0.0)
    rgbe[..., 0] = np.clip(np.floor(img[..., 0] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 1] = np.clip(np.floor(img[..., 1] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 2] = np.clip(np.floor(img[..., 2] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(valid, exp + 128, 0).astype(np.uint8)
    with open(path, 'wb') as f:
        f.write(b"#?RADIANCE\n")
        f.write(b"FORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {height} +X {width}\n".encode('ascii'))
        # Uncompressed scanlines (no RLE); stbi_loadf handles this fine.
        f.write(rgbe.tobytes())


def _write_test_hdri(path, width=32, height=16):
    """Procedural latlong HDRI: blue/red horizontal gradient + bright green spot.

    The horizontal gradient (per column) makes azimuthal rotations easy to
    detect: rotating 90° about Y shifts the lookup column by a quarter image.
    """
    img = np.zeros((height, width, 3), dtype=np.float32)
    for x in range(width):
        u = x / max(1, width - 1)
        img[:, x, 0] = u            # R rises toward right
        img[:, x, 2] = 1.0 - u      # B falls toward right
    # One bright green pixel near the equator, quarter way across.
    img[height // 2, width // 4, :] = [0.0, 50.0, 0.0]
    _write_radiance_hdr(path, img)


@pytest.fixture(scope="module")
def hdri_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("pkg63_hdri") / "test_world.hdr"
    _write_test_hdri(str(p))
    if not os.path.exists(str(p)):
        pytest.skip("HDRI write failed")
    return str(p)


# ---------------------------------------------------------------------------
# Test (a): rotation changes the lookup direction
# ---------------------------------------------------------------------------

def test_rotation_changes_env_lookup(hdri_path):
    """Rotating the env map about Y by 90° must shift the azimuthal lookup
    so the chromaticity at a fixed direction changes by more than 5%."""
    r0 = astroray.Renderer()
    assert r0.load_environment_map(hdri_path, 1.0, 0.0, 0.0, 0.0)

    ry90 = astroray.Renderer()
    # ry = +π/2: rotate Mapping by 90° about Y. This shifts the equator
    # azimuth without crossing a pole, so the lookup lands at a different
    # column of the horizontal gradient.
    assert ry90.load_environment_map(hdri_path, 1.0, 0.0, math.pi / 2.0, 0.0)

    # Sample direction +X (equator). Without rotation: phi=0 → u=0.5 (middle
    # column of the gradient). With Y-rotation: lookup shifts to phi=-π/2
    # → u=0.25 (left-quarter column, much bluer).
    direction = [1.0, 0.0, 0.0]
    u = 0.5
    s0 = np.array(r0.eval_env_spectral(direction, u))
    s90 = np.array(ry90.eval_env_spectral(direction, u))

    # If both samples are zero we can't conclude anything; require some signal.
    assert np.max(np.abs(s0)) > 0.0 or np.max(np.abs(s90)) > 0.0, \
        "both env samples are zero; HDRI not loaded?"

    # Chromaticity difference: normalize by sum to remove brightness changes,
    # then measure L1 distance.
    def chroma(s):
        total = float(np.sum(np.abs(s))) + 1e-8
        return s / total

    diff = float(np.sum(np.abs(chroma(s0) - chroma(s90))))
    assert diff > 0.05, f"rotation produced chromaticity diff {diff:.4f} ≤ 0.05"


# ---------------------------------------------------------------------------
# Test (b): color tint multiplies env radiance
# ---------------------------------------------------------------------------

def test_color_tint_halves_env_radiance(hdri_path):
    """tint=(0.5, 0.5, 0.5) must produce env radiance ≈ 0.5× untinted."""
    r1 = astroray.Renderer()
    assert r1.load_environment_map(hdri_path, 1.0,
                                   0.0, 0.0, 0.0,
                                   1.0, 1.0, 1.0)
    r_half = astroray.Renderer()
    assert r_half.load_environment_map(hdri_path, 1.0,
                                       0.0, 0.0, 0.0,
                                       0.5, 0.5, 0.5)

    # Sample a few directions. Each spectral sample is 4 wavelength strata.
    directions = [[1, 0, 0], [0, 1, 0], [0, 0, 1],
                  [-1, 0, 0], [0, -1, 0], [0, 0, -1],
                  [1, 1, 0], [0, 1, 1]]
    for u in (0.0, 0.25, 0.5, 0.75):
        for d in directions:
            d_norm = [c / max(1e-8, math.sqrt(sum(x * x for x in d))) for c in d]
            s_full = np.array(r1.eval_env_spectral(d_norm, u))
            s_half = np.array(r_half.eval_env_spectral(d_norm, u))
            # If the full-tint sample is essentially zero, the half sample
            # should be too — skip the ratio check.
            if np.max(np.abs(s_full)) < 1e-5:
                assert np.max(np.abs(s_half)) < 1e-4
                continue
            # Half tint should produce ≈ half the radiance, within 1% per stratum.
            np.testing.assert_allclose(s_half, s_full * 0.5, rtol=0.01, atol=1e-5)


# ---------------------------------------------------------------------------
# Test (c): GPU vs CPU SSIM on an HDRI scene
# ---------------------------------------------------------------------------

def test_gpu_cpu_ssim_hdri(hdri_path):
    """Render a tiny HDRI scene on CPU and CUDA backends; SSIM ≥ 0.97.

    Uses the canonical `gpu_available` / `set_use_gpu(True)` pair seen in
    test_python_bindings.py::test_gpu_renders_match_cpu — skips at runtime
    rather than collection time so a CUDA-equipped verifier host actually
    runs the gate.
    """
    try:
        from skimage.metrics import structural_similarity as ssim_fn
    except ImportError:
        pytest.skip("scikit-image not available for SSIM")

    def build(use_gpu):
        r = astroray.Renderer()
        if use_gpu:
            if not r.gpu_available:
                pytest.skip("No CUDA GPU available")
            r.set_use_gpu(True)
        r.set_integrator("path_tracer")
        r.load_environment_map(hdri_path, 1.0,
                               0.0, 0.0, math.pi / 4.0,
                               0.9, 0.9, 1.0,
                               True)
        setup_camera(r, look_from=[0, 1, 5], look_at=[0, 0, 0],
                     vfov=40, width=64, height=64)
        return np.asarray(r.render(64, 4, None, False))

    cpu = build(False)
    gpu = build(True)
    assert cpu.shape == gpu.shape == (64, 64, 3)

    # Tonemap-ish before SSIM so HDR fireflies don't dominate.
    def lin(arr):
        a = arr / max(1.0, float(arr.max()))
        return np.clip(a, 0.0, 1.0)

    score = ssim_fn(lin(cpu), lin(gpu), channel_axis=2, data_range=1.0)
    assert score >= 0.97, f"GPU vs CPU SSIM {score:.4f} < 0.97"
