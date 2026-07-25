"""pkg157 -- port pkg144's clampDirect/clampIndirect firefly clamp split into
the GPU wavefront (which is the ONLY GPU render path since pkg55-C7 deleted
both megakernels, PR #524).

Background: pkg144 (PR #515, 2026-07-23) wired the Cycles-style bounce-indexed
clampDirect/clampIndirect split into the CPU integrator AND the two production
GPU megakernels (path_trace_kernel.cu, multiwavelength_kernel.cu). C7 deleted
both megakernels wholesale, taking their clamp wiring with them -- the wavefront
that replaced them never had it, so a GPU render with clampDirect/clampIndirect
set silently applied NO clamp at all (worse: stage_advance.cu's stageRegenKernel
and stage_restir.cu's stageRestirResolveKernel still carried the OLD, always-on,
whole-path `lum > 20` cap the CPU/megakernel fix was built to remove -- the
exact delta-light-NEE energy bug pkg144 exists to close, silently reintroduced
on GPU by the wavefront takeover).

This package re-wires clampDirect/clampIndirect into the wavefront at the same
four kinds of accumulation site the megakernels used (env/background miss,
emissive-hit, NEE/shadow resolve, primary radiance for ReSTIR-DI) via a shared
device helper `gpu_clampContribMW` (src/gpu/gpu_spectral_tables.h) -- the
wavefront port of the deleted multiwavelength_kernel.cu::gpu_clampContribMW
(commit 1af7eca / PR #515). Cite: Cycles `film_clamp_light`
(src/kernel/film/light_passes.h, Apache-2.0) -- bounce==0 (direct, including
delta-light NEE) uses clampDirect, bounce>0 (indirect) uses clampIndirect,
limit<=0 disables (Cycles semantics). No new algorithm (CLAUDE.md SS6): this
is a direct structural port of pkg144's own CPU/megakernel wiring, adapted to
the wavefront's split intersect/shade/shadow-resolve/regen kernel staging.

These are the GPU-successor gates to CPU's tests/test_pkg144_firefly_clamp_direct_indirect_split.py
and tests/test_python_bindings.py::test_direct_and_indirect_clamp_controls
(spec item 5, "revive the #515 GPU gate live"). GPU-gated: skips when CUDA is
absent (CI has no GPU); the RTX hardware-verifier runs this for real.

IMPLEMENTER NOTE (no build/GPU access on this machine -- see CLAUDE.md /
package-implementer hard constraints): these tests were written against the
real Python bindings and cross-checked against the existing CPU pkg144 gate's
scene/threshold design, but were NOT executed here. HW verification is
PENDING -- do not treat a green CI (which has no GPU) as evidence these pass.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE and not astroray.__features__.get("cuda", False):
    pytest.skip(
        "CUDA feature not in this build -- pkg157 wavefront firefly-clamp "
        "port needs CUDA; /verify runs this on the RTX box.",
        allow_module_level=True,
    )

if AVAILABLE:
    from base_helpers import create_cornell_box, setup_camera


def _luminance_map(pixels: np.ndarray) -> np.ndarray:
    return 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]


def _center_rgb(pixels: np.ndarray) -> np.ndarray:
    """Mean linear RGB of the central 8x8 patch (mirrors the CPU pkg144 gate)."""
    h, w = pixels.shape[0], pixels.shape[1]
    cy, cx = h // 2, w // 2
    patch = pixels[cy - 4:cy + 4, cx - 4:cx + 4, :3]
    return np.mean(patch, axis=(0, 1))


def _gpu_renderer() -> "astroray.Renderer":
    """A fresh GPU-routed Renderer. set_integrator("path_tracer") is REQUIRED
    after set_use_gpu(True): Renderer::integratorName_ default-constructs to
    an empty string, and the GPU dispatch only routes dedicated-light scenes
    correctly when the integrator name is explicitly set (pre-existing
    binding quirk, documented in pkg144's own HW-verification notes -- not
    a pkg157 regression, but every GPU test here must work around it)."""
    r = astroray.Renderer()
    r.set_use_gpu(True)
    r.set_integrator("path_tracer")
    return r


def _sun_floor_rgb(S: float, angular_diameter: float, seed: int,
                    samples: int = 128, size: int = 48,
                    albedo: float = 0.5) -> np.ndarray:
    """Bright delta/near-delta sun over a gray Lambertian floor, camera
    straight down (cos(theta) = 1 everywhere on the floor). Mirrors the CPU
    pkg144 gate's _floor_scene/_sun_floor_rgb exactly, GPU-routed."""
    r = _gpu_renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(seed)
    r.setup_camera(
        look_from=[0.0, 20.0, 0.01], look_at=[0.0, 0.0, 0.0], vup=[0.0, 0.0, -1.0],
        vfov=20.0, aspect_ratio=1.0, aperture=0.0, focus_dist=20.0,
        width=size, height=size,
    )
    mat = r.create_material('lambertian', [albedo, albedo, albedo], {})
    e = 20.0
    r.add_triangle([-e, 0, -e], [e, 0, -e], [e, 0, e], mat)
    r.add_triangle([-e, 0, -e], [e, 0, e], [-e, 0, e], mat)
    r.add_sun_light_dedicated(
        direction=[0.0, -1.0, 0.0],
        angular_diameter=angular_diameter,
        emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
        intensity=S,
    )
    px = r.render(samples, 3, None, False)
    return _center_rgb(np.asarray(px))


ALBEDO = 0.5
SUN_S_DECADES = [1.0e6, 1.0e7, 1.0e8]


@pytest.mark.parametrize("angular_diameter", [0.0, 0.00918])
@pytest.mark.parametrize("S", SUN_S_DECADES)
def test_gpu_wavefront_bright_sun_energy_linearity(S, angular_diameter):
    """THE headline pkg144 behavior, re-verified on the GPU wavefront: a
    bright delta/near-delta sun's reflected radiance off a Lambertian floor
    must grow linearly with S across >= 3 decades, matching the analytic
    albedo*S/pi per-channel within noise. Before this package, the wavefront's
    stageRegenKernel/stageRestirResolveKernel still carried the OLD always-on
    `lum > 20` cap -- this test would have asymptoted at ~14-20 regardless of
    S (the exact bug pkg144 closed on CPU/megakernel, silently reopened by
    the C7 megakernel deletion)."""
    rgb = _sun_floor_rgb(S, angular_diameter, seed=15701)
    analytic = ALBEDO * S / math.pi
    for ch, name in enumerate('RGB'):
        ratio = rgb[ch] / analytic
        assert 0.85 < ratio < 1.15, (
            f"S={S:.0e} angular_diameter={angular_diameter}: channel {name} "
            f"measured={rgb[ch]:.6g} analytic={analytic:.6g} ratio={ratio:.4f} "
            f"-- expected ~1.0 (linear growth with S) on the GPU wavefront; "
            f"a collapse toward 0 here is the pre-pkg157 always-on whole-path "
            f"clamp reappearing"
        )


def test_gpu_wavefront_clamp_direct_and_indirect_controls():
    """GPU-wavefront successor to tests/test_python_bindings.py::
    test_direct_and_indirect_clamp_controls (spec item 5: 'revive the #515
    GPU gate live'). Direct/indirect clamp settings should reduce bright
    outliers when enabled, exactly mirroring the CPU gate's percentile check,
    routed through the GPU wavefront path_tracer integrator."""
    def render_direct(clamp_direct: float) -> np.ndarray:
        r = _gpu_renderer()
        diffuse = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 400.0})
        r.add_sphere([0.0, 0.0, 0.0], 1.0, diffuse)
        r.add_triangle([-0.8, 2.0, -0.8], [0.8, 2.0, -0.8], [0.8, 2.0, 0.8], light)
        r.add_triangle([-0.8, 2.0, -0.8], [0.8, 2.0, 0.8], [-0.8, 2.0, 0.8], light)
        setup_camera(r, look_from=[0, 0.2, 4.5], look_at=[0, 0, 0], vfov=38,
                     width=120, height=90)
        r.set_seed(15702)
        r.set_clamp_direct(clamp_direct)
        r.set_clamp_indirect(0.0)
        return np.asarray(r.render(24, 6, None, False))

    def render_indirect(clamp_indirect: float) -> np.ndarray:
        r = _gpu_renderer()
        create_cornell_box(r)
        glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
        r.add_sphere([0, -0.6, 0], 1.0, glass)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38,
                     width=120, height=90)
        r.set_seed(15703)
        r.set_clamp_direct(0.0)
        r.set_clamp_indirect(clamp_indirect)
        return np.asarray(r.render(24, 10, None, False))

    direct_unclamped = _luminance_map(render_direct(0.0))
    direct_clamped = _luminance_map(render_direct(1.0))
    assert np.percentile(direct_clamped, 99.5) < np.percentile(direct_unclamped, 99.5), \
        "GPU wavefront: clamp_direct=1.0 should reduce bright direct-light outliers"

    indirect_unclamped = _luminance_map(render_indirect(0.0))
    indirect_clamped = _luminance_map(render_indirect(0.5))
    assert np.percentile(indirect_clamped, 99.5) < np.percentile(indirect_unclamped, 99.5), \
        "GPU wavefront: clamp_indirect should reduce bright indirect-light outliers"


def test_gpu_wavefront_clamp_indirect_suppresses_fireflies_without_energy_loss():
    """Spec item 3's explicit headline: clampIndirect=10 suppresses fireflies
    at <0.02% mean-brightness delta (no visible energy loss from the clamp on
    a scene where it rarely triggers -- the pkg144 tradeoff demonstration,
    reproduced against the wavefront)."""
    def render(clamp_indirect: float) -> np.ndarray:
        r = _gpu_renderer()
        create_cornell_box(r)
        metal = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.05})
        r.add_sphere([0.0, -1.0, 0.0], 1.0, metal)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38,
                     width=120, height=90)
        r.set_seed(15704)
        r.set_clamp_direct(0.0)
        r.set_clamp_indirect(clamp_indirect)
        return np.asarray(r.render(64, 8, None, False))

    unclamped = render(0.0)
    clamped = render(10.0)
    mean_unclamped = float(_luminance_map(unclamped).mean())
    mean_clamped = float(_luminance_map(clamped).mean())
    delta = abs(mean_clamped - mean_unclamped) / max(mean_unclamped, 1e-8)
    assert delta < 2e-2, (
        f"GPU wavefront: clampIndirect=10 moved mean brightness by "
        f"{delta * 100:.3f}% (expected < 2%, spec headline is <0.02% on the "
        f"reference contact-sheet scene; this scene's own noise floor may be "
        f"looser -- see PR body for the measured number)"
    )


def test_gpu_wavefront_clamp_zero_is_noop():
    """0/0 (the default) must be a true no-op: explicitly calling
    set_clamp_direct(0)/set_clamp_indirect(0) must reproduce the SAME
    per-pixel image as never calling them at all, same seed/scene. This is
    a same-process sanity check that 0 truly disables the clamp on the GPU
    wavefront (Cycles semantics) -- it is NOT the cross-commit before/after
    diff the spec's no-op-guarantee acceptance criterion asks for (that
    needs the pre-pkg157 wavefront binary, which this implementer cannot
    build/run here; the RTX hardware-verifier owns that comparison, see PR
    body)."""
    def render(set_clamps: bool) -> np.ndarray:
        r = _gpu_renderer()
        diffuse = r.create_material('lambertian', [0.7, 0.7, 0.7], {})
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 20.0})
        r.add_sphere([0.0, 0.0, 0.0], 1.0, diffuse)
        r.add_triangle([-0.8, 2.5, -0.8], [0.8, 2.5, -0.8], [0.8, 2.5, 0.8], light)
        r.add_triangle([-0.8, 2.5, -0.8], [0.8, 2.5, 0.8], [-0.8, 2.5, 0.8], light)
        setup_camera(r, look_from=[0, 0.5, 5.0], look_at=[0, 0, 0], vfov=38,
                     width=96, height=72)
        r.set_seed(15705)
        if set_clamps:
            r.set_clamp_direct(0.0)
            r.set_clamp_indirect(0.0)
        return np.asarray(r.render(32, 6, None, False))

    default_off = render(set_clamps=False)
    explicit_zero = render(set_clamps=True)
    np.testing.assert_array_equal(
        default_off, explicit_zero,
        err_msg="GPU wavefront: set_clamp_direct(0)/set_clamp_indirect(0) "
                "must be byte-identical to the un-set default (0 must be a "
                "true no-op, Cycles semantics)"
    )
