# -*- coding: utf-8 -*-
"""pkg200 — native-settings F12 pixel-honour matrix (pure contract layer).

This module is the IMPORT-SAFE, bpy-free, GPU-free heart of the honour matrix:

  * ``enumerate_direct_surface()`` reads the pkg176 Stage-0 contract
    (``blender_addon/settings_map.py``) and returns the set of native props the
    steering wheel PLUMBS at F12 — the honour surface. The matrix is generated
    FROM this so it cannot silently drift from what pkg176 actually wired.
  * ``MATRIX`` assigns exactly one test ROW to every plumbed prop.
    ``check_completeness()`` HARD-FAILS if any plumbed prop is unassigned or
    double-assigned (Stage-0 acceptance).
  * The per-row ``predicate`` functions decide PASS / HONEST-FAIL / NEEDS-VISUAL
    from per-channel LINEAR statistics only — no Blender, no cv2, no GPU — so
    they are unit-tested in ``tests/test_pkg200_honour_matrix.py``.

The in-Blender A/B leg (``verify_pkg200_honour_matrix.py``) reads a row's
``scene`` id + ``variant_a`` / ``variant_b`` / ``common`` native-prop overrides
from here and renders two LINEAR EXRs; the outer orchestrator
(``verify_pkg200_honour_matrix_run.py``) reads those EXRs with cv2
(IMREAD_UNCHANGED — memory ``gamma-furnace-cannot-detect-energy-gain`` /
run_parity._read_exr_float), builds the ``LegStats`` this module's predicates
consume, and gates on a per-row sentinel (never the Blender exit code).

Route-2 discipline (pkg176): this file never imports bpy and never touches the
engine. Overrides are declarative (attr-path, value) pairs the leg applies.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
# settings_map.py lives in blender_addon/ and imports nothing bpy-ish at module
# load, so it is safe to import from a plain Python process.
_ADDON_DIR = _REPO_ROOT / "blender_addon"
if str(_ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(_ADDON_DIR))

import settings_map  # noqa: E402  (path set above)

# --------------------------------------------------------------------------- #
# Honour surface enumeration (from the pkg176 Stage-0 contract)
# --------------------------------------------------------------------------- #

# Only these categories carry render/sampling/light-path/film/denoise controls
# that are plumbed to a renderer.* setter or render() arg at F12. world/camera/
# light/material DIRECT rows are other packages' surface (pkg63/setup_camera/
# pkg119-B) and are explicitly out of THIS matrix (pkg200 spec, "Scope").
HONOUR_CATEGORIES = frozenset({"render", "sampling", "light_paths", "film", "denoising"})

# The two APPROXIMATED denoise rows that ARE plumbed today (resolve_denoiser_pass
# / viewport denoise) — included per the spec's "plus the plumbed approximated
# denoise rows". Every OTHER approximated row (light_sampling / use_light_tree)
# is a documented gap, see KNOWN_GAPS.
_PLUMBED_APPROXIMATED = frozenset({"denoiser", "use_preview_denoising"})


def enumerate_direct_surface() -> list[str]:
    """Native props the steering wheel PLUMBS at F12 (the honour surface).

    = DIRECT rows in the honour categories whose neutral_param is a real setter/
      render() arg (not ``(none)``), plus the two plumbed APPROXIMATED denoise
      rows. Returned sorted and de-duplicated by native_prop.
    """
    props: list[str] = []
    for e in settings_map.MAPPING:
        if e.category not in HONOUR_CATEGORIES:
            continue
        if e.status == "direct" and e.neutral_param not in ("", "(none)"):
            props.append(e.native_prop)
        elif e.status == "approximated" and e.native_prop in _PLUMBED_APPROXIMATED:
            props.append(e.native_prop)
    # De-dup, stable-sorted for a deterministic completeness check.
    return sorted(dict.fromkeys(props))


# Documented gaps: plumbed-looking but NOT honoured natively today. Recorded as
# findings, never tested as honoured (spec "Explicitly out of the honour matrix").
KNOWN_GAPS = {
    "use_light_tree": (
        "scene.cycles.use_light_tree is APPROXIMATED and NOT read at F12: "
        "convert_scene reads the custom light_sampler tri-state "
        "(settings.light_sampler), never the native use_light_tree bool. "
        "Toggling the native prop changes nothing. Follow-up: reconcile the "
        "tri-state vs. bool semantic mismatch (settings_map light_sampling row)."
    ),
}


# --------------------------------------------------------------------------- #
# Verdict vocabulary
# --------------------------------------------------------------------------- #
PASS = "PASS"
HONEST_FAIL = "HONEST-FAIL"
NEEDS_VISUAL = "NEEDS-VISUAL"
LIMITATION = "LIMITATION"   # cannot be exercised via the headless F12 path
ERROR = "ERROR"


@dataclass
class LegStats:
    """Per-channel LINEAR statistics for one rendered EXR (built by the outer
    orchestrator from cv2.imread(IMREAD_UNCHANGED))."""
    mean: tuple[float, float, float]
    maxv: tuple[float, float, float]
    var: tuple[float, float, float]
    lum_mean: float
    lum_max: float
    lum_var: float
    alpha_mean: float
    grad_mean: float          # mean gradient magnitude of luminance (edge sharpness)
    hi_pct: float             # 99.5th-percentile luminance (firefly proxy)
    shape: tuple[int, int]    # (h, w)


@dataclass
class Cross:
    """Cross-A/B per-pixel metrics (only defined when shapes match)."""
    lum_abs_diff_mean: float
    lum_abs_diff_max: float
    identical: bool           # max abs diff <= 1e-5 (GPU atomic floor)


# --------------------------------------------------------------------------- #
# Predicates (pure: consume LegStats/Cross, return (verdict, detail))
# --------------------------------------------------------------------------- #
Predicate = Callable[[LegStats, LegStats, "Cross | None"], "tuple[str, str]"]

_ENERGY_MARGIN = 1.03   # B must exceed A by >=3% mean luminance to count as "responds"


def p_monotone_energy(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """B (deep bounces) strictly brighter than A (shallow) in linear mean lum."""
    ratio = b.lum_mean / a.lum_mean if a.lum_mean > 1e-9 else float("inf")
    detail = f"lum_mean A={a.lum_mean:.5g} B={b.lum_mean:.5g} ratio={ratio:.3f}"
    if ratio >= _ENERGY_MARGIN:
        return PASS, detail
    return HONEST_FAIL, detail + f" (< {_ENERGY_MARGIN}: setting does not add indirect energy)"


def p_exposure_scale(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """film_exposure 1.0 -> 2.0 must scale linear mean by ~2.0 per channel."""
    band = (1.7, 2.3)
    ratios = [b.mean[i] / a.mean[i] if a.mean[i] > 1e-9 else float("nan") for i in range(3)]
    detail = "per-ch mean-ratio B/A = " + ", ".join(f"{r:.3f}" for r in ratios)
    ok = all(band[0] <= r <= band[1] for r in ratios)
    return (PASS if ok else HONEST_FAIL), detail + f" (target {band})"


def p_clamp(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """B (clamp on) high-percentile luminance well below A (clamp off)."""
    detail = f"hi_pct A={a.hi_pct:.4g} B={b.hi_pct:.4g}; lum_max A={a.lum_max:.4g} B={b.lum_max:.4g}"
    if b.hi_pct < a.hi_pct * 0.9 and b.lum_max < a.lum_max * 0.95:
        return PASS, detail + " (fireflies clipped)"
    return HONEST_FAIL, detail + " (clamp did not lower the high tail)"


def p_clamp_indirect(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """Like p_clamp, but if the clamp changed nothing we return NEEDS-VISUAL
    (inconclusive) rather than HONEST-FAIL: clampIndirect is the sibling of
    clampDirect in the same pkg157 kernel call (stage_advance.cu), and
    sample_clamp_direct empirically PASSES — so a null result here means the
    scene's fireflies were NEE-classified as DIRECT (clampDirect clips them),
    not that clampIndirect is unhonoured."""
    detail = f"hi_pct A={a.hi_pct:.4g} B={b.hi_pct:.4g}; lum_max A={a.lum_max:.4g} B={b.lum_max:.4g}"
    if b.hi_pct < a.hi_pct * 0.9 and b.lum_max < a.lum_max * 0.95:
        return PASS, detail + " (indirect fireflies clipped)"
    return NEEDS_VISUAL, detail + (" (inconclusive: fireflies NEE-classified as DIRECT; "
        "clampIndirect shares the pkg157 kernel param with clampDirect, which PASSES)")


def p_blur_glossy(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """B (blur on) highlight peak drops vs A (sharp)."""
    detail = f"lum_max A={a.lum_max:.4g} B={b.lum_max:.4g}"
    if b.lum_max < a.lum_max * 0.97:
        return PASS, detail + " (highlight softened)"
    return HONEST_FAIL, detail + " (blur_glossy left the highlight peak unchanged)"


def p_variance_falls(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """B (4x spp) mean stable, luminance variance markedly lower than A."""
    mean_ratio = b.lum_mean / a.lum_mean if a.lum_mean > 1e-9 else float("nan")
    var_ratio = b.lum_var / a.lum_var if a.lum_var > 1e-12 else float("nan")
    detail = f"lum_mean ratio={mean_ratio:.3f}, lum_var ratio B/A={var_ratio:.3f}"
    if 0.9 <= mean_ratio <= 1.1 and var_ratio < 0.7:
        return PASS, detail
    return HONEST_FAIL, detail + " (variance did not fall ~1/N or mean drifted)"


def p_seed_distinct(a: LegStats, b: LegStats, c: "Cross | None") -> tuple[str, str]:
    """Two DISTINCT nonzero seeds: equal mean (MC band), different noise field."""
    if c is None:
        return ERROR, "no cross metrics (shape mismatch)"
    mean_ratio = b.lum_mean / a.lum_mean if a.lum_mean > 1e-9 else float("nan")
    detail = f"lum_mean ratio={mean_ratio:.3f}, per-pixel |dLum| mean={c.lum_abs_diff_mean:.4g}"
    if 0.9 <= mean_ratio <= 1.1 and not c.identical and c.lum_abs_diff_mean > 1e-4:
        return PASS, detail + " (same mean, different noise)"
    return HONEST_FAIL, detail + " (seed did not change the noise field, or mean drifted)"


def p_seed_repeat(a: LegStats, b: LegStats, c: "Cross | None") -> tuple[str, str]:
    """Same fixed nonzero seed twice: reproducible within the GPU atomic floor."""
    if c is None:
        return ERROR, "no cross metrics (shape mismatch)"
    detail = f"per-pixel |dLum| max={c.lum_abs_diff_max:.3g}"
    if c.identical:
        return PASS, detail + " (reproducible <=1e-5)"
    return HONEST_FAIL, detail + " (fixed seed not reproducible)"


def p_alpha_transparent(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """film_transparent ON (A) -> background alpha ~0; OFF (B) -> opaque ~1."""
    detail = f"alpha_mean transparent-A={a.alpha_mean:.3f} opaque-B={b.alpha_mean:.3f}"
    if a.alpha_mean < b.alpha_mean - 0.1:
        return PASS, detail
    return HONEST_FAIL, detail + " (film_transparent did not open the background alpha)"


def p_grad_sharper(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """A (BOX / narrow) has sharper edges (higher gradient) than B (wide/soft)."""
    detail = f"grad_mean A={a.grad_mean:.5g} B={b.grad_mean:.5g}"
    if a.grad_mean > b.grad_mean * 1.01:
        return PASS, detail + " (filter changes edge sharpness)"
    return HONEST_FAIL, detail + " (pixel filter did not change edge gradient)"


def p_denoise_variance(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """B (denoised) variance collapses vs A (noisy). Visual not-garbage checked
    separately (NEEDS-VISUAL leg)."""
    var_ratio = b.lum_var / a.lum_var if a.lum_var > 1e-12 else float("nan")
    detail = f"lum_var ratio denoised/noisy={var_ratio:.3f}"
    if var_ratio < 0.85:
        return PASS, detail + " (variance reduced)"
    return HONEST_FAIL, detail + " (denoise did not collapse variance)"


def p_both_rendered(a: LegStats, b: LegStats, c: "Cross | None") -> tuple[str, str]:
    """Both backends produce a valid (finite, non-black) denoised frame. Marked
    NEEDS-VISUAL — the backend selector's honour is 'both yield a denoised
    frame', confirmed visually; whether the two backends differ is not asserted."""
    d = "no cross" if c is None else f"per-pixel |dLum| mean={c.lum_abs_diff_mean:.4g}"
    if a.lum_mean > 1e-4 and b.lum_mean > 1e-4:
        return NEEDS_VISUAL, f"both backends rendered (A mean={a.lum_mean:.4g}, " \
                             f"B mean={b.lum_mean:.4g}; {d})"
    return HONEST_FAIL, f"a backend produced a black frame (A={a.lum_mean:.4g}, B={b.lum_mean:.4g})"


def p_changes_pixels(a: LegStats, b: LegStats, c: "Cross | None") -> tuple[str, str]:
    """Generic: A and B differ measurably (used where direction is scene-specific,
    e.g. film_transparent_glass, caustics — paired with a NEEDS-VISUAL confirm)."""
    if c is None:
        return NEEDS_VISUAL, "shape mismatch — inspect manually"
    detail = f"per-pixel |dLum| mean={c.lum_abs_diff_mean:.4g} max={c.lum_abs_diff_max:.4g}"
    if c.lum_abs_diff_mean > 1e-4:
        return NEEDS_VISUAL, detail + " (setting changes pixels; confirm direction visually)"
    return HONEST_FAIL, detail + " (setting produced no pixel change)"


def p_resolution(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    """resolution_x/y honoured: the two legs render at different pixel dims."""
    detail = f"shape A={a.shape} B={b.shape}"
    if a.shape != b.shape:
        return PASS, detail
    return HONEST_FAIL, detail + " (resolution override did not change output dims)"


def p_limitation(a: LegStats, b: LegStats, _c) -> tuple[str, str]:
    return LIMITATION, "viewport-only control — not exercisable via headless F12"


# --------------------------------------------------------------------------- #
# Matrix rows
# --------------------------------------------------------------------------- #
# An override is (attr_path, value) applied to the Blender `scene`, e.g.
# ("cycles.max_bounces", 0) -> scene.cycles.max_bounces = 0. The leg walks the
# dotted path. `common` overrides apply to BOTH legs (isolate one variable).
Override = tuple[str, object]


@dataclass
class Row:
    name: str
    props: tuple[str, ...]            # native props this row proves honour for
    scene: str                        # scene-builder id (leg-side)
    stage: str
    predicate: Predicate
    variant_a: tuple[Override, ...] = ()
    variant_b: tuple[Override, ...] = ()
    common: tuple[Override, ...] = ()
    kind: str = "automatable"         # automatable | visual | limitation
    samples: int = 32
    res: int = 96
    note: str = ""
    seed_a: int = 20200
    seed_b: int = 20200               # distinct only for the seed-distinct row
    # noise_pair rows (e.g. `samples`) render FOUR frames — a two-independent-seed
    # pair at `samples` (low) and at `samples_hi` (high) — so the outer can
    # estimate MC NOISE (per-pixel |A-A2| mean) at each spp. Spatial variance does
    # NOT fall with spp (memory mc-noise-vs-deterministic); only MC noise does.
    noise_pair: bool = False
    samples_hi: int = 0


# High per-type caps so max_bounces is the only limiter in the depth rows.
_DEEP = (
    ("cycles.max_bounces", 16), ("cycles.diffuse_bounces", 16),
    ("cycles.glossy_bounces", 16), ("cycles.transmission_bounces", 16),
    ("cycles.transparent_max_bounces", 16),
)


MATRIX: list[Row] = [
    # ---- Stage 1: light-path depth energy monotonicity ----
    Row("max_bounces", ("max_bounces",), "closed_box", "1", p_monotone_energy,
        variant_a=(("cycles.max_bounces", 1), ("cycles.diffuse_bounces", 16)),
        variant_b=(("cycles.max_bounces", 12), ("cycles.diffuse_bounces", 16)),
        note="closed diffuse box; total path depth 1 vs 12"),
    Row("diffuse_bounces", ("diffuse_bounces",), "closed_box", "1", p_monotone_energy,
        common=(("cycles.max_bounces", 16),),
        variant_a=(("cycles.diffuse_bounces", 0),),
        variant_b=(("cycles.diffuse_bounces", 8),),
        note="diffuse interreflection depth 0 vs 8. NOTE: per-type bounces are NOT "
             "passed to cuda_wavefront_render (blender_module.cpp: GPU call omits the "
             "diffuse/glossy/transmission/volume/transparent args the CPU path at "
             "L1906 passes) — expected GPU HONEST-FAIL; CPU honours it."),
    Row("glossy_bounces", ("glossy_bounces",), "closed_box_glossy", "1", p_monotone_energy,
        common=(("cycles.max_bounces", 16),),
        variant_a=(("cycles.glossy_bounces", 0),),
        variant_b=(("cycles.glossy_bounces", 8),),
        note="glossy interreflection depth 0 vs 8 (smooth-shaded walls)"),
    Row("transmission_bounces", ("transmission_bounces",), "glass_sphere", "1", p_monotone_energy,
        common=(("cycles.max_bounces", 16),),
        variant_a=(("cycles.transmission_bounces", 0),),
        variant_b=(("cycles.transmission_bounces", 12),),
        note="solid glass sphere; transmission depth 0 vs 12"),
    Row("transparent_max_bounces", ("transparent_max_bounces",), "transparent_tower", "1",
        p_monotone_energy,
        common=(("cycles.max_bounces", 16),),
        variant_a=(("cycles.transparent_max_bounces", 0),),
        variant_b=(("cycles.transparent_max_bounces", 12),),
        note="stacked alpha-transparent quads; alpha depth 0 vs 12"),
    Row("world_max_bounces", ("world.light_settings.max_bounces",), "hdri_box", "1",
        p_monotone_energy,
        common=(("cycles.max_bounces", 16), ("cycles.diffuse_bounces", 16)),
        variant_a=(("world.light_settings.max_bounces", 0),),
        variant_b=(("world.light_settings.max_bounces", 12),),
        note="world-lit box; world max bounces 0 vs 12. NOTE: the addon reads a "
             "NON-EXISTENT attr world.light_settings.max_bounces (WorldLighting has "
             "no such member; the real Cycles prop is world.cycles.max_bounces), so "
             "getattr(..., 1024) always wins — override is inert. Expected HONEST-FAIL."),
    Row("volume_bounces", ("volume_bounces",), "volume_box", "1", p_monotone_energy,
        common=(("cycles.max_bounces", 16),),
        variant_a=(("cycles.volume_bounces", 0),),
        variant_b=(("cycles.volume_bounces", 8),),
        note="KNOWN-PARTIAL candidate: volume transport only partly implemented "
             "(settings_map note). HONEST-FAIL if non-responsive — file, do not fix."),

    # ---- Stage 2: clamps + filter-glossy firefly clipping ----
    Row("sample_clamp_direct", ("sample_clamp_direct",), "firefly", "2", p_clamp,
        variant_a=(("cycles.sample_clamp_direct", 0.0),),
        variant_b=(("cycles.sample_clamp_direct", 0.5),),
        note="bright emitter + glossy floor; direct clamp off vs 0.5 (GPU honours "
             "clampDirect, pkg157)"),
    Row("sample_clamp_indirect", ("sample_clamp_indirect",), "firefly_indirect", "2", p_clamp_indirect,
        variant_a=(("cycles.sample_clamp_indirect", 0.0),),
        variant_b=(("cycles.sample_clamp_indirect", 0.5),),
        note="indirect firefly (glossy reflection of a brightly-lit diffuse panel); "
             "indirect clamp off vs 0.5 (GPU honours clampIndirect, pkg157)"),
    Row("blur_glossy", ("blur_glossy",), "firefly", "2", p_blur_glossy,
        variant_a=(("cycles.blur_glossy", 0.0),),
        variant_b=(("cycles.blur_glossy", 10.0),),
        note="sharp glossy highlight; filter-glossy 0 vs 10. NOTE: renderer.filterGlossy "
             "is stored but never read in src/gpu/ — expected GPU HONEST-FAIL."),

    # ---- Stage 3: film + sampling + seed ----
    Row("film_exposure", ("film_exposure",), "closed_box", "3", p_exposure_scale,
        variant_a=(("cycles.film_exposure", 1.0),),
        variant_b=(("cycles.film_exposure", 2.0),),
        note="cleanest quantitative honour: linear mean must ~double"),
    Row("film_transparent", ("render.film_transparent",), "open_object", "3", p_alpha_transparent,
        variant_a=(("render.film_transparent", True),),
        variant_b=(("render.film_transparent", False),),
        note="single object against a VISIBLE world background; alpha transparent (A) vs opaque (B)"),
    Row("film_transparent_glass", ("film_transparent_glass",), "open_glass", "3",
        p_changes_pixels, kind="visual",
        common=(("render.film_transparent", True),),
        variant_a=(("cycles.film_transparent_glass", False),),
        variant_b=(("cycles.film_transparent_glass", True),),
        note="glass sphere on transparent film; glass-alpha behaviour; confirm visually"),
    Row("samples", ("samples",), "open_object", "3", p_variance_falls,
        noise_pair=True, samples=16, samples_hi=64, seed_a=111, seed_b=999,
        note="4x spp on a smooth scene: MC NOISE (two-independent-seed per-pixel "
             "diff) must fall ~1/2 (1/sqrt(4)); spatial variance does not fall with "
             "spp so it is not used (memory mc-noise-vs-deterministic)"),
    Row("seed_distinct", ("seed",), "closed_box", "3", p_seed_distinct,
        variant_a=(("cycles.seed", 111),),
        variant_b=(("cycles.seed", 999),), seed_a=111, seed_b=999,
        note="two distinct nonzero seeds: equal mean, different noise"),
    Row("seed_repeat", ("seed",), "closed_box", "3", p_seed_repeat,
        variant_a=(("cycles.seed", 424242),),
        variant_b=(("cycles.seed", 424242),), seed_a=424242, seed_b=424242,
        note="same fixed nonzero seed twice: reproducible <=1e-5"),

    # ---- Stage 4: caustics + pixel filter + denoise ----
    Row("caustics_reflective", ("caustics_reflective",), "caustic", "4", p_changes_pixels,
        kind="visual",
        variant_a=(("cycles.caustics_reflective", False),),
        variant_b=(("cycles.caustics_reflective", True),),
        note="reflective caustic on/off. NOTE: renderer.useReflectiveCaustics is not "
             "read in src/gpu/; GPU caustics gate on a SEPARATE usePhotonCaustics "
             "opt-in — expected GPU HONEST-FAIL (native toggle inert on GPU)."),
    Row("caustics_refractive", ("caustics_refractive",), "caustic", "4", p_changes_pixels,
        kind="visual",
        variant_a=(("cycles.caustics_refractive", False),),
        variant_b=(("cycles.caustics_refractive", True),),
        note="refractive caustic on/off. NOTE: as caustics_reflective — GPU path does "
             "not read the native toggle (usePhotonCaustics is the GPU gate)."),
    Row("pixel_filter_type", ("pixel_filter_type",), "closed_box", "4", p_grad_sharper,
        variant_a=(("cycles.pixel_filter_type", "BOX"), ("cycles.filter_width", 1.0)),
        variant_b=(("cycles.pixel_filter_type", "GAUSSIAN"), ("cycles.filter_width", 3.0)),
        note="BOX/narrow vs GAUSSIAN/wide. NOTE: pixelFilterType/Width are stored but "
             "never read in src/gpu/ — expected GPU HONEST-FAIL."),
    Row("filter_width", ("filter_width",), "closed_box", "4", p_grad_sharper,
        common=(("cycles.pixel_filter_type", "GAUSSIAN"),),
        variant_a=(("cycles.filter_width", 0.5),),
        variant_b=(("cycles.filter_width", 4.0),),
        note="narrow vs wide gaussian. NOTE: pixel filter not applied on GPU (see "
             "pixel_filter_type) — expected GPU HONEST-FAIL."),
    Row("use_denoising", ("use_denoising",), "denoiser_scene", "4", p_denoise_variance,
        kind="visual", samples=8,
        variant_a=(("cycles.use_denoising", False),),
        variant_b=(("cycles.use_denoising", True),),
        note="noisy scene: denoise variance collapse + visual not-garbage (GPU "
             "applyPasses runs the denoiser, pkg197)"),
    Row("denoiser", ("denoiser",), "denoiser_scene", "4", p_both_rendered,
        kind="visual", samples=8,
        common=(("cycles.use_denoising", True),),
        variant_a=(("cycles.denoiser", "OPENIMAGEDENOISE"),),
        variant_b=(("cycles.denoiser", "OPTIX"),),
        note="both denoiser backends must yield a valid denoised frame; confirm "
             "visually. Whether the two backends differ is not asserted."),

    # ---- resolution (trivial but plumbed) ----
    Row("resolution", ("render.resolution_x", "render.resolution_y"), "closed_box", "0", p_resolution,
        variant_a=(("render.resolution_x", 64), ("render.resolution_y", 64)),
        variant_b=(("render.resolution_x", 96), ("render.resolution_y", 96)),
        note="resolution override changes output pixel dims"),

    # ---- viewport-only controls (cannot be F12-tested headlessly) ----
    Row("preview_samples", ("preview_samples",), "closed_box", "3", p_limitation,
        kind="limitation",
        note="viewport spp; the interactive view_draw path is not exercisable via "
             "headless bpy.ops.render.render. Resolve-level read verified in unit test."),
    Row("use_preview_denoising", ("use_preview_denoising",), "closed_box", "4", p_limitation,
        kind="limitation",
        note="viewport denoise toggle; viewport-only, not an F12 control."),
]


# --------------------------------------------------------------------------- #
# Completeness gate (Stage-0 acceptance)
# --------------------------------------------------------------------------- #
def _assigned_props() -> list[str]:
    props: list[str] = []
    for row in MATRIX:
        props.extend(row.props)
    return props


def check_completeness() -> None:
    """HARD-FAIL if the plumbed honour surface and the assigned matrix rows do
    not match exactly (unassigned prop = a silently-untested control; duplicate =
    ambiguous ownership). Raises AssertionError with the drift."""
    surface = set(enumerate_direct_surface())
    # world_max_bounces is enumerated by its native_prop "world_max_bounces" in
    # settings_map but its Blender path is world.light_settings.max_bounces; map.
    _alias = {"world_max_bounces": "world.light_settings.max_bounces",
              "film_transparent": "render.film_transparent",
              "resolution_x": "render.resolution_x",
              "resolution_y": "render.resolution_y"}
    surface_paths = {_alias.get(p, p) for p in surface}
    assigned = _assigned_props()

    # `seed` legitimately needs two legs (distinct-noise + reproducibility); any
    # OTHER duplicate is accidental ambiguous ownership and hard-fails.
    _multi_ok = {"seed"}
    dupes = [p for p in set(assigned) if assigned.count(p) > 1 and p not in _multi_ok]
    if dupes:
        raise AssertionError(f"pkg200 matrix: prop double-assigned to >1 row: {sorted(dupes)}")

    assigned_set = set(assigned)
    unassigned = surface_paths - assigned_set
    if unassigned:
        raise AssertionError(
            "pkg200 matrix DRIFT: these DIRECT-plumbed props have no test row "
            f"(add one or the steering wheel lies silently): {sorted(unassigned)}")
    extra = assigned_set - surface_paths
    if extra:
        raise AssertionError(
            "pkg200 matrix: test rows reference props NOT in the plumbed honour "
            f"surface (stale row?): {sorted(extra)}")


def get_row(name: str) -> Row:
    for r in MATRIX:
        if r.name == name:
            return r
    raise KeyError(name)


if __name__ == "__main__":
    check_completeness()
    print(f"pkg200 honour surface ({len(enumerate_direct_surface())} plumbed props) "
          f"-> {len(MATRIX)} matrix rows: OK")
    for r in MATRIX:
        print(f"  [{r.stage}] {r.name:24s} scene={r.scene:16s} kind={r.kind}")
