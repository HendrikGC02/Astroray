"""pkg54d direct GPU spectral profile lookup gate."""

import os

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_BIN = os.path.join(REPO_ROOT, "data", "spectral_profiles", "profiles.bin")
HAS_PROFILES = os.path.exists(PROFILES_BIN)


def _has_cuda_gpu(renderer):
    return (
        bool(astroray.__features__.get("cuda", False))
        and bool(getattr(renderer, "gpu_available", False))
    )


def _upload_single_profile_scene(profile_name):
    renderer = astroray.Renderer()
    renderer.setup_camera(
        look_from=[0, 0, 3],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=40,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=3.0,
        width=2,
        height=2,
    )
    mat = renderer.create_material("lambertian", [0.5, 0.5, 0.5], {})
    renderer.set_material_spectral_profile(mat, profile_name)
    renderer.add_sphere([0, 0, 0], 1.0, mat)
    renderer.set_use_gpu(True)
    renderer.render(samples_per_pixel=1, max_depth=1, apply_gamma=False)
    return renderer


@pytest.mark.skipif(not HAS_PROFILES, reason="profiles.bin not found")
def test_gpu_profile_lookup_matches_cpu_grid():
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")

    astroray.load_spectral_profiles(PROFILES_BIN)
    names = astroray.spectral_profile_names()
    assert names

    max_delta = 0.0
    max_case = None
    wavelengths = [300.0 + 5.0 * k for k in range(141)]

    for name in names:
        renderer = _upload_single_profile_scene(name)
        for wavelength in wavelengths:
            cpu = astroray.spectral_profile_reflectance(name, wavelength)
            gpu = renderer._gpu_profile_lookup(0, wavelength)
            delta = abs(cpu - gpu)
            if delta > max_delta:
                max_delta = delta
                max_case = (name, wavelength, cpu, gpu)
            assert delta < 1e-6, (
                f"{name} R({wavelength:.1f}) CPU {cpu:.9f} vs GPU {gpu:.9f} "
                f"delta {delta:.9g}"
            )

    print(f"pkg54d max profile lookup delta={max_delta:.9g} at {max_case}")
