#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg275 — texel-exact environment-lookup probes (diagnostic ladder rungs 2 & 5,
with a rung-6 spectral CPU/GPU cross-check).

These probes bypass the integrator entirely: they sample the loaded HDRI at a
fixed set of world directions through the engine bindings and compare against a
numpy bilinear decode of the *same* Radiance .hdr bytes, so a mismatch cannot
be a Monte-Carlo / MIS artefact.

  - rung 2 (CPU): environment_lookup(dir) vs numpy bilinear on the stb-decoded
    float image. Catches gamma-on-load, a row-order (flip) bug, and any
    interpolation/index arithmetic error. Also *measures* the half-texel
    (texel-center) offset vs the Cycles svm_image convention as a diagnostic
    (printed, not asserted): Cycles subtracts 0.5 before flooring; Astroray's
    lookup does not, so on a high-frequency image the two disagree by up to
    ~one texel step. Reference: Cycles intern/cycles/kernel/svm/svm_image.h
    (svm_image_texture, Apache-2.0). See
    .astroray_plan/docs/pkg275-env-lookup-research.md.
  - rung 5 (GPU): the same directions through the wavefront device lookup
    (gpu_envmap_lookup) vs the CPU environment_lookup — removes Monte Carlo
    from #755.
  - rung 6 (GPU spectral): gpu_env_miss_spectral vs CPU evalSpectral at
    identical wavelengths — isolates the RGB->spectral (Jakob-Hanika) upsample
    from the lookup for the #755 per-channel-chromatic gap.

Test HDRI is generated procedurally so the test is self-contained.
"""
import math
import os
import struct
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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


# ---------------------------------------------------------------------------
# Radiance .hdr writer + stb-exact decoder
# ---------------------------------------------------------------------------

def _write_radiance_hdr(path, img):
    """Minimal uncompressed Radiance .hdr writer (RGBE). Mirrors the writer in
    tests/test_world_hdri_parity.py so both gates read the same format."""
    img = np.asarray(img, dtype=np.float32)
    height, width = img.shape[:2]
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    m = np.max(img, axis=2)
    valid = m > 1e-32
    mant, exp = np.frexp(np.where(valid, m, 1.0))
    scale = np.where(valid, mant * 256.0 / np.where(m > 0, m, 1.0), 0.0)
    rgbe[..., 0] = np.clip(np.floor(img[..., 0] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 1] = np.clip(np.floor(img[..., 1] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 2] = np.clip(np.floor(img[..., 2] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(valid, exp + 128, 0).astype(np.uint8)
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\n")
        f.write(b"FORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {height} +X {width}\n".encode("ascii"))
        f.write(rgbe.tobytes())


def _decode_radiance_hdr(path):
    """Decode the uncompressed RGBE file back to a float image, replicating
    stb_image's hdr_convert (out[c] = in[c] * 2^(e - 136)) so the reference
    operates on the *exact* floats EnvironmentMap holds after stbi_loadf."""
    with open(path, "rb") as f:
        raw = f.read()
    # Header: lines until a blank line, then the resolution line.
    idx = 0
    # skip "#?RADIANCE\n"
    while True:
        nl = raw.index(b"\n", idx)
        line = raw[idx:nl]
        idx = nl + 1
        if line.strip() == b"":
            break
    nl = raw.index(b"\n", idx)
    res = raw[idx:nl].decode("ascii").split()
    idx = nl + 1
    # res == ["-Y", H, "+X", W]
    height = int(res[1])
    width = int(res[3])
    rgbe = np.frombuffer(raw[idx:idx + width * height * 4], dtype=np.uint8)
    rgbe = rgbe.reshape(height, width, 4).astype(np.float32)
    e = rgbe[..., 3]
    f_scale = np.where(e > 0, np.exp2(e - 136.0), 0.0)
    img = np.zeros((height, width, 3), dtype=np.float32)
    for c in range(3):
        img[..., c] = rgbe[..., c] * f_scale
    return img


def _make_hdri(width=128, height=64, high_freq=False):
    """Latlong test HDRI. Smooth mode: slowly-varying chromatic gradients (all
    lookup conventions agree). high_freq mode: adds a per-column sawtooth so the
    half-texel offset produces a measurable per-texel discrepancy."""
    img = np.zeros((height, width, 3), dtype=np.float32)
    xs = np.arange(width, dtype=np.float32)
    ys = np.arange(height, dtype=np.float32)
    U, V = np.meshgrid(xs / width, ys / height)
    img[..., 0] = 0.30 + 0.60 * (0.5 + 0.5 * np.sin(2.0 * math.pi * U))
    img[..., 1] = 0.20 + 0.50 * V
    img[..., 2] = 0.30 + 0.60 * (0.5 + 0.5 * np.cos(2.0 * math.pi * U))
    if high_freq:
        saw = (xs % 2).astype(np.float32)  # 0,1,0,1,... per column
        img[..., 0] += 0.8 * saw[None, :]
        img[..., 2] += 0.8 * (1.0 - saw[None, :])
    return np.clip(img, 0.0, None)


# ---------------------------------------------------------------------------
# numpy lookup references (equirect convention transcribed from
# EnvironmentMap::lookup, include/raytracer.h:1545)
# ---------------------------------------------------------------------------

def _dir_to_uv(d):
    d = np.asarray(d, dtype=np.float64)
    d = d / np.linalg.norm(d)
    theta = math.acos(min(1.0, max(-1.0, d[1])))
    phi = math.atan2(d[2], d[0])
    u = 0.5 + phi / (2.0 * math.pi)
    v = 1.0 - theta / math.pi
    if u < 0.0:
        u += 1.0
    if u >= 1.0:
        u -= 1.0
    return u, v


def _bilinear(img, u, v, half_texel=False):
    """Bilinear fetch. half_texel=False mirrors EnvironmentMap::lookup
    (x0 = floor(u*W)); half_texel=True is the Cycles svm_image convention
    (x0 = floor(u*W - 0.5))."""
    h, w = img.shape[:2]
    up = u * w
    vp = v * h
    if half_texel:
        up -= 0.5
        vp -= 0.5
    x0 = int(math.floor(up))
    y0 = int(math.floor(vp))
    x1 = x0 + 1
    y1 = y0 + 1
    uf = up - x0
    vf = vp - y0
    cx0 = min(max(x0, 0), w - 1)
    cx1 = min(max(x1, 0), w - 1)
    cy0 = min(max(y0, 0), h - 1)
    cy1 = min(max(y1, 0), h - 1)
    c00 = img[cy0, cx0]
    c10 = img[cy0, cx1]
    c01 = img[cy1, cx0]
    c11 = img[cy1, cx1]
    c0 = c00 * (1 - uf) + c10 * uf
    c1 = c01 * (1 - uf) + c11 * uf
    return c0 * (1 - vf) + c1 * vf


# A spread of directions away from the poles and the u=0 seam.
_DIRS = []
for _az in (0.3, 0.9, 1.7, 2.4, 3.1, 3.9, 4.6, 5.3):
    for _el in (-0.7, -0.2, 0.3, 0.8):
        _DIRS.append([
            math.cos(_el) * math.cos(_az),
            math.sin(_el),
            math.cos(_el) * math.sin(_az),
        ])


@pytest.fixture(scope="module")
def hdri(tmp_path_factory):
    p = tmp_path_factory.mktemp("pkg275") / "smooth.hdr"
    _write_radiance_hdr(str(p), _make_hdri(high_freq=False))
    img = _decode_radiance_hdr(str(p))
    return str(p), img


@pytest.fixture(scope="module")
def hdri_hf(tmp_path_factory):
    p = tmp_path_factory.mktemp("pkg275hf") / "hf.hdr"
    _write_radiance_hdr(str(p), _make_hdri(high_freq=True))
    img = _decode_radiance_hdr(str(p))
    return str(p), img


def _load(path):
    r = astroray.Renderer()
    assert r.load_environment_map(path, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, False)
    return r


# ---------------------------------------------------------------------------
# rung 2 — CPU lookup vs numpy bilinear on the identical decoded image
# ---------------------------------------------------------------------------

def test_rung2_cpu_lookup_matches_numpy_bilinear(hdri):
    path, img = hdri
    r = _load(path)
    worst = 0.0
    for d in _DIRS:
        got = np.array(r.environment_lookup(d), dtype=np.float64)
        u, v = _dir_to_uv(d)
        ref = _bilinear(img, u, v, half_texel=False).astype(np.float64)
        denom = np.maximum(np.abs(ref), 1e-4)
        rel = np.max(np.abs(got - ref) / denom)
        worst = max(worst, rel)
    print(f"[pkg275 rung2] CPU lookup vs numpy bilinear (engine convention): "
          f"worst rel = {worst:.2e}")
    assert worst < 1e-3, (
        f"CPU environment_lookup diverges from numpy bilinear by {worst:.2e} "
        "(>1e-3): a decode/gamma/flip/interpolation bug")


def test_rung2_halftexel_offset_measurement(hdri_hf):
    """Diagnostic (not a pass/fail on the offset itself): quantify the
    half-texel (texel-center) discrepancy vs the Cycles svm_image convention on
    a high-frequency image. The engine lookup must still equal the *engine*
    convention exactly; the printed number is the parity gap vs Cycles."""
    path, img = hdri_hf
    r = _load(path)
    worst_engine = 0.0
    worst_cycles = 0.0
    for d in _DIRS:
        got = np.array(r.environment_lookup(d), dtype=np.float64)
        u, v = _dir_to_uv(d)
        ref_engine = _bilinear(img, u, v, half_texel=False).astype(np.float64)
        ref_cycles = _bilinear(img, u, v, half_texel=True).astype(np.float64)
        de = np.max(np.abs(got - ref_engine) / np.maximum(np.abs(ref_engine), 1e-4))
        dc = np.max(np.abs(got - ref_cycles) / np.maximum(np.abs(ref_cycles), 1e-4))
        worst_engine = max(worst_engine, de)
        worst_cycles = max(worst_cycles, dc)
    print(f"[pkg275 rung2-hf] engine-conv worst rel = {worst_engine:.2e}; "
          f"cycles-halftexel worst rel = {worst_cycles:.2e}")
    # The engine must match its own convention exactly even on a HF image.
    assert worst_engine < 1e-3


# ---------------------------------------------------------------------------
# rung 5 — GPU device lookup vs CPU lookup (removes Monte Carlo from #755)
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_rung5_gpu_lookup_matches_cpu(hdri):
    path, _ = hdri
    r = _load(path)
    if not r.gpu_available:
        pytest.skip("No CUDA GPU available")
    flat = [c for d in _DIRS for c in d]
    out = np.array(r.probe_env_lookup_gpu(flat, 0.5), dtype=np.float64)
    stride = out.size // len(_DIRS)
    out = out.reshape(len(_DIRS), stride)
    worst = 0.0
    for i, d in enumerate(_DIRS):
        cpu = np.array(r.environment_lookup(d), dtype=np.float64)
        gpu = out[i, :3]
        denom = np.maximum(np.abs(cpu), 1e-4)
        worst = max(worst, float(np.max(np.abs(gpu - cpu) / denom)))
    print(f"[pkg275 rung5] GPU vs CPU RGB lookup: worst rel = {worst:.2e}")
    assert worst < 1e-3, (
        f"GPU gpu_envmap_lookup diverges from CPU by {worst:.2e} (>1e-3)")


# ---------------------------------------------------------------------------
# rung 6 — GPU spectral env-miss vs CPU evalSpectral at identical wavelengths
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_rung6_gpu_spectral_matches_cpu(hdri):
    path, _ = hdri
    r = _load(path)
    if not r.gpu_available:
        pytest.skip("No CUDA GPU available")
    u = 0.5
    flat = [c for d in _DIRS for c in d]
    out = np.array(r.probe_env_lookup_gpu(flat, u), dtype=np.float64)
    stride = out.size // len(_DIRS)
    out = out.reshape(len(_DIRS), stride)
    worst = 0.0
    for i, d in enumerate(_DIRS):
        cpu = np.array(r.eval_env_spectral(d, u), dtype=np.float64)
        gpu = out[i, 3:3 + cpu.size]
        denom = np.maximum(np.abs(cpu), 1e-4)
        worst = max(worst, float(np.max(np.abs(gpu - cpu) / denom)))
    print(f"[pkg275 rung6] GPU vs CPU spectral env-miss: worst rel = {worst:.2e}")
    assert worst < 1e-3, (
        f"GPU gpu_env_miss_spectral diverges from CPU evalSpectral by "
        f"{worst:.2e} (>1e-3): RGB->spectral upsample skew (#755)")
