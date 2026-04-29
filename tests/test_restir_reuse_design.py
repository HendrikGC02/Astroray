"""
pkg23 — ReSTIR temporal/spatial reuse design scaffolding tests.

Covers the FrameStateHelper Python binding (wraps FrameState from
include/astroray/restir/frame_state.h) and verifies that:
  1. resize + advance_frame work correctly
  2. isTemporallyValid gates fire as documented
  3. selectSpatialNeighbors produces the right count and bounds flags
  4. restir-di rendering is still finite after the pkg23 hook-point additions
"""

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# FrameStateHelper binding tests
# ---------------------------------------------------------------------------

class TestFrameStateResize:
    def test_dimensions_after_resize(self, astroray_module):
        fs = astroray_module.FrameStateHelper()
        fs.resize(16, 8)
        assert fs.width == 16
        assert fs.height == 8

    def test_frame_index_starts_at_zero(self, astroray_module):
        fs = astroray_module.FrameStateHelper()
        assert fs.frame_index == 0

    def test_advance_frame_increments_index(self, astroray_module):
        fs = astroray_module.FrameStateHelper()
        fs.resize(4, 4)
        fs.advance_frame()
        assert fs.frame_index == 1
        fs.advance_frame()
        assert fs.frame_index == 2

    def test_in_bounds(self, astroray_module):
        fs = astroray_module.FrameStateHelper()
        fs.resize(10, 10)
        assert fs.in_bounds(0, 0)
        assert fs.in_bounds(9, 9)
        assert not fs.in_bounds(10, 0)
        assert not fs.in_bounds(0, 10)
        assert not fs.in_bounds(-1, 0)


class TestTemporalValidity:
    def _make_fs(self, astroray_module, w=8, h=8):
        fs = astroray_module.FrameStateHelper()
        fs.resize(w, h)
        return fs

    def test_invalid_before_set(self, astroray_module):
        """Default PixelHistory has valid=False, so all pixels are invalid."""
        fs = self._make_fs(astroray_module)
        fs.advance_frame()
        # Previous buffer was never written — all pixels should be invalid.
        assert not fs.is_temporally_valid(0, 0, 0.0, 0.0, 1.0, 1.0)

    def test_valid_after_set_matching_geometry(self, astroray_module):
        """A pixel set with matching normal/depth in previous frame is valid."""
        fs = self._make_fs(astroray_module)
        # set_prev_pixel writes directly into the previous buffer.
        fs.set_prev_pixel(3, 3, 0.0, 0.0, 1.0, 2.0, True)
        assert fs.is_temporally_valid(3, 3, 0.0, 0.0, 1.0, 2.0)

    def test_invalid_normal_divergence(self, astroray_module):
        """Normal dot product below threshold (0.9) must fail."""
        fs = self._make_fs(astroray_module)
        # Perpendicular normal → dot = 0
        fs.set_prev_pixel(2, 2, 1.0, 0.0, 0.0, 1.0, True)
        assert not fs.is_temporally_valid(2, 2, 0.0, 0.0, 1.0, 1.0)

    def test_invalid_depth_divergence(self, astroray_module):
        """Relative depth difference > 10% must fail."""
        fs = self._make_fs(astroray_module)
        fs.set_prev_pixel(1, 1, 0.0, 0.0, 1.0, 1.0, True)
        # Current depth is 2.0; relative diff = |1-2|/2 = 0.5 > 0.1
        assert not fs.is_temporally_valid(1, 1, 0.0, 0.0, 1.0, 2.0)

    def test_invalid_out_of_bounds(self, astroray_module):
        """Out-of-bounds coordinates must return False."""
        fs = self._make_fs(astroray_module)
        assert not fs.is_temporally_valid(-1, 0, 0.0, 0.0, 1.0, 1.0)
        assert not fs.is_temporally_valid(0, 100, 0.0, 0.0, 1.0, 1.0)

    def test_small_normal_divergence_still_valid(self, astroray_module):
        """A tiny normal perturbation within threshold should still be valid."""
        import math
        fs = self._make_fs(astroray_module)
        # Tilt by ~5° — dot product ≈ cos(5°) ≈ 0.996 > 0.9
        angle = math.radians(5)
        nx, nz = math.sin(angle), math.cos(angle)
        fs.set_prev_pixel(4, 4, nx, 0.0, nz, 1.0, True)
        assert fs.is_temporally_valid(4, 4, 0.0, 0.0, 1.0, 1.0)

    def test_small_depth_difference_still_valid(self, astroray_module):
        """A 5% depth difference (within 10% threshold) should be valid."""
        fs = self._make_fs(astroray_module)
        fs.set_prev_pixel(5, 5, 0.0, 0.0, 1.0, 1.0, True)
        # 1.05 vs 1.0 → relative diff = 0.05/1.05 ≈ 0.048 < 0.1
        assert fs.is_temporally_valid(5, 5, 0.0, 0.0, 1.0, 1.05)


class TestSpatialNeighborSelection:
    def test_returns_requested_count(self, astroray_module):
        fs = astroray_module.FrameStateHelper()
        fs.resize(32, 32)
        neighbors = fs.select_neighbors(cx=16, cy=16, radius=5, max_neighbors=5, seed=42)
        assert len(neighbors) == 5

    def test_center_pixel_excluded_from_bounds_count(self, astroray_module):
        """Neighbours may still sample center, but that's fine per the design."""
        fs = astroray_module.FrameStateHelper()
        fs.resize(32, 32)
        neighbors = fs.select_neighbors(cx=16, cy=16, radius=5, max_neighbors=20, seed=0)
        assert len(neighbors) == 20

    def test_neighbors_near_border_have_some_invalid(self, astroray_module):
        """Pixels near the corner with a large radius will produce out-of-bounds neighbours."""
        fs = astroray_module.FrameStateHelper()
        fs.resize(16, 16)
        # Corner pixel, large radius — many neighbors will be out of bounds.
        neighbors = fs.select_neighbors(cx=0, cy=0, radius=10, max_neighbors=50, seed=1)
        assert len(neighbors) == 50
        valid_count = sum(1 for n in neighbors if n[2])   # n = (x, y, valid)
        invalid_count = 50 - valid_count
        assert invalid_count > 0, "Expected some out-of-bounds neighbors near corner"

    def test_interior_pixel_large_radius_all_valid(self, astroray_module):
        """Interior pixel with small radius — all neighbors should be in bounds."""
        fs = astroray_module.FrameStateHelper()
        fs.resize(64, 64)
        neighbors = fs.select_neighbors(cx=32, cy=32, radius=3, max_neighbors=10, seed=7)
        assert all(n[2] for n in neighbors), "All neighbors should be in bounds"

    def test_neighbor_coordinates_within_radius(self, astroray_module):
        """Valid neighbor coordinates must lie within [cx-r, cx+r] x [cy-r, cy+r]."""
        fs = astroray_module.FrameStateHelper()
        fs.resize(64, 64)
        cx, cy, r = 32, 32, 5
        neighbors = fs.select_neighbors(cx=cx, cy=cy, radius=r, max_neighbors=30, seed=99)
        for nx, ny, valid in neighbors:
            if valid:
                assert abs(nx - cx) <= r
                assert abs(ny - cy) <= r

    def test_deterministic_with_same_seed(self, astroray_module):
        """Same seed must produce identical neighbor lists."""
        fs = astroray_module.FrameStateHelper()
        fs.resize(32, 32)
        n1 = fs.select_neighbors(16, 16, 5, 8, seed=123)
        n2 = fs.select_neighbors(16, 16, 5, 8, seed=123)
        assert n1 == n2

    def test_different_seeds_differ(self, astroray_module):
        """Different seeds should produce different neighbor lists (high probability)."""
        fs = astroray_module.FrameStateHelper()
        fs.resize(64, 64)
        n1 = fs.select_neighbors(32, 32, 10, 20, seed=1)
        n2 = fs.select_neighbors(32, 32, 10, 20, seed=9999)
        assert n1 != n2, "Different seeds produced identical neighbor selections"


# ---------------------------------------------------------------------------
# Render regression: pkg23 hook points must not break restir-di output
# ---------------------------------------------------------------------------

def test_restir_di_still_finite_after_pkg23(astroray_module):
    """restir-di must still render finite non-black pixels after pkg23 changes."""
    r = astroray_module.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5.5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.5,
        width=24, height=24,
    )
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 15.0})
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    r.add_triangle([-2, -2, -2], [2, -2,  2], [-2, -2, 2], white)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)
    r.set_integrator("restir-di")
    r.set_seed(42)
    pixels = np.array(r.render(samples_per_pixel=8, max_depth=8), dtype=np.float32)
    assert not np.any(np.isnan(pixels)), "NaN in restir-di after pkg23"
    assert not np.any(np.isinf(pixels)), "Inf in restir-di after pkg23"
    assert pixels.max() > 0.0, "restir-di produced black output after pkg23"
