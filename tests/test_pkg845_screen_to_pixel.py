"""#845: pixel -> film -> ray -> screenU/V -> pixel round trip (CPU).

The film mapping is u = (x + jitter)/W, v = 1 - (y + jitter)/H; the integrators'
per-pixel AOV/cryptomatte/ReSTIR writes invert it with screenToPixel. A stale
(W-1) inverse lands edge samples in the neighbouring pixel.
"""
import pytest

th = pytest.importorskip("astroray_test_helpers")
if not hasattr(th, "camera_pixel_roundtrip"):
    pytest.skip("astroray_test_helpers predates #845 camera_pixel_roundtrip", allow_module_level=True)


@pytest.mark.cpu
@pytest.mark.parametrize("ortho", [False, True], ids=["persp", "ortho"])
@pytest.mark.parametrize("w,h", [(320, 200), (200, 320), (17, 9)])
def test_pixel_roundtrip_corners_and_centre(w, h, ortho):
    pixels = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, h // 2)]
    for x, y in pixels:
        for j in (0.001, 0.5, 0.999):
            assert tuple(th.camera_pixel_roundtrip(w, h, x, y, j, j, ortho)) == (x, y), (x, y, j)
