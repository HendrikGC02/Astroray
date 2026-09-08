"""pkg265 (PR #778 review 2, cycles-parity-reviewer CRITICAL #2) — a thin-film
rough Principled glass must NOT be routed through the Heitz multiple-scattering
walk.

The walk (chooseAndSampleDir, roughness > kDeltaGlassRoughness) sets isDelta=true
(the skip-NEE delta contract) and carries PLAIN-dielectric Fresnel throughput.
For a thin-film glass (thin_film_thickness > the 0.1nm cutoff) that has two bugs
the reviewer flagged with file:line:

  (1) DOUBLE-COUNTED DIRECT LIGHT. eval()/pdf() still return the nonzero single-
      scatter thin-film f for a thin-film glass, so NEE adds it — then sample()
      flips isDelta and the emitter hit is taken at full wasSpecular MIS weight.
      Measured (emissive quad behind a glass sphere, black world, r0.85): the
      thin-film sphere reads +31% over the plain-glass single-count reference.
  (2) IRIDESCENCE DROPPED ON THE SAMPLED PATH. The walk uses plain-dielectric
      Fresnel, so the thin film has NO effect on the BSDF-sampled render. Pre-fix,
      a thin-film rough glass is BYTE-IDENTICAL to a plain glass in a world-lit
      scene (the walk never consults the film). That is the clean regression
      signal used here.

Fix (lead decision, option 2): thin-film rough glass falls back to the origin/main
single-scatter rough-transmission sampler (isDelta=false), so sample == eval == pdf
are all single-scatter thin-film — no double count, iridescence preserved via
eval() on the sampled path. Non-film glass keeps the walk. Disney glass has no
thin-film path (no change). A thin-film-AWARE walk is filed as #783. See
.astroray_plan/docs/pkg265-multiscatter-microfacet-research.md §7.

Note on the gate choice: a naive "uniform furnace stays ~1.0" gate does NOT go RED
pre-fix (the walk conserves energy in a uniform field just fine; the double count
only surfaces where a hittable emitter dominates), and render-level film/nonfilm
brightness ratios are confounded by the walk-vs-single-scatter directional
difference. The BYTE-IDENTICAL-pre-fix / DIFFERENT-post-fix signal below is the
reliable, non-confounded discriminator and catches the ROOT cause of both bugs
(routing a thin-film glass through the plain-Fresnel walk).
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

IOR = 1.45
FILM_THICKNESS = 500.0   # nm, well above the 0.1nm filmActive() cutoff
FILM_IOR = 1.33


def _params(roughness, film):
    p = {"transmission_weight": 1.0, "ior": IOR, "roughness": roughness,
         "metallic": 0.0}
    if film:
        p["thin_film_thickness"] = FILM_THICKNESS
        p["thin_film_ior"] = FILM_IOR
    return p


def _world_only(roughness, film, *, spp=256, depth=32):
    """Rough glass lit PURELY by a uniform white world background (no lights → no
    NEE), so this is a BSDF-sampling-only render. render()'s 4th arg is
    applyGamma; False keeps it LINEAR so energy gain is detectable
    (memory: gamma-furnace-cannot-detect-energy-gain)."""
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    g = r.create_material("principled", [1.0, 1.0, 1.0], _params(roughness, film))
    r.add_sphere([0.0, 0.0, 0.0], 1.0, g)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 80, 80)
    r.set_seed(7)
    img = np.asarray(r.render(spp, depth, None, False),
                     dtype=np.float32).reshape(80, 80, 3)
    return img[28:52, 28:52].mean(axis=(0, 1))


def test_thinfilm_rough_glass_not_ignored_by_walk_cpu():
    """ROOT-CAUSE gate. A thin-film rough glass must render DIFFERENTLY from an
    otherwise-identical plain glass. Pre-fix the walk consults only plain-
    dielectric Fresnel, so the two are byte-identical (reldiff ~0.000 → RED). The
    single-scatter fallback honours the film, so they differ (measured reldiff
    0.158 at r0.85 → GREEN)."""
    film = _world_only(0.85, True)
    plain = _world_only(0.85, False)
    reldiff = abs(float(film.mean()) - float(plain.mean())) / float(plain.mean())
    assert reldiff >= 0.02, (
        f"thin-film rough glass is indistinguishable from plain glass "
        f"(reldiff={reldiff:.4f}); the thin film is being ignored — a thin-film "
        f"glass is on the plain-Fresnel Heitz walk instead of the single-scatter "
        f"sampler (pkg265 PR #778 CRITICAL #2). film={np.round(film,4)} "
        f"plain={np.round(plain,4)}")


@pytest.mark.parametrize("roughness", [0.5, 0.85])
def test_thinfilm_rough_glass_no_energy_gain_cpu(roughness):
    """No double-count ENERGY GAIN. A lossless glass (R+T=1) in a uniform white
    field can only LOSE energy (single-scatter) — never exceed the field. A
    reading above ~1.0 would mean direct light was added twice. The single-scatter
    fallback reads at/below 1.0 (r0.5≈0.965, r0.85≈0.836 — the accepted single-
    scatter deficit that #783's thin-film-aware walk would recover); it must never
    exceed 1.02."""
    film = _world_only(roughness, True)
    val = float(film.mean())
    assert val <= 1.02, (
        f"thin-film rough glass white furnace = {val:.3f} > 1.02 at r{roughness}: "
        f"direct light gained/double-counted (pkg265 PR #778 CRITICAL #2). "
        f"RGB={np.round(film,4)}")
    # Lower bound is loose on purpose: single-scatter thin-film loses real energy
    # at high roughness (that is exactly why #783 tracks a thin-film-aware walk).
    assert val >= 0.60, (
        f"thin-film rough glass white furnace = {val:.3f} < 0.60 at r{roughness}: "
        f"grossly dark, not the expected single-scatter deficit.")
