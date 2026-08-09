"""pkg178 Stage-3b PR-6 — CPU gates for the Principled `alpha` transparent lobe.

Design: .astroray_plan/docs/pkg178-stage3-d4-and-forks-decision.md §3 (Alpha).
Cycles reference: svm/closure.h (CLOSURE_BSDF_PRINCIPLED_ID does transparency FIRST —
`bsdf_transparent_setup(sd, weight*(1-alpha)); weight *= alpha;`) + bsdf_transparent.h
(`wo = -wi`, matched pdf==eval so f/pdf==weight, zero eval/pdf outside sampling).

Astroray twin: a delta GPR_TRANSPARENT lobe assembled FIRST with weight (1-alpha),
the remaining lobes scaled by alpha. `f = weight_T`, `pdf = qj` → f/pdf = weight_T/qj,
the same shape as the existing delta glass. Load-bearing property (the safety proof):
at alpha==1 NO transparent lobe is assembled, so the whole stack — and in particular
the validated delta-glass gates — is BYTE-IDENTICAL to PR-4b.

Exact partition (Veach 1997 §9.2.4 one-sample MIS; the W-cancel argument in the
design doc §4.4): E[pixel] = (1-alpha)*L_bg + alpha*L_bsdf, where L_bsdf is the
alpha==1 (opaque) render — so transparency reallocates variance, never expectation.

These gates are CPU-only (no GPU/RTX). GPU bit-identity at alpha==1, the <false>/
<true> STACK deltas, and GPU alpha renders are LEAD-DEFERRED (build/verify machine).
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


def _norm(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _mat(params, base=(0.9, 0.9, 0.9)):
    r = astroray.Renderer()
    mid = r.create_material("principled", list(base), params)
    return r, mid


def _render_center(params, *, base=(0.0, 0.0, 0.0), bg=(1.0, 1.0, 1.0),
                   spp=256, depth=16, seed=7, size=48):
    """Render a single Principled sphere on a uniform background; return the
    mean of the sphere-centre patch (linear, apply_gamma=False)."""
    r = astroray.Renderer()
    r.set_background_color(list(bg))
    r.set_integrator("path_tracer")
    mid = r.create_material("principled", list(base), params)
    r.add_sphere([0, 0, 0], 1.0, mid)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, size, size)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(size, size, 3)
    lo, hi = int(size * 0.42), int(size * 0.58)
    return float(img[lo:hi, lo:hi].mean())


def _render_center_flat(params, *, base=(0.0, 0.0, 0.0), bg=(1.0, 1.0, 1.0),
                        spp=512, depth=8, seed=7, size=48):
    """Render a SINGLE flat quad (normal +Z) facing the camera on a uniform bg,
    return the mean of the centre patch. Unlike a sphere, a flat surface has ONE
    interface: the transparent branch (wi=-wo) goes straight to the background, so
    the exact one-sample-MIS partition E = (1-alpha)*L_bg + alpha*L_bsdf holds
    with no recursive back-surface term."""
    r = astroray.Renderer()
    r.set_background_color(list(bg))
    r.set_integrator("path_tracer")
    mid = r.create_material("principled", list(base), params)
    e = 1.5
    r.add_triangle([-e, -e, 0], [e, -e, 0], [e, e, 0], mid)   # +Z normal
    r.add_triangle([-e, -e, 0], [e, e, 0], [-e, e, 0], mid)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, size, size)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(size, size, 3)
    lo, hi = int(size * 0.42), int(size * 0.58)
    return float(img[lo:hi, lo:hi].mean())


def _render_full(params, *, base, bg=(1.0, 1.0, 1.0), spp=64, depth=16, seed=7, size=32,
                 transmission=False):
    r = astroray.Renderer()
    r.set_background_color(list(bg))
    r.set_integrator("path_tracer")
    mid = r.create_material("principled", list(base), params)
    r.add_sphere([0, 0, 0], 1.0, mid)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, size, size)
    r.set_seed(seed)
    return np.asarray(r.render(spp, depth, None, False), dtype=np.float32)


# ---------------------------------------------------------------------------
# 1. alpha == 1 is byte-identical to the material with no alpha set (the SAFETY
#    property: no transparent lobe is assembled, the stack is unchanged).
# ---------------------------------------------------------------------------

def test_alpha1_eval_bit_identical_to_default():
    """Continuous-BSDF eval at alpha=1 must equal the default (no-alpha) eval
    exactly — the transparent lobe is not assembled at alpha=1."""
    params = {"metallic": 0.3, "roughness": 0.4}
    r0, m0 = _mat(params)
    r1, m1 = _mat({**params, "alpha": 1.0})
    wo = _norm([0.3, 1.0, 0.2])
    wis = [_norm([0.0, 1.0, 0.0]), _norm([0.5, 1.0, 0.1]),
           _norm([-0.2, 1.0, 0.5]), _norm([0.3, 1.0, 0.3])]
    e0 = np.array([r0.eval_material(m0, list(wo), list(wi)) for wi in wis])
    e1 = np.array([r1.eval_material(m1, list(wo), list(wi)) for wi in wis])
    assert np.array_equal(e0, e1), f"alpha=1 eval != default:\n{e0}\n{e1}"


def test_alpha1_render_bit_identical_to_default():
    """A full deterministic (fixed-seed) render at alpha=1 must be pixel-for-pixel
    identical to the default material — the whole integrator path is unchanged."""
    base = (0.7, 0.5, 0.3)
    a = _render_full({"metallic": 0.2, "roughness": 0.5}, base=base)
    b = _render_full({"metallic": 0.2, "roughness": 0.5, "alpha": 1.0}, base=base)
    assert np.array_equal(a, b), (
        f"alpha=1 render differs from default: max|Δ|={np.abs(a - b).max():.3e}")


def test_delta_glass_furnace_unchanged_at_alpha1():
    """THE load-bearing safety proof: smooth (delta) glass at alpha=1 is byte-
    identical to the default, and remains energy-conserving. Adding the alpha lobe
    must not perturb the validated delta-glass gates when alpha==1 (Cycles' own
    `if (alpha < 1.0f)` guard — no transparent closure is set up)."""
    glass = {"transmission_weight": 1.0, "roughness": 0.01, "ior": 1.5}
    a = _render_full(glass, base=(1.0, 1.0, 1.0), spp=64, depth=32, size=32)
    b = _render_full({**glass, "alpha": 1.0}, base=(1.0, 1.0, 1.0), spp=64, depth=32, size=32)
    assert np.array_equal(a, b), (
        f"delta-glass render CHANGED at alpha=1: max|Δ|={np.abs(a - b).max():.3e}")
    # And the furnace itself stays ~1.0 (linear floor + ceiling).
    m = float(a.reshape(32, 32, 3)[12:20, 12:20].mean())
    assert 0.90 < m < 1.08, f"delta-glass furnace mean {m:.3f} not conserving energy"


# ---------------------------------------------------------------------------
# 2. alpha == 0 is fully transparent (straight-through, background shows through).
# ---------------------------------------------------------------------------

def test_alpha0_straight_through_sample():
    """At alpha=0 (near) every BSDF sample is the delta transparent event
    wi = -wo with a positive pdf — Cycles bsdf_transparent.h sample()."""
    r, mid = _mat({"metallic": 0.0, "roughness": 0.5, "alpha": 0.0})
    wo = _norm([0.3, 1.0, 0.15])
    rng = np.random.default_rng(3)
    u2 = np.ascontiguousarray(rng.random((2, 512)), dtype=np.float32)
    wi, pdf = r.debug_bsdf_sample_batch(mid, list(wo), u2)
    wi = np.asarray(wi, dtype=np.float64)      # (N,3)
    pdf = np.asarray(pdf, dtype=np.float64)
    straight = wi @ (-wo)                        # dot(wi, -wo); ==1 for wi==-wo
    frac = float(np.mean((straight > 0.9999) & (pdf > 0.0)))
    assert frac > 0.95, f"only {frac:.2%} of alpha=0 samples were straight-through delta events"


def test_alpha0_background_shows_through():
    """A black-base sphere at alpha=0 is invisible: the sphere-centre patch equals
    the (white) background, because the transparent lobe carries the ray straight
    through to the environment."""
    c = _render_center({"metallic": 0.0, "roughness": 0.5, "alpha": 0.0})
    assert c > 0.95, f"alpha=0 sphere centre {c:.3f} should show the white background (~1.0)"


# ---------------------------------------------------------------------------
# 3. Intermediate alpha: the exact one-sample-MIS partition
#    E = (1-alpha)*L_bg + alpha*L_bsdf, monotone in alpha.
# ---------------------------------------------------------------------------

def test_alpha_intermediate_partition():
    """On a SINGLE flat surface, center(alpha) follows the exact one-sample-MIS
    partition E = (1-alpha)*L_bg + alpha*L_bsdf, with L_bg=1 (white bg) and
    L_bsdf=center(alpha=1). (A sphere would add a recursive back-surface term; a
    flat quad has one interface so the transparent branch reaches the bg directly.)"""
    params = {"metallic": 0.0, "roughness": 0.5}
    c0 = _render_center_flat({**params, "alpha": 0.0})
    c025 = _render_center_flat({**params, "alpha": 0.25})
    c05 = _render_center_flat({**params, "alpha": 0.5})
    c1 = _render_center_flat({**params, "alpha": 1.0})
    # Monotone: more alpha -> more opaque -> darker (dark base on white bg).
    assert c0 > c05 > c1, f"center not monotone in alpha: c0={c0:.3f} c05={c05:.3f} c1={c1:.3f}"
    # Exact partition at each alpha: center(a) == (1-a)*1 + a*center(1).
    for a, c in [(0.25, c025), (0.5, c05)]:
        predicted = (1.0 - a) * 1.0 + a * c1
        assert abs(c - predicted) < 0.03, (
            f"alpha={a} center {c:.3f} off analytic partition {predicted:.3f} "
            f"(c0={c0:.3f}, c1={c1:.3f})")


# ---------------------------------------------------------------------------
# 4. Energy conservation (no gain) — white sphere in a white furnace has
#    L_bsdf == L_bg == 1, so E = (1-alpha)*1 + alpha*1 == 1 for ALL alpha.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alpha", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_alpha_white_furnace_no_gain(alpha):
    c = _render_center({"metallic": 0.0, "roughness": 0.5, "alpha": alpha},
                       base=(1.0, 1.0, 1.0), spp=256)
    assert 0.90 < c < 1.08, f"alpha={alpha} white furnace centre {c:.3f} (energy not conserved)"
