"""pkg189 — GPU wavefront hero-λ dispersion enablement (acceptance oracle).

Before pkg189 the GPU wavefront hero-wavelength dispersion was a NO-OP for every
material (pkg187 measured GPU dielectric BK7 0.2139 ≈ flat 0.2131, GPU Principled
disp 0.2041 == flat 0.2041). Root cause: gpu_material_sample_spectral collapses
to the hero wavelength via wl.terminateSecondary() (zeroing secondary pdfs) on a
dispersive refraction, but the wavefront shade kernel reconstructed `lambdas` as a
stack local and never wrote the mutated pdfs back to the per-path SoA — so the
collapse evaporated and stageRegenKernel's spectrumToXYZ still summed all four
wavelengths (broadband → achromatic). pkg189 persists the collapse to SoA behind a
compile-time HasDispersion axis (flat-IOR fleet kernels bit-unchanged).

This is the acceptance oracle for that fix:
  * CONTROL FLIP — GPU dispersive disp/flat mean-ratio must now DIFFER from the
    ~1.0 no-op, for BOTH dielectric (Sellmeier) and Principled (Cauchy) glass.
    Expected magnitude tracks the CPU reference (disp dims the mean to ~0.55×).
  * CPU/GPU PARITY — per-channel mean-ratio (NOT SSIM: independent MC streams,
    memory ssim-wrong-gate-for-independent-rng).
  * VISUAL RAINBOW — a dispersive glass sphere refracting a colored backdrop is
    rendered to PNG for the mandatory human/parent visual check (the metrics pass
    on garbage; memory general-photon-loop-needs-solid-glass). The sphere is a
    CLOSED solid with outward normals (the documented "good" caster case).

GPU-gated: skips when CUDA is absent (CI has no GPU); /verify runs on RTX.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build — pkg189 GPU wavefront dispersion needs the "
        "RTX box; /verify runs this there.",
        allow_module_level=True,
    )

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 8
SEED = 189189

DISP = {"dispersion_scale": 1.0, "dispersion_abbe": 20.0}
_P_FLAT = {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.02, "metallic": 0.0}
_P_DISP = {**_P_FLAT, **DISP}


def _make_scene(use_gpu: bool, kind: str, params: dict, width: int, height: int):
    """Glass sphere refracting a red/blue/green colored backdrop — the pkg187
    acceptance scene (glass sphere is a CLOSED solid with outward normals)."""
    r = astroray.Renderer()
    r.set_background_color([0.30, 0.45, 0.65])
    red = r.create_material("lambertian", [1.0, 0.05, 0.03], {})
    green = r.create_material("lambertian", [0.05, 1.0, 0.08], {})
    blue = r.create_material("lambertian", [0.03, 0.08, 1.0], {})
    r.add_triangle([-3, -3, -2.5], [0, -3, -2.5], [0, 3, -2.5], red)
    r.add_triangle([-3, -3, -2.5], [0, 3, -2.5], [-3, 3, -2.5], red)
    r.add_triangle([0, -3, -2.5], [3, -3, -2.5], [3, 3, -2.5], blue)
    r.add_triangle([0, -3, -2.5], [3, 3, -2.5], [0, 3, -2.5], blue)
    r.add_triangle([-3, -3, -2.6], [3, -3, -2.6], [0, -1.2, -2.6], green)
    mat = r.create_material(kind, [1.0, 1.0, 1.0], params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    r.setup_camera([0.0, 0.0, 2.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   55.0, width / height, 0.0, 2.0, width, height)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)   # engage the spectral wavefront leg
        r.set_output_mode("srgb")
    r.set_seed(SEED)
    return r


def _render(use_gpu: bool, kind: str, params: dict,
            width: int = WIDTH, height: int = HEIGHT, samples: int = SAMPLES) -> np.ndarray:
    r = _make_scene(use_gpu, kind, params, width, height)
    img = np.asarray(r.render(samples, MAX_DEPTH, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(height, width, 3)
    return img


def _means(img):
    return np.array([float(img[..., c].mean()) for c in range(3)])


def _gpu_available() -> bool:
    return astroray.Renderer().gpu_available


# ---------------------------------------------------------------------------
# CONTROL FLIP — dispersion is now LIVE on the GPU wavefront leg (was a no-op).
# ---------------------------------------------------------------------------

def test_gpu_dielectric_dispersion_control_flips():
    """GPU dielectric BK7 disp/flat must DIFFER from the ~1.0 no-op (pkg187:
    0.2139/0.2131 ≈ 1.003). After pkg189 the hero collapse persists → dispersion
    dims the mean toward the CPU reference (~0.55×)."""
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    flat = _means(_render(True, "dielectric", {"ior": 1.5})).mean()
    disp = _means(_render(True, "dielectric", {"sellmeier_preset": "bk7"})).mean()
    ratio = disp / max(flat, 1e-8)
    print(f"\n[pkg189 GPU dielectric control] flat={flat:.4f} bk7={disp:.4f} "
          f"disp/flat={ratio:.4f}")
    assert ratio < 0.90, (
        f"pkg189 GPU dielectric dispersion is STILL a no-op (bk7/flat={ratio:.4f} "
        f">= 0.90). The hero-λ collapse is not persisting — check the HasDispersion "
        f"write-back in shadePathSlot and hasDispersive scene flag.")


def test_gpu_principled_dispersion_control_flips():
    """GPU Principled (Cauchy) disp/flat must DIFFER from the ~1.0 no-op (pkg187:
    0.2041/0.2041 == 1.000). After pkg189 dispersion is live for Principled too."""
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    flat = _means(_render(True, "principled", _P_FLAT)).mean()
    disp = _means(_render(True, "principled", _P_DISP)).mean()
    ratio = disp / max(flat, 1e-8)
    print(f"\n[pkg189 GPU principled control] flat={flat:.4f} disp={disp:.4f} "
          f"disp/flat={ratio:.4f}")
    assert ratio < 0.90, (
        f"pkg189 GPU Principled dispersion is STILL a no-op (disp/flat={ratio:.4f} "
        f">= 0.90). Principled glass lowers to GMAT_CLOSURE_GRAPH; check the "
        f"HasDispersion write-back reaches the <true,...,true> instantiation.")


# ---------------------------------------------------------------------------
# CPU/GPU PARITY — per-channel mean-ratio (NOT SSIM; independent MC streams).
# ---------------------------------------------------------------------------

def _parity(kind: str, disp_params: dict, label: str):
    gpu = _means(_render(True, kind, disp_params))
    cpu = _means(_render(False, kind, disp_params))
    ratio = gpu / np.maximum(cpu, 1e-6)
    print(f"\n[pkg189 CPU/GPU parity {label}] GPU={np.round(gpu,4)} "
          f"CPU={np.round(cpu,4)} GPU/CPU={np.round(ratio,4)}")
    # Per-channel mean-ratio band. Independent MC streams + the hero-collapse's
    # single-wavelength-per-path variance make an exact match unreachable; a
    # generous band still catches "GPU dispersion diverges from CPU" (e.g. a
    # missing collapse → GPU stays bright while CPU dims).
    for c, ch in enumerate("RGB"):
        assert 0.75 <= ratio[c] <= 1.30, (
            f"pkg189 {label} CPU/GPU dispersive parity FAILED ch {ch}: "
            f"GPU/CPU mean-ratio {ratio[c]:.4f} outside [0.75, 1.30] "
            f"(GPU {gpu[c]:.4f}, CPU {cpu[c]:.4f}).")


def test_gpu_cpu_dielectric_dispersive_parity():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    _parity("dielectric", {"sellmeier_preset": "bk7"}, "dielectric-bk7")


def test_gpu_cpu_principled_dispersive_parity():
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    _parity("principled", _P_DISP, "principled")


# ---------------------------------------------------------------------------
# VISUAL RAINBOW — a dispersive glass sphere refracts a WHITE backdrop split by
# a sharp dark bar. White light spread by dispersion produces a spectral fringe
# (rainbow) at the refracted high-contrast edges. The flat-IOR control is
# perfectly ACHROMATIC (grayscale), so ANY chromatic content in the dispersive
# render is the dispersion — a clean, correctly-signed metric AND a dramatic
# visual. PNGs saved for the mandatory human/parent visual check.
# ---------------------------------------------------------------------------

def _make_rainbow_scene(kind: str, params: dict, w: int, h: int):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("light", [1, 1, 1], {"intensity": 2.0})
    r.add_triangle([-6, -6, -3], [6, -6, -3], [6, 6, -3], white)
    r.add_triangle([-6, -6, -3], [6, 6, -3], [-6, 6, -3], white)
    dark = r.create_material("lambertian", [0.0, 0.0, 0.0], {})
    r.add_triangle([-6, 0.0, -2.7], [6, 0.0, -2.7], [6, 0.6, -2.7], dark)
    r.add_triangle([-6, 0.0, -2.7], [6, 0.6, -2.7], [-6, 0.6, -2.7], dark)
    mat = r.create_material(kind, [1, 1, 1], params)
    r.add_sphere([0, 0, 0], 0.9, mat)
    r.setup_camera([0, 0, 2.0], [0, 0, 0], [0, 1, 0], 55.0, w / h, 0.0, 2.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_use_gpu(True)
    r.set_wavelength_range(380.0, 780.0)
    r.set_output_mode("srgb")
    r.set_seed(SEED)
    img = np.asarray(r.render(512, MAX_DEPTH, None, False), dtype=np.float32)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _saturation(img):
    """Mean HSV-style saturation (max-min)/max over lit sphere pixels — 0 for a
    grayscale (achromatic) render, >0 when wavelengths separate into color."""
    lum = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
    m = lum > 0.02
    if m.sum() < 16:
        return 0.0
    mx = img.max(axis=-1)
    mn = img.min(axis=-1)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    return float(sat[m].mean())


def test_gpu_dielectric_rainbow_visual(test_results_dir):
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    from base_helpers import save_image

    w = h = 200
    flat_img = _make_rainbow_scene("dielectric", {"ior": 1.5}, w, h)
    bk7_img = _make_rainbow_scene("dielectric", {"sellmeier_preset": "bk7"}, w, h)

    flat_png = os.path.join(test_results_dir, "pkg189_gpu_rainbow_flat.png")
    bk7_png = os.path.join(test_results_dir, "pkg189_gpu_rainbow_bk7.png")
    save_image(flat_img, flat_png)
    save_image(bk7_img, bk7_png)

    s_flat = _saturation(flat_img)
    s_bk7 = _saturation(bk7_img)
    print(f"\n[pkg189 GPU dielectric rainbow] saturation flat={s_flat:.4f} "
          f"bk7={s_bk7:.4f}\n  FLAT PNG: {flat_png}\n  BK7  PNG: {bk7_png}\n"
          f"  PARENT: open both PNGs — the flat control is pure grayscale; the BK7 "
          f"render shows a colored spectral fringe (rainbow) at the refracted edges.")
    # The flat control is achromatic (grayscale); the dispersive render must carry
    # clear chromatic content. Absolute floor + a wide margin over the control.
    assert s_bk7 > 0.05 and s_bk7 > s_flat * 3.0, (
        f"pkg189 GPU dielectric: dispersive render lacks chromatic content "
        f"(bk7 sat {s_bk7:.4f} vs flat {s_flat:.4f}). No spectral fringe / rainbow.")


def test_gpu_principled_rainbow_visual(test_results_dir):
    if not _gpu_available():
        pytest.skip("CUDA GPU not available on this machine")
    from base_helpers import save_image

    w = h = 200
    flat_img = _make_rainbow_scene(
        "principled", {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.0}, w, h)
    disp_img = _make_rainbow_scene(
        "principled", {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.0,
                       "dispersion_scale": 3.0, "dispersion_abbe": 15.0}, w, h)

    flat_png = os.path.join(test_results_dir, "pkg189_gpu_rainbow_principled_flat.png")
    disp_png = os.path.join(test_results_dir, "pkg189_gpu_rainbow_principled.png")
    save_image(flat_img, flat_png)
    save_image(disp_img, disp_png)

    s_flat = _saturation(flat_img)
    s_disp = _saturation(disp_img)
    print(f"\n[pkg189 GPU principled rainbow] saturation flat={s_flat:.4f} "
          f"disp={s_disp:.4f}\n  FLAT PNG: {flat_png}\n  DISP PNG: {disp_png}\n"
          f"  PARENT: open both PNGs — the flat control is grayscale; the dispersive "
          f"Principled render shows a full spectral rainbow ring at the refracted edge.")
    assert s_disp > 0.05 and s_disp > s_flat * 3.0, (
        f"pkg189 GPU principled: dispersive render lacks chromatic content "
        f"(disp sat {s_disp:.4f} vs flat {s_flat:.4f}). No rainbow.")
