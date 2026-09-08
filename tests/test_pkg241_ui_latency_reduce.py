"""pkg241 P2.2 items 2+3: unit-test the driver's generation-tagged event
reduction (`blender_driver._reduce_spike_events`) — a pure function over the
lifeline event stream, so it runs outside Blender with a synthetic stream.

Covers the two metrics P2.2 adds to the §9 reduction:
  - commit_cost   (item 2): per-generation main-thread commit ms
                  (commit_start -> commit_end);
  - cancel_ack_pump (item 3): end-to-end cancel-ack through the pump
                  (cancel_request -> the next idle_drain, i.e. when the main
                  thread actually consumed the worker's idle), distinct from the
                  worker-side cancel_ack (-> idle_ack at enqueue time).
"""

import importlib.util
import os

_DRIVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "viewport_parity", "blender_driver.py")
_spec = importlib.util.spec_from_file_location("astroray_blender_driver", _DRIVER_PATH)
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)


def _ev(name, gen, t, extra=None):
    return (name, gen, float(t), 0, extra or {})


def test_reduce_reports_commit_and_pump_cancel_metrics():
    # Two generations. Gen 1: committed (10 ms), rendered, then superseded by a
    # cancel; its idle is enqueued (idle_ack) and drained by the pump later
    # (idle_drain) — the pump wait is the difference. Gen 2: committed (2 ms),
    # rendered, presented.
    events = [
        _ev("request", 1, 0.000),
        _ev("commit_start", 1, 0.001),
        _ev("commit_end", 1, 0.011),          # commit 10 ms
        _ev("render_start", 1, 0.012),
        _ev("cancel_request", 1, 0.050),      # edit supersedes gen 1
        _ev("request", 2, 0.050),
        _ev("render_end", 1, 0.060),
        _ev("idle_ack", 1, 0.061),            # worker enqueues idle
        _ev("idle_drain", 1, 0.075),          # main-thread pump consumes it (14 ms later)
        _ev("commit_start", 2, 0.080),
        _ev("commit_end", 2, 0.082),          # commit 2 ms
        _ev("render_start", 2, 0.083),
        _ev("render_end", 2, 0.120),
        _ev("mailbox_enqueue", 2, 0.120, {"depth_after": 1}),
        _ev("mailbox_dequeue", 2, 0.130, {"depth_before": 1}),
        _ev("texture_upload_end", 2, 0.132),
        _ev("first_blit", 2, 0.133),
    ]
    out = driver._reduce_spike_events(events)
    assert out is not None

    # commit_cost: two generations, ~10 ms and ~2 ms.
    cc = out["commit_cost"]
    assert cc is not None and cc["n"] == 2
    assert abs(cc["max_ms"] - 10.0) < 0.5

    # worker-side cancel-ack: cancel_request(0.050) -> idle_ack(0.061) ~= 11 ms.
    ca = out["cancel_ack"]
    assert ca is not None and abs(ca["p50_ms"] - 11.0) < 1.0

    # end-to-end through the pump: cancel_request(0.050) -> idle_drain(0.075) ~= 25 ms.
    cap = out["cancel_ack_pump"]
    assert cap is not None and abs(cap["p50_ms"] - 25.0) < 1.0
    # the pump ack is strictly >= the worker-side ack (it includes the drain wait).
    assert cap["p50_ms"] >= ca["p50_ms"]

    # gen 2 completed and reached a first_blit -> present rate defined and 1.0.
    assert out["completed_generations"] == 1
    assert out["present_rate"] == 1.0
    assert out["mailbox_depth_max"] == 1


def test_cancel_ack_pairs_by_generation_not_by_timestamp():
    """pkg241 P2.2 item 4 (Terra review 4): a cancel_request(g) must pair only
    with the idle_ack(g)/idle_drain(g) of the SAME generation. Here gen 2's idle
    events land (by wall time) between cancel_request(1) and gen 1's own idle; the
    old timestamp-only pairing would have matched cancel(1) with idle(2) and
    reported a bogus ~10 ms ack. The generation-paired reducer must skip gen 2 and
    measure cancel_request(1)->idle_drain(1) = 200 ms."""
    events = [
        _ev("request", 1, 0.000),
        _ev("render_start", 1, 0.001),
        _ev("cancel_request", 1, 0.010),     # gen 1 in-flight, superseded
        _ev("request", 2, 0.010),
        # an unrelated gen 2 completes and idles FIRST (earlier timestamp):
        _ev("idle_ack", 2, 0.020),
        _ev("idle_drain", 2, 0.025),
        # gen 1's own idle arrives later:
        _ev("idle_ack", 1, 0.180),           # worker-side ack 170 ms
        _ev("idle_drain", 1, 0.210),         # end-to-end through the pump 200 ms
    ]
    out = driver._reduce_spike_events(events)
    assert out is not None
    # cancel_ack (worker-side) must pair with idle_ack(1), not idle_ack(2).
    assert abs(out["cancel_ack"]["p50_ms"] - 170.0) < 1.0
    # cancel_ack_pump (the gate) must pair with idle_drain(1), not idle_drain(2).
    assert abs(out["cancel_ack_pump"]["p50_ms"] - 200.0) < 1.0


def test_reduce_returns_none_on_synchronous_path():
    # No events (worker flag off) -> None, so the synchronous path is unaffected.
    assert driver._reduce_spike_events([]) is None
