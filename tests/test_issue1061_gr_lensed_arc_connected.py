"""#1061: a lensed emissive sphere renders as whole arcs, not bitten fragments.

The escaping RK45 step (h up to 50 M) lands far past r_max; since #896 the
continuation ray started there and skipped any geometry between r_max and the
overshoot, cutting black bites and bands into the lensed images. The sphere
sits outside the GR region, so every image of it must be a hole-free blob and
there must be only a few of them (primary + secondary), not a scatter of
fragments.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def test_lensed_sphere_images_are_whole():
    W, H = 480, 270
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)
    # Behind the hole, fully outside r_max = 1.05 * 5.5 (centre at 7.2).
    m = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})
    r.add_sphere([1.6, 0.6, -7.0], 0.45, m)
    r.setup_camera([0.0, 0.0, 12.0], [1.0, 0.05, 0.0], [0.0, 1.0, 0.0],
                   42.0, W / H, 0.0, 12.0, W, H)
    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.5, {
        "spin": 0.0, "disk_outer": 0.0, "accretion_rate": 0.0,
        "inclination": 0.0, "enable_adaf": False, "r_obs_M": 20.0})
    lum = np.asarray(r.render(4, 5, None, False), dtype=np.float32).mean(2)

    mask = lum > 0.5
    labels, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    images = [i + 1 for i, s in enumerate(sizes) if s >= 20]
    assert 1 <= len(images) <= 3, f"{len(images)} images (sizes {sorted(sizes)[::-1][:10]})"
    for lab in images:
        blob = labels == lab
        holes = int((ndimage.binary_fill_holes(blob) & ~blob).sum())
        assert holes == 0, f"image {lab} ({int(blob.sum())} px) has {holes} hole px"
    # Fragments: almost all lit pixels belong to the main images.
    lit = int(mask.sum())
    assert sum(sizes[i - 1] for i in images) >= 0.97 * lit
