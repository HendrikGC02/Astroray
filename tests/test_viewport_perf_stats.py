#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg56 Phase A — viewport-sync per-stage perf ring buffer tests.

Exercises the C++ ring buffer behind ``astroray.record_viewport_stage`` /
``astroray.viewport_perf_frame_complete`` / ``astroray.viewport_perf_stats``
without spinning up Blender. The ring buffer is the "before" baseline
Phase C optimises against — these tests just lock down its mechanics.
"""

import time

import pytest


@pytest.fixture(autouse=True)
def _reset_perf(astroray_module):
    """Clear the ring buffer before and after every test so order doesn't matter."""
    astroray_module.viewport_perf_reset()
    yield
    astroray_module.viewport_perf_reset()


def _record_frame(astroray, **stage_ms):
    """Record a single frame's worth of stage timings, then close it."""
    for stage, ms in stage_ms.items():
        astroray.record_viewport_stage(stage, ms)
    astroray.viewport_perf_frame_complete()


def test_empty_ring_returns_zeros(astroray_module):
    stats = astroray_module.viewport_perf_stats()
    assert stats["frames"] == 0
    for stage in ("geometry", "materials", "lights", "environment", "render"):
        assert stats[stage] == 0.0
    assert stats["total"] == 0.0


def test_single_frame_mean_equals_input(astroray_module):
    _record_frame(
        astroray_module,
        geometry=10.0, materials=2.0, lights=1.0,
        environment=0.5, render=20.0,
    )
    stats = astroray_module.viewport_perf_stats()
    assert stats["frames"] == 1
    assert stats["geometry"] == pytest.approx(10.0)
    assert stats["materials"] == pytest.approx(2.0)
    assert stats["lights"] == pytest.approx(1.0)
    assert stats["environment"] == pytest.approx(0.5)
    assert stats["render"] == pytest.approx(20.0)
    assert stats["total"] == pytest.approx(33.5)


def test_mean_across_multiple_frames(astroray_module):
    for ms in (10.0, 20.0, 30.0):
        _record_frame(astroray_module, geometry=ms)
    stats = astroray_module.viewport_perf_stats()
    assert stats["frames"] == 3
    assert stats["geometry"] == pytest.approx(20.0)


def test_within_frame_accumulation(astroray_module):
    # Two record calls inside one frame should sum, not overwrite.
    astroray_module.record_viewport_stage("materials", 1.5)
    astroray_module.record_viewport_stage("materials", 2.5)
    astroray_module.viewport_perf_frame_complete()
    stats = astroray_module.viewport_perf_stats()
    assert stats["materials"] == pytest.approx(4.0)
    assert stats["frames"] == 1


def test_unknown_stage_raises(astroray_module):
    with pytest.raises((ValueError, RuntimeError)):
        astroray_module.record_viewport_stage("bogus_stage", 1.0)


def test_ring_buffer_rolls_at_capacity(astroray_module):
    # Capacity is 100. Push 150 frames, each stamped with its index in
    # `geometry`. The mean should reflect only the last 100 indices
    # (50..149), i.e. (50+149)/2 = 99.5.
    for i in range(150):
        _record_frame(astroray_module, geometry=float(i))
    stats = astroray_module.viewport_perf_stats()
    assert stats["frames"] == 100
    assert stats["geometry"] == pytest.approx(99.5)


def test_reset_clears_ring(astroray_module):
    _record_frame(astroray_module, geometry=5.0, render=10.0)
    astroray_module.viewport_perf_reset()
    stats = astroray_module.viewport_perf_stats()
    assert stats["frames"] == 0
    assert stats["geometry"] == 0.0
    assert stats["render"] == 0.0


def test_in_flight_accumulator_cleared_by_frame_complete(astroray_module):
    # First frame contributes, second frame is "empty" — the in-flight
    # accumulator must reset between frame_complete calls so the second
    # frame doesn't inherit the first's totals.
    _record_frame(astroray_module, render=8.0)
    astroray_module.viewport_perf_frame_complete()  # empty second frame
    stats = astroray_module.viewport_perf_stats()
    assert stats["frames"] == 2
    assert stats["render"] == pytest.approx(4.0)  # 8.0 / 2


def test_in_flight_accumulator_cleared_by_reset(astroray_module):
    # Recording without closing leaves data in the in-flight buffer; reset
    # must wipe it so the next frame starts clean.
    astroray_module.record_viewport_stage("geometry", 99.0)
    astroray_module.viewport_perf_reset()
    astroray_module.record_viewport_stage("geometry", 1.0)
    astroray_module.viewport_perf_frame_complete()
    stats = astroray_module.viewport_perf_stats()
    assert stats["geometry"] == pytest.approx(1.0)


def test_mean_monotonic_with_scene_complexity(astroray_module):
    """A bigger scene should produce a larger mean than a smaller scene.

    Phase A is pure measurement, so we model scene complexity directly:
    sleep N×10 µs to stand in for "more triangles → longer geometry
    upload". The point is to lock down that the ring buffer's mean
    correctly tracks input magnitude — i.e. the overlay number actually
    moves with the scene, which is the property Phase C will optimise.
    """
    def _bench(triangles_proxy):
        astroray_module.viewport_perf_reset()
        for _ in range(5):
            t0 = time.perf_counter()
            # Tight spin proportional to "scene size". perf_counter has
            # sub-µs resolution on every supported platform; sleep(0)
            # would round to zero on Windows and break the test.
            target = t0 + triangles_proxy * 1e-4
            while time.perf_counter() < target:
                pass
            ms = (time.perf_counter() - t0) * 1000.0
            astroray_module.record_viewport_stage("geometry", ms)
            astroray_module.viewport_perf_frame_complete()
        return astroray_module.viewport_perf_stats()["geometry"]

    small = _bench(triangles_proxy=1)    # ~0.1 ms per frame
    big   = _bench(triangles_proxy=20)   # ~2.0 ms per frame
    assert big > small, f"expected big ({big}) > small ({small})"
