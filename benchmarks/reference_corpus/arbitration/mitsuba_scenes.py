"""pkg307 Phase 2 -- Mitsuba 3 spectral scenes for the three arbitration scenes.

``PARAMS`` is the single source of truth for scene geometry, materials, lamps and cameras: it is imported by
``build_arbitration.py`` (Blender: Cycles + Astroray renders) and consumed here (Mitsuba) so the engines render the
same scene by construction, not by hand-copied numbers. Importing this module needs only the standard library;
``mitsuba`` is imported inside the functions, so run it with the Mitsuba venv:

    C:/Users/hgcom/tools/venv-mitsuba/Scripts/python.exe mitsuba_scenes.py --scene arb_prism_sun --spp 256 \\
        --seed 278 --out <stem>             # writes <stem>.f32 (raw float32 linear HxWx3, row 0 = top), prints PKG307_INFO

Why a Python BSDF: Mitsuba 3.9.1's ``dielectric`` has a constant IOR (the named materials are single numbers; a
spectrum for ``int_ior`` is rejected: 'expected string, got spectrum'), so dispersion needs ``DispersiveDielectric``
below. It is the documented tinted-dielectric Python plugin (Mitsuba docs, "Custom Python plugin", BSD-3) with the
IOR taken from a Sellmeier fit at the path's hero wavelength and the other three wavelengths terminated, as pbrt-v4
does at a dispersive interface (Pharr/Jakob/Humphreys, PBR 4e section 4.5.4, ``TerminateSecondary``): the throughput
of lane 0 is multiplied by 4 (once per path, at hits from outside the convex prism) and lanes 1-3 are zeroed, which
keeps the film estimator (a mean over the four wavelengths) unbiased because each lane is marginally distributed with
the same pdf. A BSDF cannot see the path throughput, so the x4 is not idempotent across a diffuse bounce between two
prism hits: a few-percent effect on the caustic at floor albedo 0.15, bounded by the constant-IOR validation.

Lamp scale: every engine's lamp units differ (Blender W vs radiance), and transport is linear in emitter power, so
``calibration.json`` holds one scalar per scene that matches Mitsuba to its anchor ROI (see ``--calibrate``).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CALIBRATION = HERE / "calibration.json"
RES = (320, 180)
SENSOR_MM = 36.0  # Blender sensor width (sensor fit AUTO, landscape: applies to x)

# --- shared scene definition (Blender + Mitsuba) -----------------------------------------------------------------
# Units: metres, +Z up. Colours are linear sRGB. Camera: Blender lens in mm, look-at.
SF11 = {"B": (1.73759695, 0.313747346, 1.89878101), "C": (0.013188707, 0.0623068142, 155.23629)}  # = include/astroray/optical_presets.h flint_sf11
PARAMS = {
    "arb_prism_sun": {
        "doc": "SF11 prism under a 4 degree sun, diffuse floor: dispersive floor caustic (Cycles has no dispersion).",
        "floor_albedo": (0.15, 0.15, 0.15),
        "prism": {"loc": (-0.4, 0.3, 0.0), "side": 0.8, "length": 1.3, "rot_z_deg": -33.0, "glass": SF11, "ior_d": 1.7847},
        "sun": {"elev_deg": 22.0, "az_deg": -12.0, "angle_deg": 4.0, "strength": 9.0, "color": (1.0, 1.0, 1.0)},
        "camera": {"loc": (3.4, -4.6, 3.0), "target": (1.0, 0.2, 0.2), "lens": 32.0},
        "max_depth": 16,
        "anchor": {"roi": "floor_far", "leg": "cycles"},
    },
    "arb_chromatic_medium": {
        "doc": "Chromatic homogeneous medium cube above a diffuse floor, lit by a rectangle lamp.",
        "floor_albedo": (0.5, 0.5, 0.5),
        "cube": {"center": (0.0, 0.0, 0.8), "size": 1.4, "density": 1.5, "color": (0.95, 0.45, 0.12), "anisotropy": 0.0},
        "lamp": {"loc": (-2.5, -1.5, 3.0), "target": (0.0, 0.0, 0.8), "size": 1.5, "power_w": 200.0, "color": (1.0, 1.0, 1.0)},
        "camera": {"loc": (0.0, -6.0, 1.8), "target": (0.0, 0.0, 0.7), "lens": 35.0},
        "max_depth": 12,
        "anchor": {"roi": "floor_direct", "leg": "cycles"},
    },
    "arb_narrowband_wall": {
        "doc": "Narrow-band (sodium vapour) rectangle lamp on a coloured diffuse wall and a grey floor.",
        "floor_albedo": (0.5, 0.5, 0.5),
        "wall_albedo": (0.85, 0.45, 0.10),
        "wall_y": 2.0,
        "lamp": {"loc": (-1.0, -0.2, 1.8), "target": (0.8, 2.0, 0.6), "size": 0.5, "power_w": 18.0,
                 "profile": "sodium_vapor", "color": (1.0, 1.0, 1.0)},
        "camera": {"loc": (3.4, -1.2, 1.3), "target": (-0.3, 1.6, 0.9), "lens": 26.0},
        "max_depth": 8,
        "anchor": {"roi": "wall_centre", "leg": "cpu"},
    },
}
SCENES = tuple(PARAMS)


def prism_triangles(p: dict):
    """Triangle list (outward windings) of the equilateral prism standing on z = loc.z -- the vertices of
    benchmarks/blender_showcase/showcase.py::_prism (rr = side / sqrt 3, corners at 90/210/330 degrees)."""
    rr = p["side"] / math.sqrt(3.0)
    rot = math.radians(p["rot_z_deg"])
    cs, sn = math.cos(rot), math.sin(rot)
    tri = [(rr * math.cos(math.radians(a)), rr * math.sin(math.radians(a))) for a in (90, 210, 330)]

    def v(x, y, z):
        return (p["loc"][0] + x * cs - y * sn, p["loc"][1] + x * sn + y * cs, p["loc"][2] + z)

    bot = [v(x, y, 0.0) for x, y in tri]
    top = [v(x, y, p["length"]) for x, y in tri]
    tris = [(bot[0], bot[2], bot[1]), (top[0], top[1], top[2])]
    for i in range(3):
        j = (i + 1) % 3
        tris += [(bot[i], bot[j], top[j]), (bot[i], top[j], top[i])]
    cen = [sum(c[k] for c in bot + top) / 6.0 for k in range(3)]
    out = []
    for a, b, c in tris:  # flip any triangle whose normal points inward
        n = [(b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
             (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
             (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])]
        mid = [(a[k] + b[k] + c[k]) / 3.0 - cen[k] for k in range(3)]
        out.append((a, b, c) if sum(n[k] * mid[k] for k in range(3)) > 0 else (a, c, b))
    return out


def write_prism_obj(p: dict, path: Path) -> Path:
    lines = []
    for i, (a, b, c) in enumerate(prism_triangles(p)):
        lines += [f"v {a[0]} {a[1]} {a[2]}", f"v {b[0]} {b[1]} {b[2]}", f"v {c[0]} {c[1]} {c[2]}"]
    lines += [f"f {3 * i + 1} {3 * i + 2} {3 * i + 3}" for i in range(len(prism_triangles(p)))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def sun_direction(s: dict):
    """Unit vector the sunlight travels along (showcase.build_glass convention)."""
    e, a = math.radians(s["elev_deg"]), math.radians(s["az_deg"])
    return (math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), -math.sin(e))


def sodium_spd(step_nm: int = 5, lo: int = 360, hi: int = 830):
    """The Astroray ``sodium_vapor`` emission profile as (wavelength nm, value) pairs, read from its own database.
    Astroray stores it on a 5 nm grid and interpolates linearly (``SpectralProfile::emission``); Mitsuba's ``spectrum`` is also
    linear between points, so the two engines integrate the identical lamp curve (the broadened-line shape is Astroray's own).
    Needs the astroray module (ASTRORAY_PYD_DIR); cached in ``spd_<profile>.json`` so the Mitsuba venv never imports it."""
    cache = HERE / "spd_sodium_vapor.json"
    if cache.is_file():
        c = json.loads(cache.read_text())
        if c["profile"] == "sodium_vapor" and c["grid"] == [lo, hi, step_nm]:
            return [tuple(x) for x in c["values"]]
    import astroray  # only to build the cache
    vals = [(float(w), float(astroray.spectral_profile_reflectance("sodium_vapor", float(w)))) for w in range(lo, hi + 1, step_nm)]
    cache.write_text(json.dumps({"profile": "sodium_vapor", "grid": [lo, hi, step_nm], "values": vals}))
    return vals


def calibration() -> dict:
    return json.loads(CALIBRATION.read_text()) if CALIBRATION.is_file() else {}


def build_dict(sid: str, mi, work: Path, res=RES, spp: int = 64, lamp_scale: float | None = None,
               prism_bsdf: str = "sellmeier") -> dict:
    """The ``mi.load_dict`` dictionary of one arbitration scene."""
    p = PARAMS[sid]
    cam = p["camera"]
    fov = math.degrees(2.0 * math.atan(SENSOR_MM / (2.0 * cam["lens"])))
    T = mi.ScalarTransform4f
    scale = lamp_scale if lamp_scale is not None else calibration().get(sid, {}).get("lamp_scale", 1.0)
    d = {
        "type": "scene",
        "integrator": {"type": "volpath", "max_depth": p["max_depth"], "rr_depth": 5},
        "sensor": {
            "type": "perspective", "fov": fov, "fov_axis": "x",
            "to_world": T().look_at(origin=list(cam["loc"]), target=list(cam["target"]), up=[0, 0, 1]),
            "sampler": {"type": "independent", "sample_count": spp},
            "film": {"type": "hdrfilm", "width": res[0], "height": res[1], "pixel_format": "rgb",
                     "rfilter": {"type": "box"}},
        },
        "floor": {"type": "rectangle", "to_world": T().translate([0, 0, 0]).scale([20.0, 20.0, 1.0]),
                  "bsdf": {"type": "diffuse", "reflectance": {"type": "rgb", "value": list(p["floor_albedo"])}}},
    }
    if sid == "arb_prism_sun":
        pr, s = p["prism"], p["sun"]
        obj = write_prism_obj(pr, work / "prism.obj")
        d["prism"] = {"type": "obj", "filename": str(obj), "face_normals": True,
                      "bsdf": {"type": "dispersive_dielectric", "b": ",".join(map(str, pr["glass"]["B"])),
                                 "c": ",".join(map(str, pr["glass"]["C"]))}}
        if prism_bsdf == "const_plugin":  # validation pair: the plugin at constant IOR vs the stock dielectric
            d["prism"]["bsdf"]["ior"] = str(pr["ior_d"])
        elif prism_bsdf == "builtin":
            d["prism"]["bsdf"] = {"type": "dielectric", "int_ior": pr["ior_d"]}
        # Sun = a far sphere of angular half-angle angle/2 (the 4 degree Blender angle is a full angle).
        dist, half = 100.0, math.radians(s["angle_deg"] / 2.0)
        dvec = sun_direction(s)
        pos = [-dist * dvec[i] for i in range(3)]
        e_norm = math.pi * math.sin(half) ** 2  # normal irradiance of a uniform disc of radiance 1 and angular half-width ``half``
        d["sun"] = {"type": "sphere", "center": pos, "radius": dist * math.sin(half),
                    "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [c * s["strength"] * scale / e_norm for c in s["color"]]}}}
    elif sid == "arb_chromatic_medium":
        c, lp = p["cube"], p["lamp"]
        # Cycles Principled Volume with Absorption Color black: extinction = density (grey) and the Color is the scattering
        # albedo (sigma_s = density x colour, sigma_a = density x (1 - colour)); Mitsuba: unit sigma_t scaled by density.
        d["medium"] = {"type": "cube", "to_world": T().translate(list(c["center"])).scale([c["size"] / 2.0] * 3),
                       "bsdf": {"type": "null"},
                       "interior": {"type": "homogeneous", "albedo": {"type": "rgb", "value": list(c["color"])},
                                    "sigma_t": {"type": "uniform", "value": 1.0}, "scale": c["density"],
                                    "phase": {"type": "hg", "g": c["anisotropy"]}}}
        d["lamp"] = _rect_lamp(lp, T, {"type": "rgb", "value": [k * scale for k in lp["color"]]})
    else:
        lp = p["lamp"]
        d["wall"] = {"type": "rectangle", "to_world": T().translate([0, p["wall_y"], 2.0]).rotate([1, 0, 0], 90.0).scale([10.0, 3.0, 1.0]),
                     "bsdf": {"type": "diffuse", "reflectance": {"type": "rgb", "value": list(p["wall_albedo"])}}}
        d["lamp"] = _rect_lamp(lp, T, {"type": "spectrum", "value": [(w, v * scale) for w, v in sodium_spd()]})
    return d


def _rect_lamp(lp: dict, T, radiance: dict) -> dict:
    """Blender square area light (size = edge length) emitting down its local -Z toward ``target``; Cycles/Astroray area
    lamps are one-sided Lambertian, as is Mitsuba's ``area`` on a rectangle (emits along +Z, which look_at points at the target)."""
    return {"type": "rectangle",
            "to_world": T().look_at(origin=list(lp["loc"]), target=list(lp["target"]), up=[0, 0, 1]).scale([lp["size"] / 2.0] * 2 + [1.0]),
            "emitter": {"type": "area", "radiance": radiance}}


def register_dispersive_dielectric(mi, dr):
    """``dispersive_dielectric`` BSDF: smooth dielectric (the Mitsuba docs' tinted-dielectric plugin structure) whose IOR
    is the Sellmeier index at the path's hero wavelength; wavelengths 1-3 are terminated and lane 0 carries weight x4."""

    class DispersiveDielectric(mi.BSDF):
        def __init__(self, props):
            mi.BSDF.__init__(self, props)
            self.b = [float(x) for x in props["b"].split(",")]  # Mitsuba properties carry no lists: comma-separated
            self.c = [float(x) for x in props["c"].split(",")]
            self.const_ior = float(props["ior"]) if props.has_property("ior") else 0.0  # validation: constant IOR, same collapse
            refl = mi.BSDFFlags.DeltaReflection | mi.BSDFFlags.FrontSide | mi.BSDFFlags.BackSide
            trans = mi.BSDFFlags.DeltaTransmission | mi.BSDFFlags.FrontSide | mi.BSDFFlags.BackSide
            self.m_components = [refl, trans]
            self.m_flags = refl | trans

        def eta(self, lam_nm):
            if self.const_ior > 0.0:
                return self.const_ior + 0.0 * lam_nm
            l2 = dr.square(lam_nm * 1e-3)  # micrometres^2
            n2 = 1.0 + sum(b * l2 / (l2 - c) for b, c in zip(self.b, self.c))  # Sellmeier
            return dr.sqrt(n2)

        def sample(self, ctx, si, sample1, sample2, active):
            eta = self.eta(si.wavelengths[0])
            cos_i = mi.Frame3f.cos_theta(si.wi)
            r_i, cos_t, eta_it, eta_ti = mi.fresnel(cos_i, eta)
            t_i = dr.maximum(1.0 - r_i, 0.0)
            sel_r = (sample1 <= r_i) & active
            bs = mi.BSDFSample3f()
            bs.pdf = dr.select(sel_r, r_i, t_i)
            bs.sampled_component = dr.select(sel_r, mi.UInt32(0), mi.UInt32(1))
            bs.sampled_type = dr.select(sel_r, mi.UInt32(+mi.BSDFFlags.DeltaReflection),
                                        mi.UInt32(+mi.BSDFFlags.DeltaTransmission))
            bs.wo = dr.select(sel_r, mi.reflect(si.wi), mi.refract(si.wi, cos_t, eta_ti))
            bs.eta = dr.select(sel_r, 1.0, eta_it)
            w = dr.select(sel_r, 1.0, dr.square(eta_ti))  # radiance scaling across the interface, as dielectric.cpp
            value = dr.zeros(mi.UnpolarizedSpectrum)
            # Hero carries the whole path. The x4 must be applied once per path, and a BSDF cannot see the throughput, so it is
            # applied at hits from OUTSIDE (cos_i > 0): a path inside the convex prism is already collapsed. A second outside hit
            # needs a diffuse bounce in between, so that error is O(floor albedo x prism solid-angle share); the scene keeps the
            # floor dark and tests the plugin against the stock dielectric at constant IOR (tests/test_pkg307_arbitration.py).
            value[0] = w * dr.select(cos_i > 0, 4.0, 1.0)
            return bs, value

        def eval(self, ctx, si, wo, active):
            return 0.0

        def pdf(self, ctx, si, wo, active):
            return 0.0

        def traverse(self, cb):
            pass

        def to_string(self):
            return f"DispersiveDielectric[B={self.b}, C={self.c}]"

    mi.register_bsdf("dispersive_dielectric", lambda props: DispersiveDielectric(props))


def render_scene(sid: str, spp: int, seed: int, res, work: Path, variant: str = "cuda_ad_spectral",
                 lamp_scale: float | None = None, prism_bsdf: str = "sellmeier"):
    """(HxWx3 TensorXf image, render-only seconds). Wavefronts above ~2^24 lanes are split into spp chunks with
    decorrelated seeds (a 1280x720 x 320 spp wavefront does not fit in GPU memory). No numpy here: the Mitsuba venv
    has none, so the image leaves as raw float32 that the driver reads."""
    import drjit as dr
    import mitsuba as mi
    mi.set_variant(variant)
    register_dispersive_dielectric(mi, dr)
    chunk = max(1, min(spp, (1 << 24) // (res[0] * res[1])))
    scene = mi.load_dict(build_dict(sid, mi, work, res, chunk, lamp_scale, prism_bsdf))
    acc, done, t = None, 0, 0.0
    while done < spp:
        k = min(chunk, spp - done)
        t0 = time.perf_counter()
        img = mi.render(scene, spp=k, seed=seed * 7919 + done)
        arr = img * k
        dr.eval(arr)
        dr.sync_thread()
        t += time.perf_counter() - t0
        acc = arr if acc is None else acc + arr
        done += k
    return acc / spp, t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scene", required=True, choices=SCENES)
    ap.add_argument("--spp", type=int, required=True)
    ap.add_argument("--seed", type=int, default=278)
    ap.add_argument("--out", required=True, help="output stem; writes <stem>.npy")
    ap.add_argument("--res-percent", type=int, default=100)
    ap.add_argument("--variant", default=os.environ.get("ASTRORAY_MITSUBA_VARIANT", "cuda_ad_spectral"),
                    help="Mitsuba variant (scalar_spectral for CPU-only development runs)")
    ap.add_argument("--lamp-scale", type=float, default=None, help="override the calibrated lamp scale (calibration run)")
    ap.add_argument("--prism-bsdf", choices=("sellmeier", "const_plugin", "builtin"), default="sellmeier",
                    help="validation: const_plugin = the dispersive plugin at constant IOR, builtin = stock dielectric")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = (round(RES[0] * a.res_percent / 100), round(RES[1] * a.res_percent / 100))
    try:
        img, secs = render_scene(a.scene, a.spp, a.seed, res, out.parent, a.variant, a.lamp_scale, a.prism_bsdf)
    except Exception as exc:  # noqa: BLE001 - the driver keys on the sentinel
        import traceback
        traceback.print_exc()
        print(f"PKG119B_LEG FAIL {type(exc).__name__}: {exc}")
        return 1
    import array

    import mitsuba as mi
    flat = img.array  # no numpy in this venv: dr arrays export host memory through the buffer protocol (memview)
    buf = array.array("f")
    if hasattr(flat, "memview"):
        buf.frombytes(flat.memview().cast("B"))
    else:  # scalar variants
        buf.extend(float(x) for x in flat)
    assert len(buf) == res[0] * res[1] * 3, (len(buf), res)
    out.with_suffix(".f32").write_bytes(buf.tobytes())
    print("PKG307_INFO " + json.dumps({"render_s": secs, "engine": "mitsuba", "device": a.variant, "res": list(res),
                                       "samples": a.spp, "mitsuba": mi.__version__}), flush=True)
    print("PKG119B_LEG PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
