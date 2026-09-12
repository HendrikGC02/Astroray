"""pkg256 — Sky-texture (`ShaderNodeTexSky`) bake to an equirectangular HDRI.

Standalone (no bpy calls; image I/O is a self-contained Radiance-RGBE writer)
so the bake is unit-testable without Blender. `setup_world` in
`blender_addon/__init__.py` calls `bake_to_equirect(node)`, writes the result
with `write_hdr`, and loads it through the existing
`renderer.load_environment_map` HDRI path (pkg63) — no engine change.

Sky model: **Preetham/Perez** analytic daylight distribution (Preetham,
Shirley, Smits, "A Practical Analytic Model for Daylight", SIGGRAPH 1999;
Perez et al. 1993). Constants verified verbatim against the MIT-licensed
appleseed reference `preethamenvironmentedf.cpp`. Blender's own
Nishita/Hosek/Preetham implementations (intern/cycles/kernel/svm/sky*.h) are
GPL and were NOT used. Full derivation, licence records, and the equirect
orientation proof: `.astroray_plan/docs/pkg256-sky-model-research.md`.

All four Blender `sky_type` values are APPROXIMATED with this one model (spec
pkg256 Key design decision 2). `sun_disc`, `sun_size`, `sun_intensity`,
`altitude`, `air_density`, `ozone_density`, `ground_albedo`, and the `Vector`
input are NOT honoured — the caller names them verbatim in a runtime
degradation warning.

`air_density` is deliberately DROPPED, not folded into turbidity: Blender's
Nishita `air_density` scales Rayleigh scattering (more air ⇒ *bluer*/more
saturated), whereas Perez `turbidity` is a haziness axis (more turbidity ⇒
*whiter*/desaturated). Mapping air_density onto turbidity therefore inverts
its perceptual direction, so it is left unconsumed and warned instead (PR #793
cycles-parity review item 1, 2026-09-10; matches spec Non-goals). Only
`aerosol_density` (haze ⇒ turbidity, same direction) is still folded in.
"""

import math

import numpy as np

# Sockets/props the Preetham bake does NOT consume — named verbatim by the
# addon's degradation warning (pkg200 rule: never silently dropped).
# #799: sun_disc / sun_size / sun_intensity are now HONOURED via a dedicated
# distant sun light (see sun_disc_params + setup_world), so they left this list.
DROPPED_SOCKETS = (
    "sun_direction",  # sun position taken from sun_elevation/sun_rotation instead
    "altitude",
    "air_density",    # Rayleigh axis; folding onto turbidity inverts its sense
    "ozone_density",
    "ground_albedo",
    "sun_limb_darkening",  # the distant-sun disc is uniform (#799 non-goal)
    "Vector",
)

# Photopic luminous efficacy K_m (lm/W, CIE 1924 V(λ) max at 555 nm). Preetham
# zenith luminance Yz is ABSOLUTE photometric luminance (cd/m²); Y[cd/m²] =
# K_m · ∫L(λ)ȳ(λ)dλ, so Y/K_m is an absolute radiance floor. See
# .astroray_plan/docs/799-sky-absolute-exposure-sun-disc-research.md §2.
PHOTOPIC_LUMINOUS_EFFICACY = 683.0

# Photometric-luminance (cd/m²) → radiance unit bridge (#799). Decomposed:
#
#   LUM_TO_RADIANCE = 1/1766 = (1/683) · (1/2.586)
#     = [photopic K_m — PHYSICS] · [Cycles-Nishita exposure convention — UNITS]
#
# The 1/683 is physics (peak luminous efficacy). The residual 1/2.586
# (equivalently 1/14.7 relative to the ~120 lm/W broadband daylight efficacy)
# is Cycles' Nishita absolute-exposure normalisation, measured once against the
# corpus scene (world_sky_sky: MULTIPLE_SCATTERING, turbidity 2.6, elevation
# 28°). It is a legitimate UNITS CHOICE, not a physics fit: Cycles' Nishita
# absolute scale lives in GPL code (svm/sky.h, not read) and is undocumented as
# an SI value.
#
# This residual is model- and condition-dependent, so NO single constant is
# universal. Measured drift (benchmarks/reference_corpus/sky_ab_bands.py,
# PKG256_AB_PT, Blender 5.2 Cycles): calibrated at Nishita/28° → ratio 1.005,
# but Cycles' legacy PREETHAM sky_type lands at ratio 7.7–15 across
# (turbidity, elevation). Absolute cross-model/condition parity therefore needs
# an engine-side spectral sky lookup (issue #799 Phase-2 "real fix"), which is a
# separate architecture pass. Per the owner's physics-first rule (2026-09-08),
# the bake's absolute radiance Y/K is the physical quantity and the Cycles A/B
# is a cross-check band, not the gate, away from the calibrated Nishita point.
# Measured residual = 683/1766 = 1/2.586 (units choice, §2). Written this way so
# LUM_TO_RADIANCE is EXACTLY 1/1766 (corpus Nishita gate stays byte-identical).
CYCLES_NISHITA_EXPOSURE = PHOTOPIC_LUMINOUS_EFFICACY / 1766.0
LUM_TO_RADIANCE = CYCLES_NISHITA_EXPOSURE / PHOTOPIC_LUMINOUS_EFFICACY  # == 1/1766

# CIE xyY -> linear sRGB (Rec.709 / D65).
_XYZ_TO_RGB = np.array(
    [[3.2406, -1.5372, -0.4986],
     [-0.9689, 1.8758, 0.0415],
     [0.0557, -0.2040, 1.0570]],
    dtype=np.float64,
)


def _sun_direction(elevation, rotation):
    """Blender Z-up world-frame sun direction from sun_elevation (rad, above
    horizon) and sun_rotation (rad, azimuth about +Z)."""
    ce, se = math.cos(elevation), math.sin(elevation)
    return np.array([ce * math.cos(rotation), ce * math.sin(rotation), se],
                    dtype=np.float64)


def _effective_turbidity(sky_type, turbidity, aerosol_density):
    """Map a Blender sky_type + its native params to a Perez turbidity.

    NISHITA family (SINGLE/MULTIPLE_SCATTERING) has no turbidity input, so we
    derive an effective one from `aerosol_density` only (haze ⇒ turbidity, same
    perceptual direction — approximation, see research note §3).
    `air_density` (Rayleigh) is intentionally NOT folded in: it is a bluer/more-
    saturated axis and mapping it onto turbidity (a whiter/hazier axis) would
    invert its direction, so it is DROPPED + warned instead (PR #793 review
    item 1). PREETHAM/HOSEK_WILKIE use the native `turbidity` prop.
    """
    if sky_type in ("SINGLE_SCATTERING", "MULTIPLE_SCATTERING", "NISHITA"):
        t = 2.0 + 2.0 * float(aerosol_density)
    else:  # PREETHAM, HOSEK_WILKIE
        t = float(turbidity)
    return float(min(max(t, 1.7), 10.0))


def _perez_coeffs(turbidity):
    """Turbidity-linear Perez A..E for luminance Y and chromaticities x, y.
    Verified vs appleseed preethamenvironmentedf.cpp (MIT)."""
    t = turbidity
    y = np.array([0.1787 * t - 1.4630, -0.3554 * t + 0.4275,
                  -0.0227 * t + 5.3251, 0.1206 * t - 2.5771,
                  -0.0670 * t + 0.3703])
    x = np.array([-0.0193 * t - 0.2592, -0.0665 * t + 0.0008,
                  -0.0004 * t + 0.2125, -0.0641 * t - 0.8989,
                  -0.0033 * t + 0.0452])
    yy = np.array([-0.0167 * t - 0.2608, -0.0950 * t + 0.0092,
                   -0.0079 * t + 0.2102, -0.0441 * t - 1.6537,
                   -0.0109 * t + 0.0529])
    return y, x, yy


def _perez(coeffs, cos_theta, gamma, cos_gamma):
    """Perez F = (1 + A e^{B/cosθ})(1 + C e^{Dγ} + E cos²γ)."""
    a, b, c, d, e = coeffs
    return ((1.0 + a * np.exp(b / cos_theta))
            * (1.0 + c * np.exp(d * gamma) + e * cos_gamma * cos_gamma))


def _zenith_xyY(turbidity, sun_theta):
    """Absolute zenith luminance (cd/m²) and chromaticities (Preetham)."""
    t = turbidity
    chi = (4.0 / 9.0 - t / 120.0) * (math.pi - 2.0 * sun_theta)
    yz = 1000.0 * ((4.0453 * t - 4.9710) * math.tan(chi)
                   - 0.2155 * t + 2.4192)
    ts = sun_theta
    a = (0.00166 * t - 0.02903) * t + 0.11693
    b = (-0.00375 * t + 0.06377) * t - 0.21196
    c = (0.00209 * t - 0.03202) * t + 0.06052
    dd = 0.00394 * t + 0.25886
    xz = ((a * ts + b) * ts + c) * ts + dd
    e = (0.00275 * t - 0.04214) * t + 0.15346
    f = (-0.00610 * t + 0.08970) * t - 0.26756
    g = (0.00317 * t - 0.04153) * t + 0.06670
    h = 0.00516 * t + 0.26688
    yzc = ((e * ts + f) * ts + g) * ts + h
    return max(yz, 0.0), xz, yzc


def bake_params(sky_type, sun_elevation, sun_rotation, turbidity=2.0,
                aerosol_density=1.0, width=1024, height=512):
    """Bake a Preetham/Perez equirect sky to a (height, width, 3) float32 RGB
    array (linear, radiance-scaled). Deterministic. Row 0 = zenith (+Z),
    row H-1 = nadir; column c ↦ φ=((c+0.5)/W-0.5)·2π (see research note §4)."""
    t = _effective_turbidity(sky_type, turbidity, aerosol_density)
    sun = _sun_direction(sun_elevation, sun_rotation)
    sun_theta = math.acos(min(max(float(sun[2]), -1.0), 1.0))  # from +Z

    # Per-pixel view directions (Blender Z-up), matching EnvironmentMap.
    r = np.arange(height, dtype=np.float64)
    c = np.arange(width, dtype=np.float64)
    theta = (r + 0.5) / height * math.pi            # polar from +Z, (H,)
    phi = ((c + 0.5) / width - 0.5) * 2.0 * math.pi  # (W,)
    sin_t = np.sin(theta)[:, None]                   # (H,1)
    cos_t = np.cos(theta)[:, None]                   # (H,1) = dir.z
    dir_x = sin_t * np.cos(phi)[None, :]
    dir_y = -sin_t * np.sin(phi)[None, :]
    dir_z = np.broadcast_to(cos_t, (height, width))

    cos_gamma = np.clip(dir_x * sun[0] + dir_y * sun[1] + dir_z * sun[2],
                        -1.0, 1.0)
    gamma = np.arccos(cos_gamma)
    # View zenith cosine clamped to the upper hemisphere (keeps horizon
    # finite; lower hemisphere reuses the horizon value — #787 keeps the
    # ground dark in-render regardless).
    cos_view = np.clip(dir_z, 1e-3, 1.0)

    cy, cx, cyy = _perez_coeffs(t)
    yz, xz, yzc = _zenith_xyY(t, sun_theta)
    cos_st = math.cos(sun_theta)

    def channel(coeffs, zenith_val):
        f0 = _perez(coeffs, 1.0, sun_theta, cos_st)
        f = _perez(coeffs, cos_view, gamma, cos_gamma)
        return zenith_val * f / f0

    big_y = channel(cy, yz)       # luminance cd/m², (H,W)
    chroma_x = channel(cx, xz)
    chroma_y = np.clip(channel(cyy, yzc), 1e-4, None)

    # xyY -> XYZ.
    big_x = (chroma_x / chroma_y) * big_y
    big_z = ((1.0 - chroma_x - chroma_y) / chroma_y) * big_y
    xyz = np.stack([big_x, big_y, big_z], axis=-1)  # (H,W,3)
    rgb = xyz @ _XYZ_TO_RGB.T
    rgb = np.clip(rgb, 0.0, None) * LUM_TO_RADIANCE
    return np.ascontiguousarray(rgb, dtype=np.float32)


# --- #799: sun disc (dedicated distant sun light) ---------------------------
# Extra-atmospheric solar-disc luminance (cd/m²). Textbook photometry (IES
# Lighting Handbook); surface value for a high clear sun is ~1.6-2.0e9 cd/m².
SOLAR_DISC_LUMINANCE = 1.6e9
# Blender ShaderNodeTexSky.sun_size default = 0.545° = 0.009512 rad (full angle).
DEFAULT_SUN_SIZE = 0.009512


def _optical_depth(turbidity):
    """Broadband direct-beam optical depth, turbidity-scaled (Beer-Lambert
    clear-sky, Bird & Riordan 1986 form). Clear T≈2 → 0.10; hazy T≈6 → 0.28."""
    return 0.10 + 0.045 * (float(turbidity) - 2.0)


def _sky_rgb(turbidity, sun_theta, cos_view, gamma, cos_gamma):
    """Preetham/Perez sky radiance (linear sRGB, LUM_TO_RADIANCE-scaled) for a
    SINGLE view direction — the scalar twin of bake_params' vectorised body
    (same _perez/_zenith_xyY helpers, so no model drift)."""
    cy, cx, cyy = _perez_coeffs(turbidity)
    yz, xz, yzc = _zenith_xyY(turbidity, sun_theta)
    cos_st = math.cos(sun_theta)
    cv = max(float(cos_view), 1e-3)

    def channel(coeffs, zenith_val):
        f0 = _perez(coeffs, 1.0, sun_theta, cos_st)
        f = _perez(coeffs, cv, gamma, cos_gamma)
        return zenith_val * f / f0

    big_y = channel(cy, yz)
    x = channel(cx, xz)
    y = max(channel(cyy, yzc), 1e-4)
    big_x = (x / y) * big_y
    big_z = ((1.0 - x - y) / y) * big_y
    rgb = np.array([big_x, big_y, big_z]) @ _XYZ_TO_RGB.T
    return np.clip(rgb, 0.0, None) * LUM_TO_RADIANCE


def sun_disc_params(sky_type, sun_elevation, sun_rotation, turbidity=2.0,
                    aerosol_density=1.0, sun_size=DEFAULT_SUN_SIZE,
                    sun_intensity=1.0):
    """Physical parameters for a dedicated distant sun light matching the baked
    sky (see .astroray_plan/docs/799-sky-absolute-exposure-sun-disc-research.md
    §3). Returns:
      direction        : travel direction (= -sun), Blender Z-up
      angular_diameter : sun_size (rad) — sets shadow sharpness (exposure-free)
      color            : unit-luminance linear-sRGB disc colour (warm at low sun)
      intensity        : direct-normal irradiance in the SAME bake radiance
                         units as the sky (rides LUM_TO_RADIANCE)
    Beer-Lambert direct beam: L_sun = L0·exp(-τ·m); E_sun = L_sun·Ω·sun_intensity;
    intensity = E_sun·LUM_TO_RADIANCE. Ω = 2π(1-cos(sun_size/2))."""
    t = _effective_turbidity(sky_type, turbidity, aerosol_density)
    sun = _sun_direction(sun_elevation, sun_rotation)
    elev = max(float(sun_elevation), math.radians(0.5))
    air_mass = 1.0 / math.sin(elev)
    tau = _optical_depth(t)
    l_sun = SOLAR_DISC_LUMINANCE * math.exp(-tau * air_mass)      # cd/m²
    omega = 2.0 * math.pi * (1.0 - math.cos(0.5 * float(sun_size)))  # sr
    e_sun = l_sun * omega * float(sun_intensity)                  # illuminance-like
    intensity = e_sun * LUM_TO_RADIANCE                          # bake radiance units
    # Disc colour = our own sky colour toward the sun (γ=0), unit-luminance.
    sun_theta = math.acos(min(max(float(sun[2]), -1.0), 1.0))
    rgb = _sky_rgb(t, sun_theta, float(sun[2]), 0.0, 1.0)
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    color = (rgb / lum) if lum > 1e-8 else np.array([1.0, 1.0, 1.0])
    return {
        "direction": [-float(sun[0]), -float(sun[1]), -float(sun[2])],
        "angular_diameter": float(sun_size),
        "color": [float(c) for c in color],
        "intensity": float(intensity),
    }


def sun_disc_params_from_node(node):
    """sun_disc_params from a `ShaderNodeTexSky` node (or duck-typed stub).
    Returns None when the node's sun disc is disabled."""
    if not bool(getattr(node, "sun_disc", False)):
        return None
    return sun_disc_params(
        getattr(node, "sky_type", "SINGLE_SCATTERING"),
        _node_prop(node, "sun_elevation", 0.26),
        _node_prop(node, "sun_rotation", 0.0),
        turbidity=_node_prop(node, "turbidity", 2.0),
        aerosol_density=_node_prop(node, "aerosol_density", 1.0),
        sun_size=_node_prop(node, "sun_size", DEFAULT_SUN_SIZE),
        sun_intensity=_node_prop(node, "sun_intensity", 1.0),
    )


def _node_prop(node, name, default):
    val = getattr(node, name, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def bake_to_equirect(node, width=1024, height=512):
    """Bake a Blender `ShaderNodeTexSky` node to an equirect RGB float32 array.
    Reads sky_type + sun/atmosphere props off the node (real bpy node or a
    duck-typed stub in tests)."""
    sky_type = getattr(node, "sky_type", "SINGLE_SCATTERING")
    return bake_params(
        sky_type,
        _node_prop(node, "sun_elevation", 0.26),
        _node_prop(node, "sun_rotation", 0.0),
        turbidity=_node_prop(node, "turbidity", 2.0),
        aerosol_density=_node_prop(node, "aerosol_density", 1.0),
        width=width, height=height,
    )


def _to_rgbe(rgb):
    """Vectorised Ward RGBE encode of a (H,W,3) float array -> (H,W,4) uint8.
    Decode: v = (rgbe[:3] + 0.5) * 2^(rgbe[3] - 136)."""
    rgb = np.maximum(np.asarray(rgb, dtype=np.float64), 0.0)
    maxc = rgb.max(axis=2)
    out = np.zeros(rgb.shape[:2] + (4,), dtype=np.uint8)
    mask = maxc >= 1e-32
    if np.any(mask):
        mant, exp = np.frexp(maxc[mask])          # maxc = mant * 2^exp
        scale = mant * 256.0 / maxc[mask]
        px = rgb[mask] * scale[:, None]
        out[mask, :3] = np.clip(px, 0, 255).astype(np.uint8)
        out[mask, 3] = np.clip(exp + 128, 0, 255).astype(np.uint8)
    return out


def write_hdr(path, rgb):
    """Write a (H,W,3) float RGB array as a flat (uncompressed) Radiance .hdr.
    Row 0 is the top of the image (`-Y H +X W`), matching bake_params' zenith
    row and the stb_image loader used by EnvironmentMap::load."""
    rgb = np.asarray(rgb, dtype=np.float32)
    height, width = rgb.shape[0], rgb.shape[1]
    rgbe = _to_rgbe(rgb)
    header = (f"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y {height} +X {width}\n"
              ).encode("ascii")
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(rgbe.tobytes())
    return path
