"""pkg168 Step 1 — CPU<->GPU RGB->spectral upsampling parity A/B.

Unit-level A/B of the per-wavelength upsampled reflectance the two backends
fill each SampledSpectrum slot with:

* CPU: astroray._cpu_rgb_upsample_batch -> RGBAlbedoSpectrum/RGBIlluminantSpectrum
       ::evalAt (src/spectrum.cpp).
* GPU: Renderer._gpu_rgb_upsample_batch -> gpu_rgbSpectrumAt (gpu_materials.h),
       the exact scalar gpu_rgbToSampledSpectrum writes per sample.

The grid uses the pkg156 naive-scene albedos + primaries + neutral greys over a
dense visible lambda grid. If the two tables agree at unit level (float
precision), the [1.014, 1.007, 1.014] render-level ratio cannot originate here
and the fork routes to call-structure (pkg163 class rule). A systematic,
channel-correlated per-lambda divergence instead convicts the tables.

Skipped when no CUDA GPU is available (the GPU dump needs the device).
"""

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

MODE_ALBEDO = 1
MODE_ILLUMINANT = 2

# pkg156 naive scene (tests/scenes/multiwavelength_parity.py) albedos, plus
# sRGB primaries and a neutral-grey ramp that spans the LUT's z (max-channel)
# axis and its x/y (chroma) plane.
ALBEDO_POINTS = [
    ("veg",    [0.20, 0.55, 0.30]),
    ("water",  [0.05, 0.10, 0.18]),
    ("metal",  [0.85, 0.85, 0.88]),
    ("red",    [1.00, 0.00, 0.00]),
    ("green",  [0.00, 1.00, 0.00]),
    ("blue",   [0.00, 0.00, 1.00]),
    ("grey05", [0.05, 0.05, 0.05]),
    ("grey18", [0.18, 0.18, 0.18]),
    ("grey50", [0.50, 0.50, 0.50]),
    ("grey85", [0.85, 0.85, 0.85]),
    ("white",  [1.00, 1.00, 1.00]),
]

# ILLUMINANT points: the scene light + background tint + neutral greys.
ILLUMINANT_POINTS = [
    ("light",   [1.00, 1.00, 1.00]),
    ("bg_tint", [0.05, 0.05, 0.07]),
    ("grey18",  [0.18, 0.18, 0.18]),
    ("grey50",  [0.50, 0.50, 0.50]),
]

LAMBDAS = [380.0 + 5.0 * k for k in range(81)]  # 380..780 nm, 5 nm step


def _has_cuda_gpu(renderer):
    return (
        bool(astroray.__features__.get("cuda", False))
        and bool(getattr(renderer, "gpu_available", False))
    )


def _ab(points, mode):
    """Return (names, cpu[n,m], gpu[n,m]) over the lambda grid."""
    rgbs = []
    names = []
    for name, rgb in points:
        names.append(name)
        rgbs.extend(rgb)
    cpu = np.array(astroray._cpu_rgb_upsample_batch(rgbs, LAMBDAS, mode),
                   dtype=np.float64).reshape(len(points), len(LAMBDAS))
    renderer = astroray.Renderer()
    gpu = np.array(renderer._gpu_rgb_upsample_batch(rgbs, LAMBDAS, mode),
                   dtype=np.float64).reshape(len(points), len(LAMBDAS))
    return names, cpu, gpu


def _rel(cpu, gpu):
    denom = np.maximum(np.abs(cpu), 1e-6)
    return np.abs(gpu - cpu) / denom


def _report(tag, names, cpu, gpu):
    rel = _rel(cpu, gpu)
    ratios = []
    print(f"\n=== pkg168 Step 1 A/B: {tag} ===")
    print(f"{'point':<8} {'maxRel':>10} {'meanRel':>10} "
          f"{'cpuMean':>10} {'gpuMean':>10} {'meanRatio':>10}")
    for i, name in enumerate(names):
        cmean = cpu[i].mean()
        gmean = gpu[i].mean()
        ratio = gmean / cmean if abs(cmean) > 1e-12 else float("nan")
        ratios.append(ratio)
        print(f"{name:<8} {rel[i].max():>10.3e} {rel[i].mean():>10.3e} "
              f"{cmean:>10.5f} {gmean:>10.5f} {ratio:>10.6f}")
    print(f"{tag} overall maxRel={rel.max():.3e} meanRel={rel.mean():.3e}")
    return rel.mean(), np.array(ratios)


# The render-relevant quantity is the band-integrated mean ratio per point (what
# actually scales a channel), NOT the worst single-lambda relative error: a
# fully-saturated primary (e.g. green [0,1,0]) has a near-zero sigmoid value at
# one edge wavelength where fma ordering inflates the relative error to ~2e-4
# while contributing nothing to any integrated channel. The fork discriminator
# is whether the tables reproduce the render-level [1.014,1.007,1.014] signature:
# a mean ratio within ~1e-3 of unity means they do NOT (tables clean -> the gap
# is in the call structure, pkg163 class rule).
RATIO_TOL = 1e-3
MEANREL_TOL = 1e-4


def test_pkg168_step1_albedo_parity():
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")
    names, cpu, gpu = _ab(ALBEDO_POINTS, MODE_ALBEDO)
    mean_rel, ratios = _report("ALBEDO", names, cpu, gpu)
    worst = float(np.max(np.abs(ratios - 1.0)))
    assert worst < RATIO_TOL, (
        f"ALBEDO band-integrated mean ratio deviates {worst:.3e} >= {RATIO_TOL} "
        f"from unity — tables DIVERGE, convict the source (see step1 note)."
    )
    assert mean_rel < MEANREL_TOL, (
        f"ALBEDO overall meanRel {mean_rel:.3e} >= {MEANREL_TOL}."
    )


def test_pkg168_step1_illuminant_parity():
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")
    names, cpu, gpu = _ab(ILLUMINANT_POINTS, MODE_ILLUMINANT)
    mean_rel, ratios = _report("ILLUMINANT", names, cpu, gpu)
    worst = float(np.max(np.abs(ratios - 1.0)))
    assert worst < RATIO_TOL, (
        f"ILLUMINANT band-integrated mean ratio deviates {worst:.3e} >= "
        f"{RATIO_TOL} from unity — tables DIVERGE (see step1 note)."
    )
    assert mean_rel < MEANREL_TOL, (
        f"ILLUMINANT overall meanRel {mean_rel:.3e} >= {MEANREL_TOL}."
    )
