"""pkg160 — plain `metal` GGX multi-scatter energy compensation (CPU).

Replaces tests/test_pkg160_ggx_table_systems.py, which pinned the measured
DISAGREEMENT between this repo's two GGX energy-compensation table systems.
One of those systems no longer exists, so that pin is gone; this file pins the
state that replaced it.

What changed (pkg160)
---------------------
`MetalPlugin::eval`/`evalSpectral` (plugins/materials/metal.cpp) used to return

    singleScatter + albedo * (Fms * roughness*(2-roughness) * 1.3)

with `Fms = ggxMultiScatterCompensation(...)` reading a runtime-MC
`GGXEnergyCompensationLUT` that lived in include/raytracer.h. That term was
wrong three independent ways:

  1. WRONG TABLE. The runtime LUT estimated E with 256 uniform-hemisphere
     samples per cell, which cannot resolve a narrow GGX lobe, so E -> 0 as
     roughness -> 0. Since Fms = (1-Ewo)(1-Ewi)/(pi*max(1-Eavg,1e-4)), that
     pinned Fms near its 1/pi ceiling exactly where multiple scattering should
     vanish. Measured at roughness 0.15, mu 0.5: runtime E = 0.0407 vs the
     shipped Cycles table's 0.9985 (24.6x), and 1030x in the downstream Fms.
  2. NO COSINE. AGENTS.md:87 — `Material::eval()` returns brdf * NdotL. The
     singleScatter term bakes the cosine in (NdotL cancels against the
     Cook-Torrance 1/(4*NdotV*NdotL) denominator), but the additive term
     carried no NdotL at all.
  3. INVENTED WEIGHT. `roughness*(2-roughness)` and `* 1.3f` appear in no
     publication (CLAUDE.md section 6).

metal.cpp now applies the same MULTIPLICATIVE compensation disney.cpp has
shipped since pkg60/pkg145 — Kulla & Conty 2017 Eq. 6-9 in the form Cycles
ships as `microfacet_ggx_preserve_energy` (bsdf_microfacet.h:389-436,
BSD-3-Clause), net factor `1 + Fms*(1-E)/E`, off the shipped
data/disney_compensation/ggx_E{,avg}.bin tables. Multiplicative fixes all
three at once: right table, inherits singleScatter's cosine, no free weights.

That is also the table the GPU has — `uploadGgxTables()` (src/gpu/gpu_ggx_tables.cu)
copies `DisneyEnergyCompensationTables::ggxEData()/ggxEavgData()` verbatim into
`g_ggxE`/`g_ggxEavg`, which `gpu_metal_eval` reads through
`gpu_ggxCompensationFactor`. CPU and GPU now read one table with one formula.

CPU-only: no GPU needed. The GPU/CPU render gate is
tests/test_pkg160_plain_metal_gpu_cpu_parity.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray_test_helpers
    HELPERS_AVAILABLE = True
except ImportError:
    HELPERS_AVAILABLE = False

try:
    import astroray
    ASTRORAY_AVAILABLE = True
except ImportError:
    ASTRORAY_AVAILABLE = False


# The roughness sweep pkg160 uses everywhere. 0.05 sits BELOW
# MetalPlugin::kNearDeltaThreshold (0.1) and is the untouched-control row;
# 0.1 itself is deliberately excluded because it sits exactly ON the
# threshold. 0.15 is the disney_contact_sheet plain-metal patch, i.e. the
# config the original defect was measured at.
ROUGHNESS_SWEEP = [0.05, 0.15, 0.3, 0.6, 0.9]


# ---------------------------------------------------------------------------
# Table + formula pins (astroray_test_helpers only)
# ---------------------------------------------------------------------------

helpers_only = pytest.mark.skipif(
    not HELPERS_AVAILABLE, reason="astroray_test_helpers not built"
)


def _reference_darkening(f: float, e: float, eavg: float) -> float:
    """Kulla & Conty 2017 Eq. 6-9 / Cycles microfacet_ggx_preserve_energy,
    written out independently here so the C++ implementation is checked
    against the published formula rather than against itself."""
    f = min(max(f, 0.0), 0.999)
    missing = (1.0 - e) / e
    fms = f * eavg / max(1.0 - f * (1.0 - eavg), 1e-4)
    return 1.0 + fms * missing


@helpers_only
def test_shipped_tables_are_loaded():
    """Guards everything below: an unloaded table fills with 1.0, which would
    make the compensation trivially 1.0 and every assertion vacuous."""
    assert astroray_test_helpers.disney_compensation_tables_loaded(), (
        "data/disney_compensation/*.bin failed to load; metal.cpp would fall "
        "back to an uncompensated single-scatter lobe and this file's "
        "assertions would be meaningless"
    )


@helpers_only
@pytest.mark.parametrize("roughness", ROUGHNESS_SWEEP)
@pytest.mark.parametrize("mu", [0.15, 0.5, 0.95])
def test_darkening_channel_matches_published_formula(roughness, mu):
    """astroray::ggxDarkeningChannel (include/astroray/energy_compensation.h)
    is the SINGLE host definition metal.cpp and disney.cpp share, and the
    device twin gpu_ggxDarkeningChannel must stay byte-identical to it. Check
    it against the published closed form at a real (roughness, mu) grid."""
    e = astroray_test_helpers.disney_ggx_e(roughness, mu)
    eavg = astroray_test_helpers.disney_ggx_eavg(roughness)
    for f in (0.05, 0.35, 0.78, 0.92, 1.0):
        got = astroray_test_helpers.ggx_darkening_channel(f, max(e, 1e-4),
                                                          min(max(eavg, 0.0), 0.999))
        want = _reference_darkening(f, max(e, 1e-4), min(max(eavg, 0.0), 0.999))
        assert got == pytest.approx(want, rel=1e-5)


@helpers_only
@pytest.mark.parametrize("roughness", ROUGHNESS_SWEEP)
def test_compensation_brightens_and_grows_with_roughness(roughness):
    """Sanity properties of the factor metal.cpp now multiplies in, evaluated
    off the SHIPPED table (the one uploaded to the GPU as g_ggxE):

      * >= 1.0 — it restores energy the single-scatter lobe lost, never removes
        any. The term it replaced could not make this claim: it was additive
        with a `1.3` gain and no cosine.
      * monotonically larger with roughness at fixed mu — more energy is lost
        to multiple scattering as the surface roughens. The deleted runtime LUT
        got this exactly BACKWARDS (its Fms peaked at roughness -> 0).
    """
    mu = 0.5
    f = 0.92  # the contact-sheet gold R channel; conductor F0 = albedo
    e = max(astroray_test_helpers.disney_ggx_e(roughness, mu), 1e-4)
    eavg = min(max(astroray_test_helpers.disney_ggx_eavg(roughness), 0.0), 0.999)
    factor = astroray_test_helpers.ggx_darkening_channel(f, e, eavg)
    assert factor >= 1.0, (
        f"compensation factor {factor} < 1 at roughness={roughness}: this term "
        "is multiplicative energy RESTORATION and must never darken"
    )

    if roughness > ROUGHNESS_SWEEP[0]:
        prev = ROUGHNESS_SWEEP[ROUGHNESS_SWEEP.index(roughness) - 1]
        e_prev = max(astroray_test_helpers.disney_ggx_e(prev, mu), 1e-4)
        eavg_prev = min(max(astroray_test_helpers.disney_ggx_eavg(prev), 0.0), 0.999)
        prev_factor = astroray_test_helpers.ggx_darkening_channel(f, e_prev, eavg_prev)
        assert factor >= prev_factor, (
            f"compensation at roughness={roughness} ({factor:.4f}) is not >= "
            f"roughness={prev} ({prev_factor:.4f}); multiple-scattering energy "
            "loss must grow with roughness"
        )


# ---------------------------------------------------------------------------
# White furnace — the behavioural pin that metal.cpp itself changed
# ---------------------------------------------------------------------------

furnace = pytest.mark.skipif(
    not ASTRORAY_AVAILABLE, reason="astroray not built"
)

FURNACE_W = FURNACE_H = 24
FURNACE_SPP = 256
FURNACE_DEPTH = 8
FURNACE_SEED = 424242

# Measured on this branch, MinGW g++ -O2 CPU build, 32x32 @ 512spp depth 8,
# green channel, albedo=1 / environment=1 (scratch furnace run, 2026-07-26).
# BEFORE pkg160 the CPU conductor CREATED energy:
#   roughness 0.05 -> 1.0007   (near-delta path, untouched by pkg160)
#   roughness 0.15 -> 1.6434
#   roughness 0.30 -> 1.2530
#   roughness 0.60 -> 1.4069
#   roughness 0.90 -> 1.7690
# AFTER:
#   roughness 0.05 -> 1.0007   (byte-identical, as required)
#   roughness 0.15 -> 0.8823
#   roughness 0.30 -> 0.8511
#   roughness 0.60 -> 0.8092
#   roughness 0.90 -> 0.8802
#
# The residual ~0.81-0.88 deficit is NOT what pkg160 set out to fix and is
# expected: Astroray's conductor uses the UE4/Karis remapped Smith-Schlick
# masking term (k = (roughness+1)^2/8) and D-based (non-VNDF) sampling, while
# the shipped ggx_E table was baked by Cycles for height-correlated Smith with
# VNDF sampling, so the compensation is approximate for THIS lobe. Same
# approximation disney.cpp has shipped since pkg60. Closing it properly is
# pkg129 (Turquin multi-scatter LUTs).
FURNACE_CEILING = 1.02
FURNACE_FLOOR = 0.70


def _furnace_value(roughness: float) -> float:
    """Directional-hemispherical reflectance of the conductor lobe: an
    albedo=1 sphere that fills the frame inside an environment of radiance 1,
    with nothing else in the scene. Every camera ray hits the conductor, so
    each pixel IS the BRDF's reflectance at that view angle."""
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    m = r.create_material("metal", [1.0, 1.0, 1.0], {"roughness": roughness})
    r.add_sphere([0.0, 0.0, 0.0], 0.9, m)
    # Camera at 1.35 with a 60 deg vertical fov: the sphere's angular radius
    # (41.8 deg) exceeds the frame corner (39.2 deg), so coverage is total.
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, FURNACE_W / FURNACE_H, 0.0, 1.35, FURNACE_W, FURNACE_H)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", FURNACE_DEPTH)
    r.set_seed(FURNACE_SEED)
    # 4th positional arg is applyGamma -- must stay False for a linear
    # radiometric comparison (memory gamma-vs-linear-comparison-artifact).
    px = np.asarray(r.render(FURNACE_SPP, FURNACE_DEPTH, None, False),
                    dtype=np.float64)
    assert np.all(np.isfinite(px)), "furnace render produced NaN/Inf"
    return float(px[..., 1].mean())


@furnace
@pytest.mark.parametrize("roughness", ROUGHNESS_SWEEP)
def test_metal_white_furnace_conserves_energy(roughness):
    """A conductor with F0 = 1 in an environment of radiance 1 cannot reflect
    more than 1. Pre-pkg160 plain `metal` reflected up to 1.77x — the additive
    multiscatter term was manufacturing radiance.

    This is the test that pins metal.cpp itself (the table pins above only
    exercise the helper). It is deliberately a physical bound, not a golden
    value, so it survives table regeneration and MC-noise changes.
    """
    value = _furnace_value(roughness)
    print(f"\n[pkg160 metal furnace] roughness={roughness} reflectance={value:.4f}")
    assert value <= FURNACE_CEILING, (
        f"plain metal reflects {value:.4f} > {FURNACE_CEILING} of the incident "
        f"radiance at roughness={roughness} with albedo=1 — the conductor lobe "
        f"is creating energy. This is the pkg160 defect (measured 1.25-1.77 "
        f"before the fix)."
    )
    assert value >= FURNACE_FLOOR, (
        f"plain metal reflects only {value:.4f} < {FURNACE_FLOOR} at "
        f"roughness={roughness}; the multi-scatter compensation is missing or "
        f"the shipped ggx_E tables failed to load (uncompensated single "
        f"scatter falls well below this)."
    )


@furnace
def test_near_delta_row_is_untouched_by_pkg160():
    """roughness <= kNearDeltaThreshold (0.1) takes MetalPlugin's perfect-mirror
    shortcut, which pkg160 does not touch and which was already byte-identical
    to gpu_metal_eval's. Measured 1.0007 both before and after the fix -- if
    this row moves, the compensation leaked into the near-delta branch."""
    value = _furnace_value(0.05)
    assert value == pytest.approx(1.0, abs=0.02), (
        f"near-delta metal furnace reflectance {value:.4f} is not ~1.0; the "
        "perfect-mirror shortcut must remain uncompensated (measured 1.0007 on "
        "both sides of the pkg160 fix)"
    )
