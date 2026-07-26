"""pkg161 -- the firefly-bearing gate scene, validated BY MEASUREMENT.

pkg161 contract item 2: "Validate by measurement, not by eye. The scene
qualifies only if peak / p99.9 >~ 10x at the gate's spp. A scene that merely
*looks* noisy does not qualify."

The scene is tests/scenes/firefly_window.py; its construction, its citations and
its tuning model are documented there and in
.astroray_plan/docs/pkg161-firefly-scene-research.md.

WHY THERE ARE NEGATIVE CONTROLS IN THIS FILE
--------------------------------------------
The reason the library ended up with no firefly-bearing scene is that
"looks noisy" was never checked against a number. A tail-ratio assertion that
nothing can fail would repeat that mistake one level up, so
`test_tail_metric_discriminates` proves the SAME measurement function fails on
two inputs that must not pass:

  (a) `metal_cornell` -- measured 1.07x / 1.04x at 16 / 64 spp on RTX 5070 Ti
      2026-07-26, the flattest scene in the suite. If the metric passed this,
      it would be measuring nothing.
  (b) the firefly scene itself rendered with apply_gamma=True -- the gamma path
      clamps to [0, 1] before the 1/2.2 power
      (module/blender_module.cpp:1803-1811), which annihilates precisely the
      outliers being measured. This assertion exists so nobody can quietly flip
      the 4th positional argument of render() back to its default and still see
      a green suite. Memory: `gamma-furnace-cannot-detect-energy-gain`.

CALIBRATION STATUS
------------------
The scene's EMITTER_INTENSITY / EMITTER_RADIUS defaults are ANALYTIC DESIGN
TARGETS, not measurements -- the implementer had no GPU and ran no renders.
`scripts/verify_pkg161_firefly_scene.py` measures them and prints corrected
constants. If a test in this file fails on its threshold, run that script
before touching the threshold: the thresholds here are the spec's, and the
scene constants are the thing meant to move.
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
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

if AVAILABLE:
    import scenes.firefly_window as firefly
    import scenes.metal_cornell as metal_cornell


#: pkg161 contract item 2. The whole suite measured 1.04x-1.82x before this
#: package, so 10x is ~5.5x above the best pre-existing scene.
FIREFLY_TAIL_RATIO_MIN = 10.0

#: What a scene WITHOUT fireflies must stay under. metal_cornell measured
#: 1.07x / 1.04x; 3.0 leaves generous headroom over every measured
#: non-firefly scene (worst was diffuse_light_cornell at 1.82x) while staying
#: far below the 10x bar, so the two populations cannot be confused.
NO_TAIL_RATIO_MAX = 3.0


def _render(build, camera, *, width, height, samples, max_depth, seed,
            use_gpu=False, apply_gamma=False):
    r = astroray.Renderer()
    if use_gpu:
        r.set_use_gpu(True)
    # Required after set_use_gpu(True), harmless otherwise: Renderer's GPU
    # dispatch only routes dedicated-light scenes correctly when the integrator
    # name is set explicitly (documented in pkg157's _gpu_renderer()).
    r.set_integrator("path_tracer")
    build(r)
    camera(r, width, height)
    r.set_seed(seed)
    return np.asarray(r.render(samples, max_depth, None, apply_gamma))


def _firefly_render(*, width, height, samples, seed, use_gpu, apply_gamma=False,
                    emitter_radius=None):
    # Resolved lazily, NOT as a default argument. `firefly` is imported only
    # under `if AVAILABLE:`, and a default argument is evaluated at *def* time —
    # i.e. at module import, before `pytestmark = skipif(not AVAILABLE)` can
    # suppress anything. Naming it in the signature makes this module fail to
    # COLLECT on a checkout with no build, which is precisely the environment
    # implementers work in here.
    if emitter_radius is None:
        emitter_radius = firefly.EMITTER_RADIUS
    return _render(
        lambda r: firefly.build_scene(r, emitter_radius=emitter_radius),
        firefly.setup_camera,
        width=width, height=height, samples=samples,
        max_depth=firefly.MAX_DEPTH, seed=seed,
        use_gpu=use_gpu, apply_gamma=apply_gamma,
    )


def _explain(stats, label):
    return (
        f"{label}: peak={stats['peak']:.6g} p99.9={stats['p99_9']:.6g} "
        f"ratio={stats['ratio']:.3g} mean={stats['mean']:.6g} "
        f"fireflies={stats['n_fireflies']}/{stats['n_pixels']} "
        f"({100.0 * stats['n_fireflies'] / stats['n_pixels']:.4f}% of pixels)"
    )


def test_firefly_scene_has_heavy_tail_cpu():
    """CPU leg. The scene must carry a real firefly tail on the CPU integrator
    too, so it doubles as a CPU/GPU parity fixture (pkg161 gate 4: "fireflies
    are exactly where CPU/GPU transport differences show up").

    Renders with a deliberately enlarged emitter
    (CPU_EMITTER_RADIUS_SCALE): the firefly COUNT is proportional to total
    sample count (n_ff ~ N * spp * r_e^2) while the tail RATIO depends only on
    L_e / spp, so scaling the radius buys back the count a CPU-affordable
    render loses without changing the quantity under test. See the TUNING MODEL
    section of scenes/firefly_window.py.
    """
    pixels = _firefly_render(
        width=firefly.CPU_WIDTH, height=firefly.CPU_HEIGHT,
        samples=firefly.CPU_SAMPLES, seed=firefly.SEED, use_gpu=False,
        emitter_radius=firefly.EMITTER_RADIUS * firefly.CPU_EMITTER_RADIUS_SCALE,
    )
    stats = firefly.tail_stats(pixels)

    # Guard the measurement itself before trusting it: a black or NaN image
    # would give ratio = inf and pass the real assertion vacuously.
    assert np.isfinite(pixels).all(), "CPU render produced NaN/Inf"
    assert stats["mean"] > 1e-4, (
        f"CPU render is essentially black ({_explain(stats, 'cpu')}); the tail "
        f"ratio of a black image is meaningless"
    )

    assert stats["ratio"] >= FIREFLY_TAIL_RATIO_MIN, (
        f"{_explain(stats, 'cpu')} -- pkg161 contract item 2 requires "
        f">= {FIREFLY_TAIL_RATIO_MIN}x. If n_fireflies is 0 the emitter is too "
        f"small (or too few samples); if n_fireflies exceeds 0.1% of pixels the "
        f"99.9th percentile is itself a firefly and the emitter is too large. "
        f"Run scripts/verify_pkg161_firefly_scene.py to recalibrate "
        f"scenes/firefly_window.py's constants -- do NOT lower this threshold."
    )


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build; /verify runs this on the RTX box.",
)
def test_firefly_scene_has_heavy_tail_gpu():
    """GPU-wavefront leg, at the exact configuration pkg157's un-skipped
    firefly gate uses. This is the measurement pkg161 contract item 2 is
    written against."""
    pixels = _firefly_render(
        width=firefly.WIDTH, height=firefly.HEIGHT,
        samples=firefly.SAMPLES, seed=firefly.SEED, use_gpu=True,
    )
    stats = firefly.tail_stats(pixels)

    assert np.isfinite(pixels).all(), "GPU render produced NaN/Inf"
    assert stats["mean"] > 1e-4, (
        f"GPU render is essentially black ({_explain(stats, 'gpu')})"
    )
    assert stats["n_fireflies"] > 0, (
        f"{_explain(stats, 'gpu')} -- no pixel sits an order of magnitude above "
        f"the tail cut, so there is no firefly population to suppress and "
        f"pkg157's clamp gate would pass vacuously. Grow EMITTER_RADIUS."
    )
    assert stats["n_fireflies"] < 0.001 * stats["n_pixels"], (
        f"{_explain(stats, 'gpu')} -- the firefly population is larger than the "
        f"top 0.1%, so the 99.9th percentile is itself a firefly and the ratio "
        f"below understates the tail. Shrink EMITTER_RADIUS."
    )
    assert stats["ratio"] >= FIREFLY_TAIL_RATIO_MIN, (
        f"{_explain(stats, 'gpu')} -- pkg161 contract item 2 requires "
        f">= {FIREFLY_TAIL_RATIO_MIN}x. Run "
        f"scripts/verify_pkg161_firefly_scene.py to recalibrate "
        f"scenes/firefly_window.py -- do NOT lower this threshold."
    )

    # THE ASSERTION THAT MAKES THE TAIL PROVABLY *VARIANCE*.
    # Every check above would also pass if the camera could see some small,
    # very bright OBJECT -- a specular image of the emitter through the pane,
    # say. That is a deterministic feature, not a firefly, and it would set
    # `peak` while suppressing nothing when clamped for the right reason. It is
    # exactly the class of fake tail that would let pkg157's gate pass
    # vacuously for a fourth time.
    #
    # Fireflies move when the RNG stream moves; bright objects do not. So
    # re-render at a different seed and require the firefly pixel LOCATIONS to
    # decorrelate. (Seeds are nonzero: 0 is the std::random_device sentinel,
    # raytracer.h:2803, memory `seed-zero-is-random-sentinel`.)
    other = _firefly_render(
        width=firefly.WIDTH, height=firefly.HEIGHT,
        samples=firefly.SAMPLES, seed=firefly.SEED + 3, use_gpu=True,
    )
    other_stats = firefly.tail_stats(other)
    hot_a = firefly.luminance(pixels) > 10.0 * stats["p99_9"]
    hot_b = firefly.luminance(other) > 10.0 * other_stats["p99_9"]
    n_common = int((hot_a & hot_b).sum())
    smaller = max(1, min(int(hot_a.sum()), int(hot_b.sum())))
    overlap = n_common / smaller
    assert overlap < 0.5, (
        f"{stats['n_fireflies']} bright pixels at seed {firefly.SEED} and "
        f"{other_stats['n_fireflies']} at seed {firefly.SEED + 3} overlap in "
        f"{n_common} locations ({100.0 * overlap:.1f}%) -- a firefly "
        f"population decorrelates completely between seeds, so this tail is a "
        f"DETERMINISTIC bright feature, not variance. Most likely the camera "
        f"can reach the hidden emitter through a specular chain (check that "
        f"the pane and the aperture are out of frame in "
        f"scenes/firefly_window.setup_camera). Clamping such a feature proves "
        f"nothing about firefly suppression."
    )


def test_tail_metric_discriminates():
    """NEGATIVE CONTROLS: the same measurement must FAIL on inputs that have no
    firefly tail. Without this, `ratio >= 10` could be measuring an artifact of
    the metric rather than a property of the scene.

    Both legs run on CPU so they execute in CI, where there is no GPU.
    """
    # (a) The flattest scene in the library. Measured 1.07x / 1.04x at
    #     16 / 64 spp on RTX 5070 Ti 2026-07-26.
    flat_pixels = _render(
        metal_cornell.build_scene, metal_cornell.setup_camera,
        width=160, height=160, samples=32, max_depth=8, seed=16102,
        use_gpu=False, apply_gamma=False,
    )
    flat = firefly.tail_stats(flat_pixels)
    assert flat["mean"] > 1e-4, _explain(flat, "metal_cornell")
    assert flat["ratio"] < NO_TAIL_RATIO_MAX, (
        f"{_explain(flat, 'metal_cornell')} -- metal_cornell has NO firefly "
        f"population (measured 1.07x / 1.04x on RTX). A tail ratio at or above "
        f"{NO_TAIL_RATIO_MAX} here means the metric is responding to something "
        f"other than fireflies, and every pkg161/pkg157 conclusion drawn from "
        f"it is suspect."
    )
    assert flat["ratio"] < FIREFLY_TAIL_RATIO_MIN, (
        "the firefly bar must be unreachable by a scene with no fireflies"
    )

    # (b) The firefly scene through the gamma path. render()'s 4th positional
    #     argument is apply_gamma and DEFAULTS TO TRUE; it clamps to [0, 1]
    #     before the 1/2.2 power, so every firefly collapses to exactly 1.0 and
    #     the tail disappears. Small render -- this asserts a property of the
    #     output transform, not of the scene, so it needs no firefly count.
    gamma_pixels = _firefly_render(
        width=120, height=90, samples=16, seed=16103, use_gpu=False,
        apply_gamma=True,
        emitter_radius=firefly.EMITTER_RADIUS * firefly.CPU_EMITTER_RADIUS_SCALE,
    )
    gamma = firefly.tail_stats(gamma_pixels)
    assert gamma["peak"] <= 1.0 + 1e-6, (
        f"gamma render peak={gamma['peak']:.6g} > 1.0 -- the [0,1] clamp in "
        f"module/blender_module.cpp:1803-1811 is gone, and this control no "
        f"longer proves what it claims"
    )
    assert gamma["ratio"] < NO_TAIL_RATIO_MAX, (
        f"{_explain(gamma, 'firefly_window @ apply_gamma=True')} -- a "
        f"gamma-rendered tail measurement is supposed to be MEANINGLESS "
        f"(the clamp destroys the outliers). Seeing a real tail here means the "
        f"output transform changed and every linear/gamma assumption in pkg161 "
        f"needs rechecking."
    )
