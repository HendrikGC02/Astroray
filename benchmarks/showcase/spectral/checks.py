# -*- coding: utf-8 -*-
"""pkg324 - analytic checks for the spectral showcase corpus (normal Python env, numpy only).

* ``airy_*``: thin-film hue vs thickness. Single dielectric layer, Airy / transfer-matrix
  reflectance (Born & Wolf 1999, section 1.6.4; the model Belcour & Barla 2017 evaluate
  for Cycles' Principled thin film). The reflected spectrum under a flat (D65) RGB-white
  world is integrated with the CIE 1931 2 deg observer the engine itself bakes
  (``data/spectra/cie_cmf.inc``), then projected with the IEC 61966-2-1 matrix.
* ``prism_*``: minimum-deviation prism with the engine's own Sellmeier table
  (``include/astroray/optical_presets.h``, bk7 / flint_sf11 / diamond; Schott coefficients).
* ``furnace_*``: white-furnace energy of a lossless shell.

All functions are pure; ``measure_*`` helpers take linear ``.npy`` renders
(HxWx3, row 0 = top) and the manifest's fractional ROI rects.
"""
from __future__ import annotations

import colorsys
import math
import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]

# IEC 61966-2-1 XYZ(D65) -> linear sRGB (tests/test_issue767_observer_contract pins the engine to this).
M_SRGB = np.array([[3.2406, -1.5372, -0.4986],
                   [-0.9689, 1.8758, 0.0415],
                   [0.0557, -0.2040, 1.0570]])

# Sellmeier presets (include/astroray/optical_presets.h): B1..B3, C1..C3 (um^2).
SELLMEIER = {
    "bk7": ((1.03961212, 0.231792344, 1.01046945), (0.00600069867, 0.0200179144, 103.560653)),
    "flint_sf11": ((1.73759695, 0.313747346, 1.89878101), (0.013188707, 0.0623068142, 155.23629)),
    "diamond": ((0.3306, 4.3356, 0.0), (0.0175, 0.1060, 0.0)),
}


def _inc_array(name: str, filename: str) -> np.ndarray:
    txt = (REPO / "data" / "spectra" / filename).read_text(encoding="utf-8")
    body = re.search(name + r"\[\d+\]\s*=\s*\{(.*?)\};", txt, re.DOTALL).group(1)
    return np.array([float(v.strip().rstrip("f")) for v in body.split(",") if v.strip()])


_CACHE: dict = {}


def observer():
    """(lambda_nm[471], cmf[3,471], d65[471]); 360..830 nm at 1 nm."""
    if "obs" not in _CACHE:
        lam = np.arange(360.0, 831.0)
        cmf = np.stack([_inc_array(n, "cie_cmf.inc") for n in ("kCieCmfX", "kCieCmfY", "kCieCmfZ")])
        _CACHE["obs"] = (lam, cmf, _inc_array("kD65Spd", "illuminant_d65.inc"))
    return _CACHE["obs"]


def sellmeier_n(lam_nm, preset: str = "bk7"):
    """Refractive index n(lambda) from the engine's Sellmeier coefficients."""
    B, C = SELLMEIER[preset]
    l2 = (np.asarray(lam_nm, dtype=float) * 1e-3) ** 2
    return np.sqrt(1.0 + sum(b * l2 / (l2 - c) for b, c in zip(B, C)))


# --------------------------------------------------------------------------- #
# Thin film (Airy)
# --------------------------------------------------------------------------- #

def airy_reflectance(lam_nm, d_nm: float, n_film: float, n_sub: float, theta_deg: float = 0.0,
                     n_ambient: float = 1.0):
    """Unpolarised reflectance of one lossless film (n_film, thickness d) on a substrate, at the
    given incidence angle in the ambient medium (Born & Wolf eq 1.6.20 / transfer-matrix form)."""
    lam = np.asarray(lam_nm, dtype=float)
    s0 = n_ambient * math.sin(math.radians(theta_deg))
    c0 = math.cos(math.radians(theta_deg))
    c1 = math.sqrt(1.0 - (s0 / n_film) ** 2)
    c2 = math.sqrt(1.0 - (s0 / n_sub) ** 2)
    delta = 2.0 * math.pi * n_film * d_nm * c1 / lam  # one-way phase thickness
    out = 0.0
    for pol in ("s", "p"):
        if pol == "s":
            r01 = (n_ambient * c0 - n_film * c1) / (n_ambient * c0 + n_film * c1)
            r12 = (n_film * c1 - n_sub * c2) / (n_film * c1 + n_sub * c2)
        else:
            r01 = (n_film * c0 - n_ambient * c1) / (n_film * c0 + n_ambient * c1)
            r12 = (n_sub * c1 - n_film * c2) / (n_sub * c1 + n_film * c2)
        r = (r01 + r12 * np.exp(-2j * delta)) / (1.0 + r01 * r12 * np.exp(-2j * delta))
        out = out + 0.5 * np.abs(r) ** 2
    return out


def spectrum_to_linear_srgb(refl_fn):
    """Linear sRGB of ``refl_fn(lambda_nm)`` lit by a flat-RGB-white (D65) illuminant; the perfect
    reflector maps to (1, 1, 1)."""
    lam, cmf, d65 = observer()
    refl = np.asarray(refl_fn(lam), dtype=float)
    xyz = (cmf * (d65 * refl)).sum(axis=1)
    white_y = (cmf[1] * d65).sum()
    return M_SRGB @ (xyz / white_y)


def hue_deg(rgb) -> float:
    r, g, b = (float(max(c, 0.0)) for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360.0


def hue_diff_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def roi_mean(img: np.ndarray, rect) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    xs, xe = int(round(x0 * w)), max(int(round(x1 * w)), int(round(x0 * w)) + 1)
    ys, ye = int(round(y0 * h)), max(int(round(y1 * h)), int(round(y0 * h)) + 1)
    return img[ys:ye, xs:xe].reshape(-1, 3).mean(axis=0)


def airy_thin_film_check(img: np.ndarray, entry: dict) -> dict:
    """Per-thickness hue of the sphere-centre ROI vs the Airy prediction (manifest ``check`` block)."""
    chk = entry["check"]
    rows = {}
    for label, d_nm in chk["film_nm"].items():
        pred = spectrum_to_linear_srgb(lambda lam, d=d_nm: airy_reflectance(
            lam, d, chk["film_ior"], chk["substrate_ior"]))
        meas = roi_mean(img, entry["rois"][label])
        h_p, h_m = hue_deg(pred), hue_deg(meas)
        rows[label] = {"thickness_nm": d_nm, "pred_rgb_norm": (pred / pred.max()).round(4).tolist(),
                       "meas_rgb_norm": (meas / meas.max()).round(4).tolist(),
                       "pred_hue_deg": round(h_p, 2), "meas_hue_deg": round(h_m, 2),
                       "hue_err_deg": round(hue_diff_deg(h_p, h_m), 2)}
    rows["max_hue_err_deg"] = max(v["hue_err_deg"] for k, v in rows.items() if isinstance(v, dict))
    rows["pass"] = rows["max_hue_err_deg"] <= chk["tolerance_deg"]
    return rows


# --------------------------------------------------------------------------- #
# Furnace
# --------------------------------------------------------------------------- #

def furnace_check(img: np.ndarray, entry: dict) -> dict:
    exp, tol = entry["check"]["expected"], entry["check"]["tolerance"]
    out = {}
    for name, rect in entry["rois"].items():
        m = roi_mean(img, rect)
        out[name] = {"mean_rgb": m.round(4).tolist(), "max_abs_dev": round(float(np.abs(m - exp).max()), 4)}
    out["pass"] = all(v["max_abs_dev"] <= tol for v in out.values() if isinstance(v, dict))
    return out


# --------------------------------------------------------------------------- #
# Prism fan: 2-D Sellmeier ray trace vs the screen's left-edge channel crossings
# --------------------------------------------------------------------------- #

def _trace_prism(n: float, verts: np.ndarray, y0: float, x_start: float = -5.0):
    """2-D trace of a +X ray at height y0 through the convex polygon ``verts`` (CCW), air -> glass -> air.
    Returns (exit point, exit direction) or None (miss / TIR)."""
    d = np.array([1.0, 0.0])
    p = np.array([x_start, y0])
    n_in, n_out = 1.0, n
    inside = False
    for _ in range(2):
        best = None
        for i in range(len(verts)):
            a, b = verts[i], verts[(i + 1) % len(verts)]
            edge = b - a
            nrm = np.array([edge[1], -edge[0]])
            nrm /= np.linalg.norm(nrm)  # outward for a CCW polygon
            den = float(d @ nrm)
            if abs(den) < 1e-12:
                continue
            t = float((a - p) @ nrm) / den
            if t <= 1e-9:
                continue
            q = p + t * d
            if 0.0 <= float((q - a) @ edge) / float(edge @ edge) <= 1.0 and (best is None or t < best[0]):
                best = (t, q, nrm)
        if best is None:
            return None
        t, q, nrm = best
        nn = nrm if not inside else -nrm  # normal facing the incoming ray
        nn = nn if float(d @ nn) < 0 else -nn
        eta = n_in / n_out
        cosi = -float(d @ nn)
        k = 1.0 - eta * eta * (1.0 - cosi * cosi)
        if k < 0:
            return None  # TIR
        d = eta * d + (eta * cosi - math.sqrt(k)) * nn
        d /= np.linalg.norm(d)
        p = q
        n_in, n_out = n, 1.0
        inside = True
    return p, d


def prism_edge_profile(chk: dict, lam=None, n_rays: int = 41):
    """Per-wavelength footprint [u_lo, u_hi] (m, u = -s with s along t from the wall centre, so u grows to the
    right in the square-on check camera) of the window beam on the screen."""
    if lam is None:
        lam = observer()[0]
    ang = [math.radians(a) + math.radians(chk["prism_rot_deg"]) for a in (90.0, 210.0, 330.0)]
    rr = chk["prism_side_m"] / math.sqrt(3.0)
    verts = np.array([[rr * math.cos(a), rr * math.sin(a)] for a in ang])
    wc, tv = np.array(chk["wall_centre"]), np.array(chk["t_dir"])
    ev = np.array([tv[1], -tv[0]])  # exit direction e (t = (-e_y, e_x) -> e = (t_y, -t_x))
    ys = np.linspace(-chk["window_half_m"], chk["window_half_m"], n_rays)
    n_lam = sellmeier_n(lam, chk["preset"])
    lo, hi = np.full(len(lam), np.nan), np.full(len(lam), np.nan)
    for i, nl in enumerate(n_lam):
        ss = []
        for y0 in ys:
            r = _trace_prism(float(nl), verts, float(y0))
            if r is None:
                continue
            p, d = r
            if float(d @ ev) < math.cos(math.radians(10.0)):
                continue  # ray left through another face (does not reach the screen)
            tt = float((wc - p) @ ev) / float(d @ ev)
            q = p + tt * d
            ss.append(-float((q - wc) @ tv))
        if ss:
            lo[i], hi[i] = min(ss), max(ss)
    return lam, lo, hi


def _crossing(x: np.ndarray, y: np.ndarray, level: float) -> float:
    """First upward crossing of ``level`` by y(x) (linear interpolation)."""
    idx = np.where((y[:-1] < level) & (y[1:] >= level))[0]
    if len(idx) == 0:
        return float("nan")
    i = idx[0]
    return float(x[i] + (level - y[i]) * (x[i + 1] - x[i]) / (y[i + 1] - y[i]))


def prism_fan_prediction(chk: dict, blur_m: float = 0.0015):
    """Predicted left-edge 50 % crossings (m on the screen) of the clipped linear-sRGB channels."""
    lam, cmf, d65 = observer()
    band = (lam >= 380.0) & (lam <= 720.0)  # the CMFs are < 1e-3 of peak outside; the UV tail would only widen the edge
    lam, cmf, d65 = lam[band], cmf[:, band], d65[band]
    lam, lo, hi = prism_edge_profile(chk, lam)
    ok = ~np.isnan(lo)
    s_grid = np.arange(lo[ok].min() - 0.02, hi[ok].max() + 0.02, 0.0002)
    xyz = np.zeros((len(s_grid), 3))
    for i in np.where(ok)[0]:
        on = (s_grid >= lo[i]) & (s_grid <= hi[i])
        xyz[on] += (cmf[:, i] * d65[i])[None, :]
    if blur_m > 0:  # the engine's photon gather / pixel filter smooths the edge before the film clips
        k = np.arange(-4 * blur_m, 4 * blur_m + 1e-9, 0.0002)
        g = np.exp(-0.5 * (k / blur_m) ** 2)
        g /= g.sum()
        xyz = np.stack([np.convolve(xyz[:, c], g, mode="same") for c in range(3)], axis=1)
    rgb = np.clip((xyz / (cmf[1] * d65).sum()) @ M_SRGB.T, 0.0, None)  # (sums over the 380-720 band)
    core = (lam >= 400.0) & (lam <= 700.0)
    s_lo_common, s_hi_common = np.nanmax(lo[core]), np.nanmin(hi[core])
    mid = (s_grid > s_lo_common + 0.02) & (s_grid < s_hi_common - 0.02)
    plateau = rgb[mid].mean(axis=0)
    left = s_grid < (s_lo_common + 0.5 * (s_hi_common - s_lo_common))
    cross = [_crossing(s_grid[left], rgb[left, c], 0.5 * plateau[c]) for c in range(3)]
    return {"u_cross_m": cross, "plateau": plateau.tolist(), "u_common_lo_m": float(s_lo_common),
            "u_common_hi_m": float(s_hi_common)}


def prism_fan_check(img: np.ndarray, entry: dict) -> dict:
    chk = entry["check"]
    pred = prism_fan_prediction(chk)
    pts = sorted((float(k), v) for k, v in chk["px_at_s_m"].items())
    slope = -(pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])  # px per m of u = -s (> 0)
    s_to_px = lambda u: pts[1][1] + slope * u
    px_to_s = lambda x: (x - pts[1][1]) / slope  # (named s, but it is u)
    r0, r1 = chk["rows_px"]
    prof = img[r0:r1].mean(axis=0)  # (W, 3)
    xs = np.arange(prof.shape[0], dtype=float)
    kern = np.ones(3) / 3.0
    prof = np.stack([np.convolve(prof[:, c], kern, mode="same") for c in range(3)], axis=1)
    lo_px = s_to_px(pred["u_common_lo_m"] + 0.02)
    hi_px = s_to_px(pred["u_common_hi_m"] - 0.02)
    a, b = sorted((int(round(lo_px)), int(round(hi_px))))
    plateau = prof[a:b].mean(axis=0)
    left_stop = int(round(0.5 * (a + b)))
    lo_edge_px = int(round(s_to_px(min(pred["u_cross_m"]) - 0.04)))
    meas = []
    for c in range(3):
        sl = slice(max(lo_edge_px, 0), left_stop)
        meas.append(px_to_s(_crossing(xs[sl], prof[sl, c], 0.5 * plateau[c])))
    pc, mc = pred["u_cross_m"], meas
    sep_p, sep_m = pc[2] - pc[0], mc[2] - mc[0]  # blue minus red (m)
    L = chk["wall_distance_m"]
    return {"pred_cross_m_rgb": [round(v, 5) for v in pc], "meas_cross_m_rgb": [round(v, 5) for v in mc],
            "pred_sep_RB_mm": round(1e3 * sep_p, 2), "meas_sep_RB_mm": round(1e3 * sep_m, 2),
            "pred_sep_RB_deg": round(math.degrees(sep_p / L), 4), "meas_sep_RB_deg": round(math.degrees(sep_m / L), 4),
            "rel_err": round(abs(sep_m - sep_p) / abs(sep_p), 4), "pass": abs(sep_m - sep_p) / abs(sep_p) <= chk["tolerance"]}


# --------------------------------------------------------------------------- #
# Bounce cap (pkg325 acceptance scene) and dispatcher
# --------------------------------------------------------------------------- #

def luminance(img: np.ndarray) -> np.ndarray:
    return img @ np.array([0.2126, 0.7152, 0.0722])


def bounce_cap_check(imgs: dict, entry: dict) -> dict:
    """Report-only metrics per bounce-cap variant vs the high-bounce reference variant: ROI mean ratio and the
    fraction of ROI pixels darker than ``dark_threshold_frac_of_ref_mean`` x the reference ROI mean luminance
    ("dead spots")."""
    ref_id = entry["reference_variant"]
    thr_frac = entry["check"]["dark_threshold_frac_of_ref_mean"]
    rect = next(iter(entry["rois"].values()))

    def crop(img):
        h, w = img.shape[:2]
        x0, y0, x1, y1 = rect
        return img[int(round(y0 * h)):int(round(y1 * h)), int(round(x0 * w)):int(round(x1 * w))]
    ref = crop(imgs[ref_id])
    ref_mean = float(luminance(ref).mean())
    out = {"reference": ref_id, "ref_roi_luminance": round(ref_mean, 5)}
    for vid, img in imgs.items():
        c = crop(img)
        lum = luminance(c)
        out[vid] = {"roi_mean_ratio_vs_ref": round(float(lum.mean()) / ref_mean, 4),
                    "dark_pixel_fraction": round(float((lum < thr_frac * ref_mean).mean()), 4)}
    return out


def run_check(entry: dict, imgs: dict):
    """``imgs``: {variant_id: HxWx3 linear array} for ONE leg. Returns a result dict or None (no analytic check)."""
    kind = entry.get("check", {}).get("kind")
    if kind == "airy_thin_film":
        return airy_thin_film_check(imgs["default"], entry)
    if kind == "white_furnace_energy":
        return furnace_check(imgs["default"], entry)
    if kind == "prism_fan_sellmeier":
        return prism_fan_check(imgs["default"], entry)
    if kind == "bounce_cap_dead_spots":
        return bounce_cap_check(imgs, entry)
    return None
