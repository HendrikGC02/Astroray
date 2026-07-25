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

HARDWARE-CALIBRATED 2026-07-26 (RTX 5070 Ti, commit 0cd285f). First HW run
was 7 passed / 2 failed. BOTH failures were defects in THESE TESTS, not in
the port -- the clamp wiring measured correct throughout (a clamp sweep
showed clean monotonic response at limits that actually bind). Fixed here:

  * Clamp limits are no longer hard-coded constants copied from #515. They
    are DERIVED from each scene's own measured peak radiance, because a
    limit above the scene's peak cannot bind and makes the test vacuous.
    #515's headline "10" was measured on a bright-sun scene; on a Cornell
    scene (peak ~1.76) it is a mathematical no-op. Every clamp test now
    asserts the limit can bind BEFORE asserting what the clamp did.
  * The indirect-clamp assertion moved off p99.5 (the top percentile is
    direct-lit and an indirect clamp barely touches it) onto mean/max.
  * The 0/0 no-op gate is a 1e-5 tolerance check, NOT byte-identity. The
    wavefront is not bit-identical even to itself across launches
    (atomic accumulation ordering; measured floor ~1.2e-07), so the spec's
    "BYTE-IDENTICAL" contract item 2 is unsatisfiable by construction. This
    is flagged in PR #526 for the owner to amend, not silently worked around.

Full measured numbers: test_results/overnight_report_2026-07-25/pkg157_hw_numbers.json
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
    GPU gate live'). Direct/indirect clamp settings must measurably reduce
    radiance when enabled, routed through the GPU wavefront path_tracer.

    HW-CALIBRATED 2026-07-26 (RTX 5070 Ti, commit 0cd285f). The first draft of
    this test copied the CPU gate verbatim -- fixed clamp constants plus a
    p99.5 percentile comparison -- and FAILED on hardware for two independent
    reasons, both TEST defects (the port itself measured correct):

      1. FIXED CLAMP CONSTANTS DO NOT TRANSFER BETWEEN SCENES. A clamp does
         nothing unless its limit sits BELOW the scene's peak radiance. On a
         Cornell-scale scene (measured peak ~1.76 linear) a limit of 10 is a
         mathematical no-op no matter how correct the wiring is. Measured
         sweep, `diffuse_light_cornell` 120^2 64spp: clampIndirect=10 ->
         max|delta| 0.00000 (never binds); =1 -> 0.14764; =0.1 -> 0.20867.
         The limit is now DERIVED from each scene's own measured peak, and
         the test asserts up front that the limit really can bind -- so it
         can never again pass or fail for reasons of scene scale.

      2. p99.5 IS THE WRONG STATISTIC FOR AN *INDIRECT* CLAMP. The brightest
         pixels in these scenes are DIRECT-lit, so clamping indirect paths
         barely moves the top percentile; the original assertion failed on
         exactly-equal values (5.0587068 < 5.0587068). Measured: an indirect
         clamp moves `mean` and `max` while p99.5 stays put. The indirect leg
         now asserts on those.

    Assertions are direction-of-effect (a clamp removes energy, never adds),
    which is what the port must guarantee -- deliberately NOT a magnitude,
    which would re-introduce exactly the scene-specific tuning that broke
    the first draft."""
    # Fraction of the measured unclamped peak used as the clamp limit. Well
    # inside the scene's range so the clamp is guaranteed to bind (the sweep
    # above shows ~0.57x peak already binds), while leaving headroom so the
    # test is not sensitive to the exact peak.
    LIMIT_FRAC = 0.25
    # The wavefront is not bit-identical to itself across launches (atomic
    # accumulation ordering; measured self-variation ~1.2e-07). Any real
    # clamp effect must clear that floor by orders of magnitude.
    NOISE_FLOOR = 1e-5
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

    # ---- DIRECT leg -------------------------------------------------------
    direct_unclamped = _luminance_map(render_direct(0.0))
    direct_peak = float(direct_unclamped.max())
    direct_limit = direct_peak * LIMIT_FRAC
    assert direct_limit > 0.0 and direct_limit < direct_peak, (
        f"direct scene peak={direct_peak:.6g} gives limit={direct_limit:.6g}; "
        f"the limit must sit strictly inside the scene's range or the clamp "
        f"cannot bind and this test would pass vacuously"
    )
    direct_clamped = _luminance_map(render_direct(direct_limit))

    d_delta = float(np.max(np.abs(direct_clamped - direct_unclamped)))
    assert d_delta > NOISE_FLOOR, (
        f"clamp_direct={direct_limit:.6g} changed NOTHING (max|delta|="
        f"{d_delta:.3g} <= noise floor {NOISE_FLOOR:.0e}) on a scene whose "
        f"peak is {direct_peak:.6g} -- the direct clamp is not reaching the "
        f"wavefront's direct accumulation sites"
    )
    assert float(direct_clamped.max()) < direct_peak, (
        f"clamp_direct={direct_limit:.6g} did not lower the peak "
        f"({direct_clamped.max():.6g} vs unclamped {direct_peak:.6g})"
    )
    assert float(direct_clamped.mean()) < float(direct_unclamped.mean()), (
        "clamp_direct removed no energy overall; a binding clamp can only "
        "reduce radiance, never increase or preserve it exactly"
    )

    # ---- INDIRECT leg -----------------------------------------------------
    indirect_unclamped = _luminance_map(render_indirect(0.0))
    indirect_peak = float(indirect_unclamped.max())
    indirect_limit = indirect_peak * LIMIT_FRAC
    assert indirect_limit > 0.0 and indirect_limit < indirect_peak, (
        f"indirect scene peak={indirect_peak:.6g} gives limit="
        f"{indirect_limit:.6g}; the limit must sit strictly inside the "
        f"scene's range or the clamp cannot bind"
    )
    indirect_clamped = _luminance_map(render_indirect(indirect_limit))

    i_delta = float(np.max(np.abs(indirect_clamped - indirect_unclamped)))
    assert i_delta > NOISE_FLOOR, (
        f"clamp_indirect={indirect_limit:.6g} changed NOTHING (max|delta|="
        f"{i_delta:.3g} <= noise floor {NOISE_FLOOR:.0e}) on a scene whose "
        f"peak is {indirect_peak:.6g} -- the indirect clamp is not reaching "
        f"the wavefront's bounce>0 accumulation sites"
    )
    # mean/max, NOT p99.5: the top percentile here is direct-lit and an
    # indirect clamp leaves it essentially untouched (see docstring item 2).
    assert float(indirect_clamped.mean()) < float(indirect_unclamped.mean()), (
        f"clamp_indirect={indirect_limit:.6g} did not reduce mean radiance "
        f"({indirect_clamped.mean():.8g} vs unclamped "
        f"{indirect_unclamped.mean():.8g})"
    )
    assert float(indirect_clamped.max()) <= indirect_peak + NOISE_FLOOR, (
        "clamp_indirect INCREASED peak radiance; a clamp must never add energy"
    )


def test_gpu_wavefront_clamp_indirect_suppresses_fireflies_without_energy_loss():
    """Spec item 3's headline: an indirect clamp suppresses the brightest
    indirect contributions WITHOUT meaningful energy loss (the pkg144
    bias/variance tradeoff, reproduced against the wavefront).

    HW-CALIBRATED 2026-07-26 (RTX 5070 Ti, commit 0cd285f). This test PASSED
    on hardware in its first form, but it passed VACUOUSLY and is fixed here
    anyway. It used #515's headline constant clampIndirect=10; the verifier's
    sweep proved that on a Cornell-scale scene (peak ~1.76 linear) a limit of
    10 never binds -- max|delta| was exactly 0.00000. So the old assertion
    "mean brightness moved < 2%" was satisfied by the clamp doing literally
    nothing, and would have kept passing even if the port were entirely
    unwired. #515's 10 was measured on a bright-sun scene with a far larger
    dynamic range, not on this one.

    Now the limit is derived from the scene's own measured peak, and the test
    asserts BOTH halves of the claim: that the clamp actually binds, and that
    it nonetheless preserves total energy. A vacuous pass is now impossible --
    the binding assertion fails first."""
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

    # Milder than the controls test's 0.25: high enough that only the
    # brightest indirect contributions are capped, so total energy stays
    # essentially intact. Measured reference: a limit at ~0.57x peak moved
    # mean by 0.4% while producing max|delta| 0.148 (i.e. it clearly bound).
    LIMIT_FRAC = 0.5
    NOISE_FLOOR = 1e-5

    unclamped = render(0.0)
    lum_unclamped = _luminance_map(unclamped)
    peak = float(lum_unclamped.max())
    limit = peak * LIMIT_FRAC
    assert limit > 0.0 and limit < peak, (
        f"scene peak={peak:.6g} gives limit={limit:.6g}; the limit must sit "
        f"strictly inside the scene's range or the clamp cannot bind"
    )

    clamped = render(limit)
    lum_clamped = _luminance_map(clamped)

    # Half 1 -- it must actually BIND. This is the assertion whose absence
    # made the original version vacuous.
    delta_max = float(np.max(np.abs(lum_clamped - lum_unclamped)))
    assert delta_max > NOISE_FLOOR, (
        f"clampIndirect={limit:.6g} changed NOTHING (max|delta|="
        f"{delta_max:.3g} <= noise floor {NOISE_FLOOR:.0e}) on a scene whose "
        f"peak is {peak:.6g} -- no firefly suppression happened, so the "
        f"energy-preservation half below would be meaningless"
    )

    # Half 2 -- having bound, it must not cost meaningful total energy.
    mean_unclamped = float(lum_unclamped.mean())
    mean_clamped = float(lum_clamped.mean())
    rel = abs(mean_clamped - mean_unclamped) / max(mean_unclamped, 1e-8)
    assert rel < 2e-2, (
        f"clampIndirect={limit:.6g} bound (max|delta|={delta_max:.4g}) but "
        f"moved mean brightness by {rel * 100:.3f}% (expected < 2%) -- the "
        f"clamp is removing real energy, not just firefly outliers"
    )
    # Direction check: clamping can only remove energy.
    assert mean_clamped <= mean_unclamped + NOISE_FLOOR, (
        "clampIndirect INCREASED mean radiance; a clamp must never add energy"
    )


def test_gpu_wavefront_clamp_zero_is_noop():
    """0/0 (the default) must be a true no-op: explicitly calling
    set_clamp_direct(0)/set_clamp_indirect(0) must reproduce the same image
    as never calling them at all, same seed/scene -- i.e. 0 really disables
    the clamp (Cycles semantics).

    HW-CALIBRATED 2026-07-26 (RTX 5070 Ti, commit 0cd285f). This test
    originally asserted BYTE-IDENTICAL output via assert_array_equal and
    FAILED: 53/20736 elements differed, max|delta| 4.77e-07.

    That premise is UNACHIEVABLE BY CONSTRUCTION, and the failure is not a
    pkg157 defect. The verifier measured the wavefront against ITSELF -- same
    seed, same config, no clamp calls at all, three consecutive renders:

        run1 vs run2: NOT bit-identical, max|delta| 1.19e-07 (29/27648 elems)
        run1 vs run3: NOT bit-identical, max|delta| 8.94e-08

    The wavefront accumulates via atomicAdd into per-pixel accumulators
    (stage_advance.cu stageRegenKernel); float addition is not associative,
    and the order in which dead paths land varies between launches. So the
    path is non-deterministic at the float32 epsilon level with or without
    this package. The 4.77e-07 observed above IS that same floor, and it is
    ~20x TIGHTER than the project's stated 1e-5 MC convention for the
    wavefront.

    The gate is therefore restated as agreement within that 1e-5 convention.
    This is a DELIBERATE WEAKENING of the assertion and is called out as such
    in PR #526: the pkg157 spec's contract item 2 demands clamps-off output be
    "BYTE-IDENTICAL", which no wavefront render can satisfy against any
    reference including itself. The spec needs amending -- flagged to the
    owner rather than quietly worked around.

    DO NOT re-tighten toward byte-identical (it will flake, then get marked
    xfail, and the real signal will be lost). 1e-5 is four orders of magnitude
    above the measured self-variation floor, so a genuine clamp leak -- which
    would change radiance by O(0.1) -- still fails this loudly.
    """
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

    # The wavefront's own launch-to-launch self-variation is ~1.2e-07
    # (measured, see docstring). 1e-5 is the project's MC convention for this
    # path and sits four orders of magnitude above that floor.
    MC_TOLERANCE = 1e-5

    default_off = render(set_clamps=False)
    explicit_zero = render(set_clamps=True)

    delta = float(np.max(np.abs(
        default_off.astype(np.float64) - explicit_zero.astype(np.float64))))
    assert delta < MC_TOLERANCE, (
        f"GPU wavefront: set_clamp_direct(0)/set_clamp_indirect(0) diverged "
        f"from the un-set default by max|delta|={delta:.3g}, above the "
        f"{MC_TOLERANCE:.0e} MC convention -- 0 is NOT behaving as 'clamp "
        f"disabled' (Cycles semantics). Note this is a tolerance gate, not a "
        f"byte-identity gate: the wavefront is not bit-identical even to "
        f"itself (atomic accumulation ordering, measured floor ~1.2e-07), so "
        f"a divergence this large is a real clamp leak, not float noise."
    )
