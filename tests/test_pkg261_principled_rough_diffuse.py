"""pkg261 — Principled specular-layer albedo parity with Cycles at high roughness.

The pkg258 ground residual (Astroray ~7% under Cycles on a rough-specular
diffuse ground) traced to the diffuse/specular LAYERING albedo: Astroray fed
`closure_layering_weight` an `E * Fview * darkening` estimate whose view-angle
Fresnel `Fview -> 1` at grazing, over-attenuating the diffuse layer beneath by
1.2-5.5x at mu <= 0.5 (research note
`.astroray_plan/docs/pkg261-principled-layering-research.md`). Cycles instead
uses `bsdf_microfacet_estimate_albedo` (bsdf_microfacet.h:423-470, BSD-3-Clause):
`albedo = mix(f0, f90=1, s)`, `s` from the lobe-averaged 16^3 table
`ggx_gen_schlick_ior_s` (Apache-2.0, shipped verbatim as
`data/disney_compensation/ggx_gen_schlick_ior_s.bin`). pkg261 ports that.

Two gates:
  1. table reference regression (deterministic, no engine): the shipped LUT,
     read with Cycles' trilinear axis order, reproduces the pinned reference
     albedo `mix(f0,1,s)`; and the pre-fix `E*Fview*darkening` estimate is shown
     to over-shoot the reference by >3x at grazing (the defect the fix removes).
  2. normalised roughness sweep vs a pinned Cycles reference (CPU and GPU):
     a grazing-viewed Principled dielectric plane under a sun; mean(r)/mean(0)
     must match Cycles within +-3% at every roughness.
"""
import os
import struct

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_HERE, "..", "data", "disney_compensation")

# ---------------------------------------------------------------------------
# Gate 1: table reference regression (no engine).
# ---------------------------------------------------------------------------
_SZ = 16  # DisneyEnergyCompensationTables::kGenSchlickSize


def _read_bin(name, n):
    with open(os.path.join(_DATA, name), "rb") as fh:
        return list(struct.unpack("<%df" % n, fh.read(4 * n)))


def _sample3D(table, r, mu, z):
    """Trilinear read matching Cycles lookup_table_read_3D (rough x fastest, mu
    y, z z) and DisneyEnergyCompensationTables::sample3D exactly."""
    def cl(v):
        return min(max(v, 0.0), 1.0)
    r, mu, z = cl(r), cl(mu), cl(z)
    fx, fy, fz = r * (_SZ - 1), mu * (_SZ - 1), z * (_SZ - 1)
    x0, y0, z0 = min(int(fx), _SZ - 1), min(int(fy), _SZ - 1), min(int(fz), _SZ - 1)
    x1, y1, z1 = min(x0 + 1, _SZ - 1), min(y0 + 1, _SZ - 1), min(z0 + 1, _SZ - 1)
    tx, ty, tz = fx - x0, fy - y0, fz - z0

    def at(xi, yi, zi):
        return table[(zi * _SZ + yi) * _SZ + xi]

    def lp(a, b, t):
        return a * (1 - t) + b * t
    c00 = lp(at(x0, y0, z0), at(x1, y0, z0), tx)
    c10 = lp(at(x0, y1, z0), at(x1, y1, z0), tx)
    c01 = lp(at(x0, y0, z1), at(x1, y0, z1), tx)
    c11 = lp(at(x0, y1, z1), at(x1, y1, z1), tx)
    return lp(lp(c00, c10, ty), lp(c01, c11, ty), tz)


def _sample2D(table, sz, r, mu):
    def cl(v):
        return min(max(v, 0.0), 1.0)
    r, mu = cl(r), cl(mu)
    fx, fy = r * (sz - 1), mu * (sz - 1)
    x0, y0 = min(int(fx), sz - 1), min(int(fy), sz - 1)
    x1, y1 = min(x0 + 1, sz - 1), min(y0 + 1, sz - 1)
    tx, ty = fx - x0, fy - y0
    v00, v10 = table[y0 * sz + x0], table[y0 * sz + x1]
    v01, v11 = table[y1 * sz + x0], table[y1 * sz + x1]
    return (v00 * (1 - tx) + v10 * tx) * (1 - ty) + (v01 * (1 - tx) + v11 * tx) * ty


def _sample1D(table, sz, x):
    x = min(max(x, 0.0), 1.0)
    fx = x * (sz - 1)
    x0 = min(int(fx), sz - 1)
    x1 = min(x0 + 1, sz - 1)
    t = fx - x0
    return table[x0] * (1 - t) + table[x1] * t


# Cycles albedo mix(f0=0.04, 1, s) at IOR 1.5, evaluated from the shipped LUT.
# Pinned regression values (research note table, blender/blender@eaa5f63b).
_CYCLES_ALBEDO_REF = {
    (0.30, 0.20): 0.2706,
    (0.50, 0.20): 0.1667,
    (0.85, 1.00): 0.0414,
    (0.85, 0.50): 0.0570,
    (0.85, 0.20): 0.0822,
    (1.00, 1.00): 0.0413,
    (1.00, 0.20): 0.0686,
}


def test_ggx_gen_schlick_table_reference():
    """The shipped ggx_gen_schlick_ior_s LUT reproduces Cycles' mix(f0,1,s)
    layering albedo, and the pre-fix E*Fview*darkening estimate over-shoots it
    by >3x at grazing high roughness (the defect pkg261 removes)."""
    import math
    s_tab = _read_bin("ggx_gen_schlick_ior_s.bin", _SZ ** 3)
    assert len(s_tab) == _SZ ** 3
    assert min(s_tab) >= 0.0 and max(s_tab) <= 1.0
    ggxE = _read_bin("ggx_E.bin", 32 * 32)
    ggxEavg = _read_bin("ggx_Eavg.bin", 32)

    ior, f0 = 1.5, 0.04
    z = math.sqrt(abs((ior - 1.0) / (ior + 1.0)))

    def fresnel_dielectric(mu):
        c = abs(mu)
        s2 = (1 - c * c) / (ior * ior)
        if s2 >= 1:
            return 1.0
        ct = math.sqrt(1 - s2)
        rs = (c - ior * ct) / (c + ior * ct)
        rp = (ior * c - ct) / (ior * c + ct)
        return 0.5 * (rs * rs + rp * rp)

    def darkening(f, e, eavg):
        f = min(max(f, 0.0), 0.999)
        return 1.0 + (f * eavg / max(1 - f * (1 - eavg), 1e-4)) * ((1 - e) / e)

    for (r, mu), expect in _CYCLES_ALBEDO_REF.items():
        s = _sample3D(s_tab, r, mu, z)
        cyc = f0 * (1 - s) + 1.0 * s
        assert abs(cyc - expect) <= 0.002, (
            f"LUT albedo drift at r={r} mu={mu}: got {cyc:.4f}, pinned {expect:.4f}")

    # pre-fix estimate at grazing high roughness over-attenuates the diffuse.
    for (r, mu) in [(0.85, 0.20), (1.00, 0.20)]:
        e = max(_sample2D(ggxE, 32, r, mu), 1e-4)
        eavg = min(max(_sample1D(ggxEavg, 32, r), 0.0), 0.999)
        fv = min(fresnel_dielectric(mu), 0.999)
        old = e * fv * darkening(fv, e, eavg)
        s = _sample3D(s_tab, r, mu, z)
        cyc = f0 * (1 - s) + 1.0 * s
        assert old / cyc > 3.0, (
            f"pre-fix estimate at r={r} mu={mu} = {old:.4f} should exceed the "
            f"Cycles reference {cyc:.4f} by >3x (the layering defect)")


# ---------------------------------------------------------------------------
# Gate 2: normalised roughness sweep vs pinned Cycles (CPU + GPU).
# ---------------------------------------------------------------------------
# Pinned Cycles reference: grazing Principled dielectric plane (grey 0.5,
# metallic 0, transmission 0) under one sun straight down, black world, 64 spp
# CPU, Standard view transform, EXR linear, 160x120. Reproduce with:
#   & 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' -b \
#     --factory-startup --python \
#     test_results/2026-09-08-pkg261/cycles_ref_sweep.py
# (blender 5.2.0 LTS, mean linear luminance, ratio mean(r)/mean(0)).
_CYCLES_NORM = {0.0: 1.00000, 0.3: 1.19160, 0.5: 1.37060, 0.85: 1.51543, 1.0: 1.51879}
_SWEEP_ROUGHNESS = [0.0, 0.3, 0.5, 0.85, 1.0]
_SW, _SH, _SSPP = 160, 120, 64


def _sweep_scene(use_gpu, roughness):
    r = astroray.Renderer()
    look_from = [0.0, -6.0, 0.9]
    look_at = [0.0, -6.0 + 0.9903, 0.9 - 0.1392]  # cam rot X 82deg (matches Cycles)
    r.setup_camera(
        look_from=look_from, look_at=look_at, vup=[0.0, 0.0, 1.0],
        vfov=42.2, aspect_ratio=float(_SW) / float(_SH), aperture=0.0,
        focus_dist=6.0, width=_SW, height=_SH)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    mid = r.create_material("principled", [0.5, 0.5, 0.5],
                            {"metallic": 0.0, "roughness": roughness, "transmission": 0.0})
    s = 100.0
    r.add_triangle([-s, -s, 0.0], [s, -s, 0.0], [s, s, 0.0], mid)
    r.add_triangle([-s, -s, 0.0], [s, s, 0.0], [-s, s, 0.0], mid)
    r.add_sun_light_dedicated(direction=[0.0, 0.0, -1.0], angular_diameter=0.53,
                              emission={"mode": "rgb", "color": [1.0, 1.0, 1.0]},
                              intensity=3.0)
    return r


def _sweep_mean(use_gpu, roughness):
    r = _sweep_scene(use_gpu, roughness)
    px = np.array(r.render(_SSPP, 8, None, False), dtype=np.float32)  # linear
    assert np.isfinite(px).all()
    if px.ndim == 1:
        px = px.reshape(_SH, _SW, -1)
    rgb = px[:, :, :3]
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    return float(lum.mean())


@pytest.mark.parametrize("use_gpu", [
    pytest.param(False, id="cpu"),
    pytest.param(True, id="gpu", marks=pytest.mark.skipif(
        not (AVAILABLE and astroray.__features__.get("cuda", False)),
        reason="CUDA feature not in this build")),
])
def test_principled_rough_diffuse_sweep(use_gpu):
    means = {r: _sweep_mean(use_gpu, r) for r in _SWEEP_ROUGHNESS}
    base = means[0.0]
    backend = "gpu" if use_gpu else "cpu"
    worst = 0.0
    for r in _SWEEP_ROUGHNESS:
        norm = means[r] / base
        ref = _CYCLES_NORM[r]
        rel = abs(norm - ref) / ref
        worst = max(worst, rel)
        print(f"[pkg261 {backend}] r={r:.2f} norm={norm:.4f} cycles={ref:.4f} rel={rel*100:.2f}%")
    for r in _SWEEP_ROUGHNESS:
        norm = means[r] / base
        ref = _CYCLES_NORM[r]
        assert abs(norm - ref) / ref <= 0.03, (
            f"{backend} roughness {r}: normalised diffuse {norm:.4f} deviates "
            f"{abs(norm-ref)/ref*100:.2f}% from Cycles {ref:.4f} (>3%)")
