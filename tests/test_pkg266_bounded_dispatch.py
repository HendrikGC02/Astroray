"""pkg266 Viewport Phase 2.3 — cancellation-bounded GPU wavefront dispatch.

The GPU wavefront render can now be launched in bounded work units: passing
`sub_pass_budget=N` to `renderer.render(...)` makes the driver call
`cudaDeviceSynchronize()` + poll the cancel hook every N wavefront passes, so a
cancel takes effect within one bounded unit instead of after the whole async
launch backlog drains (the P2.2 cancel-p99-over-budget root cause, Terra review
4 / design §13). A host-side sync does NOT change device execution order, so
`sub_pass_budget > 0` is numerically identical to the fully-async `= 0` path —
this file asserts both the cancel bound and that on-vs-off agree within the
GPU's own run-to-run atomic-add noise floor (GPU accumulation is not bit-stable
run to run — see test_pkg241_cancellation.py).

`last_render_info()` gains `units_launched` (bounded sync-units completed) and
`cancelled_at_unit` (the unit the cancel was observed at, -1 if not cancelled).
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# base_helpers configures the build-dir sys.path and imports astroray; keep this
# import before `import astroray` (isort would reorder it).
from base_helpers import (  # noqa: I001
    create_cornell_box,
    create_renderer,
    setup_camera,
)
import astroray

# Fixed non-zero seed: seed 0 is the std::random_device sentinel (memory
# seed-zero-is-random-sentinel), so on/off agreement requires a real seed.
FIXED_SEED = 1234


def _cornell(width, height):
    r = create_renderer()
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 width=width, height=height)
    create_cornell_box(r)
    r.set_seed(FIXED_SEED)
    r.set_use_gpu(True)
    return r


def _has_cuda_gpu(renderer):
    return (astroray is not None
            and bool(astroray.__features__.get("cuda", False))
            and bool(getattr(renderer, "gpu_available", False)))


def _skip_if_no_gpu():
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")


# ---------------------------------------------------------------------------
# last_render_info() reports the new bounded-unit fields
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_last_render_info_has_bounded_unit_fields():
    """A completed GPU render exposes units_launched / cancelled_at_unit; with
    sub-pass dispatch OFF (budget 0) no units are launched and the render is not
    cancelled."""
    _skip_if_no_gpu()
    r = _cornell(96, 96)
    r.render(16, 6, None, False, sub_pass_budget=0)
    info = r.last_render_info()
    assert info["cancelled"] is False
    assert info["units_launched"] == 0
    assert info["cancelled_at_unit"] == -1


@pytest.mark.gpu
def test_subpass_dispatch_counts_units():
    """With a small sub-pass budget and an always-continue callback, the driver
    completes several bounded units (it syncs every `budget` passes) and finishes
    the frame without cancelling."""
    _skip_if_no_gpu()
    r = _cornell(96, 96)

    def always_continue(_frac):
        return True

    # 16 spp x depth 6 is many wavefront passes; a budget of 2 passes/unit yields
    # multiple completed units.
    r.render(16, 6, always_continue, False, sub_pass_budget=2)
    info = r.last_render_info()
    assert info["cancelled"] is False
    assert info["cancelled_at_unit"] == -1
    assert info["units_launched"] >= 1, (
        f"expected the bounded loop to sync at least one unit, "
        f"got {info['units_launched']}")


# ---------------------------------------------------------------------------
# Cancel is acknowledged within one bounded unit
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_cancel_acknowledged_at_the_first_completed_unit():
    """Terra review (item 4): run THROUGH the first bounded-unit boundary, then
    cancel at the poll that follows a completed unit's cudaDeviceSynchronize().

    The old pkg241 hook polled the cancel callback EVERY pass with no bounded
    sync, so it had no notion of a 'unit' — `units_launched` stays 0 and
    `cancelled_at_unit` cannot record a completed unit. This test therefore FAILS
    against a build with the old per-pass hook only (units_launched == 0 /
    cancelled_at_unit == 0 before any unit synced) and passes only with the
    bounded-dispatch driver: it asserts at least one unit COMPLETED before the
    cancel and that the cancel was attributed to that completed unit.

    The driver polls the cancel hook every pass but only SYNCS + counts a unit at
    each `budget`-pass boundary (pass % budget == 0), before that poll. With
    budget == 2 the poll sequence is: pass 0 (no unit), pass 1 (no unit), pass 2
    (unit 1 just synced), … so cancelling on the third poll lands immediately
    after the first bounded unit completed — units_launched >= 1 and
    cancelled_at_unit == 1. The live unit count is not exposed to the callback
    (last_render_info() publishes only after the render returns), so the test
    drives the boundary by counting polls, which is deterministic given the fixed
    budget."""
    _skip_if_no_gpu()
    r = _cornell(96, 96)

    # Continue through the first two polls (passes 0,1 — no unit synced yet) and
    # cancel on the third (pass 2), which lands right after the first unit's
    # cudaDeviceSynchronize(). budget=2 makes this deterministic.
    state = {"calls": 0}

    def cancel_after_first_unit(_frac):
        state["calls"] += 1
        return state["calls"] < 3   # cancel on the 3rd poll (post first-unit sync)

    pixels = np.asarray(
        r.render(32, 6, cancel_after_first_unit, False, sub_pass_budget=2),
        dtype=np.float32)
    info = r.last_render_info()

    assert info["cancelled"] is True
    # A bounded unit COMPLETED before the cancel — the old per-pass hook could not
    # produce this (it never synced a unit; units_launched would be 0).
    assert info["units_launched"] >= 1, (
        f"no bounded unit completed before cancel (units_launched="
        f"{info['units_launched']}) — bounded dispatch inactive / old hook")
    # The cancel was attributed to the completed unit it followed, and remains
    # bounded to an early unit (not the full 32-spp / depth-6 pass backlog).
    assert info["cancelled_at_unit"] >= 1
    assert info["cancelled_at_unit"] <= 4, (
        f"cancel took {info['cancelled_at_unit']} units — not bounded")
    assert pixels.shape == (96, 96, 3)
    assert np.all(np.isfinite(pixels))
    assert np.all(pixels >= 0.0)


# ---------------------------------------------------------------------------
# Sub-pass dispatch ON is numerically identical to OFF at equal spp
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_subpass_on_matches_off_within_atomic_noise():
    """The bounded-dispatch acceptance criterion: the full-resolution result with
    sub-pass dispatch ON (a nonzero budget) matches the fully-async OFF path at
    equal spp. A host cudaDeviceSynchronize() does not change device execution
    order, so the ONLY residual is GPU atomicAdd non-associativity, which is not
    bit-stable run to run even for the OFF path against itself. This test first
    measures that run-to-run noise floor (OFF vs OFF) and then asserts ON-vs-OFF
    adds no divergence beyond it — the honest form of the spec's 'byte-identity
    on vs off'."""
    _skip_if_no_gpu()
    spp, depth = 24, 6

    off_a = np.asarray(_cornell(80, 80).render(spp, depth, None, False,
                                               sub_pass_budget=0),
                       dtype=np.float32)
    off_b = np.asarray(_cornell(80, 80).render(spp, depth, None, False,
                                               sub_pass_budget=0),
                       dtype=np.float32)
    # The GPU's own run-to-run atomic-reorder floor for this render.
    noise_floor = float(np.max(np.abs(off_a - off_b)))

    def always_continue(_frac):
        return True

    on = np.asarray(_cornell(80, 80).render(spp, depth, always_continue, False,
                                            sub_pass_budget=2),
                    dtype=np.float32)
    on_vs_off = float(np.max(np.abs(on - off_a)))

    # ON must not diverge from OFF by more than the OFF-vs-OFF atomic noise floor
    # (with a tiny absolute cushion for the case the floor is ~0). Also well
    # under the §9 max-abs comparator bound (2e-2).
    assert on_vs_off <= max(noise_floor + 1e-4, 1e-4), (
        f"sub-pass dispatch changed the result beyond the atomic-noise floor: "
        f"on_vs_off={on_vs_off:.3e}, off_vs_off floor={noise_floor:.3e}")
    assert on_vs_off <= 2e-2, (
        f"on_vs_off {on_vs_off:.3e} exceeds the §9 max-abs comparator bound")
