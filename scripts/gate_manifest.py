#!/usr/bin/env python
"""pkg278 - assemble and validate the Pillar-4 exit-gate acceptance manifest.

One file, ``docs/blender_parity/acceptance_manifest.json``, is the gate's only
source of truth: one row per north-star row (a)-(g), each carrying scene
SHA-256s, build id, backend, settings, metric, value, threshold, evidence path
and date.

The status of every row is COMPUTED here from hash-verified evidence and the
frozen thresholds in this module; a caller-supplied ``status`` is never trusted.
A row with no instrument stays ``unmeasured`` with ``value: null`` -- never
omitted. A missing or dangling evidence item makes the row ``red``; a hand-edited
green is rejected and flagged.

    python scripts/gate_manifest.py --validate
    python scripts/gate_manifest.py --instruments-dir docs/blender_parity/evidence \
        --out docs/blender_parity/acceptance_manifest.json

The normative shape is ``docs/blender_parity/acceptance_manifest.schema.json``;
this module enforces the same shape (plus the semantic per-row requirements)
without a third-party jsonschema dependency.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
# Direct CLI execution puts ``scripts/`` on sys.path, while the C reducer
# imports the checkout-owned reference-bank metric implementation.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCHEMA_PATH = REPO_ROOT / "docs" / "blender_parity" / "acceptance_manifest.schema.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "blender_parity" / "acceptance_manifest.json"

ROWS = ("a", "b", "c", "d", "e", "f", "g")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

BASE_FIELDS = (
    "instrument", "scene_sha256", "build_id", "backend", "settings", "metric",
    "value", "threshold", "evidence_path", "evidence_sha256", "dimensions", "date",
)

PAYLOAD_SCHEMA = "pkg278.instrument.v2"
# These are logical corpus roles, not substitute legacy/current filenames.  The
# producer freezes the resolved actual scene id and blend hash for each role.
TRIO_ROLES = ("materials_hall", "textures_mapping", "world_sky:terrace-with-hair")
# Row (c) Welch tile test, pkg317 candidate 1b (gate-c-metric-study-2026-10.md): 8x8 tiles, three
# channels, Holm family-wise alpha 0.05, only a bias above 1 % of the tile mean is rejected.
GATE_C_WELCH = {"tile": 8, "alpha": 0.05, "margin_rel": 0.01}


def _bound(value: float, rule: Mapping[str, float]) -> bool:
    if "max" in rule:
        return value <= float(rule["max"])
    if "min" in rule:
        return value >= float(rule["min"])
    return False


# --------------------------------------------------------------------------- #
# Frozen per-row requirements + thresholds. Do not loosen these.
# --------------------------------------------------------------------------- #
ROW_SPEC: dict[str, dict[str, Any]] = {
    "a": {
        "instrument": "viewport_latency",
        "required_dimensions": ("scene", "edit_kind", "repetitions"),
        "required_backends": ("GPU",),
        "min_scenes": 2,
        "threshold": {
            "gpu_p95_ms": {"max": 100.0},
            "gpu_p99_ms": {"max": 150.0},
            "cancel_p95_ms": {"max": 200.0},
            "cancel_p99_ms": {"max": 300.0},
            "stale_frames_after_ack": {"max": 0},
        },
        "required_subchecks": (
            "both_pinned_scenes", "three_by_hundred_repetitions",
            "denoise_excluded", "gpu_only_latency",
        ),
    },
    "b": {
        "instrument": "coverage_report",
        "required_dimensions": ("backend", "variant"),
        "required_backends": ("CPU", "GPU"),
        "min_scenes": 1,
        "threshold": {"cpu_score": {"min": 0.95}, "gpu_score": {"min": 0.95}},
        "required_subchecks": (
            "b1_input_manifest_ratified", "b2_cpu_score", "b3_gpu_score",
            "b4_zero_silent_drops", "b5_named_node_checks", "b6_nonzero_links_evidence",
        ),
        "requires_scanner_823": True,
    },
    # Row (c): owner decision 2026-10-06 replaces SSIM >= 0.95 with the pkg317 Welch tile test
    # (candidate 1b, GATE_C_WELCH) on the 8 frozen spread seeds per backend; the +-5 % ROI
    # channel-mean band stays as a guard, SSIM is recorded as informational only.
    "c": {
        "instrument": "trio_parity",
        "required_dimensions": ("backend", "scene", "roi", "seeds"),
        "required_backends": ("CPU", "GPU"),
        "min_scenes": 3,
        "threshold": {"welch_rejected_tiles": {"max": 0}, "roi_pct_max": {"max": 5.0}},
        "required_subchecks": (
            "cpu_seed_legs", "gpu_seed_legs", "pinned_images", "identity_bound", "non_vacuity",
        ),
    },
    "d": {
        "instrument": "native_panel_smoke",
        "required_dimensions": ("backend", "panel"),
        "required_backends": ("CPU", "GPU"),
        "min_scenes": 1,
        "threshold": {"mean_rel_error_max": {"max": 0.02},
                      "detail_preservation_min": {"min": 0.95}},
        "required_subchecks": (
            "adaptive_changes_sample_count_aov", "adaptive_lowers_flat_noise",
            "denoise_lowers_residual_noise", "reference_comparison",
        ),
    },
    "e": {
        "instrument": "issue_triage",
        "required_dimensions": ("issue_snapshot", "ratings"),
        "required_backends": (),
        "min_scenes": 0,
        "threshold": {"high_count": {"max": 0}},
        "required_subchecks": (
            "snapshot_unique", "count_matches_total", "all_rated_independently",
            "delta_empty",
        ),
    },
    "f": {
        "instrument": "clean_install",
        "required_dimensions": ("check",),
        "required_backends": (),
        "min_scenes": 0,
        "threshold": {},
        "required_subchecks": (
            "fresh_profile", "zip_identity", "installer_path", "no_toolchain",
            "f12_exit_zero",
        ),
    },
    # Row (g): pkg310 production node-tree score (owner 2026-09-29: "Stage 0 exit-gate
    # row", re-confirmed 2026-10-06: "becomes manifest row (g)").  Owner decision
    # 2026-10-06: at least 6/8 production scenes passing on BOTH CPU and GPU (PASS = in
    # band and silent-free), plus zero silent pairs (2026-09-29).
    "g": {
        "instrument": "production_node_score",
        "required_dimensions": ("backend", "material"),
        "required_backends": ("CPU", "GPU"),
        "min_scenes": 8,
        "threshold": {"cpu_pass": {"min": 6}, "gpu_pass": {"min": 6},
                      "cpu_silent_pairs": {"max": 0}, "gpu_silent_pairs": {"max": 0}},
        "required_subchecks": (
            "legs_complete", "identity_bound", "bands_recomputed",
            "zero_silent_degradations",
        ),
    },
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _resolve(repo_root: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else Path(repo_root) / p


def empty_row(rid: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row": rid,
        "instrument": spec["instrument"],
        "status": "unmeasured",
        "scene_sha256": [],
        "build_id": None,
        "backend": [],
        "settings": {},
        "metric": {},
        "value": None,
        "threshold": {},
        "evidence_path": None,
        "evidence_sha256": None,
        "dimensions": {},
        "subchecks": {},
        "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
    }


def _evidence_valid(row: Mapping[str, Any], repo_root: Path) -> tuple[bool, str]:
    path = row.get("evidence_path")
    recorded = str(row.get("evidence_sha256") or "").lower()
    if not path:
        return False, "no evidence_path"
    if not _HEX64.match(recorded):
        return False, "missing or malformed evidence_sha256"
    p = _resolve(repo_root, str(path))
    if not p.is_file():
        return False, f"evidence_path does not exist: {path}"
    if sha256_file(p) != recorded:
        return False, f"evidence_sha256 mismatch for {path}"
    return True, ""


def _number(value: Any) -> float | None:
    """Accept only finite JSON numbers; bool is deliberately not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _subcheck_passed(value: Any) -> bool:
    """Accept the bool and typed-check forms emitted by the canonical reducers."""
    return value is True or (isinstance(value, Mapping) and value.get("pass") is True)


def _artifact(ref: Any, base: Path, label: str) -> tuple[Path | None, list[str]]:
    """Resolve an immutable producer artifact beneath its payload directory."""
    if not isinstance(ref, Mapping):
        return None, [f"{label} must be an artifact object"]
    path, digest = ref.get("path"), ref.get("sha256")
    if not isinstance(path, str) or not path.strip():
        return None, [f"{label} artifact path missing"]
    if not isinstance(digest, str) or not _HEX64.match(digest):
        return None, [f"{label} artifact digest malformed"]
    candidate = (base / path).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None, [f"{label} artifact escapes payload directory"]
    if not candidate.is_file():
        return None, [f"{label} artifact missing: {path}"]
    if sha256_file(candidate) != digest:
        return None, [f"{label} artifact digest mismatch: {path}"]
    return candidate, []


def _repo_artifact(ref: Any, label: str) -> tuple[Path | None, list[str]]:
    """Resolve a hash-pinned canonical input beneath this checkout."""
    if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
        return None, [f"{label} must be an artifact object"]
    digest = ref.get("sha256")
    if not isinstance(digest, str) or not _HEX64.match(digest):
        return None, [f"{label} artifact digest malformed"]
    candidate = _resolve(REPO_ROOT, ref["path"]).resolve()
    try:
        candidate.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None, [f"{label} artifact escapes repository"]
    if not candidate.is_file():
        return None, [f"{label} artifact missing: {ref['path']}"]
    if sha256_file(candidate) != digest:
        return None, [f"{label} artifact digest mismatch: {ref['path']}"]
    return candidate, []


def _typed_payload(row: Mapping[str, Any], rid: str, spec: Mapping[str, Any],
                   repo_root: Path) -> tuple[Mapping[str, Any] | None, Path | None, list[str]]:
    """Read the hash-pinned instrument result; hashes alone do not prove meaning."""
    ok, why = _evidence_valid(row, repo_root)
    if not ok:
        return None, None, [f"evidence invalid: {why}"]
    path = _resolve(repo_root, str(row["evidence_path"]))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, [f"instrument payload is not JSON: {exc}"]
    if not isinstance(payload, Mapping):
        return None, None, ["instrument payload must be an object"]
    errors: list[str] = []
    if payload.get("schema") != PAYLOAD_SCHEMA:
        errors.append(f"instrument payload schema must be {PAYLOAD_SCHEMA!r}")
    if payload.get("row") != rid:
        errors.append("instrument payload row mismatch")
    if payload.get("instrument") != spec["instrument"]:
        errors.append("instrument payload instrument mismatch")
    if row.get("instrument") != spec["instrument"]:
        errors.append("manifest instrument mismatch")
    records = payload.get("records")
    if not isinstance(records, list) or not records or not all(isinstance(x, Mapping) for x in records):
        errors.append("instrument payload requires non-empty typed records")
    for name in ("build_id", "scene_sha256", "backend", "settings", "metric", "threshold"):
        if payload.get(name) != row.get(name):
            errors.append(f"manifest {name} disagrees with instrument payload")
    return (payload if not errors else None), path.parent, errors


def _pct(samples: list[float], quantile: float) -> float:
    return sorted(samples)[max(0, int(len(samples) * quantile + .999999) - 1)]


def _validate_a(records: list[Any], base: Path, expected_scenes: Any) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    errors: list[str] = []; samples: list[float] = []; cancels: list[float] = []; cells = set(); scenes = set(); stale = 0; triangles = {}
    if len(records) != 12: errors.append("row a requires 12 raw captures (2 scenes × 2 kinds × 3 batches)")
    driver_path = REPO_ROOT / "benchmarks" / "viewport_parity" / "blender_driver.py"
    spec = importlib.util.spec_from_file_location("pkg278_gate_a_reducer", driver_path)
    driver = importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(driver)
    for i, cap in enumerate(records):
        if not isinstance(cap, Mapping): errors.append(f"row a capture {i} is not an object"); continue
        scene, kind, batch = cap.get("scene_sha256"), cap.get("edit_kind"), cap.get("batch")
        if not isinstance(scene, str) or not _HEX64.match(scene) or kind not in ("camera", "material") or batch not in (0, 1, 2):
            errors.append(f"row a capture {i} has invalid dimensions"); continue
        if cap.get("backend") != "GPU" or cap.get("denoise_enabled") is not False:
            errors.append(f"row a capture {i} is not GPU denoise-off evidence")
        observed = cap.get("observed_runtime")
        if not isinstance(observed, Mapping) or observed.get("engine") != "CUSTOM_RAYTRACER" or observed.get("requested_device") != "gpu" or observed.get("denoise_enabled") is not False:
            errors.append(f"row a capture {i} lacks observed GPU denoise-off runtime identity")
        actual_devices = observed.get("actual_gpu_devices") if isinstance(observed, Mapping) else None
        if (not isinstance(actual_devices, list) or not actual_devices
                or any(not isinstance(device, int) or device < 0 for device in actual_devices)):
            errors.append(f"row a capture {i} lacks observed native GPU render telemetry")
        if not all(isinstance(observed.get(name, {}).get("path"), str) and _HEX64.match(str(observed.get(name, {}).get("sha256") or ""))
                   for name in ("addon", "module")) if isinstance(observed, Mapping) else True:
            errors.append(f"row a capture {i} lacks hash-pinned loaded addon/module identity")
        workload = cap.get("workload")
        if (not isinstance(workload, Mapping) or workload.get("sha256") != scene
                or not isinstance(workload.get("path"), str)
                or workload.get("triangles") not in (10000, 100000)):
            errors.append(f"row a capture {i} lacks frozen 10k/100k workload identity")
        else:
            freeze = workload.get("freeze")
            if not isinstance(freeze, Mapping) or freeze.get("blend_sha256") != scene or freeze.get("observed_triangles") != workload.get("triangles"):
                errors.append(f"row a capture {i} lacks pre-session observed workload census")
            triangles[scene] = workload["triangles"]
        result = driver.reduce_gate_a_capture(cap.get("raw_events", []), cap.get("edits", []), truncated=bool(cap.get("truncated")), artifact_root=base)
        errors.extend(f"row a capture {i}: {e}" for e in result["errors"])
        if len(result["rows"]) != 100: errors.append(f"row a capture {i} lacks 100 correct presents")
        if not result["cancels"]: errors.append(f"row a capture {i} has no cancel acknowledgement")
        scenes.add(scene)
        for rep, row in enumerate(result["rows"]):
            cells.add((scene, kind, batch, rep)); samples.append((row["present_ns"] - row["event_ns"]) / 1e6)
        for cancel in result["cancels"]:
            # The contract is the worker's actual acknowledgement.  Drain is
            # retained as safety telemetry by the raw gate producer, but timing
            # it would charge the main-thread pump rather than cancellation.
            cancels.append((cancel["idle_ack_ns"] - cancel["cancel_ns"]) / 1e6)
            stale += int(cancel["stale_frames_after_ack"])
    if (not isinstance(expected_scenes, list) or len(expected_scenes) != 2 or set(expected_scenes) != scenes
            or len(cells) != 1200 or sorted(triangles.values()) != [10000, 100000]):
        errors.append("row a captures must cover two pinned scenes × camera/material × 3 batches × 100 repetitions")
    value = {"gpu_p95_ms": _pct(samples, .95) if samples else None, "gpu_p99_ms": _pct(samples, .99) if samples else None,
             "cancel_p95_ms": _pct(cancels, .95) if cancels else None, "cancel_p99_ms": _pct(cancels, .99) if cancels else None,
             "stale_frames_after_ack": stale}
    return errors, value, {"both_pinned_scenes": len(scenes) == 2, "three_by_hundred_repetitions": len(cells) == 1200, "denoise_excluded": not any("denoise" in e for e in errors), "gpu_only_latency": not any("not GPU" in e for e in errors)}


def _c_receipt_errors(leg: str, report: Mapping[str, Any], control: str, frozen: Mapping[str, Any]) -> list[str]:
    """Observed graph bindings + mutation receipt of one row-(c) leg against its frozen role."""
    errors: list[str] = []
    bindings = report.get("bindings")
    if not isinstance(bindings, Mapping):
        return [f"{leg} lacks observed graph bindings"]
    for declared in frozen.get("controls", []):
        kind = declared.get("kind"); observed = bindings.get(kind)
        if not isinstance(observed, Mapping):
            errors.append(f"{leg} lacks observed {kind} binding"); continue
        checks = {"checker_flat": (("object", "object"), ("material", "material"), ("node", "node"), ("object_type", "MESH"), ("node_type", "ShaderNodeTexChecker")),
                  "hair_off": (("object", "object"), ("object_type", "CURVES")),
                  "hdri_off": (("world", "world"), ("node", "node"), ("node_type", "ShaderNodeTexEnvironment"))}.get(kind, ())
        for observed_key, expected_key in checks:
            expected_value = declared.get(expected_key) if expected_key in declared else expected_key
            if observed.get(observed_key) != expected_value:
                errors.append(f"{leg} observed {kind} binding differs from freeze")
                break
        if kind == "hair_off" and (observed.get("curve_count") != frozen.get("expected_curve_count")
                                   or observed.get("curve_point_count") != frozen.get("expected_curve_point_count")):
            errors.append(f"{leg} observed hair census differs from freeze")
    receipt = report.get("mutation_receipt")
    declared = next((item for item in frozen.get("controls", []) if item.get("kind") == control), {})
    if not isinstance(receipt, Mapping) or receipt.get("kind") != control or receipt.get("ok") is not True:
        errors.append(f"{leg} mutation receipt is missing or wrong")
    elif control == "baseline" and set(receipt) != {"kind", "ok"}:
        errors.append(f"{leg} baseline receipt is not inert")
    elif control == "checker_flat" and (receipt.get("object") != declared.get("object") or receipt.get("material") != declared.get("material") or receipt.get("node") != declared.get("node") or receipt.get("before") == receipt.get("after")):
        errors.append(f"{leg} checker mutation receipt is not the declared flat control")
    elif control == "hair_off" and (receipt.get("object") != declared.get("object") or receipt.get("type") != "CURVES" or receipt.get("was_hide_render") is not False or receipt.get("after_hide_render") is not True):
        errors.append(f"{leg} hair mutation receipt is not the declared hide control")
    elif control == "hdri_off" and (receipt.get("world") != declared.get("world") or receipt.get("node") != declared.get("node") or not receipt.get("image") or receipt.get("after_image", "not-none") is not None):
        errors.append(f"{leg} HDRI mutation receipt is not the declared world control")
    return errors


def _roi_box(roi: Any, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    return int(roi[1] * shape[0]), int(roi[3] * shape[0]), int(roi[0] * shape[1]), int(roi[2] * shape[1])


def _evaluate_c(records: list[Any], base: Path, expected_hashes: Any, build_id: Any,
                freeze_ref: Any = None) -> tuple[list[str], dict[str, Any], dict[str, Any], list[str]]:
    """Recompute row (c) from raw per-seed legs; separates invalid evidence from a valid failed measurement.

    Metric (owner decision 2026-10-06, pkg317 candidate 1b): per role, the 8 frozen-seed CPU renders vs
    the 8 GPU renders, per 8x8 tile and colour channel Welch t-test of a bias larger than 1 % of the
    tile mean, Holm family-wise alpha 0.05 (``mc_compare.welch_verdict``; Jung, Hanika, Dachsbacher
    2020, JCGT 9(2)).  A role passes iff Holm rejects no tile.  Guard: the per-ROI channel-mean ratio
    of the 8-seed means stays within +-5 %.  SSIM of the frozen-seed pair is informational only.
    Non-vacuity: the declared paired controls at the frozen role seed, unchanged from pkg278.
    No verdict, value or claim stored in the evidence is read."""
    import numpy as np

    from benchmarks.blender_parity import mc_compare as MCC
    from benchmarks.blender_parity.harness import (
        SENTINEL,
        STUDY_SEEDS,
        _gate_c_paired_probe,
        _parse_gate_leg_report,
    )
    from benchmarks.reference_bank.metrics import compute_ssim
    from benchmarks.reference_bank.runner import compute_channel_mean_ratio
    errors: list[str] = []
    identity_errors: list[str] = []
    measurement_failures: list[str] = []
    seeds = tuple(STUDY_SEEDS)
    freeze_path, why = _artifact(freeze_ref, base, "row c freeze"); errors.extend(why)
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8")) if freeze_path else {}
    except (OSError, json.JSONDecodeError):
        freeze = {}; errors.append("row c freeze cannot be read")
    if not isinstance(freeze, Mapping):
        freeze = {}; errors.append("row c freeze is not an object")
    roles = freeze.get("roles", {})
    if not isinstance(roles, Mapping) or set(roles) != set(TRIO_ROLES) or not all(isinstance(v, Mapping) for v in roles.values()):
        errors.append("row c freeze lacks the exact declared trio roles")
        roles = {}
    freeze_sha = sha256_file(freeze_path) if freeze_path else ""
    if freeze.get("build_id") != build_id or not isinstance(build_id, str) or not build_id:
        errors.append("row c freeze build identity differs from the instrument")
    for field in ("module_sha256", "addon_sha256"):
        if not isinstance(freeze.get(field), str) or not _HEX64.match(freeze[field]):
            errors.append(f"row c freeze has invalid {field}")
    if (not isinstance(expected_hashes, list) or len(expected_hashes) != 3
            or sorted(map(str, expected_hashes)) != sorted(str(r.get("scene_sha256")) for r in roles.values())):
        errors.append("row c scene hashes do not equal the frozen trio scene hashes")
    for role, frozen in roles.items():
        if frozen.get("seed") not in seeds:
            errors.append(f"row c {role} frozen seed is not in the spread seed list")
    stacks: dict[tuple[str, str], dict[int, tuple[Any, str]]] = {}
    controls: dict[tuple[str, str, str], tuple[Any, Any]] = {}
    seen: set[tuple[str, str, str, int]] = set()
    blender_versions: set[str] = set()
    for i, r in enumerate(records):
        if not isinstance(r, Mapping):
            errors.append(f"row c record {i} is not an object"); continue
        role, backend, control, seed = (r.get(k) for k in ("role", "backend", "control", "seed"))
        frozen = roles.get(role) if isinstance(role, str) else None
        declared = {c.get("kind"): c for c in frozen.get("controls", []) if isinstance(c, Mapping)} if frozen else {}
        if (r.get("kind") != "seed_leg" or frozen is None or backend not in ("CPU", "GPU")
                or control not in {"baseline", *declared} or not isinstance(seed, int) or isinstance(seed, bool)):
            errors.append(f"row c record {i} has invalid kind/role/backend/control/seed"); continue
        leg = f"row c {role}/{backend}/{control}/s{seed}"
        if (role, backend, control, seed) in seen:
            errors.append(f"{leg} is a duplicate leg"); continue
        seen.add((role, backend, control, seed))
        if control == "baseline" and seed not in seeds:
            errors.append(f"{leg} seed is not in the frozen spread seed list")
        if control != "baseline" and seed != frozen.get("seed"):
            errors.append(f"{leg} control leg does not use the frozen role seed")
        settings = frozen.get("settings", {})
        npy, why_npy = _artifact(r.get("linear_npy"), base, f"{leg} render")
        log, why_log = _artifact(r.get("log"), base, f"{leg} log")
        errors.extend(why_npy + why_log)
        if log is not None:
            text = log.read_text(encoding="utf-8", errors="replace")
            report, parse_error = _parse_gate_leg_report(text)
            if parse_error or f"{SENTINEL} PASS" not in text or f"{SENTINEL} FAIL" in text:
                identity_errors.append(f"{leg} log lacks one successful sentinel report")
                report = {}
            want = {"corpus_scene": frozen.get("scene_id"), "blend_sha256": frozen.get("scene_sha256"),
                    "freeze_sha256": freeze_sha, "build_id": build_id,
                    "requested_device": backend.lower(), "effective_device": backend.lower(),
                    "engine": "CUSTOM_RAYTRACER", "res_x": settings.get("res_x"), "res_y": settings.get("res_y"),
                    "samples": settings.get("samples"), "resolved_seed": seed, "animated_seed": False,
                    "module_sha256": freeze.get("module_sha256"), "addon_sha256": freeze.get("addon_sha256")}
            bad = [k for k, v in want.items() if report.get(k) != v]
            if not isinstance(report.get("blender_version"), str) or not report["blender_version"].startswith("5.2"):
                bad.append("blender_version")
            else:
                blender_versions.add(report["blender_version"])
            if report and bad:
                identity_errors.append(f"{leg} observed identity/settings differ from the freeze: {bad}")
            if report:
                identity_errors.extend(_c_receipt_errors(leg, report, control, frozen))
        else:
            report = {}
            identity_errors.append(f"{leg} has no hash-pinned log, so its identity is unproven")
        if npy is None:
            continue
        try:
            arr = np.load(npy)
            if (arr.ndim != 3 or arr.shape[:2] != (settings.get("res_y"), settings.get("res_x"))
                    or arr.shape[2] < 3 or not np.isfinite(arr).all()):
                raise ValueError()
            arr = arr[..., :3].astype(np.float32)
            if control == "baseline" and float(np.abs(arr).max()) <= 1e-9:
                raise ValueError()
        except (OSError, ValueError):
            errors.append(f"{leg} render is not a finite non-empty frozen-size RGB image"); continue
        if control == "baseline":
            stacks.setdefault((role, backend), {})[seed] = (arr, r["linear_npy"]["sha256"])
            continue
        mask_path, why = _artifact(r.get("feature_mask"), base, f"{leg} feature mask"); errors.extend(why)
        mask = None
        try:
            mask = np.load(mask_path).astype(bool) if mask_path else None
            if mask is None or mask.shape != arr.shape[:2] or not mask.any():
                raise ValueError()
        except (OSError, ValueError):
            errors.append(f"{leg} feature mask cannot be loaded"); mask = None
        mask_receipt = report.get("mask_receipt")
        if (not isinstance(mask_receipt, Mapping) or mask_receipt.get("control") != control
                or mask_receipt.get("kind") != declared[control].get("mask", {}).get("kind")
                or mask is None or mask_receipt.get("sha256") != (r.get("feature_mask") or {}).get("sha256")
                or mask_receipt.get("shape") != [int(mask.shape[0]), int(mask.shape[1])]
                or mask_receipt.get("pixels") != int(mask.sum())):
            identity_errors.append(f"{leg} mask receipt is not bound to the frozen control artifact")
        if mask is not None:
            controls[(role, backend, control)] = (arr, mask)
    complete = {"CPU": True, "GPU": True}
    for role, frozen in roles.items():
        for backend in ("CPU", "GPU"):
            got = stacks.get((role, backend), {})
            if set(got) != set(seeds):
                complete[backend] = False
                errors.append(f"row c {role}/{backend} baseline seeds {sorted(got)} are not exactly the "
                              f"{len(seeds)} frozen spread seeds {list(seeds)}")
            digests = [digest for _arr, digest in got.values()]
            if len(set(digests)) != len(digests):
                errors.append(f"row c {role}/{backend} reuses one render under several seeds")
            for kind in (c.get("kind") for c in frozen.get("controls", [])):
                if (role, backend, kind) not in controls:
                    errors.append(f"row c {role}/{backend} lacks a usable {kind} control leg at the frozen seed")
    if not roles:
        complete = {"CPU": False, "GPU": False}
    if len(blender_versions) > 1:
        identity_errors.append(f"row c legs ran under different Blender versions {sorted(blender_versions)}")
    errors.extend(identity_errors)
    per_role: dict[str, Any] = {}
    non_vacuity_valid = bool(roles)
    mapping = {"checker": "checker_flat", "hair": "hair_off", "hdri": "hdri_off"}
    for role in TRIO_ROLES:
        frozen = roles.get(role)
        cpu_d, gpu_d = stacks.get((role, "CPU"), {}), stacks.get((role, "GPU"), {})
        if frozen is None or set(cpu_d) != set(seeds) or set(gpu_d) != set(seeds) or frozen.get("seed") not in seeds:
            non_vacuity_valid = False
            continue
        cpu = np.stack([cpu_d[s][0] for s in seeds]); gpu = np.stack([gpu_d[s][0] for s in seeds])
        w = MCC.welch_verdict(cpu, gpu, alpha=GATE_C_WELCH["alpha"], tile=GATE_C_WELCH["tile"],
                              delta_rel=GATE_C_WELCH["margin_rel"])
        cpu_mean, gpu_mean = cpu.mean(0), gpu.mean(0)
        k = seeds.index(frozen["seed"])
        gaps, ssims = [], []
        for name, roi in frozen.get("rois", {}).items():
            y0, y1, x0, x1 = _roi_box(roi, cpu_mean.shape)
            gap, _channels = compute_channel_mean_ratio(gpu_mean, cpu_mean, (y0, y1, x0, x1))
            if not math.isfinite(gap):
                errors.append(f"row c {role} ROI {name} has no finite channel-mean ratio"); continue
            gaps.append(gap * 100)
            try:
                ssims.append(float(compute_ssim(gpu[k, y0:y1, x0:x1], cpu[k, y0:y1, x0:x1])[0]))
            except ValueError:
                pass  # informational only
        per_role[role] = {"welch_rejected_tiles": int(w["n_reject_holm"]), "welch_tests": int(w["n_tests"]),
                          "welch_min_p": float(w["min_p"]), "roi_pct_max": max(gaps) if gaps else None,
                          "ssim_min_informational": min(ssims) if ssims else None}
        if w["n_reject_holm"]:
            measurement_failures.append(f"row c {role} Welch-1b rejects {w['n_reject_holm']}/{w['n_tests']} tile tests")
        for probe in frozen.get("non_vacuity", []):
            kind = probe.get("kind"); ck = mapping.get(kind)
            if ck is None:
                continue
            for backend in ("CPU", "GPU"):
                baseline = (cpu_d if backend == "CPU" else gpu_d)[frozen["seed"]][0]
                pair = controls.get((role, backend, ck))
                result = _gate_c_paired_probe(baseline, pair[0], pair[1], probe) if pair else {"error": "missing"}
                if "error" in result:
                    non_vacuity_valid = False
                    errors.append(f"row c {role}/{backend} lacks a concrete {kind} paired probe")
                elif not result["ok"]:
                    measurement_failures.append(f"row c {role}/{backend} {kind} non-vacuity witness failed")
    measured = [per_role[r] for r in TRIO_ROLES if r in per_role]
    full = len(measured) == len(TRIO_ROLES)
    gaps = [m["roi_pct_max"] for m in measured if m["roi_pct_max"] is not None]
    ssims = [m["ssim_min_informational"] for m in measured if m["ssim_min_informational"] is not None]
    value = {"welch_rejected_tiles": sum(m["welch_rejected_tiles"] for m in measured) if full else None,
             "roi_pct_max": max(gaps) if full and gaps else None,
             "ssim_min_informational": min(ssims) if full and ssims else None,
             "per_role": per_role}
    if not full:
        errors.append("row c has no complete 8-seed CPU+GPU stack for every trio role")
    for key, rule in ROW_SPEC["c"]["threshold"].items():
        if _number(value.get(key)) is not None and not _bound(float(value[key]), rule):
            measurement_failures.append(f"row c {key}={value[key]} outside frozen bound {rule}")
    subchecks = {"cpu_seed_legs": complete["CPU"], "gpu_seed_legs": complete["GPU"],
                 "pinned_images": not any("artifact" in e for e in errors),
                 "identity_bound": bool(roles) and not identity_errors,
                 "non_vacuity": non_vacuity_valid}
    return errors, value, subchecks, measurement_failures


def _validate_c(records: list[Any], base: Path, expected_hashes: Any, build_id: Any,
                freeze_ref: Any = None) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Compatibility wrapper for direct reducer tests; errors include metric failures."""
    provenance_errors, value, subchecks, measurement_failures = _evaluate_c(
        records, base, expected_hashes, build_id, freeze_ref)
    return provenance_errors + measurement_failures, value, subchecks


def _validate_e(records: list[Any], base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    required = {("snapshot", "baseline"), ("snapshot", "recheck"), ("ratings", None)}
    if len(records) != 3 or not all(isinstance(record, Mapping) for record in records):
        return ["row e requires baseline/recheck snapshots and one ratings artifact"], {}, {}
    paths: dict[tuple[str, Any], Path] = {}
    for i, record in enumerate(records):
        key = (record.get("kind"), record.get("phase") if record.get("kind") == "snapshot" else None)
        if key not in required or key in paths:
            errors.append(f"row e record {i} has unexpected or duplicate kind/phase"); continue
        path, why = _artifact(record.get("artifact"), base, f"row e {key[0]} {key[1] or ''}".strip())
        errors.extend(why)
        if path is not None: paths[key] = path
    if set(paths) != required:
        return errors + ["row e typed artifacts incomplete"], {}, {}
    try:
        spec = importlib.util.spec_from_file_location("pkg278_known_issues", REPO_ROOT / "scripts" / "dev" / "known_issues_report.py")
        if spec is None or spec.loader is None: raise ImportError("cannot load known-issues reducer")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result = module.validate_gate_e_artifacts(paths[("snapshot", "baseline")], paths[("snapshot", "recheck")], paths[("ratings", None)])
    except (ImportError, OSError, ValueError, json.JSONDecodeError) as exc:
        return errors + [f"row e strict reducer rejected evidence: {exc}"], {}, {}
    return errors, result["value"], result["subchecks"]


def _validate_f(records: list[Any], base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    if len(records) != 1 or not isinstance(records[0], Mapping) or records[0].get("kind") != "clean_install_checks":
        return ["row f requires one clean_install_checks adapter record"], {}, {}
    checks_path, errors = _artifact(records[0].get("checks"), base, "row f checks")
    if checks_path is None:
        return errors, {}, {}
    try:
        doc = json.loads(checks_path.read_text(encoding="utf-8"))
        # Load the versioned producer beside this script.  This works both from
        # ``python scripts/gate_manifest.py`` and when the manifest reducer is
        # imported by tests; gate (f) has exactly one reducer.
        spec = importlib.util.spec_from_file_location("pkg278_clean_install", REPO_ROOT / "scripts" / "validate_clean_install.py")
        if spec is None or spec.loader is None:
            raise ImportError("cannot load clean-install reducer")
        clean_install = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = clean_install
        spec.loader.exec_module(clean_install)
        result = clean_install.evaluate(doc, checks_path.parent)
    except (OSError, json.JSONDecodeError, ImportError) as exc:
        return [f"row f checks cannot be evaluated: {exc}"], {}, {}
    names = ("fresh_profile", "zip_identity", "installer_path", "no_toolchain", "f12_exit_zero")
    subchecks = {name: result.get("checks", {}).get(name, {}).get("pass") is True for name in names}
    if result.get("status") != "green" or not result.get("all_green"):
        errors.append(f"row f clean-install evaluator status is {result.get('status')!r}")
    return errors, {}, subchecks


def _validate_d(records: list[Any], base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Re-run gate (d)'s canonical reducer from hash-linked raw CPU/GPU legs."""
    if len(records) != 1 or not isinstance(records[0], Mapping) or records[0].get("kind") != "native_panel_aggregate":
        return ["row d requires one native_panel_aggregate adapter record"], {}, {}
    raw_path, errors = _artifact(records[0].get("artifact"), base, "row d aggregate")
    expected = records[0].get("expected_identity")
    required = ("build_id", "engine_id", "module_sha256", "addon_init_sha256")
    if not isinstance(expected, Mapping) or any(not isinstance(expected.get(k), str) or not expected[k] for k in required):
        errors.append("row d requires complete expected candidate build identity")
        return errors, {}, {}
    if raw_path is None:
        return errors, {}, {}
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return errors + [f"row d aggregate cannot be read: {exc}"], {}, {}
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1 or raw.get("instrument") != "gate_native_panels":
        return errors + ["row d aggregate has wrong native-panel schema/instrument"], {}, {}
    backends = raw.get("backends")
    if not isinstance(backends, Mapping) or set(backends) != {"cpu", "gpu"}:
        return errors + ["row d aggregate requires exactly CPU and GPU raw legs"], {}, {}
    try:
        if str(REPO_ROOT / "tests") not in sys.path:  # the reducer imports tests/results_layout
            sys.path.insert(0, str(REPO_ROOT / "tests"))
        spec = importlib.util.spec_from_file_location("pkg278_native_panel_reducer", REPO_ROOT / "tests" / "test_gate_native_panels.py")
        if spec is None or spec.loader is None: raise ImportError("cannot load native-panel reducer")
        native = importlib.util.module_from_spec(spec); sys.modules[spec.name] = native; spec.loader.exec_module(native)
    except (ImportError, OSError) as exc:
        return errors + [f"row d canonical reducer unavailable: {exc}"], {}, {}
    recomputed = {}
    for backend in ("cpu", "gpu"):
        leg = backends[backend]
        if not isinstance(leg, Mapping):
            errors.append(f"row d {backend} leg is not an object"); continue
        build = leg.get("build") or {}
        if build.get("provenance_claim") != "candidate":
            errors.append(f"row d {backend} is baseline diagnostic provenance, not candidate evidence")
        if any(build.get(k) != expected[k] for k in required):
            errors.append(f"row d {backend} loaded build does not match expected candidate identity")
        if build.get("expected_identity") != {k: expected[k] for k in ("build_id", "module_sha256", "addon_init_sha256")}:
            errors.append(f"row d {backend} did not receive the expected identity contract")
        try:
            recomputed[backend] = native._host_evaluate_backend(dict(leg), raw_path.parent)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"row d {backend} canonical reducer rejected raw evidence: {exc}")
    if set(recomputed) != {"cpu", "gpu"}:
        return errors, {}, {}
    checks = [rec.get("checks", {}) for rec in recomputed.values()]
    accuracy = [c.get(name, {}).get("stats", {}) for c in checks for name in ("adaptive_accuracy", "denoise_accuracy")]
    mean_errors = [value for stats in accuracy for value in (stats.get("mean_rel_error") or {}).values() if _number(value) is not None]
    details = [stats.get("detail_preservation") for stats in accuracy if _number(stats.get("detail_preservation")) is not None]
    if not mean_errors or not details:
        errors.append("row d canonical reducer produced no accuracy metrics")
    required_checks = ("native_settings_honored", "actual_backend_provenance", "adaptive_effect", "denoise_effect", "sample_count_aov_changes", "reference_nonvacuous", "reference_regions_identified")
    subchecks = {
        "adaptive_changes_sample_count_aov": all(c.get("sample_count_aov_changes", {}).get("passed") is True for c in checks),
        "adaptive_lowers_flat_noise": all(c.get("adaptive_effect", {}).get("passed") is True for c in checks),
        "denoise_lowers_residual_noise": all(c.get("denoise_effect", {}).get("passed") is True for c in checks),
        "reference_comparison": all(c.get("adaptive_accuracy", {}).get("passed") is True and c.get("denoise_accuracy", {}).get("passed") is True for c in checks),
    }
    if any(c.get(name, {}).get("status") in ("error", "unmeasured") for c in checks for name in required_checks):
        errors.append("row d has missing/invalid raw legs, telemetry, or AOV capture")
    return errors, {"mean_rel_error_max": max(mean_errors) if mean_errors else None,
                    "detail_preservation_min": min(details) if details else None}, subchecks


def _coverage_reducer():
    spec = importlib.util.spec_from_file_location(
        "pkg278_coverage_manifest_reducer",
        REPO_ROOT / "benchmarks" / "reference_corpus" / "coverage_report.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate_b(records: list[Any], _base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Re-run the coverage reducer from its hash-pinned committed inputs."""
    if len(records) != 1 or not isinstance(records[0], Mapping) or records[0].get("kind") != "coverage_reduction":
        return ["row b requires exactly one canonical coverage reduction record"], {}, {}
    record = records[0]
    paths: dict[str, Path] = {}
    errors: list[str] = []
    for key in ("input", "snapshot", "matrix", "report"):
        path, why = _repo_artifact(record.get(key), f"coverage {key}")
        errors.extend(why)
        if path is not None:
            paths[key] = path
    if errors:
        return errors, {}, {}
    try:
        frozen = json.loads(paths["input"].read_text(encoding="utf-8"))
        snapshot = json.loads(paths["snapshot"].read_text(encoding="utf-8"))
        matrix = json.loads(paths["matrix"].read_text(encoding="utf-8"))
        claimed = json.loads(paths["report"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"row b canonical artifact is not JSON: {exc}"], {}, {}
    if not isinstance(frozen, Mapping) or frozen.get("schema") not in (
            "pkg278.coverage_input_manifest.v3", "pkg278.coverage_input_manifest.v4"):
        return ["row b requires a v3 or v4 frozen coverage input"], {}, {}
    if frozen.get("schema") == "pkg278.coverage_input_manifest.v4" and (
            frozen.get("evidence", {}).get("runner_case_map", {}).get("status") != "ready"):
        return ["row b v4 frozen case map must be ready"], {}, {}
    if paths["input"].resolve() != (REPO_ROOT / str(frozen.get("input_path") or "")).resolve():
        return ["row b input artifact is not the frozen canonical input_path"], {}, {}
    if paths["matrix"].resolve() != (REPO_ROOT / str(frozen.get("matrix", {}).get("path") or "")).resolve():
        return ["row b matrix artifact is not the frozen canonical matrix path"], {}, {}
    if not isinstance(claimed, Mapping) or claimed.get("schema") != "pkg278.coverage_report.v1":
        return ["row b requires a canonical coverage_report.v1 artifact"], {}, {}
    try:
        recomputed = _coverage_reducer().build_report(frozen, snapshot, matrix, REPO_ROOT)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return [f"row b canonical reducer failed: {exc}"], {}, {}
    if claimed != recomputed:
        return ["row b coverage report differs from the canonical recomputation"], {}, {}
    cpu, gpu = recomputed.get("cpu", {}), recomputed.get("gpu", {})
    value = {"cpu_score": cpu.get("score"), "gpu_score": gpu.get("score")}
    subchecks = recomputed.get("subchecks")
    if not isinstance(subchecks, Mapping):
        return ["row b canonical reducer produced no subchecks"], value, {}
    errors = []
    if recomputed.get("status") != "green":
        errors.append(f"row b canonical coverage report status is {recomputed.get('status')!r}, not 'green'")
    return errors, value, dict(subchecks)


PRODUCTION_MATERIALS = 8  # pkg310 corpus size ("N/8")


def _production_leg_mismatches(report: Mapping[str, Any], info: Mapping[str, Any], sid: str,
                               backend: str, sha: str, scene_gates: Mapping[str, Any],
                               build_id: Any) -> list[str]:
    """Fields the leg's own sentinel report must carry (what actually rendered) that differ from the pins."""
    want = {"corpus_scene": sid, "blend_sha256": sha, "requested_device": backend.lower(),
            "effective_device": backend.lower(), "engine": "CUSTOM_RAYTRACER",
            "res_x": scene_gates["res"][0], "res_y": scene_gates["res"][1],
            "samples": scene_gates["spp_gate"], "resolved_seed": scene_gates["seed"],
            "animated_seed": False, "build_id": build_id}
    bad = [k for k, v in want.items() if report.get(k) != v]
    if not isinstance(report.get("blender_version"), str) or not report["blender_version"].startswith("5.2"):
        bad.append("blender_version")
    if not isinstance(report.get("module_sha256"), str) or not _HEX64.match(report["module_sha256"]):
        bad.append("module_sha256")
    if info.get("adaptive") is not False or info.get("denoise") is not False:
        bad.append("adaptive/denoise")
    return bad


def _validate_g(payload: Mapping[str, Any], base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Recompute row (g) from raw per-leg renders + logs and the hash-pinned pkg310 inputs.

    Per (material, backend): ROI-channel bands via ``mc_tolerance.score_material`` on the stored
    linear render, silent drops via ``silent_drop_audit.audit_scene`` on its render log -- the same
    reducers tests/test_production_corpus.py uses.  PASS = in band and no silent pair (pkg310
    "Scoring").  No pass/fail field in the evidence is read."""
    import numpy as np
    import tomllib

    from benchmarks.blender_parity.harness import SENTINEL, _parse_gate_leg_report
    from benchmarks.reference_corpus import mc_tolerance as MC
    from benchmarks.reference_corpus import silent_drop_audit as AUDIT
    inputs, records = payload.get("inputs"), payload.get("records")
    if not isinstance(inputs, Mapping):
        return ["row g requires hash-pinned pkg310 inputs"], {}, {}
    canonical = {"gates": MC.CORPUS / "gates_production.toml", "manifest": MC.PROD / "manifest.json",
                 "node_uses": MC.PROD / "node_uses.json", "matrix": AUDIT.MATRIX}
    paths: dict[str, Path] = {}
    errors: list[str] = []
    for key, want in canonical.items():
        path, why = _repo_artifact(inputs.get(key), f"row g input {key}")
        errors.extend(why)
        if path is not None and path.resolve() != want.resolve():
            errors.append(f"row g input {key} is not the canonical {want.name}")
        elif path is not None:
            paths[key] = path
    if errors:
        return errors, {}, {}
    try:
        gates = tomllib.loads(paths["gates"].read_text(encoding="utf-8"))["scenes"]
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))["scenes"]
        uses = json.loads(paths["node_uses"].read_text(encoding="utf-8"))["scenes"]
        matrix = AUDIT.load_matrix(paths["matrix"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"row g pinned inputs cannot be read: {exc}"], {}, {}
    materials = sorted(gates)
    if len(materials) != PRODUCTION_MATERIALS or set(manifest) != set(materials) or set(uses) != set(materials):
        return [f"row g inputs must pin the same {PRODUCTION_MATERIALS} production materials"], {}, {}
    hashes = {sid: manifest[sid].get("sha256") for sid in materials}
    if payload.get("scene_sha256") != sorted(hashes.values()):
        errors.append("row g scene hashes do not equal the pinned production manifest")
    for sid in materials:
        if uses[sid].get("scene_sha256") != hashes[sid] or uses[sid].get("collection_errors"):
            errors.append(f"row g node_uses snapshot for {sid} is stale or errored")
    if not isinstance(records, list):
        return errors + ["row g requires typed production_leg records"], {}, {}
    seen: set[tuple[str, str]] = set()
    identity_errors: list[str] = []
    score_errors: list[str] = []
    in_band: dict[tuple[str, str], bool] = {}
    silent: dict[tuple[str, str], set[str]] = {}
    modules: set[str] = set()
    for i, rec in enumerate(records):
        sid, backend = (rec.get("material"), rec.get("backend")) if isinstance(rec, Mapping) else (None, None)
        if (not isinstance(rec, Mapping) or rec.get("kind") != "production_leg" or sid not in gates
                or backend not in ("CPU", "GPU") or rec.get("scene_sha256") != hashes.get(sid)):
            errors.append(f"row g record {i} has invalid kind/material/backend/scene hash")
            continue
        if (sid, backend) in seen:
            errors.append(f"row g record {i} duplicates leg {sid}/{backend}")
            continue
        seen.add((sid, backend))
        npy, why_npy = _artifact(rec.get("linear_npy"), base, f"row g {sid}/{backend} render")
        log, why_log = _artifact(rec.get("log"), base, f"row g {sid}/{backend} log")
        score_errors.extend(why_npy + why_log)
        if npy is None or log is None:
            continue
        try:
            img = np.load(npy)
            text = log.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            score_errors.append(f"row g {sid}/{backend} artifact unreadable: {exc}")
            continue
        res_x, res_y = gates[sid]["res"]
        if img.shape != (res_y, res_x, 3) or not np.isfinite(img).all() or float(np.abs(img).max()) <= 1e-9:
            score_errors.append(f"row g {sid}/{backend} render is not a finite non-empty {res_x}x{res_y} RGB image")
            continue
        report, parse_error = _parse_gate_leg_report(text)
        info_line = next((ln for ln in text.splitlines() if ln.startswith("PKG307_INFO ")), "")
        try:
            info = json.loads(info_line[len("PKG307_INFO "):])
        except json.JSONDecodeError:
            info = {}
        if parse_error or f"{SENTINEL} PASS" not in text or f"{SENTINEL} FAIL" in text:
            identity_errors.append(f"row g {sid}/{backend} log lacks one successful sentinel report")
            continue
        bad = _production_leg_mismatches(report, info, sid, backend, hashes[sid], gates[sid],
                                         payload.get("build_id"))
        if bad:
            identity_errors.append(f"row g {sid}/{backend} observed identity/settings differ from the pins: {bad}")
        modules.add(str(report.get("module_sha256")))
        rows = MC.score_material(gates[sid], img, backend.lower())
        in_band[(sid, backend)] = all(r["ok"] for r in rows)
        res = AUDIT.audit_scene(uses[sid]["pairs"], matrix, text)
        silent[(sid, backend)] = {f"{sid}|{p['bl_idname']}|{p['socket']}" for p in res["silent"]}
    complete = seen == {(sid, b) for sid in materials for b in ("CPU", "GPU")}
    if not complete:
        errors.append("row g records do not cover every material on both backends exactly once")
    if len(modules) > 1:
        identity_errors.append("row g legs ran against different engine modules")
    errors += identity_errors + score_errors
    value: dict[str, Any] = {}
    if complete and not score_errors and not identity_errors:
        for b in ("CPU", "GPU"):
            k = b.lower()
            value[f"{k}_pass"] = sum(1 for s in materials if in_band[(s, b)] and not silent[(s, b)])
            value[f"{k}_in_band"] = sum(1 for s in materials if in_band[(s, b)])
            value[f"{k}_silent_pairs"] = len(set().union(*(silent[(s, b)] for s in materials)))
    subchecks = {"legs_complete": complete, "identity_bound": complete and not identity_errors,
                 "bands_recomputed": complete and not score_errors,
                 "zero_silent_degradations": bool(value) and value["cpu_silent_pairs"] == 0
                 and value["gpu_silent_pairs"] == 0}
    return errors, value, subchecks


def _records_validate(payload: Mapping[str, Any], rid: str, base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list) or not records: return ["instrument payload requires non-empty typed records"], {}, {}
    if rid == "a": return _validate_a(records, base, payload.get("scene_sha256"))
    if rid == "b": return _validate_b(records, base)
    if rid == "c": return _validate_c(records, base, payload.get("scene_sha256"), payload.get("build_id"), payload.get("freeze"))
    if rid == "d": return _validate_d(records, base)
    if rid == "e": return _validate_e(records, base)
    if rid == "f": return _validate_f(records, base)
    if rid == "g": return _validate_g(payload, base)
    return [f"row {rid} producer adapter is not yet available"], {}, {}


def _check_common(row: Mapping[str, Any], spec: Mapping[str, Any],
                  repo_root: Path, measurement_failure_is_error: bool = True) -> list[str]:
    reasons: list[str] = []
    for fld in BASE_FIELDS:
        if fld not in row:
            reasons.append(f"missing required field: {fld}")
    scenes = row.get("scene_sha256") or []
    if not isinstance(scenes, list) or any(not _HEX64.match(str(s)) for s in scenes):
        reasons.append("scene_sha256 must be a list of 64-hex digests")
    if len(scenes) < int(spec.get("min_scenes", 0)):
        reasons.append(f"scene_sha256 has {len(scenes)} entries; "
                       f"row {row.get('row')} requires >= {spec.get('min_scenes')}")
    if not str(row.get("build_id") or "").strip():
        reasons.append("build_id missing")
    backends = set(row.get("backend") or [])
    missing_backends = [b for b in spec.get("required_backends", ()) if b not in backends]
    if missing_backends:
        reasons.append(f"required backend(s) absent: {missing_backends}")
    dims = row.get("dimensions") or {}
    for dim in spec.get("required_dimensions", ()):
        observed = dims.get(dim) if isinstance(dims, Mapping) else None
        if not observed or isinstance(observed, (bool, list, tuple, dict, set)):
            reasons.append(f"required dimension absent: {dim}")
    # Frozen thresholds: the row may not loosen (or drop) a bound.
    supplied = row.get("threshold") or {}
    for key, rule in spec.get("threshold", {}).items():
        if key not in supplied:
            reasons.append(f"threshold missing frozen bound: {key}")
            continue
        supplied_value = _number(supplied[key])
        if supplied_value is None:
            reasons.append(f"threshold {key} must be a finite number")
            continue
        if "max" in rule and supplied_value > float(rule["max"]):
            reasons.append(f"threshold {key} loosened: {supplied[key]} > {rule['max']}")
        if "min" in rule and supplied_value < float(rule["min"]):
            reasons.append(f"threshold {key} loosened: {supplied[key]} < {rule['min']}")
    # Value must be inside the frozen bounds.
    value = row.get("value")
    if not isinstance(value, Mapping):
        reasons.append("value must be an object of measured metrics")
    else:
        for key, rule in spec.get("threshold", {}).items():
            if key not in value or value[key] is None:
                reasons.append(f"value missing measured metric: {key}")
            elif _number(value[key]) is None:
                reasons.append(f"value {key} must be a finite number")
            elif measurement_failure_is_error and not _bound(_number(value[key]), rule):
                reasons.append(f"value {key}={value[key]} outside frozen bound {rule}")
    payload, payload_base, payload_errors = _typed_payload(row, str(row.get("row")), spec, repo_root)
    reasons.extend(payload_errors)
    if payload is not None and payload_base is not None:
        rid = str(row.get("row"))
        measurement_failures: list[str] = []
        if rid == "c":
            record_errors, derived_value, derived_subchecks, measurement_failures = _evaluate_c(
                payload.get("records", []), payload_base, payload.get("scene_sha256"),
                payload.get("build_id"), payload.get("freeze"))
        else:
            record_errors, derived_value, derived_subchecks = _records_validate(payload, rid, payload_base)
        reasons.extend(record_errors)
        if derived_value and row.get("value") != derived_value:
            reasons.append("manifest value is not the value derived from concrete records")
        if derived_subchecks and row.get("subchecks") != derived_subchecks:
            reasons.append("manifest subchecks are not derived from concrete records")
        # A failed required check is a measured RED during row computation.  A
        # C RED remains semantically valid in validate_manifest, where
        # measurement_failure_is_error is deliberately false.
        if measurement_failure_is_error:
            for name in spec.get("required_subchecks", ()):
                result = derived_subchecks.get(name) if isinstance(derived_subchecks, Mapping) else None
                if not _subcheck_passed(result):
                    reasons.append(f"required subcheck failed or missing: {name}")
        if rid == "c":
            if row.get("measurement_failures") != measurement_failures:
                reasons.append("manifest measurement failures are not derived from concrete records")
            if measurement_failure_is_error:
                reasons.extend(measurement_failures)
    return reasons


def _check_scanner_823(row: Mapping[str, Any], repo_root: Path) -> tuple[bool, str]:
    entry = row.get("scanner_issue_823")
    try:
        return _coverage_reducer().verify_scanner_integration_proof(entry, repo_root)
    except (ImportError, OSError, ValueError):
        return False, "scanner integration verifier unavailable"


def compute_row(rid: str, raw: Mapping[str, Any] | None, spec: Mapping[str, Any],
                repo_root: Path, existing: Mapping[str, Any] | None = None
                ) -> tuple[dict[str, Any], list[str]]:
    """Compute one row's status. Returns (row, reasons). Never trusts raw status."""
    reasons: list[str] = []
    existing_status = str((existing or {}).get("status") or "")

    if raw is None:
        row = empty_row(rid, spec)
        # A stored green with no instrument is a hand-edited status: reject it.
        if existing_status == "green":
            row["status"] = "red"
            row["hand_edit_detected"] = True
            reasons.append("hand-edited status: green recorded with no instrument output")
        else:
            row["status"] = "unmeasured"
            reasons.append("no instrument output")
        return row, reasons

    row = empty_row(rid, spec)
    for key, value in raw.items():
        if key != "status":  # caller-supplied status is never trusted
            row[key] = value
    row["row"] = rid
    row.setdefault("instrument", spec["instrument"])
    row["status"] = "red"  # provisional until checks pass
    reasons = _check_common(row, spec, repo_root)

    if spec.get("requires_scanner_823"):
        scanner_ok, scanner_why = _check_scanner_823(row, repo_root)
        if not scanner_ok:
            # No score is published before #823: the row is unmeasured, not red.
            row["status"] = "unmeasured"
            reasons.append(f"gate (b) not scored: {scanner_why}")
            return row, reasons

    row["status"] = "green" if not reasons else "red"
    if existing_status and existing_status != row["status"]:
        # The stored status disagrees with the recomputed one: a hand edit.
        row["hand_edit_detected"] = True
        reasons.append(f"hand-edited status: stored {existing_status!r} "
                       f"!= computed {row['status']!r}")
        row["status"] = "red"
    return row, reasons


def assemble(instruments: Mapping[str, Mapping[str, Any] | None],
             repo_root: Path = REPO_ROOT,
             existing: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Assemble the manifest so it ALWAYS has rows a-g. Returns (manifest, reasons)."""
    existing_rows = (existing or {}).get("rows", {}) if existing else {}
    rows: dict[str, Any] = {}
    reasons: dict[str, list[str]] = {}
    for rid in ROWS:
        row, why = compute_row(rid, instruments.get(rid), ROW_SPEC[rid],
                               repo_root, existing_rows.get(rid))
        rows[rid] = row
        reasons[rid] = why
    return {
        "schema": "pkg278.acceptance_manifest.v1",
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
    }, reasons


# --------------------------------------------------------------------------- #
# Validation against the normative schema shape
# --------------------------------------------------------------------------- #

def validate_shape(manifest: Mapping[str, Any]) -> list[str]:
    """Enforce the shape the JSON schema declares (no jsonschema dependency)."""
    errors: list[str] = []
    if manifest.get("schema") != "pkg278.acceptance_manifest.v1":
        errors.append("schema must be 'pkg278.acceptance_manifest.v1'")
    rows = manifest.get("rows")
    if not isinstance(rows, Mapping):
        return errors + ["rows must be an object"]
    missing = [r for r in ROWS if r not in rows]
    extra = [r for r in rows if r not in ROWS]
    if missing:
        errors.append(f"rows missing: {missing}")
    if extra:
        errors.append(f"unknown rows: {extra}")
    for rid in ROWS:
        row = rows.get(rid)
        if not isinstance(row, Mapping):
            continue
        if row.get("row") != rid:
            errors.append(f"row {rid}: row id mismatch")
        if row.get("status") not in ("green", "red", "unmeasured"):
            errors.append(f"row {rid}: invalid status {row.get('status')!r}")
        for fld in ("instrument", "scene_sha256", "backend", "dimensions", "date"):
            if fld not in row:
                errors.append(f"row {rid}: missing field {fld}")
        if row.get("instrument") not in {"viewport_latency", "coverage_report", "trio_parity", "native_panel_smoke", "issue_triage", "clean_install", "production_node_score"}:
            errors.append(f"row {rid}: invalid instrument")
        if not isinstance(row.get("scene_sha256"), list) or any(not _HEX64.match(str(x)) for x in row.get("scene_sha256", [])):
            errors.append(f"row {rid}: scene_sha256 must be digest array")
        if not isinstance(row.get("backend"), list) or any(x not in ("CPU", "GPU") for x in row.get("backend", [])) or len(set(row.get("backend", []))) != len(row.get("backend", [])):
            errors.append(f"row {rid}: backend must be unique CPU/GPU array")
        if not isinstance(row.get("settings"), Mapping) or not isinstance(row.get("metric"), Mapping) or not isinstance(row.get("threshold"), Mapping) or not isinstance(row.get("dimensions"), Mapping):
            errors.append(f"row {rid}: settings/metric/threshold/dimensions must be objects")
        if row.get("value") is not None and not isinstance(row.get("value"), Mapping):
            errors.append(f"row {rid}: value must be an object or null")
        if row.get("status") == "green":
            if not row.get("evidence_path"):
                errors.append(f"row {rid}: green without evidence_path")
            if not _HEX64.match(str(row.get("evidence_sha256") or "").lower()):
                errors.append(f"row {rid}: green without valid evidence_sha256")
            if row.get("value") is None:
                errors.append(f"row {rid}: green without value")
            if not str(row.get("build_id") or "").strip():
                errors.append(f"row {rid}: green without build_id")
            if rid not in ("e", "f") and not row.get("scene_sha256"):
                errors.append(f"row {rid}: green without scene hash")
    return errors


def validate_manifest(manifest: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    """Shape + semantic validation. Any error means the manifest is rejected."""
    errors = validate_shape(manifest)
    rows = manifest.get("rows", {})
    for rid in ROWS:
        row = rows.get(rid)
        if not isinstance(row, Mapping):
            continue
        status = row.get("status")
        if status == "green" or (rid == "c" and status == "red"):
            reasons = _check_common(row, ROW_SPEC[rid], repo_root,
                                    measurement_failure_is_error=status == "green")
            if ROW_SPEC[rid].get("requires_scanner_823"):
                ok, why = _check_scanner_823(row, repo_root)
                if not ok:
                    reasons.append(f"scanner #823: {why}")
            if reasons:
                errors.append(f"row {rid}: {status} fails semantic recomputation: {reasons[:3]}")
    return errors


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def adapt_c_instrument(raw_path: Path) -> dict[str, Any]:
    """Adapt immutable raw C evidence into the generic manifest-row contract."""
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    if (not isinstance(payload, Mapping) or payload.get("schema") != PAYLOAD_SCHEMA
            or payload.get("row") != "c" or payload.get("instrument") != "trio_parity"):
        raise ValueError("row-c raw evidence must be a trio_parity v2 instrument")
    _provenance_errors, value, subchecks, measurement_failures = _evaluate_c(
        payload.get("records", []), raw_path.parent, payload.get("scene_sha256"),
        payload.get("build_id"), payload.get("freeze"))
    row = dict(payload)
    row["evidence_path"] = str(raw_path)
    row["evidence_sha256"] = sha256_file(raw_path)
    row["dimensions"] = {
        "backend": "CPU+GPU",
        "scene": "exact frozen trio scene SHA-256s",
        "roi": "freeze-declared ROIs",
        "seeds": "8 frozen spread seeds per backend",
    }
    row["value"] = value
    row["subchecks"] = subchecks
    row["measurement_failures"] = measurement_failures
    row["date"] = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    return row


def adapt_c_seed_instrument(legs_dir: Path, freeze_path: Path, out_path: Path) -> dict[str, Any]:
    """Wrap a ``harness.py --seeds study`` output dir (``<legs_dir>/seed_legs/<role>_<backend>_<control>/
    s<seed>.npy|.log``, ``mask_s<seed>.npy``) into a row-(c) payload written at ``out_path``.

    Every file on disk is listed and hash-pinned in place (paths relative to ``out_path``'s directory);
    the reducer, not this adapter, decides what is admissible.  The payload carries no verdict."""
    from benchmarks.blender_parity.harness import STUDY_SEEDS
    out_dir = Path(out_path).resolve().parent

    def ref(path: Path) -> dict[str, str] | None:
        if not path.is_file():
            return None
        try:
            rel = path.resolve().relative_to(out_dir)
        except ValueError as exc:
            raise ValueError(f"row-c artifact {path} is not beneath the output directory {out_dir}") from exc
        return {"path": str(rel).replace("\\", "/"), "sha256": sha256_file(path)}

    freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    roles = freeze.get("roles") if isinstance(freeze, Mapping) else None
    if not isinstance(roles, Mapping):
        raise TypeError("row-c freeze lacks roles")
    records: list[dict[str, Any]] = []
    for role, frozen in roles.items():
        kinds = ["baseline"] + [c.get("kind") for c in frozen.get("controls", [])]
        for backend in ("CPU", "GPU"):
            for kind in kinds:
                leg_dir = Path(legs_dir) / "seed_legs" / f"{role.replace(':', '_')}_{backend.lower()}_{kind}"
                found = sorted(int(p.stem[1:]) for p in leg_dir.glob("s*.npy") if p.stem[1:].isdigit())
                for seed in (found if kind == "baseline" else [s for s in found if s == frozen.get("seed")]):
                    stem = leg_dir / f"s{seed}"
                    record = {"kind": "seed_leg", "role": role, "backend": backend, "control": kind, "seed": seed,
                              "linear_npy": ref(stem.with_suffix(".npy")), "log": ref(stem.with_suffix(".log"))}
                    if kind != "baseline":
                        record["feature_mask"] = ref(leg_dir / f"mask_s{seed}.npy")
                    records.append(record)
    return {"schema": PAYLOAD_SCHEMA, "row": "c", "instrument": "trio_parity",
            "scene_sha256": sorted(str(r.get("scene_sha256")) for r in roles.values()),
            "build_id": freeze.get("build_id"), "backend": ["CPU", "GPU"],
            "settings": {"source": "harness.py --seeds study", "seeds": list(STUDY_SEEDS)},
            "metric": {"name": "welch_tiles_1b", **GATE_C_WELCH, "multiple_testing": "holm",
                       "guard": "per-ROI channel-mean ratio of the 8-seed means",
                       "informational": "per-ROI SSIM of the frozen-seed pair"},
            "value": {}, "threshold": {k: rule.get("max", rule.get("min")) for k, rule in ROW_SPEC["c"]["threshold"].items()},
            "freeze": ref(Path(freeze_path)), "records": records}


def load_instruments(instruments_dir: Path | None,
                     overrides: Mapping[str, Path] | None) -> dict[str, Any]:
    def adapt(path: Path) -> Any:
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Producer payloads are not manifest rows.  Wrap their own immutable
        # file as evidence and derive gate-e values/subchecks from its raw
        # artifacts; do not invent dimensions or accept producer pass flags.
        if (isinstance(payload, Mapping) and payload.get("schema") == PAYLOAD_SCHEMA
                and payload.get("row") == "a" and payload.get("instrument") == "viewport_latency"):
            errors, value, subchecks = _validate_a(payload.get("records", []), path.parent,
                                                   payload.get("scene_sha256"))
            row = dict(payload)
            row["evidence_path"] = str(path)
            row["evidence_sha256"] = sha256_file(path)
            row["dimensions"] = {"scene": "frozen workload SHA", "edit_kind": "camera/material",
                                 "repetitions": "3x100 serialized edits"}
            row["subchecks"] = subchecks if not errors else {}
            row["value"] = value
            row["date"] = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            return row
        if (isinstance(payload, Mapping) and payload.get("schema") == PAYLOAD_SCHEMA
                and payload.get("row") == "b" and payload.get("instrument") == "coverage_report"):
            _errors, value, subchecks = _validate_b(payload.get("records", []), path.parent)
            row = dict(payload)
            row["evidence_path"] = str(path)
            row["evidence_sha256"] = sha256_file(path)
            row["dimensions"] = {"backend": "CPU+GPU", "variant": "frozen-ledger"}
            row["subchecks"] = subchecks
            row["value"] = value
            row["date"] = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            return row
        if (isinstance(payload, Mapping) and payload.get("schema") == PAYLOAD_SCHEMA
                and payload.get("row") == "c" and payload.get("instrument") == "trio_parity"):
            return adapt_c_instrument(path)
        if (isinstance(payload, Mapping) and payload.get("schema") == PAYLOAD_SCHEMA
                and payload.get("row") == "e" and payload.get("instrument") == "issue_triage"):
            errors, value, subchecks = _validate_e(payload.get("records", []), path.parent)
            row = dict(payload)
            row["evidence_path"] = str(path)
            row["evidence_sha256"] = sha256_file(path)
            row["dimensions"] = {"issue_snapshot": "raw-artifacts", "ratings": "independent-review"}
            row["subchecks"] = subchecks if not errors else {}
            row["value"] = value if not errors else payload.get("value")
            row["date"] = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            return row
        if (isinstance(payload, Mapping) and payload.get("schema") == PAYLOAD_SCHEMA
                and payload.get("row") == "d" and payload.get("instrument") == "native_panel_smoke"):
            errors, value, subchecks = _validate_d(payload.get("records", []), path.parent)
            row = dict(payload)
            row["evidence_path"] = str(path)
            row["evidence_sha256"] = sha256_file(path)
            row["dimensions"] = {"backend": "CPU+GPU", "panel": "native Cycles settings"}
            row["subchecks"] = subchecks if not errors else {}
            row["value"] = value
            row["date"] = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            return row
        if (isinstance(payload, Mapping) and payload.get("schema") == PAYLOAD_SCHEMA
                and payload.get("row") == "g" and payload.get("instrument") == "production_node_score"):
            _errors, value, subchecks = _validate_g(payload, path.parent)
            row = dict(payload)
            row["evidence_path"] = str(path)
            row["evidence_sha256"] = sha256_file(path)
            row["dimensions"] = {"backend": "CPU+GPU", "material": "eight pkg310 production scenes"}
            row["subchecks"] = subchecks
            row["value"] = value
            row["date"] = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            return row
        return payload

    out: dict[str, Any] = {r: None for r in ROWS}
    if instruments_dir is not None:
        for rid in ROWS:
            candidate = Path(instruments_dir) / rid / "instrument.json"
            if candidate.is_file():
                out[rid] = adapt(candidate)
    for rid, path in (overrides or {}).items():
        if rid in out and Path(path).is_file():
            out[rid] = adapt(Path(path))
    return out


def adapt_d_instrument(raw_path: Path, expected_identity: Mapping[str, str]) -> dict[str, Any]:
    """Create the v2 row-(d) adapter; the raw aggregate remains the evidence."""
    required = ("build_id", "engine_id", "module_sha256", "addon_init_sha256")
    if any(not isinstance(expected_identity.get(key), str) or not expected_identity[key] for key in required):
        raise ValueError("expected row-d identity needs build_id, engine_id, module_sha256, addon_init_sha256")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("instrument") != "gate_native_panels":
        raise ValueError("row-d raw evidence must be a gate_native_panels aggregate")
    build_id = expected_identity["build_id"]
    scene_hashes = sorted({str((record or {}).get("scene_sha256"))
                           for record in (raw.get("backends") or {}).values()
                           if isinstance(record, Mapping) and str(record.get("scene_sha256") or "")})
    return {"schema": PAYLOAD_SCHEMA, "row": "d", "instrument": "native_panel_smoke",
            "scene_sha256": scene_hashes, "build_id": build_id, "backend": ["CPU", "GPU"],
            "settings": raw.get("declared") or {}, "metric": {"source": "canonical_native_panel_reducer"},
            "value": {}, "threshold": {"mean_rel_error_max": 0.02, "detail_preservation_min": 0.95},
            "records": [{"kind": "native_panel_aggregate",
                         "artifact": {"path": raw_path.name, "sha256": sha256_file(raw_path)},
                         "expected_identity": dict(expected_identity)}]}


def _repo_ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    try:
        rel = path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"canonical gate-b artifact escapes this checkout: {path}") from exc
    return {"path": str(rel).replace("\\", "/"), "sha256": sha256_file(path)}


def adapt_b_instrument(report_path: Path, input_path: Path, snapshot_path: Path,
                       matrix_path: Path) -> dict[str, Any]:
    """Wrap a canonical report only after reproducing it from pinned inputs."""
    report_path, input_path = Path(report_path).resolve(), Path(input_path).resolve()
    snapshot_path, matrix_path = Path(snapshot_path).resolve(), Path(matrix_path).resolve()
    frozen = json.loads(input_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    claimed = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(frozen, Mapping) or frozen.get("schema") not in (
            "pkg278.coverage_input_manifest.v3", "pkg278.coverage_input_manifest.v4"):
        raise ValueError("row-b adapter requires coverage_input_v3.json or coverage_input_v4.json")
    if frozen.get("schema") == "pkg278.coverage_input_manifest.v4" and (
            frozen.get("evidence", {}).get("runner_case_map", {}).get("status") != "ready"):
        raise ValueError("row-b v4 frozen case map must be ready")
    canonical_input = (REPO_ROOT / str(frozen.get("input_path") or "")).resolve()
    if canonical_input != input_path:
        raise ValueError("row-b input must be the frozen input_path in this checkout")
    recomputed = _coverage_reducer().build_report(frozen, snapshot, matrix, REPO_ROOT)
    if claimed != recomputed:
        raise ValueError("coverage report differs from canonical build_report recomputation")
    build = frozen.get("evidence", {}).get("runner_case_map", {}).get("candidate_build", {})
    build_id = build.get("build_id") if isinstance(build, Mapping) else None
    if not isinstance(build_id, str) or not build_id:
        raise ValueError("row-b frozen case map has no candidate build identity")
    scenes = frozen.get("corpus", {}).get("scenes", {})
    record = {"kind": "coverage_reduction", "input": _repo_ref(input_path),
              "snapshot": _repo_ref(snapshot_path), "matrix": _repo_ref(matrix_path),
              "report": _repo_ref(report_path)}
    return {"schema": PAYLOAD_SCHEMA, "row": "b", "instrument": "coverage_report",
            "scene_sha256": sorted(str(row.get("sha256")) for row in scenes.values() if isinstance(row, Mapping)),
            "build_id": build_id, "backend": ["CPU", "GPU"],
            "settings": {"source": "canonical_coverage_reducer"}, "metric": {"source": "build_report"},
            "value": {"cpu_score": recomputed.get("cpu", {}).get("score"),
                      "gpu_score": recomputed.get("gpu", {}).get("score")},
            "threshold": {"cpu_score": .95, "gpu_score": .95}, "dimensions": {"backend": "CPU+GPU", "variant": "frozen-ledger"},
            "subchecks": dict(recomputed.get("subchecks") or {}),
            "scanner_issue_823": frozen.get("scanner_issue_823"), "records": [record]}


def adapt_g_instrument(work_dir: Path, out_path: Path) -> dict[str, Any]:
    """Wrap a pkg310 production work dir (``<material>_<cpu|gpu>_s<seed>.npy/.log``, as written by
    tests/test_production_corpus.py via ``PKG310_WORK``) into a row-(g) payload.

    Renders and logs are copied beside ``out_path`` and hash-pinned; the payload is accepted only if
    the canonical reducer finds no evidence-integrity error.  It carries no score of its own."""
    import shutil

    import tomllib

    from benchmarks.blender_parity.harness import _parse_gate_leg_report
    from benchmarks.reference_corpus import mc_tolerance as MC
    from benchmarks.reference_corpus import silent_drop_audit as AUDIT
    inputs = {"gates": MC.CORPUS / "gates_production.toml", "manifest": MC.PROD / "manifest.json",
              "node_uses": MC.PROD / "node_uses.json", "matrix": AUDIT.MATRIX}
    gates = tomllib.loads(inputs["gates"].read_text(encoding="utf-8"))["scenes"]
    manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))["scenes"]
    work_dir, out_path = Path(work_dir), Path(out_path)
    out_dir = out_path.parent
    (out_dir / "renders").mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    build_ids: set[str] = set()
    for sid in sorted(gates):
        for backend in ("CPU", "GPU"):
            stem = f"{sid}_{backend.lower()}_s{gates[sid]['seed']}"
            ref: dict[str, dict[str, str]] = {}
            for key, suffix in (("linear_npy", ".npy"), ("log", ".log")):
                src = work_dir / f"{stem}{suffix}"
                if not src.is_file():
                    raise ValueError(f"missing production render artifact: {src}")
                shutil.copyfile(src, out_dir / "renders" / src.name)
                ref[key] = {"path": f"renders/{src.name}", "sha256": sha256_file(out_dir / "renders" / src.name)}
            report, _err = _parse_gate_leg_report((out_dir / ref["log"]["path"]).read_text(encoding="utf-8", errors="replace"))
            build_ids.add(str(report.get("build_id") or ""))
            records.append({"kind": "production_leg", "material": sid, "backend": backend,
                            "scene_sha256": manifest[sid]["sha256"], **ref})
    if len(build_ids) != 1 or not next(iter(build_ids)):
        raise ValueError(f"production legs must report one non-empty build id, got {sorted(build_ids)}")
    threshold: dict[str, Any] = {k: rule.get("max", rule.get("min")) for k, rule in ROW_SPEC["g"]["threshold"].items()}
    payload: dict[str, Any] = {
        "schema": PAYLOAD_SCHEMA, "row": "g", "instrument": "production_node_score",
        "scene_sha256": sorted(e["sha256"] for e in manifest.values()), "build_id": build_ids.pop(),
        "backend": ["CPU", "GPU"],
        "settings": {"source": "tests/test_production_corpus.py work dir", "adaptive": False, "denoise": False,
                     "seeds": sorted({g["seed"] for g in gates.values()})},
        "metric": {"source": "mc_tolerance.score_material + silent_drop_audit.audit_scene"},
        "value": {}, "threshold": threshold,
        "inputs": {key: _repo_ref(path) for key, path in inputs.items()}, "records": records}
    errors, value, _subchecks = _validate_g(payload, out_dir)
    if errors:
        raise ValueError("production evidence rejected: " + "; ".join(errors[:5]))
    payload["value"] = value
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Assemble/validate the exit-gate acceptance manifest (pkg278).")
    p.add_argument("--instruments-dir", type=Path,
                   default=REPO_ROOT / "docs" / "blender_parity" / "evidence")
    p.add_argument("--instrument", action="append", default=[],
                   metavar="ROW=PATH", help="override one row's instrument JSON (repeatable)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--validate", action="store_true",
                   help="validate an existing manifest instead of assembling")
    p.add_argument("--existing", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--adapt-d", type=Path, metavar="RAW_JSON",
                   help="write a v2 row-(d) adapter around hash-linked native-panel raw evidence")
    p.add_argument("--adapt-b-report", type=Path, metavar="COVERAGE_REPORT_JSON",
                   help="wrap a canonical gate-b coverage_report.json after recomputation")
    p.add_argument("--adapt-b-input", type=Path, metavar="COVERAGE_INPUT_V3_OR_V4")
    p.add_argument("--adapt-b-snapshot", type=Path, metavar="NODE_USES_JSON")
    p.add_argument("--adapt-b-matrix", type=Path, metavar="COVERAGE_MATRIX_JSON")
    p.add_argument("--adapt-g", type=Path, metavar="PKG310_WORK_DIR",
                   help="write a row-(g) production-node-score payload (to --out) from a pkg310 "
                        "PKG310_WORK dir; renders/logs are copied beside it and hash-pinned")
    p.add_argument("--adapt-c-seeds", type=Path, metavar="SEED_LEGS_OUT_DIR",
                   help="write a row-(c) Welch payload (to --out, beside the legs) from a "
                        "`harness.py --seeds study` output dir; legs are hash-pinned in place")
    p.add_argument("--adapt-c-freeze", type=Path, metavar="GATE_C_FREEZE_JSON",
                   help="with --adapt-c-seeds: the freeze the legs used (default <dir>/gate_c.freeze.json)")
    p.add_argument("--expected-d-build-id")
    p.add_argument("--expected-d-engine-id")
    p.add_argument("--expected-d-module-sha256")
    p.add_argument("--expected-d-addon-init-sha256")
    args = p.parse_args(argv)

    if args.adapt_d:
        identity = {"build_id": args.expected_d_build_id, "engine_id": args.expected_d_engine_id,
                    "module_sha256": args.expected_d_module_sha256,
                    "addon_init_sha256": args.expected_d_addon_init_sha256}
        try:
            payload = adapt_d_instrument(args.adapt_d, identity)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            p.error(str(exc))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    if args.adapt_g:
        try:
            payload = adapt_g_instrument(args.adapt_g, args.out)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            p.error(str(exc))
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}  value={payload['value']}")
        return 0

    if args.adapt_c_seeds:
        if args.out == DEFAULT_OUT:
            p.error("--adapt-c-seeds requires --out <dir>/row_c_welch.json beside the legs")
        try:
            payload = adapt_c_seed_instrument(args.adapt_c_seeds,
                                              args.adapt_c_freeze or args.adapt_c_seeds / "gate_c.freeze.json",
                                              args.out)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            p.error(str(exc))
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        errors, value, subchecks, failures = _evaluate_c(payload["records"], args.out.resolve().parent,
                                                         payload["scene_sha256"], payload["build_id"], payload["freeze"])
        print(f"wrote {args.out}  records={len(payload['records'])}")
        print(json.dumps({"value": value, "subchecks": subchecks, "measurement_failures": failures,
                          "evidence_errors": errors[:20], "evidence_error_count": len(errors)}, indent=1))
        return 0 if not errors else 1

    if args.adapt_b_report:
        if not all((args.adapt_b_input, args.adapt_b_snapshot, args.adapt_b_matrix)):
            p.error("--adapt-b-report requires --adapt-b-input, --adapt-b-snapshot and --adapt-b-matrix")
        try:
            payload = adapt_b_instrument(args.adapt_b_report, args.adapt_b_input,
                                         args.adapt_b_snapshot, args.adapt_b_matrix)
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            p.error(str(exc))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    overrides: dict[str, Path] = {}
    for spec in args.instrument:
        rid, _, path = spec.partition("=")
        overrides[rid] = Path(path)

    if args.validate:
        path = args.existing or args.out
        if not Path(path).is_file():
            print(f"manifest not found: {path}", file=sys.stderr)
            return 2
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        errors = validate_manifest(manifest, REPO_ROOT)
        if args.json:
            print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
        else:
            print(f"manifest {path}: {'VALID' if not errors else 'REJECTED'}")
            for err in errors:
                print(f"  - {err}")
        return 0 if not errors else 1

    existing = None
    if args.existing and Path(args.existing).is_file():
        existing = json.loads(Path(args.existing).read_text(encoding="utf-8"))
    elif args.out.is_file():
        existing = json.loads(Path(args.out).read_text(encoding="utf-8"))

    instruments = load_instruments(args.instruments_dir, overrides)
    manifest, reasons = assemble(instruments, REPO_ROOT, existing)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    errors = validate_manifest(manifest, REPO_ROOT)
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors,
                          "statuses": {r: manifest["rows"][r]["status"] for r in ROWS}}, indent=2))
    else:
        print(f"wrote {args.out}")
        for rid in ROWS:
            print(f"  ({rid}) {manifest['rows'][rid]['status']}"
                  + (f"  -- {reasons[rid][0]}" if reasons[rid] else ""))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
