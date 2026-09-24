# -*- coding: utf-8 -*-
"""pkg276 analytic reference: Cycles IES x spot composition in numpy.

Pure numpy (no Blender, no engine). Used by the pkg276 CPU/GPU gates
(tests/test_pkg276_*.py) and the Cycles A/B driver (ies_leg.py / ab.py in
this directory).

Ported from Blender 5.2 Cycles (Apache-2.0):
  * util/ies.cpp        IESFile::parse, IESFile::process_type_c, IESFile::process
  * kernel/util/ies.h   kernel_ies_interp, interpolate_ies_vertical
  * util/math_base.h    cubic_interp, smoothstepf, inverse_lerp
  * kernel/svm/ies.h    svm_node_ies (v_angle = acos(-z), h_angle = atan2(x, y) + pi)
  * kernel/light/spot.h spot_light_attenuation, spot_light_to_local
  * scene/light.cpp     SpotLight::copy_to_kernel (cos_half_spot_angle, spot_smooth),
                        PointLight::copy_to_kernel (eval_fac = 1/(4*pi) at radius 0)
Notes: .astroray_plan/docs/pkg276-ies-spot-research.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# util/ies.cpp: candela (lm/sr) -> W/sr via D65 efficacy 177.83 lm/W, x 4*pi.
K_CANDELA_TO_WATT = 0.0706650768394


@dataclass
class IESTable:
    """Cycles' processed IES layout (radians; intensity[h][v] already scaled)."""
    h_angles: np.ndarray
    v_angles: np.ndarray
    intensity: np.ndarray  # shape (h_num, v_num)


def _angle_close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-4


def parse_ies(text: str) -> IESTable:
    """IESFile::parse + IESFile::process for photometric type C (util/ies.cpp)."""
    text = text.replace(",", " ")
    pos = text.find("\nTILT=")
    if pos < 0:
        raise ValueError("no TILT= line")
    rest = text[pos + 1:]
    line_end = rest.find("\n")
    tilt_line = rest[:line_end]
    body = rest[line_end + 1:].split()
    if tilt_line.startswith("TILT=INCLUDE"):
        # lamp-to-luminaire geometry, count, then 2*count values.
        n = int(body[1])
        body = body[2 + 2 * n:]
    vals = iter(body)
    nxt = lambda: float(next(vals))  # noqa: E731
    nxt()                      # number of lamps
    nxt()                      # lumens per lamp
    factor = nxt()             # candela multiplier
    v_num = int(nxt())
    h_num = int(nxt())
    ptype = int(nxt())
    if ptype != 1:
        raise NotImplementedError("reference ports photometric type C only")
    nxt(); nxt(); nxt(); nxt()  # units, width, length, height
    factor *= nxt()            # ballast factor
    factor *= nxt()            # ballast-lamp photometric factor
    nxt()                      # input watts
    factor *= K_CANDELA_TO_WATT
    v = [nxt() for _ in range(v_num)]
    h = [nxt() for _ in range(h_num)]
    inten = [[factor * nxt() for _ in range(v_num)] for _ in range(h_num)]

    # IESFile::process_type_c
    if _angle_close(h[0], 90.0):
        h = [a - 90.0 for a in h]
    if len(h) == 1:
        h = [0.0, 360.0]
        inten.append(list(inten[0]))
    if _angle_close(h[-1], 90.0):
        hnum = len(h)
        for i in range(hnum - 2, -1, -1):
            h.append(180.0 - h[i])
            inten.append(list(inten[i]))
    if _angle_close(h[-1], 180.0):
        hnum = len(h)
        for i in range(hnum - 2, -1, -1):
            h.append(360.0 - h[i])
            inten.append(list(inten[i]))
    if _angle_close(h[0], 0.0) and not _angle_close(h[-1], 360.0):
        hnum = len(h)
        last_step = h[hnum - 1] - h[hnum - 2]
        first_step = h[1] - h[0]
        gap_step = 360.0 - h[hnum - 1]
        if _angle_close(last_step, gap_step) or _angle_close(first_step, gap_step):
            h.append(360.0)
            inten.append(list(inten[0]))

    # Cycles stores float32 radians (`angle *= M_PI_F / 180.f`).
    deg = np.float32(np.float32(math.pi) / np.float32(180.0))
    return IESTable(
        h_angles=np.asarray(h, dtype=np.float32) * deg,
        v_angles=np.asarray(v, dtype=np.float32) * deg,
        intensity=np.asarray(inten, dtype=np.float64),
    )


def _cubic_interp(a, b, c, d, x):
    """util/math_base.h cubic_interp (Catmull-Rom)."""
    return 0.5 * (((d + 3.0 * (b - c) - a) * x + (2.0 * a - 5.0 * b + 4.0 * c - d)) * x
                  + (c - a)) * x + b


def ies_interp(t: IESTable, h_angle, v_angle):
    """kernel/util/ies.h kernel_ies_interp, vectorised over arrays of angles."""
    h_angle = np.asarray(h_angle, dtype=np.float64)
    v_angle = np.asarray(v_angle, dtype=np.float64)
    H = t.h_angles.astype(np.float64)
    V = t.v_angles.astype(np.float64)
    I = t.intensity
    h_num, v_num = len(H), len(V)

    valid = ((v_angle >= V[0]) & (v_angle < V[-1]) & (h_angle >= H[0]) & (h_angle < H[-1]))
    # Evaluated in float32 exactly as the kernel does: 1e-7f is below the ulp at
    # 2*pi and pi, so M_2PI_F - 1e-7f == M_2PI_F and a 0..360 table (or a 0..180
    # vertical range) does NOT wrap in Cycles. Parity reproduces that.
    f32 = np.float32
    wrap_h = bool(t.h_angles[0] < f32(1e-7)
                  and t.h_angles[-1] > f32(f32(2.0 * math.pi) - f32(1e-7)))
    wrap_vlow = bool(t.v_angles[0] < f32(1e-7))
    wrap_vhigh = bool(t.v_angles[-1] > f32(f32(math.pi) - f32(1e-7)))

    hs = np.where(valid, h_angle, H[0])
    vs = np.where(valid, v_angle, V[0])
    # `for (h_i = 0; H(h_i + 1) < h_angle; h_i++)`
    h_i = np.searchsorted(H[1:], hs, side="left")
    v_i = np.searchsorted(V[1:], vs, side="left")
    h_i = np.clip(h_i, 0, h_num - 2)
    v_i = np.clip(v_i, 0, v_num - 2)
    h_frac = (hs - H[h_i]) / (H[h_i + 1] - H[h_i])
    v_frac = (vs - V[v_i]) / (V[v_i + 1] - V[v_i])

    def vert(h):
        c = I[h, v_i + 1]
        b = I[h, v_i]
        a_idx = np.where(v_i > 0, v_i - 1, 1 if wrap_vlow else v_i)
        a = np.where((v_i > 0) | wrap_vlow, I[h, np.clip(a_idx, 0, v_num - 1)], b)
        d_idx = np.where(v_i + 2 < v_num, v_i + 2, v_num - 2)
        d = np.where((v_i + 2 < v_num) | wrap_vhigh, I[h, np.clip(d_idx, 0, v_num - 1)], c)
        return _cubic_interp(a, b, c, d, v_frac)

    b = vert(h_i)
    c = vert(h_i + 1)
    a_h = np.where(h_i > 0, h_i - 1, h_num - 2)
    a = np.where((h_i > 0) | wrap_h, vert(a_h), b)
    d_h = np.where(h_i + 2 < h_num, h_i + 2, 1)
    # NOTE: Cycles falls back to `b` (not `c`) for the last h point.
    d = np.where((h_i + 2 < h_num) | wrap_h, vert(np.clip(d_h, 0, h_num - 1)), b)
    out = np.maximum(_cubic_interp(a, b, c, d, h_frac), 0.0)
    return np.where(valid, out, 0.0)


def ies_angles(local_dir):
    """kernel/svm/ies.h: v = acos(-z), h = atan2(x, y) + pi on the light-local
    direction from the light toward the lit point (Geometry:Incoming -> object
    space, scene/shader_graph.cpp LINK_TEXTURE_INCOMING)."""
    d = local_dir / np.linalg.norm(local_dir, axis=-1, keepdims=True)
    v = np.arccos(np.clip(-d[..., 2], -1.0, 1.0))
    h = np.arctan2(d[..., 0], d[..., 1]) + math.pi
    return h, v


def smoothstepf(f):
    f = np.asarray(f, dtype=np.float64)
    ff = f * f
    return np.where(f <= 0.0, 0.0, np.where(f >= 1.0, 1.0, 3.0 * ff - 2.0 * ff * f))


def spot_attenuation(cos_axis, spot_size, spot_blend):
    """kernel/light/spot.h spot_light_attenuation with scene/light.cpp fields."""
    cos_half = math.cos(spot_size * 0.5)
    spot_smooth = 1.0 / ((1.0 - cos_half) * spot_blend)
    return smoothstepf((np.asarray(cos_axis) - cos_half) * spot_smooth)


def cycles_cone_angles(spot_size, spot_blend):
    """(inner, outer) half-angles whose linear-in-cos smoothstep
    t = (cos - cos_outer) / (cos_inner - cos_outer) equals the Cycles field."""
    cos_half = math.cos(spot_size * 0.5)
    cos_inner = cos_half + (1.0 - cos_half) * spot_blend
    return math.acos(min(cos_inner, 1.0)), spot_size * 0.5


def rotation_z(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


@dataclass
class SpotScene:
    """Controlled single-spot scene (Blender world, Z up). A downward spot over a
    grey Lambertian plane at z=0, top-down pinhole camera, black world."""
    light_pos: tuple = (0.25, -0.15, 2.0)
    light_rot_z_deg: float = 30.0      # spin about the (vertical) axis
    power: float = 100.0               # Blender light.energy (W)
    spot_size: float = math.radians(60.0)
    spot_blend: float = 0.15
    kind: str = "SPOT"                 # or "POINT"
    albedo: float = 0.5
    cam_height: float = 6.0
    fov_deg: float = 30.0
    res: int = 200
    radius: float = 0.0                # Blender shadow_soft_size
    soft_falloff: bool = True          # Blender use_soft_falloff (default True)
    # #852 AREA A/B (ies_leg.py only; no analytic reference for AREA here).
    area_size: tuple = (1.0, 1.0)      # Blender light.size, size_y (m)
    area_shape: str = "RECTANGLE"
    spread: float = math.pi            # Blender light.spread (full angle, rad)
    light_rot_x_deg: float = 0.0       # tilt about X, applied before the Z spin

    def rotation(self) -> np.ndarray:
        """Light object rotation (columns = local X, Y, Z in world); the light
        emits along local -Z, so an unrotated light points straight down.
        Blender XYZ euler: R = Rz @ Rx."""
        a = math.radians(self.light_rot_x_deg)
        c, s = math.cos(a), math.sin(a)
        rx = np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
        return rotation_z(self.light_rot_z_deg) @ rx


def plane_points(sc: SpotScene, sub: int = 1, divisor: float | None = None):
    """World points on z=0 for each pixel (row 0 = top = +Y), `sub` x `sub`
    stratified subsamples per pixel. Returns (res, res, sub*sub, 3).

    `divisor` is the raster->NDC divisor: `res` for Blender/Cycles (default).
    The Astroray camera divides by `res - 1` on both backends (raytracer.h
    render loop, stage_init.cu; documented and deferred in pkg212 spec line 34),
    so engine-direct gates pass `res - 1` to sample the same plane points."""
    n = sc.res
    div = float(n if divisor is None else divisor)
    half = sc.cam_height * math.tan(math.radians(sc.fov_deg) * 0.5)
    o = (np.arange(sub) + 0.5) / sub
    sy, sx = np.meshgrid(o, o, indexing="ij")
    sx, sy = sx.ravel(), sy.ravel()
    j = np.arange(n)[None, :, None]
    i = np.arange(n)[:, None, None]
    ndc_x = (j + sx[None, None, :]) / div * 2.0 - 1.0
    ndc_y = 1.0 - (i + sy[None, None, :]) / div * 2.0
    x = np.broadcast_to(ndc_x * half, (n, n, sub * sub))
    y = np.broadcast_to(ndc_y * half, (n, n, sub * sub))
    return np.stack([x, y, np.zeros_like(x)], axis=-1)


def _emit_factor(sc, table, ies_strength, dirw, spot_mask=None):
    """Directional emission factor along world dirs (light -> lit point): spot
    attenuation x IES, both in the light-local frame. `spot_mask` False = no
    spot attenuation there (Cycles skips it inside a sphere lamp)."""
    local = dirw @ sc.rotation()                # (dir . X, dir . Y, dir . Z)
    f = np.ones(dirw.shape[:-1])
    if sc.kind == "SPOT":
        att = spot_attenuation(-local[..., 2], sc.spot_size, sc.spot_blend)
        f = f * (att if spot_mask is None else np.where(spot_mask, att, 1.0))
    if table is not None:
        h, v = ies_angles(local)
        f = f * ies_strength * ies_interp(table, h, v)
    return f


def _gauss_legendre_01(n):
    x, w = np.polynomial.legendre.leggauss(n)
    return 0.5 * (x + 1.0), 0.5 * w


def _radiance_area(sc, table, ies_strength, P, nq_r=12, nq_phi=48):
    """radius > 0 (Cycles kernel/light/point.h, spot.h). Radiance of the lamp
    surface L_e = P_w * eval_fac, eval_fac = 1/(4 pi r^2 * pi) (scene/light.cpp,
    area = 4 pi r^2 in BOTH modes). use_soft_falloff (is_sphere = false): an
    oriented disk of radius r facing the lit point, E = int L_e f cos_l cos_i / t^2 dA.
    Sphere (use_soft_falloff off): the visible cap, E = int L_e f cos_i dw.
    Quadrature: Gauss-Legendre in the radial / cos variable, uniform in phi."""
    L = np.asarray(sc.light_pos, dtype=np.float64)
    r = sc.radius
    Le = sc.power / (4.0 * math.pi * r * r * math.pi)
    xr, wr = _gauss_legendre_01(nq_r)
    phi = (np.arange(nq_phi) + 0.5) / nq_phi * 2.0 * math.pi
    shape = P.shape[:-1]
    Pf = P.reshape(-1, 3)
    E = np.zeros(len(Pf))
    for c0 in range(0, len(Pf), 4096):
        Pc = Pf[c0:c0 + 4096]
        n = Pc - L
        d = np.linalg.norm(n, axis=-1)
        n = n / d[:, None]                      # light -> point
        a = np.where(np.abs(n[:, 0:1]) > 0.9, [[0.0, 1.0, 0.0]], [[1.0, 0.0, 0.0]])
        u = a - n * (n * a).sum(-1, keepdims=True)
        u /= np.linalg.norm(u, axis=-1, keepdims=True)
        v = np.cross(n, u)
        acc = np.zeros(len(Pc))
        for xi, wi in zip(xr, wr):
            for ph in phi:
                if sc.soft_falloff:
                    rho = r * math.sqrt(xi)          # area-uniform in rho^2
                    Q = L + rho * (math.cos(ph) * u + math.sin(ph) * v)
                    PQ = Pc - Q                      # disk point -> lit point
                    t = np.linalg.norm(PQ, axis=-1)
                    dirw = PQ / t[:, None]
                    cos_l = np.abs((n * dirw).sum(-1))
                    cos_i = np.clip(-dirw[:, 2], 0.0, None)
                    val = Le * _emit_factor(sc, table, ies_strength, dirw) * cos_l * cos_i / (t * t)
                    acc += wi * val * (math.pi * r * r) / len(phi)
                else:
                    outside = d > r
                    # Outside: the visible cap; inside: every direction hits the lamp.
                    cos_a = np.where(outside, np.sqrt(np.maximum(0.0, 1.0 - r * r / (d * d))), -1.0)
                    ct = 1.0 - xi * (1.0 - cos_a)    # uniform in cos over the cap
                    st = np.sqrt(np.maximum(0.0, 1.0 - ct * ct))
                    w = -n                            # point -> light centre
                    om = (ct[:, None] * w + st[:, None] * (math.cos(ph) * u + math.sin(ph) * v))
                    dirw = -om                        # lamp surface -> lit point
                    cos_i = np.clip(om[:, 2], 0.0, None)
                    dom = 2.0 * math.pi * (1.0 - cos_a) / len(phi)
                    acc += wi * Le * _emit_factor(sc, table, ies_strength, dirw, outside) * cos_i * dom
        E[c0:c0 + 4096] = acc
    return E.reshape(shape)


def radiance(sc: SpotScene, table: IESTable | None, ies_strength: float = 1.0, sub: int = 4,
             divisor: float | None = None):
    """Linear radiance (res, res) of the plane: rho/pi * I(dir) * cos_i / d^2 with
    I = P/(4 pi) * spot_attenuation * ies_fac (Cycles light/sample.h: shader
    emission * eval_fac * strength; radius-0 point/spot pdf = d^2). radius > 0:
    see _radiance_area."""
    P = plane_points(sc, sub, divisor)
    if sc.radius > 0.0:
        return (sc.albedo / math.pi * _radiance_area(sc, table, ies_strength, P)).mean(axis=-1)
    L = np.asarray(sc.light_pos, dtype=np.float64)
    d_vec = P - L                               # light -> point (world)
    dist = np.linalg.norm(d_vec, axis=-1)
    dirw = d_vec / dist[..., None]
    R = sc.rotation()
    local = dirw @ R                            # (dir . X, dir . Y, dir . Z)
    cos_axis = -local[..., 2]                   # spot axis = local -Z
    intensity = np.full(dist.shape, sc.power / (4.0 * math.pi))
    if sc.kind == "SPOT":
        intensity = intensity * spot_attenuation(cos_axis, sc.spot_size, sc.spot_blend)
    if table is not None:
        h, v = ies_angles(local)
        intensity = intensity * ies_strength * ies_interp(table, h, v)
    cos_i = np.clip(-dirw[..., 2], 0.0, None)   # plane normal +Z
    rad = sc.albedo / math.pi * intensity * cos_i / (dist * dist)
    return rad.mean(axis=-1)


def pixel_geometry(sc: SpotScene, divisor: float | None = None):
    """Per-pixel-centre angle from the spot axis (deg) and light-local azimuth
    (deg, Cycles h convention) -> (theta_deg, h_deg), each (res, res)."""
    P = plane_points(sc, 1, divisor)[:, :, 0, :]
    d = P - np.asarray(sc.light_pos, dtype=np.float64)
    d = d / np.linalg.norm(d, axis=-1, keepdims=True)
    local = d @ sc.rotation()
    theta = np.degrees(np.arccos(np.clip(-local[..., 2], -1.0, 1.0)))
    h, _ = ies_angles(local)
    return theta, np.degrees(h)


def binned_ratio(img, ref, key, edges, min_ref_frac=0.02, min_pixels=20):
    """Per-bin, per-channel mean(img)/mean(ref) over pixels with `key` in each
    [edges[k], edges[k+1]). Bins whose reference mean is below `min_ref_frac` of
    the peak bin (noise floor / outside the cone) are reported with ratio NaN.
    img: (H, W, 3); ref: (H, W). Returns list of dicts."""
    peak = 0.0
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (key >= lo) & (key < hi)
        n = int(m.sum())
        rmean = float(ref[m].mean()) if n else 0.0
        imean = img[m].reshape(-1, 3).mean(axis=0) if n else np.zeros(3)
        rows.append({"lo": float(lo), "hi": float(hi), "n": n, "ref": rmean,
                     "img": [float(x) for x in imean]})
        peak = max(peak, rmean)
    for r in rows:
        ok = r["n"] >= min_pixels and r["ref"] >= min_ref_frac * peak and r["ref"] > 0
        r["ratio"] = [x / r["ref"] if ok else float("nan") for x in r["img"]]
    return rows


# --------------------------------------------------------------------------- #
# Synthetic LM-63 profiles (formula-built, not a real fixture).
# --------------------------------------------------------------------------- #
def asym_profile_lm63(base: float = 60.0, h_step: int = 30, v_step: int = 5,
                      v_max: int = 90, include_360: bool = True) -> str:
    """Type-C profile with radial rings AND an azimuth lobe with no mirror axis:
    a(h) = 1 + 0.6 cos(h - 40) + 0.3 cos(2h - 170)  (p2 = 2 p1 + 90 deg), and
    g(v) = 0.55 + 0.45 cos(v * 12 deg/deg) (30-deg period, 6 samples/period so
    cubic vs linear interpolation differ at the troughs)."""
    v_angles = list(range(0, v_max + 1, v_step))
    h_end = 360 if include_360 else 360 - h_step
    h_angles = list(range(0, h_end + 1, h_step))

    def g(v):
        return 0.55 + 0.45 * math.cos(math.radians(v * 12.0))

    def a(h):
        return (1.0 + 0.6 * math.cos(math.radians(h - 40.0))
                + 0.3 * math.cos(math.radians(2.0 * h - 170.0)))

    rows = [" ".join(f"{base * g(v) * a(h % 360):.4f}" for v in v_angles) for h in h_angles]
    return "\n".join([
        "IESNA:LM-63-2002",
        "[TEST] pkg276 synthetic asymmetric profile (formula-built)",
        "TILT=NONE",
        f"1 -1 1.0 {len(v_angles)} {len(h_angles)} 1 2 0.0 0.0 0.0",
        "1.0 1.0 100.0",
        " ".join(str(v) for v in v_angles),
        " ".join(str(h) for h in h_angles),
        *rows,
    ]) + "\n"
