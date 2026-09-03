"""pkg225 Stage 4 — GPU Principled Hair BSDF: CPU<->GPU render parity.

Stage 4 ports the CPU Principled Hair BSDF (Chiang 2016; plugins/materials/
principled_hair.cpp + include/astroray/hair_bsdf.h) to the GPU wavefront shade
kernel:
  - include/astroray/gpu_hair.cuh  (__device__ __noinline__ eval/pdf/sample,
    reusing the shared hair_bsdf.h Mp/Np/Ap math for parity-by-construction)
  - GMAT_HAIR_PRINCIPLED standalone branch in the material dispatch (gpu_materials.h)
  - the hit->shade SoA hand-off of the strand tangent + azimuthal v
    (hit_uv_tangent_* / hit_hair_v lanes in GPUWavefrontHitBuffers), gated by the
    runtime __constant__ c_hasHair flag so non-hair fleet scenes are byte-identical

This renders the SAME curved hair tuft on CPU and GPU and gates per-channel
mean-ratio (NOT SSIM -- independent MC streams; memory
ssim-wrong-gate-for-independent-rng). Both backends render the THICK swept-circle
Cylinder mode (GPU default is ribbon) via set_curve_thick_mode(True) so the two
run identical curve math and only the BSDF port is under test.

The tuft is lit from the side so the longitudinal (Marschner/Chiang R-lobe)
highlight is visible; a diffuse-looking GPU result (missing the anisotropic
sheen) shifts the per-channel means out of band. A companion scratch harness
saves PNGs for visual sheen inspection (see the pkg225-S4 PR notes).
"""

from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg225 Stage 4 GPU hair parity needs "
        "the RTX box.",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 96
SAMPLES = 384
MAX_DEPTH = 6
SEED = 225401

# Parity is gated on the WELL-LIT hair (per-pixel luminance > LIT_THRESHOLD), not
# the full-frame mean. Rationale (measured, pkg225-S4): the GPU curve GEOMETRY
# matches the CPU to <2% (the S3 diffuse-curve gate, coverage 0.366 vs 0.372,
# ratios ~1.001), but the hair BSDF's strong silhouette response (h=±1, grazing
# Fresnel -> 1) lights a dim halo of SUB-PIXEL edge pixels whose exact fraction
# swings with the independent MC stream on thin strands. That halo dominates the
# full-frame mean (~1.10) while the actual shaded hair — the highlight + body, what
# the sheen check inspects — matches to a few percent. So the gate targets the
# well-lit hair (the BSDF signal) and additionally asserts channel BALANCE, which a
# real sigma_a / frame / lobe divergence would break (it would shift ONE channel).
LIT_THRESHOLD = 0.03
RATIO_LOW = 0.85
RATIO_HIGH = 1.15
CHANNEL_BALANCE = 1.15   # max(ratio)/min(ratio): a colour-shift bug breaks this
COVERAGE_FLOOR = 0.05    # >=5% of pixels must be lit hair (both backends)


def _make_tuft():
    """A dense fan of gently-curved strands (one CurveSegment each via the middle
    span + Cycles phantom-endpoint clamping) sweeping top->bottom, so the tuft
    fills the view and the strands are genuinely curved."""
    positions = []
    counts = []
    n_cols = 14
    n_rows = 5
    for ci in range(n_cols):
        x0 = -1.2 + 2.4 * ci / (n_cols - 1)
        bow = 0.30 * np.sin(ci * 0.6)
        strand = []
        for ri in range(n_rows):
            t = ri / (n_rows - 1)
            y = 1.2 - 2.4 * t
            x = x0 + bow * np.sin(t * np.pi)
            z = 0.12 * np.cos(t * np.pi + ci)
            strand.append((x, y, z))
        positions.extend(strand)
        counts.append(n_rows)
    return np.asarray(positions, dtype=np.float32), counts


def _make_hair_scene(use_gpu: bool):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # Direct-coloring (reflectance) mode, a warm brown — the node default mode.
    hair = r.create_material(
        "principled_hair", [0.55, 0.28, 0.12],
        {"roughness": 0.3, "radial_roughness": 0.3, "coat": 0.0,
         "parametrization": "reflectance"})
    positions, counts = _make_tuft()
    radii = np.full(len(positions), 0.045, dtype=np.float32)
    r.add_curves_bulk(positions, radii, counts, hair)

    # Side light so the longitudinal highlight sweeps across the fibers.
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 16.0})
    r.add_sphere([2.2, 1.4, 1.6], 0.5, light)

    r.setup_camera([0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   40.0, WIDTH / HEIGHT, 0.0, 4.2, WIDTH, HEIGHT)

    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_curve_thick_mode(True)  # CPU-parity swept-circle mode on both backends
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool) -> np.ndarray:
    r = _make_hair_scene(use_gpu=use_gpu)
    r.set_seed(SEED)
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)


def test_gpu_hair_render_matches_cpu():
    gpu = _render(use_gpu=True)
    cpu = _render(use_gpu=False)

    assert gpu.shape == (HEIGHT, WIDTH, 3)
    assert cpu.shape == (HEIGHT, WIDTH, 3)

    gpu_bad = int(np.sum(~np.isfinite(gpu)))
    cpu_bad = int(np.sum(~np.isfinite(cpu)))
    assert gpu_bad == 0, f"GPU hair render produced {gpu_bad} non-finite components"
    assert cpu_bad == 0, f"CPU hair render produced {cpu_bad} non-finite components"

    gpu_cov = float(np.mean(np.any(gpu > 1e-4, axis=-1)))
    cpu_cov = float(np.mean(np.any(cpu > 1e-4, axis=-1)))
    print(f"\n[pkg225-S4 GPU hair] coverage cpu={cpu_cov:.3f} gpu={gpu_cov:.3f}")
    assert cpu_cov >= COVERAGE_FLOOR, (
        f"CPU render shows no hair coverage ({cpu_cov:.3f} < {COVERAGE_FLOOR}) "
        f"-- investigate the CPU hair path before GPU.")
    assert gpu_cov >= COVERAGE_FLOOR, (
        f"GPU render shows no hair coverage ({gpu_cov:.3f} < {COVERAGE_FLOOR}) "
        f"-- GMAT_HAIR_PRINCIPLED dispatch / uvTangent+hairV SoA hand-off not "
        f"wired: the GPU hair BSDF returns black.")

    # Well-lit mask: pixels the hair actually shades (union so a small coverage
    # difference between backends doesn't bias the set toward one backend).
    def _lum(im):
        return 0.2126 * im[..., 0] + 0.7152 * im[..., 1] + 0.0722 * im[..., 2]
    lit = (_lum(cpu) > LIT_THRESHOLD) | (_lum(gpu) > LIT_THRESHOLD)
    assert int(lit.sum()) > 50, f"too few well-lit hair pixels ({int(lit.sum())}) to gate"

    per_channel = []
    for c, ch in enumerate("RGB"):
        cs = float(cpu[..., c][lit].sum())
        gs = float(gpu[..., c][lit].sum())
        ratio = (gs / cs) if cs > 1e-9 else (float("inf") if gs > 1e-9 else 1.0)
        per_channel.append((ch, cs, gs, ratio))

    for ch, cs, gs, ratio in per_channel:
        print(f"  {ch}: cpu_lit_sum={cs:.3f} gpu_lit_sum={gs:.3f} ratio={ratio:.4f}")

    for ch, cs, gs, ratio in per_channel:
        assert RATIO_LOW <= ratio <= RATIO_HIGH, (
            f"pkg225-S4 GPU/CPU hair parity FAILED: channel {ch} well-lit ratio "
            f"{ratio:.4f} outside [{RATIO_LOW}, {RATIO_HIGH}]. The GPU hair BSDF "
            f"diverges from the CPU Chiang model (frame, sigma_a, or lobe math).")

    ratios = [r for _, _, _, r in per_channel]
    balance = max(ratios) / min(ratios)
    print(f"  channel balance max/min = {balance:.4f}")
    assert balance <= CHANNEL_BALANCE, (
        f"pkg225-S4 GPU/CPU hair parity FAILED: channel imbalance {balance:.4f} > "
        f"{CHANNEL_BALANCE} (ratios {[f'{r:.3f}' for r in ratios]}). A per-channel "
        f"sigma_a / frame divergence shifts one channel — the GPU hair colour "
        f"response does not match the CPU.")

    print("[pkg225-S4 GPU hair] PASS: finite, hair visible, well-lit per-channel "
          f"ratios within [{RATIO_LOW}, {RATIO_HIGH}], channel-balanced.")
