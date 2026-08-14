"""pkg199 Stage 2 (GPU) — dedicated volume-scatter wavefront stage parity oracle.

Stage 2 mirrors the CPU homogeneous scattering medium (HG in-scatter, exponential
free-flight distance sampling, NEE-through-medium) on the GPU wavefront via a
DEDICATED stageVolumeScatterKernel scheduled between intersect and shade. The
free-flight scatter DECISION lives in intersectPathSlot (gated on the same
mediumScatters = hasVolume && density>0 && scatter>0 condition as the CPU, so
α=0 is byte-identical Stage-1); scattered slots route to a volume queue that the
new kernel drains (phase NEE parked into the shared nee/shadow lanes; HG
continuation requeued). stageShadeBucketedKernel is untouched → byte-identical.

Gates (GPU legs skip when CUDA is absent; /verify runs them on the RTX):
  * α=0 GPU INERTNESS — a scatter=0 GPU render reproduces Stage-1 absorption
    (darkens with density, NO god-ray brightening); the scattering estimator is
    not engaged (the -2 volume route never fires).
  * CPU↔GPU GOD-RAY PARITY — a scattering point-light-in-fog scene: per-channel
    CPU↔GPU mean-ratio within the independent-MC band (NOT SSIM, NOT bit-exact;
    the wavefront has a ~2e-7 atomic floor — memory ssim-wrong-gate-for-independent-rng).
  * FORWARD/BACK on GPU — g>0 (light behind fog) must out-scatter g<0 on the GPU too.
  * VISUAL — god-ray PNGs saved for the mandatory human/parent inspection.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

from base_helpers import save_image

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

SEED = 199223
W = H = 64


def _gpu_available() -> bool:
    return AVAILABLE and astroray.__features__.get("cuda", False) \
        and astroray.Renderer().gpu_available


@pytest.fixture
def test_results_dir():
    d = os.path.join(os.path.dirname(__file__), "..", "test_results")
    os.makedirs(d, exist_ok=True)
    return os.path.abspath(d)


def _godray_scene(use_gpu: bool, density: float, scatter: float, g: float,
                  w: int = W, h: int = H):
    """A point light embedded in scattering fog, viewed so the shafts cross the
    frame. Grey medium so the per-channel machinery collapses cleanly."""
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.0, 0.0, 0.0])
    if density > 0.0:
        r.set_world_volume(density, [1.0, 1.0, 1.0], g, scatter)
    r.add_point_light([0.0, 0.0, -3.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 90.0)
    # A diffuse floor to catch shafts and give a multi-object GI path through fog.
    floor = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    r.add_sphere([0.0, -1001.0, -3.0], 1000.0, floor)
    r.setup_camera([0.0, 0.6, 6.0], [0.0, 0.0, -3.0], [0.0, 1.0, 0.0],
                   40.0, w / h, 0.0, 9.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 5)
    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    return r


def _render(r, spp=256, max_depth=5, w=W, h=H):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _means(img):
    return np.array([float(img[..., c].mean()) for c in range(3)])


# ---------------------------------------------------------------------------
# α=0 GPU INERTNESS — scatter=0 reproduces Stage-1 absorption (no god-rays).
# ---------------------------------------------------------------------------

def test_alpha_zero_gpu_is_absorption():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available")
    clear = _means(_render(_godray_scene(True, 0.0, 0.0, 0.0)))
    foggy = _means(_render(_godray_scene(True, 0.12, 0.0, 0.0)))   # α=0
    print(f"\n[pkg199-s2 GPU α=0] clear={np.round(clear,4)} foggy={np.round(foggy,4)}")
    # Absorption only: foggy must not EXCEED clear (a god-ray leak at α=0 would
    # brighten — the scattering estimator must be gated off).
    assert foggy.mean() <= clear.mean() * 1.03, (
        f"α=0 GPU ADDED energy ({foggy.mean():.4f} > {clear.mean():.4f}) — "
        f"scattering leaked into the absorption limit (mediumScatters gate broken)")
    assert foggy.mean() < clear.mean() * 0.99, (
        f"α=0 GPU fog produced no attenuation ({foggy.mean():.4f} vs {clear.mean():.4f})")


# ---------------------------------------------------------------------------
# CPU↔GPU GOD-RAY PARITY — the decisive Stage-2 gate.
# ---------------------------------------------------------------------------

def test_godray_cpu_gpu_parity(test_results_dir):
    if not _gpu_available():
        pytest.skip("CUDA GPU not available")
    gpu = _render(_godray_scene(True, 0.12, 0.6, 0.4))
    cpu = _render(_godray_scene(False, 0.12, 0.6, 0.4))
    gm, cm = _means(gpu), _means(cpu)
    ratio = gm / np.maximum(cm, 1e-6)
    print(f"\n[pkg199-s2 god-ray CPU/GPU] GPU={np.round(gm,4)} CPU={np.round(cm,4)} "
          f"ratio={np.round(ratio,4)}")
    save_image(gpu.astype(np.float32),
               os.path.join(test_results_dir, "pkg199_s2_godray_gpu.png"))
    save_image(cpu.astype(np.float32),
               os.path.join(test_results_dir, "pkg199_s2_godray_cpu.png"))
    for c, ch in enumerate("RGB"):
        assert 0.85 <= ratio[c] <= 1.18, (
            f"pkg199-s2 god-ray CPU/GPU parity FAILED ch {ch}: ratio {ratio[c]:.4f} "
            f"outside [0.85, 1.18] (GPU {gm[c]:.4f}, CPU {cm[c]:.4f})")
    # Scattering must ADD in-scattered light vs the α=0 absorption baseline.
    absorb = _means(_render(_godray_scene(True, 0.12, 0.0, 0.4)))
    print(f"[pkg199-s2 god-ray] scatter mean={gm.mean():.4f} absorb mean={absorb.mean():.4f}")
    assert gm.mean() > absorb.mean() * 1.02, (
        f"GPU in-scatter added no visible energy vs α=0 ({gm.mean():.4f} vs {absorb.mean():.4f})")


# ---------------------------------------------------------------------------
# FORWARD / BACK on GPU.
# ---------------------------------------------------------------------------

def test_forward_back_scatter_gpu():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available")
    # Light directly behind the fog (cosθ≈-1) → forward (g>0) throws the halo.
    fwd = _means(_render(_godray_scene(True, 0.15, 0.6, 0.7), spp=256, max_depth=2))
    bwd = _means(_render(_godray_scene(True, 0.15, 0.6, -0.7), spp=256, max_depth=2))
    print(f"\n[pkg199-s2 GPU fwd/back] fwd={fwd.mean():.5f} back={bwd.mean():.5f} "
          f"ratio={fwd.mean()/max(bwd.mean(),1e-9):.3f}")
    assert fwd.mean() > bwd.mean() * 1.3, (
        f"GPU forward scatter (g=+0.7, {fwd.mean():.5f}) must exceed back "
        f"(g=-0.7, {bwd.mean():.5f}) — HG sign/frame bug on GPU")
