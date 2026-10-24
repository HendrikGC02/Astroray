"""pkg325 acceptance scene: numpy geometry core (no bpy, no astroray import).

Shared by the engine-only tests (``engine_scene.py``) and the headless-Blender
``.blend`` builder (``build_blend.py``), so both legs render the SAME triangles.
All coordinates are Blender world space (Z up, metres); ``to_engine`` maps to the
engine's Y-up frame (x, z, -y).

Scene "thick glass stack": three glass panes staggered in depth (each 0.30 thick,
0.10 m apart) in front of a solid glass tumbler, a diffuse floor and a white world.
A camera ray through all three panes crosses 6 glass interfaces, so a path-depth cap
below 7 leaves a dark (terminated) region while 8 / 12 / 64 do not.

Mesh hygiene (the pkg324 sp07 tumbler broke all three, issue #1160): every closed
mesh has outward winding (signed volume > 0), no coplanar overlapping faces (within or
across meshes), and >= 1 mm clearance between distinct bodies and the floor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MIN_GAP = 1e-3  # metres; the hygiene floor for any two bodies

CAMERA = {"loc": (0.0, -6.2, 1.1), "target": (0.0, 0.5, 1.1), "lens": 50.0, "sensor": 36.0}
RES = (320, 240)
FLOOR_Z = 0.0


@dataclass
class Mesh:
    name: str
    tris: np.ndarray            # (N, 3, 3) float64, Blender coordinates, CCW seen from outside
    kind: str = "glass"         # "glass" | "floor" | "opaque" (diffuse prop)
    smooth: bool = False        # smooth shading (tumbler wall); boxes are flat
    color: tuple = (0.4, 0.4, 0.4)  # diffuse albedo for floor / opaque
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #

def signed_volume(tris: np.ndarray) -> float:
    """Divergence-theorem volume of a closed triangle soup; > 0 iff wound outward."""
    return float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6.0)


def box(name: str, center, size, rot_z_deg: float = 0.0) -> Mesh:
    cx, cy, cz = center
    sx, sy, sz = size
    c, s = math.cos(math.radians(rot_z_deg)), math.sin(math.radians(rot_z_deg))
    def v(dx, dy, dz):
        x, y = dx * sx / 2, dy * sy / 2
        return (cx + c * x - s * y, cy + s * x + c * y, cz + dz * sz / 2)
    # faces as CCW quads seen from outside
    quads = [
        ((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)),   # -z
        ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),       # +z
        ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),   # -y
        ((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)),       # +y
        ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),   # -x
        ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),       # +x
    ]
    tris = []
    for q in quads:
        a, b, c2, d = (v(*p) for p in q)
        tris.append([a, b, c2])
        tris.append([a, c2, d])
    return Mesh(name, np.asarray(tris, dtype=np.float64), "glass", False)


def prop_box(name, center, size, color) -> Mesh:
    m = box(name, center, size)
    m.kind, m.color = "opaque", color
    return m


def revolve_solid(name: str, profile, segs: int = 48, center_xy=(0.0, 0.0), z_base: float = 0.0) -> Mesh:
    """Revolve an OPEN (r, z) profile that starts and ends on the axis (r == 0) into a
    closed solid. The profile is traversed bottom -> top along the outer wall; winding is
    chosen from the signed volume, so the result is outward by construction."""
    prof = [(float(r), float(z) + z_base) for r, z in profile]
    assert prof[0][0] == 0.0 and prof[-1][0] == 0.0, "profile must start and end on the axis"
    cx, cy = center_xy
    ring = lambda r, z, k: (cx + r * math.cos(2 * math.pi * k / segs), cy + r * math.sin(2 * math.pi * k / segs), z)
    tris = []
    for i in range(len(prof) - 1):
        (r0, z0), (r1, z1) = prof[i], prof[i + 1]
        for k in range(segs):
            k2 = (k + 1) % segs
            a, b = ring(r0, z0, k), ring(r0, z0, k2)
            c, d = ring(r1, z1, k2), ring(r1, z1, k)
            if r0 == 0.0:
                tris.append([a, c, d])
            elif r1 == 0.0:
                tris.append([a, b, c])
            else:
                tris.append([a, b, c])
                tris.append([a, c, d])
    tris = np.asarray(tris, dtype=np.float64)
    if signed_volume(tris) < 0:
        tris = tris[:, [0, 2, 1]]
    return Mesh(name, tris, "glass", True)


def floor_quad(half: float = 40.0, z: float = FLOOR_Z) -> Mesh:
    q = [(-half, -half, z), (half, -half, z), (half, half, z), (-half, half, z)]   # CCW from +z
    return Mesh("Floor", np.asarray([[q[0], q[1], q[2]], [q[0], q[2], q[3]]], dtype=np.float64), "floor", False,
                (0.4, 0.4, 0.4))


# --------------------------------------------------------------------------- #
# The scene
# --------------------------------------------------------------------------- #

PANE_T = 0.30
PANE_GAP = 0.10
PANE_W, PANE_H = 1.8, 1.9
PANE_X = (-0.5, 0.0, 0.5)
LIFT = 0.002  # 2 mm clearance under every glass body


def glass_meshes() -> list[Mesh]:
    zc = FLOOR_Z + LIFT + PANE_H / 2
    panes = []
    for i, x in enumerate(PANE_X):
        y = -0.6 + i * (PANE_T + PANE_GAP)
        panes.append(box(f"Pane{i}", (x, y + PANE_T / 2, zc), (PANE_W, PANE_T, PANE_H)))
    # solid flared tumbler in front-left, standing on the floor (convex profile, rounded foot)
    prof = [(0.0, 0.0), (0.30, 0.0), (0.36, 0.05), (0.42, 0.6), (0.50, 1.25), (0.0, 1.25)]
    tumbler = revolve_solid("Tumbler", prof, segs=48, center_xy=(-1.75, -1.3), z_base=FLOOR_Z + LIFT)
    return panes + [tumbler]


def prop_meshes() -> list[Mesh]:
    """Diffuse blocks behind the stack (so the panes' refraction is visible); 2 mm off the floor."""
    return [prop_box("BlockRed", (-0.9, 2.4, LIFT + 0.5), (0.9, 0.9, 1.0), (0.75, 0.12, 0.10)),
            prop_box("BlockBlue", (1.0, 3.0, LIFT + 0.4), (0.9, 0.9, 0.8), (0.10, 0.25, 0.75))]


def scene_meshes() -> list[Mesh]:
    return glass_meshes() + prop_meshes() + [floor_quad()]


def to_engine(p: np.ndarray) -> np.ndarray:
    """Blender (x, y, z) -> engine (x, z, -y)."""
    return np.stack([p[..., 0], p[..., 2], -p[..., 1]], axis=-1)


def corner_normals(tris: np.ndarray, smooth: bool, angle_deg: float = 40.0) -> np.ndarray:
    """Per-corner normals (N,3,3) in the input frame. Flat meshes: face normals. Smooth:
    area-weighted average of the faces sharing the corner position whose normals differ
    from this face by < angle_deg (Blender auto-smooth)."""
    fn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    area = np.linalg.norm(fn, axis=1, keepdims=True)
    fnu = fn / np.maximum(area, 1e-30)
    out = np.repeat(fnu[:, None, :], 3, axis=1)
    if not smooth:
        return out
    cos_lim = math.cos(math.radians(angle_deg))
    groups: dict = {}
    for t in range(len(tris)):
        for c in range(3):
            groups.setdefault(tuple(np.round(tris[t, c], 6)), []).append(t)
    for t in range(len(tris)):
        for c in range(3):
            fs = groups[tuple(np.round(tris[t, c], 6))]
            m = np.array([f for f in fs if fnu[f] @ fnu[t] >= cos_lim])
            n = (fn[m]).sum(axis=0)           # area-weighted (fn is 2 * area * unit)
            out[t, c] = n / max(np.linalg.norm(n), 1e-30)
    return out


# --------------------------------------------------------------------------- #
# Hygiene (the fails-before test; issue #1160)
# --------------------------------------------------------------------------- #

def _tri_overlap_area_2d(a: np.ndarray, b: np.ndarray) -> float:
    """Overlap area of two 2D triangles (Sutherland-Hodgman clip of a by b)."""
    def ccw(t):
        cz = (t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) - (t[1][1] - t[0][1]) * (t[2][0] - t[0][0])
        return t if cz > 0 else t[[0, 2, 1]]
    a, b = ccw(a), ccw(b)
    poly = [p for p in a]
    for i in range(3):
        p, q = b[i], b[(i + 1) % 3]
        edge = q - p
        new = []
        for j in range(len(poly)):
            cur, nxt = poly[j], poly[(j + 1) % len(poly)]
            sc = edge[0] * (cur[1] - p[1]) - edge[1] * (cur[0] - p[0])
            sn = edge[0] * (nxt[1] - p[1]) - edge[1] * (nxt[0] - p[0])
            if sc >= 0:
                new.append(cur)
            if (sc >= 0) != (sn >= 0):
                tt = sc / (sc - sn)
                new.append(cur + tt * (nxt - cur))
        poly = new
        if not poly:
            return 0.0
    P = np.asarray(poly)
    x, y = P[:, 0], P[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def coincident_face_pairs(meshes: list[Mesh], plane_tol: float = 1e-5, area_tol: float = 1e-8) -> list:
    """Pairs of triangles (any meshes) that lie in the same plane (either orientation) and
    overlap in area. Edge-sharing neighbours of a flat face overlap in zero area and pass."""
    items = []
    for mi, m in enumerate(meshes):
        fn = np.cross(m.tris[:, 1] - m.tris[:, 0], m.tris[:, 2] - m.tris[:, 0])
        ln = np.linalg.norm(fn, axis=1)
        for t in range(len(m.tris)):
            if ln[t] < 1e-14:
                continue
            n = fn[t] / ln[t]
            if n[np.argmax(np.abs(n))] < 0:       # canonical sign: both orientations share a bucket
                n = -n
            d = float(n @ m.tris[t, 0])
            items.append((mi, t, tuple(np.round(n, 4)), d))
    buckets: dict = {}
    for it in items:
        buckets.setdefault(it[2], []).append(it)
    pairs = []
    for key, lst in buckets.items():
        if len(lst) < 2:
            continue
        n = np.array(key)
        n /= np.linalg.norm(n)
        # in-plane basis
        u = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        lst = sorted(lst, key=lambda it: it[3])
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                if lst[j][3] - lst[i][3] > plane_tol:
                    break
                (mi, ti, _, _), (mj, tj, _, _) = lst[i], lst[j]
                A = meshes[mi].tris[ti]
                B = meshes[mj].tris[tj]
                a2 = np.stack([A @ u, A @ v], axis=1)
                b2 = np.stack([B @ u, B @ v], axis=1)
                if _tri_overlap_area_2d(a2, b2) > area_tol:
                    pairs.append((meshes[mi].name, ti, meshes[mj].name, tj))
    return pairs


def _point_tri_dist(p: np.ndarray, tris: np.ndarray) -> float:
    """Min distance from point p to a set of triangles."""
    return min(float(np.linalg.norm(p - _closest_on_tri(p, t[0], t[1], t[2]))) for t in tris)


def _closest_on_tri(p, a, b, c):
    """Closest point on triangle abc to p (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = ab @ ap, ac @ ap
    if d1 <= 0 and d2 <= 0:
        return a
    bp = p - b
    d3, d4 = ab @ bp, ac @ bp
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return a + ab * (d1 / (d1 - d3))
    cp = p - c
    d5, d6 = ab @ cp, ac @ cp
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return a + ac * (d2 / (d2 - d6))
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return b + (c - b) * w
    denom = 1.0 / (va + vb + vc)
    return a + ab * (vb * denom) + ac * (vc * denom)


def min_body_gap(meshes: list[Mesh]) -> float:
    """Smallest vertex-to-surface distance between distinct bodies (vertex of A to
    triangles of B and vice versa); ~exact for the convex bodies used here."""
    best = np.inf
    for i in range(len(meshes)):
        for j in range(len(meshes)):
            if i == j:
                continue
            A, B = meshes[i], meshes[j]
            # prune with AABBs
            if (A.tris.min((0, 1)) > B.tris.max((0, 1)) + 0.5).any() or (B.tris.min((0, 1)) > A.tris.max((0, 1)) + 0.5).any():
                continue
            verts = np.unique(np.round(A.tris.reshape(-1, 3), 9), axis=0)
            if A.kind == "floor":
                continue
            for p in verts:
                best = min(best, _point_tri_dist(p, B.tris))
    return float(best)


def project(pt, w: int = RES[0], h: int = RES[1]) -> tuple:
    """Pinhole projection of a Blender-space point with CAMERA -> (x_px, y_px), y down. Sensor fit horizontal."""
    eye, tgt = np.array(CAMERA["loc"]), np.array(CAMERA["target"])
    f = (tgt - eye) / np.linalg.norm(tgt - eye)
    rt = np.cross(f, [0.0, 0.0, 1.0]); rt /= np.linalg.norm(rt)
    up = np.cross(rt, f)
    d = np.asarray(pt, dtype=float) - eye
    x, y, z = d @ rt, d @ up, d @ f
    focal_px = CAMERA["lens"] / CAMERA["sensor"] * w
    return (w / 2 + focal_px * x / z, h / 2 - focal_px * y / z)


def rois(w: int = RES[0], h: int = RES[1]) -> dict:
    """Pixel rects (x0, y0, x1, y1) inside regions crossed by exactly 1 / 2 / 3 panes (2 / 4 / 6
    glass interfaces), above the horizon at camera height (z = 1.1) so the uncapped reference
    is the uniform white world. ``count_interfaces`` verifies the counts per pixel."""
    ymid = -0.6 + (PANE_T + PANE_GAP) + PANE_T / 2          # middle pane's mid-plane
    def rect(x0, x1, z0=1.35, z1=1.8):
        a, b = project((x0, ymid, z1), w, h), project((x1, ymid, z0), w, h)
        return (math.ceil(a[0]), math.ceil(a[1]), math.floor(b[0]), math.floor(b[1]))
    return {"stack1": rect(-1.30, -1.00), "stack2": rect(-0.80, -0.50), "stack3": rect(-0.30, 0.30)}


def camera_rays(w: int, h: int, xs, ys) -> tuple:
    """Primary rays (origin, unit dirs) through pixel centres (xs, ys arrays), Blender frame."""
    eye, tgt = np.array(CAMERA["loc"]), np.array(CAMERA["target"])
    f = (tgt - eye) / np.linalg.norm(tgt - eye)
    rt = np.cross(f, [0.0, 0.0, 1.0]); rt /= np.linalg.norm(rt)
    up = np.cross(rt, f)
    focal_px = CAMERA["lens"] / CAMERA["sensor"] * w
    x = (np.asarray(xs) + 0.5 - w / 2) / focal_px
    y = -(np.asarray(ys) + 0.5 - h / 2) / focal_px
    d = f[None, :] + x[:, None] * rt[None, :] + y[:, None] * up[None, :]
    return eye, d / np.linalg.norm(d, axis=1, keepdims=True)


def count_crossings(origin, dirs: np.ndarray, meshes: list[Mesh], kinds=("glass",)) -> np.ndarray:
    """Number of triangle crossings (t > 0) per ray over meshes of the given kinds
    (Moller-Trumbore; a closed body crossed through gives 2)."""
    n = np.zeros(len(dirs), dtype=int)
    for m in meshes:
        if m.kind not in kinds:
            continue
        for v0, v1, v2 in m.tris:
            e1, e2 = v1 - v0, v2 - v0
            pv = np.cross(dirs, e2)
            det = pv @ e1
            ok = np.abs(det) > 1e-12
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            tv = origin - v0
            u = (pv @ tv) * inv
            qv = np.cross(tv, e1)
            vv = (dirs @ qv) * inv
            t = (qv @ e2) * inv
            n += (ok & (u >= 0) & (vv >= 0) & (u + vv <= 1) & (t > 1e-9)).astype(int)
    return n


def hygiene(meshes: list[Mesh]) -> dict:
    return {
        "signed_volume": {m.name: signed_volume(m.tris) for m in meshes if m.kind == "glass"},
        "coincident_pairs": coincident_face_pairs(meshes),
        "min_gap": min_body_gap(meshes),
    }


# --------------------------------------------------------------------------- #
# Negative control: the pkg324 sp07 tumbler as authored (issue #1160)
# --------------------------------------------------------------------------- #

def legacy_pkg324_meshes() -> list[Mesh]:
    """Plinth (z 0..0.5) + the pkg324 build_sp07 tumbler profile: base disk at z0 = 0.5
    (coplanar with the plinth top) and a self-overlapping rim ring (duplicated profile
    point). Revolved exactly as authored (closed polyline, no axis-to-axis assumption)."""
    z0, h, ro, wall, base = 0.5, 1.3, 0.5, 0.1, 0.3
    profile = [(0.0, z0), (0.36, z0), (ro - 0.02, z0 + h), (ro, z0 + h), (ro, z0 + h),
               (ro - wall, z0 + h), (ro - wall - 0.02, z0 + h), (0.28, z0 + base), (0.0, z0 + base)]
    segs = 64
    P = [[(r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs), z) for k in range(segs)]
         for r, z in profile]
    n = len(profile)
    tris = []
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        for k in range(segs):
            k2 = (k + 1) % segs
            quad = [np.array(a[k]), np.array(a[k2]), np.array(b[k2]), np.array(b[k])]
            uniq = []
            for q in quad:
                if not any(np.allclose(q, u) for u in uniq):
                    uniq.append(q)
            if len(uniq) == 4:
                tris += [[uniq[0], uniq[1], uniq[2]], [uniq[0], uniq[2], uniq[3]]]
            elif len(uniq) == 3:
                tris.append(uniq)
    tris = np.asarray(tris, dtype=np.float64)
    # Blender's recalc_face_normals on the self-overlapping profile left it wound inward
    # (signed volume -0.380, #1160); reproduce that winding.
    if signed_volume(tris) > 0:
        tris = tris[:, [0, 2, 1]]
    tumbler = Mesh("LegacyTumbler", tris, "glass", True)
    plinth = box("LegacyPlinth", (0.0, 0.0, 0.25), (1.8, 1.8, 0.5))
    plinth.kind = "opaque"
    return [plinth, tumbler]
