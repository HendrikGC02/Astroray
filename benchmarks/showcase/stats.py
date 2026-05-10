"""pkg74 Phase 2 — per-category stat collectors.

Spec:     .astroray_plan/packages/pkg74-engine-benchmark-showcase.md
Research: .astroray_plan/docs/engine-benchmark-research.md  §2

Every collector returns a flat `dict[str, str|float|int]` with keys
prefixed by category (`geom_`, `mem_`, `time_`, `samp_`, `qual_`,
`spec_`, `gpu_`, `intstat_`). The runner merges them into one row.

**Spec design decision #7 (no engine changes in pkg74):** anything that
would require a new C++ binding is probed via `hasattr` and reports
the empty string when absent. The framework therefore stays
forward-compatible: when (e.g.) a future package lands a `bvh_stats()`
binding on `Renderer`, the column populates automatically without a
runner change.

Reference patterns (cite, do not mirror verbatim):
- mmp/pbrt-v4 src/pbrt/util/stats.h  — STAT_* category split
- blender/cycles src/util/stats.h    — RenderStats { mesh, image, kernel, shaders, objects }
- mitsuba-renderer/mitsuba3 include/mitsuba/core/profiler.h — per-stage timing
"""

from __future__ import annotations

import math
import os
from typing import Any

import numpy as np


# Column-prefix → human-readable category label (used by the HTML index).
CATEGORY_LABELS: dict[str, str] = {
    "meta": "Run metadata",
    "geom": "Geometry",
    "mem":  "Memory",
    "time": "Timing",
    "samp": "Sampling",
    "qual": "Quality",
    "spec": "Spectral",
    "gpu":  "GPU",
    "intstat": "Integrator-specific",
}


# ---------------------------------------------------------------------------
# Geometry — what's in the scene
# ---------------------------------------------------------------------------

def geometry_stats(renderer: Any, scene_meta: dict[str, int]) -> dict[str, Any]:
    """Counts the scene builder reports + (when bound) on-engine BVH stats.

    `scene_meta` is the dict returned by the scene builders. Engine-side
    BVH stats (node count, leaf count, max depth) are probed via
    `hasattr` so we round-trip whatever a future binding exposes
    without churning this code.
    """
    out: dict[str, Any] = {
        "geom_triangles":   scene_meta.get("triangles", ""),
        "geom_spheres":     scene_meta.get("spheres", ""),
        "geom_materials":   scene_meta.get("materials", ""),
        "geom_lights":      scene_meta.get("lights", ""),
        "geom_primitives":  scene_meta.get("primitives", ""),
    }
    # Forward-compat probes — these bindings do not exist today (per the
    # research note's Section B); if a future package adds them, the CSV
    # populates automatically.
    for attr, key in (
        ("bvh_node_count",       "geom_bvh_nodes"),
        ("bvh_leaf_count",       "geom_bvh_leaves"),
        ("bvh_max_depth",        "geom_bvh_max_depth"),
        ("bvh_primitive_count",  "geom_bvh_prims"),
        ("bvh_build_ms",         "geom_bvh_build_ms"),
    ):
        method = getattr(renderer, attr, None)
        if callable(method):
            try:
                out[key] = method()
            except Exception:
                out[key] = ""
        else:
            out[key] = ""
    return out


# ---------------------------------------------------------------------------
# Memory — host RSS + image buffer + (when bound) GPU memory
# ---------------------------------------------------------------------------

def memory_stats(renderer: Any, pixels: np.ndarray | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "mem_peak_rss_mb": _peak_rss_mb(),
        "mem_image_mb":    _image_buffer_mb(pixels),
    }
    # Forward-compat: pkg74 does not add a GPU-memory binding (decision
    # #7); when a future package lands `gpu_memory_used_mb()` /
    # `gpu_memory_free_mb()` on Renderer, these populate.
    for attr, key in (
        ("gpu_memory_used_mb",  "mem_gpu_used_mb"),
        ("gpu_memory_free_mb",  "mem_gpu_free_mb"),
        ("gpu_memory_total_mb", "mem_gpu_total_mb"),
    ):
        method = getattr(renderer, attr, None)
        if callable(method):
            try:
                out[key] = float(method())
            except Exception:
                out[key] = ""
        else:
            out[key] = ""
    return out


def _peak_rss_mb() -> float:
    try:
        import psutil  # type: ignore
        return round(float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024), 2)
    except Exception:
        return float("nan")


def _image_buffer_mb(pixels: np.ndarray | None) -> float:
    if pixels is None:
        return 0.0
    return round(float(pixels.nbytes) / (1024 * 1024), 4)


# ---------------------------------------------------------------------------
# Timing — scene-build vs render split (Phase 1 had only the total).
# ---------------------------------------------------------------------------

def timing_stats(scene_build_ms: float, render_ms: float,
                 pass_setup_ms: float = 0.0) -> dict[str, Any]:
    total = scene_build_ms + render_ms + pass_setup_ms
    return {
        "time_scene_build_ms": round(float(scene_build_ms), 4),
        "time_render_ms":      round(float(render_ms), 4),
        "time_pass_setup_ms":  round(float(pass_setup_ms), 4),
        "time_total_ms":       round(float(total), 4),
    }


# ---------------------------------------------------------------------------
# Sampling — what was asked of the integrator (the rest needs C++ counters).
# ---------------------------------------------------------------------------

def sampling_stats(samples: int, width: int, height: int,
                   max_depth: int) -> dict[str, Any]:
    pixels = int(width) * int(height)
    return {
        "samp_pixels":             pixels,
        "samp_per_pixel":          int(samples),
        "samp_total_paths":        pixels * int(samples),
        "samp_max_depth_budget":   int(max_depth),
        # Engine-bound counters land here when a future package exposes
        # the per-ray-type histogram (research note §2.2 / Section C).
        "samp_camera_rays":        "",
        "samp_shadow_rays":        "",
        "samp_scattered_rays":     "",
        "samp_rr_termination_pct": "",
    }


# ---------------------------------------------------------------------------
# Quality — image-derived stats; second-seed variance is opt-in.
# ---------------------------------------------------------------------------

def quality_stats(pixels: np.ndarray,
                  pixels_second_seed: np.ndarray | None = None,
                  *,
                  reference: np.ndarray | None = None) -> dict[str, Any]:
    """Image stats + optional inter-seed variance + optional RMSE-vs-ref.

    Phase 1's image stats stay unprefixed (`mean_luminance` etc) for
    backwards compat. Phase 2 adds `qual_*` variants alongside, plus
    new variance and reference-deviation columns the Phase 1 row never
    carried.
    """
    arr = np.asarray(pixels, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    else:
        lum = arr.reshape(arr.shape[0], -1)[:, :1]

    mean_l = float(np.mean(lum))
    threshold = 4.0 * max(mean_l, 1e-6)
    fireflies = int(np.count_nonzero(lum > threshold))

    out: dict[str, Any] = {
        # Phase 1 originals (unchanged)
        "mean_luminance":        round(mean_l, 6),
        "p99_luminance":         round(float(np.percentile(lum, 99.0)), 6),
        "max_luminance":         round(float(np.max(lum)), 6),
        "nonzero_fraction":      round(float(np.count_nonzero(lum > 1e-5)) / float(lum.size), 6),
        "firefly_count_4x_mean": float(fireflies),
        # Phase 2 additions, prefixed
        "qual_p50_luminance":    round(float(np.percentile(lum, 50.0)), 6),
        "qual_p95_luminance":    round(float(np.percentile(lum, 95.0)), 6),
        "qual_min_luminance":    round(float(np.min(lum)), 6),
        "qual_dynamic_range":    round(float(np.max(lum) / max(float(np.min(lum)), 1e-6)), 4),
    }

    if pixels_second_seed is not None:
        b = np.asarray(pixels_second_seed, dtype=np.float32)
        if b.shape == arr.shape:
            # Per-pixel single-sample variance from a paired draw:
            # var ≈ (a − b)^2 / 2  (Welford one-pass with n=2).
            diff_sq = (arr - b) ** 2 * 0.5
            per_pixel_var = np.mean(diff_sq, axis=-1) if diff_sq.ndim == 3 else diff_sq
            out["qual_variance_mean"] = round(float(np.mean(per_pixel_var)), 8)
            out["qual_variance_p95"]  = round(float(np.percentile(per_pixel_var, 95.0)), 8)
            out["qual_variance_max"]  = round(float(np.max(per_pixel_var)), 8)

    if reference is not None and reference.shape == arr.shape:
        # RMSE vs reference (used by convergence rows; the runner already
        # records this under the Phase 1 column name when applicable).
        diff = arr.astype(np.float64) - reference.astype(np.float64)
        out["qual_rmse_vs_reference"] = round(math.sqrt(float(np.mean(diff * diff))), 8)

    return out


def convergence_rate_slope(spp_values: list[int],
                           rmse_values: list[float]) -> float:
    """Log-log slope of RMSE vs SPP. Excludes any zero / non-finite entries.

    A pure Monte-Carlo path tracer should approach −0.5 (RMSE ∝ 1/√spp).
    Returns NaN if too few usable points.
    """
    pts = [(s, r) for s, r in zip(spp_values, rmse_values)
           if s > 0 and r > 0 and math.isfinite(r)]
    if len(pts) < 2:
        return float("nan")
    xs = np.log(np.array([p[0] for p in pts], dtype=np.float64))
    ys = np.log(np.array([p[1] for p in pts], dtype=np.float64))
    # Plain least-squares slope.
    slope, _ = np.polyfit(xs, ys, 1)
    return float(slope)


# ---------------------------------------------------------------------------
# Spectral — configured wavelength range; histograms need engine counters.
# ---------------------------------------------------------------------------

def spectral_stats(renderer: Any) -> dict[str, Any]:
    """Reports configured wavelength range when the integrator is spectral.

    Note: `set_wavelength_range` is a setter; Astroray currently has no
    getter for the *current* range, so we report only what we can probe.
    Hero-wavelength selection histograms (research note §2.6) need engine
    counters and stay empty here.
    """
    out: dict[str, Any] = {
        "spec_wavelength_min_nm":     "",
        "spec_wavelength_max_nm":     "",
        "spec_hero_band_histogram":   "",
        "spec_secondary_term_pct":    "",
    }
    for attr, key in (
        ("get_wavelength_min_nm", "spec_wavelength_min_nm"),
        ("get_wavelength_max_nm", "spec_wavelength_max_nm"),
    ):
        method = getattr(renderer, attr, None)
        if callable(method):
            try:
                out[key] = float(method())
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# GPU — device probe; per-pass kernel times need engine counters.
# ---------------------------------------------------------------------------

def gpu_stats(renderer: Any, device: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "gpu_device_requested":  device,
        "gpu_available":         bool(getattr(renderer, "gpu_available", False)),
        "gpu_device_name":       str(getattr(renderer, "gpu_device_name", "") or ""),
        "gpu_optix_available":   "",
        "gpu_used":              device == "gpu",
    }
    # `gpu_optix_available` is a module-level function, not a renderer
    # method; the runner passes it in via `optix_available` if available.
    return out


def gpu_module_stats(astroray_module: Any) -> dict[str, Any]:
    """Stats that live on the `astroray` module rather than a Renderer."""
    out: dict[str, Any] = {"gpu_optix_available": ""}
    fn = getattr(astroray_module, "gpu_optix_available", None)
    if callable(fn):
        try:
            out["gpu_optix_available"] = bool(fn())
        except Exception:
            out["gpu_optix_available"] = ""
    return out


# ---------------------------------------------------------------------------
# Integrator-specific — round-trip whatever get_integrator_stats() yields.
# ---------------------------------------------------------------------------

def integrator_specific_stats(renderer: Any) -> dict[str, Any]:
    """Flatten `get_integrator_stats()` under the `intstat_` prefix.

    Phase 1 used `integrator_stats_<key>`. Phase 2 emits both the new
    short prefix AND the legacy long one — Phase 1 consumers keep
    working, Phase 2 consumers see the same data under the shorter
    name.
    """
    if not hasattr(renderer, "get_integrator_stats"):
        return {}
    try:
        raw = renderer.get_integrator_stats()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        items = raw.items()
    except AttributeError:
        return {}
    out: dict[str, Any] = {}
    for k, v in items:
        out[f"intstat_{k}"] = v
        out[f"integrator_stats_{k}"] = v   # back-compat with Phase 1 readers
    return out


# ---------------------------------------------------------------------------
# Aggregator — single call from the runner.
# ---------------------------------------------------------------------------

def collect(*, renderer: Any,
            astroray_module: Any,
            scene_meta: dict[str, int],
            samples: int, width: int, height: int, max_depth: int,
            scene_build_ms: float, render_ms: float,
            pixels: np.ndarray,
            pixels_second_seed: np.ndarray | None = None,
            reference: np.ndarray | None = None,
            device: str = "cpu") -> dict[str, Any]:
    """One-shot merge of every Phase 2 category."""
    row: dict[str, Any] = {}
    row.update(geometry_stats(renderer, scene_meta))
    row.update(memory_stats(renderer, pixels))
    row.update(timing_stats(scene_build_ms, render_ms))
    row.update(sampling_stats(samples, width, height, max_depth))
    row.update(quality_stats(pixels,
                             pixels_second_seed=pixels_second_seed,
                             reference=reference))
    row.update(spectral_stats(renderer))
    row.update(gpu_stats(renderer, device))
    row.update(gpu_module_stats(astroray_module))
    row.update(integrator_specific_stats(renderer))
    return row


def column_category(column_name: str) -> str:
    """Map a CSV column name to a category id (for HTML grouping)."""
    if "_" not in column_name:
        # Phase 1 unprefixed columns: heuristic bucket.
        if column_name in {"mean_luminance", "p99_luminance", "max_luminance",
                           "nonzero_fraction", "firefly_count_4x_mean"}:
            return "qual"
        if column_name in {"render_seconds", "peak_rss_mb"}:
            return "time"
        if column_name in {"samples", "width", "height", "max_depth", "seed"}:
            return "samp"
        if column_name in {"scene", "integrator", "device", "skip_reason",
                           "machine_id", "git_sha", "run_date",
                           "rmse_vs_in_run_reference"}:
            return "meta"
        return "meta"
    head = column_name.split("_", 1)[0]
    if head == "integrator":
        return "intstat"  # legacy `integrator_stats_*` columns
    return head if head in CATEGORY_LABELS else "meta"
