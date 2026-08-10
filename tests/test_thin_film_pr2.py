"""pkg178 Stage 4 PR-2 — CPU conductor (metallic) thin-film (Belcour-Barla) gates.

CPU-only (GPU is PR-3): every test forces set_use_gpu(False). PR-1 covers the
dielectric specular/transmission legs; here we gate the CONDUCTOR path — the
Principled metallic (F82) lobe whose thin-film bottom interface is a conductor
whose (n,k) come from the Gulbrandsen inversion (host-precomputed at ctor):

  * thickness-0 BIT-EQUALITY (load-bearing): a metallic Principled render with
    thin_film_thickness ∈ {absent, 0, 0.05nm ≤ cutoff} is byte-identical — the
    conductor film is a true no-op when off.
  * film ON actually changes the metallic image, chromatically (wired, not dead).
  * furnace (LINEAR ceiling, memory gamma-furnace-cannot-detect-energy-gain): the
    conductor film creates no net energy across a thickness × film-IOR sweep.
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


def _render(params, *, color=(0.9, 0.6, 0.2), spp=48, depth=16, bg=1.0):
    """Metallic sphere (metallic=1) under a uniform white environment — the
    conductor lobe reflects the background so the F82/film Fresnel is exercised."""
    r = astroray.Renderer()
    r.set_use_gpu(False)  # CPU only — GPU thin film is PR-3
    r.set_background_color([bg, bg, bg])
    p = {"ior": 1.5, "roughness": 0.12, "metallic": 1.0, "transmission_weight": 0.0}
    p.update(params)
    mid = r.create_material("principled", list(color), p)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, _W, _W)
    r.set_seed(_SEED)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(_W, _W, 3)
    return img


# ---------------------------------------------------------------------------
# thickness-0 bit-equality (load-bearing no-op guard for the metallic lobe)
# ---------------------------------------------------------------------------
def test_metallic_thin_film_thickness0_bit_equality():
    base = _render({})                              # param absent
    zero = _render({"thin_film_thickness": 0.0})
    subc = _render({"thin_film_thickness": 0.05})   # ≤ 0.1nm cutoff
    assert np.array_equal(base, zero), (
        "metallic: thin_film_thickness=0 not byte-identical to absent "
        f"(max Δ={np.abs(base - zero).max():.3e})")
    assert np.array_equal(base, subc), (
        "metallic: thin_film_thickness=0.05 (≤cutoff) not byte-identical to off "
        f"(max Δ={np.abs(base - subc).max():.3e})")


# ---------------------------------------------------------------------------
# film ON changes the metallic image, chromatically (iridescence, not dead code)
# ---------------------------------------------------------------------------
def test_metallic_thin_film_on_changes_image():
    off = _render({"thin_film_thickness": 0.0})
    on = _render({"thin_film_thickness": 400.0, "thin_film_ior": 1.4})
    diff = float(np.abs(on - off).mean())
    assert diff > 1e-3, f"metallic thin film (400nm) did not change the image (mean Δ={diff:.3e})"
    dr, dg, db = (on - off).reshape(-1, 3).mean(axis=0)
    spread = max(abs(dr - dg), abs(dg - db), abs(dr - db))
    assert spread > 1e-4, (
        f"metallic film change is achromatic (no hue shift): {dr:.4f},{dg:.4f},{db:.4f}")


# ---------------------------------------------------------------------------
# furnace: the conductor film creates NO net energy across a thickness × film-IOR
# sweep. A metallic sphere in a white environment reflects but never amplifies —
# the whole-image mean must stay in a tight band around the film-OFF mean, LINEAR
# (memory gamma-furnace-cannot-detect-energy-gain). Neutral base color keeps the
# F82 reflectance high so a spurious energy GAIN would be unmistakable.
# ---------------------------------------------------------------------------
def test_metallic_thin_film_furnace_no_energy_gain():
    off_mean = float(_render({"thin_film_thickness": 0.0}, color=(0.9, 0.9, 0.9), spp=64).mean())
    for d in (100.0, 300.0, 600.0, 1500.0, 3000.0):
        for fior in (1.2, 1.5, 1.8):
            m = float(_render({"thin_film_thickness": d, "thin_film_ior": fior},
                              color=(0.9, 0.9, 0.9), spp=64).mean())
            assert m <= off_mean * 1.06 + 0.02, (
                f"metallic d={d} fior={fior}: mean {m:.4f} > off {off_mean:.4f} x1.06 (energy GAIN)")
            assert m >= off_mean * 0.90 - 0.02, (
                f"metallic d={d} fior={fior}: mean {m:.4f} < off {off_mean:.4f} x0.90 (energy LOSS)")
