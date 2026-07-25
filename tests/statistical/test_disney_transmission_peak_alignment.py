"""
pkg149 — Disney dielectric rough-TRANSMISSION sample()/pdf() peak-alignment gate.

Measures the angular offset between where sample()'s VNDF-then-refract
transmission draws actually land and where pdf()'s continuous transmission
density says the mass should be, restricted to the incidence plane (the
same methodology as the pkg138 research note that discovered the ~16-18 deg
mismatch: `.astroray_plan/docs/pkg138-disney-dielectric-rough-reflection-research.md`
Root cause #3).

Root cause (see `.astroray_plan/docs/pkg149-disney-rough-transmission-research.md`):
`sampleGgxVNDF`'s disk-warp step ported pbrt-v4's
`p.y = Lerp((1 + wh.z) / 2, h, p.y)` (pbrt-v4 `src/pbrt/util/scattering.h`,
Apache-2.0; `Lerp(t,a,b) = (1-t)*a + t*b`, `src/pbrt/util/math.h`) with `h`
and `py` swapped, biasing every VNDF-sampled half-vector to the azimuth
OPPOSITE `wo` instead of the (correct) side aligned with it. This is what
produced the reported peak offset; `roughTransmissionEval`/`roughTransmissionPdf`/
`refractThroughMicroNormal` were independently re-derived against pbrt-v4
`DielectricBxDF::f`/`PDF` and found already correct (half-vector reconstruction
from a sampled `(wo,wi)` pair matches the original sampled `wm` bit-for-bit).
"""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
except ImportError:
    pytest.skip("astroray module not available", allow_module_level=True)


PEAK_ALIGNMENT_TOLERANCE_DEG = 2.0
IN_PLANE_EPS = 0.03  # matches the pkg138 research note's |z| in-plane band


def spherical_to_cartesian(theta, phi):
    """Y-up convention (matches makeMaterialTestRecord normal=[0,1,0])."""
    sin_theta = np.sin(theta)
    cos_theta = np.cos(theta)
    return np.array([sin_theta * np.cos(phi), cos_theta, sin_theta * np.sin(phi)])


def _measure_peaks(renderer, mat_id, wo, theta_o_deg, ior, n_samples=200_000, n_pdf_pts=400):
    """Returns (sample_peak_deg, pdf_peak_deg, n_live_in_plane)."""
    rng = np.random.default_rng(12345)
    u2 = rng.random((2, n_samples)).astype(np.float32)
    wi, pdf = renderer.debug_bsdf_sample_batch(mat_id, wo.tolist(), u2)

    # Transmission side (below the macro hemisphere, Y-up: n=[0,1,0]) and
    # restricted to the exact incidence plane (z ~ 0), matching pkg138's method.
    live = (pdf > 0.0) & (wi[:, 1] < 0.0) & (np.abs(wi[:, 2]) < IN_PLANE_EPS)
    wi_live = wi[live]
    n_live = int(live.sum())
    assert n_live >= 1000, f"too few live in-plane transmission samples: {n_live}"

    theta_from_normal = np.degrees(np.arccos(np.clip(wi_live[:, 1], -1.0, 1.0)))
    hist, edges = np.histogram(theta_from_normal, bins=60, range=(90.0, 180.0))
    peak_bin = np.argmax(hist)
    sample_peak = 0.5 * (edges[peak_bin] + edges[peak_bin + 1])

    # Sweep pdf() over theta in the exact incidence plane, on the refraction-bend
    # side (same azimuthal half-plane the live samples above land on).
    thetas = np.linspace(90.001, 179.999, n_pdf_pts)
    wi_query = np.zeros((n_pdf_pts, 3), dtype=np.float32)
    for i, th in enumerate(thetas):
        thr = np.radians(th)
        # bend to -x side (opposite wo's transverse component), matching the
        # physical refraction direction for wo = (sin(theta_o), cos(theta_o), 0).
        wi_query[i] = [-np.sin(np.pi - thr), np.cos(thr), 0.0]
    pdf_vals = renderer.debug_bsdf_pdf_batch(mat_id, wo.tolist(), wi_query)
    pdf_peak_idx = np.argmax(pdf_vals)
    pdf_peak = thetas[pdf_peak_idx]

    return sample_peak, pdf_peak, n_live


@pytest.mark.parametrize("theta_deg,roughness,ior", [
    (45.0, 0.3, 1.5),   # the exact glass[0.3-45] chi2-gate config
])
def test_transmission_sample_pdf_peak_alignment(theta_deg, roughness, ior):
    """
    pkg149 gate: sample()'s transmission-direction density peak must land
    within PEAK_ALIGNMENT_TOLERANCE_DEG of pdf()'s peak, at N>=100k live
    in-plane samples. Pre-fix this was ~16-18 deg (152 vs 168-170); post-fix
    it must be <2 deg.
    """
    renderer = astroray.Renderer()
    mat_id = renderer.create_material(
        "disney", [1.0, 1.0, 1.0],
        {"metallic": 0.0, "roughness": roughness, "transmission": 1.0, "ior": ior},
    )
    theta_rad = np.deg2rad(theta_deg)
    wo = spherical_to_cartesian(theta_rad, 0.0)

    sample_peak, pdf_peak, n_live = _measure_peaks(
        renderer, mat_id, wo, theta_deg, ior, n_samples=300_000
    )
    assert n_live >= 100_000, f"N>=100k required by spec, got {n_live}"

    offset = abs(sample_peak - pdf_peak)
    print(
        f"\n[pkg149] glass[{roughness}-{int(theta_deg)}]: "
        f"sample peak={sample_peak:.2f} deg, pdf peak={pdf_peak:.2f} deg, "
        f"offset={offset:.2f} deg, N_live={n_live}"
    )
    assert offset < PEAK_ALIGNMENT_TOLERANCE_DEG, (
        f"Transmission sample/pdf peak offset {offset:.2f} deg exceeds "
        f"{PEAK_ALIGNMENT_TOLERANCE_DEG} deg gate "
        f"(sample_peak={sample_peak:.2f}, pdf_peak={pdf_peak:.2f}, N={n_live})"
    )
