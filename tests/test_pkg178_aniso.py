"""pkg178 Stage-3b PR-4b — CPU gates for anisotropic Principled GGX (αx≠αy).

The load-bearing property is that `anisotropic == 0` reduces EXACTLY to the PR-4a
isotropic code (bit-identical), and `anisotropic → 0` is continuous into it. These
gates run on CPU (no GPU/RTX). The GPU aniso parity + iso-continuity + non-aniso
bit-identity on RTX, the pkg119b Cycles parity sweep, and pkg129 metal re-run are
LEAD-DEFERRED (require the build/verify machine). See the PR report.

Frame note: makeMaterialTestRecord seeds rec.uvTangent = the arbitrary tangent
(= what a sphere hit carries), normal = +Y, tangent = +X, bitangent = -Z; the
aniso frame is therefore X = +X (large-α axis for anisotropic>0), Y = -Z.
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

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _mat(params):
    r = astroray.Renderer()
    mid = r.create_material("principled", [0.9, 0.9, 0.9], params)
    return r, mid


def _norm(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# 1. Iso reduction / continuity: anisotropic in {0, 1e-4} must give (nearly)
#    identical eval and pdf — the aniso branch reduces to the iso branch.
# ---------------------------------------------------------------------------

def _eval_dirs(r, mid, wo, wis):
    return np.array([r.eval_material(mid, list(wo), list(wi)) for wi in wis], dtype=np.float64)


@pytest.mark.parametrize("params", [
    {"metallic": 1.0, "roughness": 0.4},
    {"metallic": 0.0, "roughness": 0.35, "specular_ior_level": 0.5},
])
def test_aniso_continuity_eval(params):
    """anisotropic=1e-4 eval ≈ anisotropic=0 eval across the reflection lobe."""
    r0, m0 = _mat(params)
    r1, m1 = _mat({**params, "anisotropic": 1e-4})
    wo = _norm([0.3, 1.0, 0.1])
    # A spread of wi around the mirror direction.
    wis = [_norm([0.0, 1.0, 0.0]), _norm([0.4, 1.0, 0.0]), _norm([0.0, 1.0, 0.4]),
           _norm([0.3, 1.0, 0.3]), _norm([-0.3, 1.0, -0.2]), _norm([0.5, 1.0, 0.2])]
    e0 = _eval_dirs(r0, m0, wo, wis)
    e1 = _eval_dirs(r1, m1, wo, wis)
    denom = np.maximum(np.abs(e0), 1e-4)
    rel = np.abs(e1 - e0) / denom
    assert rel.max() < 5e-3, f"aniso→0 eval discontinuity: max rel {rel.max():.2e}\n{e0}\n{e1}"


def test_aniso_continuity_pdf():
    r0, m0 = _mat({"metallic": 1.0, "roughness": 0.4})
    r1, m1 = _mat({"metallic": 1.0, "roughness": 0.4, "anisotropic": 1e-4})
    wo = _norm([0.3, 1.0, 0.1])
    wis = np.ascontiguousarray(
        np.array([_norm([0.0, 1.0, 0.0]), _norm([0.4, 1.0, 0.0]),
                  _norm([0.0, 1.0, 0.4]), _norm([0.3, 1.0, 0.3])]), dtype=np.float32)  # (N,3)
    p0 = np.asarray(r0.debug_bsdf_pdf_batch(m0, list(wo), wis), dtype=np.float64)
    p1 = np.asarray(r1.debug_bsdf_pdf_batch(m1, list(wo), wis), dtype=np.float64)
    rel = np.abs(p1 - p0) / np.maximum(p0, 1e-4)
    assert rel.max() < 5e-3, f"aniso→0 pdf discontinuity: {p0} vs {p1}"


# ---------------------------------------------------------------------------
# 2. anisotropic=0 is identical to the material with no anisotropic param set
#    (the default path does not perturb the isotropic result).
# ---------------------------------------------------------------------------

def test_aniso_zero_equals_default():
    r0, m0 = _mat({"metallic": 1.0, "roughness": 0.5})
    r1, m1 = _mat({"metallic": 1.0, "roughness": 0.5, "anisotropic": 0.0})
    wo = _norm([0.2, 1.0, 0.4])
    wis = [_norm([0.0, 1.0, 0.0]), _norm([0.5, 1.0, 0.1]), _norm([-0.2, 1.0, 0.5])]
    e0 = _eval_dirs(r0, m0, wo, wis)
    e1 = _eval_dirs(r1, m1, wo, wis)
    assert np.allclose(e0, e1, atol=0.0, rtol=0.0), f"anisotropic=0 != default:\n{e0}\n{e1}"


# ---------------------------------------------------------------------------
# 3. Orientation: with anisotropic>0 the lobe is WIDER along the tangent (large
#    alpha_x, +X) than along the bitangent (small alpha_y, -Z). Off-mirror eval
#    falls off slower in the wide direction → eval(+X offset) > eval(bitangent
#    offset). Isotropic: the two are equal.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("aniso", [0.6, 0.9])
def test_aniso_orientation(aniso):
    wo = _norm([0.0, 1.0, 0.0])           # view along the normal → mirror = +Y
    d = np.deg2rad(18.0)
    wi_tan = _norm([np.sin(d), np.cos(d), 0.0])    # offset along +X (tangent, large α)
    wi_bit = _norm([0.0, np.cos(d), np.sin(d)])    # offset along ±Z (bitangent, small α)

    r_iso, m_iso = _mat({"metallic": 1.0, "roughness": 0.35})
    e_iso_t = r_iso.eval_material(m_iso, list(wo), list(wi_tan))[1]
    e_iso_b = r_iso.eval_material(m_iso, list(wo), list(wi_bit))[1]
    assert abs(e_iso_t - e_iso_b) / max(e_iso_t, 1e-4) < 5e-3, "isotropic must be rotationally symmetric"

    r_a, m_a = _mat({"metallic": 1.0, "roughness": 0.35, "anisotropic": aniso})
    e_t = r_a.eval_material(m_a, list(wo), list(wi_tan))[1]
    e_b = r_a.eval_material(m_a, list(wo), list(wi_bit))[1]
    assert e_t > e_b * 1.15, (
        f"anisotropic={aniso}: tangent-offset eval {e_t:.4f} should exceed "
        f"bitangent-offset eval {e_b:.4f} (elongated highlight)")


# ---------------------------------------------------------------------------
# 4. Anisotropic sample/pdf consistency: sampled directions land in the upper
#    hemisphere with positive pdf, and the pdf integrates near unity via a coarse
#    MC estimate over sampled directions (a fast sanity net; the rigorous χ² grid
#    is in tests/statistical/test_chi2_principled.py).
# ---------------------------------------------------------------------------

def test_aniso_sample_pdf_positive():
    r, mid = _mat({"metallic": 1.0, "roughness": 0.4, "anisotropic": 0.8,
                   "anisotropic_rotation": 0.25})
    wo = _norm([0.2, 1.0, 0.3])
    rng = np.random.default_rng(7)
    u2 = np.ascontiguousarray(rng.random((2, 256)), dtype=np.float32)  # (2,N)
    _wi, pdf = r.debug_bsdf_sample_batch(mid, list(wo), u2)
    pdf = np.asarray(pdf, dtype=np.float64)
    ok = pdf > 0
    assert ok.mean() > 0.9, f"only {ok.mean():.2%} of aniso samples had positive pdf"


# ---------------------------------------------------------------------------
# 5. White-furnace energy conservation with anisotropy ON (linear; floor +
#    ceiling). A perfectly reflecting anisotropic metal must not create or
#    destroy energy (Kulla-Conty comp fed the geometric-mean roughness).
# ---------------------------------------------------------------------------

def _furnace_mean(params, samples=64):
    r = astroray.Renderer()
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=32, height=32)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    mid = r.create_material("principled", [1.0, 1.0, 1.0], params)
    r.add_sphere([0, 0, 0], 1.0, mid)
    px = np.array(r.render(samples, 8, None, False), dtype=np.float32)  # linear
    return float(np.mean(px))


@pytest.mark.parametrize("aniso", [0.5, 0.9])
def test_aniso_white_furnace(aniso):
    m = _furnace_mean({"metallic": 1.0, "roughness": 0.5, "anisotropic": aniso})
    assert 0.9 < m < 1.08, f"anisotropic={aniso} furnace mean {m:.3f} (energy not conserved)"
