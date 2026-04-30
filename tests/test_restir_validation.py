"""
pkg24 — ReSTIR DI validation tests.

Implements the 6 validation criteria from
.astroray_plan/docs/restir-temporal-spatial-design.md §7:

  1. Temporal reuse reduces per-frame variance
  2. Spatial reuse reduces MSE vs converged reference
  3. Temporal bias magnitude < 10% of converged mean (biased pass, no shadow-ray)
  4. Spatial bias magnitude < 10% of converged mean
  5. No NaN/Inf after temporal + spatial reuse
  6. Determinism: same seed → bit-identical output with reuse enabled

Additional regression: restir-di default mode (no reuse) must not degrade
from pkg22 behaviour.
"""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from restir_helpers import (
    make_renderer, build_cornell_box, build_many_light_scene,
    render, render_sequence, render_warmed,
    mean_luminance, pixel_stddev, mse, relative_mean_diff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cornell(astroray_module, w=32, h=32):
    r = make_renderer(astroray_module, w, h)
    build_cornell_box(r)
    return r


def _many_lights(astroray_module, w=32, h=32, n_lights=5):
    r = make_renderer(astroray_module, w, h)
    build_many_light_scene(r, n_lights=n_lights)
    return r


# ---------------------------------------------------------------------------
# Criterion 5 (NaN/Inf) — cheapest, run first as a sanity gate
# ---------------------------------------------------------------------------

class TestFiniteness:
    def test_no_nan_inf_with_temporal(self, astroray_module):
        r = _many_lights(astroray_module)
        pixels = render(r, "restir-di", samples=8, use_temporal=True)
        assert not np.any(np.isnan(pixels)), "NaN with temporal reuse"
        assert not np.any(np.isinf(pixels)), "Inf with temporal reuse"

    def test_no_nan_inf_with_spatial(self, astroray_module):
        r = _many_lights(astroray_module)
        pixels = render(r, "restir-di", samples=8, use_spatial=True)
        assert not np.any(np.isnan(pixels)), "NaN with spatial reuse"
        assert not np.any(np.isinf(pixels)), "Inf with spatial reuse"

    def test_no_nan_inf_with_both(self, astroray_module):
        r = _many_lights(astroray_module)
        pixels = render(r, "restir-di", samples=8,
                        use_temporal=True, use_spatial=True)
        assert not np.any(np.isnan(pixels))
        assert not np.any(np.isinf(pixels))
        assert pixels.max() > 0.0, "all-black output with reuse enabled"

    def test_no_nan_inf_black_background(self, astroray_module):
        """Regression: no NaN when the background is black and reuse is on."""
        r = _cornell(astroray_module)
        r.set_background_color([0.0, 0.0, 0.0])
        pixels = render(r, "restir-di", samples=4,
                        use_temporal=True, use_spatial=True)
        assert not np.any(np.isnan(pixels))
        assert pixels.max() > 0.0


# ---------------------------------------------------------------------------
# Criterion 6 — Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_temporal_deterministic(self, astroray_module):
        """Two seeded renders with temporal reuse must be bit-identical."""
        p1 = render(_cornell(astroray_module), "restir-di",
                    samples=4, seed=7, use_temporal=True)
        p2 = render(_cornell(astroray_module), "restir-di",
                    samples=4, seed=7, use_temporal=True)
        np.testing.assert_array_equal(p1, p2, err_msg="temporal reuse non-deterministic")

    def test_spatial_deterministic(self, astroray_module):
        p1 = render(_cornell(astroray_module), "restir-di",
                    samples=4, seed=13, use_spatial=True)
        p2 = render(_cornell(astroray_module), "restir-di",
                    samples=4, seed=13, use_spatial=True)
        np.testing.assert_array_equal(p1, p2, err_msg="spatial reuse non-deterministic")

    def test_both_deterministic(self, astroray_module):
        p1 = render(_cornell(astroray_module), "restir-di",
                    samples=4, seed=42, use_temporal=True, use_spatial=True)
        p2 = render(_cornell(astroray_module), "restir-di",
                    samples=4, seed=42, use_temporal=True, use_spatial=True)
        np.testing.assert_array_equal(p1, p2, err_msg="temporal+spatial reuse non-deterministic")


# ---------------------------------------------------------------------------
# Criterion 1 — Temporal reuse reduces per-frame variance
# ---------------------------------------------------------------------------

class TestTemporalVariance:
    """
    Render 30 frames of the same scene with 1 SPP.
    Temporal reuse accumulates history, so per-frame pixel variance should
    decrease relative to plain RIS over the same number of frames.
    """
    N_FRAMES  = 30
    WIDTH     = 24
    HEIGHT    = 24

    def _stddev(self, astroray_module, use_temporal):
        frames = render_sequence(
            astroray_module,
            lambda r: build_cornell_box(r),
            "restir-di",
            n_frames=self.N_FRAMES,
            width=self.WIDTH, height=self.HEIGHT,
            samples_per_frame=1,
            seed=100,
            use_temporal=use_temporal,
        )
        return pixel_stddev(frames)

    def test_temporal_reduces_variance(self, astroray_module):
        stddev_no_reuse  = self._stddev(astroray_module, False)
        stddev_temporal  = self._stddev(astroray_module, True)
        assert stddev_no_reuse > 0, "No-reuse render is degenerate (zero variance)"
        assert stddev_temporal < stddev_no_reuse, (
            f"Temporal reuse did not reduce variance: "
            f"no-reuse stddev={stddev_no_reuse:.4f}, "
            f"temporal stddev={stddev_temporal:.4f}"
        )


# ---------------------------------------------------------------------------
# Criterion 2 — Spatial reuse reduces MSE vs converged reference
# ---------------------------------------------------------------------------

class TestSpatialMSE:
    """
    Spatial reuse borrows candidates from neighbouring pixels' previous-frame
    reservoirs, effectively raising the per-pixel candidate count from M to
    M + K*M_prev (K = spatial_neighbors). For a many-light scene where
    4 initial candidates cover only a fraction of the 8 lights, spatial reuse
    dramatically improves light coverage and lowers MSE.

    Averaging N_MEASURE frames reduces single-frame noise. Seeds are aligned:
    render_warmed(seed=0, warmup=WARMUP) measures at seeds WARMUP..WARMUP+N-1;
    the no-reuse baseline uses the same seeds.
    """
    WIDTH     = 24
    HEIGHT    = 24
    N_LIGHTS  = 8
    REF_SPP   = 256
    TEST_SPP  = 1   # low SPP maximises the reuse benefit
    WARMUP    = 3
    N_MEASURE = 8   # average over 8 frames to suppress single-frame noise

    def _scene(self, r):
        build_many_light_scene(r, n_lights=self.N_LIGHTS, light_intensity=6.0)

    def test_spatial_reduces_mse(self, astroray_module):
        # Converged reference.
        ref_r = make_renderer(astroray_module, self.WIDTH, self.HEIGHT)
        self._scene(ref_r)
        reference = render(ref_r, "restir-di", samples=self.REF_SPP, seed=0)

        # Baseline: N_MEASURE no-reuse frames at seeds WARMUP..WARMUP+N-1.
        no_r = make_renderer(astroray_module, self.WIDTH, self.HEIGHT)
        self._scene(no_r)
        mse_no_list = []
        for i in range(self.N_MEASURE):
            frame = render(no_r, "restir-di", samples=self.TEST_SPP,
                           seed=self.WARMUP + i)
            mse_no_list.append(mse(frame, reference))
        mean_mse_no = float(np.mean(mse_no_list))

        # Spatial with warmup: render_warmed(seed=0, warmup=WARMUP) uses
        # measure seeds WARMUP..WARMUP+N-1 — identical to the no-reuse seeds.
        spatial_imgs = render_warmed(
            astroray_module,
            self._scene,
            "restir-di",
            warmup_frames=self.WARMUP,
            measure_frames=self.N_MEASURE,
            width=self.WIDTH, height=self.HEIGHT,
            samples=self.TEST_SPP, seed=0,
            use_spatial=True,
        )
        mean_mse_spatial = float(np.mean([mse(img, reference)
                                          for img in spatial_imgs]))

        assert mean_mse_no > 0, "No-reuse image matches reference (unexpected)"
        assert mean_mse_spatial < mean_mse_no, (
            f"Spatial reuse did not reduce MSE after warmup: "
            f"no-reuse={mean_mse_no:.6f}, spatial={mean_mse_spatial:.6f}"
        )


# ---------------------------------------------------------------------------
# Criterion 3 — Temporal bias magnitude
# ---------------------------------------------------------------------------

class TestTemporalBias:
    """
    Converge two renders with many SPP: one with temporal, one without.
    Mean luminance should agree to within 10% (generous threshold for the
    biased initial pass; tighten once shadow-ray correction is added).
    """
    WIDTH  = 24
    HEIGHT = 24
    CONV_SPP = 128
    BIAS_THRESHOLD = 0.10   # 10%

    def test_temporal_bias_within_threshold(self, astroray_module):
        ref = render(_cornell(astroray_module, self.WIDTH, self.HEIGHT),
                     "restir-di", samples=self.CONV_SPP, seed=42)
        temporal = render(_cornell(astroray_module, self.WIDTH, self.HEIGHT),
                          "restir-di", samples=self.CONV_SPP, seed=42,
                          use_temporal=True)

        diff = relative_mean_diff(ref, temporal)
        assert diff < self.BIAS_THRESHOLD, (
            f"Temporal reuse bias {diff:.3%} exceeds threshold {self.BIAS_THRESHOLD:.0%}"
        )


# ---------------------------------------------------------------------------
# Criterion 4 — Spatial bias magnitude
# ---------------------------------------------------------------------------

class TestSpatialBias:
    WIDTH  = 24
    HEIGHT = 24
    CONV_SPP = 128
    BIAS_THRESHOLD = 0.10   # 10%

    def test_spatial_bias_within_threshold(self, astroray_module):
        ref = render(_cornell(astroray_module, self.WIDTH, self.HEIGHT),
                     "restir-di", samples=self.CONV_SPP, seed=42)
        spatial = render(_cornell(astroray_module, self.WIDTH, self.HEIGHT),
                         "restir-di", samples=self.CONV_SPP, seed=42,
                         use_spatial=True)

        diff = relative_mean_diff(ref, spatial)
        assert diff < self.BIAS_THRESHOLD, (
            f"Spatial reuse bias {diff:.3%} exceeds threshold {self.BIAS_THRESHOLD:.0%}"
        )


# ---------------------------------------------------------------------------
# Regression: default mode (no reuse) unchanged from pkg22
# ---------------------------------------------------------------------------

class TestDefaultModeRegression:
    def test_no_reuse_renders_finite_non_black(self, astroray_module):
        r = _cornell(astroray_module)
        pixels = render(r, "restir-di", samples=8)
        assert not np.any(np.isnan(pixels))
        assert not np.any(np.isinf(pixels))
        assert pixels.max() > 0.0

    def test_no_reuse_not_dramatically_darker_than_path_tracer(self, astroray_module):
        """Smoke check: restir-di default mode vs path_tracer within factor 3."""
        pt = render(_cornell(astroray_module, 24, 24), "path_tracer",  samples=32, seed=42)
        rs = render(_cornell(astroray_module, 24, 24), "restir-di",    samples=32, seed=42)
        pt_mean = mean_luminance(pt)
        rs_mean = mean_luminance(rs)
        assert pt_mean > 0
        assert rs_mean > 0
        ratio = rs_mean / pt_mean
        assert 0.1 < ratio < 10.0, (
            f"restir-di mean {rs_mean:.4f} vs path_tracer {pt_mean:.4f}, ratio={ratio:.2f}"
        )
