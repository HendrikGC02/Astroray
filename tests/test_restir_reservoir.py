"""
pkg20 — ReSTIR reservoir core tests.

Covers the Reservoir<float> invariants through the FloatReservoir test helper
(a thin pybind11 wrapper that holds the RNG internally so tests can seed it).

Test strategy:
  - Deterministic invariant checks: seeded, exact results.
  - Edge-case weight handling: zero, negative, NaN, Inf.
  - Merge correctness: M accumulation and w_sum combining.
  - Loose distribution sanity: fraction of selections within wide tolerance.
"""

import math
import pytest


@pytest.fixture(scope="module")
def reservoir_cls(astroray_module):
    return astroray_module.FloatReservoir


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_fresh_reservoir_is_zero(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        assert r.w_sum == 0.0
        assert r.M == 0
        assert r.W == 0.0
        assert r.y == 0.0

    def test_reset_clears_state(self, reservoir_cls):
        r = reservoir_cls(seed=1)
        r.update(5.0, 2.0)
        r.finalize_weight(1.0)
        r.reset()
        assert r.w_sum == 0.0
        assert r.M == 0
        assert r.W == 0.0
        assert r.y == 0.0


# ---------------------------------------------------------------------------
# Update — invariants
# ---------------------------------------------------------------------------

class TestUpdateInvariants:
    def test_m_increments_each_call(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        for i in range(1, 6):
            r.update(float(i), 1.0)
            assert r.M == i

    def test_w_sum_accumulates(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(1.0, 0.5)
        r.update(2.0, 1.5)
        assert math.isclose(r.w_sum, 2.0, rel_tol=1e-6)

    def test_zero_weight_increments_m_but_not_w_sum(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(99.0, 0.0)
        assert r.M == 1
        assert r.w_sum == 0.0
        assert r.y == 0.0  # default; zero-weight can't win

    def test_negative_weight_treated_as_zero(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(99.0, -3.0)
        assert r.M == 1
        assert r.w_sum == 0.0
        assert r.y == 0.0

    def test_nan_weight_treated_as_zero(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(99.0, float("nan"))
        assert r.M == 1
        assert r.w_sum == 0.0
        assert r.y == 0.0

    def test_inf_weight_treated_as_zero(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(99.0, float("inf"))
        assert r.M == 1
        assert r.w_sum == 0.0
        assert r.y == 0.0

    def test_w_sum_not_poisoned_after_bad_weights(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(1.0, float("nan"))
        r.update(2.0, float("inf"))
        r.update(3.0, -5.0)
        r.update(4.0, 2.0)   # valid weight
        assert math.isclose(r.w_sum, 2.0, rel_tol=1e-6)
        assert r.M == 4
        assert r.y == 4.0    # only 4.0 had positive weight

    def test_single_candidate_always_selected(self, reservoir_cls):
        for seed in range(10):
            r = reservoir_cls(seed=seed)
            r.update(7.0, 3.0)
            assert r.y == 7.0


# ---------------------------------------------------------------------------
# Finalize weight
# ---------------------------------------------------------------------------

class TestFinalizeWeight:
    def test_finalize_basic(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(1.0, 2.0)   # w_sum=2, M=1
        r.finalize_weight(1.0)
        # W = w_sum / (p_hat * M) = 2 / (1 * 1) = 2
        assert math.isclose(r.W, 2.0, rel_tol=1e-6)

    def test_finalize_zero_m_gives_zero_w(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.finalize_weight(1.0)
        assert r.W == 0.0

    def test_finalize_zero_p_hat_gives_zero_w(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(1.0, 1.0)
        r.finalize_weight(0.0)
        assert r.W == 0.0

    def test_finalize_negative_p_hat_gives_zero_w(self, reservoir_cls):
        r = reservoir_cls(seed=0)
        r.update(1.0, 1.0)
        r.finalize_weight(-1.0)
        assert r.W == 0.0


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

class TestMerge:
    def test_merge_accumulates_m(self, reservoir_cls):
        r1 = reservoir_cls(seed=10)
        r1.update(1.0, 1.0)
        r1.finalize_weight(1.0)

        r2 = reservoir_cls(seed=20)
        r2.update(2.0, 3.0)
        r2.finalize_weight(1.0)

        r1.merge(r2, target_pdf=1.0)
        assert r1.M == 2

    def test_merge_w_sum_combines(self, reservoir_cls):
        # r1: w_sum=1, W=1, M=1 → merge weight = W * target_pdf * M = 1*1*1 = 1
        # r2: w_sum=3, W=3, M=1 → merge weight = 3*1*1 = 3
        # combined w_sum = 1 + 3 = 4
        r1 = reservoir_cls(seed=10)
        r1.update(1.0, 1.0)
        r1.finalize_weight(1.0)   # W=1

        r2 = reservoir_cls(seed=20)
        r2.update(2.0, 3.0)
        r2.finalize_weight(1.0)   # W=3

        initial_w_sum = r1.w_sum  # 1.0
        r1.merge(r2, target_pdf=1.0)
        assert math.isclose(r1.w_sum, initial_w_sum + r2.W * 1.0 * r2.M, rel_tol=1e-5)

    def test_merge_empty_other_leaves_m_unchanged(self, reservoir_cls):
        r1 = reservoir_cls(seed=10)
        r1.update(1.0, 1.0)
        r1.finalize_weight(1.0)
        m_before = r1.M  # 1

        r_empty = reservoir_cls(seed=99)  # M=0, W=0
        r1.merge(r_empty, target_pdf=1.0)
        assert r1.M == m_before  # 1 + 0 = 1


# ---------------------------------------------------------------------------
# Deterministic seeded sequence
# ---------------------------------------------------------------------------

class TestDeterminism:
    def _run_sequence(self, reservoir_cls, seed):
        r = reservoir_cls(seed=seed)
        r.update(1.0, 0.5)
        r.update(2.0, 1.5)
        r.update(3.0, 0.3)
        return r.y, r.w_sum, r.M

    def test_same_seed_same_result(self, reservoir_cls):
        a = self._run_sequence(reservoir_cls, seed=42)
        b = self._run_sequence(reservoir_cls, seed=42)
        assert a == b

    def test_different_seeds_may_differ(self, reservoir_cls):
        results = {self._run_sequence(reservoir_cls, seed=s)[0] for s in range(20)}
        # With 3 distinct candidates and 20 seeds, at least 2 distinct y values expected
        assert len(results) >= 2

    def test_w_sum_is_deterministic_regardless_of_seed(self, reservoir_cls):
        # w_sum is path-independent: it only depends on the weights, not the RNG
        for seed in range(5):
            _, w_sum, M = self._run_sequence(reservoir_cls, seed=seed)
            assert math.isclose(w_sum, 2.3, rel_tol=1e-5)
            assert M == 3


# ---------------------------------------------------------------------------
# Distribution sanity (loose tolerance)
# ---------------------------------------------------------------------------

class TestDistribution:
    def test_two_candidate_selection_probability(self, reservoir_cls):
        """
        With candidates x=1 (w=1) and x=2 (w=3), the probability of selecting
        x=2 should be 3/(1+3) = 0.75. Check within ±10 percentage points.
        """
        n = 10_000
        selected_two = 0
        for seed in range(n):
            r = reservoir_cls(seed=seed)
            r.update(1.0, 1.0)
            r.update(2.0, 3.0)
            if r.y == 2.0:
                selected_two += 1

        fraction = selected_two / n
        assert abs(fraction - 0.75) < 0.10, (
            f"Expected ~0.75 selection of x=2, got {fraction:.3f}"
        )

    def test_uniform_weights_approach_uniform_selection(self, reservoir_cls):
        """Four equal-weight candidates should each be selected ~25% of the time."""
        n = 10_000
        counts = {1.0: 0, 2.0: 0, 3.0: 0, 4.0: 0}
        for seed in range(n):
            r = reservoir_cls(seed=seed)
            for x in [1.0, 2.0, 3.0, 4.0]:
                r.update(x, 1.0)
            counts[r.y] = counts.get(r.y, 0) + 1

        for x, count in counts.items():
            fraction = count / n
            assert abs(fraction - 0.25) < 0.05, (
                f"Candidate {x}: expected ~0.25, got {fraction:.3f}"
            )
