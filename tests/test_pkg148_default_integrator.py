#!/usr/bin/env python
"""pkg148 — `integratorName_` no longer default-constructs empty.

Spec: .astroray_plan/packages/pkg148-default-integrator-empty-string.md

Option A (chosen — see PR body for the call-site sweep): default
`integratorName_` to `"path_tracer"` at construction, mirroring
`Renderer::ensureDefaultIntegrator()`'s existing lazy CPU default
(src/default_integrator.cpp), and reset to that same default (not empty)
at the `clear()` and `set_integrator("auto"|"default"|"")` reset sites
(module/blender_module.cpp:2233 pre-fix line numbers, :2499).

Before this fix: a fresh `Renderer` + GPU device + a dedicated light,
rendered without an explicit `set_integrator()` call, was solid black —
the GPU dispatch keys directly off `integratorName_` and has no
equivalent of the CPU's lazy `ensureDefaultIntegrator()` fallback. The
non-black GPU acceptance gate is HW-verifier territory (see the
HW-pending test at the bottom of this file); the tests here pin the
plumbing (binding-level default + CPU behavioral parity) that the GPU
fix depends on.
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

WIDTH = HEIGHT = 48
SPP = 8
MAX_DEPTH = 4
SEED = 11


def _lit_sphere_scene(r):
    m = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    r.add_sphere([0, 0, 0], 1.0, m)
    m_light = r.create_material("emissive", [4.0, 4.0, 4.0], {})
    r.add_sphere([0, 2.2, 0], 0.4, m_light)
    r.setup_camera(look_from=[0, 0.5, 4.0], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=40.0, aspect_ratio=1.0, aperture=0.0, focus_dist=4.0,
                   width=WIDTH, height=HEIGHT)
    r.set_background_color([0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Binding-level default pin (acceptance criterion 2).
# ---------------------------------------------------------------------------

def test_fresh_renderer_default_integrator_is_path_tracer():
    """A brand-new Renderer must report 'path_tracer' as its integrator name,
    not empty — the C++-level default this whole package is about."""
    r = astroray.Renderer()
    assert r.get_integrator() == "path_tracer"


def test_clear_resets_integrator_to_path_tracer_not_empty():
    """clear() must reset to the same default as construction (spec's
    :2499 reset site) — otherwise the footgun returns after a scene reset."""
    r = astroray.Renderer()
    r.set_integrator("ambient_occlusion")
    assert r.get_integrator() == "ambient_occlusion"
    r.clear()
    assert r.get_integrator() == "path_tracer"


@pytest.mark.parametrize("alias", ["auto", "default", ""])
def test_auto_default_empty_aliases_reset_to_path_tracer_not_empty(alias):
    """set_integrator('auto'|'default'|'') must reset to 'path_tracer', not
    empty (spec's :2233 reset site) — this sentinel is itself a way the
    empty-name footgun could reappear post-reset."""
    r = astroray.Renderer()
    r.set_integrator("ambient_occlusion")
    r.set_integrator(alias)
    assert r.get_integrator() == "path_tracer"


# ---------------------------------------------------------------------------
# CPU behavioral parity (acceptance criterion 1's CPU half).
# ---------------------------------------------------------------------------

def test_cpu_default_construction_matches_explicit_path_tracer():
    """A default-constructed Renderer (no set_integrator call) must render
    identically to one with set_integrator('path_tracer') explicitly set,
    at a fixed seed. This is the CPU-side half of the CPU==GPU parity
    acceptance gate; the GPU half is HW-verifier territory (see below)."""
    r_default = astroray.Renderer()
    _lit_sphere_scene(r_default)
    r_default.set_seed(SEED)
    pixels_default = np.asarray(
        r_default.render(SPP, MAX_DEPTH, None, False), dtype=np.float32)

    r_explicit = astroray.Renderer()
    _lit_sphere_scene(r_explicit)
    r_explicit.set_integrator("path_tracer")
    r_explicit.set_seed(SEED)
    pixels_explicit = np.asarray(
        r_explicit.render(SPP, MAX_DEPTH, None, False), dtype=np.float32)

    assert not np.any(np.isnan(pixels_default))
    assert float(pixels_default.mean()) > 0.001, \
        "default-constructed CPU render is unexpectedly dark/black"
    np.testing.assert_allclose(
        pixels_default, pixels_explicit, rtol=0.0, atol=1e-6,
        err_msg="default-constructed Renderer must match explicit "
                "set_integrator('path_tracer') bit-for-bit at a fixed seed")


# ---------------------------------------------------------------------------
# GPU acceptance gate — HW-PENDING. CI has no NVIDIA GPU (memory
# ci_has_no_gpu_runtime_blindspot); this module-level-skips on CUDA-less
# builds and the implementer does not run it. /verify runs it on the RTX box.
# ---------------------------------------------------------------------------

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip("CUDA feature not in this build — pkg148 GPU gate needs "
                "CUDA; /verify runs this on the RTX box.",
                allow_module_level=True)


def _gpu_available() -> bool:
    return astroray.Renderer().gpu_available


def test_gpu_dedicated_light_nonblack_at_default_construction():
    """HW-PENDING (RTX-verified, not run here): a fresh Renderer + GPU +
    a dedicated AREA light, rendered WITHOUT an explicit set_integrator()
    call, must be non-black and match the CPU render of the same
    default-constructed scene (mean-ratio parity) — mirrors
    tests/test_pkg89_gpu_dedicated_lights.py, but omits the explicit
    set_integrator('path_tracer') call that test relies on, since that is
    exactly the footgun this package closes."""
    if not _gpu_available():
        pytest.skip("no GPU on this machine")

    def _build():
        r = astroray.Renderer()
        m = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
        r.add_triangle([-50, 0, -50], [50, 0, -50], [50, 0, 50], m)
        r.add_triangle([-50, 0, -50], [50, 0, 50], [-50, 0, 50], m)
        r.setup_camera(look_from=[0, 3.0, 0.0001], look_at=[0, 0, 0],
                       vup=[0, 0, -1], vfov=30.0, aspect_ratio=1.0,
                       aperture=0.0, focus_dist=3.0, width=64, height=64)
        r.set_background_color([0.0, 0.0, 0.0])
        r.add_area_light_dedicated([0, 3, 0], [1, 0, 0], [0, 0, 1], 3.0, 3.0,
                                   'RECTANGLE', {'mode': 'rgb', 'color': [1, 1, 1]},
                                   300.0, 1.57)
        return r

    r_gpu = _build()
    r_gpu.set_use_gpu(True)
    r_gpu.set_seed(7)
    gpu_pixels = np.asarray(r_gpu.render(128, 3, None, False))

    r_cpu = _build()
    r_cpu.set_use_gpu(False)
    r_cpu.set_seed(7)
    cpu_pixels = np.asarray(r_cpu.render(128, 3, None, False))

    assert np.all(np.isfinite(gpu_pixels))
    gpu_mean = float(gpu_pixels.mean())
    cpu_mean = float(cpu_pixels.mean())
    assert gpu_mean > 0.05, \
        f"GPU still dark at default construction (mean={gpu_mean:.5f})"
    ratio = gpu_mean / max(cpu_mean, 1e-9)
    assert 0.9 <= ratio <= 1.1, \
        f"GPU/CPU mean-ratio {ratio:.3f} outside [0.9,1.1] " \
        f"(gpu={gpu_mean:.4f} cpu={cpu_mean:.4f})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
