# -*- coding: utf-8 -*-
"""pkg119 Phase B - differential parity harness driver (pure Python, no bpy).

Reads the Phase-A coverage matrix, selects the SUPPORTED/APPROXIMATED cells as
the differential test population, and for each feature (plus a curated set of
COMPOSITE scenes) spawns two subprocess-isolated headless-Blender render legs -
one CYCLES oracle, one CUSTOM_RAYTRACER (per pkg71 discipline). It then compares
the two linear renders with the pkg104 reference-bank metrics (compute_ssim +
compute_delta_e_2000 + a trivial per-channel mean ratio - NOT a new metric
stack), gates each feature, and triages every failure into exactly one of
NOT-IMPLEMENTED / TRANSLATION-BUG / INTENTIONAL-DIVERGENCE (triage.py).

Crash isolation (spec Phase-B acceptance): any leg that crashes, times out, or
fails to print its ``PKG119B_LEG PASS`` sentinel is recorded as a crashed
feature and the run CONTINUES. A crashed feature also back-propagates a note to
close its Phase-A UNKNOWN cell.

One command:
    python -m benchmarks.blender_parity.harness \
        --matrix docs/blender_parity/coverage_matrix.json \
        --out test_results/blender_parity_diff

The metric/triage/report layer is import-safe and unit-tested without Blender or
a GPU (tests/test_blender_parity_harness.py). Only ``run()`` needs Blender.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
# reference_bank is a sibling package under benchmarks/; make it importable.
sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.blender_parity import triage as T  # noqa: E402

SENTINEL = "PKG119B_LEG"
DEFAULT_MATRIX = _REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json"
_RENDER_LEG = Path(__file__).resolve().parent / "render_leg.py"


# --------------------------------------------------------------------------- #
# Feature selection (pure)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Feature:
    category: str
    feature: str
    bl_idname: str
    phase_a_bucket: str  # SUPPORTED or APPROXIMATED (worst-case across sockets)

    @property
    def key(self) -> str:
        return f"{self.category}:{self.feature}"


# Categories that have a differential visual scene generator. Others (e.g.
# render_settings sampling knobs) have no meaningful oracle diff and are recorded
# with a skip_reason per pkg71 discipline rather than silently dropped.
RENDERABLE_CATEGORIES = {"shader_node", "light", "camera", "world"}


def select_features(matrix_rows: list[dict[str, Any]]) -> list[Feature]:
    """Dedup the SUPPORTED/APPROXIMATED matrix rows to unique features.

    A feature is APPROXIMATED if ANY of its rows is APPROXIMATED (worst case),
    else SUPPORTED. bl_idname is taken from the first row that carries one.
    """
    buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
    idnames: dict[tuple[str, str], str] = {}
    for r in matrix_rows:
        cls = r.get("classification")
        if cls not in ("SUPPORTED", "APPROXIMATED"):
            continue
        k = (r["category"], r["feature"])
        buckets[k].add(cls)
        if not idnames.get(k) and r.get("bl_idname"):
            idnames[k] = r["bl_idname"]
    feats: list[Feature] = []
    for (cat, feat), cls_set in sorted(buckets.items()):
        bucket = "APPROXIMATED" if "APPROXIMATED" in cls_set else "SUPPORTED"
        feats.append(Feature(cat, feat, idnames.get((cat, feat), ""), bucket))
    return feats


# --------------------------------------------------------------------------- #
# Per-feature result (pure data)
# --------------------------------------------------------------------------- #

@dataclass
class FeatureResult:
    category: str
    feature: str
    phase_a_bucket: str
    status: str  # "pass" | "fail" | "crash" | "skip"
    ssim: float | None = None
    delta_e: float | None = None
    ratio: tuple[float, float, float] | None = None
    triage_bucket: str | None = None
    triage_reason: str | None = None
    skip_reason: str | None = None
    notes: str = ""
    # SPP-escalation audit trail (populated only for noise-suspect re-renders).
    escalated: bool = False
    samples_low: int | None = None
    samples_high: int | None = None
    ssim_high_spp: float | None = None
    delta_e_high_spp: float | None = None


# --------------------------------------------------------------------------- #
# Metric comparison (reuses pkg104 reference_bank; NO new metric stack)
# --------------------------------------------------------------------------- #

def per_channel_ratio(actual, reference) -> tuple[float, float, float]:
    """Mean Astroray/Cycles ratio per RGB channel (trivial - not a new metric)."""
    import numpy as np
    a = actual.reshape(-1, 3).mean(axis=0)
    r = reference.reshape(-1, 3).mean(axis=0)
    out = []
    for i in range(3):
        out.append(float(a[i] / r[i]) if r[i] > 1e-9 else float("nan"))
    return (out[0], out[1], out[2])


def _metrics(actual, reference) -> tuple[float, float, tuple[float, float, float]]:
    """(ssim, mean dE2000, per-channel ratio) via the pkg104 reference bank."""
    from benchmarks.reference_bank.metrics import compute_ssim, compute_delta_e_2000
    ssim, _ = compute_ssim(actual, reference)
    delta_e, _ = compute_delta_e_2000(actual, reference)
    ratio = per_channel_ratio(actual, reference)
    return ssim, delta_e, ratio


def compare_and_triage(feat: Feature, actual, reference) -> FeatureResult:
    """Run the reference-bank metrics, gate, and triage a single feature.

    This is the SINGLE-spp pass (no escalation); ``run()`` layers the SPP-
    escalation re-render on top for noise-suspect TRANSLATION-BUG cells.
    """
    ssim, delta_e, ratio = _metrics(actual, reference)

    gr = T.gate(ssim, delta_e, ratio)
    res = FeatureResult(
        category=feat.category, feature=feat.feature,
        phase_a_bucket=feat.phase_a_bucket,
        status="pass" if gr.passed else "fail",
        ssim=ssim, delta_e=delta_e, ratio=ratio,
    )
    if not gr.passed:
        bucket, reason = T.triage(feat.feature, feat.phase_a_bucket, gr)
        res.triage_bucket = bucket
        res.triage_reason = reason
    return res


# --------------------------------------------------------------------------- #
# Reference-scene non-vacuity checks (north-star gate (c): "scene-specific
# non-vacuity checks... so a black or missing feature cannot pass")
#
# Pure functions on a linear HxWx3 array; ROIs are FRACTIONAL (0-1) so they
# resolve against any render resolution (the Astroray CPU sanity leg renders
# at <=320x180 while the pinned scene settings are 512x512 / 640x360).
# Thresholds were tuned against real cornell_interior/material_zoo/
# hdri_exterior_hair Cycles-CPU and Astroray-CPU renders (see the PR
# description): a pipeline that silently drops the feature (grey checker
# backdrop, black world, no hair strands) collapses these metrics far below
# the margin a correct render clears.
# --------------------------------------------------------------------------- #

# material_zoo: box around the CheckerGenerated sphere (row 3, col 1 of the
# 4x4 grid), pinned camera/resolution 640x360.
CHECKER_ROI = (235 / 640, 225 / 360, 330 / 640, 285 / 360)
CHECKER_DARK_LUMINANCE = 0.03   # linear
CHECKER_MIN_DARK_FRACTION = 0.05  # measured: real checker ~0.14-0.15, flat control ~0.00-0.03

# hdri_exterior_hair: top strip, above the hair apex at every camera/res the
# scene is rendered at - guaranteed sky-only (no scalp/hair/glass/ground).
HDRI_BACKGROUND_ROI = (0.0, 0.0, 1.0, 30 / 360)
HDRI_MIN_BACKGROUND_MEAN = 0.05  # linear; matches the north-star doc's own gate (c) wording

# hdri_exterior_hair: a band strictly ABOVE the bald scalp sphere's apex
# (verified against build_hdri_exterior_hair_scene's pinned geometry+camera:
# bald apex projects to y=92px of 360, hair strands can reach y=44px) so it
# can ONLY show non-background pixels if Curves/hair actually rendered.
HAIR_ROI = (245 / 640, 44 / 360, 365 / 640, 90 / 360)
HAIR_COVERAGE_TOL = 0.05
HAIR_MIN_COVERAGE_FRACTION = 0.02  # measured: real hair ~0.19-0.38, geometrically 0 if strands are absent


def _resolve_roi(img, roi: tuple[float, float, float, float]):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = roi
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def checker_contrast_ok(img, roi=CHECKER_ROI, dark_luminance=CHECKER_DARK_LUMINANCE,
                        min_dark_fraction=CHECKER_MIN_DARK_FRACTION) -> tuple[bool, float]:
    """material_zoo non-vacuity: the checker sphere must show a genuine
    bimodal (near-black cell / near-white cell) pattern, not the flat grey a
    silently-dropped checker node produces. Returns (ok, dark_fraction)."""
    patch = _resolve_roi(img, roi)
    lum = patch.mean(axis=-1)
    dark_fraction = float((lum < dark_luminance).mean())
    return dark_fraction >= min_dark_fraction, dark_fraction


def hdri_background_ok(img, roi=HDRI_BACKGROUND_ROI,
                       min_mean=HDRI_MIN_BACKGROUND_MEAN) -> tuple[bool, float]:
    """hdri_exterior_hair non-vacuity: the environment texture must actually
    illuminate the background - a black/near-black world is the gate's own
    definition of a failed HDRI leg. Returns (ok, mean)."""
    patch = _resolve_roi(img, roi)
    mean = float(patch.mean())
    return mean > min_mean, mean


def hair_pixel_coverage_ok(img, roi=HAIR_ROI, background_roi=HDRI_BACKGROUND_ROI,
                           tol=HAIR_COVERAGE_TOL,
                           min_fraction=HAIR_MIN_COVERAGE_FRACTION) -> tuple[bool, float]:
    """hdri_exterior_hair non-vacuity: ``roi`` sits strictly above the bald
    scalp sphere's silhouette, so it can only contain non-background pixels
    if the Curves/hair strands rendered. Returns (ok, coverage_fraction)."""
    import numpy as np
    patch = _resolve_roi(img, roi)
    bg_patch = _resolve_roi(img, background_roi)
    bg_ref = bg_patch.reshape(-1, patch.shape[-1]).mean(axis=0)
    diff = np.abs(patch - bg_ref).sum(axis=-1)
    coverage = float((diff > tol).mean())
    return coverage > min_fraction, coverage


def _run_non_vacuity_checks(scene_id: str, npy_path: Path) -> dict:
    """Dispatch the applicable non-vacuity check(s) for one scene's rendered
    .npy (linear HxWx3 float32). cornell_interior has no scene-specific
    texture/HDRI/hair feature to probe, so it gets an empty dict."""
    import numpy as np
    img = np.load(npy_path)
    checks: dict[str, Any] = {}
    if scene_id == "material_zoo":
        ok, val = checker_contrast_ok(img)
        checks["checker_contrast"] = {"ok": ok, "dark_fraction": val}
    elif scene_id == "hdri_exterior_hair":
        ok_bg, val_bg = hdri_background_ok(img)
        checks["hdri_background"] = {"ok": ok_bg, "mean": val_bg}
        ok_hair, val_hair = hair_pixel_coverage_ok(img)
        checks["hair_coverage"] = {"ok": ok_hair, "coverage_fraction": val_hair}
    return checks


# --------------------------------------------------------------------------- #
# Render-leg orchestration (needs Blender)
# --------------------------------------------------------------------------- #

def _find_blender() -> Path | None:
    env = os.environ.get("BLENDER_EXE", "")
    if env and Path(env).is_file():
        return Path(env)
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    # pkg178-D1: Blender 5.2 LTS is the parity oracle (installed alongside 5.1);
    # prefer it, falling back to 5.1/5.0 only if 5.2 is absent.
    for c in (r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"):
        if Path(c).is_file():
            return Path(c)
    return None


def _pyd_dir(root: Path) -> Path | None:
    # The Astroray leg imports astroray INSIDE Blender's Python (render_leg),
    # so it MUST be an OpenMP-OFF build or MinGW libgomp deadlocks in Blender
    # (memory mingw_openmp_blender_deadlock). Prefer the addon build dirs
    # (build_blender_addon.py forces -DASTRORAY_DISABLE_OPENMP=ON) over the
    # plain build_cuda (OpenMP ON — deadlocks headless-Blender renders).
    for cand in (root / "build_blender_addon_cuda", root / "build_blender_addon_tcnn",
                 root / "build_blender_addon", root / "build_cuda",
                 root / "build_cuda" / "Release"):
        if list(cand.glob("astroray*.pyd")):
            return cand
    return None


def _run_render_leg_script(blender: Path, script_args: list[str], env: dict,
                            timeout: int) -> tuple[bool, str, str]:
    """Spawn render_leg.py with arbitrary CLI args (used by the reference-scene
    export/verify flow, which doesn't fit the per-feature (category, feature,
    engine) shape of ``_run_leg``). Returns (ok, full_combined_output, tail)."""
    cmd = [str(blender), "--background", "--factory-startup",
           "--python", str(_RENDER_LEG), "--"] + script_args
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        msg = f"TIMEOUT after {timeout}s"
        return False, msg, msg
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ok = f"{SENTINEL} FAIL" not in combined and f"{SENTINEL} PASS" in combined
    return ok, combined, combined[-3000:]


def _npy_to_png(npy_path: Path, png_path: Path) -> None:
    """sRGB-encode a linear .npy render for the manifest's small reference
    PNGs (render_leg.py's own PNG write is skipped - Blender's bundled Python
    has no PIL - so this runs in the harness's own Python instead). Deletes
    the (much larger, float32) .npy afterwards - refs/ is meant to hold only
    the small PNGs."""
    import numpy as np
    from PIL import Image
    px = np.load(npy_path)
    srgb = np.where(px <= 0.0031308, px * 12.92,
                    1.055 * np.clip(px, 0, None) ** (1 / 2.4) - 0.055)
    Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(png_path)
    npy_path.unlink(missing_ok=True)


def export_reference_scenes(scenes_dir: Path, *, timeout: int = 600) -> int:
    """Pillar-4 exit-gate (c): build+save the three pinned reference .blend
    files, verify each reopens headlessly (object/node census), render each
    with Cycles CPU at 32spp into ``scenes_dir/refs`` and attempt a tiny
    Astroray CPU render. A thrown Astroray exception is RECORDED in the
    manifest, not treated as a harness failure or "fixed" here (task
    instruction: that IS a finding). Writes ``scenes_dir/manifest.json``.

    Returns 0 iff every .blend exported, reopened, and rendered clean under
    Cycles CPU (the addon-CPU column is diagnostic, not gating).
    """
    import hashlib
    from benchmarks.blender_parity import scene_library

    blender = _find_blender()
    if blender is None:
        print("[pkg119b] Blender not found (set BLENDER_EXE) - cannot export.",
              file=sys.stderr)
        return 2

    scenes_dir = Path(scenes_dir).resolve()
    scenes_dir.mkdir(parents=True, exist_ok=True)
    refs_dir = scenes_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if build_dir is not None:
        env["ASTRORAY_PYD_DIR"] = str(build_dir)
        env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")
    # A worktree checkout (memory: parallel-agent-worktree-contamination) has
    # no local build_* dir of its own; honour a caller-supplied
    # ASTRORAY_PYD_DIR pointing at the shared build instead of concluding
    # "no build" whenever _pyd_dir(_REPO_ROOT) comes up empty.
    have_astroray_build = build_dir is not None or bool(env.get("ASTRORAY_PYD_DIR"))

    manifest: dict[str, Any] = {"scenes": {}}
    all_ok = True
    for scene_id, spec in scene_library.REFERENCE_SCENES.items():
        print(f"[pkg119b] exporting {scene_id} ...", flush=True)
        entry: dict[str, Any] = {}
        blend_path = scenes_dir / f"{scene_id}.blend"

        ok, _combined, tail = _run_render_leg_script(
            blender, ["--category", "reference_scene", "--feature", scene_id,
                      "--export-blend", str(blend_path)], env, timeout)
        if not ok or not blend_path.exists():
            entry["export_error"] = tail
            manifest["scenes"][scene_id] = entry
            all_ok = False
            continue

        entry["blend_path"] = str(blend_path.relative_to(_REPO_ROOT)).replace("\\", "/")
        entry["sha256"] = hashlib.sha256(blend_path.read_bytes()).hexdigest()
        entry["settings"] = {"res_x": spec["res_x"], "res_y": spec["res_y"],
                             "samples": spec["samples"], "saved_default_engine": "CYCLES"}

        # Reopen headlessly + object/node census.
        ok_r, combined_r, tail_r = _run_render_leg_script(
            blender, ["--load-blend", str(blend_path), "--report-only"], env, timeout)
        report: dict[str, Any] = {}
        if ok_r:
            for line in combined_r.splitlines():
                prefix = f"{SENTINEL} REPORT "
                if line.startswith(prefix):
                    report = json.loads(line[len(prefix):])
                    break
        entry["reopen_verified"] = ok_r and bool(report)
        if not entry["reopen_verified"]:
            entry["reopen_error"] = tail_r
            all_ok = False
        entry["triangle_count"] = report.get("triangle_count")
        entry["curve_count"] = report.get("curve_count")
        entry["curve_point_count"] = report.get("curve_point_count")
        entry["object_counts"] = report.get("object_counts")
        entry["node_ids"] = report.get("node_ids")

        # Cycles CPU reference render at 32 spp (task-pinned).
        cycles_stem = refs_dir / f"{scene_id}_cycles_cpu"
        ok_c, _combined_c, tail_c = _run_render_leg_script(
            blender, ["--load-blend", str(blend_path), "--engine", "CYCLES",
                      "--out", str(cycles_stem), "--res", str(spec["res_x"]),
                      "--res-y", str(spec["res_y"]), "--samples", "32",
                      "--device", "cpu"], env, timeout)
        cycles_ok = ok_c and cycles_stem.with_suffix(".npy").exists()
        if cycles_ok:
            entry["cycles_cpu_32spp"] = {
                "ok": True,
                "non_vacuity": _run_non_vacuity_checks(scene_id, cycles_stem.with_suffix(".npy")),
                "png": str(cycles_stem.with_suffix(".png").relative_to(_REPO_ROOT)).replace("\\", "/"),
            }
            _npy_to_png(cycles_stem.with_suffix(".npy"), cycles_stem.with_suffix(".png"))
        else:
            entry["cycles_cpu_32spp"] = {"ok": False, "error": tail_c}
            all_ok = False

        # Astroray CPU tiny attempt (<=320x180, <=32spp) - diagnostic only,
        # never gates this function's return value. An exception here is a
        # finding to report, not something this task fixes.
        if not have_astroray_build:
            entry["astroray_cpu_attempt"] = {"ok": False, "error": "no astroray*.pyd build found"}
        else:
            astro_res_x, astro_res_y = min(320, spec["res_x"]), min(180, spec["res_y"])
            astro_stem = refs_dir / f"{scene_id}_astroray_cpu"
            ok_a, _combined_a, tail_a = _run_render_leg_script(
                blender, ["--load-blend", str(blend_path), "--engine", "CUSTOM_RAYTRACER",
                          "--out", str(astro_stem), "--res", str(astro_res_x),
                          "--res-y", str(astro_res_y), "--samples", "16",
                          "--device", "cpu"], env, timeout)
            astro_ok = ok_a and astro_stem.with_suffix(".npy").exists()
            if astro_ok:
                entry["astroray_cpu_attempt"] = {
                    "ok": True,
                    "non_vacuity": _run_non_vacuity_checks(scene_id, astro_stem.with_suffix(".npy")),
                    "png": str(astro_stem.with_suffix(".png").relative_to(_REPO_ROOT)).replace("\\", "/"),
                }
                _npy_to_png(astro_stem.with_suffix(".npy"), astro_stem.with_suffix(".png"))
            else:
                entry["astroray_cpu_attempt"] = {"ok": False, "traceback_tail": tail_a}

        manifest["scenes"][scene_id] = entry
        print(f"    sha256={entry['sha256'][:12]} tris={entry['triangle_count']} "
              f"reopen={entry['reopen_verified']} cycles_cpu={cycles_ok} "
              f"astroray_cpu={entry['astroray_cpu_attempt']['ok']}", flush=True)

    manifest_path = scenes_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[pkg119b] wrote {manifest_path}", flush=True)
    return 0 if all_ok else 1


def _run_leg(blender: Path, feat: Feature, engine: str, out_stem: Path,
             res: int, samples: int, timeout: int, env: dict) -> tuple[bool, str]:
    """Spawn one headless-Blender leg. Returns (ok, log_tail)."""
    cmd = [
        str(blender), "--background", "--factory-startup",
        "--python", str(_RENDER_LEG), "--",
        "--category", feat.category, "--feature", feat.feature,
        "--bl-idname", feat.bl_idname, "--engine", engine,
        "--out", str(out_stem), "--res", str(res), "--samples", str(samples),
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s"
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ok = f"{SENTINEL} FAIL" not in combined and f"{SENTINEL} PASS" in combined
    ok = ok and out_stem.with_suffix(".npy").exists()
    return ok, combined[-1500:]


def _render_pair(blender: Path, feat: Feature, renders_dir: Path, res: int,
                 samples: int, timeout: int, env: dict, *, suffix: str = ""):
    """Render both engine legs for one feature. Returns (arrays, bad_engine,
    log_tail): arrays is a {engine: np.ndarray} dict on success, else None with
    the engine that failed and its log tail."""
    import numpy as np
    arrays = {}
    for engine in ("CYCLES", "CUSTOM_RAYTRACER"):
        stem = renders_dir / f"{feat.category}__{feat.feature}__{engine.lower()}{suffix}"
        ok, log_tail = _run_leg(blender, feat, engine, stem, res, samples, timeout, env)
        if not ok:
            return None, engine, log_tail
        arrays[engine] = np.load(stem.with_suffix(".npy"))
    return arrays, None, ""


def run(matrix_path: Path, out_dir: Path, *, res: int = 128, samples: int = 64,
        timeout: int = 300, include_composites: bool = True) -> int:
    blender = _find_blender()
    if blender is None:
        print("[pkg119b] Blender not found (set BLENDER_EXE) - cannot run legs.",
              file=sys.stderr)
        return 2
    build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if build_dir is None:
        print("[pkg119b] no astroray*.pyd found - build the addon first.",
              file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["ASTRORAY_PYD_DIR"] = str(build_dir)
    env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")

    matrix_rows = json.loads(Path(matrix_path).read_text(encoding="utf-8"))
    features = select_features(matrix_rows)
    if include_composites:
        from benchmarks.blender_parity import scene_library
        for name in scene_library.COMPOSITE_SCENES:
            features.append(Feature("composite", name, "", "SUPPORTED"))

    # Resolve to ABSOLUTE: render_leg runs inside Blender whose CWD is NOT the
    # harness CWD, so a relative out-stem makes Blender save the .exr under a
    # different root (observed: C:\test_results\...) than render_leg then looks
    # for -> "no render output". Absolute stems make both legs agree.
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(exist_ok=True)

    results: list[FeatureResult] = []
    for feat in features:
        print(f"[pkg119b] {feat.key} ...", flush=True)
        if feat.category not in RENDERABLE_CATEGORIES and feat.category != "composite":
            results.append(FeatureResult(
                feat.category, feat.feature, feat.phase_a_bucket, "skip",
                skip_reason=f"no differential scene for category {feat.category} "
                            "(sampling/meta feature - no oracle visual diff)"))
            continue

        arrays, bad_engine, log_tail = _render_pair(
            blender, feat, renders_dir, res, samples, timeout, env)
        if arrays is None:
            results.append(FeatureResult(
                feat.category, feat.feature, feat.phase_a_bucket, "crash",
                notes=f"{bad_engine} leg did not PASS; back-propagates to close "
                      f"Phase-A UNKNOWN cell. log tail:\n{log_tail}"))
            continue

        try:
            res_ft = compare_and_triage(feat, arrays["CUSTOM_RAYTRACER"], arrays["CYCLES"])
        except Exception as exc:  # noqa: BLE001
            results.append(FeatureResult(
                feat.category, feat.feature, feat.phase_a_bucket, "crash",
                notes=f"metric comparison raised {type(exc).__name__}: {exc}"))
            continue

        # SPP-escalation discriminator: a FAIL that would be TRANSLATION-BUG but
        # has in-band ratios + small dE is a noise-suspect. Re-render both legs at
        # 4x spp and let triage decide NOISE-LIMITED vs a real (plateauing) bug.
        if (res_ft.triage_bucket == T.TRANSLATION_BUG
                and T.is_noise_suspect(res_ft.ratio, res_ft.delta_e)):
            high_spp = samples * T.ESCALATION_FACTOR
            print(f"    noise-suspect -> escalating {samples}->{high_spp} spp",
                  flush=True)
            hi_arrays, hi_bad, hi_log = _render_pair(
                blender, feat, renders_dir, res, high_spp, timeout, env, suffix="__hi")
            if hi_arrays is not None:
                h_ssim, h_de, h_ratio = _metrics(
                    hi_arrays["CUSTOM_RAYTRACER"], hi_arrays["CYCLES"])
                h_gr = T.gate(h_ssim, h_de, h_ratio)
                esc = T.Escalation(
                    ssim_low=res_ft.ssim, ssim_high=h_ssim,
                    spp_low=samples, spp_high=high_spp,
                    ratio_high=h_ratio, delta_e_high=h_de)
                bucket, reason = T.triage(
                    feat.feature, feat.phase_a_bucket, h_gr, escalation=esc)
                res_ft.triage_bucket = bucket
                res_ft.triage_reason = reason
                res_ft.escalated = True
                res_ft.samples_low = samples
                res_ft.samples_high = high_spp
                res_ft.ssim_high_spp = h_ssim
                res_ft.delta_e_high_spp = h_de
            else:
                res_ft.notes += (f"escalation re-render crashed on {hi_bad} leg; "
                                 f"keeping TRANSLATION-BUG. log tail: {hi_log[:200]}")

        results.append(res_ft)
        esc_note = (f" [esc {res_ft.samples_low}->{res_ft.samples_high} spp, "
                    f"ssim->{res_ft.ssim_high_spp:.4f}]" if res_ft.escalated else "")
        print(f"    {res_ft.status.upper()} ssim={res_ft.ssim:.4f} "
              f"dE={res_ft.delta_e:.3f}"
              + (f" -> {res_ft.triage_bucket}" if res_ft.triage_bucket else "")
              + esc_note,
              flush=True)

    write_reports(results, out_dir)
    # A crashed feature is a hard failure of "no crash on any feature"; a
    # triaged FAIL is expected output, not a harness failure.
    crashes = [r for r in results if r.status == "crash"]
    return 1 if crashes else 0


# --------------------------------------------------------------------------- #
# Reports (pure)
# --------------------------------------------------------------------------- #

def summarize(results: list[FeatureResult]) -> dict[str, Any]:
    status = Counter(r.status for r in results)
    triage = Counter(r.triage_bucket for r in results if r.triage_bucket)
    return {
        "total": len(results),
        "status": dict(status),
        "triage": dict(triage),
        "follow_up_candidates": [
            {"feature": f"{r.category}:{r.feature}", "bucket": r.triage_bucket,
             "reason": r.triage_reason}
            for r in results
            if r.triage_bucket in (T.NOT_IMPLEMENTED, T.TRANSLATION_BUG)
        ],
    }


def write_reports(results: list[FeatureResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    payload = {"summary": summary, "features": [asdict(r) for r in results]}
    (out_dir / "triage_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Blender Differential Parity - Triage Report (pkg119 Phase B)",
        "",
        "Cycles (oracle) vs CUSTOM_RAYTRACER, gated on reference-bank SSIM/dE2000.",
        "",
        "## Summary",
        "",
        f"- Total features: {summary['total']}",
        f"- Status: {summary['status']}",
        f"- Triage: {summary['triage']}",
        "",
        "## Follow-up-package candidates (NOT-IMPLEMENTED / TRANSLATION-BUG)",
        "",
    ]
    if summary["follow_up_candidates"]:
        for c in summary["follow_up_candidates"]:
            lines.append(f"- **{c['feature']}** [{c['bucket']}] - {c['reason']}")
    else:
        lines.append("_none_")
    lines += ["", "## Per-feature results", "",
              "| Feature | Phase-A | Status | SSIM | dE2000 | Triage |",
              "|---------|---------|--------|------|--------|--------|"]
    for r in results:
        ssim = f"{r.ssim:.4f}" if r.ssim is not None else "-"
        de = f"{r.delta_e:.3f}" if r.delta_e is not None else "-"
        tri = r.triage_bucket or (r.skip_reason or "") if r.status != "pass" else ""
        lines.append(f"| {r.category}:{r.feature} | {r.phase_a_bucket} | "
                     f"{r.status} | {ssim} | {de} | {tri} |")
        if r.escalated:
            lines.append(
                f"  - SPP-escalation: {r.samples_low}->{r.samples_high} spp, "
                f"SSIM {r.ssim:.4f}->{r.ssim_high_spp:.4f}, "
                f"dE {r.delta_e:.3f}->{r.delta_e_high_spp:.3f}")
        if r.status == "crash" and r.notes:
            lines.append(f"  - crash: {r.notes.splitlines()[0]}")
    (out_dir / "triage_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[pkg119b] wrote {out_dir / 'triage_report.json'} and .md", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Blender differential parity harness (pkg119 Phase B).")
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--out", type=Path, default=_REPO_ROOT / "test_results" / "blender_parity_diff")
    p.add_argument("--res", type=int, default=128)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--no-composites", action="store_true")
    p.add_argument("--export-blend", type=Path, default=None,
                   help="north-star gate (c): build+save the pinned "
                        "cornell_interior/material_zoo/hdri_exterior_hair "
                        ".blend corpus into this directory (with a "
                        "manifest.json) instead of running the differential "
                        "matrix")
    args = p.parse_args(argv)
    if args.export_blend is not None:
        return export_reference_scenes(args.export_blend, timeout=args.timeout)
    return run(args.matrix, args.out, res=args.res, samples=args.samples,
               timeout=args.timeout, include_composites=not args.no_composites)


if __name__ == "__main__":
    sys.exit(main())
