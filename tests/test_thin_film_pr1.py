"""pkg178 Stage 4 PR-1 — CPU dielectric thin-film (Belcour-Barla) gates.

CPU-only (GPU is PR-3): every test forces set_use_gpu(False). The thin-film
utility math itself is unit-tested in tests/cpp/test_thin_film_fresnel.cpp
(analytic-phase check vs exact closed-form Airy). Here we gate the CPU integration
into the native "principled" dielectric specular + transmission Fresnel:

  * thickness-0 BIT-EQUALITY (load-bearing): thin_film_thickness ∈ {absent, 0,
    0.05nm ≤ cutoff} render byte-identical — the film is a true no-op when off.
  * film ON actually changes the image (wired, not dead code).
  * furnace (LINEAR ceiling, memory gamma-furnace-cannot-detect-energy-gain): the
    film creates no energy across a thickness sweep, front and back faces.
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


def _render(params, *, transmission, color=(1.0, 1.0, 1.0), spp=48, depth=24, bg=1.0):
    r = astroray.Renderer()
    r.set_use_gpu(False)  # CPU only — GPU thin film is PR-3
    r.set_background_color([bg, bg, bg])
    p = {"ior": 1.5, "roughness": 0.12, "metallic": 0.0, "transmission_weight": transmission}
    p.update(params)
    mid = r.create_material("principled", list(color), p)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, _W, _W)
    r.set_seed(_SEED)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(_W, _W, 3)
    return img


# ---------------------------------------------------------------------------
# thickness-0 bit-equality (load-bearing no-op guard)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("transmission,label", [(0.0, "specular"), (1.0, "glass")])
def test_thin_film_thickness0_bit_equality(transmission, label):
    base = _render({}, transmission=transmission)                          # param absent
    zero = _render({"thin_film_thickness": 0.0}, transmission=transmission)
    subc = _render({"thin_film_thickness": 0.05}, transmission=transmission)  # ≤ 0.1 cutoff
    assert np.array_equal(base, zero), (
        f"{label}: thin_film_thickness=0 not byte-identical to absent "
        f"(max Δ={np.abs(base - zero).max():.3e})")
    assert np.array_equal(base, subc), (
        f"{label}: thin_film_thickness=0.05 (≤cutoff) not byte-identical to off "
        f"(max Δ={np.abs(base - subc).max():.3e})")


# ---------------------------------------------------------------------------
# film ON changes the image (wired, colored iridescence). Specular uses a black
# base so the (small) dielectric specular lobe is not swamped by white diffuse.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("transmission,color,label",
                         [(0.0, (0.0, 0.0, 0.0), "specular"), (1.0, (1.0, 1.0, 1.0), "glass")])
def test_thin_film_on_changes_image(transmission, color, label):
    off = _render({"thin_film_thickness": 0.0}, transmission=transmission, color=color)
    on = _render({"thin_film_thickness": 400.0, "thin_film_ior": 1.4},
                 transmission=transmission, color=color)
    diff = float(np.abs(on - off).mean())
    assert diff > 1e-3, f"{label}: thin film (400nm) did not change the image (mean Δ={diff:.3e})"
    # iridescence is chromatic: the per-channel means should not move in lockstep.
    dr, dg, db = (on - off).reshape(-1, 3).mean(axis=0)
    spread = max(abs(dr - dg), abs(dg - db), abs(dr - db))
    assert spread > 1e-4, f"{label}: film change is achromatic (no hue shift): {dr:.4f},{dg:.4f},{db:.4f}"


# ---------------------------------------------------------------------------
# furnace: the film creates NO net energy across a thickness × film-IOR sweep.
# A glass sphere is a LENS — individual pixels legitimately exceed 1.0 by caustic
# focusing (the film-OFF render peaks ~1.7 too), so the energy check is on the
# whole-image MEAN vs the film-OFF mean (established glass-furnace methodology,
# tests/test_dielectric_glass_furnace.py), rendered LINEAR (memory
# gamma-furnace-cannot-detect-energy-gain).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("transmission,label", [(0.0, "specular"), (1.0, "glass")])
def test_thin_film_furnace_no_energy_gain(transmission, label):
    off_mean = float(_render({"thin_film_thickness": 0.0}, transmission=transmission, spp=64).mean())
    for d in (100.0, 300.0, 600.0, 1500.0, 3000.0):
        for fior in (1.2, 1.5, 1.8):
            m = float(_render({"thin_film_thickness": d, "thin_film_ior": fior},
                              transmission=transmission, spp=64).mean())
            # The film only redistributes Fresnel spectrally — total energy is
            # conserved, so the mean must stay within a tight band of the OFF mean
            # (a genuine energy GAIN would push it well above off*1.06).
            assert m <= off_mean * 1.06 + 0.02, (
                f"{label} d={d} fior={fior}: mean {m:.4f} > off {off_mean:.4f} x1.06 (energy GAIN)")
            assert m >= off_mean * 0.90 - 0.02, (
                f"{label} d={d} fior={fior}: mean {m:.4f} < off {off_mean:.4f} x0.90 (energy LOSS)")


# ---------------------------------------------------------------------------
# backface: a glass sphere refracts rays IN and OUT, exercising the backface film
# path (film IOR ÷ bulk IOR, adjust_thin_film_ior_at_backface). Both interfaces
# must stay energy-conserving — the eta² bug-class guard. Mean-based (lensing).
# ---------------------------------------------------------------------------
def test_thin_film_glass_backface_furnace():
    off_mean = float(_render({"thin_film_thickness": 0.0}, transmission=1.0, spp=96).mean())
    on_mean = float(_render({"thin_film_thickness": 500.0, "thin_film_ior": 1.5},
                            transmission=1.0, spp=96).mean())
    assert abs(on_mean - off_mean) <= 0.06, (
        f"glass+film mean {on_mean:.4f} drifted from off {off_mean:.4f} (backface energy error)")
