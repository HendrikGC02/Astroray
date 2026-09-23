"""pkg278 gate (d) - native-panel output-effect instrument (adaptive + denoise).

This is an OUTPUT-EFFECT instrument, not a reachability probe: adaptive sampling
and denoise must be driven **only by Blender's native panels**
(``scene.cycles.use_adaptive_sampling`` / ``scene.cycles.use_denoising`` /
``scene.cycles.samples``) and must change the render in the required direction,
on both CPU and GPU. The one exception is backend selection: the renderer's
device is chosen through the addon's supported ``custom_raytracer.device_mode``
property (``auto``/``cpu``/``gpu``), which is the documented backend selector.

Two layers
----------

* **Pure analysis helpers + unit tests** on synthetic arrays. These run in an
  ordinary host pytest process, import no ``bpy``, need no Blender and no GPU,
  and are the real regression coverage for the metric/record logic.
* **Native legs** (``test_gate_d_native_panels_effect``): explicitly opt-in via
  ``ASTRORAY_GATE_D_NATIVE=1``. The host pytest process **never imports bpy**;
  it spawns an isolated ``blender --background --factory-startup`` process (its
  own output dir, no installed-profile changes) running an in-Blender leg that
  registers the staged Astroray addon, asserts the exact ``CUSTOM_RAYTRACER``
  engine identity, renders the legs through the real F12 path, and writes raw
  linear top-down arrays plus per-leg settings. The host then reads those
  artifacts and evaluates the checks. The parent executes this under the shared
  GPU lock; it is never run by ordinary CI.

RED discipline
--------------

A genuinely absent sample-count AOV, an ignored native panel, or an absent
output effect is recorded as **RED**, never PASS and never invented. A missing
runtime dependency (no Blender / no addon dir / no CUDA device) is recorded as
**UNMEASURED**. The pytest function fails only when the instrument itself is
invalid (missing artifacts, dangling hashes, non-finite data, vacuous
reference) - a measured RED gate row is a valid pkg278 result.

Fixed-budget note
-----------------

The comparison budget is declared up front (``ADAPTIVE_BUDGET_SAMPLES``,
``REFERENCE_SAMPLES``, ``DENOISE_SETTLE_SAMPLES``). Adaptive sampling may retire
pixels early, so an equal max-spp budget is an upper bound on equal work; the
declared budget and the resolved per-leg sample counts are recorded so the
interpretation is auditable. This package fixes no adaptive algorithm.

Typed output
------------

``test_results/gate_native_panels/gate_native_panels.json`` (plus one
``gate_native_panels.<backend>.json`` per run) with ``schema_version: 1``,
``instrument: "gate_native_panels"``, ``build_id``, engine/build provenance,
and per-backend ``legs`` / ``checks`` records linked to SHA-256 artifact hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# Frozen gate (d) declarations. Declared here and in the acceptance manifest;
# never loosened at call time ("lead may adjust" is a spec change, not a runtime
# option).
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1
INSTRUMENT = "gate_native_panels"

# The engine identifier the addon registers (blender_addon/__init__.py:1050,
# CustomRaytracerRenderEngine.bl_idname). There is no fallback to the current /
# default engine: the native leg asserts this exact id after registration.
ENGINE_ID = "CUSTOM_RAYTRACER"

MEAN_REL_ERROR_MAX = 0.02          # mean relative luminance error <= 2 %
DETAIL_PRESERVATION_MIN = 0.95     # edge/texture gradient energy >= 0.95
ADAPTIVE_BUDGET_SAMPLES = 64       # declared fixed budget for the comparison
REFERENCE_SAMPLES = 512            # converged reference budget
DENOISE_SETTLE_SAMPLES = 64
LIGHT_FLOOR = 1e-4                 # reference must carry real light
DETAIL_ENERGY_FLOOR = 1e-6         # reference detail region must carry edges
CHECKER_DARK_MAX = 0.25            # fixed pre-render checker non-vacuity bound
CHECKER_BRIGHT_MIN = 0.45          # fixed pre-render checker non-vacuity bound
CHECKER_MIN_FRACTION = 0.02        # each tone must occupy this much detail ROI
FLAT_MAX_GRADIENT_ENERGY = 0.02    # flat ROI must remain distinguishable from checker

# Edge energy is measured after a single 3x3 box smooth so Monte-Carlo noise
# gradient is not counted as "preserved detail" (a noisy frame would otherwise
# inflate the ratio and hide a real blur).
DETAIL_SMOOTH = 3

# Declared reference-comparison regions (top-down, x0, y0, x1, y1), fixed BEFORE
# the render; never chosen after the fact. The flat region is a featureless
# diffuse floor patch and the detail region carries a high-contrast checker.
DECLARED_REGIONS = {
    "flat": (0.05, 0.45, 0.45, 0.95),
    "detail": (0.55, 0.45, 0.95, 0.95),
}

LEG_NAMES = ("adaptive_off", "adaptive_on", "denoise_off", "denoise_on", "reference")
SAMPLE_COUNT_PASS_NAME = "Sample Count"

# Native settings whose resolved (engine-effective) value must equal the native
# value for the native panel to be honoured.
NATIVE_PANEL_SETTINGS = ("samples", "use_adaptive_sampling", "use_denoising")

_NATIVE_ENV = "ASTRORAY_GATE_D_NATIVE"
_BACKENDS_ENV = "ASTRORAY_GATE_D_BACKENDS"
_BLENDER_ENV = "ASTRORAY_GATE_D_BLENDER"
_OUT_ENV = "ASTRORAY_GATE_D_OUT"
_ADDON_ENV = "ASTRORAY_SMOKE_ADDON_DIR"


# --------------------------------------------------------------------------- #
# Pure analysis helpers
# --------------------------------------------------------------------------- #

def luminance(img: np.ndarray) -> np.ndarray:
    """Rec.709 relative luminance; accepts HxW or HxWx(>=3)."""
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim == 2:
        return arr
    return arr[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def resolve_region(img: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    """Crop a normalized top-down ROI (y=0 is the TOP row)."""
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = roi
    return arr[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _box_smooth(img: np.ndarray) -> np.ndarray:
    """Separable 3x3 box smooth (no scipy dependency), 2-D or HxWxC."""
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim == 2:
        pad = np.pad(arr, 1, mode="reflect")
        out = np.zeros_like(arr)
        for dy in range(3):
            for dx in range(3):
                out += pad[dy:dy + arr.shape[0], dx:dx + arr.shape[1]]
        return out / 9.0
    pad = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="reflect")
    out = np.zeros_like(arr)
    for dy in range(3):
        for dx in range(3):
            out += pad[dy:dy + arr.shape[0], dx:dx + arr.shape[1]]
    return out / 9.0


def flat_region_noise(img: np.ndarray,
                      roi: tuple[float, float, float, float] = DECLARED_REGIONS["flat"]) -> float:
    """Standard deviation of luminance over a featureless region (MC noise)."""
    region = luminance(resolve_region(img, roi))
    if region.size == 0:
        return float("nan")
    return float(np.std(region))


def mean_relative_luminance_error(actual: np.ndarray, reference: np.ndarray,
                                  roi: tuple[float, float, float, float]) -> float:
    """Region-level relative error: mean|a-r| / mean|r|. Robust on dark pixels.

    A per-pixel relative error is ill-conditioned where the reference is black
    (a checker's dark cell), so the declared metric is the region mean absolute
    error normalised by the region's reference mean luminance. Returns NaN for
    an empty or non-finite region (invalid, never a silent pass).
    """
    a = luminance(resolve_region(actual, roi))
    r = luminance(resolve_region(reference, roi))
    if a.size == 0 or r.size == 0 or a.shape != r.shape:
        return float("nan")
    if not (np.isfinite(a).all() and np.isfinite(r).all()):
        return float("nan")
    denom = float(np.mean(np.abs(r)))
    if denom <= 1e-8:
        return float("nan")
    return float(np.mean(np.abs(a - r))) / denom


def gradient_energy(img: np.ndarray,
                    roi: tuple[float, float, float, float] = DECLARED_REGIONS["detail"]) -> float:
    """Edge/texture gradient energy over a region, after noise suppression."""
    lum = _box_smooth(luminance(img))
    region = resolve_region(lum, roi)
    if region.size == 0 or not np.isfinite(region).all():
        return float("nan")
    gy, gx = np.gradient(region)
    return float(np.mean(gx * gx + gy * gy))


def detail_preservation_ratio(actual: np.ndarray, reference: np.ndarray,
                              roi: tuple[float, float, float, float]) -> float:
    """Ratio of edge energy actual/reference. NaN if the reference is vacuous.

    A zero-detail reference is INVALID, never ``+inf`` success.
    """
    ref = gradient_energy(reference, roi)
    act = gradient_energy(actual, roi)
    if not np.isfinite(ref) or not np.isfinite(act) or ref <= DETAIL_ENERGY_FLOOR:
        return float("nan")
    return act / ref


def reference_nonvacuous(reference: np.ndarray) -> tuple[bool, dict]:
    """The converged reference must carry real light and real detail."""
    lum = luminance(reference)
    mean_lum = float(np.mean(lum)) if lum.size else float("nan")
    detail = gradient_energy(reference, DECLARED_REGIONS["detail"])
    finite = bool(np.isfinite(reference).all())
    ok = finite and np.isfinite(mean_lum) and mean_lum > LIGHT_FLOOR \
        and np.isfinite(detail) and detail > DETAIL_ENERGY_FLOOR
    return ok, {
        "finite": finite,
        "mean_luminance": mean_lum,
        "detail_gradient_energy": detail,
        "light_floor": LIGHT_FLOOR,
        "detail_energy_floor": DETAIL_ENERGY_FLOOR,
    }


def reference_regions_identified(reference: np.ndarray) -> tuple[bool, dict]:
    """Prove the frozen ROIs contain the authored flat/checker controls."""
    detail = luminance(resolve_region(reference, DECLARED_REGIONS["detail"]))
    flat = luminance(resolve_region(reference, DECLARED_REGIONS["flat"]))
    if detail.size == 0 or flat.size == 0 or not (np.isfinite(detail).all() and np.isfinite(flat).all()):
        return False, {"valid": False, "reason": "empty or non-finite declared ROI"}
    dark = float((detail <= CHECKER_DARK_MAX).mean())
    bright = float((detail >= CHECKER_BRIGHT_MIN).mean())
    flat_energy = gradient_energy(reference, DECLARED_REGIONS["flat"])
    ok = (dark >= CHECKER_MIN_FRACTION and bright >= CHECKER_MIN_FRACTION
          and np.isfinite(flat_energy) and flat_energy <= FLAT_MAX_GRADIENT_ENERGY)
    return ok, {"valid": True, "checker_dark_fraction": dark,
                "checker_bright_fraction": bright, "flat_gradient_energy": flat_energy,
                "checker_dark_max": CHECKER_DARK_MAX, "checker_bright_min": CHECKER_BRIGHT_MIN,
                "checker_min_fraction": CHECKER_MIN_FRACTION,
                "flat_max_gradient_energy": FLAT_MAX_GRADIENT_ENERGY}


def adaptive_effect_ok(
        adaptive_off: np.ndarray, adaptive_on: np.ndarray,
        roi: tuple[float, float, float, float] = DECLARED_REGIONS["flat"],
) -> tuple[bool, dict]:
    """Adaptive-on must lower flat-region noise at the declared budget."""
    before = flat_region_noise(adaptive_off, roi)
    after = flat_region_noise(adaptive_on, roi)
    valid = np.isfinite(before) and np.isfinite(after)
    return bool(valid and after < before), {
        "valid": bool(valid), "flat_noise_off": before, "flat_noise_on": after}


def denoise_effect_ok(
        denoise_off: np.ndarray, denoise_on: np.ndarray,
        roi: tuple[float, float, float, float] = DECLARED_REGIONS["flat"],
) -> tuple[bool, dict]:
    """Denoise-on must lower residual noise after settle."""
    before = flat_region_noise(denoise_off, roi)
    after = flat_region_noise(denoise_on, roi)
    valid = np.isfinite(before) and np.isfinite(after)
    return bool(valid and after < before), {
        "valid": bool(valid), "residual_noise_off": before, "residual_noise_on": after}


def accuracy_safeguard_ok(actual: np.ndarray, reference: np.ndarray) -> tuple[bool, dict]:
    """Bias + detail checks so lower variance from blurring/bias cannot pass."""
    errors = {name: mean_relative_luminance_error(actual, reference, roi)
              for name, roi in DECLARED_REGIONS.items()}
    detail = detail_preservation_ratio(actual, reference, DECLARED_REGIONS["detail"])
    full_finite = bool(np.isfinite(np.asarray(actual)).all()
                       and np.isfinite(np.asarray(reference)).all())
    finite = full_finite and all(np.isfinite(v) for v in errors.values()) \
        and np.isfinite(detail)
    ok = (finite
          and max(errors.values()) <= MEAN_REL_ERROR_MAX
          and detail >= DETAIL_PRESERVATION_MIN)
    return ok, {"mean_rel_error": errors, "detail_preservation": detail,
                "valid": bool(finite),
                "mean_rel_error_max": MEAN_REL_ERROR_MAX,
                "detail_preservation_min": DETAIL_PRESERVATION_MIN}


def sample_count_aov_differs(off: np.ndarray, on: np.ndarray) -> tuple[bool, dict]:
    """The sample-count AOV must differ between adaptive off and on.

    A shape mismatch or non-finite data is INVALID (never a pass).
    """
    a = np.asarray(off, dtype=np.float64)
    b = np.asarray(on, dtype=np.float64)
    if a.shape != b.shape:
        return False, {"valid": False, "reason": "shape_mismatch",
                       "shape_off": list(a.shape), "shape_on": list(b.shape)}
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return False, {"valid": False, "reason": "non_finite"}
    differs = not np.allclose(a, b, rtol=0.0, atol=0.0)
    return differs, {"valid": True,
                     "max_abs_delta": float(np.max(np.abs(a - b))) if differs else 0.0}


def merge_status(statuses) -> str:
    """Aggregate per-check/per-backend statuses: error > red > unmeasured > green."""
    order = {"green": 0, "unmeasured": 1, "red": 2, "error": 3}
    worst = "green"
    for status in statuses:
        if order.get(status, 3) > order[worst]:
            worst = status
    return worst


# --------------------------------------------------------------------------- #
# Pure unit tests (synthetic; run without Blender/GPU)
# --------------------------------------------------------------------------- #

def _noisy(base: float, seed: int, size: int = 64) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (base + rng.normal(0, 0.03, (size, size, 3))).astype(np.float32)


def _detailed(seed: int = 1, size: int = 64) -> np.ndarray:
    """A checker pattern with real edge energy plus light noise."""
    yy, xx = np.mgrid[0:size, 0:size]
    checker = (((xx // 8) + (yy // 8)) % 2).astype(np.float32)[..., None]
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.01, (size, size, 1)).astype(np.float32)
    return (checker + noise).astype(np.float32) * np.ones(3, np.float32)


def _split_reference(seed: int = 1, size: int = 64) -> np.ndarray:
    """Synthetic converged reference matching the declared ROIs: a featureless
    left half (flat region) and a high-contrast checker right half (detail)."""
    yy, xx = np.mgrid[0:size, 0:size]
    checker = (((xx // 8) + (yy // 8)) % 2).astype(np.float32)
    img = np.full((size, size, 3), 0.5, np.float32)
    img[:, size // 2:, 0] = checker[:, size // 2:]
    img[:, size // 2:, 1] = checker[:, size // 2:]
    img[:, size // 2:, 2] = checker[:, size // 2:]
    rng = np.random.default_rng(seed)
    return (img + rng.normal(0, 0.003, img.shape)).astype(np.float32)


def _box_blur(img: np.ndarray, k: int = 5) -> np.ndarray:
    """Separable box blur (no scipy dependency)."""
    pad = k // 2
    p = np.pad(np.asarray(img, np.float64), ((pad, pad), (pad, pad), (0, 0)),
               mode="reflect")
    out = np.zeros_like(np.asarray(img, np.float64))
    for dy in range(k):
        for dx in range(k):
            out += p[dy:dy + img.shape[0], dx:dx + img.shape[1]]
    return (out / (k * k)).astype(np.float32)


def test_flat_region_noise_lower_for_cleaner_image():
    noisy = _noisy(0.5, 1)
    clean = np.full((64, 64, 3), 0.5, np.float32)
    assert flat_region_noise(clean) < flat_region_noise(noisy)


def test_adaptive_effect_ok_direction():
    off = _noisy(0.5, 2)
    on = np.full((64, 64, 3), 0.5, np.float32)  # adaptive converged the flat area
    ok, stats = adaptive_effect_ok(off, on)
    assert ok and stats["flat_noise_on"] < stats["flat_noise_off"]
    # A no-op adaptive must fail the effect direction.
    ok2, _ = adaptive_effect_ok(off, off.copy())
    assert not ok2


def test_denoise_effect_ok_direction():
    off = _noisy(0.5, 3)
    on = np.full((64, 64, 3), 0.5, np.float32)
    ok, stats = denoise_effect_ok(off, on)
    assert ok and stats["residual_noise_on"] < stats["residual_noise_off"]
    ok2, _ = denoise_effect_ok(off, off.copy())
    assert not ok2


def test_accuracy_safeguard_rejects_biased_flat_output():
    reference = _detailed(seed=4)
    # Biased everywhere by 10 % -> mean relative error blows the 2 % bound.
    biased = (reference * 1.10).astype(np.float32)
    ok, stats = accuracy_safeguard_ok(biased, reference)
    assert not ok and max(stats["mean_rel_error"].values()) > MEAN_REL_ERROR_MAX


def test_accuracy_safeguard_rejects_blurred_output():
    reference = _detailed(seed=5)
    # A real box blur kills gradient energy while keeping the mean -> detail fails.
    blurred = _box_blur(reference, 5)
    ok, stats = accuracy_safeguard_ok(blurred, reference)
    assert not ok and stats["detail_preservation"] < DETAIL_PRESERVATION_MIN


def test_accuracy_safeguard_accepts_identical_and_low_noise():
    reference = _detailed(seed=6)
    ok, _ = accuracy_safeguard_ok(reference.copy(), reference)
    assert ok
    rng = np.random.default_rng(7)
    low_noise = (reference + rng.normal(0, 0.002, reference.shape)).astype(np.float32)
    ok2, _ = accuracy_safeguard_ok(low_noise, reference)
    assert ok2


def test_accuracy_safeguard_rejects_zero_detail_reference():
    """A zero-detail reference is INVALID, never +inf success."""
    reference = np.full((64, 64, 3), 0.5, np.float32)
    actual = np.full((64, 64, 3), 0.5, np.float32)
    ok, stats = accuracy_safeguard_ok(actual, reference)
    assert not ok and not np.isfinite(stats["detail_preservation"])
    # The vacuity helper also flags it.
    vacuous, vac_stats = reference_nonvacuous(reference)
    assert not vacuous and vac_stats["detail_gradient_energy"] <= DETAIL_ENERGY_FLOOR


def test_reference_regions_require_the_authored_checker_and_flat_controls():
    reference = _split_reference(seed=41)
    assert reference_regions_identified(reference)[0]
    flat = np.full_like(reference, 0.5)
    assert not reference_regions_identified(flat)[0]


def test_accuracy_safeguard_rejects_non_finite():
    reference = _detailed(seed=8)
    broken = reference.copy()
    broken[10, 10, 0] = np.inf
    ok, stats = accuracy_safeguard_ok(broken, reference)
    assert not ok and not stats["valid"]


def test_sample_count_aov_differs():
    a = np.ones((8, 8), np.float32) * 16
    b = np.ones((8, 8), np.float32) * 64
    assert sample_count_aov_differs(a, b)[0]
    assert not sample_count_aov_differs(a, a.copy())[0]


def test_sample_count_aov_shape_mismatch_is_invalid():
    a = np.ones((8, 8), np.float32)
    b = np.ones((8, 4), np.float32)
    ok, stats = sample_count_aov_differs(a, b)
    assert not ok and stats["valid"] is False and stats["reason"] == "shape_mismatch"


def test_sample_count_aov_non_finite_is_invalid():
    a = np.ones((8, 8), np.float32)
    b = np.ones((8, 8), np.float32)
    b[0, 0] = np.nan
    ok, stats = sample_count_aov_differs(a, b)
    assert not ok and stats["valid"] is False and stats["reason"] == "non_finite"


def test_declared_regions_are_disjoint_and_in_unit_square():
    for name, roi in DECLARED_REGIONS.items():
        x0, y0, x1, y1 = roi
        assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0, name
    flat, detail = DECLARED_REGIONS["flat"], DECLARED_REGIONS["detail"]
    assert flat[2] <= detail[0], "flat/detail ROIs must not overlap in x"


def test_resolve_region_is_top_down():
    """y=0 selects the TOP rows, not the bottom (top-down convention)."""
    img = np.zeros((10, 10, 3), np.float32)
    img[:3] = 1.0   # top band
    top = resolve_region(img, (0.0, 0.0, 1.0, 0.3))
    bottom = resolve_region(img, (0.0, 0.7, 1.0, 1.0))
    assert float(np.mean(top)) == pytest.approx(1.0)
    assert float(np.mean(bottom)) == pytest.approx(0.0)


def test_fixed_budget_is_declared_and_positive():
    assert ADAPTIVE_BUDGET_SAMPLES > 0
    assert REFERENCE_SAMPLES > ADAPTIVE_BUDGET_SAMPLES
    assert DENOISE_SETTLE_SAMPLES > 0
    assert 0.0 < MEAN_REL_ERROR_MAX < 1.0
    assert 0.0 < DETAIL_PRESERVATION_MIN <= 1.0


# --------------------------------------------------------------------------- #
# Pure host-side record evaluation (no bpy) - also unit-tested below.
# --------------------------------------------------------------------------- #

def evaluate_backend(backend: str, legs: dict, arrays: dict, aov: dict,
                     declared: dict | None = None) -> dict:
    """Evaluate one backend's legs into a typed per-backend record.

    ``legs``   name -> per-leg metadata (native/resolved settings, artifact hash)
    ``arrays`` name -> HxWx3 top-down linear array (or None if missing)
    ``aov``    {"present": bool, "reason": str|None, "off": arr|None, "on": arr|None}
    """
    declared = declared or {}
    checks: dict = {}

    def record(name: str, passed: bool, status: str, stats: dict):
        checks[name] = {"backend": backend, "check": name, "passed": bool(passed),
                        "status": status, "stats": stats}

    # --- finiteness of every rendered leg ---------------------------------
    missing = [n for n in LEG_NAMES if arrays.get(n) is None]
    non_finite = [n for n in LEG_NAMES
                  if arrays.get(n) is not None
                  and not np.isfinite(np.asarray(arrays[n])).all()]
    record("finite", not missing and not non_finite,
           "green" if (not missing and not non_finite) else "error",
           {"missing_legs": missing, "non_finite_legs": non_finite})

    # --- native panels actually drive the resolved settings ----------------
    ignored = []
    for leg in LEG_NAMES:
        meta = legs.get(leg, {})
        native = meta.get("native", {})
        resolved = meta.get("resolved", {})
        for key in NATIVE_PANEL_SETTINGS:
            if key in native and key in resolved and native[key] != resolved[key]:
                ignored.append({"leg": leg, "setting": key,
                                "native": native[key], "resolved": resolved[key]})
    record("native_settings_honored", not ignored,
           "green" if not ignored else "red",
           {"ignored_native_settings": ignored})

    observed_devices = []
    for leg in legs.values():
        for info in leg.get("output_telemetry", []) or []:
            value = info.get("device", info.get("device_mode", info.get("backend")))
            if isinstance(value, str):
                value = value.lower()
                observed_devices.append("gpu" if "gpu" in value or "cuda" in value else
                                        ("cpu" if "cpu" in value else None))
            elif isinstance(value, (int, float)):
                observed_devices.append("gpu" if value >= 0 else "cpu")
    observed_devices = [d for d in observed_devices if d is not None]
    device_ok = bool(observed_devices) and all(d == backend for d in observed_devices)
    record("actual_backend_provenance", device_ok,
           "green" if device_ok else "unmeasured",
           {"expected": backend, "observed": observed_devices,
            "reason": None if observed_devices else "write_pixels recorded no usable last_render_info device"})

    # --- reference must be converged AND non-vacuous -----------------------
    ref = arrays.get("reference")
    if ref is None:
        record("reference_nonvacuous", False, "unmeasured",
               {"reason": "reference artifact missing"})
    else:
        ok, stats = reference_nonvacuous(ref)
        record("reference_nonvacuous", ok, "green" if ok else "red", stats)
        ok, stats = reference_regions_identified(ref)
        record("reference_regions_identified", ok, "green" if ok else "red", stats)

    # --- adaptive effect + accuracy safeguard ------------------------------
    a_off, a_on = arrays.get("adaptive_off"), arrays.get("adaptive_on")
    if a_off is None or a_on is None:
        record("adaptive_effect", False, "unmeasured", {"reason": "leg artifact missing"})
    else:
        ok, stats = adaptive_effect_ok(a_off, a_on)
        record("adaptive_effect", ok, "green" if ok else "red", stats)
    if a_on is None or ref is None:
        record("adaptive_accuracy", False, "unmeasured", {"reason": "leg artifact missing"})
    else:
        ok, stats = accuracy_safeguard_ok(a_on, ref)
        record("adaptive_accuracy", ok, "green" if ok else "red", stats)

    # --- denoise effect + accuracy safeguard -------------------------------
    d_off, d_on = arrays.get("denoise_off"), arrays.get("denoise_on")
    if d_off is None or d_on is None:
        record("denoise_effect", False, "unmeasured", {"reason": "leg artifact missing"})
    else:
        ok, stats = denoise_effect_ok(d_off, d_on)
        record("denoise_effect", ok, "green" if ok else "red", stats)
    if d_on is None or ref is None:
        record("denoise_accuracy", False, "unmeasured", {"reason": "leg artifact missing"})
    else:
        ok, stats = accuracy_safeguard_ok(d_on, ref)
        record("denoise_accuracy", ok, "green" if ok else "red", stats)

    # --- sample-count AOV ---------------------------------------------------
    if aov.get("capture_invalid"):
        record("sample_count_aov_changes", False, "unmeasured",
               {"reason": aov.get("reason") or "sample-count capture invalid",
                "captures": aov.get("captures", {})})
    elif not aov.get("present"):
        record("sample_count_aov_changes", False, "red",
               {"reason": aov.get("reason") or "sample-count AOV not exposed by the engine",
                "attempted": aov.get("attempted", []),
                "passes_seen": aov.get("passes_seen", [])})
    else:
        ok, stats = sample_count_aov_differs(aov.get("off"), aov.get("on"))
        record("sample_count_aov_changes", ok, "green" if ok else "red", stats)

    status = merge_status(c["status"] for c in checks.values())
    return {
        "backend": backend,
        "status": status,
        "legs": legs,
        "checks": checks,
        "declared": declared,
    }


def test_evaluate_backend_green_on_synthetic_effect():
    """The record builder marks a genuine effect GREEN (no bpy needed)."""
    ref = _split_reference(seed=11, size=64)
    rng = np.random.default_rng(12)
    legs = {n: {"native": {"samples": 64, "use_adaptive_sampling": n.startswith("adaptive"),
                           "use_denoising": n == "denoise_on"},
                "resolved": {"samples": 64, "use_adaptive_sampling": n.startswith("adaptive"),
                             "use_denoising": n == "denoise_on"},
                "output_telemetry": [{"device": -1}]}
            for n in LEG_NAMES}
    noisy = (ref + rng.normal(0, 0.05, ref.shape)).astype(np.float32)
    arrays = {
        "adaptive_off": noisy.copy(),
        "adaptive_on": ref.copy(),
        "denoise_off": noisy.copy(),
        "denoise_on": (ref + rng.normal(0, 0.001, ref.shape)).astype(np.float32),
        "reference": ref,
    }
    aov = {"present": True, "off": np.ones((8, 8)), "on": np.ones((8, 8)) * 64}
    rec = evaluate_backend("cpu", legs, arrays, aov)
    assert rec["status"] == "green", rec["checks"]
    assert rec["checks"]["sample_count_aov_changes"]["passed"]


def test_evaluate_backend_red_on_absent_effect_and_aov():
    """An absent effect / absent AOV is RED, never PASS."""
    ref = _detailed(seed=15, size=64)
    legs = {n: {"native": {"samples": 64, "use_adaptive_sampling": False,
                           "use_denoising": False},
                "resolved": {"samples": 64, "use_adaptive_sampling": False,
                             "use_denoising": False}}
            for n in LEG_NAMES}
    same = _noisy(0.5, 16)
    arrays = {n: (ref.copy() if n == "reference" else same.copy()) for n in LEG_NAMES}
    aov = {"present": False, "reason": "no sample-count pass registered"}
    rec = evaluate_backend("gpu", legs, arrays, aov)
    assert rec["status"] == "red"
    assert not rec["checks"]["adaptive_effect"]["passed"]
    assert not rec["checks"]["denoise_effect"]["passed"]
    assert not rec["checks"]["sample_count_aov_changes"]["passed"]
    assert rec["checks"]["sample_count_aov_changes"]["status"] == "red"


def test_evaluate_backend_flags_ignored_native_panel():
    """A native setting the engine does not read is recorded, not hidden."""
    ref = _detailed(seed=17, size=64)
    legs = {n: {"native": {"samples": 64, "use_adaptive_sampling": False,
                           "use_denoising": False},
                "resolved": {"samples": 64, "use_adaptive_sampling": True,
                             "use_denoising": False}}
            for n in LEG_NAMES}
    arrays = {n: (ref.copy() if n == "reference" else _noisy(0.5, 18)) for n in LEG_NAMES}
    rec = evaluate_backend("cpu", legs, arrays, {"present": False, "reason": "n/a"})
    honored = rec["checks"]["native_settings_honored"]
    assert not honored["passed"] and honored["status"] == "red"
    assert any(item["setting"] == "use_adaptive_sampling"
               for item in honored["stats"]["ignored_native_settings"])


def test_evaluate_backend_marks_invalid_aov_capture_unmeasured():
    ref = _split_reference(seed=42)
    legs = {n: {"native": {"samples": 64, "use_adaptive_sampling": n.startswith("adaptive"),
                           "use_denoising": n == "denoise_on"},
                "resolved": {"samples": 64, "use_adaptive_sampling": n.startswith("adaptive"),
                             "use_denoising": n == "denoise_on"}}
            for n in LEG_NAMES}
    record = evaluate_backend("cpu", legs, {n: ref.copy() for n in LEG_NAMES},
                              {"present": False, "capture_invalid": True,
                               "reason": "end_result was not called",
                               "captures": {"adaptive_off": {"valid": False}}})
    check = record["checks"]["sample_count_aov_changes"]
    assert check["status"] == "unmeasured" and not check["passed"]


def test_instance_bound_rna_end_result_can_be_captured_from_write_pixels():
    """RenderEngine-style methods can exist only on a live instance.

    This mirrors Blender RNA: the subclass has no ``end_result`` attribute,
    while its instance obtains the native delegate dynamically. The write hook
    must capture that delegate before temporarily shadowing it on the subclass.
    """
    calls = []

    class RnaEngine:
        def __getattr__(self, name):
            if name == "end_result":
                return lambda result: calls.append(("native", result))
            raise AttributeError(name)

    class Engine(RnaEngine):
        def write_pixels(self):
            self.end_result("render-result")

    assert not hasattr(Engine, "end_result")
    original_write = Engine.write_pixels

    def capture_write(self):
        bound_end = self.end_result

        def capture_end(_engine, result):
            calls.append(("capture", result))
            return bound_end(result)

        marker = object()
        previous = Engine.__dict__.get("end_result", marker)
        Engine.end_result = capture_end
        try:
            return original_write(self)
        finally:
            if previous is marker:
                delattr(Engine, "end_result")
            else:
                Engine.end_result = previous

    Engine.write_pixels = capture_write
    Engine().write_pixels()
    assert calls == [("capture", "render-result"), ("native", "render-result")]
    assert not hasattr(Engine, "end_result")


# --------------------------------------------------------------------------- #
# In-Blender leg script (host pytest NEVER imports bpy; this runs inside Blender)
# --------------------------------------------------------------------------- #

_LEG_SCRIPT = r'''
import argparse
import hashlib
import json
import sys
import traceback
import uuid
from pathlib import Path

SENTINEL = "GATE_D_LEG"


def _fail(reason):
    print(SENTINEL + " FAIL " + str(reason), flush=True)
    sys.exit(0)  # sentinel, not exit code, is the source of truth


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _diffuse_mat(bpy, name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Roughness"].default_value = 0.9
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def _checker_mat(bpy, name, scale):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.9
    checker = nt.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = scale
    checker.inputs["Color1"].default_value = (0.04, 0.04, 0.04, 1.0)
    checker.inputs["Color2"].default_value = (0.9, 0.9, 0.9, 1.0)
    nt.links.new(checker.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def _build_scene(bpy):
    """Deterministic floor scene: flat (featureless) left half, checker right
    half, area light above/front, camera looking forward-and-down. The camera is
    centred on the split, so the left image half lands on the flat plane and the
    right half on the checker (declared top-down ROIs)."""
    import math
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(-5.0, 0.0, 0.0))
    flat = bpy.context.object
    flat.scale = (10.0, 20.0, 1.0)
    flat.data.materials.append(_diffuse_mat(bpy, "GateDFlat", (0.6, 0.6, 0.6)))

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(5.0, 0.0, 0.0))
    chk = bpy.context.object
    chk.scale = (10.0, 20.0, 1.0)
    chk.data.materials.append(_checker_mat(bpy, "GateDChecker", 20.0))

    ld = bpy.data.lights.new("GateDLight", type="AREA")
    ld.energy = 600.0
    ld.size = 0.5
    light = bpy.data.objects.new("GateDLight", ld)
    light.location = (1.0, -2.0, 4.0)
    light.rotation_euler = (0.0, 0.0, 0.0)
    scene.collection.objects.link(light)

    cam_data = bpy.data.cameras.new("GateDCam")
    cam = bpy.data.objects.new("GateDCam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -6.0, 1.5)
    cam.rotation_euler = (math.radians(78.0), 0.0, 0.0)
    scene.camera = cam

    world = bpy.data.worlds.new("GateDWorld")
    world.use_nodes = False
    world.color = (0.0, 0.0, 0.0)
    scene.world = world

    scene.render.resolution_x = 128
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.exr_codec = "NONE"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    return scene


def _scene_manifest(scene):
    cam = scene.camera
    light = next((o for o in scene.objects if o.type == "LIGHT"), None)
    return {
        "resolution": [int(scene.render.resolution_x), int(scene.render.resolution_y)],
        "camera_location": [float(v) for v in cam.location],
        "camera_rotation_euler": [float(v) for v in cam.rotation_euler],
        "light_location": [float(v) for v in light.location] if light else None,
        "light_energy": float(light.data.energy) if light else None,
        "light_size": float(getattr(light.data, "size", 0.0)) if light else None,
        "view_transform": str(scene.view_settings.view_transform),
        "exposure": float(scene.view_settings.exposure),
        "gamma": float(scene.view_settings.gamma),
        "film_transparent": bool(scene.render.film_transparent),
    }


def _render_leg(bpy, scene, out_dir, stem, engine_cls):
    """Render one leg through the real F12 path and return the top-down linear
    HxWx3 array (or None + error)."""
    import numpy as np
    path = out_dir / (stem + ".exr")
    path.unlink(missing_ok=True)
    capture = {"end_result_calls": 0, "write_pixels_calls": 0,
               "passes": [], "telemetry": [], "valid": False,
               "reason": None, "sample_count": None}
    orig_write = engine_cls.write_pixels

    def capture_write(self, pixels, width, height, alpha=None, renderer=None,
                      view_layer=None, scene=None, layer_name=None):
        capture["write_pixels_calls"] += 1
        if renderer is not None:
            try:
                capture["telemetry"].append(dict(renderer.last_render_info() or {}))
            except Exception as exc:  # noqa: BLE001
                capture["telemetry"].append({"last_render_info_error": repr(exc)})

        # Blender exposes end_result through the live RenderEngine instance,
        # not as a normal attribute on CustomRaytracerRenderEngine or its RNA
        # base type. Capture that bound delegate first, then temporarily shadow
        # it on the Python subclass while write_pixels creates and ends result.
        # This preserves the exact instance delegate Blender supplied.
        try:
            bound_end = self.end_result
        except Exception as exc:  # noqa: BLE001
            capture["reason"] = "cannot obtain instance end_result: %r" % (exc,)
            return orig_write(self, pixels, width, height, alpha=alpha, renderer=renderer,
                              view_layer=view_layer, scene=scene, layer_name=layer_name)

        def capture_end(_engine, result):
            capture["end_result_calls"] += 1
            try:
                for layer in result.layers:
                    for render_pass in layer.passes:
                        name = str(getattr(render_pass, "name", ""))
                        channels = int(getattr(render_pass, "channels", 0))
                        rect = np.asarray(render_pass.rect[:], dtype=np.float32)
                        capture["passes"].append({"layer": str(getattr(layer, "name", "")),
                                                   "name": name, "channels": channels,
                                                   "rect_len": int(rect.size)})
                        if name == "__SAMPLE_COUNT_PASS__":
                            capture["sample_count"] = {"channels": channels,
                                                       "rect": rect.copy()}
            except Exception as exc:  # noqa: BLE001
                capture["reason"] = "end_result capture failed: %r" % (exc,)
            return bound_end(result)

        marker = object()
        previous_end = engine_cls.__dict__.get("end_result", marker)
        engine_cls.end_result = capture_end
        try:
            return orig_write(self, pixels, width, height, alpha=alpha, renderer=renderer,
                              view_layer=view_layer, scene=scene, layer_name=layer_name)
        finally:
            if previous_end is marker:
                delattr(engine_cls, "end_result")
            else:
                engine_cls.end_result = previous_end

    engine_cls.write_pixels = capture_write
    try:
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    finally:
        engine_cls.write_pixels = orig_write
    capture["valid"] = capture["end_result_calls"] > 0 and capture["reason"] is None
    if not capture["valid"]:
        capture["reason"] = capture["reason"] or "end_result was not called"
    if not path.is_file():
        return None, None, "no EXR produced for stem %s" % stem, capture
    img = bpy.data.images.load(str(path))
    try:
        w, h = int(img.size[0]), int(img.size[1])
        if w <= 0 or h <= 0:
            return None, path, "rendered image has empty size"
        px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        arr = np.ascontiguousarray(px[::-1, :, :3])  # bottom-up -> top-down, once
    finally:
        bpy.data.images.remove(img)
    return arr, path, None, capture


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True)
    p.add_argument("--backend", required=True, choices=["cpu", "gpu"])
    p.add_argument("--repo-root", required=True)
    args = p.parse_args(argv)

    import numpy as np
    import bpy

    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    addon_dir = __import__("os").environ.get("ASTRORAY_SMOKE_ADDON_DIR")
    if not addon_dir or not Path(addon_dir).is_dir():
        _fail("ASTRORAY_SMOKE_ADDON_DIR is unset or missing; refusing the "
              "dev-tree fallback (exact engine/build provenance required)")

    # Reuse the ONE canonical addon bootstrap (no duplicate registration path).
    import verify_pkg175_smoke_blender as smoke
    astroray, addon = smoke._bootstrap()

    if not hasattr(addon, "CustomRaytracerRenderEngine"):
        _fail("addon registered but CustomRaytracerRenderEngine is missing")

    engine_id = "CUSTOM_RAYTRACER"
    scene = _build_scene(bpy)
    try:
        scene.render.engine = engine_id
    except TypeError as exc:
        _fail("engine %r is not registered: %s" % (engine_id, exc))
    if str(scene.render.engine) != engine_id:
        _fail("engine did not stick (got %r, want %r) - refusing to render on a "
              "default/fallback engine" % (str(scene.render.engine), engine_id))

    if not hasattr(scene, "custom_raytracer"):
        _fail("scene.custom_raytracer missing - addon registration incomplete")
    if not hasattr(scene, "cycles"):
        _fail("scene.cycles missing - native Cycles panels are unavailable")

    build = {
        "engine_id": engine_id,
        "build_id": str(getattr(astroray, "__build__", "")),
        "version": str(getattr(astroray, "__version__", "")),
        "astroray_module": str(getattr(astroray, "__file__", "")),
        "addon_dir": str(Path(addon_dir).resolve()),
        "addon_init": str(getattr(addon, "__file__", "")),
        "blender_version": str(bpy.app.version_string),
        "blender_binary": str(bpy.app.binary_path),
    }
    build["module_sha256"] = _sha256(Path(build["astroray_module"])) \
        if Path(build["astroray_module"]).is_file() else None
    build["addon_init_sha256"] = _sha256(Path(build["addon_init"])) \
        if Path(build["addon_init"]).is_file() else None
    if not build["build_id"] or not build["module_sha256"] or not build["addon_init_sha256"]:
        _fail("missing build identity or hash; refusing unproven runtime provenance")

    # Backend selection uses the addon's SUPPORTED device selector only.
    try:
        scene.custom_raytracer.device_mode = args.backend
    except (TypeError, AttributeError) as exc:
        _fail("cannot set custom_raytracer.device_mode=%r: %s" % (args.backend, exc))

    probe = astroray.Renderer()
    gpu_available = bool(getattr(probe, "gpu_available", False))
    del probe
    build["gpu_available"] = gpu_available

    legs_meta = {}
    artifacts = {}

    if args.backend == "gpu" and not gpu_available:
        record = {
            "schema_version": __SCHEMA_VERSION__,
            "instrument": "gate_native_panels",
            "backend": args.backend,
            "status": "unmeasured",
            "reason": "no CUDA GPU available for the gpu backend",
            "build": build,
            "scene": _scene_manifest(scene),
            "scene_sha256": hashlib.sha256(
                json.dumps(_scene_manifest(scene), sort_keys=True).encode("utf-8")).hexdigest(),
            "legs": {},
            "checks": {},
            "artifacts": {},
        }
        _write_json(out_dir / ("legs_" + args.backend + ".json"), record)
        print(SENTINEL + " PASS", flush=True)
        return

    specs = [
        ("adaptive_off", False, False, __ADAPTIVE_BUDGET__),
        ("adaptive_on", True, False, __ADAPTIVE_BUDGET__),
        ("denoise_off", False, False, __DENOISE_SETTLE__),
        ("denoise_on", False, True, __DENOISE_SETTLE__),
        ("reference", False, False, __REFERENCE__),
    ]

    run_id = uuid.uuid4().hex
    aov_captures = {}
    aov_arrays = {}
    for name, adaptive, denoise, samples in specs:
        # NATIVE PANEL ONLY: samples / adaptive / denoise come exclusively from
        # scene.cycles.*. The custom_raytracer duplicates are never written here.
        scene.cycles.samples = int(samples)
        scene.cycles.use_adaptive_sampling = bool(adaptive)
        scene.cycles.use_denoising = bool(denoise)

        resolved = addon.resolve_native_settings(scene)
        arr, exr_path, err, capture = _render_leg(
            bpy, scene, out_dir, run_id + "_" + args.backend + "_" + name,
            addon.CustomRaytracerRenderEngine)
        if err:
            _fail("%s/%s: %s" % (args.backend, name, err))

        stem = args.backend + "_" + name
        npy_path = out_dir / (run_id + "_" + stem + ".npy")
        np.save(npy_path, arr)
        artifacts[str(npy_path.name)] = {
            "path": str(npy_path),
            "sha256": _sha256(npy_path),
            "kind": "linear_topdown_npy",
            "shape": [int(v) for v in arr.shape],
        }
        if exr_path is not None and Path(exr_path).exists():
            artifacts[Path(exr_path).name] = {
                "path": str(exr_path),
                "sha256": _sha256(exr_path),
                "kind": "linear_exr",
            }

        lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
        legs_meta[name] = {
            "backend": args.backend,
            "leg": name,
            "artifact": npy_path.name,
            "sha256": artifacts[npy_path.name]["sha256"],
            "shape": [int(v) for v in arr.shape],
            "finite": bool(np.isfinite(arr).all()),
            "mean_luminance": float(lum.mean()),
            "native": {
                "samples": int(scene.cycles.samples),
                "use_adaptive_sampling": bool(scene.cycles.use_adaptive_sampling),
                "use_denoising": bool(scene.cycles.use_denoising),
            },
            "resolved": {
                "samples": int(resolved.samples),
                "use_adaptive_sampling": bool(resolved.use_adaptive_sampling),
                "use_denoising": bool(resolved.use_denoising),
                "device_mode": str(resolved.device_mode),
            },
            "rendered": True,
            "error": None,
            "output_telemetry": capture["telemetry"],
        }

        if name in ("adaptive_off", "adaptive_on"):
            aov_info = {k: v for k, v in capture.items() if k != "sample_count"}
            sample = capture.get("sample_count")
            if sample is None:
                aov_info["present"] = False
                aov_info["reason"] = (aov_info.get("reason") if not capture["valid"]
                                      else "exact sample-count pass not registered")
            else:
                channels = int(sample["channels"] or 0)
                rect = np.asarray(sample["rect"], dtype=np.float32)
                expected = int(arr.shape[0]) * int(arr.shape[1]) * channels
                if channels <= 0 or rect.size != expected:
                    aov_info.update({"present": False, "valid": False,
                                     "reason": "sample-count pass rect shape invalid"})
                else:
                    aov_arr = rect.reshape(arr.shape[0], arr.shape[1], channels)[::-1].copy()
                    aov_info["present"] = True
                    aov_info["reason"] = None
            aov_captures[name] = aov_info
            if aov_info.get("present"):
                aov_path = out_dir / (run_id + "_" + args.backend + "_aov_" + name + ".npy")
                np.save(aov_path, aov_arr)
                artifacts[aov_path.name] = {
                    "path": str(aov_path),
                    "sha256": _sha256(aov_path),
                    "kind": "sample_count_aov",
                    "shape": [int(v) for v in aov_arr.shape],
                }
                aov_arrays[name] = {
                    "artifact": aov_path.name,
                    "sha256": artifacts[aov_path.name]["sha256"],
                }

    scene_manifest = _scene_manifest(scene)
    record = {
        "schema_version": __SCHEMA_VERSION__,
        "instrument": "gate_native_panels",
        "backend": args.backend,
        "status": "measured",
        "build": build,
        "scene": scene_manifest,
        "scene_sha256": hashlib.sha256(
            json.dumps(scene_manifest, sort_keys=True).encode("utf-8")).hexdigest(),
        "legs": legs_meta,
        "run_id": run_id,
        "aov": {"captures": aov_captures, "artifacts": aov_arrays},
        "artifacts": artifacts,
    }
    _write_json(out_dir / ("legs_" + args.backend + ".json"), record)
    print(SENTINEL + " PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        _fail("%s: %s" % (type(exc).__name__, exc))
'''.replace("__SCHEMA_VERSION__", str(SCHEMA_VERSION)) \
   .replace("__ADAPTIVE_BUDGET__", str(ADAPTIVE_BUDGET_SAMPLES)) \
   .replace("__DENOISE_SETTLE__", str(DENOISE_SETTLE_SAMPLES)) \
   .replace("__REFERENCE__", str(REFERENCE_SAMPLES)) \
   .replace("__SAMPLE_COUNT_PASS__", SAMPLE_COUNT_PASS_NAME)


# --------------------------------------------------------------------------- #
# Host-side native-leg orchestration
# --------------------------------------------------------------------------- #

def _find_blender():
    explicit = os.environ.get(_BLENDER_ENV, "")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    for candidate in (
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


def _requested_backends() -> list[str]:
    raw = os.environ.get(_BACKENDS_ENV, "cpu,gpu")
    backends = [b.strip().lower() for b in raw.split(",") if b.strip()]
    unknown = [b for b in backends if b not in ("cpu", "gpu")]
    if unknown:
        raise ValueError(f"unknown backend(s) in {_BACKENDS_ENV}: {unknown}")
    return backends or ["cpu", "gpu"]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_native_backend(blender: Path, addon_dir: Path, out_dir: Path,
                        backend: str, leg_script: Path) -> dict:
    """Spawn isolated headless Blender, return its parsed legs_<backend>.json."""
    env = os.environ.copy()
    env[_ADDON_ENV] = str(addon_dir)
    cmd = [
        str(blender), "--background", "--factory-startup",
        "--python", str(leg_script), "--",
        "--out-dir", str(out_dir),
        "--backend", backend,
        "--repo-root", str(REPO_ROOT),
    ]
    print(f"\n[gate_d_native] running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=1800, check=False)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if f"GATE_D_LEG FAIL" in out or f"GATE_D_LEG PASS" not in out:
        tail = "\n".join(out.strip().splitlines()[-25:])
        raise RuntimeError(f"native leg did not PASS for backend {backend!r}:\n{tail}")
    print("\n".join(out.strip().splitlines()[-12:]))

    legs_path = out_dir / f"legs_{backend}.json"
    if not legs_path.is_file():
        raise RuntimeError(f"native leg wrote no {legs_path.name}")
    return json.loads(legs_path.read_text(encoding="utf-8"))


def _host_evaluate_backend(raw: dict, out_dir: Path) -> dict:
    """Read raw artifacts, verify hashes, and build the typed per-backend record."""
    backend = raw["backend"]
    if raw.get("status") == "unmeasured":
        return {"backend": backend, "status": "unmeasured",
                "reason": raw.get("reason"), "build": raw.get("build"),
                "scene_sha256": raw.get("scene_sha256"), "legs": {}, "checks": {},
                "artifacts": {}}

    build = raw.get("build") or {}
    required_build = ("build_id", "engine_id", "module_sha256", "addon_init_sha256")
    missing_build = [key for key in required_build if not isinstance(build.get(key), str)
                     or not build[key]]
    if build.get("engine_id") != ENGINE_ID:
        missing_build.append("engine_id=%r" % build.get("engine_id"))
    for key in ("module_sha256", "addon_init_sha256"):
        value = build.get(key)
        if isinstance(value, str) and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower())):
            missing_build.append(key + "(not sha256)")
    if missing_build:
        raise RuntimeError("measured backend lacks exact build provenance: " + ", ".join(missing_build))

    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("measured backend lacks run-specific artifact provenance")

    artifacts = raw.get("artifacts", {})
    for name, meta in artifacts.items():
        if not name.startswith(run_id + "_"):
            raise RuntimeError(f"artifact {name!r} is not bound to run {run_id!r}")
        path = out_dir / name
        if not path.is_file():
            raise RuntimeError(f"artifact {name!r} missing for backend {backend!r}")
        actual = _sha256_file(path)
        if meta.get("sha256") != actual:
            raise RuntimeError(
                f"artifact hash mismatch for {name!r} ({backend}): "
                f"recorded {meta.get('sha256')} != {actual}")

    arrays: dict = {}
    legs_meta: dict = {}
    for leg in LEG_NAMES:
        meta = raw["legs"].get(leg)
        if meta is None:
            arrays[leg] = None
            continue
        arr_path = out_dir / meta["artifact"]
        if not arr_path.is_file():
            raise RuntimeError(f"leg artifact {meta['artifact']!r} missing ({backend}/{leg})")
        arr = np.load(arr_path)
        if not np.isfinite(arr).all():
            raise RuntimeError(f"non-finite pixel data in {meta['artifact']!r} ({backend}/{leg})")
        arrays[leg] = arr
        legs_meta[leg] = {
            "backend": backend,
            "leg": leg,
            "artifact": meta["artifact"],
            "sha256": meta["sha256"],
            "shape": meta["shape"],
            "finite": meta["finite"],
            "mean_luminance": meta["mean_luminance"],
            "native": meta["native"],
            "resolved": meta["resolved"],
            "rendered": meta.get("rendered", True),
            "error": meta.get("error"),
            "output_telemetry": meta.get("output_telemetry", []),
        }

    aov_raw = raw.get("aov", {})
    captures = aov_raw.get("captures", {}) or {}
    aov_art = aov_raw.get("artifacts", {}) or {}
    required_captures = {name: captures.get(name) for name in ("adaptive_off", "adaptive_on")}
    invalid_capture = {name: cap for name, cap in required_captures.items()
                       if not isinstance(cap, dict) or not cap.get("valid")}
    missing_pass = {name: cap for name, cap in required_captures.items()
                    if isinstance(cap, dict) and cap.get("valid") and not cap.get("present")}
    aov = {"present": not invalid_capture and not missing_pass,
           "capture_invalid": bool(invalid_capture),
           "captures": required_captures,
           "reason": ("invalid end_result capture: " + ", ".join(invalid_capture)
                      if invalid_capture else
                      ("sample-count pass absent after valid capture: " + ", ".join(missing_pass)
                       if missing_pass else None))}
    if aov["present"] and "adaptive_off" in aov_art and "adaptive_on" in aov_art:
        aov["off"] = np.load(out_dir / aov_art["adaptive_off"]["artifact"])
        aov["on"] = np.load(out_dir / aov_art["adaptive_on"]["artifact"])
    else:
        aov["present"] = False

    declared = {
        "mean_rel_error_max": MEAN_REL_ERROR_MAX,
        "detail_preservation_min": DETAIL_PRESERVATION_MIN,
        "adaptive_budget_samples": ADAPTIVE_BUDGET_SAMPLES,
        "reference_samples": REFERENCE_SAMPLES,
        "denoise_settle_samples": DENOISE_SETTLE_SAMPLES,
        "regions": {k: list(v) for k, v in DECLARED_REGIONS.items()},
        "region_nonvacuity": {"checker_dark_max": CHECKER_DARK_MAX,
                                "checker_bright_min": CHECKER_BRIGHT_MIN,
                                "checker_min_fraction": CHECKER_MIN_FRACTION,
                                "flat_max_gradient_energy": FLAT_MAX_GRADIENT_ENERGY},
        "budget_note": ("equal max-spp is an upper bound on equal work: adaptive "
                        "sampling may retire pixels early; declared budgets and "
                        "resolved per-leg sample counts are recorded for audit"),
    }
    record = evaluate_backend(backend, legs_meta, arrays, aov, declared)
    record["build"] = raw.get("build")
    record["scene_sha256"] = raw.get("scene_sha256")
    record["run_id"] = raw.get("run_id")
    record["artifacts"] = {
        name: {"backend": backend, "path": str(out_dir / name),
               "sha256": meta["sha256"], "kind": meta.get("kind"),
               "shape": meta.get("shape")}
        for name, meta in artifacts.items()
    }
    return record


def _write_merged(out_dir: Path, backend_records: dict):
    """Write per-backend records plus a merged typed JSON (schema_version 1)."""
    merged_backends = {}
    all_artifacts = {}
    for backend, record in backend_records.items():
        (out_dir / f"gate_native_panels.{backend}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        merged_backends[backend] = record
        all_artifacts.update(record.get("artifacts", {}))

    # Merge any earlier per-backend runs already on disk (parent may run the
    # backends in separate invocations under the GPU lock).
    for path in out_dir.glob("gate_native_panels.*.json"):
        parts = path.name.split(".")
        if len(parts) != 3 or parts[2] != "json":
            continue
        backend = parts[1]
        if backend in merged_backends:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for name, meta in record.get("artifacts", {}).items():
            artifact = Path(meta.get("path", ""))
            if not artifact.is_file() or _sha256_file(artifact) != meta.get("sha256"):
                record["status"] = "error"
                record["artifact_error"] = f"stale or mismatched merged artifact: {name}"
        merged_backends[backend] = record
        all_artifacts.update(record.get("artifacts", {}))

    measured = [r for r in merged_backends.values() if r.get("status") != "unmeasured"]
    identities = {tuple((r.get("build") or {}).get(key)
                        for key in ("build_id", "engine_id", "module_sha256", "addon_init_sha256"))
                  for r in measured}
    builds = {identity[0] for identity in identities if identity[0]}
    scenes = {r.get("scene_sha256") for r in measured}
    run_ids = [r.get("run_id") for r in measured]
    status = merge_status(r.get("status", "error") for r in merged_backends.values())
    if len(identities) > 1 or len(scenes) > 1 or len(run_ids) != len(set(run_ids)):
        status = "error"
    if set(merged_backends) != {"cpu", "gpu"}:
        status = "unmeasured"
    merged = {
        "schema_version": SCHEMA_VERSION,
        "instrument": INSTRUMENT,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "engine_id": ENGINE_ID,
        "build_id": next(iter(builds)) if len(builds) == 1 else None,
        "status": status,
        "backends": merged_backends,
        "artifacts": all_artifacts,
        "declared": {
            "mean_rel_error_max": MEAN_REL_ERROR_MAX,
            "detail_preservation_min": DETAIL_PRESERVATION_MIN,
            "adaptive_budget_samples": ADAPTIVE_BUDGET_SAMPLES,
            "reference_samples": REFERENCE_SAMPLES,
            "denoise_settle_samples": DENOISE_SETTLE_SAMPLES,
            "regions": {k: list(v) for k, v in DECLARED_REGIONS.items()},
            "region_nonvacuity": {"checker_dark_max": CHECKER_DARK_MAX,
                                    "checker_bright_min": CHECKER_BRIGHT_MIN,
                                    "checker_min_fraction": CHECKER_MIN_FRACTION,
                                    "flat_max_gradient_energy": FLAT_MAX_GRADIENT_ENERGY},
        },
    }
    (out_dir / "gate_native_panels.json").write_text(
        json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
    return merged


# --------------------------------------------------------------------------- #
# Native test (explicitly opt-in; parent runs it under the shared GPU lock)
# --------------------------------------------------------------------------- #

@pytest.mark.serial
def test_gate_d_native_panels_effect():
    """Gate (d): native adaptive/denoise panels must change the output.

    Skipped unless explicitly opted in (``ASTRORAY_GATE_D_NATIVE=1``). When
    opted in, a missing Blender or addon dir is a FAILURE (never a silent skip),
    because the instrument was explicitly requested. A measured RED row is a
    valid result and is recorded, not asserted green.
    """
    if os.environ.get(_NATIVE_ENV) != "1":
        pytest.skip(
            "gate (d) native legs are explicitly opt-in. Parent runs them under "
            "the shared GPU lock with: ASTRORAY_GATE_D_NATIVE=1, "
            "ASTRORAY_SMOKE_ADDON_DIR=<staged addon>, "
            "ASTRORAY_GATE_D_BACKENDS=cpu|gpu, pytest -q "
            "tests/test_gate_native_panels.py (or -k gate_d_native_panels_effect; "
            "-k native also matches the pure tests because of the file name)")

    blender = _find_blender()
    if blender is None:
        pytest.fail(
            f"ASTRORAY_GATE_D_NATIVE=1 but no Blender found; set {_BLENDER_ENV} "
            "or install Blender (this is a runtime dependency, not a pass)")

    addon_dir = os.environ.get(_ADDON_ENV)
    if not addon_dir or not Path(addon_dir).is_dir():
        pytest.fail(
            f"ASTRORAY_GATE_D_NATIVE=1 but {_ADDON_ENV} is unset/missing; the "
            "staged addon dir is required for exact engine/build provenance")

    backends = _requested_backends()
    out_dir = Path(os.environ.get(_OUT_ENV, REPO_ROOT / "test_results" / "gate_native_panels"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Persist the in-Blender leg next to its artifacts for auditability.
    leg_script = out_dir / "gate_d_leg.py"
    leg_script.write_text(_LEG_SCRIPT, encoding="utf-8")

    backend_records: dict = {}
    for backend in backends:
        raw = _run_native_backend(blender, Path(addon_dir), out_dir, backend, leg_script)
        backend_records[backend] = _host_evaluate_backend(raw, out_dir)

    merged = _write_merged(out_dir, backend_records)
    out_json = out_dir / "gate_native_panels.json"
    print(f"\n[gate_d_native] wrote {out_json}")
    for backend, record in backend_records.items():
        print(f"[gate_d_native] {backend}: status={record['status']}")
        for name, check in record.get("checks", {}).items():
            print(f"    {name:28s} {check['status']:10s} passed={check['passed']}")

    # Instrument-validity gate (NOT a green-gate): every requested backend must
    # have produced a valid measurement; a measured RED row is recorded above.
    for backend in backends:
        record = backend_records[backend]
        assert record["status"] in ("green", "red", "unmeasured"), record["status"]
        if record["status"] == "unmeasured":
            continue
        for leg in LEG_NAMES:
            assert leg in record["legs"], f"{backend}: leg {leg!r} missing"
            assert record["legs"][leg]["rendered"], f"{backend}: leg {leg!r} not rendered"
        finite = record["checks"]["finite"]
        assert finite["passed"], f"{backend}: non-finite or missing legs {finite['stats']}"

    assert merged["schema_version"] == SCHEMA_VERSION
    assert merged["instrument"] == INSTRUMENT
    assert merged["status"] in ("green", "red", "unmeasured", "error")
    assert merged["status"] != "error", "instrument error - see per-backend records"


# --------------------------------------------------------------------------- #
# JSON contract smoke (pure; exercises the typed writer without Blender)
# --------------------------------------------------------------------------- #

def test_merged_json_contract(tmp_path):
    """The typed output carries the schema_version/instrument/records contract."""
    ref = _detailed(seed=21, size=64)
    legs = {n: {"backend": "cpu", "leg": n, "artifact": f"{n}.npy",
                "sha256": "0" * 64, "shape": [64, 64, 3], "finite": True,
                "mean_luminance": 0.4,
                "native": {"samples": 64, "use_adaptive_sampling": False,
                           "use_denoising": False},
                "resolved": {"samples": 64, "use_adaptive_sampling": False,
                             "use_denoising": False}}
            for n in LEG_NAMES}
    arrays = {n: (ref.copy() if n == "reference" else _noisy(0.5, 22)) for n in LEG_NAMES}
    record = evaluate_backend("cpu", legs, arrays, {"present": False, "reason": "n/a"})
    record["build"] = {"build_id": "test", "engine_id": ENGINE_ID}
    record["scene_sha256"] = "0" * 64
    record["artifacts"] = {"adaptive_off.npy": {"backend": "cpu", "path": "x",
                                                "sha256": "0" * 64,
                                                "kind": "linear_topdown_npy",
                                                "shape": [64, 64, 3]}}
    merged = _write_merged(tmp_path, {"cpu": record})
    assert merged["schema_version"] == 1
    assert merged["instrument"] == "gate_native_panels"
    assert "cpu" in merged["backends"]
    assert merged["backends"]["cpu"]["checks"]["sample_count_aov_changes"]["status"] == "red"
    for name in ("legs", "checks", "artifacts", "build", "scene_sha256"):
        assert name in merged["backends"]["cpu"]
    on_disk = json.loads((tmp_path / "gate_native_panels.json").read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 1
    assert on_disk["backends"]["cpu"]["checks"]["finite"]["passed"]


def test_host_evaluate_backend_reads_and_verifies_artifacts(tmp_path):
    """The host pipeline reads npy artifacts, verifies SHA-256, and records the
    sample-count AOV absence as RED (no Blender needed)."""
    ref = _split_reference(seed=31, size=64)
    rng = np.random.default_rng(32)
    noisy = (ref + rng.normal(0, 0.05, ref.shape)).astype(np.float32)
    arrays = {
        "adaptive_off": noisy,
        "adaptive_on": ref,
        "denoise_off": noisy,
        "denoise_on": (ref + rng.normal(0, 0.001, ref.shape)).astype(np.float32),
        "reference": ref,
    }
    run_id = "test-run"
    raw = {"backend": "cpu", "status": "measured", "run_id": run_id,
           "build": {"build_id": "test-build", "engine_id": ENGINE_ID,
                     "module_sha256": "a" * 64, "addon_init_sha256": "b" * 64},
           "scene_sha256": "abc", "legs": {}, "artifacts": {},
           "aov": {"captures": {
               "adaptive_off": {"valid": True, "present": False,
                                "reason": "exact sample-count pass not registered"},
               "adaptive_on": {"valid": True, "present": False,
                               "reason": "exact sample-count pass not registered"}},
                   "artifacts": {}}}
    for leg, arr in arrays.items():
        name = f"{run_id}_cpu_{leg}.npy"
        path = tmp_path / name
        np.save(path, arr)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        raw["artifacts"][name] = {"path": str(path), "sha256": digest,
                                  "kind": "linear_topdown_npy",
                                  "shape": list(arr.shape)}
        raw["legs"][leg] = {
            "backend": "cpu", "leg": leg, "artifact": name, "sha256": digest,
            "shape": list(arr.shape), "finite": True,
            "mean_luminance": float(luminance(arr).mean()),
            "native": {"samples": 64, "use_adaptive_sampling": leg.startswith("adaptive"),
                       "use_denoising": leg == "denoise_on"},
            "resolved": {"samples": 64, "use_adaptive_sampling": leg.startswith("adaptive"),
                         "use_denoising": leg == "denoise_on"},
            "rendered": True, "error": None,
        }
    record = _host_evaluate_backend(raw, tmp_path)
    assert record["status"] == "red"  # absent sample-count AOV, not PASS
    assert record["checks"]["finite"]["passed"]
    assert record["checks"]["adaptive_effect"]["passed"]
    assert record["checks"]["denoise_effect"]["passed"]
    assert record["checks"]["sample_count_aov_changes"]["status"] == "red"
    assert record["build"]["build_id"] == "test-build"
    assert f"{run_id}_cpu_adaptive_off.npy" in record["artifacts"]
    raw["aov"]["captures"].pop("adaptive_on")
    missing_pair = _host_evaluate_backend(raw, tmp_path)
    assert missing_pair["checks"]["sample_count_aov_changes"]["status"] == "unmeasured"
    raw["build"].pop("module_sha256")
    with pytest.raises(RuntimeError, match="exact build provenance"):
        _host_evaluate_backend(raw, tmp_path)


def test_host_evaluate_backend_rejects_tampered_artifact(tmp_path):
    """A dangling/hash-mismatched artifact is an instrument error, never a pass."""
    ref = _split_reference(seed=33, size=64)
    run_id = "tampered-run"
    path = tmp_path / f"{run_id}_cpu_adaptive_off.npy"
    np.save(path, ref)
    raw = {"backend": "cpu", "status": "measured", "run_id": run_id,
           "build": {"build_id": "test-build", "engine_id": ENGINE_ID,
                     "module_sha256": "a" * 64, "addon_init_sha256": "b" * 64}, "scene_sha256": "x",
           "legs": {"adaptive_off": {"artifact": path.name, "sha256": "0" * 64}},
           "artifacts": {path.name: {"sha256": "0" * 64, "kind": "linear_topdown_npy"}},
           "aov": {"probe": {}, "artifacts": {}}}
    with pytest.raises(RuntimeError, match="hash mismatch"):
        _host_evaluate_backend(raw, tmp_path)


def test_merged_pair_rejects_mismatched_build_or_reused_run(tmp_path):
    """CPU/GPU records may merge only when they identify one build and distinct runs."""
    build = {"build_id": "test-build", "engine_id": ENGINE_ID,
             "module_sha256": "a" * 64, "addon_init_sha256": "b" * 64}
    cpu = {"backend": "cpu", "status": "red", "build": build,
           "scene_sha256": "scene", "run_id": "cpu-run", "artifacts": {}}
    gpu = {"backend": "gpu", "status": "red", "build": {**build, "module_sha256": "c" * 64},
           "scene_sha256": "scene", "run_id": "gpu-run", "artifacts": {}}
    assert _write_merged(tmp_path, {"cpu": cpu, "gpu": gpu})["status"] == "error"
    gpu["build"] = build
    gpu["run_id"] = "cpu-run"
    assert _write_merged(tmp_path, {"cpu": cpu, "gpu": gpu})["status"] == "error"
