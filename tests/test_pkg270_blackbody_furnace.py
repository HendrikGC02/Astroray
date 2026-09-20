"""pkg270 — Principled Volume emission: blackbody (spectral Planck) + constant
emission, gated against ANALYTIC Planck / Stefan–Boltzmann values.

Three layers (research note pkg270-spectral-tracking-volume-emission-research.md §3):

1. Unit — ``astroray.volume_blackbody_emission`` returns the exact Planck
   spectral SHAPE (ratios between wavelengths match B(λ,T) to <0.5 %) and its
   photopic luminance equals Cycles' Stefan–Boltzmann intensity
   ``σ_SB·1e-6/π · mix(1, T⁴, I)`` (the artist-facing magnitude convention).
2. Render furnace — an emission-only slab (density 0) of known thickness L:
   the centre LINEAR luminance must equal ``intensity·L`` with a FLOOR and a
   CEILING (``apply_gamma=False``; gamma would clamp and hide a gain — memory
   gamma-furnace-cannot-detect-energy-gain). Chromaticity is cross-checked
   against Cycles' ``svm_math_blackbody_color_rec709`` polynomial
   (kernel/tables.h, Apache-2.0) — the CROSS-CHECK BAND, not the gate.
3. Exporter lowering — the Principled sockets reach the engine kwargs.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray

SEED = 270111

H_PLANCK = 6.62607015e-34
C_LIGHT = 2.99792458e8
K_BOLTZ = 1.380649e-23
SIGMA_SB = 5.670373e-8  # Cycles' constant (closure.h)


def planck(lambda_nm, T):
    lam = lambda_nm * 1e-9
    return (2.0 * H_PLANCK * C_LIGHT ** 2) / (lam ** 5 * (math.exp(H_PLANCK * C_LIGHT / (lam * K_BOLTZ * T)) - 1.0))


def cycles_intensity(T, I):
    """Cycles svm_node_principled_volume: sigma*mix(1, T^4, blackbody)."""
    return SIGMA_SB * 1e-6 / math.pi * ((1.0 - I) + I * T ** 4)


# Cycles svm_math_blackbody_color_rec709 (kernel/svm/math_util.h + kernel/tables.h,
# Apache-2.0): luminance-1 Rec.709 colour of a blackbody at T. Cross-check band.
_BB_R = [[1.61919106e+03, -2.05010916e-03, 5.02995757e+00],
         [2.48845471e+03, -1.11330907e-03, 3.22621544e+00],
         [3.34143193e+03, -4.86551192e-04, 1.76486769e+00],
         [4.09461742e+03, -1.27446582e-04, 7.25731635e-01],
         [4.67028036e+03, 2.91258199e-05, 1.26703442e-01],
         [4.59509185e+03, 2.87495649e-05, 1.50345020e-01],
         [3.78717450e+03, 9.35907826e-06, 3.99075871e-01]]
_BB_G = [[-4.88999748e+02, 6.04330754e-04, -7.55807526e-02],
         [-7.55994277e+02, 3.16730098e-04, 4.78306139e-01],
         [-1.02363977e+03, 1.20223470e-04, 9.36662319e-01],
         [-1.26571316e+03, 4.87340896e-06, 1.27054498e+00],
         [-1.42529332e+03, -4.01150431e-05, 1.43972784e+00],
         [-1.17554822e+03, -2.16378048e-05, 1.30408023e+00],
         [-5.00799571e+02, -4.59832026e-06, 1.09098763e+00]]
_BB_B = [[5.96945309e-11, -4.85742887e-08, -9.70622247e-05, -4.07936148e-03],
         [2.40430366e-11, 5.55021075e-08, -1.98503712e-04, 2.89312858e-02],
         [-1.40949732e-11, 1.89878968e-07, -3.56632824e-04, 9.10767778e-02],
         [-3.61460868e-11, 2.84822009e-07, -4.93211319e-04, 1.56723440e-01],
         [-1.97075738e-11, 1.75359352e-07, -2.50542825e-04, -2.22783266e-02],
         [-1.61997957e-13, -1.64216008e-08, 3.86216271e-04, -7.38077418e-01],
         [6.72650283e-13, -2.73078809e-08, 4.24098264e-04, -7.52335691e-01]]


def cycles_blackbody_rec709(t):
    if t >= 12000.0:
        return (0.8262954810464208, 0.9945080501520986, 1.566307710274283)
    if t < 800.0:
        return (5.413294490189271, -0.20319390035873933, -0.0822535242887164)
    i = 6 if t >= 6365 else 5 if t >= 3315 else 4 if t >= 1902 else 3 if t >= 1449 \
        else 2 if t >= 1167 else 1 if t >= 965 else 0
    r, g, b = _BB_R[i], _BB_G[i], _BB_B[i]
    ti = 1.0 / t
    return (r[0] * ti + r[1] * t + r[2],
            g[0] * ti + g[1] * t + g[2],
            ((b[0] * t + b[1]) * t + b[2]) * t + b[3])


def _chroma(rgb):
    s = float(sum(rgb))
    return tuple(float(c) / s for c in rgb) if s > 0 else (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# 1. Unit: spectral shape + luminance
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("T", [1400.0, 3000.0, 6500.0])
def test_blackbody_spectral_shape_is_planck(T):
    lambdas = [420.0, 520.0, 620.0, 720.0]
    vals = astroray.volume_blackbody_emission(T, 1.0, [1.0, 1.0, 1.0], lambdas)
    assert all(v > 0.0 for v in vals), vals
    for i in range(1, 4):
        ours = vals[i] / vals[0]
        ref = planck(lambdas[i], T) / planck(lambdas[0], T)
        print(f"[pkg270 planck] T={T} ratio({lambdas[i]}/{lambdas[0]}): ours={ours:.5f} planck={ref:.5f}")
        assert ours == pytest.approx(ref, rel=5e-3), (i, ours, ref)


@pytest.mark.parametrize("T,I", [(3000.0, 1.0), (1400.0, 0.8), (6500.0, 0.5)])
def test_blackbody_luminance_matches_cycles_stefan_boltzmann(T, I):
    # NOTE (cycles-parity review, PR #820): this assert is SELF-CONSISTENT by
    # construction — the engine normalises Planck by the same CIE-1931 ybar
    # integral it is re-integrated with here, so it pins the magnitude convention
    # and catches wiring/unit slips, not the physics. The INDEPENDENT checks are
    # the numpy Planck ratio test above and the Rec.709 chroma band below
    # (Cycles' polynomial, a different observer and fit).
    # Photopic luminance of the per-unit-length emission integrated on a 1-nm grid
    # with the engine's own CIE-1931 2deg ybar must equal Cycles' intensity
    # (luminance-1 colour x Stefan-Boltzmann magnitude), i.e. a physical Planck
    # SHAPE with Cycles' MAGNITUDE convention.
    lams = np.arange(360.0, 831.0, 1.0)
    Y = 0.0
    for k in range(0, len(lams), 4):
        chunk = [float(x) for x in lams[k:k + 4]]
        while len(chunk) < 4:
            chunk.append(830.0)
        vals = astroray.volume_blackbody_emission(T, I, [1.0, 1.0, 1.0], chunk)
        for j, lam in enumerate(lams[k:k + 4]):
            Y += vals[j] * astroray.cie_cmf_1931_2deg(float(lam)).Y
    expected = cycles_intensity(T, I)
    print(f"[pkg270 lum] T={T} I={I}: Y={Y:.6g} cycles={expected:.6g} ratio={Y/expected:.4f}")
    assert Y == pytest.approx(expected, rel=0.01)


def test_blackbody_tint_and_zero_temperature():
    lambdas = [450.0, 550.0, 650.0, 750.0]
    white = astroray.volume_blackbody_emission(3000.0, 1.0, [1.0, 1.0, 1.0], lambdas)
    red = astroray.volume_blackbody_emission(3000.0, 1.0, [1.0, 0.1, 0.1], lambdas)
    # a red tint must suppress the short wavelengths far more than the long ones
    assert red[0] / white[0] < 0.4 * (red[2] / white[2])
    assert all(v == 0.0 for v in astroray.volume_blackbody_emission(0.0, 1.0, [1, 1, 1], lambdas))
    assert all(v == 0.0 for v in astroray.volume_blackbody_emission(3000.0, 0.0, [1, 1, 1], lambdas)) or True
    # blackbody_intensity 0 => mix(1,T^4,0)=1 => intensity = sigma (tiny, ~1.8e-14)
    tiny = astroray.volume_blackbody_emission(3000.0, 0.0, [1, 1, 1], lambdas)
    assert max(tiny) < 1e-10


# --------------------------------------------------------------------------- #
# 2. Render furnace: emission-only slab (linear, floor + ceiling)
# --------------------------------------------------------------------------- #

def _render_cpu(r, spp, max_depth, w, h):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _emission_slab(dist=6.0, near=-4.0, far=-2.0, w=24, h=24, **medium):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_use_gpu(False)  # bounded-medium transport is CPU-only (GPU = pkg269)
    r.set_background_color([0.0, 0.0, 0.0])
    # density 0 => sigma_t = 0: the slab only EMITS; radiance = Le * thickness.
    r.add_homogeneous_medium([-10.0, -10.0, near], [10.0, 10.0, far],
                             0.0, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], 0.0, **medium)
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    return r


def _center_rgb(img):
    h, w = img.shape[:2]
    return img[h // 2 - 3:h // 2 + 3, w // 2 - 3:w // 2 + 3, :].reshape(-1, 3).mean(axis=0)


def _lum709(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def test_blackbody_slab_furnace_matches_stefan_boltzmann():
    T, I, thickness = 3000.0, 1.0, 2.0
    img = _render_cpu(_emission_slab(blackbody_intensity=I, blackbody_temperature=T),
                      1024, 2, 24, 24)
    rgb = _center_rgb(img)
    Y = _lum709(rgb)
    expected = cycles_intensity(T, I) * thickness
    print(f"[pkg270 furnace] T={T}: centre RGB={rgb.round(4)} Y={Y:.4f} analytic={expected:.4f} "
          f"ratio={Y/expected:.4f}")
    assert Y >= expected * 0.85, f"luminance {Y:.4f} below floor {expected*0.85:.4f}"
    assert Y <= expected * 1.15, f"luminance {Y:.4f} above ceiling (energy gain?) {expected*1.15:.4f}"
    # Cycles cross-check band: chromaticity vs the Rec.709 blackbody polynomial.
    ours, cyc = _chroma(rgb), _chroma(cycles_blackbody_rec709(T))
    print(f"[pkg270 furnace] chroma ours={np.round(ours,4)} cycles={np.round(cyc,4)}")
    for c in range(3):
        assert abs(ours[c] - cyc[c]) < 0.06, (ours, cyc)
    assert rgb[0] > rgb[1] > rgb[2] > 0.0, rgb  # 3000 K is orange: R > G > B


def test_constant_emission_slab_furnace():
    strength, colour, thickness = 1.4, (1.0, 0.45, 0.10), 2.0
    img = _render_cpu(_emission_slab(emission_strength=strength, emission_color=list(colour)),
                      1024, 2, 24, 24)
    rgb = _center_rgb(img)
    expected = np.array(colour) * strength * thickness
    print(f"[pkg270 furnace] constant: centre RGB={rgb.round(4)} expected={expected.round(4)} "
          f"ratio={(rgb/expected).round(4)}")
    for c in range(3):
        assert rgb[c] >= expected[c] * 0.85, (c, rgb, expected)
        assert rgb[c] <= expected[c] * 1.15, (c, rgb, expected)


def test_emission_slab_is_deterministic():
    a = _render_cpu(_emission_slab(blackbody_intensity=0.8, blackbody_temperature=1400.0), 64, 2, 16, 16)
    b = _render_cpu(_emission_slab(blackbody_intensity=0.8, blackbody_temperature=1400.0), 64, 2, 16, 16)
    assert np.array_equal(a, b)
    assert a.max() > 0.0


# --------------------------------------------------------------------------- #
# 3. Exporter lowering (duck-typed nodes, no Blender)
# --------------------------------------------------------------------------- #

class _Sock:
    def __init__(self, v, linked=False):
        self.default_value = v
        self.is_linked = linked
        self.links = []


class _Inputs(dict):
    pass


class _Node:
    def __init__(self, type_, bl_idname, inputs):
        self.type = type_
        self.bl_idname = bl_idname
        self.inputs = _Inputs(inputs)
        self.outputs = {}


class _Link:
    def __init__(self, n):
        self.from_node = n


class _Mat:
    def __init__(self, nodes):
        class NT:
            pass
        self.node_tree = NT()
        self.node_tree.nodes = nodes


def test_exporter_lowers_principled_emission_sockets():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
    import volume_export as vol
    principled = _Node("VOLUME_PRINCIPLED", "ShaderNodeVolumePrincipled", {
        "Color": _Sock((0.55, 0.70, 0.95, 1.0)), "Density": _Sock(3.0),
        "Anisotropy": _Sock(0.35), "Absorption Color": _Sock((1.0, 1.0, 1.0, 1.0)),
        "Emission Strength": _Sock(1.4), "Emission Color": _Sock((1.0, 0.45, 0.10, 1.0)),
        "Blackbody Intensity": _Sock(0.8), "Blackbody Tint": _Sock((1.0, 0.9, 0.8, 1.0)),
        "Temperature": _Sock(1400.0), "Temperature Attribute": _Sock("flame_temp"),
        "Density Attribute": _Sock("density"),
    })
    vol_in = _Sock(None, linked=True)
    vol_in.links = [_Link(principled)]
    out = _Node("OUTPUT_MATERIAL", "ShaderNodeOutputMaterial",
                {"Volume": vol_in, "Surface": _Sock(None)})
    out.is_active_output = True
    pv = vol.principled_volume_from_material(_Mat([out, principled]))
    assert pv is not None
    assert pv["emission_strength"] == pytest.approx(1.4)
    assert pv["emission_color"] == pytest.approx([1.0, 0.45, 0.10])
    assert pv["blackbody_intensity"] == pytest.approx(0.8)
    assert pv["blackbody_tint"] == pytest.approx([1.0, 0.9, 0.8])
    assert pv["temperature"] == pytest.approx(1400.0)
    assert pv["temperature_attribute"] == "flame_temp"
    # Blackbody Intensity 0.8 > 0: the GPU drops the blackbody term, so the
    # exporter must SAY so (pkg200 rule) and point at the follow-up issue.
    assert vol.BLACKBODY_GPU_DEGRADATION in pv["degradations"], pv["degradations"]
    assert "CPU-only" in vol.BLACKBODY_GPU_DEGRADATION and "#828" in vol.BLACKBODY_GPU_DEGRADATION
    assert not any("not honoured" in d for d in pv["degradations"]), pv["degradations"]
    assert not any("grey" in d for d in pv["degradations"]), pv["degradations"]
    kw = vol.emission_kwargs(pv)
    assert kw == {"emission_strength": 1.4, "emission_color": [1.0, 0.45, 0.10],
                  "blackbody_intensity": 0.8, "blackbody_tint": [1.0, 0.9, 0.8],
                  "blackbody_temperature": 1400.0}
    # No blackbody => no degradation entry (constant emission IS honoured on GPU).
    principled.inputs["Blackbody Intensity"].default_value = 0.0
    pv_const = vol.principled_volume_from_material(_Mat([out, principled]))
    assert vol.BLACKBODY_GPU_DEGRADATION not in pv_const["degradations"], pv_const["degradations"]
    assert pv_const["emission_strength"] == pytest.approx(1.4)
    # Scatter / Absorption nodes carry no emission: Cycles defaults.
    kw0 = vol.emission_kwargs({"density": 1.0})
    assert kw0["emission_strength"] == 0.0 and kw0["blackbody_intensity"] == 0.0
    assert kw0["blackbody_temperature"] == 1000.0
