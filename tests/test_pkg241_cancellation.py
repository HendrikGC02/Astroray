"""pkg241 Phase 1b — cooperative render cancellation (native CPU + GPU).

The progress callback now returns a bool (True = continue, False = cancel).
`renderer.render(...)` honours it: the CPU tile loop stops scheduling new tiles,
the GPU wavefront driver stops between passes, and both return the partial
framebuffer accumulated so far. `renderer.last_render_info()` reports whether the
last render completed or was cancelled and (CPU) how many tiles finished.

Ordinary completion (progress=None, or a callback that always returns True) is
unchanged — the null-callback path is byte-identical to the pre-pkg241 code.

Companion addon-level unit tests (the viewport cancel flag + accumulation reset)
live in test_pkg241_cancellation_addon.py; this file exercises the native
Renderer directly, mirroring tests/base_helpers.py.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# base_helpers configures the build-dir sys.path and imports astroray; it must be
# imported before `import astroray`, so keep this order (isort would reorder it).
from base_helpers import (  # noqa: I001
    create_cornell_box,
    create_renderer,
    setup_camera,
)
import astroray

# A fixed non-zero seed: seed 0 is the std::random_device sentinel (memory
# seed-zero-is-random-sentinel), so determinism assertions require a real seed.
FIXED_SEED = 1234


def _cornell(width, height):
    r = create_renderer()
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 width=width, height=height)
    create_cornell_box(r)
    r.set_seed(FIXED_SEED)
    return r


def _has_cuda_gpu(renderer):
    return (astroray is not None
            and bool(astroray.__features__.get("cuda", False))
            and bool(getattr(renderer, "gpu_available", False)))


# ---------------------------------------------------------------------------
# CPU cooperative cancellation
# ---------------------------------------------------------------------------

def test_cpu_cancel_stops_early_and_returns_partial():
    """A callback returning False after N tiles stops the render well short of
    the full tile count and returns a valid partial framebuffer."""
    width, height = 320, 320  # 20x20 = 400 tiles at tileSize 16
    r = _cornell(width, height)

    cancel_after = 5
    state = {"calls": 0}

    def progress_cb(_frac):
        state["calls"] += 1
        return state["calls"] <= cancel_after  # False on call cancel_after+1

    pixels = np.asarray(r.render(8, 4, progress_cb, False), dtype=np.float32)
    info = r.last_render_info()

    assert info["cancelled"] is True, "render should report it was cancelled"
    total = info["total_tiles"]
    done = info["tiles_completed"]
    assert total > 100, f"expected many tiles for a {width}x{height} image, got {total}"
    # Stopped early: only a small fraction of tiles completed. OpenMP may finish
    # a few in-flight tiles after the cancel latches, so allow a generous thread
    # slack above cancel_after but well below the full count.
    assert done < total, f"cancel did not stop scheduling ({done}/{total})"
    assert done <= cancel_after + 64, f"stopped too late: {done} tiles (cancel_after={cancel_after})"
    assert done >= cancel_after, f"stopped too early: {done} tiles"

    # Partial framebuffer is well-formed: right shape, finite, non-negative, and
    # the completed tiles carry real (non-zero) radiance from the Cornell light.
    assert pixels.shape == (height, width, 3)
    assert np.all(np.isfinite(pixels))
    assert np.all(pixels >= 0.0)
    assert np.count_nonzero(pixels) > 0, "completed tiles should have content"


def test_cpu_null_progress_byte_identical():
    """progress=None is deterministic on a fixed seed, and a callback that always
    returns True yields the byte-identical image (the bool-return path does not
    perturb the ordinary render)."""
    a = np.asarray(_cornell(160, 120).render(16, 4, None, False), dtype=np.float32)
    b = np.asarray(_cornell(160, 120).render(16, 4, None, False), dtype=np.float32)
    np.testing.assert_array_equal(a, b)

    def always_continue(_frac):
        return True

    c = np.asarray(_cornell(160, 120).render(16, 4, always_continue, False),
                   dtype=np.float32)
    np.testing.assert_array_equal(a, c)

    info = _cornell(160, 120)
    px = info.render(16, 4, None, False)  # noqa: F841
    ri = info.last_render_info()
    assert ri["cancelled"] is False
    assert ri["tiles_completed"] == ri["total_tiles"] > 0


def test_cpu_non_bool_return_counts_as_continue():
    """A progress-only callback that returns None (no explicit bool) must not
    cancel — it counts as continue, preserving legacy progress-callback usage."""
    r = _cornell(128, 128)

    def progress_only(_frac):
        return None  # legacy fire-and-forget style

    pixels = np.asarray(r.render(8, 4, progress_only, False), dtype=np.float32)
    info = r.last_render_info()
    assert info["cancelled"] is False
    assert info["tiles_completed"] == info["total_tiles"]
    assert np.count_nonzero(pixels) > 0


# ---------------------------------------------------------------------------
# GPU cooperative cancellation (wavefront)
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_gpu_cancel_hook_stops_between_passes():
    """A callback returning False mid-render cancels the GPU wavefront within a
    small number of host-side pass checks and returns a valid partial frame."""
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")

    r = _cornell(96, 96)
    r.set_use_gpu(True)

    state = {"calls": 0}

    def cancel_second(_frac):
        state["calls"] += 1
        return state["calls"] < 2  # False on the 2nd poll

    pixels = np.asarray(r.render(16, 6, cancel_second, False), dtype=np.float32)
    info = r.last_render_info()

    assert info["cancelled"] is True, "GPU render should report cancellation"
    # Stopped early: the host poll fired only a handful of times, not once per
    # pass across every sample/round.
    assert state["calls"] <= 8, f"cancel did not stop early: {state['calls']} polls"
    assert pixels.shape == (96, 96, 3)
    assert np.all(np.isfinite(pixels))
    assert np.all(pixels >= 0.0)


@pytest.mark.gpu
def test_gpu_null_hook_matches_always_continue():
    """The null cancel hook (progress=None) leaves the GPU path unchanged: an
    always-continue callback produces the same image (the hook never breaks)."""
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")

    def gpu_render(cb):
        r = _cornell(96, 96)
        r.set_use_gpu(True)
        return np.asarray(r.render(32, 6, cb, False), dtype=np.float32)

    base = gpu_render(None)

    def always_continue(_frac):
        return True

    same = gpu_render(always_continue)
    info_r = _cornell(96, 96)
    info_r.set_use_gpu(True)
    info_r.render(32, 6, None, False)
    assert info_r.last_render_info()["cancelled"] is False

    # The always-continue hook does identical GPU work; only host-side Python
    # polls differ. GPU atomic-add ordering is not bit-stable run to run, so
    # assert numerical agreement rather than exact bytes.
    assert np.allclose(base, same, atol=2e-3), (
        f"null vs always-continue diverged: max |Δ|={np.max(np.abs(base - same))}")


def test_cpu_callback_exception_propagates_without_terminate():
    """cpp-abi-guard (PR #748): a Python exception raised inside the per-tile
    progress callback must surface as a Python exception, not unwind through
    the OpenMP parallel-for (undefined behaviour -> std::terminate on the
    OpenMP-ON dev .pyd). The binding stashes the exception, cancels the render
    cooperatively and rethrows after render() returns."""
    r = _cornell(160, 160)

    class Boom(RuntimeError):
        pass

    state = {"calls": 0}

    def progress_cb(_frac):
        state["calls"] += 1
        if state["calls"] == 3:
            raise Boom("callback failure")
        return True

    with pytest.raises(Boom):
        r.render(4, 3, progress_cb, False)
    info = r.last_render_info()
    assert info["cancelled"] is True
    assert info["tiles_completed"] < info["total_tiles"]
