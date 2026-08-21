"""CPU<->GPU emission-colour parity for preset (measured_spd) lamps.

Regression gate for the deviceReference chroma bug (2026-08-22): the GPU renders
non-RGB emission (measured_spd / blackbody / composite) as an RGB approximation
via EmissionSpectrum::deviceReference. That reference RGB was estimated from a
4-sample Monte-Carlo toXYZ at sampleUniform(0.5) over the default [360,830] nm
range -- four fixed wavelengths (595, 712.5, 830, 477.5) that badly undersample
a structured lamp SPD (830 nm is dead for a 380-780 nm LED; none lands on the
blue pump peak). The result was a strongly red/orange-biased RGB the GPU rendered
faithfully: salmon LEDs, over-orange sodium, reddish mercury (live Blender repro:
led_5000k GPU R/G ~1.52 vs CPU ~1.09). The fix replaces the 4-sample MC with a
fine 1 nm CMF-grid integral (emission_spectrum.cpp), so the reference RGB carries
the true chroma.

This asserts per-channel mean-ratio parity (NOT SSIM -- CPU and GPU draw
independent RNG streams; see memory ssim-wrong-gate-for-independent-rng). It runs
the dedicated-light NEE path (integrator "path_tracer"); the naive
"multiwavelength_path_tracer" does not drive GPU dedicated-light NEE.

Broadband lamps reach a few-% parity here. Narrow line lamps (sodium) keep a
larger chroma gap that is intrinsic to the RGB approximation and is closed by the
follow-up device-SPD upload (pkg218); this test only asserts sodium improved well
past the old red bias, not tight parity.
"""
import os

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")
HAS_PROFILES = os.path.exists(PROFILES_BIN)

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip("CUDA feature not in this build — emission parity needs CUDA; "
                "run on the RTX box via /verify.", allow_module_level=True)


def _has_gpu():
    try:
        return bool(astroray.Renderer().gpu_available)
    except Exception:
        return False


def _lamp_channels(emission, use_gpu, spp=192, width=48, height=48):
    """White sphere lit by a point lamp; per-channel linear means. path_tracer
    exercises the (GPU wavefront) dedicated-light NEE emission path."""
    astroray.load_spectral_profiles(PROFILES_BIN)
    r = astroray.Renderer()
    r.set_use_gpu(use_gpu)
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=35, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    r.set_seed(101)
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_point_light(position=[2.0, 2.0, 2.0], emission=emission,
                      intensity=60.0, radius=0.0)
    r.set_wavelength_range(380.0, 780.0)
    r.set_integrator("path_tracer")
    pixels = np.array(r.render(spp, 6, None, False), dtype=np.float32)  # linear
    return pixels.reshape(-1, 3).mean(axis=0)


def _rg(v):
    return float(v[0] / v[1]) if v[1] > 1e-9 else float("inf")


needs = pytest.mark.skipif(not HAS_PROFILES or not (AVAILABLE and _has_gpu()),
                           reason="profiles.bin or CUDA GPU not available")


@needs
@pytest.mark.parametrize("profile", ["led_5000k", "led_3000k", "mercury_vapor", "cie_f2"])
def test_broadband_lamp_cpu_gpu_parity(profile):
    """Broadband preset lamps: GPU per-channel mean within 8% of CPU.

    (Measured ~2-4% post-fix; 8% leaves margin for MC noise + boost-clock drift.
    Pre-fix, led_5000k red channel was ~40% hot vs its own CPU render.)
    """
    em = {"mode": "measured_spd", "profile_name": profile}
    cpu = _lamp_channels(em, use_gpu=False)
    gpu = _lamp_channels(em, use_gpu=True)
    assert cpu.min() > 1e-3 and gpu.min() > 1e-3, (
        f"{profile}: lamp rendered near-black CPU={cpu} GPU={gpu}"
    )
    ratio = gpu / np.maximum(cpu, 1e-9)
    maxdev = float(np.abs(ratio - 1.0).max())
    print(f"[{profile}] CPU={cpu.round(4)} GPU={gpu.round(4)} "
          f"R/G cpu={_rg(cpu):.3f} gpu={_rg(gpu):.3f} maxdev={maxdev*100:.1f}%")
    assert maxdev < 0.08, (
        f"{profile}: CPU/GPU per-channel mismatch {maxdev*100:.1f}% > 8% "
        f"(CPU={cpu}, GPU={gpu})"
    )


@needs
def test_led_5000k_not_red_shifted():
    """Direct regression guard on the salmon bug: neutral-white LED must render
    near-neutral on GPU (R/G close to CPU), not the pre-fix salmon R/G."""
    em = {"mode": "measured_spd", "profile_name": "led_5000k"}
    cpu = _lamp_channels(em, use_gpu=False)
    gpu = _lamp_channels(em, use_gpu=True)
    rg_cpu, rg_gpu = _rg(cpu), _rg(gpu)
    print(f"[led_5000k] R/G cpu={rg_cpu:.3f} gpu={rg_gpu:.3f}")
    # GPU R/G within 8% of CPU, and comfortably below the pre-fix salmon regime
    # (the live repro showed GPU R/G inflated ~40% over CPU).
    assert abs(rg_gpu - rg_cpu) / rg_cpu < 0.08, (
        f"led_5000k GPU R/G {rg_gpu:.3f} vs CPU {rg_cpu:.3f} -- red-shift regressed"
    )
    assert rg_gpu < rg_cpu * 1.15, (
        f"led_5000k GPU R/G {rg_gpu:.3f} red-hot vs CPU {rg_cpu:.3f}"
    )


@needs
def test_sodium_lamp_improved_not_red():
    """Sodium line lamp: the RGB approximation keeps a larger chroma gap (closed
    by pkg218's device-SPD upload), so parity is loose here -- but the GPU render
    must still be amber and track the CPU hue direction, not the old red bias."""
    em = {"mode": "measured_spd", "profile_name": "sodium_vapor"}
    cpu = _lamp_channels(em, use_gpu=False)
    gpu = _lamp_channels(em, use_gpu=True)
    print(f"[sodium] CPU={cpu.round(4)} GPU={gpu.round(4)} "
          f"R/G cpu={_rg(cpu):.3f} gpu={_rg(gpu):.3f}")
    assert gpu[0] > 1e-3, f"sodium GPU render black: {gpu}"
    # Amber: R dominant over G, G over (tiny) B.
    assert gpu[0] > gpu[1] > gpu[2], f"sodium GPU not amber: {gpu}"
    # Loose chroma tracking (pkg218 tightens to a few %).
    assert abs(_rg(gpu) - _rg(cpu)) / _rg(cpu) < 0.30, (
        f"sodium GPU R/G {_rg(gpu):.3f} far from CPU {_rg(cpu):.3f}"
    )
