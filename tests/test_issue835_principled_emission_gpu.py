"""#835: native Principled emission on the GPU wavefront (CPU<->GPU parity).

The GPU never read GPrincipledClosure::emission*: gpu_material_emitted summed
only GCLOSURE_EMISSION closures, so an emissive Principled surface rendered
unlit on the GPU (F12 and viewport) while the CPU lit it. Fixed in
gpu_materials.h (gpu_principled_emitted + illuminant upsampling).

Per-channel mean-ratio parity (independent RNG streams; memory
ssim-wrong-gate-for-independent-rng), linear output (4th render arg False).
Cases: directly visible white and coloured emission (camera-ray hit, illuminant
upsampling above 1), and a Principled quad lighting a diffuse sphere (NEE).
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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip("CUDA feature not in this build", allow_module_level=True)

W = H = 48
SPP = 256
DEPTH = 6
SEED = 835835
BAND = (0.95, 1.05)


def _has_gpu():
    try:
        return bool(astroray.Renderer().gpu_available)
    except (RuntimeError, AttributeError):
        return False


def _renderer(use_gpu):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(SEED)
    return r


def _self_emission(use_gpu, emission_color, strength):
    r = _renderer(use_gpu)
    m = r.create_material("principled", [0.0, 0.0, 0.0],
                          {"emission_color": emission_color,
                           "emission_strength": strength})
    r.add_sphere([0.0, 0.0, 0.0], 0.9, m)
    # Sphere fills the frame (pkg160 framing): no background pixels.
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, 1.0, 0.0, 1.35, W, H)
    return np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float64)


def _quad_lit(use_gpu):
    r = _renderer(use_gpu)
    lamp = r.create_material("principled", [0.0, 0.0, 0.0],
                             {"emission_color": [1.0, 0.8, 0.5],
                              "emission_strength": 8.0})
    # Downward-facing quad above the sphere (winding -> normal -y).
    r.add_triangle([-1, 2.5, -1], [1, 2.5, -1], [1, 2.5, 1], lamp)
    r.add_triangle([-1, 2.5, -1], [1, 2.5, 1], [-1, 2.5, 1], lamp)
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, white)
    r.setup_camera([0.0, 0.0, 3.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   45.0, 1.0, 0.0, 3.2, W, H)
    return np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float64)


def _assert_parity(label, cpu, gpu):
    assert np.all(np.isfinite(gpu)), "GPU render produced NaN/Inf"
    print(f"\n[#835 principled emission GPU/CPU] {label}")
    for c, ch in enumerate("RGB"):
        cm, gm = float(cpu[..., c].mean()), float(gpu[..., c].mean())
        ratio = gm / cm if cm > 1e-8 else float("nan")
        print(f"  {ch}: cpu={cm:.5f} gpu={gm:.5f} ratio={ratio:.4f}")
        assert BAND[0] <= ratio <= BAND[1], (
            f"{label} channel {ch}: GPU/CPU {ratio:.4f} outside {BAND} "
            f"(cpu={cm:.5f}, gpu={gm:.5f})")


@pytest.mark.parametrize("label,color,strength", [
    ("white_x5", [1.0, 1.0, 1.0], 5.0),
    ("green_x3", [0.2, 1.0, 0.3], 3.0),
])
def test_principled_self_emission_gpu_matches_cpu(label, color, strength):
    if not _has_gpu():
        pytest.skip("no CUDA device")
    cpu = _self_emission(False, color, strength)
    gpu = _self_emission(True, color, strength)
    # Pre-fix the GPU returned ~0 here (emission never read).
    assert gpu.mean() > 0.5 * cpu.mean() > 0.0
    _assert_parity(label, cpu, gpu)


def test_principled_emitter_lights_scene_gpu_matches_cpu():
    if not _has_gpu():
        pytest.skip("no CUDA device")
    cpu = _quad_lit(False)
    gpu = _quad_lit(True)
    assert cpu.mean() > 1e-3
    _assert_parity("quad_nee", cpu, gpu)
