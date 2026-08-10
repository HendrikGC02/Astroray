"""pkg178 Stage 4 PR-4 — Thin Wall (thin-glass) + thin subsurface CPU gates.

CPU-only here (GPU parity is a LEAD-run hardware gate). Ports Cycles
bsdf_thin_glass_setup (bsdf_microfacet.h:1236-1428) + bsdf_thin_subsurface_setup
(bsdf_oren_nayar.h:169). Gates:

  * default-OFF no-op: thin_wall absent / thin_wall=0 render byte-identical (the
    load-bearing safety proof; PR-6-style within-build comparison).
  * thin_wall=true actually changes the transmission + subsurface renders (wired).
  * R'+T' <= 1: the closed-form thin-glass split is energy-conserving over the
    (ior x roughness x angle x base_color) grid (Python port of thinGlassFresnelRGB).
  * furnace (LINEAR, memory gamma-furnace-cannot-detect-energy-gain): a thin-glass
    sphere creates no net energy across a roughness x ior sweep.
  * thin subsurface: the diffuse/translucent split follows subsurface_anisotropy
    (g<0 -> more front reflection, g>0 -> more back transmission).
"""
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

_W = 64
_SEED = 7


def _render(params, *, color=(0.8, 0.8, 0.8), spp=48, depth=24, bg=1.0):
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.set_background_color([bg, bg, bg])
    p = {"ior": 1.5, "roughness": 0.12, "metallic": 0.0}
    p.update(params)
    mid = r.create_material("principled", list(color), p)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, _W, _W)
    r.set_seed(_SEED)
    return np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(_W, _W, 3)


# ---------------------------------------------------------------------------
# default-OFF no-op: thin_wall absent vs thin_wall=0 is byte-identical (both take
# the pre-PR-4 else path). Covers the transmission AND subsurface code sites.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scene", [
    {"transmission_weight": 1.0, "roughness": 0.02},            # smooth glass
    {"transmission_weight": 1.0, "roughness": 0.35},            # rough glass
    {"subsurface_weight": 0.8},                                 # subsurface
    {"transmission_weight": 0.5, "subsurface_weight": 0.4},     # combined
])
def test_thin_wall_off_bit_equality(scene):
    absent = _render(scene)
    off = _render({**scene, "thin_wall": 0.0})
    assert np.array_equal(absent, off), (
        f"thin_wall=0 not byte-identical to absent for {scene} "
        f"(max delta={np.abs(absent - off).max():.3e})")


# ---------------------------------------------------------------------------
# thin_wall=true actually changes the render (wired, not dead code).
# ---------------------------------------------------------------------------
def test_thin_wall_changes_transmission():
    off = _render({"transmission_weight": 1.0, "roughness": 0.3}, color=(0.9, 0.6, 0.4))
    on = _render({"transmission_weight": 1.0, "roughness": 0.3, "thin_wall": 1.0},
                 color=(0.9, 0.6, 0.4))
    diff = float(np.abs(on - off).mean())
    assert diff > 1e-3, f"thin_wall transmission did not change the image (mean delta={diff:.3e})"


def test_thin_wall_changes_subsurface():
    off = _render({"subsurface_weight": 0.9, "ior": 1.0}, color=(0.85, 0.4, 0.3))
    on = _render({"subsurface_weight": 0.9, "ior": 1.0, "thin_wall": 1.0,
                  "subsurface_anisotropy": 0.6}, color=(0.85, 0.4, 0.3))
    diff = float(np.abs(on - off).mean())
    assert diff > 1e-3, f"thin_wall subsurface did not change the image (mean delta={diff:.3e})"


# ---------------------------------------------------------------------------
# R'+T' <= 1: closed-form energy conservation of the thin-glass split. Python
# port of PrincipledPlugin::thinGlassFresnelRGB (no-film path) — validates the
# FORMULA directly over the parameter grid (independent of the render).
# ---------------------------------------------------------------------------
def _thin_glass_RT(cos_i, ior, base, spec_tint):
    F0 = ((ior - 1.0) / (ior + 1.0)) ** 2
    eta_ct = ior * ior - (1.0 - cos_i * cos_i)
    if eta_ct <= 0.0:  # TIR at the front interface
        return 1.0, 0.0
    ci = abs(cos_i)
    cos_t = -np.sqrt(eta_ct) / ior          # negative (Cycles convention)
    rs = (ci + ior * cos_t) / (ci - ior * cos_t)
    rp = (cos_t + ior * ci) / (ior * ci - cos_t)
    Freal = 0.5 * (rs * rs + rp * rp)
    s = min(max((Freal - F0) / (1.0 - F0), 0.0), 1.0)
    f0c = F0 * spec_tint
    F1 = f0c + (1.0 - f0c) * s
    r1, t1 = F1, 1.0 - F1
    r2, t2 = r1, t1                          # no film
    cc = 0.0 if cos_t == 0.0 else base ** (-1.0 / cos_t)   # Beer
    denom = 1.0 - (r2 * cc) ** 2
    Tc = (cc * t1 * t2 / denom) if abs(denom) > 1e-12 else 0.0
    Rc = r1 + Tc * r2 * cc
    return Rc, Tc


def test_thin_glass_RplusT_le_one():
    worst = 0.0
    for ior in (1.05, 1.2, 1.33, 1.5, 1.8, 2.4):
        for cos_i in np.linspace(0.02, 1.0, 25):
            for base in (0.05, 0.3, 0.6, 0.9, 1.0):
                for st in (0.3, 0.7, 1.0):
                    R, T = _thin_glass_RT(cos_i, ior, base, st)
                    assert R >= -1e-6 and T >= -1e-6, f"negative R/T: {R},{T}"
                    worst = max(worst, R + T)
                    assert R + T <= 1.0 + 1e-5, (
                        f"R'+T'={R + T:.6f} > 1 (ior={ior} cos={cos_i:.3f} "
                        f"base={base} tint={st}) — energy GAIN")
    # sanity: the peak (no absorption, white tint) should be ~1 (not tiny)
    assert worst > 0.99, f"R'+T' never approaches 1 (peak {worst:.4f}) — check the port"


# ---------------------------------------------------------------------------
# furnace: a thin-glass sphere creates NO net energy across roughness x ior.
# Whole-image MEAN vs the off (opaque-ish) mean, LINEAR (glass lensing forbids a
# per-pixel <=1 bound; established glass-furnace methodology).
# ---------------------------------------------------------------------------
def test_thin_glass_furnace_no_energy_gain():
    # Reference: a thin white sheet in a white furnace should return ~background.
    for rough in (0.05, 0.2, 0.5):
        for ior in (1.2, 1.5, 2.0):
            m = float(_render({"transmission_weight": 1.0, "roughness": rough, "ior": ior,
                               "thin_wall": 1.0}, color=(1.0, 1.0, 1.0), spp=64).mean())
            assert m <= 1.06, f"thin glass r={rough} ior={ior}: mean {m:.4f} > 1.06 (energy GAIN)"
            assert m >= 0.85, f"thin glass r={rough} ior={ior}: mean {m:.4f} < 0.85 (energy LOSS)"


# ---------------------------------------------------------------------------
# thin subsurface: subsurface_anisotropy g steers energy between the front
# (diffuse, reflection) and back (translucent, transmission) hemispheres. With
# the sphere lit from a bright background, g<0 (more front) must be BRIGHTER to
# the camera than g>0 (more back-scatter away from the camera).
# ---------------------------------------------------------------------------
def test_thin_subsurface_anisotropy_split():
    front = float(_render({"subsurface_weight": 1.0, "ior": 1.0, "thin_wall": 1.0,
                           "subsurface_anisotropy": -0.9}, color=(0.9, 0.9, 0.9), spp=64).mean())
    back = float(_render({"subsurface_weight": 1.0, "ior": 1.0, "thin_wall": 1.0,
                          "subsurface_anisotropy": 0.9}, color=(0.9, 0.9, 0.9), spp=64).mean())
    assert front > back + 1e-3, (
        f"subsurface_anisotropy split not wired: g=-0.9 mean {front:.4f} "
        f"not brighter than g=+0.9 mean {back:.4f}")
