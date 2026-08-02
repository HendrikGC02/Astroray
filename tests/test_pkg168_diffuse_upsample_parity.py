"""pkg168 Step 2 — diffuse RGB->spectral upsampling call-structure parity.

Step 1 proved the JH upsampling TABLES are bit-clean between CPU and GPU. Step 2
localized a CALL-STRUCTURE divergence: the GPU shaded a diffuse (Lambertian /
diffuse-only closure-graph) lobe by upsampling the pre-scaled RGB BSDF value
`albedo*cos/pi` (gpu_material_sample_spectral), whereas the CPU upsamples the
pure albedo COLOUR and applies `cos/pi` as a wavelength-flat scalar
(Lambertian::evalSpectral). Because Jakob-Hanika upsampling is nonlinear in
magnitude — upsample(k*c) != k*upsample(c) — the two legs produced different
spectrum SHAPES for the same colour; both integrate to the same XYZ, but the
mismatch bites once the throughput is multiplied by the next factor and
integrated, giving a chroma-dependent, per-bounce divergence (measured up to
2.5% per channel on a saturated diffuse sphere). Fix: upsample the reflectance
colour per-lambda, apply the geometric scalar (gpu_lambertian_eval_spectral) —
mirroring the pkg163 metal fix and the CPU oracle.

This gate renders saturated diffuse spheres on both backends and asserts the
per-channel GPU/CPU mean ratio is within 0.5%. It fails on the pre-fix build
(red ~0.975, blue ~1.019).

Skipped when no CUDA GPU is available.
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


def _has_cuda_gpu(renderer):
    return (
        bool(astroray.__features__.get("cuda", False))
        and bool(getattr(renderer, "gpu_available", False))
    )


def _render(use_gpu, albedo, bg, spp, depth, seed):
    r = astroray.Renderer()
    r.setup_camera(look_from=[0, 0, 4], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=4.0,
                   width=24, height=24)
    m = r.create_material("lambertian", albedo, {})
    r.add_sphere([0, 0, 0], 1.2, m)
    r.set_background_color(bg)
    if use_gpu:
        r.set_use_gpu(True)
    r.set_wavelength_range(380.0, 780.0)
    r.set_output_mode("")
    r.set_integrator("multiwavelength_path_tracer")
    r.set_seed(seed)
    return np.array(
        r.render(samples_per_pixel=spp, max_depth=depth, apply_gamma=False),
        dtype=np.float64).reshape(-1, 3)


# Saturated + neutral diffuse albedos; a saturated colour is where the JH
# magnitude-nonlinearity bites hardest. bg is a bright neutral illuminant so the
# lit sphere pixels dominate the mask.
CASES = [
    ("grey",  [0.5, 0.5, 0.5]),
    ("red",   [0.9, 0.1, 0.1]),
    ("green", [0.2, 0.55, 0.30]),
    ("blue",  [0.1, 0.1, 0.9]),
]


@pytest.mark.parametrize("name,albedo", CASES)
def test_diffuse_sphere_cpu_gpu_channel_parity(name, albedo):
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")
    bg = [1.0, 1.0, 1.0]
    cpu = _render(False, albedo, bg, spp=4096, depth=4, seed=42)
    gpu = _render(True,  albedo, bg, spp=4096, depth=4, seed=42)
    mask = cpu.min(axis=1) > 1e-3
    cm = cpu[mask].mean(axis=0)
    gm = gpu[mask].mean(axis=0)
    ratio = gm / cm
    print(f"pkg168 diffuse {name} albedo={albedo} GPU/CPU="
          f"[{ratio[0]:.5f},{ratio[1]:.5f},{ratio[2]:.5f}]")
    dev = float(np.max(np.abs(ratio - 1.0)))
    assert dev < 0.005, (
        f"{name} diffuse sphere GPU/CPU channel ratio {ratio} deviates "
        f"{dev*100:.2f}% > 0.5% — RGB->spectral upsample call-structure "
        f"divergence (pkg168 Step 2)."
    )
