#!/usr/bin/env python
"""pkg223 — GPU tangent-space normal maps: visible relief, Strength, CPU/GPU parity.

The addon already exports a normal map (normal_map_texture + normal_strength) and
the CPU `NormalMappedPlugin` decodes it, but the GPU wavefront dropped it: a
NormalMapped decorator is a CPU shared_ptr wrapper that does not survive GMaterial
upload, so a normal-mapped material rendered flat on the device. pkg223 uploads the
normal texture on the c_wfTexBinding side arrays (matNormalTexId/matNormalStrength)
and perturbs the shading normal in the wavefront shade stage behind
`template<bool HasNormalPerturb>` — so scenes without a normal map stay
byte-identical (register-probe gate) and pay zero cost.

Decode mirrors the CPU oracle exactly (Cycles svm_node_normal_map, cite note
.astroray_plan/docs/pkg223-normal-map-research.md):
    n_ts   = 2*rgb - 1
    B      = uvBitangentSign * cross(N, uvTangent)         # Mikk-TSpace handedness
    mapped = normalize(T*n_ts.x + B*n_ts.y + N*n_ts.z)     # UV-aligned frame
    n      = normalize(lerp(N, mapped, clamp(strength,0,1)))

A Lambertian's shading is invisible to normal perturbation under a UNIFORM world
(it integrates the normal away), so the scene uses a BLACK world + a single grazing
sun: the diffuse response is then ~ albedo * max(0, N.L), directly sensitive to the
mapped normal's direction.

GPU-gated: skips when no CUDA device (CI has none); this is an RTX-box leg.
"""

import math

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _norm(v):
    v = np.asarray(v, np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _normal_image(nx, ny, nz):
    """A constant 2x2 tangent-space normal texture encoding (nx,ny,nz) normalized:
    rgb = n_ts*0.5 + 0.5. The identity (0,0,1) -> (0.5,0.5,1.0) = geometric normal."""
    v = np.asarray([nx, ny, nz], np.float32)
    v = v / np.linalg.norm(v)
    rgb = (v * 0.5 + 0.5).astype(np.float32)
    img = np.empty((2, 2, 3), np.float32)
    img[:] = rgb
    return img


# A strong tangent-space tilt toward +U (~45 deg): with the UVMap below, +U maps to
# world +x, and the grazing sun comes from +x, so the tilt swings N.L hard vs flat.
_TILT = (0.7071, 0.0, 0.7071)


def _build(renderer, normal=None, strength=1.0):
    renderer.set_background_color([0.0, 0.0, 0.0])  # sun-only lighting
    params = {}
    if normal is not None:
        renderer.load_texture("pkg223_nrm", _normal_image(*normal), 2, 2, "UV")
        params["normal_map_texture"] = "pkg223_nrm"
        params["normal_strength"] = float(strength)
    mat = renderer.create_material("lambertian", [0.8, 0.8, 0.8], params)

    # Quad at z=0, geometric normal +z; UVMap makes +U -> world +x, +V -> world +y.
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)

    # Grazing sun coming from +x and slightly in front (travel dir toward -x,-z),
    # so a +U(+x)-tilted normal faces INTO the light and brightens vs the flat quad.
    ang = 0.02
    omega = 2.0 * math.pi * (1.0 - math.cos(ang * 0.5))
    renderer.add_sun_light_dedicated(_norm([-1.0, 0.0, -0.4]), ang,
                                     {"mode": "rgb", "color": [1.0, 1.0, 1.0]},
                                     3.0)

    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(normal=None, strength=1.0, use_gpu=False, samples=96):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg223 normal-map gate runs on the RTX box.")
        r.set_use_gpu(True)
    _build(r, normal=normal, strength=strength)
    return render_image(r, samples=samples, max_depth=2, apply_gamma=False)


def _mean(img):
    return float(np.asarray(img).mean())


def test_gpu_normal_map_visible_relief():
    """A GPU render with the tilted normal map must differ substantially from the
    same quad with NO normal map (geometric normal) — proof the map is applied on
    the device rather than dropped."""
    mapped = _render(normal=_TILT, strength=1.0, use_gpu=True)
    flat = _render(normal=None, use_gpu=True)
    mean_abs_diff = float(np.abs(np.asarray(mapped) - np.asarray(flat)).mean())
    assert _mean(flat) > 0.02, f"flat render too dark to gate ({_mean(flat):.4f})"
    assert mean_abs_diff > 0.03, (
        f"GPU normal-mapped render too close to flat (mean|diff|={mean_abs_diff:.4f}); "
        f"the normal map was likely dropped on GPU."
    )


def test_gpu_normal_strength_monotonic():
    """Strength 0 ~= flat (geometric normal); |effect| grows monotonically with
    Strength. Sign-agnostic so it does not depend on the exact light geometry."""
    flat = _mean(_render(normal=None, use_gpu=True))
    s0 = _mean(_render(normal=_TILT, strength=0.0, use_gpu=True))
    s05 = _mean(_render(normal=_TILT, strength=0.5, use_gpu=True))
    s1 = _mean(_render(normal=_TILT, strength=1.0, use_gpu=True))
    # Strength 0 collapses the lerp to the geometric normal.
    assert abs(s0 - flat) < 0.015, (
        f"Strength 0 should match the flat render (s0={s0:.4f}, flat={flat:.4f})"
    )
    d05, d1 = s05 - flat, s1 - flat
    assert abs(d1) > 0.02, f"Strength 1 shows no relief (d1={d1:.4f})"
    # Same direction, and full strength moves further than half.
    assert (d05 == 0.0) or (np.sign(d05) == np.sign(d1)), (
        f"Strength 0.5 and 1.0 perturb in opposite directions (d05={d05:.4f}, d1={d1:.4f})"
    )
    assert abs(d1) > abs(d05) + 0.005, (
        f"effect not monotonic in Strength (|d05|={abs(d05):.4f}, |d1|={abs(d1):.4f})"
    )


def test_cpu_gpu_normal_map_parity():
    """Per-channel mean-ratio of the CPU oracle vs GPU normal-mapped render within
    band — the GPU decode + UV-aligned TBN must byte-mirror NormalMappedPlugin."""
    gpu = _render(normal=_TILT, strength=1.0, use_gpu=True)
    cpu = _render(normal=_TILT, strength=1.0, use_gpu=False)
    gm = np.array([float(np.asarray(gpu)[..., c].mean()) for c in range(3)])
    cm = np.array([float(np.asarray(cpu)[..., c].mean()) for c in range(3)])
    assert cm.mean() > 0.02, f"CPU reference too dark to gate: {cm}"
    assert gm.mean() > 0.02, f"GPU render too dark to gate: {gm}"
    ratio = gm / np.maximum(cm, 1e-6)
    for c, rc in enumerate(ratio):
        assert 0.80 <= rc <= 1.25, (
            f"channel {c} CPU/GPU mean-ratio {rc:.3f} out of band [0.80,1.25]; "
            f"cpu={cm}, gpu={gm}"
        )
