"""pkg316 (#1051) -- Principled Hair (Chiang) vs an independent reference, lobe by lobe.

Reference: pbrt-v4 ``HairBxDF`` (src/pbrt/bxdfs.cpp + bxdfs.h, Apache-2.0; Chiang,
Bitterli, Tappan, Burley 2016) re-implemented below in float64, with the two
Cycles conventions Blender renders with (bsdf_principled_hair_chiang.h, Apache-2.0):
the cuticle tilt is negated in setup (``bsdf->alpha = -bsdf->alpha``) and
h = sin(gamma_o) = dot(cross(Ng, X), Z) on the physical side of the axis.
With those conventions the single-fibre h-average below equals a Blender 5.2
Cycles render of the same fibre to 4 digits (0.02787 / 0.02492 / 0.02172; see
.astroray_plan/docs/pkg316-hair-dimness-diagnosis.md).

Gates:
  1. Lobe grid: engine f(wo, wi) (cos-folded) == reference to 1e-3 relative.
  2. White furnace (sigma_a = 0): every reference lobe integrates to 1 and the
     engine total to 1 within 1 %; the engine R lobe alone (sigma_a -> inf)
     integrates to its Fresnel weight within 1 %.
  3. Single sunlit fibre (render): h-averaged radiance == reference per channel
     (spectral path: sigma_a(lambda) from the JH-upsampled colour, pbrt-v4
     HairMaterial), specular glint on the lit side of the fibre.
  4. Thick-curve geometry: a Lambertian thick curve is lit on the side facing
     the light; neighbouring thick strands shadow each other as in Cycles.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = hasattr(astroray.Renderer, "eval_hair_material")
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray hair bindings not built")

ALPHA = 2.0 * math.pi / 180.0  # node Offset default


def _gpu_ok() -> bool:
    return AVAILABLE and bool(astroray.__features__.get("cuda", False))


BACKENDS = [False] + ([True] if _gpu_ok() else [])


# --------------------------------------------------------------------------
# pbrt-v4 HairBxDF reference (float64). Cycles alpha sign: tilt by -Offset.
# --------------------------------------------------------------------------
def _i0(x):
    val, x2i, ifact, i4 = 0.0, 1.0, 1, 1
    for i in range(10):  # pbrt-v4 / Cycles: 10-term series
        if i > 1:
            ifact *= i
        val += x2i / (i4 * ifact * ifact)
        x2i *= x * x
        i4 *= 4
    return val


def _log_i0(x):
    if x > 12:
        return x + 0.5 * (-math.log(2 * math.pi) + math.log(1 / x) + 1 / (8 * x))
    return math.log(_i0(x))


def _mp(ci, co, si, so, v):
    a, b = ci * co / v, si * so / v
    if v <= 0.1:
        return math.exp(_log_i0(a) - b - 1 / v + 0.6931 + math.log(1 / (2 * v)))
    return math.exp(-b) * _i0(a) / (math.sinh(1 / v) * 2 * v)


def _fr(c, eta):
    s2t = (1 - c * c) / eta ** 2
    if s2t >= 1:
        return 1.0
    ct = math.sqrt(1 - s2t)
    rpa = (eta * c - ct) / (eta * c + ct)
    rpe = (c - eta * ct) / (c + eta * ct)
    return 0.5 * (rpa ** 2 + rpe ** 2)


def _np(phi, p, s, go, gt):
    d = phi - (2 * p * gt - 2 * go + p * math.pi)
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    e = math.exp(-abs(d) / s)
    norm = 1 / (1 + math.exp(-math.pi / s)) - 1 / (1 + math.exp(math.pi / s))
    return e / (s * (1 + e) ** 2) / norm


class _RefHair:
    def __init__(self, h, sigma_a, bm, bn, eta=1.55, offset=ALPHA):
        self.h, self.eta, self.sig = h, eta, np.asarray(sigma_a, float)
        v0 = (0.726 * bm + 0.812 * bm ** 2 + 3.7 * bm ** 20) ** 2
        self.v = [v0, 0.25 * v0, 4 * v0, 4 * v0]
        self.s = 0.626657069 * (0.265 * bn + 1.194 * bn ** 2 + 5.372 * bn ** 22)
        a = -offset  # Cycles bsdf_hair_chiang_setup: bsdf->alpha = -bsdf->alpha
        self.s2 = [math.sin(a), math.sin(2 * a), math.sin(4 * a)]
        self.c2 = [math.cos(a), math.cos(2 * a), math.cos(4 * a)]

    def ap(self, cos_o):
        f = _fr(cos_o * math.sqrt(1 - self.h ** 2), self.eta)
        return f

    def lobes(self, wo, wi):
        """Per-lobe cos-folded f (pbrt f * |cos theta_i|), shape (4, 3)."""
        so = wo[0]; co = math.sqrt(max(0.0, 1 - so * so)); po = math.atan2(wo[2], wo[1])
        si = wi[0]; ci = math.sqrt(max(0.0, 1 - si * si)); pi_ = math.atan2(wi[2], wi[1])
        go = math.asin(self.h)
        ct = math.sqrt(1 - (so / self.eta) ** 2)
        sgt = self.h / (math.sqrt(self.eta ** 2 - so ** 2) / co)
        gt = math.asin(sgt)
        T = np.exp(-self.sig * (2 * math.sqrt(1 - sgt ** 2) / ct))
        f = self.ap(co)
        ap = [np.full(3, f), (1 - f) ** 2 * T]
        ap.append(ap[1] * T * f)
        ap.append(ap[2] * f * T / (1 - T * f))
        phi = pi_ - po
        tilt = [(so * self.c2[1] - co * self.s2[1], co * self.c2[1] + so * self.s2[1]),
                (so * self.c2[0] + co * self.s2[0], co * self.c2[0] - so * self.s2[0]),
                (so * self.c2[2] + co * self.s2[2], co * self.c2[2] - so * self.s2[2])]
        out = np.zeros((4, 3))
        for p in range(3):
            sop, cop = tilt[p]
            out[p] = _mp(ci, abs(cop), si, sop, self.v[p]) * ap[p] * _np(phi, p, self.s, go, gt)
        out[3] = _mp(ci, co, si, so, self.v[3]) * ap[3] / (2 * math.pi)
        return out


def _frame(tangent, wo):
    X = np.asarray(tangent, float); X /= np.linalg.norm(X)
    Y = np.cross(X, wo); Y /= np.linalg.norm(Y)
    return X, Y, np.cross(X, Y)


def _local(d, F):
    return np.array([d @ F[0], d @ F[1], d @ F[2]])


def _sigma_from_color(c, bn=0.3):
    d = 5.969 - 0.215 * bn + 2.532 * bn ** 2 - 10.73 * bn ** 3 + 5.574 * bn ** 4 + 0.245 * bn ** 5
    return (math.log(c) / d) ** 2


# --------------------------------------------------------------------------
# 1. Lobe grid
# --------------------------------------------------------------------------
def test_lobe_grid_matches_pbrt_v4_reference_with_cycles_tilt():
    r = astroray.Renderer()
    T = np.array([1.0, 0.0, 0.0])
    worst = 0.0
    for bm, bn, sig in [(0.3, 0.3, [0.2, 0.6, 1.4]), (0.1, 0.5, [0.0, 0.0, 0.0]),
                        (0.6, 0.2, [1.5, 3.0, 5.0])]:
        mat = r.create_material("principled_hair", [0.5, 0.5, 0.5], {
            "roughness": bm, "radial_roughness": bn,
            "parametrization": "absorption", "absorption_coefficient": sig})
        for hv in (0.1, 0.5, 0.62, 0.9):
            # engine h = 2*hair_v - 1 (thick-curve v; curves.h)
            ref = _RefHair(2 * hv - 1, sig, bm, bn)
            for tho in (-60, -20, 0, 35, 70):
                t = math.radians(tho)
                wo = np.array([math.sin(t), math.cos(t), 0.3]); wo /= np.linalg.norm(wo)
                F = _frame(T, wo)
                for ti_deg in (-75, -30, 0, 15, 50, 80):
                    for phd in (-170, -90, -20, 0, 40, 100, 179):
                        a, b = math.radians(ti_deg), math.radians(phd)
                        wi = math.sin(a) * F[0] + math.cos(a) * (math.cos(b) * F[1] + math.sin(b) * F[2])
                        e = np.asarray(r.eval_hair_material(mat, list(wo), list(wi), list(T), hv))
                        rf = ref.lobes(_local(wo, F), _local(wi, F)).sum(0)
                        worst = max(worst, float(np.max(np.abs(e - rf) / np.maximum(np.abs(rf), 1e-4))))
    print(f"\n[pkg316] lobe grid worst relative error {worst:.2e}")
    assert worst < 1e-3, f"hair f(wo,wi) deviates from the pbrt-v4/Cycles reference by {worst:.3g}"


# --------------------------------------------------------------------------
# 2. White furnace, per lobe and total (deterministic quadrature in sin(theta), phi)
# --------------------------------------------------------------------------
# Configurations keep a = cos(theta_i) cos(theta_o) / v below the range where the
# shared 10-term I0 series (pbrt-v4 and Cycles alike) under-normalises the R lobe
# (~1.3 % at h = 0.9, theta_o = 0; noted in the diagnosis doc).
@pytest.mark.parametrize("bm,hv,tho", [(0.3, 0.62, 35.0), (0.6, 0.5, 70.0), (0.2, 0.3, -40.0)])
def test_white_furnace_per_lobe_and_total(bm, hv, tho):
    r = astroray.Renderer()
    T = np.array([1.0, 0.0, 0.0])
    t = math.radians(tho)
    wo = np.array([math.sin(t), math.cos(t), 0.0])
    F = _frame(T, wo)
    lo = _local(wo, F)
    n = 120
    xs = -1 + (np.arange(n) + 0.5) * 2 / n
    ps = -math.pi + (np.arange(2 * n) + 0.5) * math.pi / n
    dw = (2 / n) * (math.pi / n)
    ref = _RefHair(2 * hv - 1, [0.0, 0.0, 0.0], bm, 0.3)
    clear = r.create_material("principled_hair", [0.5] * 3, {
        "roughness": bm, "radial_roughness": 0.3,
        "parametrization": "absorption", "absorption_coefficient": [0.0, 0.0, 0.0]})
    opaque = r.create_material("principled_hair", [0.5] * 3, {
        "roughness": bm, "radial_roughness": 0.3,
        "parametrization": "absorption", "absorption_coefficient": [1e4, 1e4, 1e4]})
    lob = np.zeros(4); total = 0.0; r_only = 0.0
    for x in xs:
        c = math.sqrt(1 - x * x)
        for p in ps:
            wi = x * F[0] + c * (math.cos(p) * F[1] + math.sin(p) * F[2])
            lob += ref.lobes(lo, _local(wi, F))[:, 0] * dw
            total += r.eval_hair_material(clear, list(wo), list(wi), list(T), hv)[0] * dw
            r_only += r.eval_hair_material(opaque, list(wo), list(wi), list(T), hv)[0] * dw
    f = ref.ap(math.cos(t))
    ap = np.array([f, (1 - f) ** 2, (1 - f) ** 2 * f, (1 - f) ** 2 * f * f / (1 - f)])
    per_lobe = lob / ap
    print(f"\n[pkg316] furnace bm={bm} hv={hv} tho={tho}: lobes {np.round(per_lobe, 4)} "
          f"engine total {total:.4f} engine R/F {r_only / f:.4f}")
    assert np.all(np.abs(per_lobe - 1) < 0.01), f"reference lobe normalisation {per_lobe}"
    assert abs(total - 1) < 0.01, f"engine white furnace {total:.4f}"
    assert abs(r_only / f - 1) < 0.01, f"engine R lobe {r_only:.5f} vs Fresnel {f:.5f}"


# --------------------------------------------------------------------------
# 3. Single sunlit fibre (render, ortho camera, black world)
# --------------------------------------------------------------------------
COLOR = (0.15, 0.09, 0.05)   # corpus v2 hair_tuft colour
RAD, RES, E_SUN = 0.1, 64, 2.0
SUN_TO = np.array([0.3, 0.5, 0.8]) / np.linalg.norm([0.3, 0.5, 0.8])


def _fibre_reference():
    sig = [_sigma_from_color(c) for c in COLOR]
    wo = np.array([0.0, 0.0, 1.0])
    F = _frame([1.0, 0.0, 0.0], wo)
    n = 400
    acc = np.zeros(3)
    for k in range(n):
        h = -1 + (k + 0.5) * 2 / n
        acc += _RefHair(h, sig, 0.3, 0.3).lobes(_local(wo, F), _local(SUN_TO, F)).sum(0)
    return E_SUN * acc / n


def _render_fibre(gpu, material="hair", strand=((-3.0, 0.0, 0.0), (3.0, 0.0, 0.0)), sun_to=SUN_TO,
                  spp=256):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    if material == "hair":
        m = r.create_material("principled_hair", list(COLOR), {
            "roughness": 0.3, "radial_roughness": 0.3, "parametrization": "reflectance",
            "color": list(COLOR)})
    else:
        m = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    pts = np.asarray(strand, np.float32)
    r.add_curves_bulk(pts, np.full(len(pts), RAD, np.float32), [len(pts)], m)
    r.set_curve_thick_mode(True)
    r.add_sun_light_dedicated(list(-np.asarray(sun_to)), 0.0, {"mode": "rgb", "color": [1, 1, 1]}, E_SUN)
    r.setup_camera([0, 0, 5], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 5.0, RES, RES,
                   orthographic=True, ortho_width=1.0, ortho_height=1.0)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 4)
    r.set_adaptive_sampling(False)
    if gpu:
        r.set_use_gpu(True)
    r.set_seed(31601)
    return np.asarray(r.render(spp, 4, None, False), np.float32).reshape(RES, RES, 3)


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_single_fibre_matches_reference(gpu):
    img = _render_fibre(gpu)
    cols = img[:, 8:56, :]
    band = (cols.sum(axis=0) / (2 * RAD * RES)).mean(axis=0)   # h-average per column
    ref = _fibre_reference()
    ratio = band / ref
    rows = cols.mean(axis=(1, 2))
    print(f"\n[pkg316] fibre {'gpu' if gpu else 'cpu'}: engine {np.round(band, 5)} "
          f"reference {np.round(ref, 5)} ratio {np.round(ratio, 4)} brightest row {int(rows.argmax())}")
    # Was 1.24 / 1.26 / 1.33 (pbrt tilt sign), then r 1.038 (piecewise-linear sigma(lambda)).
    assert np.all(np.abs(ratio - 1) < 0.015), f"single-fibre radiance / reference = {ratio}"
    # The sun is on the +y side (image top, row < 32): the R-lobe glint must be there.
    assert rows.argmax() < RES // 2, f"specular glint on the unlit side (row {rows.argmax()})"


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_thick_lambertian_curve_lit_side_faces_light(gpu):
    img = _render_fibre(gpu, material="lambertian", sun_to=np.array([0.0, 0.8, 0.6]), spp=16)
    rows = img[:, 20:44, 0].mean(axis=1)
    top, bottom = float(rows[:RES // 2].sum()), float(rows[RES // 2:].sum())
    print(f"\n[pkg316] lambertian curve lit(+y)={top:.3f} unlit(-y)={bottom:.3f}")
    assert top > 2.0 * bottom, f"thick-curve normal mirrored: +y half {top:.3f} vs -y half {bottom:.3f}"


# --------------------------------------------------------------------------
# 4. Thick-curve shading point and neighbouring strands
# --------------------------------------------------------------------------
@pytest.mark.parametrize("thick", [True, False], ids=["thick", "ribbon"])
def test_curve_shading_point_thick_surface_ribbon_axis(thick):
    """Cycles shades a THICK curve where the ray enters the tube and a RIBBON on
    its ray-facing plane through the axis. Ray along -y at z = 0.05 onto a
    radius-0.2 strand on the x axis: entry y = sqrt(0.2^2 - 0.05^2) = 0.1936."""
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    m = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_curves_bulk(np.asarray([(-3.0, 0.0, 0.0), (3.0, 0.0, 0.0)], np.float32),
                      np.full(2, 0.2, np.float32), [2], m)
    r.set_curve_thick_mode(thick)
    r.setup_camera([0.0, 5.0, 0.05], [0.0, 0.0, 0.05], [0.0, 0.0, 1.0], 40.0, 1.0, 0.0, 5.0, 3, 3,
                   orthographic=True, ortho_width=0.003, ortho_height=0.003)
    r.set_integrator("path_tracer")
    r.set_seed(7)
    r.render(1, 1, None, False)
    y = float(np.asarray(r.get_position_buffer())[1, 1][1])
    want = math.sqrt(0.2 ** 2 - 0.05 ** 2) if thick else 0.0
    assert abs(y - want) < 2e-3, f"{'thick' if thick else 'ribbon'} shading point y={y:.4f}, want {want:.4f}"


# pkg225 melanin tuft strands 5 and 6, sun, direct only.
def _tuft_strand(ci):
    x0 = -1.2 + 2.4 * ci / 13
    bow = 0.30 * np.sin(ci * 0.6)
    return [(x0 + bow * np.sin(t * np.pi), 1.2 - 2.4 * t, 0.12 * np.cos(t * np.pi + ci))
            for t in np.linspace(0.0, 1.0, 5)]


def _render_strands(gpu, cis):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    m = r.create_material("principled_hair", [0.5, 0.5, 0.5], {
        "roughness": 0.3, "radial_roughness": 0.3, "parametrization": "melanin",
        "melanin": 0.6, "melanin_redness": 0.0})
    pts = np.asarray([p for ci in cis for p in _tuft_strand(ci)], np.float32)
    r.add_curves_bulk(pts, np.full(len(pts), 0.045, np.float32), [5] * len(cis), m)
    r.set_curve_thick_mode(True)
    d = np.array([2.2, 1.4, 1.6]) / np.linalg.norm([2.2, 1.4, 1.6])
    r.add_sun_light_dedicated(list(-d), 0.0, {"mode": "rgb", "color": [1, 1, 1]}, 3.0)
    r.setup_camera([0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 40.0, 1.0, 0.0, 4.2, 96, 96)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 1)
    r.set_adaptive_sampling(False)
    if gpu:
        r.set_use_gpu(True)
    r.set_seed(31602)
    return float(np.asarray(r.render(128, 1, None, False), np.float32).sum())


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_neighbour_strand_shadowing_matches_cycles(gpu):
    """Cycles 5.2 (THICK, direct only, 256 spp): strands 5+6 together keep 0.959
    of their separate sums (6.854 vs 4.663 + 2.484 summed over RGB / 3). With the
    corrected h and tilt but shading at the axis, strand 6 shadowed strand 5's
    glint: 0.55 (the pre-pkg316 engine read 0.93 only through the mirrored glint)."""
    pair = _render_strands(gpu, [5, 6])
    alone = _render_strands(gpu, [5]) + _render_strands(gpu, [6])
    keep = pair / alone
    print(f"\n[pkg316] strands 5+6 keep {keep:.3f} of their separate radiance (Cycles 0.959)")
    assert keep > 0.93, f"neighbouring thick strands over-shadow: {keep:.3f} (Cycles 0.959)"
