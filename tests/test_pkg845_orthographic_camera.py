"""#845 -- Blender ORTHO cameras render orthographically (CPU + GPU).

Analytic plane-grid fixture (benchmarks/blender_parity/scene_library.py
ORTHO_GRID): emissive strips on z=0 under a shifted, clipped ORTHO camera.
Line positions, extents and shift must land within one output pixel of
Blender's own ``world_to_camera_view`` (captured in
tests/data/pkg845_blender_ortho_reference.json), for landscape and portrait
frames, five fixed seeds. The camera goes through the addon's real
``_apply_camera`` lowering, so the ortho_scale -> plane-extent conversion is
under test too. Near/far markers prove the primary clip bounds.

Regenerate the reference (headless Blender 5.2):
    blender -b --factory-startup --python tests/test_pkg845_orthographic_camera.py -- --write-reference
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REF_PATH = REPO / "tests" / "data" / "pkg845_blender_ortho_reference.json"
sys.path.insert(0, str(REPO / "benchmarks" / "blender_parity"))
import scene_library as SL  # noqa: E402  (bpy-free at import)

G = SL.ORTHO_GRID
SEEDS = (11, 23, 37, 51, 73)
TOL_PX = 1.0  # predeclared analytic raster bound (batchU-readiness #845)


# --------------------------------------------------------------------------- #
# Blender side: capture the reference
# --------------------------------------------------------------------------- #

def _write_reference():
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    out = {"blender": bpy.app.version_string, "frames": {}}
    hw = G["line_w"] / 2.0
    for orient in ("landscape", "portrait"):
        W, H = G[orient]
        scene, *_ = SL.build_camera_lens_ortho_scene(bpy, (W, H))
        cam = scene.camera
        dg = bpy.context.evaluated_depsgraph_get()

        def px(x, y, z=0.0):
            c = world_to_camera_view(scene, cam, Vector((x, y, z)))
            return [c.x * W, (1.0 - c.y) * H]  # continuous px, top-down

        (y0, y1), (x0, x1) = G["v_span_y"], G["h_span_x"]
        frame = {
            "v_lines_px_x": [px(x, 0.0)[0] for x in G["v_lines_x"]],
            "h_lines_px_y": [px(0.0, y)[1] for y in G["h_lines_y"]],
            # v-line ends (top = larger world y) and h-line ends, in px
            "v_span_px_y": [px(0.0, y1)[1], px(0.0, y0)[1]],
            "h_span_px_x": [px(x0, 0.0)[0], px(x1, 0.0)[0]],
            "line_w_px": px(hw, 0.0)[0] - px(-hw, 0.0)[0],
            "window_matrix": [list(r) for r in cam.calc_matrix_camera(dg, x=W, y=H)],
        }
        for key in ("near_marker", "far_marker"):
            (cx, cy), z, size = G[key]
            a = px(cx - size / 2, cy + size / 2, z)
            b = px(cx + size / 2, cy - size / 2, z)
            frame[key + "_px_rect"] = [a[0], a[1], b[0], b[1]]  # x0, y0, x1, y1
        out["frames"][orient] = frame
    REF_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"[pkg845] wrote {REF_PATH}")


if __name__ == "__main__" and "--write-reference" in sys.argv:
    _write_reference()
    raise SystemExit(0)


# --------------------------------------------------------------------------- #
# Engine side
# --------------------------------------------------------------------------- #

import numpy as np  # noqa: E402
import pytest  # noqa: E402


def _ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


class _V3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]

    def __add__(self, o):
        return _V3(self.x + o.x, self.y + o.y, self.z + o.z)


class _IdentityQuat:
    def __matmul__(self, v):
        return _V3(v[0], v[1], v[2])


def _ortho_cam_obj():
    loc = _V3(0.0, 0.0, G["cam_z"])
    matrix = types.SimpleNamespace(decompose=lambda: (loc, _IdentityQuat(), _V3(1, 1, 1)),
                                   translation=loc)
    dof = types.SimpleNamespace(use_dof=False, aperture_fstop=0.0,
                                focus_object=None, focus_distance=10.0)
    data = types.SimpleNamespace(type="ORTHO", ortho_scale=G["ortho_scale"],
                                 sensor_fit="AUTO", shift_x=G["shift"][0],
                                 shift_y=G["shift"][1], clip_start=G["clip"][0],
                                 clip_end=G["clip"][1], dof=dof, lens=50.0,
                                 sensor_width=36.0, sensor_height=24.0)
    return types.SimpleNamespace(data=data, matrix_world=matrix)


def _render(monkeypatch, orient, seed, gpu):
    astroray = pytest.importorskip("astroray")
    from test_addon_viewport_camera_vfov import _load_blender_addon

    W, H = G[orient]
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    if gpu:
        r.set_use_gpu(True)
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    r.set_seed(seed)
    r.set_background_color([0.0, 0.0, 0.0])
    for _name, rgb, c in SL.ortho_grid_quads():
        m = r.create_material("light", list(rgb), {"intensity": 1.0})
        r.add_triangle(list(c[0]), list(c[1]), list(c[2]), m)
        r.add_triangle(list(c[0]), list(c[2]), list(c[3]), m)
    # Real addon lowering (stub bpy); `astroray` above was imported first.
    addon = _load_blender_addon(monkeypatch)
    addon.CustomRaytracerRenderEngine()._apply_camera(r, _ortho_cam_obj(), W, H)
    img = np.asarray(r.render(16, 2, None, False), dtype=np.float64).reshape(H, W, 3)
    return img


def _centroid(profile, lo, hi):
    lo, hi = max(0, int(lo)), min(len(profile), int(hi))
    w = profile[lo:hi]
    return float(np.sum((np.arange(lo, hi) + 0.5) * w) / np.sum(w))


def _rising_edge(cov, lo, hi):   # coverage 0 -> 1 across [lo, hi)
    return lo + float(np.sum(1.0 - np.clip(cov[lo:hi], 0, 1)))


def _falling_edge(cov, lo, hi):  # coverage 1 -> 0 across [lo, hi)
    return lo + float(np.sum(np.clip(cov[lo:hi], 0, 1)))


def _measure(img, fr):
    """Measured geometry (continuous px) matching the reference keys."""
    lum = img[..., 0] + img[..., 1] + img[..., 2]
    white = np.minimum(np.minimum(img[..., 0], img[..., 1]), img[..., 2])  # grid only
    hx, vy = fr["h_lines_px_y"], fr["v_lines_px_x"]
    # Sample rows / columns in the gaps between crossing lines.
    gap_rows = [int((a + b) / 2) for a, b in zip(hx[:-1], hx[1:])]
    gap_cols = [int((a + b) / 2) for a, b in zip(vy[:-1], vy[1:])]
    m = {"v_lines_px_x": [], "h_lines_px_y": []}
    col_prof = white[np.r_[tuple(slice(g - 4, g + 5) for g in gap_rows)], :].mean(axis=0)
    for x in vy:
        m["v_lines_px_x"].append(_centroid(col_prof, x - 8, x + 9))
    row_prof = white[:, np.r_[tuple(slice(g - 4, g + 5) for g in gap_cols)]].mean(axis=1)
    for y in hx:
        m["h_lines_px_y"].append(_centroid(row_prof, y - 8, y + 9))
    # Extents: per-line coverage normalised by the line's interior plateau.
    tops, bots = [], []
    for x in m["v_lines_px_x"]:
        prof = white[:, int(x) - 1:int(x) + 2].mean(axis=1)
        top, bot = fr["v_span_px_y"]
        cov = prof / np.median(prof[int(top) + 12:int(bot) - 12])
        tops.append(_rising_edge(cov, int(top) - 6, int(top) + 7))
        bots.append(_falling_edge(cov, int(bot) - 6, int(bot) + 7))
    lefts, rights = [], []
    for y in m["h_lines_px_y"]:
        prof = white[int(y) - 1:int(y) + 2, :].mean(axis=0)
        left, right = fr["h_span_px_x"]
        cov = prof / np.median(prof[int(left) + 12:int(right) - 12])
        lefts.append(_rising_edge(cov, int(left) - 6, int(left) + 7))
        rights.append(_falling_edge(cov, int(right) - 6, int(right) + 7))
    m["v_span_px_y"] = [float(np.mean(tops)), float(np.mean(bots))]
    m["h_span_px_x"] = [float(np.mean(lefts)), float(np.mean(rights))]
    m["_span_spread"] = float(max(np.ptp(tops), np.ptp(bots), np.ptp(lefts), np.ptp(rights)))

    def rect_mean(key, ch):
        x0, y0, x1, y1 = fr[key]
        return float(img[int(y0) + 1:int(y1) - 1, int(x0) + 1:int(x1) - 1, ch].mean())

    m["near_marker_red"] = rect_mean("near_marker_px_rect", 0)
    m["far_marker_green"] = rect_mean("far_marker_px_rect", 1)
    m["grid_peak"] = float(lum.max())
    return m


GEOM_KEYS = ("v_lines_px_x", "h_lines_px_y", "v_span_px_y", "h_span_px_x")


def _geometry_errors(m, fr):
    return {k: float(np.max(np.abs(np.asarray(m[k]) - np.asarray(fr[k])))) for k in GEOM_KEYS}


def test_reference_is_orthographic_and_shifted():
    """Sanity on the Blender capture itself: equal line spacing (parallel,
    no perspective) and the authored shift moves the grid off-centre."""
    for orient, fr in _ref()["frames"].items():
        W, H = G[orient]
        px_per_unit = W / (G["ortho_scale"] if W >= H else G["ortho_scale"] * W / H)
        for key in ("v_lines_px_x", "h_lines_px_y"):
            d = np.diff(fr[key])
            assert np.allclose(np.abs(d), px_per_unit, atol=1e-3), (orient, key, d)
        # world x=0 sits shift_x*ortho_scale left of the frame centre
        exp_x0 = W / 2 - G["shift"][0] * G["ortho_scale"] * px_per_unit
        assert abs(fr["v_lines_px_x"][1] - exp_x0) < 1e-3


def test_addon_viewport_path_inverts_blender_ortho_window_matrix(monkeypatch):
    """The CAMERA-view path (window_matrix inversion) must give the same
    plane as the F12 datablock path for Blender's real ortho matrix."""
    from test_addon_viewport_camera_vfov import _load_blender_addon
    addon = _load_blender_addon(monkeypatch)
    cls = addon.CustomRaytracerRenderEngine
    cam = _ortho_cam_obj().data
    for orient, fr in _ref()["frames"].items():
        W, H = G[orient]
        f12 = cls._ortho_camera_plane(cam, W, H)
        vp = cls._ortho_camera_plane(cam, W, H, proj=fr["window_matrix"])
        assert np.allclose(f12, vp, atol=1e-5), (orient, f12, vp)


@pytest.mark.parametrize("orient", ["landscape", "portrait"])
@pytest.mark.parametrize("gpu", [False, True], ids=["cpu", "gpu"])
def test_ortho_grid_matches_blender_projection(monkeypatch, orient, gpu):
    fr = _ref()["frames"][orient]
    per_seed = []
    for seed in SEEDS:
        m = _measure(_render(monkeypatch, orient, seed, gpu), fr)
        err = _geometry_errors(m, fr)
        per_seed.append((seed, err, m))
        print(f"[pkg845] {orient} {'gpu' if gpu else 'cpu'} seed={seed} "
              f"err_px={ {k: round(v, 3) for k, v in err.items()} } "
              f"span_spread={m['_span_spread']:.3f} near_red={m['near_marker_red']:.4f} "
              f"far_green={m['far_marker_green']:.4f}")
        for k, v in err.items():
            assert v <= TOL_PX, (seed, k, v, m[k], fr[k])
    # Five fixed seeds keep the same geometry (no seed-dependent drift).
    for k in GEOM_KEYS:
        vals = np.array([np.asarray(m[k]) for _s, _e, m in per_seed])
        assert float(np.max(np.ptp(vals, axis=0))) <= 0.25, (k, vals)


@pytest.mark.parametrize("orient", ["landscape", "portrait"])
def test_ortho_primary_clip_hides_markers_cpu(monkeypatch, orient):
    fr = _ref()["frames"][orient]
    m = _measure(_render(monkeypatch, orient, SEEDS[0], gpu=False), fr)
    assert m["grid_peak"] > 0.5
    assert m["near_marker_red"] < 0.02, m["near_marker_red"]   # inside clip_start
    assert m["far_marker_green"] < 0.02, m["far_marker_green"]  # beyond clip_end
