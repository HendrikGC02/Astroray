"""Issue #801 — GPU wavefront device scene cache.

Before #801 every ``render()`` call re-ran ``buildSceneArrays`` (host-side scene
conversion: BVH flatten, triangles, materials, texels, light tree) and re-memcpy'd
every scene array to the device, whether or not ``skip_upload`` was set.  The
Blender viewport refines in 1-spp chunks, so at 100k triangles each chunk paid
~45 ms of conversion + upload for ~14 ms of path tracing — the owner's "the scene
is re-uploaded to the GPU every frame".

Contract under test (src/gpu/wavefront/gpu_wavefront_snapshot.cu):
  1. ``render(skip_upload=True)`` after an upload render of the SAME renderer is
     byte-identical at a pinned seed (the cache serves the same scene).
  2. The cache is keyed on the owning renderer: another renderer's upload never
     serves a reuse (the viewport must not render the F12 renderer's scene).
  3. Host-side mutations that bypass render() — the pkg56 per-domain uploaders —
     invalidate the cache (``upload_environment`` after loading an HDRI).
  4. The reuse path is measurably cheaper than the upload path on a large scene.
"""
import os
import time

import numpy as np
import pytest

import runtime_setup  # noqa: F401

astroray = pytest.importorskip("astroray")

pytestmark = pytest.mark.gpu

W, H = 160, 90
SEED = 7
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_HDR = os.path.join(HERE, "..", "samples", "test_env.hdr")


def _gpu_or_skip():
    r = astroray.Renderer()
    if not r.gpu_available:
        pytest.skip("CUDA device not available")


def _scene(ntri, seed=1, colour=(0.8, 0.3, 0.3)):
    r = astroray.Renderer()
    r.set_background_color([0.2, 0.2, 0.25])
    r.create_material("lambertian", list(colour), {})
    r.create_material("lambertian", [0.3, 0.4, 0.9], {})
    rng = np.random.default_rng(seed)
    centre = rng.uniform(-1, 1, size=(ntri, 1, 3))
    jitter = rng.uniform(-0.05, 0.05, size=(ntri, 3, 3))
    pos = (centre + jitter).astype(np.float32)
    ids = rng.integers(0, 2, size=ntri).astype(np.int32)
    mp = np.zeros(ntri, np.int32)
    r.add_triangles_bulk(pos, ids, mp, 0, np.zeros((0, ntri, 3, 2), np.float32), [],
                         np.zeros((0, 3, 3), np.float32))
    r.add_sun_light_dedicated([0.3, -0.5, -1.0], 0.02,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 4.0)
    r.setup_camera([0, 0, 4.0], [0, 0, 0], [0, 1, 0], 45.0, W / H, 0.0, 4.0, W, H)
    r.set_use_gpu(True)
    r.set_seed(SEED)
    return r


def _render(r, spp=2, skip_upload=False):
    img = np.asarray(r.render(spp, 4, None, False, -1, -1, -1, -1, -1, skip_upload),
                     dtype=np.float32)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def test_reuse_is_byte_identical_to_upload():
    _gpu_or_skip()
    r = _scene(2000)
    a = _render(r, skip_upload=False)
    b = _render(r, skip_upload=True)
    c = _render(r, skip_upload=False)
    assert a.mean() > 0.01, "scene renders black — fixture broken"
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(a, c)


def test_cache_is_keyed_on_the_owning_renderer():
    """Viewport + F12 are separate Renderer objects sharing one process-global
    wavefront context: after B uploads, A's skip_upload render must still be A's
    scene, not B's."""
    _gpu_or_skip()
    ra = _scene(2000, seed=1, colour=(0.8, 0.3, 0.3))
    rb = _scene(2000, seed=2, colour=(0.1, 0.9, 0.1))
    a0 = _render(ra, skip_upload=False)
    b0 = _render(rb, skip_upload=False)
    assert not np.array_equal(a0, b0)
    a1 = _render(ra, skip_upload=True)
    np.testing.assert_array_equal(a0, a1)
    b1 = _render(rb, skip_upload=True)
    np.testing.assert_array_equal(b0, b1)


def test_domain_uploader_invalidates_the_cache():
    """upload_environment() bypasses render(); a following skip_upload render
    must see the new HDRI (cache invalidated), matching an upload render."""
    _gpu_or_skip()
    if not os.path.exists(ENV_HDR):
        pytest.skip("samples/test_env.hdr missing")
    r = _scene(500)
    base = _render(r, skip_upload=False)
    assert r.load_environment_map(ENV_HDR, 1.0)
    r.upload_environment()
    after_reuse = _render(r, skip_upload=True)
    after_upload = _render(r, skip_upload=False)
    assert not np.array_equal(base, after_reuse), (
        "skip_upload render after upload_environment() still shows the cached "
        "(env-less) scene — cuda_wavefront_invalidate_scene not reached")
    np.testing.assert_array_equal(after_reuse, after_upload)


def test_reuse_is_cheaper_than_upload_on_a_large_scene():
    """Informational bound: at 200k triangles the reuse path skips the host
    conversion + memcpy (~45 ms at 100k tris measured 2026-09-12), so a 1-spp
    render must be at least 1.5x faster (min-of-N to dodge clock drift)."""
    _gpu_or_skip()
    r = _scene(200_000)
    _render(r, spp=1, skip_upload=False)  # warm-up (BVH + first upload)

    def best(skip):
        ts = []
        for _ in range(5):
            t = time.perf_counter()
            _render(r, spp=1, skip_upload=skip)
            ts.append(time.perf_counter() - t)
        return min(ts)

    t_upload = best(False)
    t_reuse = best(True)
    print(f"[#801] 200k tris 1 spp: upload {t_upload*1e3:.1f} ms, reuse {t_reuse*1e3:.1f} ms")
    assert t_reuse * 1.5 < t_upload, (t_upload, t_reuse)
