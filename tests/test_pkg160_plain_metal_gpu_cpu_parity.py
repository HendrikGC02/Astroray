"""pkg160 — plain `metal` GPU(wavefront) <-> CPU render parity.

Why this file exists
--------------------
Plain `metal` shipped a 3.5x mean / 7x median GPU-vs-CPU brightness deficit
invisibly because it had NO parity gate at all. The only metal parity tests
were:

  * tests/test_pkg123_disney_metal_gpu_cpu_parity.py — *Disney* metal
    (gpu_disney_eval), a different function, and its band [0.4, 2.5] would not
    even have caught the 0.279 ratio;
  * tests/wavefront_diff/test_cpu_wavefront_metal_bit_identity.py — CPU
    wavefront vs CPU reference path tracer. Both call MetalPlugin, so it is
    bit-identical BY CONSTRUCTION and structurally blind to gpu_metal_eval.

This is the missing gate: GPU wavefront vs CPU, plain `metal`, across roughness.

Scene
-----
An albedo=[0.92,0.78,0.35] metal sphere that FILLS the frame inside a uniform
environment, with nothing else in the scene. Deliberate:

  * 100% metal coverage means no masking heuristic and no background pixels
    diluting the statistics (background pixels are identical on both backends
    and would drag every ratio toward 1.0, which is exactly how a
    whole-image mean hid this defect for so long);
  * a uniform environment lights the sphere at EVERY roughness including the
    near-delta mirror row, where a small area light would give a handful of
    hot pixels and nothing else.

Gate
----
Per channel, BOTH the mean ratio and the median ratio must land in
[0.95, 1.05] — except roughness 0.9, whose CEILING is 1.10 under an
owner-approved documented exception (see the RATIO_HIGH_ROUGHNESS_0_9 block
below for the measured value, the confirmed cause, the evidence, and why it is
a widened ceiling rather than an xfail). The floor is 0.95 at every roughness.

The median is not redundant: the original defect measured mean 0.279 but
median 0.141, i.e. the typical pixel was twice as wrong as the mean said, and a
mean-only gate near a bright highlight can mask exactly that.
Ratio-of-medians (not median-of-per-pixel-ratios) is used because the two
backends draw independent MC streams — a per-pixel quotient of two noisy
estimates is itself heavily skewed, whereas each backend's median is a stable
estimator of the same underlying quantity (memory
ssim-wrong-gate-for-independent-rng, same reasoning).

Roughness sweep {0.05, 0.15, 0.3, 0.6, 0.9}. 0.1 is deliberately NOT in the
sweep: it sits exactly on MetalPlugin::kNearDeltaThreshold, so it would pin
which side of a `<=` both implementations land on rather than pinning shading.
0.05 is the near-delta control row (perfect-mirror shortcut, byte-identical on
both sides and untouched by pkg160); the other four exercise the rough branch.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg160 plain-metal GPU/CPU parity "
        "needs the RTX box.",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 4
SEED = 160160

# The disney_contact_sheet plain-metal patch colour, i.e. the material the
# 0.279/0.286/0.316 deficit was originally measured on.
ALBEDO = [0.92, 0.78, 0.35]
BACKGROUND = [0.35, 0.45, 0.60]

ROUGHNESS_SWEEP = [0.05, 0.15, 0.3, 0.6, 0.9]

# Tightened band, proposed by the pkg160 spec and adopted by the owner. The
# only pre-existing plain-metal-adjacent bands are Disney's [0.4, 2.5]
# (pkg123), which is far too loose to see this class of defect. For reference,
# the same-scene-controlled scan that found pkg160 measured dielectric at
# 0.9987-0.9999 and diffuse_light at 0.9987-1.0007 on the wavefront, so
# [0.95, 1.05] is what a genuinely matched material looks like here.
RATIO_LOW = 0.95
RATIO_HIGH = 1.05

# ---------------------------------------------------------------------------
# DOCUMENTED EXCEPTION at roughness 0.9 (owner-approved, PR #527, 2026-07-26)
# ---------------------------------------------------------------------------
# The first RTX 5070 Ti run of this gate measured 31/32 assertions inside
# [0.95, 1.05]. The one outside was roughness 0.9, channel B: **1.0722**.
# Full sweep, GPU/CPU mean ratio:
#
#     roughness      R        G        B
#     0.05        0.9998   1.0000   0.9977
#     0.15        1.0174   0.9863   1.0133
#     0.30        1.0052   0.9980   1.0040
#     0.60        1.0247   0.9964   1.0288
#     0.90        1.0393   1.0137   1.0722   <- this row
#
# CAUSE — pre-existing architecture that pkg160 EXPOSED, not introduced.
# CPU MetalPlugin::evalSpectral applies the compensation PER WAVELENGTH, from
# Fss = albedo_spec_.sample(lambdas) (the Jakob-Hanika upsample of the albedo);
# GPU gpu_metal_eval applies it PER RGB CHANNEL from mat.baseColor and then
# upsamples the product. The two agree exactly only for a flat (achromatic)
# spectrum. This is the same class of CPU-spectral/GPU-RGB difference the
# Fresnel term in these two functions has always had; pkg160 simply put a
# second, roughness-amplified factor through the same seam.
#
# EVIDENCE it is the upsampler and not a missing/incorrect term (team-lead,
# three isolations on hardware, PR #527):
#   1. r=0.05 sits at 0.9977-1.0000 — the near-delta branch where the
#      compensation is inert. A missing or wrong term would diverge there too.
#   2. Neutral albedo [0.35,0.35,0.35] collapses the per-channel spread 25x
#      (0.0589 -> 0.0023).
#   3. Decisive: neutral [0.35,0.35,0.35] gives B = 1.0074, while chromatic
#      [0.92,0.78,0.35] — the SAME B value — gives B = 1.0743. Ten times the
#      divergence with the only variable being whether the OTHER channels
#      differ. That is a spectral-upsampling signature and nothing else.
# Camera framing is the amplifier: the same material at a far camera measures
# R/G/B = 1.0052/1.0025/1.0056. This test's close 60-degree framing is
# grazing-dominated, which is where the two upsampling orders diverge most.
# The chromatic background contributes only ~0.3%.
#
# WHY A WIDENED CEILING AND NOT AN xfail. An xfail would make ANY future
# regression at r=0.9 invisible, and the repo already carries non-strict
# xfails that assert nothing. 1.0722 against a 1.10 ceiling leaves ~3%
# headroom, so a genuine regression beyond the known divergence STILL FAILS.
# That is the difference between an exception and a hole. The floor is NOT
# widened: the divergence is one-directional (GPU brighter), so a GPU-dim
# regression must still trip at 0.95.
#
# FOLLOW-UP: the architect filed a package for the CPU-spectral vs GPU-RGB
# compensation mismatch off this gate run (see PR #527's HW-gate comment
# thread for the measurements above). When that lands, delete this exception
# and put r=0.9 back on RATIO_HIGH.
RATIO_HIGH_ROUGHNESS_0_9 = 1.10


def _band(roughness: float) -> tuple[float, float]:
    """Per-roughness acceptance band. See the exception block above: only the
    r=0.9 CEILING is relaxed, and only to 1.10."""
    if roughness == 0.9:
        return RATIO_LOW, RATIO_HIGH_ROUGHNESS_0_9
    return RATIO_LOW, RATIO_HIGH


def _make_metal_scene(use_gpu: bool, roughness: float):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    metal = r.create_material("metal", ALBEDO, {"roughness": roughness})
    r.add_sphere([0.0, 0.0, 0.0], 0.9, metal)
    # Camera at 1.35 with a 60 deg vertical fov: the sphere's angular radius
    # (asin(0.9/1.35) = 41.8 deg) exceeds the frame corner (39.2 deg), so the
    # sphere covers every pixel. Verified: 0 background pixels at every
    # roughness in the sweep.
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, WIDTH / HEIGHT, 0.0, 1.35, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(use_gpu: bool, roughness: float) -> np.ndarray:
    r = _make_metal_scene(use_gpu=use_gpu, roughness=roughness)
    r.set_seed(SEED)
    # 4th positional arg is applyGamma -- False keeps both sides linear
    # (memory gamma-vs-linear-comparison-artifact).
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float64)


@pytest.mark.parametrize("roughness", ROUGHNESS_SWEEP)
def test_plain_metal_gpu_cpu_parity(roughness):
    gpu = _render(use_gpu=True, roughness=roughness)
    cpu = _render(use_gpu=False, roughness=roughness)

    assert gpu.shape == (HEIGHT, WIDTH, 3)
    assert cpu.shape == (HEIGHT, WIDTH, 3)
    assert np.all(np.isfinite(gpu)), "GPU render produced NaN/Inf"
    assert np.all(np.isfinite(cpu)), "CPU render produced NaN/Inf"

    # Coverage guard: a pixel that missed the sphere would be exactly the
    # background colour, and background pixels would bias every ratio toward
    # 1.0. If the camera/sphere framing ever drifts, fail loudly rather than
    # silently weakening the gate.
    missed = int(np.sum(np.all(np.isclose(cpu, np.array(BACKGROUND), atol=1e-6),
                               axis=-1)))
    assert missed == 0, (
        f"{missed} pixels missed the metal sphere; the gate's statistics are "
        "only meaningful at full coverage -- re-check the camera framing"
    )

    rows = []
    for c, ch in enumerate("RGB"):
        cpu_mean, gpu_mean = float(cpu[..., c].mean()), float(gpu[..., c].mean())
        cpu_med = float(np.median(cpu[..., c]))
        gpu_med = float(np.median(gpu[..., c]))
        rows.append((ch, cpu_mean, gpu_mean, gpu_mean / cpu_mean,
                     cpu_med, gpu_med, gpu_med / cpu_med))

    low, high = _band(roughness)
    exception = " (r=0.9 documented exception, see module header)" if high != RATIO_HIGH else ""

    print(f"\n[pkg160 plain-metal GPU/CPU parity] roughness={roughness} "
          f"band=[{low}, {high}]{exception}")
    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        print(f"  {ch}: mean cpu={cm:.5f} gpu={gm:.5f} ratio={mr:.4f} | "
              f"median cpu={cmed:.5f} gpu={gmed:.5f} ratio={medr:.4f}")

    for ch, cm, gm, mr, cmed, gmed, medr in rows:
        assert low <= mr <= high, (
            f"pkg160 plain-metal GPU/CPU MEAN parity FAILED at "
            f"roughness={roughness}, channel {ch}: ratio {mr:.4f} outside "
            f"[{low}, {high}] (cpu={cm:.5f}, gpu={gm:.5f}){exception}"
        )
        assert low <= medr <= high, (
            f"pkg160 plain-metal GPU/CPU MEDIAN parity FAILED at "
            f"roughness={roughness}, channel {ch}: ratio {medr:.4f} outside "
            f"[{low}, {high}] (cpu={cmed:.5f}, gpu={gmed:.5f}){exception}. "
            f"The median is the statistic that exposed this defect: the "
            f"original measurement was mean 0.279 but median 0.141."
        )
