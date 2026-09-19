"""pkg276 — IES x spot composition vs the Cycles-exact numpy reference (CPU).

The reference (benchmarks/cycles-parity/ies_spot/ies_reference.py) ports Cycles
IESFile::process_type_c + kernel_ies_interp + spot_light_attenuation and was
validated against headless Cycles 5.2 renders of the same scene to 1.000 +/-
0.0003 per 1-deg annulus and per 15-deg azimuth sector (research note
.astroray_plan/docs/pkg276-ies-spot-research.md). These gates render the SAME
scene with the Astroray CPU engine and compare, per channel:
  * radial profile: 1-deg annuli of the angle from the spot axis,
  * azimuth lobe:   30-deg sectors of the Cycles light-local h angle inside the
                    core (an asymmetric profile with no mirror axis, so a frame
                    rotation or mirror fails loudly; a radial mean cannot).
Band [0.95, 1.05] above the noise floor (reference >= 5 % of the peak bin).

Camera note: the Astroray raster->NDC divisor is (res - 1) on both backends
(raytracer.h render loop, stage_init.cu; deferred in the pkg212 spec), so the
reference samples the plane at the engine's pixel positions (divisor=res-1).
"""

import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_REF_DIR = REPO_ROOT / "benchmarks" / "cycles-parity" / "ies_spot"
if str(_REF_DIR) not in sys.path:
    sys.path.insert(0, str(_REF_DIR))
import ies_reference as ref  # noqa: E402

BAND = (0.95, 1.05)
NOISE_FLOOR = 0.05


def _wall_washer():
    bp = str(REPO_ROOT / "benchmarks" / "blender_parity")
    if bp not in sys.path:
        sys.path.insert(0, bp)
    from scene_library import _ies_wall_washer_lm63
    return _ies_wall_washer_lm63()


def _quadrant_profile():
    """Type C, horizontal 0..90 only (Cycles mirrors to 0..360)."""
    v = list(range(0, 91, 5))
    h = [0, 15, 30, 45, 60, 75, 90]
    rows = [" ".join("%.4f" % (40.0 * (0.6 + 0.4 * math.cos(math.radians(vv * 9.0)))
                                * (1.0 + 0.5 * math.cos(math.radians(2.0 * hh)))) for vv in v)
            for hh in h]
    return "\n".join(["IESNA:LM-63-2002", "TILT=NONE",
                      "1 -1 1.0 %d %d 1 2 0.0 0.0 0.0" % (len(v), len(h)),
                      "1.0 1.0 100.0", " ".join(map(str, v)), " ".join(map(str, h)),
                      *rows]) + "\n"


PROFILES = {
    "asym360": ref.asym_profile_lm63,       # full 0..360 table (no wrap in Cycles)
    "wallwasher": _wall_washer,             # 0..315: Cycles appends the 360 entry
    "quadrant": _quadrant_profile,          # 0..90: Cycles mirrors twice
}


def render_astroray(astroray, sc, ies_path, spp=32, use_gpu=False, seed=7):
    """Render ref.SpotScene with the engine directly (addon-equivalent inputs:
    Cycles cone mapping, light matrix_world columns as light_frame)."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)
    r.set_seed(seed)
    r.set_pixel_filter(0, 1.0)             # box, 1 px (the Cycles leg uses BOX 1.0)
    r.set_background_color([0.0, 0.0, 0.0])
    m = r.create_material("lambertian", [sc.albedo] * 3, {})
    s = 6.0
    r.add_triangle([-s, -s, 0], [s, -s, 0], [s, s, 0], m)
    r.add_triangle([-s, -s, 0], [s, s, 0], [-s, s, 0], m)
    em = {"mode": "rgb", "color": [1.0, 1.0, 1.0]}
    R = sc.rotation()
    kw = {"light_frame": [float(R[rr, c]) for c in range(3) for rr in range(3)]}
    if sc.radius > 0.0:
        kw["soft_falloff"] = bool(sc.soft_falloff)   # #840
    if sc.kind == "SPOT":
        inner, outer = ref.cycles_cone_angles(sc.spot_size, sc.spot_blend)
        r.add_spot_light_dedicated(list(sc.light_pos), list(-R[:, 2]), inner, outer, em,
                                   sc.power, sc.radius, ies_path, 0, 0, **kw)
    else:
        r.add_point_light(list(sc.light_pos), em, sc.power, sc.radius, ies_path, 0, 0, **kw)
    r.setup_camera(look_from=[0, 0, sc.cam_height], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=sc.fov_deg, aspect_ratio=1.0, aperture=0.0,
                   focus_dist=sc.cam_height, width=sc.res, height=sc.res)
    img = np.asarray(r.render(spp, 4, None, False))
    return img[..., :3]


def profile_tables(img, sc, table):
    """(radial_rows, azimuth_rows) of per-channel img/reference ratios."""
    div = sc.res - 1
    refimg = ref.radiance(sc, table, sub=6, divisor=div)
    theta, h = ref.pixel_geometry(sc, divisor=div)
    radial = ref.binned_ratio(img, refimg, theta, np.arange(0.0, 31.0, 1.0),
                              min_ref_frac=NOISE_FLOOR)
    core = (theta > 4.0) & (theta < 24.0)
    azim = ref.binned_ratio(np.where(core[..., None], img, 0.0), np.where(core, refimg, 0.0),
                            np.where(core, h, -1.0), np.arange(0.0, 361.0, 30.0),
                            min_ref_frac=NOISE_FLOOR)
    return radial, azim


def _out_of_band(rows):
    bad = []
    for r in rows:
        for c, x in zip("RGB", r["ratio"]):
            if not math.isnan(x) and not (BAND[0] <= x <= BAND[1]):
                bad.append("%s[%g,%g) %s=%.3f" % ("bin", r["lo"], r["hi"], c, x))
    return bad


def _checked(rows):
    return sum(1 for r in rows if not math.isnan(r["ratio"][1]))


# --------------------------------------------------------------------------- #
# Reference self-consistency (pure numpy; no engine).
# --------------------------------------------------------------------------- #
def test_reference_cone_mapping_equals_cycles_field():
    """t = (cos - cosO)/(cosI - cosO) with cosI from cycles_cone_angles equals
    Cycles' (cos - cos_half) * spot_smooth for every cos in the blend band."""
    size, blend = math.radians(60.0), 0.15
    inner, outer = ref.cycles_cone_angles(size, blend)
    cos = np.linspace(math.cos(outer), 1.0, 257)
    t = (cos - math.cos(outer)) / (math.cos(inner) - math.cos(outer))
    engine = ref.smoothstepf(t)
    np.testing.assert_allclose(engine, ref.spot_attenuation(cos, size, blend), atol=1e-6)


_RECORDED = REPO_ROOT / "benchmarks" / "cycles-parity" / "ies_spot" / "cycles_recorded.json"
_RECORDED_LEGS = ["spot_noies", "spot_asym", "point_asym", "spot_wallwasher",
                  "point_r01_soft", "point_r10_soft", "point_r10_sphere",
                  "spot_r025_soft", "spot_r10_sphere"]


@pytest.mark.parametrize("leg", _RECORDED_LEGS)
def test_reference_reproduces_recorded_cycles(leg):
    """The reference is not validated against itself: headless Cycles 5.2 annulus
    means (cycles_recorded.json, see its _provenance) must be reproduced within
    1 % in every bin above 5 % of the peak (measured: <= 0.2 %)."""
    import json
    rec = json.loads(_RECORDED.read_text(encoding="utf-8"))
    entry = rec[leg]
    sc = ref.SpotScene(**entry["scene"])
    prof = entry["profile"]
    table = None
    if prof == "asym":
        table = ref.parse_ies(ref.asym_profile_lm63())
    elif prof == "wallwasher":
        table = ref.parse_ies(_wall_washer())
    img = ref.radiance(sc, table, sub=2)
    theta, _ = ref.pixel_geometry(sc)
    edges = rec["edges_deg"]
    want = entry["annulus_mean_G"]
    peak = max(w for w in want if w is not None)
    checked = 0
    for (lo, hi), w in zip(zip(edges[:-1], edges[1:]), want):
        if w is None or w < 0.05 * peak:
            continue
        m = (theta >= lo) & (theta < hi)
        got = float(img[m].mean())
        assert got == pytest.approx(w, rel=0.01), (leg, lo, got, w)
        checked += 1
    assert checked >= 8, (leg, checked)


def test_reference_cycles_float32_wrap_quirk():
    """Cycles compares against M_2PI_F - 1e-7f in float32, which equals
    M_2PI_F, so a 0..360 table does not wrap. The reference must reproduce it."""
    t = ref.parse_ies(ref.asym_profile_lm63())
    f32 = np.float32
    assert not (t.h_angles[-1] > f32(f32(2 * math.pi) - f32(1e-7)))


# --------------------------------------------------------------------------- #
# Addon: Blender spot_size/spot_blend -> engine cone, light frame for IES.
# --------------------------------------------------------------------------- #
class _Mat3:
    def __init__(self, m):
        self.m = np.asarray(m, dtype=float)

    def __getitem__(self, r):
        return self.m[r]

    def __matmul__(self, v):
        out = self.m @ np.array([v.x, v.y, v.z], dtype=float)
        return types.SimpleNamespace(x=out[0], y=out[1], z=out[2],
                                     normalized=lambda: types.SimpleNamespace(
                                         x=out[0] / np.linalg.norm(out),
                                         y=out[1] / np.linalg.norm(out),
                                         z=out[2] / np.linalg.norm(out)))


class _Matrix4:
    def __init__(self, R, t):
        self.R, self.translation = R, list(t)

    def to_3x3(self):
        return _Mat3(self.R)


class _Recorder:
    def __init__(self):
        self.spot, self.point = [], []

    def add_spot_light_dedicated(self, *a, **k):
        self.spot.append((a, k))

    def add_point_light(self, *a, **k):
        self.point.append((a, k))

    def add_sun_light_dedicated(self, *a, **k):
        pass

    def add_area_light_dedicated(self, *a, **k):
        pass


def _light_instance(kind, R, ies_text=None):
    nodes = []
    if ies_text is not None:
        nodes.append(types.SimpleNamespace(
            type="TEX_IES", mode="INTERNAL", filepath="",
            ies=types.SimpleNamespace(name="pkg276", as_string=lambda: ies_text),
            outputs=[types.SimpleNamespace(is_linked=True)], inputs={}))
    light = types.SimpleNamespace(
        type=kind, color=(1.0, 1.0, 1.0), energy=100.0, shadow_soft_size=0.0,
        spot_size=math.radians(60.0), spot_blend=0.15,
        node_tree=types.SimpleNamespace(nodes=nodes) if nodes else None)
    obj = types.SimpleNamespace(type="LIGHT", data=light, pass_index=0)
    return types.SimpleNamespace(object=obj, matrix_world=_Matrix4(R, (0.25, -0.15, 2.0)),
                                 is_instance=False)


def _convert(monkeypatch, instance):
    from _batch_a_stub import load_addon
    addon = load_addon(monkeypatch, "pkg276")
    engine = addon.CustomRaytracerRenderEngine()
    rec = _Recorder()
    engine.convert_lights(types.SimpleNamespace(object_instances=[instance]), rec)
    return rec


def test_addon_spot_cone_matches_cycles_field(monkeypatch):
    rec = _convert(monkeypatch, _light_instance("SPOT", np.eye(3)))
    (args, _kw), = rec.spot
    inner, outer = args[2], args[3]
    want_inner, want_outer = ref.cycles_cone_angles(math.radians(60.0), 0.15)
    assert outer == pytest.approx(want_outer, abs=1e-6)
    assert inner == pytest.approx(want_inner, abs=1e-6), (
        "addon cone mapping must reproduce Cycles spot_smooth "
        "(cosInner = cos_half + (1 - cos_half) * blend)")


@pytest.mark.parametrize("kind", ["SPOT", "POINT"])
def test_addon_passes_light_frame_with_ies(monkeypatch, kind):
    R = ref.rotation_z(30.0)
    rec = _convert(monkeypatch, _light_instance(kind, R, ies_text=ref.asym_profile_lm63()))
    calls = rec.spot if kind == "SPOT" else rec.point
    (_args, kw), = calls
    want = [R[r, c] for c in range(3) for r in range(3)]
    np.testing.assert_allclose(kw["light_frame"], want, atol=1e-9)


# --------------------------------------------------------------------------- #
# Engine (CPU): radial + azimuth profile vs the Cycles-exact reference.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def ies_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("pkg276_ies")
    out = {}
    for name, gen in PROFILES.items():
        p = d / (name + ".ies")
        p.write_text(gen(), encoding="utf-8")
        out[name] = p
    return out


def test_spot_cone_profile_no_ies(astroray_module):
    sc = ref.SpotScene()
    img = render_astroray(astroray_module, sc, "")
    radial, _ = profile_tables(img, sc, None)
    assert _checked(radial) >= 25, radial
    bad = _out_of_band(radial)
    assert not bad, "no-IES spot radial profile off Cycles: %s" % bad


@pytest.mark.parametrize("profile", sorted(PROFILES))
@pytest.mark.parametrize("kind", ["SPOT", "POINT"])
def test_ies_profile_matches_cycles_reference(astroray_module, ies_files, kind, profile):
    sc = ref.SpotScene(kind=kind)
    path = ies_files[profile]
    table = ref.parse_ies(path.read_text(encoding="utf-8"))
    img = render_astroray(astroray_module, sc, str(path))
    radial, azim = profile_tables(img, sc, table)
    assert _checked(radial) >= 20 and _checked(azim) >= 10, (radial, azim)
    bad = _out_of_band(radial) + ["azimuth " + b for b in _out_of_band(azim)]
    assert not bad, "%s %s IES profile off the Cycles reference: %s" % (kind, profile, bad)
