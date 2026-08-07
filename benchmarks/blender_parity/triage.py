# -*- coding: utf-8 -*-
"""pkg119 Phase B - differential-parity thresholds + failure triage (pure).

This module holds the *decision logic* of the differential harness and is
deliberately free of ``bpy``/``numpy``-render dependencies so it is fully
unit-testable on CPU with synthetic metric values (no Blender, no GPU).

Two responsibilities:

1. ``gate()`` - given the reference-bank metrics for a feature (SSIM +
   mean dE2000 + per-channel mean ratio), decide PASS / FAIL against explicit
   thresholds. The thresholds themselves are reused pkg104 metrics; no new
   metric stack is introduced here.

2. ``triage()`` - assign every FAILING feature to exactly one of the three
   spec buckets: NOT-IMPLEMENTED / TRANSLATION-BUG / INTENTIONAL-DIVERGENCE.

Thresholds rationale
--------------------
* ``SSIM_MIN = 0.90`` - Cycles (oracle) and Astroray draw *independent* Monte
  Carlo streams, so a tight windowed SSIM is unreachable at modest spp
  (memory: ssim-wrong-gate-for-independent-rng - windowed SSIM >= 0.985 is
  unreachable for independent MC streams). 0.90 catches gross structural
  divergence (wrong texture, black material, missing feature) while tolerating
  per-pixel MC noise. compute_ssim already clips to the shared 99.9 percentile
  (pkg71 firefly guard).
* ``DELTA_E_MAX = 8.0`` - mean CIEDE2000 over the frame. ~8 is a clearly
  visible-but-not-gross perceptual gap; a correct translation of an RGB feature
  lands well under it, an energy-scale or hue bug blows past it.
* ``RATIO_LO / RATIO_HI = 0.85 / 1.18`` - per-channel mean-ratio band. NOT part
  of the pass gate (the spec names SSIM/dE); used only in triage to recognise a
  pure energy-scale divergence (e.g. pkg89 dedicated lights render ~3x hot vs
  Cycles - memory pkg89 findings) so it triages to INTENTIONAL-DIVERGENCE
  (pending the pkg89 GPU-upload / wattage follow-ups) rather than a translation
  bug.

These are the defaults; ``gate()`` and ``triage()`` accept overrides so a
per-feature threshold can be pinned without editing this module.
"""

from __future__ import annotations

from dataclasses import dataclass

SSIM_MIN = 0.90
DELTA_E_MAX = 8.0
RATIO_LO = 0.85
RATIO_HI = 1.18

# Triage buckets (spec Phase B).
NOT_IMPLEMENTED = "NOT-IMPLEMENTED"
TRANSLATION_BUG = "TRANSLATION-BUG"
INTENTIONAL_DIVERGENCE = "INTENTIONAL-DIVERGENCE"

# Features whose Cycles-vs-Astroray difference is physically justified (spectral
# vs RGB, or a known-deferred energy/GPU gap) rather than a bug. Seeded from the
# spec's "Dependencies & sequencing notes" (pkg89) and the spectral nodes.
# feature -> reason string.
KNOWN_INTENTIONAL_DIVERGENCE: dict[str, str] = {
    # pkg89 dedicated lights: GPU upload deferred + uniform ~3x exposure vs
    # Cycles (spec sequencing notes; pkg115 findings 1 & 5). Tag pending the
    # pkg89 follow-ups, do NOT attempt the GPU port here.
    "POINT": "pkg89: dedicated-light energy/GPU-upload gap (deferred follow-up)",
    "SUN": "pkg89: dedicated-light energy/GPU-upload gap (deferred follow-up)",
    "AREA": "pkg89: dedicated-light energy/GPU-upload + area-normal orientation "
            "(deferred follow-up; see verify_pkg122 orientation note)",
    "SPOT": "pkg89: dedicated-light energy/GPU-upload gap (deferred follow-up)",
    # Spectral-domain nodes: Astroray is spectral, Cycles maps these to RGB.
    "WAVELENGTH": "spectral-vs-RGB: single-wavelength emission differs by design",
    "BLACKBODY": "spectral-vs-RGB: Planckian locus sampled spectrally vs RGB",
}

# Features the render probe shows the addon reads (Phase-A SUPPORTED) but the
# engine has no distinct behaviour for -> roadmap follow-up, not a bug. Empty by
# default; the on-hardware run fills this from observed no-effect renders.
KNOWN_NOT_IMPLEMENTED: dict[str, str] = {}


@dataclass
class GateResult:
    passed: bool
    ssim: float
    delta_e: float
    ratio: tuple[float, float, float]
    reason: str = ""


def gate(
    ssim: float,
    delta_e: float,
    ratio: tuple[float, float, float],
    *,
    ssim_min: float = SSIM_MIN,
    delta_e_max: float = DELTA_E_MAX,
) -> GateResult:
    """PASS iff SSIM >= ssim_min AND mean dE2000 <= delta_e_max.

    ``ratio`` (per-channel mean Astroray/Cycles) is carried through for triage;
    it does not affect pass/fail.
    """
    reasons = []
    ssim_ok = ssim >= ssim_min
    de_ok = delta_e <= delta_e_max
    if not ssim_ok:
        reasons.append(f"SSIM {ssim:.4f} < {ssim_min}")
    if not de_ok:
        reasons.append(f"dE2000 {delta_e:.3f} > {delta_e_max}")
    return GateResult(
        passed=ssim_ok and de_ok,
        ssim=float(ssim),
        delta_e=float(delta_e),
        ratio=(float(ratio[0]), float(ratio[1]), float(ratio[2])),
        reason="; ".join(reasons),
    )


def ratio_is_energy_scale(ratio: tuple[float, float, float]) -> bool:
    """True iff all three channels miss the band in the SAME direction - the
    signature of a uniform exposure/energy-scale offset (pkg89 ~3x), as opposed
    to a hue/structure bug that moves channels differently."""
    lows = [r < RATIO_LO for r in ratio]
    highs = [r > RATIO_HI for r in ratio]
    return all(highs) or all(lows)


def triage(
    feature: str,
    phase_a_bucket: str,
    gate_result: GateResult,
    *,
    known_intentional: dict[str, str] | None = None,
    known_not_implemented: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Assign a FAILING feature to exactly one triage bucket.

    Precedence (deterministic):
      1. explicit known-intentional table (pkg89 lights, spectral nodes)
      2. Phase-A APPROXIMATED  -> INTENTIONAL-DIVERGENCE (documented approx)
      3. uniform energy-scale ratio -> INTENTIONAL-DIVERGENCE (pending pkg89)
      4. explicit known-not-implemented table
      5. default (Phase-A SUPPORTED but wrong render) -> TRANSLATION-BUG

    Returns (bucket, reason). Caller must only invoke this for a FAILED gate.
    """
    ki = KNOWN_INTENTIONAL_DIVERGENCE if known_intentional is None else known_intentional
    kni = KNOWN_NOT_IMPLEMENTED if known_not_implemented is None else known_not_implemented

    if feature in ki:
        return INTENTIONAL_DIVERGENCE, ki[feature]
    if phase_a_bucket == "APPROXIMATED":
        return (INTENTIONAL_DIVERGENCE,
                ("Phase-A APPROXIMATED: nearest-behaviour mapping is documented, "
                 "not a bug"))
    if ratio_is_energy_scale(gate_result.ratio):
        return (INTENTIONAL_DIVERGENCE,
                (f"uniform energy-scale ratio {gate_result.ratio} "
                 f"(pending energy-model / pkg89 follow-up)"))
    if feature in kni:
        return NOT_IMPLEMENTED, kni[feature]
    return (TRANSLATION_BUG,
            f"Phase-A SUPPORTED but render diverges ({gate_result.reason})")
