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
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
# reference_bank is a sibling package under benchmarks/; make it importable.
sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.blender_parity import triage as T  # noqa: E402

SENTINEL = "PKG119B_LEG"
DEFAULT_MATRIX = _REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json"
_RENDER_LEG = Path(__file__).resolve().parent / "render_leg.py"
GATE_B_RUNNER_RESULT_SCHEMA = "pkg278.gate_b.runner_result.v1"


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
# 4x4 grid), pinned camera/resolution 640x360. Re-measured 2026-09-08 (pkg119b
# harness pixel-orientation fix) via bpy_extras.object_utils.world_to_camera_view
# on the sphere's actual world location/radius (scene_library.build_material_zoo_scene:
# sphere_at(1, 3) -> (-0.7, 2.1, 0.5), r=0.5): projects to row 83-138 of 360 /
# col 247-308 of 640 - the OLD box (row 225-285) was correct only under the
# pre-fix bottom-up array reading and framed empty background/shadow between
# other spheres once row 0 became the top (verified by cropping both boxes
# out of the rendered PNG - see PR).
CHECKER_ROI = (230 / 640, 75 / 360, 325 / 640, 145 / 360)
CHECKER_DARK_LUMINANCE = 0.03   # linear
CHECKER_MIN_DARK_FRACTION = 0.05  # measured (post-fix, corrected ROI): real checker ~0.14-0.15, flat control ~0.00-0.03

# hdri_exterior_hair: top strip, above the hair apex at every camera/res the
# scene is rendered at - guaranteed sky-only (no scalp/hair/glass/ground).
HDRI_BACKGROUND_ROI = (0.0, 0.0, 1.0, 30 / 360)
# Floor re-derived 2026-09-08 (pkg119b harness pixel-orientation fix). Before
# the render_leg.py bottom-up/top-down orientation fix this ROI actually
# sampled the near-GROUND strip, not the sky, which is why the old floor
# (0.05) and the old measured means (Cycles 0.121, Astroray-pre-258 0.047)
# were both meaningless for a "sky-only" check.
#
# .astroray_plan/docs/hdri-background-gap-diagnosis-2026-09-07.md experiment
# 1c reports an independent ground-truth `.hdr` decode of 0.033811 for "this
# ROI", but that decode script (test_results/2026-09-07-hdri-gap/sample_hdr.py
# in the main checkout) has its OWN, separate v-axis flip bug: it indexes the
# OpenCV-loaded (top-down, row 0 = file's first/TOP row) pixel array directly
# with `vp = v * H`, while Cycles' v=1 means the TOP of the image - so its
# samples are taken from the mirrored (bottom-hemisphere-facing) direction.
# Verified here (2026-09-08) two independent ways: (1) a round-trip camera-ray
# check (cast the reconstructed ray 10 units out, feed it back through
# bpy_extras.object_utils.world_to_camera_view - the row/col recovers exactly,
# so the ray directions themselves are correct) and (2) sampling
# samples/test_env.hdr with `vp = (1.0 - v) * H` instead reproduces the ACTUAL
# rendered Cycles pixel values for this ROI to <1% (32-spp MC noise), while
# the unflipped indexing does not (matches neither in value nor in hue - the
# unflipped decode is warm/ground-toned, the real sky here is blue/grey
# cloud). The correct ground-truth sky mean for this ROI is therefore
# ~0.184 (Cycles 0.18370, pre-pkg258 Astroray 0.18382 - both agree, since a
# direct camera-miss env lookup does not depend on env-NEE), not 0.034; the
# diagnosis doc's experiment 1c figure (and anything reasoning from a "true
# ground-truth sky mean 0.034" for this scene/camera) should be treated as
# stale pending its own fix. Floor is set to roughly half of the verified
# ground-truth mean (0.184 / 2 = 0.092) so real MC noise at the pinned
# 32-64spp doesn't false-positive-fail the check while a black/near-black
# world (the failure mode this guards against) still clears no bar.
HDRI_MIN_BACKGROUND_MEAN = 0.092  # linear; see derivation above

# hdri_exterior_hair: a band strictly ABOVE the bald scalp sphere's apex
# (verified against build_hdri_exterior_hair_scene's pinned geometry+camera:
# bald apex projects to y=92px of 360, hair strands can reach y=44px) so it
# can ONLY show non-background pixels if Curves/hair actually rendered. This
# ROI was already written top-down (y=44 above y=92, matching
# world_to_camera_view + the render_leg.py orientation fix) so its box is
# unchanged by the fix; only the coverage numbers below were re-measured.
HAIR_ROI = (245 / 640, 44 / 360, 365 / 640, 90 / 360)
HAIR_COVERAGE_TOL = 0.05
HAIR_MIN_COVERAGE_FRACTION = 0.02  # re-measured 2026-09-08 (post-fix): real hair
# ~0.89-0.90 (this tight box is centred on the fringe of strands against sky,
# so most of it differs from the flat sky reference - see PR crop), 0 if
# strands are absent. The old comment's 0.19-0.38 was measured against the
# pre-fix ground/shadow band, not hair; the 0.02 gate floor itself does not
# need to change (it is already far below either era's numbers).


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


def _npy_to_png(npy_path: Path, png_path: Path, *, preserve_source: bool = False) -> None:
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
    if not preserve_source:
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
    for scene_id, spec in scene_library.HISTORICAL_EXPORT_SCENES.items():
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


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_ref(path: Path, base: Path) -> dict[str, str]:
    return {"path": str(path.resolve().relative_to(base.resolve())).replace("\\", "/"), "sha256": _sha256(path)}


def _gate_c_freeze(manifest_path: Path) -> dict[str, Any]:
    """Freeze the only admissible trio before spawning Blender.

    A gate scene carries its own declared ROIs and non-vacuity probes.  This is
    deliberately stricter than the general corpus manifest: a normal corpus
    scene is not automatically gate-(c) evidence.
    """
    from benchmarks.blender_parity import scene_library
    roles = scene_library.resolve_gate_c_roles(manifest_path)
    frozen: dict[str, Any] = {}
    for role, entry in roles.items():
        cfg = entry.get("gate_c")
        if not isinstance(cfg, dict) or not isinstance(cfg.get("rois"), dict):
            raise ValueError(f"gate-c role {role} lacks declared gate_c ROIs/non-vacuity")
        probes = cfg.get("non_vacuity")
        if not isinstance(probes, list) or (role != "materials_hall" and not probes):
            raise ValueError(f"gate-c role {role} lacks declared non-vacuity probes")
        for name, roi in cfg["rois"].items():
            if (not isinstance(name, str) or not isinstance(roi, list) or len(roi) != 4
                    or any(not isinstance(x, (int, float)) or isinstance(x, bool) or x < 0 or x > 1 for x in roi)
                    or roi[0] >= roi[2] or roi[1] >= roi[3]):
                raise ValueError(f"gate-c role {role} has invalid ROI {name!r}")
        if role == "world_sky:terrace-with-hair":
            for key, census_key in (("expected_curve_count", "curve_count"),
                                    ("expected_curve_point_count", "curve_point_count")):
                expected = cfg.get(key)
                if (not isinstance(expected, int) or isinstance(expected, bool)
                        or entry.get(census_key) != expected):
                    raise ValueError(f"gate-c terrace role has invalid {key}")
        controls = cfg.get("controls", [])
        if role != "materials_hall" and (not isinstance(controls, list) or not controls):
            raise ValueError(f"gate-c role {role} lacks declared counterfactual controls")
        if any(not isinstance(c, dict) or not isinstance(c.get("kind"), str) or not isinstance(c.get("mask"), dict) for c in controls):
            raise ValueError(f"gate-c role {role} has invalid counterfactual controls")
        seed = cfg.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed <= 0:
            raise ValueError(f"gate-c role {role} lacks a fixed non-zero seed")
        for control in controls:
            mask_kind = control["mask"].get("kind")
            if mask_kind == "rect" or mask_kind not in ("object_polygon", "curves", "sky_rays"):
                raise ValueError(f"gate-c role {role} has an invalid control mask")
            required = {"checker_flat": ("object", "material", "node"),
                        "hair_off": ("object",), "hdri_off": ("world", "node")}.get(control["kind"])
            if required is None or any(not isinstance(control.get(key), str) or not control[key] for key in required):
                raise ValueError(f"gate-c role {role} has incomplete {control['kind']} binding")
        frozen[role] = {"scene_id": entry["scene_id"] if "scene_id" in entry else role,
                        "blend_path": entry["blend_path"], "scene_sha256": entry["sha256"],
                        "assets": entry.get("assets", []), "settings": entry["settings"],
                        "rois": cfg["rois"], "non_vacuity": probes, "controls": controls,
                        "seed": seed,
                        "expected_curve_count": cfg.get("expected_curve_count"),
                        "expected_curve_point_count": cfg.get("expected_curve_point_count")}
    return frozen


def _gate_c_probe(img, probe: Mapping[str, Any], rois: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a declared simple image probe.  Values are recorded, never flags."""
    import numpy as np
    kind, roi_name = probe.get("kind"), probe.get("roi")
    roi = rois.get(roi_name)
    if kind not in ("checker", "hdri", "hair", "luminance_std") or not isinstance(roi, list):
        return {"kind": kind, "ok": False, "error": "invalid declared probe"}
    patch = _resolve_roi(img, tuple(roi))
    if patch.size == 0 or not np.isfinite(patch).all():
        return {"kind": kind, "ok": False, "error": "empty or non-finite ROI"}
    threshold = probe.get("min", 0.0)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        return {"kind": kind, "ok": False, "error": "invalid threshold"}
    if kind in ("checker", "luminance_std"):
        value = float(patch.mean(axis=-1).std())
    elif kind == "hdri":
        value = float(patch.mean())
    else:
        bg = rois.get(probe.get("background_roi"))
        if not isinstance(bg, list):
            return {"kind": kind, "ok": False, "error": "hair probe lacks background ROI"}
        reference = _resolve_roi(img, tuple(bg)).reshape(-1, 3).mean(axis=0)
        value = float((np.abs(patch - reference).sum(axis=-1) > float(probe.get("tolerance", .05))).mean())
    return {"kind": kind, "value": value, "threshold": float(threshold), "ok": value > float(threshold)}


def _gate_c_paired_probe(baseline, control, mask, probe: Mapping[str, Any]) -> dict[str, Any]:
    """Feature witness from a recorded negative control, never scene variance."""
    import numpy as np
    if baseline.shape != control.shape or mask.shape != baseline.shape[:2] or not np.isfinite(baseline).all() or not np.isfinite(control).all():
        return {"kind": probe.get("kind"), "ok": False, "error": "paired image/mask shape or finite check failed"}
    selected = mask.astype(bool)
    if not selected.any(): return {"kind": probe.get("kind"), "ok": False, "error": "empty frozen feature mask"}
    delta = np.abs(baseline - control).mean(axis=-1)[selected]
    floor, coverage = float(probe.get("min_delta", 0.0)), float(probe.get("min_coverage", 0.0))
    value, support = float(delta.mean()), float((delta > floor).mean())
    result = {"kind": probe.get("kind"), "value": value, "coverage": support,
              "threshold": floor, "coverage_threshold": coverage,
              "ok": value > floor and support > coverage}
    if probe.get("kind") == "checker":
        # The negative control is its midpoint.  A working checker must retain
        # both bright and dark phases around it; a uniform brightness change is
        # not a checker witness.  Rec. 709 coefficients are the standard
        # linear-RGB luminance weights (ITU-R BT.709-6, Table 3).
        signed = np.tensordot(baseline - control, np.array((.2126, .7152, .0722)), axes=([-1], [0]))[selected]
        positive, negative = float((signed > floor).mean()), float((signed < -floor).mean())
        result.update({"positive_coverage": positive, "negative_coverage": negative,
                       "ok": result["ok"] and positive > coverage and negative > coverage})
    return result


def _gate_leg_execution(cmd: list[str], returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """Retain raw process evidence independently from parsed leg output."""
    return {"command": cmd, "exit_code": returncode, "stdout": stdout, "stderr": stderr}


def _parse_gate_leg_report(output: str) -> tuple[dict[str, Any], str | None]:
    """Extract exactly one structured report even when Blender glues log lines."""
    marker = f"{SENTINEL} REPORT "
    offsets: list[int] = []
    start = 0
    while (offset := output.find(marker, start)) >= 0:
        offsets.append(offset)
        start = offset + len(marker)
    if len(offsets) != 1:
        return {}, f"expected one {marker!r} marker, found {len(offsets)}"
    try:
        report, _end = json.JSONDecoder().raw_decode(output[offsets[0] + len(marker):])
    except json.JSONDecodeError as exc:
        return {}, f"invalid sentinel report JSON: {exc.msg}"
    if not isinstance(report, dict):
        return {}, "sentinel report JSON is not an object"
    return report, None


def _run_gate_leg(blender: Path, args: list[str], env: dict[str, str], timeout: int) -> tuple[int, bool, dict[str, Any]]:
    cmd = [str(blender), "--background", "--factory-startup", "--python", str(_RENDER_LEG), "--"] + args
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, False, {"error": "timeout", "reason": f"TIMEOUT after {timeout}s",
                            "_gate_leg_execution": _gate_leg_execution(cmd, 124, stdout, stderr)}
    stdout, stderr = proc.stdout or "", proc.stderr or ""
    output = stdout + "\n" + stderr
    report, parse_error = _parse_gate_leg_report(output)
    if parse_error:
        report = {"error": "report_parse", "reason": parse_error}
    report["_gate_leg_execution"] = _gate_leg_execution(cmd, proc.returncode, stdout, stderr)
    return proc.returncode, f"{SENTINEL} PASS" in output and f"{SENTINEL} FAIL" not in output, report


def run_gate_c_trio(out_dir: Path, *, manifest_path: Path | None = None,
                    timeout: int = 1800, build_id: str = "", module_sha256: str = "",
                    addon_sha256: str = "") -> int:
    """Produce real six-leg F12 evidence.  The current missing terrace role is
    an intentional fail-closed result and starts no substitute renders."""
    manifest_path = Path(manifest_path or _REPO_ROOT / "benchmarks" / "reference_corpus" / "scenes" / "manifest.json").resolve()
    out_dir = Path(out_dir).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"schema": "pkg278.instrument.v2", "row": "c", "instrument": "trio_parity",
                               "scene_sha256": [], "build_id": build_id, "backend": ["CPU", "GPU"],
                               "settings": {}, "metric": {"ssim_min": .95, "channel_ratio_max": .05},
                               "threshold": {"roi_pct_max": 5.0, "ssim_min": .95}, "records": []}
    try:
        frozen = _gate_c_freeze(manifest_path)
        payload["scene_sha256"] = [frozen[r]["scene_sha256"] for r in sorted(frozen)]
        payload["settings"] = {"manifest": str(manifest_path), "frozen_roles": frozen}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload["freeze_error"] = str(exc)
        (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1
    import hashlib
    freeze_path = out_dir / "gate_c.freeze.json"
    if len(module_sha256) != 64:
        payload["freeze_error"] = "gate-c requires an expected 64-hex module SHA-256"
        (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1
    if not isinstance(build_id, str) or not build_id.strip():
        payload["freeze_error"] = "gate-c requires an expected non-empty build id"
        (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1
    if not addon_sha256:
        addon_sha256 = _sha256(_REPO_ROOT / "blender_addon" / "__init__.py")
    if len(addon_sha256) != 64:
        payload["freeze_error"] = "gate-c requires an expected 64-hex addon SHA-256"
        (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1
    freeze = {"manifest_path": str(manifest_path), "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              "build_id": build_id, "module_sha256": module_sha256,
              "addon_sha256": addon_sha256, "roles": frozen}
    freeze_path.write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    freeze_sha = _sha256(freeze_path)
    payload["freeze"] = _artifact_ref(freeze_path, out_dir)
    (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    blender = _find_blender()
    if blender is None:
        payload["freeze_error"] = "Blender not found"
        (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 2
    env = os.environ.copy(); pyd = _pyd_dir(_REPO_ROOT)
    if pyd: env["ASTRORAY_PYD_DIR"] = str(pyd)
    arrays: dict[tuple[str, str, str], Path] = {}
    masks: dict[tuple[str, str, str], Path] = {}
    for role, item in frozen.items():
        for backend in ("CPU", "GPU"):
          for control in ([{"kind": "baseline"}] + item.get("controls", [])):
            control_kind = control["kind"]
            leg_dir = out_dir / "legs" / f"{role.replace(':', '_')}_{backend.lower()}_{control_kind}"; leg_dir.mkdir(parents=True, exist_ok=True)
            stem = leg_dir / "render"
            for stale in (stem.with_suffix(".npy"), stem.with_suffix(".png")): stale.unlink(missing_ok=True)
            extra = [] if control_kind == "baseline" else ["--gate-c-control", control_kind, "--gate-c-mask-out", str(leg_dir / "feature_mask.npy")]
            code, sentinel, report = _run_gate_leg(blender, ["--corpus-manifest", str(manifest_path),
                "--corpus-scene", item["scene_id"], "--engine", "CUSTOM_RAYTRACER", "--device", backend.lower(),
                "--gate-c-freeze", str(freeze_path), "--gate-c-freeze-sha256", freeze_sha, "--gate-c-build-id", build_id, "--gate-c-seed", str(item.get("seed", 278)), "--out", str(stem)] + extra, env, timeout)
            npy, png = stem.with_suffix(".npy"), stem.with_suffix(".png")
            execution = report.pop("_gate_leg_execution", None)
            record: dict[str, Any] = {"kind": "f12_run", "control": control_kind, "role": role, "scene_id": item["scene_id"],
                "scene_sha256": item["scene_sha256"], "backend": backend, "build_id": build_id,
                "exit_code": code, "sentinel": SENTINEL if sentinel else "", "leg_report": report,
                "settings": {**item["settings"], "gate_c_rois": item["rois"], "gate_c_probes": item["non_vacuity"]}, "non_vacuity": [], "rois": []}
            if isinstance(execution, dict):
                for stream in ("stdout", "stderr"):
                    value = execution.get(stream)
                    if not isinstance(value, str):
                        value = ""
                    stream_path = leg_dir / f"{stream}.log"
                    stream_path.write_text(value, encoding="utf-8")
                    record[f"{stream}_artifact"] = _artifact_ref(stream_path, out_dir)
                execution_path = leg_dir / "execution.json"
                execution_path.write_text(json.dumps({"command": execution.get("command"),
                                                      "exit_code": execution.get("exit_code")}, indent=2), encoding="utf-8")
                record["execution_artifact"] = _artifact_ref(execution_path, out_dir)
            expected = {"corpus_scene": item["scene_id"], "blend_sha256": item["scene_sha256"], "freeze_sha256": freeze_sha,
                        "requested_device": backend.lower(), "effective_device": backend.lower(), "build_id": build_id, "module_sha256": module_sha256, "engine": "CUSTOM_RAYTRACER", "res_x": item["settings"]["res_x"], "res_y": item["settings"]["res_y"], "samples": item["settings"]["samples"], "resolved_seed": item.get("seed", 278), "animated_seed": False}
            actual_identity = (isinstance(report.get("module_path"), str) and
                               isinstance(report.get("addon_path"), str) and
                               len(str(report.get("module_sha256") or "")) == 64 and
                               report.get("addon_sha256") == addon_sha256 and
                               isinstance(report.get("bindings"), dict) and
                               isinstance(report.get("telemetry"), list))
            mask_path = leg_dir / "feature_mask.npy"
            control_ok = control_kind == "baseline" or (isinstance(report.get("mutation_receipt"), dict) and report["mutation_receipt"].get("kind") == control_kind and report["mutation_receipt"].get("ok") is True and isinstance(report.get("mask_receipt"), dict) and report["mask_receipt"].get("control") == control_kind and mask_path.is_file())
            if npy.is_file() and code == 0 and sentinel and actual_identity and control_ok and all(report.get(k) == v for k, v in expected.items()):
                _npy_to_png(npy, png, preserve_source=True)
                if png.is_file():
                    record["linear_npy"] = _artifact_ref(npy, out_dir); record["image"] = _artifact_ref(png, out_dir); record["report_artifact"] = {"path": str((leg_dir / "report.json").relative_to(out_dir)).replace("\\", "/"), "sha256": ""}; (leg_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8"); record["report_artifact"]["sha256"] = _sha256(leg_dir / "report.json"); arrays[(role, backend)] = npy
                    if control_kind != "baseline": record["feature_mask"] = _artifact_ref(mask_path, out_dir); masks[(role, backend, control_kind)] = mask_path
                    arrays[(role, backend, control_kind)] = npy
            payload["records"].append(record)
            (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    import numpy as np
    from benchmarks.reference_bank.metrics import compute_ssim
    from benchmarks.reference_bank.runner import compute_channel_mean_ratio
    for role, item in frozen.items():
        cpu, gpu = arrays.get((role, "CPU", "baseline")), arrays.get((role, "GPU", "baseline"))
        if not cpu or not gpu: continue
        a, b = np.load(gpu), np.load(cpu)
        for record in [r for r in payload["records"] if r["role"] == role and r.get("control") == "baseline"]:
            backend = record["backend"]
            paired = {c["kind"]: c for c in item["controls"]}
            record["non_vacuity"] = []
            for probe in item["non_vacuity"]:
                kind = probe.get("kind"); control_kind = {"checker": "checker_flat", "hair": "hair_off", "hdri": "hdri_off"}.get(kind)
                if control_kind in paired and (role, backend, control_kind) in arrays and (role, backend, control_kind) in masks:
                    record["non_vacuity"].append(_gate_c_paired_probe(np.load(arrays[(role, backend, "baseline")]), np.load(arrays[(role, backend, control_kind)]), np.load(masks[(role, backend, control_kind)]), probe))
            for name, roi in item["rois"].items():
                y0, y1, x0, x1 = int(roi[1]*a.shape[0]), int(roi[3]*a.shape[0]), int(roi[0]*a.shape[1]), int(roi[2]*a.shape[1])
                ratio, channels = compute_channel_mean_ratio(a, b, (y0, y1, x0, x1))
                ssim, _ = compute_ssim(a[y0:y1, x0:x1], b[y0:y1, x0:x1])
                record["rois"].append({"name": name, "ratio": channels, "ratio_max": float(ratio), "ssim": float(ssim)})
    (out_dir / "instrument.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if all((role, backend, "baseline") in arrays for role in frozen for backend in ("CPU", "GPU")) else 1


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
        timeout: int = 300, include_composites: bool = True,
        gate_b_cases: Path | None = None, gate_b_backend: str = "",
        gate_b_build_id: str = "", gate_b_module_sha256: str = "",
        gate_b_addon_sha256: str = "") -> int:
    if gate_b_cases is not None:
        raise ValueError("generic differential runs cannot emit gate-b corpus evidence; use run_gate_b_corpus")
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

def verdict_payload(results: list[FeatureResult]) -> dict[str, Any]:
    """pkg278: machine-readable per-feature verdicts for the acceptance manifest.

    Reuses the pkg119b triage output verbatim; adds no metric. One entry per
    feature with its status, triage bucket and metric values.
    """
    return {
        "schema": "pkg278.feature_verdicts.v1",
        "total": len(results),
        "verdicts": [
            {
                "feature": f"{r.category}:{r.feature}",
                "category": r.category,
                "name": r.feature,
                "phase_a_bucket": r.phase_a_bucket,
                "status": r.status,
                "triage_bucket": r.triage_bucket,
                "skip_reason": r.skip_reason,
                "ssim": r.ssim,
                "delta_e": r.delta_e,
                "ratio": list(r.ratio) if r.ratio else None,
            }
            for r in results
        ],
    }


def gate_b_runner_results(results: list[FeatureResult], cases: list[dict[str, Any]],
                          *, backend: str, build_id: str, module_sha256: str,
                          addon_sha256: str) -> list[dict[str, Any]]:
    """Deprecated generic feature records; never use for corpus coverage.

    ``cases`` is the frozen coverage case map supplied by the gate runner.  A
    result is emitted only when exactly one measured feature is named by its
    ``feature`` field; pass/fail is recomputed from retained parity metrics.
    """
    del results, cases, backend, build_id, module_sha256, addon_sha256
    raise ValueError("generic FeatureResult output cannot prove a frozen gate-b corpus case; use --gate-b-cases")


def gate_b_corpus_result(case: Mapping[str, Any], observed: Mapping[str, Any],
                         metrics: Mapping[str, Any], artifacts: Mapping[str, Any]) -> dict[str, Any]:
    """Build one corpus-case result from a render-leg's observed raw record.

    This deliberately has no FeatureResult input: a parity-matrix feature may
    not be relabelled as a frozen corpus scene/socket variant.
    """
    required = ("case_id", "identity", "scene_id", "variant_digest", "backend", "build_id")
    if any(not isinstance(case.get(key), str) or not case[key] for key in required):
        raise ValueError("gate-b corpus case is incomplete")
    if any(observed.get(key) != case.get(key)
           for key in ("identity", "scene_id", "variant_digest", "backend", "build_id")):
        raise ValueError("observed corpus identity does not match frozen case")
    if not all(isinstance(observed.get(key), str) and observed[key] for key in ("module_sha256", "addon_sha256", "engine_id", "device")):
        raise ValueError("corpus render leg lacks observed engine identity")
    ssim, delta_e = metrics.get("ssim"), metrics.get("delta_e")
    if not isinstance(ssim, (int, float)) or not isinstance(delta_e, (int, float)):
        raise ValueError("corpus render leg lacks measured SSIM/delta_e")
    for key in ("astroray_linear_npy", "cycles_linear_npy", "report"):
        if not isinstance(artifacts.get(key), Mapping):
            raise ValueError(f"corpus render leg lacks {key} artifact")
    return {"schema": GATE_B_RUNNER_RESULT_SCHEMA, **{key: case[key] for key in required},
            "observed": dict(observed), "metrics": {"ssim": ssim, "delta_e": delta_e},
            "artifacts": dict(artifacts),
            "status": "pass" if ssim >= .95 and delta_e <= 5.0 else "fail"}


def _gate_b_cases(cases_path: Path) -> list[dict[str, Any]]:
    """Read the v3 frozen case map, never a feature-result surrogate."""
    payload = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    case_map = payload.get("evidence", {}).get("runner_case_map", {}) if isinstance(payload, Mapping) else {}
    cases = case_map.get("cases") if isinstance(case_map, Mapping) else None
    if payload.get("schema") != "pkg278.coverage_input.v3" or not isinstance(cases, list):
        raise ValueError("--gate-b-cases requires a frozen coverage_input_v3.json with cases")
    expected = hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
    if case_map.get("sha256") != expected:
        raise ValueError("frozen gate-b case map hash mismatch")
    required = ("case_id", "identity", "scene_id", "variant_digest", "backend", "build_id",
                "module_sha256", "addon_sha256")
    if any(not isinstance(case, Mapping) or any(not isinstance(case.get(key), str) or not case[key]
                                                for key in required) for case in cases):
        raise ValueError("frozen gate-b case map contains an incomplete case")
    return [dict(case) for case in cases]


def _gate_b_report(combined: str) -> dict[str, Any]:
    prefix = f"{SENTINEL} REPORT "
    reports = [line[len(prefix):] for line in combined.splitlines() if line.startswith(prefix)]
    if len(reports) != 1:
        raise ValueError("corpus render leg did not emit exactly one observation report")
    report = json.loads(reports[0])
    if not isinstance(report, dict):
        raise ValueError("corpus render-leg observation is not an object")
    return report


def _gate_b_artifact(path: Path, base: Path) -> dict[str, str]:
    # Evidence can be written under a caller-selected repository evidence
    # directory; absolute references keep the runner result valid when its
    # sidecar is discovered from the frozen canonical sidecar directory.
    return {"path": str(path.resolve()).replace("\\", "/"),
            "sha256": _sha256(path)}


def run_gate_b_corpus(cases_path: Path, corpus_manifest: Path, out_dir: Path, *,
                      timeout: int = 600) -> int:
    """Render every frozen corpus case and retain the paired linear evidence.

    Each Blender invocation receives one immutable case file.  The leg itself
    reopens the named corpus blend, verifies its bytes, and records the actual
    reachability-derived identity/variant plus loaded addon/module telemetry.
    This is deliberately separate from the generic feature differential loop:
    a FeatureResult has no authority to label a corpus case.
    """
    import numpy as np

    blender = _find_blender()
    build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if blender is None or build_dir is None:
        print("[pkg278] Blender and an addon astroray build are required for gate-b corpus cases.", file=sys.stderr)
        return 2
    cases = _gate_b_cases(cases_path)
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ASTRORAY_PYD_DIR"] = str(build_dir)
    env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")
    results: list[dict[str, Any]] = []
    sidecars = out_dir / "sidecars"
    sidecars.mkdir(exist_ok=True)

    for case in cases:
        case_dir = out_dir / "cases" / case["case_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        case_path = case_dir / "case.json"
        case_path.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        legs: dict[str, dict[str, Any]] = {}
        failed = ""
        for engine, device, name in (("CYCLES", "cpu", "cycles"),
                                     ("CUSTOM_RAYTRACER", case["backend"].lower(), "astroray")):
            stem = case_dir / name
            raw = case_dir / f"{name}_raw.json"
            args = ["--corpus-manifest", str(Path(corpus_manifest).resolve()),
                    "--corpus-scene", case["scene_id"], "--gate-b-case", str(case_path),
                    "--gate-b-report", str(raw), "--engine", engine, "--device", device,
                    "--out", str(stem)]
            ok, combined, tail = _run_render_leg_script(blender, args, env, timeout)
            if not ok or not stem.with_suffix(".npy").is_file() or not raw.is_file():
                failed = f"{name} leg failed: {tail}"
                break
            try:
                legs[name] = {"report": _gate_b_report(combined), "raw": raw,
                              "npy": stem.with_suffix(".npy")}
            except (ValueError, json.JSONDecodeError) as exc:
                failed = f"{name} observation invalid: {exc}"
                break
        if failed:
            results.append({"schema": GATE_B_RUNNER_RESULT_SCHEMA, "case_id": case["case_id"],
                            "status": "fail", "reason": failed})
            continue
        astro, cycles = legs["astroray"], legs["cycles"]
        try:
            observed = astro["report"]["observed"]
            for report in (astro["report"], cycles["report"]):
                if report.get("case") != {key: case[key] for key in ("case_id", "identity", "scene_id", "variant_digest", "backend", "build_id")}:
                    raise ValueError("render-leg case binding mismatch")
                if report.get("graph", {}).get("identity") != case["identity"] or report["graph"].get("variant_digest") != case["variant_digest"]:
                    raise ValueError("render-leg graph does not confirm frozen identity/variant")
                if report.get("blend_sha256") != astro["report"].get("blend_sha256"):
                    raise ValueError("paired legs opened different corpus bytes")
            ssim, delta_e, _ratio = _metrics(np.load(astro["npy"]), np.load(cycles["npy"]))
            artifacts = {"astroray_linear_npy": _gate_b_artifact(astro["npy"], out_dir),
                         "cycles_linear_npy": _gate_b_artifact(cycles["npy"], out_dir),
                         "report": _gate_b_artifact(astro["raw"], out_dir),
                         "cycles_report": _gate_b_artifact(cycles["raw"], out_dir)}
            result = gate_b_corpus_result(case, observed, {"ssim": ssim, "delta_e": delta_e}, artifacts)
            results.append(result)
            runner_one = case_dir / "runner_result.json"
            runner_one.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            verifier = _gate_b_artifact(runner_one, out_dir)
            sidecar = {"schema": "pkg278.gate_b.evidence.v2", "identity": case["identity"],
                       "scene_id": case["scene_id"], "variant": case["scene_id"],
                       "variant_digest": case["variant_digest"], "backend": case["backend"],
                       "build_id": case["build_id"], "case_id": case["case_id"], "result_kind": "render",
                       "artifact": artifacts["astroray_linear_npy"],
                       "verdict": {"schema": "pkg278.gate_b.verdict.v1", "pass": result["status"] == "pass",
                                   **{key: case[key] for key in ("identity", "scene_id", "variant_digest", "backend", "build_id")},
                                   "result": {"kind": "render", "artifact_sha256": verifier["sha256"]}},
                       "verifier_result": verifier}
            (sidecars / f"{case['case_id']}.json").write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except (KeyError, TypeError, ValueError) as exc:
            results.append({"schema": GATE_B_RUNNER_RESULT_SCHEMA, "case_id": case["case_id"],
                            "status": "fail", "reason": str(exc)})
    payload = {"schema": GATE_B_RUNNER_RESULT_SCHEMA, "results": results}
    (out_dir / "gate_b_runner_results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if len(results) == len(cases) and all(result.get("status") == "pass" for result in results) else 1


def write_gate_b_runner_results(results: list[FeatureResult], cases_path: Path,
                                out_path: Path, *, backend: str, build_id: str,
                                module_sha256: str, addon_sha256: str) -> None:
    """Write canonical runner output consumed by the gate-(b) scorer."""
    cases_payload = json.loads(cases_path.read_text(encoding="utf-8"))
    if isinstance(cases_payload, dict) and isinstance(cases_payload.get("cases"), list):
        cases = cases_payload["cases"]
    elif isinstance(cases_payload, dict):
        cases = cases_payload.get("evidence", {}).get("runner_case_map", {}).get("cases")
    else:
        cases = None
    if not isinstance(cases, list):
        raise ValueError("gate-(b) case map must contain a cases list")
    payload = {"schema": GATE_B_RUNNER_RESULT_SCHEMA, "results": gate_b_runner_results(
        results, cases, backend=backend, build_id=build_id,
        module_sha256=module_sha256, addon_sha256=addon_sha256)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    # pkg278: per-feature verdict JSON for the acceptance manifest. Reuses the
    # pkg119b triage output verbatim (no new metric) so gate (b)/(c) can link a
    # machine-readable verdict per feature.
    (out_dir / "feature_verdicts.json").write_text(
        json.dumps(verdict_payload(results), indent=2), encoding="utf-8")

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
    p.add_argument("--gate-c", action="store_true",
                   help="produce the owner-selected corpus trio CPU/GPU F12 evidence")
    p.add_argument("--corpus-manifest", type=Path, default=None)
    p.add_argument("--build-id", default="", help="pinned addon/build identity for gate-c evidence")
    p.add_argument("--module-sha256", default="", help="expected loaded astroray module SHA-256 for gate-c")
    p.add_argument("--gate-b-cases", type=Path,
                   help="frozen coverage_input_v3.json; run each immutable corpus case")
    p.add_argument("--gate-b-backend", choices=("CPU", "GPU"), default="")
    p.add_argument("--gate-b-addon-sha256", default="")
    args = p.parse_args(argv)
    if args.export_blend is not None:
        return export_reference_scenes(args.export_blend, timeout=args.timeout)
    if args.gate_c:
        return run_gate_c_trio(args.out, manifest_path=args.corpus_manifest,
                               timeout=args.timeout, build_id=args.build_id,
                               module_sha256=args.module_sha256)
    if args.gate_b_cases is not None:
        if args.corpus_manifest is None:
            p.error("--gate-b-cases requires --corpus-manifest")
        return run_gate_b_corpus(args.gate_b_cases, args.corpus_manifest, args.out,
                                 timeout=args.timeout)
    return run(args.matrix, args.out, res=args.res, samples=args.samples,
               timeout=args.timeout, include_composites=not args.no_composites,
               gate_b_cases=args.gate_b_cases, gate_b_backend=args.gate_b_backend,
               gate_b_build_id=args.build_id, gate_b_module_sha256=args.module_sha256,
               gate_b_addon_sha256=args.gate_b_addon_sha256)


if __name__ == "__main__":
    sys.exit(main())
