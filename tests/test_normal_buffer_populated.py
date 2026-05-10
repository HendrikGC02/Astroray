"""pkg75: assert the default integrator populates Camera::normalBuffer.

Before pkg75 the spectral path tracer (registered as "path_tracer", the
default integrator) wrote albedo + depth into SampleResult but left
normal at Vec3(0). OIDN/OptiX AOV-mode denoising then bound an all-zero
guide image, silently degrading to HDR+albedo. This test pins the
canonical fix: every primary-ray hit must produce a unit-length
world-space normal in the buffer the denoisers read.
"""

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _scene():
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
        width=32, height=32,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.5, mat)
    return r


def test_normal_buffer_populated_at_hits():
    r = _scene()
    r.render(samples_per_pixel=2, max_depth=2)
    normals = np.array(r.get_normal_buffer(), dtype=np.float32).reshape(-1, 3)
    depth = np.array(r.get_depth_buffer(), dtype=np.float32).reshape(-1)

    hit_mask = depth > 0.0
    assert hit_mask.any(), "scene produced no geometry hits; test setup broken"

    hit_normals = normals[hit_mask]
    # Every hit pixel must carry a non-zero normal.
    norms = np.linalg.norm(hit_normals, axis=1)
    assert np.all(norms > 0.0), (
        f"{int((norms == 0.0).sum())} hit pixels still have zero normals — "
        "pkg75 regression: SpectralPathTracer is not writing r.normal."
    )
    # And those normals must be unit length within tolerance.
    assert np.allclose(norms, 1.0, atol=0.01), (
        f"hit-normal mean={norms.mean():.4f} (expected ~1.0); "
        "rec.normal is not unit-length world-space."
    )


def test_normal_buffer_misses_are_zero():
    r = _scene()
    r.render(samples_per_pixel=2, max_depth=2)
    normals = np.array(r.get_normal_buffer(), dtype=np.float32).reshape(-1, 3)
    depth = np.array(r.get_depth_buffer(), dtype=np.float32).reshape(-1)

    miss_mask = depth == 0.0
    if not miss_mask.any():
        pytest.skip("no env/miss pixels in this framing")
    miss_norms = np.linalg.norm(normals[miss_mask], axis=1)
    # OIDN documents zero-vector as the default for unknown directions.
    assert np.all(miss_norms == 0.0), (
        "background pixels carry non-zero normals; pkg75 documents Vec3(0) "
        "for misses to match OIDN's expected guide-image default."
    )
