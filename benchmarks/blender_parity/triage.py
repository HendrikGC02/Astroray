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

2. ``triage()`` - assign every FAILING feature to exactly one bucket:
   NOT-IMPLEMENTED / TRANSLATION-BUG / INTENTIONAL-DIVERGENCE / NOISE-LIMITED.
   The NOISE-LIMITED bucket is decided by ``classify_noise_vs_bug()`` from an
   SPP-escalation sweep the driver supplies (see below).

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

# SPP-escalation discriminator (memory: mc-noise-vs-deterministic). A single-spp
# read cannot separate MC noise from a structural bug that preserves mean colour
# (a flipped/rotated UV or a geometry offset also lands ratios-in-band + small-dE
# + low-SSIM). The ONLY robust discriminator is a samples sweep: re-render both
# legs at ESCALATION_FACTOR x the run's spp and re-gate. A noise-limited SSIM
# CLIMBS toward the threshold with more samples; a structural bug's SSIM deficit
# PLATEAUS. Concrete climb rule lives in classify_noise_vs_bug().
ESCALATION_FACTOR = 4          # higher-spp re-render is 4x the run's samples
NOISE_CLIMB_MARGIN = 0.03      # min absolute SSIM increase to call it a climb
NOISE_GAP_SHRINK = 0.40        # gap-to-threshold must shrink by >= 40%
NOISE_DELTA_E_FRAC = 0.5       # "small dE" == <= DELTA_E_MAX * this fraction (4.0)

# Triage buckets (spec Phase B + Phase-B/C follow-up NOISE-LIMITED).
NOT_IMPLEMENTED = "NOT-IMPLEMENTED"
TRANSLATION_BUG = "TRANSLATION-BUG"
INTENTIONAL_DIVERGENCE = "INTENTIONAL-DIVERGENCE"
NOISE_LIMITED = "NOISE-LIMITED"

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


@dataclass
class Escalation:
    """Evidence from the higher-spp re-render the driver performs for a
    noise-suspect FAIL. All fields are plain numbers so triage stays pure and
    unit-testable without Blender/GPU. ``ratio_high`` / ``delta_e_high`` come from
    the higher-spp (more converged) render."""
    ssim_low: float
    ssim_high: float
    spp_low: int
    spp_high: int
    ratio_high: tuple[float, float, float]
    delta_e_high: float


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


def ratio_in_band(ratio: tuple[float, float, float]) -> bool:
    """True iff every channel's mean ratio is within [RATIO_LO, RATIO_HI] - no
    energy/hue bias. A low-SSIM FAIL with in-band ratios is either MC noise or a
    mean-preserving structural bug; the SPP sweep tells them apart."""
    return all(RATIO_LO <= r <= RATIO_HI for r in ratio)


def is_noise_suspect(ratio: tuple[float, float, float], delta_e: float,
                     *, delta_e_max: float = DELTA_E_MAX) -> bool:
    """A FAILED cell worth an SPP-escalation re-render: per-channel ratios all
    in-band AND mean dE well under the gate (<= DELTA_E_MAX * NOISE_DELTA_E_FRAC).
    Cheap gate the driver checks BEFORE paying for the higher-spp render."""
    return ratio_in_band(ratio) and delta_e <= delta_e_max * NOISE_DELTA_E_FRAC


def classify_noise_vs_bug(
    ssim_low_spp: float,
    ssim_high_spp: float,
    spp_low: int,
    spp_high: int,
    ratio: tuple[float, float, float],
    delta_e: float,
    ssim_min: float = SSIM_MIN,
    *,
    delta_e_max: float = DELTA_E_MAX,
) -> bool:
    """Decide, from a two-point SPP sweep, whether a FAILED cell is MC-noise-
    limited (True) rather than a real structural translation bug (False).

    Climb rule (documented, deterministic):
      * Guard - a real energy/hue bias is never noise: require ``ratio`` in-band
        and ``delta_e`` small (<= DELTA_E_MAX * NOISE_DELTA_E_FRAC). Out-of-band
        or large-dE -> False (routes to the existing rules / TRANSLATION-BUG).
      * The sweep must actually escalate (``spp_high > spp_low``).
      * If the higher-spp SSIM CROSSES the threshold (gap_high <= 0) the deficit
        was purely convergence -> True.
      * Otherwise require BOTH a meaningful climb (>= NOISE_CLIMB_MARGIN) AND the
        gap-to-threshold to shrink by >= NOISE_GAP_SHRINK (40%). A structural bug
        PLATEAUS: SSIM barely moves and the gap stays wide -> False, so the bug
        is NOT masked.
    """
    if not ratio_in_band(ratio):
        return False
    if delta_e > delta_e_max * NOISE_DELTA_E_FRAC:
        return False
    if spp_high <= spp_low:
        return False
    gap_low = ssim_min - ssim_low_spp
    gap_high = ssim_min - ssim_high_spp
    climb = ssim_high_spp - ssim_low_spp
    if gap_high <= 0.0:            # crossed the threshold on more samples
        return True
    if gap_low <= 0.0:            # wasn't actually below threshold at low spp
        return False
    gap_shrink = (gap_low - gap_high) / gap_low
    return climb >= NOISE_CLIMB_MARGIN and gap_shrink >= NOISE_GAP_SHRINK


def triage(
    feature: str,
    phase_a_bucket: str,
    gate_result: GateResult,
    *,
    known_intentional: dict[str, str] | None = None,
    known_not_implemented: dict[str, str] | None = None,
    escalation: Escalation | None = None,
    ssim_min: float = SSIM_MIN,
) -> tuple[str, str]:
    """Assign a FAILING feature to exactly one triage bucket.

    Precedence (deterministic):
      1. explicit known-intentional table (pkg89 lights, spectral nodes)
      2. Phase-A APPROXIMATED  -> INTENTIONAL-DIVERGENCE (documented approx)
      3. uniform energy-scale ratio -> INTENTIONAL-DIVERGENCE (pending pkg89)
      4. explicit known-not-implemented table
      5. SPP-escalation says MC-noise-limited -> NOISE-LIMITED (needs ``escalation``)
      6. default (Phase-A SUPPORTED but wrong render) -> TRANSLATION-BUG

    Returns (bucket, reason). Caller must only invoke this for a FAILED gate.
    ``escalation`` is the higher-spp re-render evidence the driver supplies for a
    noise-suspect FAIL; without it the noise rule is skipped and the default
    (TRANSLATION-BUG) stands, so a real bug is never masked by a missing sweep.
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
    if escalation is not None and classify_noise_vs_bug(
            escalation.ssim_low, escalation.ssim_high,
            escalation.spp_low, escalation.spp_high,
            escalation.ratio_high, escalation.delta_e_high, ssim_min):
        return (NOISE_LIMITED,
                (f"MC-noise-limited: SSIM climbs {escalation.ssim_low:.4f}"
                 f"->{escalation.ssim_high:.4f} across {escalation.spp_low}"
                 f"->{escalation.spp_high} spp with in-band ratios and mean dE "
                 f"{escalation.delta_e_high:.2f}; under-converged, not a bug"))
    return (TRANSLATION_BUG,
            f"Phase-A SUPPORTED but render diverges ({gate_result.reason})")
