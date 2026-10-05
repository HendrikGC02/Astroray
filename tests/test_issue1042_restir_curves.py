"""#1042 -- GPU ReSTIR DI renders and shadows hair/curves.

stage_restir.cu used to call intersectPathSlot without the curve-segment array
(HasCurves=false) and its resolve shadow walk (gpu_tlas_occluded) omitted curves,
so GPU ReSTIR DI drew no strands and strands cast no shadows. The path tracer's
stages already carried d_curveSegments + the HasCurves axis (pkg225 Stage 3); the
ReSTIR primary and resolve kernels now do too.

Two gates, each built from ONE scene description and run on every backend:
  visible : black background + lit diffuse strands; ReSTIR must show the strands
            (coverage floor) and match the path tracer's direct lighting
            (max_depth=1) per-channel within an MC band.
  shadow  : strands OUTSIDE the camera frame sit between a small area light and a
            diffuse floor in view; their shadow band must darken the floor to
            well under half of the strand-free floor.
CPU legs are the oracle (CPU restir-di already traverses curves); GPU legs are the
code under test and need the RTX box + a CUDA build.
"""
from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

WIDTH = HEIGHT = 64
SEED = 1042
LUM = np.array([0.2126, 0.7152, 0.0722])


def _backend_param(name):
    marks = [pytest.mark.gpu, pytest.mark.serial] if name == "gpu" else []
    return pytest.param(name, marks=marks, id=name)


BACKENDS = [_backend_param("cpu"), _backend_param("gpu")]


def _light_quad(r, centre, target, half, intensity):
    """Square emitter at `centre` facing `target` (two triangles, normal toward target)."""
    centre = np.asarray(centre, dtype=np.float64)
    n = np.asarray(target, dtype=np.float64) - centre
    n /= np.linalg.norm(n)
    u = np.cross(n, [0.0, 1.0, 0.0])
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(n, [1.0, 0.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(n, u)                       # u x v = n
    c = [centre + s * u * half + t * v * half for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": intensity})
    r.add_triangle(*[x.tolist() for x in (c[0], c[1], c[2])], light)
    r.add_triangle(*[x.tolist() for x in (c[0], c[2], c[3])], light)


def _setup(backend, integrator, look_from, vfov):
    if backend == "gpu":
        probe = astroray.Renderer()
        if not astroray.__features__.get("cuda", False):
            pytest.skip("CUDA feature not in this build")
        try:
            probe.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip("GPU unavailable: %s" % e)
        if not getattr(probe, "gpu_available", False):
            pytest.skip("gpu_available is False")
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera(look_from, [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], vfov, 1.0, 0.0,
                   float(np.linalg.norm(look_from)), WIDTH, HEIGHT)
    if integrator == "restir-di":
        r.set_integrator_param("use_temporal", 0)
        r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    r.set_curve_thick_mode(True)   # CPU always renders the thick swept circle
    r.set_use_gpu(backend == "gpu")
    r.set_seed(SEED)
    return r


def _strands(r, rows, hair):
    pos, counts = [], []
    for pts in rows:
        pos.extend(pts)
        counts.append(len(pts))
    pos = np.asarray(pos, dtype=np.float32)
    r.add_curves_bulk(pos, np.full(len(pos), 0.05, dtype=np.float32), counts, hair)


def _render(r, spp, depth):
    return np.asarray(r.render(spp, depth, None, False), dtype=np.float64)


# --------------------------------------------------------------------------- #
# visible: strands lit by a quad light, black background
# --------------------------------------------------------------------------- #
def _visible_scene(backend, integrator):
    r = _setup(backend, integrator, [0.0, 0.0, 4.2], 40.0)
    hair = r.create_material("lambertian", [0.7, 0.55, 0.4], {})
    rows = []
    for ci in range(9):
        x0 = -1.4 + 2.8 * ci / 8
        bow = 0.25 * np.sin(ci * 0.7)
        strand = []
        for ri in range(5):
            t = ri / 4
            strand.append((x0 + bow * np.sin(t * np.pi), 1.3 - 2.6 * t, 0.15 * np.cos(t * np.pi + ci)))
        rows.append(strand)
    _strands(r, rows, hair)
    _light_quad(r, [1.6, 2.6, 1.8], [0.0, 0.0, 0.0], 0.5, 14.0)
    return r


@pytest.mark.parametrize("backend", BACKENDS)
def test_restir_renders_curves(backend):
    restir = _render(_visible_scene(backend, "restir-di"), 64, 1)
    pt = _render(_visible_scene(backend, "path_tracer"), 256, 1)  # direct light only
    assert np.isfinite(restir).all()
    cov = float(np.mean(np.any(restir > 1e-4, axis=-1)))
    assert cov >= 0.02, f"{backend} ReSTIR shows no strands (coverage {cov:.4f})"
    for c in range(3):
        ratio = restir[..., c].mean() / pt[..., c].mean()
        assert 0.80 <= ratio <= 1.20, (backend, "rgb"[c], ratio, restir[..., c].mean(), pt[..., c].mean())


# --------------------------------------------------------------------------- #
# shadow: off-frame strands shadow a floor that is in frame
# --------------------------------------------------------------------------- #
def _shadow_scene(backend, integrator, with_strands):
    r = _setup(backend, integrator, [0.0, 0.0, 6.0], 20.0)
    grey = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_triangle([-3, -3, 0], [3, -3, 0], [3, 3, 0], grey)       # floor facing +z
    r.add_triangle([-3, -3, 0], [3, 3, 0], [-3, 3, 0], grey)
    if with_strands:
        hair = r.create_material("lambertian", [0.7, 0.55, 0.4], {})
        # Horizontal strands at z = 2, y in [2.0, 2.4]: above the camera frame there
        # (half-height tan(10deg) * 4 = 0.7) but their shadow from the light at
        # (0, 3, 3) lands on the floor at y = 3y - 6 in [0, 1.2], in frame (<= 1.06).
        rows = [[(x, y, 2.0) for x in np.linspace(-2.0, 2.0, 5)] for y in np.linspace(2.0, 2.4, 5)]
        _strands(r, rows, hair)
    _light_quad(r, [0.0, 3.0, 3.0], [0.0, 0.0, 0.0], 0.15, 40.0)
    return r


def _floor_roi_mean(img):
    # In-frame floor rows covering the shadow band y in [0.1, 0.9] (image row 0 = top).
    half = np.tan(np.radians(10.0)) * 6.0
    rows = [i for i in range(HEIGHT) if 0.1 <= (1.0 - (i + 0.5) / HEIGHT * 2.0) * half <= 0.9]
    cols = slice(WIDTH // 4, 3 * WIDTH // 4)
    return float((img[rows][:, cols] @ LUM).mean())


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("integrator,spp,depth", [("path_tracer", 128, 1), ("restir-di", 64, 1)])
def test_curves_shadow_floor(backend, integrator, spp, depth):
    lit = _floor_roi_mean(_render(_shadow_scene(backend, integrator, False), spp, depth))
    shadowed = _floor_roi_mean(_render(_shadow_scene(backend, integrator, True), spp, depth))
    assert lit > 1e-3, f"strand-free floor is dark ({lit}): the test geometry is wrong"
    assert shadowed < 0.5 * lit, (backend, integrator, shadowed, lit)
