"""
pkg160 Step 0 — pin the measured disagreement between Astroray's TWO
independent GGX energy-compensation table systems.

Why this file exists
--------------------
`gpu_metal_eval` (include/astroray/gpu_materials.h) omits the multiscatter
term that `MetalPlugin::eval`/`evalSpectral` (plugins/materials/metal.cpp:54-58,
:86-89) add:

    Fms          = ggxMultiScatterCompensation(NdotV, NdotL, roughness)
    msWeight     = roughness * (2 - roughness)
    multiScatter = albedo * (Fms * msWeight * 1.3)

Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks" —
the GGX multiscatter energy-compensation term.

The obvious mirror is to write `gpu_ggxE(roughness, mu)` in place of the CPU's
`lut.lookupE(mu, roughness)`. **That does not work**, and this test is the
executable proof, so nobody re-derives it or lands it silently:

  (1) `GGXEnergyCompensationLUT` (include/raytracer.h:281-379) is computed at
      RUNTIME by MC integration in its constructor — 256 uniform-hemisphere
      samples per cell. It is what the CPU metal path actually reads.
  (2) `DisneyEnergyCompensationTables` (include/astroray/energy_compensation.h)
      is LOADED from the shipped Cycles table data/disney_compensation/ggx_E.bin.
      It is the only one uploaded to the GPU (src/gpu/gpu_ggx_tables.cu ->
      g_ggxE, read by gpu_ggxE in gpu_ggx_tables.cuh).

They are different functions, not two views of one table. The mirrored index
conventions (`lookupE(mu, roughness)` vs `ggxE(roughness, mu)`) are each
internally consistent — there is no transposition bug — but the DATA disagrees
by more than an order of magnitude across most of the roughness range, and by
~1000x in the downstream `Fms` at the roughness the defect was measured at.

Numbers below were measured on main @ 3800759 by compiling the real repo code
(both table systems, MinGW g++ -O2) and dumping them over a common grid. See
.astroray_plan/packages/pkg160-gpu-plain-metal-multiscatter-omission.md
("Implementation hazard — WHICH E table?").

CPU-only: no renderer, no GPU. Pure table lookups.

Requires the `ggx_runtime_e`/`ggx_runtime_eavg`/`ggx_multiscatter_compensation`/
`disney_ggx_e`/`disney_ggx_eavg` helpers added to module/test_helpers_module.cpp
by this package. A STALE astroray_test_helpers will AttributeError rather than
skip — that is deliberate (memory `stale_pyd_locations`): rebuild it.
"""

from __future__ import annotations

import math

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray_test_helpers
    HELPERS_AVAILABLE = True
except ImportError:
    HELPERS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not HELPERS_AVAILABLE, reason="astroray_test_helpers not built"
)

# The plain-metal patch on tests/scenes/disney_contact_sheet.py — the config the
# GPU/CPU deficit (mean 0.279/0.286/0.316, median 0.141) was measured on. It sits
# just ABOVE MetalPlugin's kNearDeltaThreshold = 0.1, i.e. in the rough branch
# that diverges, which is why this roughness is the one that matters most.
CONTACT_SHEET_METAL_ROUGHNESS = 0.15

# Measured on main @ 3800759 (MinGW g++ -O2, ASTRORAY_DATA_DIR=<repo>/data), at
# mu = 0.5:  roughness -> (runtime lookupE, shipped ggxE)
MEASURED_E_AT_MU_HALF = {
    0.05: (0.001399, 0.999975),
    0.15: (0.040669, 0.998543),
    0.30: (0.353788, 0.974699),
    0.60: (0.549046, 0.782171),
    0.90: (0.457155, 0.535442),
}

# Loose enough to survive a compiler/FP-contraction difference, tight enough that
# a table regeneration or an index-convention change trips it.
ABS_TOL = 2e-3


def _shipped_fms(roughness: float, ndotv: float, ndotl: float) -> float:
    """ggxMultiScatterCompensation's formula (raytracer.h:372-379) evaluated
    against the SHIPPED tables instead of the runtime LUT — i.e. exactly what a
    naive `gpu_ggxE` mirror inside gpu_metal_eval would compute."""
    e_wo = astroray_test_helpers.disney_ggx_e(roughness, ndotv)
    e_wi = astroray_test_helpers.disney_ggx_e(roughness, ndotl)
    e_avg = astroray_test_helpers.disney_ggx_eavg(roughness)
    denom = math.pi * max(1.0 - e_avg, 1e-4)
    return max((1.0 - e_wo) * (1.0 - e_wi) / denom, 0.0)


def test_shipped_tables_are_loaded():
    """Guards every other assertion here: an unloaded table fills with 1.0 and
    would make the shipped side look trivially self-consistent."""
    assert astroray_test_helpers.disney_compensation_tables_loaded(), (
        "data/disney_compensation/*.bin failed to load; the shipped-vs-runtime "
        "comparison below is meaningless against the all-ones fallback"
    )


@pytest.mark.parametrize("roughness", sorted(MEASURED_E_AT_MU_HALF))
def test_both_e_tables_match_their_measured_values(roughness):
    """Pin BOTH systems so neither can drift silently under the other."""
    expect_runtime, expect_shipped = MEASURED_E_AT_MU_HALF[roughness]
    # Note the deliberately different argument orders — each table's own.
    got_runtime = astroray_test_helpers.ggx_runtime_e(0.5, roughness)
    got_shipped = astroray_test_helpers.disney_ggx_e(roughness, 0.5)
    assert got_runtime == pytest.approx(expect_runtime, abs=ABS_TOL)
    assert got_shipped == pytest.approx(expect_shipped, abs=ABS_TOL)


def test_the_two_e_tables_disagree_and_by_how_much():
    """The core Step-0 finding. If this ever goes GREEN in the sense of the two
    agreeing, the fix landscape for pkg160 changes completely — go re-read the
    spec before touching gpu_metal_eval."""
    runtime = astroray_test_helpers.ggx_runtime_e(0.5, CONTACT_SHEET_METAL_ROUGHNESS)
    shipped = astroray_test_helpers.disney_ggx_e(CONTACT_SHEET_METAL_ROUGHNESS, 0.5)
    assert shipped / runtime > 20.0, (
        f"runtime={runtime:.6f} shipped={shipped:.6f}: the two GGX E tables were "
        "measured to differ by ~24.6x here. They now agree more closely than "
        "pkg160 assumed — re-derive the fix rather than trusting this package."
    )


def test_runtime_lut_saturates_fms_at_low_roughness():
    """WHY the CPU term dominates at roughness 0.15, and why it is physically
    backwards there.

    ggxMultiScatterCompensation = (1-Ewo)(1-Ewi) / (pi * max(1-Eavg, 1e-4)).
    The runtime LUT's 256 uniform-hemisphere samples cannot resolve a narrow GGX
    lobe, so E -> 0 as roughness -> 0, which drives Fms -> 1/pi, its MAXIMUM,
    exactly where multiple scattering should vanish. The CPU therefore adds a
    near-constant ~0.11 * albedo ambient floor to smooth-ish metal.

    This is the CPU's behaviour and metal.cpp is canonical for pkg160 (do not
    'fix' it here) — but any GPU mirror inherits it, so it is pinned."""
    fms = astroray_test_helpers.ggx_multiscatter_compensation(
        0.5, 0.5, CONTACT_SHEET_METAL_ROUGHNESS
    )
    assert fms == pytest.approx(0.307206, abs=ABS_TOL)
    # Measured 0.3072 = 96.5% of the 1/pi ceiling; 0.9 leaves headroom without
    # weakening the "it is saturated" claim.
    assert fms > 0.90 * (1.0 / math.pi), "Fms no longer saturates; see docstring"


def test_shipped_tables_cannot_reproduce_the_cpu_term():
    """The decisive result: substituting gpu_ggxE() into gpu_metal_eval would
    close essentially NONE of the measured deficit at the roughness it was
    measured at. ~1000x too small at 0.15; only converges near roughness 0.9."""
    r = CONTACT_SHEET_METAL_ROUGHNESS
    runtime_fms = astroray_test_helpers.ggx_multiscatter_compensation(0.5, 0.5, r)
    shipped_fms = _shipped_fms(r, 0.5, 0.5)
    assert runtime_fms / shipped_fms > 100.0, (
        f"runtime Fms={runtime_fms:.6f} vs shipped-table Fms={shipped_fms:.6g} — "
        "pkg160 measured a ~1000x gap here. A gpu_ggxE-based mirror is only a "
        "viable fix if this ratio is near 1."
    )

    # ...and the convergence at high roughness, which is why a coarse sweep that
    # only samples roughness 0.9 would wrongly conclude the tables agree.
    runtime_hi = astroray_test_helpers.ggx_multiscatter_compensation(0.5, 0.5, 0.9)
    shipped_hi = _shipped_fms(0.9, 0.5, 0.5)
    assert 0.5 < runtime_hi / shipped_hi < 2.0
