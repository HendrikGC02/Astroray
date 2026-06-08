#!/usr/bin/env python
"""pkg113 Phase 2 — GPU photon EMISSION + BOUNCE vs a numpy float64 oracle.

The GPU device kernel (src/gpu/photon_emission.cu) forward-traces a batch of
collimated-sun photons through a single glass sphere (Snell refraction +
Schlick-Fresnel reflect/transmit + enter/exit from the geometric-normal sign +
per-λ Sellmeier iorAt + TIR) and deposits the surviving per-λ CIE flux as
GPhotons on a flat receiver plane. This is the GPU port of the GENERAL
deterministic-refraction path of plugins/integrators/light_tracer_caustic.cpp
(lines 276-326). The flat-prism explicit 2-face path STAYS CPU (see
include/astroray/gpu_photon_emit.h).

Parity is by AGGREGATE bounds, NOT bit-exact — the forward trace is a stochastic
light-particle deposit (memory [[general-photon-loop-needs-solid-glass]]: the
caustic numeric gates pass on salt-and-pepper noise, so assert energy AND
position, never a count alone). The oracle runs the IDENTICAL closed-form math
(same pe_jitter aperture lattice, same Sellmeier IOR via the GPU's GDispersion
coefficients, same Schlick transmittance, same CIE-CMF table via the
`cie_cmf_1964_10deg` binding) fed the SAME deterministic entry samples — the
"inject the same samples both sides" tactic sms_attempt_device.cuh uses for its
Phase-1 unit test — so the comparison isolates the device math from RNG noise.

GPU-gated: skips gracefully when CUDA is absent (CI has no GPU); /verify runs
this on the RTX box. Mirrors the skip pattern of tests/test_gpu_photon_store.py.

References: Arvo 1986 (forward light transport); Jensen 1996 (diffuse photon
deposit); Schlick 1994 (Fresnel); Sellmeier 1871 (n(λ), reused via pkg64-gpu
gpu_dispersion.cuh); CIE 1964 10° CMF (data/spectra/cie_cmf.inc). See
.astroray_plan/docs/pkg113-phase2-photon-emission-research.md.
"""

from __future__ import annotations

import numpy as np
import pytest

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build — pkg113 Phase 2 GPU photon emission "
        "needs CUDA; /verify runs this on the RTX box.",
        allow_module_level=True,
    )

if AVAILABLE and not hasattr(astroray, "_gpu_photon_emit_sphere"):
    pytest.skip(
        "GPU photon-emission binding not present — rebuild astroray.pyd (pkg113).",
        allow_module_level=True,
    )


# --- BK7 Sellmeier coefficients (Schott BK7, the prism/sphere glass) ----------
# n²(λ) = 1 + B1λ²/(λ²−C1) + B2λ²/(λ²−C2) + B3λ²/(λ²−C3), λ in μm.
BK7_B = (1.03961212, 0.231792344, 1.01046945)
BK7_C = (0.00600069867, 0.0200179144, 103.560653)
BK7_SELLMEIER = list(BK7_B) + list(BK7_C)


# --- Oracle: bit-faithful re-implementation of the device kernel math ---------
_M32 = 0xFFFFFFFF


def _pe_jitter(cell, salt):
    """Exact uint32 reproduction of pe_jitter() in photon_emission.cu. CUDA's
    unsigned arithmetic wraps mod 2^32; we mask Python ints to 32 bits to match
    bit-for-bit, then do the final float multiply in float32 like the device."""
    h = (cell * 0x9E3779B1 + salt * 0x85EBCA77) & _M32
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & _M32
    h ^= h >> 12
    h = (h * 0x297A2D39) & _M32
    h ^= h >> 15
    return float(np.float32((h & 0x00FFFFFF) * np.float32(1.0 / 16777216.0)))


def _sellmeier_ior(lam_nm, B, C):
    lam_um = lam_nm * 1e-3
    l2 = lam_um * lam_um
    n2 = 1.0
    n2 += B[0] * l2 / (l2 - C[0])
    n2 += B[1] * l2 / (l2 - C[1])
    n2 += B[2] * l2 / (l2 - C[2])
    return float(np.sqrt(max(1.0, n2)))


def _refract(d, n, eta):
    cosi = -float(np.dot(d, n))
    s2 = eta * eta * (1.0 - cosi * cosi)
    if s2 >= 1.0:
        return None
    out = d * eta + n * (eta * cosi - np.sqrt(1.0 - s2))
    return out / np.linalg.norm(out)


def _fresnel_t(cosi, ior):
    f0 = (1.0 - ior) / (1.0 + ior)
    f0 *= f0
    fr = f0 + (1.0 - f0) * max(0.0, 1.0 - abs(cosi)) ** 5
    return 1.0 - fr


def _sphere_hit(center, radius, o, d, t_min):
    oc = o - center
    a = float(np.dot(d, d))
    hb = float(np.dot(oc, d))
    c = float(np.dot(oc, oc)) - radius * radius
    disc = hb * hb - a * c
    if disc < 0.0:
        return None
    sq = np.sqrt(disc)
    root = (-hb - sq) / a
    if root < t_min:
        root = (-hb + sq) / a
        if root < t_min:
            return None
    p = o + d * root
    ng = (p - center) / radius
    return root, ng


def _oracle_emit(center, radius, B, C, sun_dir, ap_origin, ap_u, ap_v,
                 ap_radius, receiver_y, aperture_n, lam_min, lam_max, max_depth,
                 ior_fn=_sellmeier_ior):
    eps = 1e-3
    deposits = []
    for gy in range(aperture_n):
        for gx in range(aperture_n):
            cell = gy * aperture_n + gx
            u_lam = float(_pe_jitter(cell, 101))
            lam = lam_min + (lam_max - lam_min) * u_lam
            ior = ior_fn(lam, B, C)
            if ior <= 1.0:
                ior = 1.5

            jx = (gx + float(_pe_jitter(cell, 1))) / aperture_n
            jy = (gy + float(_pe_jitter(cell, 2))) / aperture_n
            a2 = (jx * 2.0 - 1.0) * ap_radius
            b2 = (jy * 2.0 - 1.0) * ap_radius
            o = ap_origin + ap_u * a2 + ap_v * b2
            d = sun_dir.copy()

            tr = 1.0
            passed = False
            for _ in range(max_depth):
                hit = _sphere_hit(center, radius, o, d, eps)
                if hit is None:
                    if not passed:
                        o = None
                    break
                t, ng = hit
                hit_point = o + d * t
                if float(np.dot(d, ng)) < 0.0:
                    nf, eta = ng, 1.0 / ior
                else:
                    nf, eta = -ng, ior
                nd = _refract(d, nf, eta)
                if nd is not None:
                    tr *= _fresnel_t(float(np.dot(d, nf)), ior)
                    d = nd
                else:
                    d = d - nf * (2.0 * float(np.dot(d, nf)))
                    d = d / np.linalg.norm(d)
                passed = True
                o = hit_point + d * eps

            if o is None or not passed or tr <= 0.0:
                continue
            if d[1] >= -1e-6:
                continue
            t_plane = (receiver_y - o[1]) / d[1]
            if t_plane <= eps:
                continue
            hit = o + d * t_plane
            cmf = astroray.cie_cmf_1964_10deg(lam)  # exact CPU CMF table (XYZ struct)
            power = np.array([cmf.X * tr, cmf.Y * tr, cmf.Z * tr])
            deposits.append((hit, power, lam))
    return deposits


def _scene():
    center = np.array([0.0, 1.0, 0.0])
    radius = 0.5
    sun_dir = np.array([0.0, -1.0, 0.0])      # straight down
    # Aperture disc above the sphere, spanning the inner projected extent.
    # ap_radius=0.35 (< radius) keeps every ray clear of the grazing/TIR rim, so
    # the deterministic lattice survives 100% on BOTH sides — no float32-vs-float64
    # boundary flips — giving a clean, focused-caustic parity scene.
    ap_origin = np.array([0.0, 3.0, 0.0])
    ap_radius = 0.35
    receiver_y = -1.0
    aperture_n = 96                           # 9216 photons
    lam_min, lam_max = 380.0, 720.0
    max_depth = 12
    # Device-side aperture frame around sun_dir (matches the .cu launcher).
    a = np.array([1.0, 0.0, 0.0]) if abs(sun_dir[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    ap_u = a - sun_dir * float(np.dot(a, sun_dir))
    ap_u = ap_u / np.linalg.norm(ap_u)
    ap_v = np.cross(sun_dir, ap_u)
    return dict(center=center, radius=radius, sun_dir=sun_dir, ap_origin=ap_origin,
                ap_u=ap_u, ap_v=ap_v, ap_radius=ap_radius, receiver_y=receiver_y,
                aperture_n=aperture_n, lam_min=lam_min, lam_max=lam_max,
                max_depth=max_depth)


def _run_gpu(s):
    return astroray._gpu_photon_emit_sphere(
        center=s["center"].tolist(), radius=s["radius"],
        sellmeier=BK7_SELLMEIER, flat_ior=1.5, is_dispersive=True,
        sun_dir=s["sun_dir"].tolist(),
        aperture_center=s["ap_origin"].tolist(),
        aperture_radius=s["ap_radius"], receiver_y=s["receiver_y"],
        aperture_n=s["aperture_n"], lambda_min=s["lam_min"],
        lambda_max=s["lam_max"], max_depth=s["max_depth"],
    )


def _aggregate(positions, powers):
    pos = np.asarray(positions, dtype=np.float64)
    pw = np.asarray(powers, dtype=np.float64)
    total_y = float(pw[:, 1].sum())
    # Y-weighted centroid in the receiver plane (x, z).
    w = pw[:, 1]
    wsum = max(w.sum(), 1e-12)
    cx = float((pos[:, 0] * w).sum() / wsum)
    cz = float((pos[:, 2] * w).sum() / wsum)
    # Y-weighted radial RMS extent about the centroid.
    rr = (pos[:, 0] - cx) ** 2 + (pos[:, 2] - cz) ** 2
    rms = float(np.sqrt((rr * w).sum() / wsum))
    return total_y, (cx, cz), rms


def test_gpu_deposit_set_matches_oracle_aggregate():
    """GPU deposit set vs numpy float64 oracle (identical math, same lattice):
    total Y-energy within ±5 %, Y-weighted centroid within 0.05·radius, radial
    RMS extent within ±15 %. Aggregate bounds, not bit-exact (stochastic
    forward trace; memory [[general-photon-loop-needs-solid-glass]])."""
    s = _scene()

    gpu = _run_gpu(s)
    assert len(gpu) > 100, f"GPU deposited only {len(gpu)} photons (expected many)"
    g_pos = [d[0] for d in gpu]
    g_pw = [d[1] for d in gpu]

    oracle = _oracle_emit(
        s["center"], s["radius"], BK7_B, BK7_C, s["sun_dir"], s["ap_origin"],
        s["ap_u"], s["ap_v"], s["ap_radius"], s["receiver_y"], s["aperture_n"],
        s["lam_min"], s["lam_max"], s["max_depth"],
    )
    assert len(oracle) > 100, f"oracle deposited only {len(oracle)} (math/scene bug)"
    o_pos = [d[0] for d in oracle]
    o_pw = [d[1] for d in oracle]

    # Survivor count: same deterministic lattice -> nearly identical survivor set
    # (float32 vs float64 may flip a handful at the TIR / grazing boundary).
    assert abs(len(gpu) - len(oracle)) <= 0.02 * len(oracle) + 5, (
        f"survivor count GPU {len(gpu)} vs oracle {len(oracle)} diverges"
    )

    g_total, g_cent, g_rms = _aggregate(g_pos, g_pw)
    o_total, o_cent, o_rms = _aggregate(o_pos, o_pw)

    energy_ratio = g_total / max(o_total, 1e-12)
    assert 0.95 <= energy_ratio <= 1.05, (
        f"deposited Y-energy ratio {energy_ratio:.4f} outside ±5% "
        f"(GPU {g_total:.4g}, oracle {o_total:.4g})"
    )

    cent_err = np.hypot(g_cent[0] - o_cent[0], g_cent[1] - o_cent[1])
    assert cent_err < 0.05 * s["radius"], (
        f"deposit centroid off by {cent_err:.4g} > 0.05·radius "
        f"(GPU {g_cent}, oracle {o_cent})"
    )

    rms_ratio = g_rms / max(o_rms, 1e-9)
    assert 0.85 <= rms_ratio <= 1.15, (
        f"deposit radial RMS extent ratio {rms_ratio:.4f} outside ±15% "
        f"(GPU {g_rms:.4g}, oracle {o_rms:.4g})"
    )


def test_gpu_deposit_is_dispersed_not_a_point():
    """A dispersive glass sphere focuses a caustic with finite extent and a
    spread of wavelengths — guards against a degenerate all-at-one-point or
    all-one-λ deposit (the salt-and-pepper failure mode)."""
    s = _scene()
    gpu = _run_gpu(s)
    assert len(gpu) > 100
    lambdas = np.array([d[2] for d in gpu])
    pos = np.asarray([d[0] for d in gpu], dtype=np.float64)
    # Wavelengths span a real band (dispersion is active), not collapsed.
    assert lambdas.max() - lambdas.min() > 100.0, "deposit λ band collapsed"
    # The caustic has finite spatial extent (not a single degenerate point).
    extent = np.hypot(pos[:, 0].std(), pos[:, 2].std())
    assert extent > 1e-3, "deposit collapsed to a point (geometry/refraction bug)"


def test_non_dispersive_glass_also_deposits():
    """A flat-IOR (non-dispersive) glass sphere still focuses a caustic — the
    is_dispersive=False path (flat_ior, no Sellmeier) must deposit, with energy
    matching the oracle within ±5 %."""
    s = _scene()
    gpu = astroray._gpu_photon_emit_sphere(
        center=s["center"].tolist(), radius=s["radius"],
        sellmeier=[0.0] * 6, flat_ior=1.5, is_dispersive=False,
        sun_dir=s["sun_dir"].tolist(),
        aperture_center=s["ap_origin"].tolist(),
        aperture_radius=s["ap_radius"], receiver_y=s["receiver_y"],
        aperture_n=s["aperture_n"], lambda_min=s["lam_min"],
        lambda_max=s["lam_max"], max_depth=s["max_depth"],
    )
    assert len(gpu) > 100, f"non-dispersive glass deposited only {len(gpu)}"

    # Oracle with a constant IOR = 1.5 (Sellmeier bypassed), matching the
    # device's is_dispersive=False path (flat_ior=1.5).
    def const_ior(_lam, _B, _C):
        return 1.5

    oracle = _oracle_emit(
        s["center"], s["radius"], (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), s["sun_dir"],
        s["ap_origin"], s["ap_u"], s["ap_v"], s["ap_radius"],
        s["receiver_y"], s["aperture_n"], s["lam_min"], s["lam_max"],
        s["max_depth"], ior_fn=const_ior,
    )

    g_total, _, _ = _aggregate([d[0] for d in gpu], [d[1] for d in gpu])
    o_total, _, _ = _aggregate([d[0] for d in oracle], [d[1] for d in oracle])
    ratio = g_total / max(o_total, 1e-12)
    assert 0.95 <= ratio <= 1.05, f"non-dispersive energy ratio {ratio:.4f} outside ±5%"
