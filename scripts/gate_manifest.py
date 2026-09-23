#!/usr/bin/env python
"""pkg278 - assemble and validate the Pillar-4 exit-gate acceptance manifest.

One file, ``docs/blender_parity/acceptance_manifest.json``, is the gate's only
source of truth: one row per north-star row (a)-(f), each carrying scene
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
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "docs" / "blender_parity" / "acceptance_manifest.schema.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "blender_parity" / "acceptance_manifest.json"

ROWS = ("a", "b", "c", "d", "e", "f")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

BASE_FIELDS = (
    "instrument", "scene_sha256", "build_id", "backend", "settings", "metric",
    "value", "threshold", "evidence_path", "evidence_sha256", "dimensions", "date",
)

PAYLOAD_SCHEMA = "pkg278.instrument.v2"
# These are logical corpus roles, not substitute legacy/current filenames.  The
# producer freezes the resolved actual scene id and blend hash for each role.
TRIO_ROLES = ("materials_hall", "textures_mapping", "world_sky:terrace-with-hair")


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
    "c": {
        "instrument": "trio_parity",
        "required_dimensions": ("backend", "scene", "roi"),
        "required_backends": ("CPU", "GPU"),
        "min_scenes": 3,
        "threshold": {"roi_pct_max": {"max": 5.0}, "ssim_min": {"min": 0.95}},
        "required_subchecks": (
            "cpu_exit_zero", "gpu_exit_zero", "pinned_images", "non_vacuity",
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
    errors: list[str] = []; samples: list[float] = []; cancels: list[float] = []; cells = set(); scenes = set(); stale = 0
    if len(records) != 1200:
        errors.append("row a requires exactly 1200 concrete latency records")
    for i, r in enumerate(records):
        if not isinstance(r, Mapping): errors.append(f"row a record {i} is not an object"); continue
        fields = (r.get("scene_sha256"), r.get("edit_kind"), r.get("batch"), r.get("repetition"))
        if (not isinstance(fields[0], str) or not _HEX64.match(fields[0]) or fields[1] not in ("camera", "material")
                or isinstance(fields[2], bool) or fields[2] not in (0, 1, 2)
                or isinstance(fields[3], bool) or fields[3] not in range(100)):
            errors.append(f"row a record {i} has invalid concrete dimensions"); continue
        if r.get("backend") != "GPU" or r.get("denoise_enabled") is not False:
            errors.append(f"row a record {i} is not GPU denoise-off evidence")
        values = [_number(r.get(k)) for k in ("event_ns", "present_ns", "cancel_ack_ns", "stale_frames_after_ack")]
        if any(x is None for x in values) or values[0] < 0 or values[1] < values[0] or values[2] < values[0] or values[3] < 0:
            errors.append(f"row a record {i} has invalid event/present/cancel/stale values"); continue
        _, why = _artifact(r.get("artifact"), base, f"row a record {i}"); errors.extend(why)
        cell = tuple(fields); cells.add(cell); scenes.add(fields[0]); samples.append((values[1]-values[0])/1e6); cancels.append((values[2]-values[0])/1e6); stale += int(values[3])
    if not isinstance(expected_scenes, list) or len(expected_scenes) != 2 or set(expected_scenes) != scenes or len(scenes) != 2 or len(cells) != 1200:
        errors.append("row a records must cover two pinned scenes × camera/material × 3 batches × 100 repetitions")
    value = {"gpu_p95_ms": _pct(samples, .95) if samples else None, "gpu_p99_ms": _pct(samples, .99) if samples else None,
             "cancel_p95_ms": _pct(cancels, .95) if cancels else None, "cancel_p99_ms": _pct(cancels, .99) if cancels else None,
             "stale_frames_after_ack": stale}
    return errors, value, {"both_pinned_scenes": len(scenes) == 2, "three_by_hundred_repetitions": len(cells) == 1200, "denoise_excluded": not any("denoise" in e for e in errors), "gpu_only_latency": not any("not GPU" in e for e in errors)}


def _validate_c(records: list[Any], base: Path, expected_hashes: Any, build_id: Any, freeze_ref: Any = None) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Fail closed unless every semantic witness is a paired control delta."""
    import numpy as np

    from benchmarks.reference_bank.metrics import compute_ssim
    from benchmarks.reference_bank.runner import compute_channel_mean_ratio
    errors=[]; pairs=set(); hashes={}; images={}; masks={}; ratios=[]; ssims=[]; reports={}; leg_keys=set()
    freeze_path, why = _artifact(freeze_ref, base, "row c freeze"); errors.extend(why)
    try: freeze=json.loads(freeze_path.read_text(encoding="utf-8")) if freeze_path else {}
    except (OSError,json.JSONDecodeError): freeze={}; errors.append("row c freeze cannot be read")
    roles = freeze.get("roles", {}) if isinstance(freeze, Mapping) else {}
    if not isinstance(roles, Mapping) or set(roles) != set(TRIO_ROLES):
        errors.append("row c freeze lacks the exact declared trio roles")
        roles = {}
    freeze_sha = sha256_file(freeze_path) if freeze_path else ""
    if freeze.get("build_id") != build_id or not isinstance(build_id, str) or not build_id:
        errors.append("row c freeze build identity differs from the instrument")
    for field in ("module_sha256", "addon_sha256"):
        if not isinstance(freeze.get(field), str) or not _HEX64.match(freeze[field]):
            errors.append(f"row c freeze has invalid {field}")
    expected_legs = {(role, backend, control.get("kind", "baseline"))
                     for role, frozen in roles.items() for backend in ("CPU", "GPU")
                     for control in ([{"kind": "baseline"}] + list(frozen.get("controls", [])))}
    if len(records) != len(expected_legs): errors.append("row c requires paired baseline/control F12 evidence for every declared feature")
    for i,r in enumerate(records):
        if not isinstance(r,Mapping): errors.append(f"row c record {i} is not an object"); continue
        role,scene,backend,digest,control=(r.get(k) for k in ("role","scene_id","backend","scene_sha256","control"))
        frozen=roles.get(role,{})
        allowed={"baseline"}|{c.get("kind") for c in frozen.get("controls",[]) if isinstance(c,Mapping)}
        if role not in TRIO_ROLES or backend not in ("CPU","GPU") or not isinstance(scene,str) or not isinstance(digest,str) or not _HEX64.match(digest) or control not in allowed: errors.append(f"row c record {i} has invalid identity/control"); continue
        leg_key = (role, backend, control)
        if leg_key in leg_keys: errors.append(f"row c record {i} duplicates a frozen leg")
        leg_keys.add(leg_key)
        if scene != frozen.get("scene_id") or digest != frozen.get("scene_sha256"):
            errors.append(f"row c record {i} identity differs from its frozen role")
        if r.get("kind")!="f12_run" or r.get("exit_code")!=0 or r.get("sentinel")!="PKG119B_LEG" or r.get("build_id")!=build_id: errors.append(f"row c record {i} lacks successful F12 sentinel/build")
        _image_path,image_why=_artifact(r.get("image"),base,f"row c record {i} image"); errors.extend(image_why)
        report_path,report_why=_artifact(r.get("report_artifact"),base,f"row c record {i} report"); errors.extend(report_why)
        linear,why=_artifact(r.get("linear_npy"),base,f"row c record {i} linear render"); errors.extend(why)
        try:
            arr=np.load(linear)[...,:3] if linear else None
            if arr is None or arr.ndim!=3 or not np.isfinite(arr).all() or float(np.abs(arr).max())<=1e-9: raise ValueError()
            images[(role,backend,control)]=arr
        except (OSError,ValueError): errors.append(f"row c record {i} linear render cannot be loaded")
        try:
            report=json.loads(report_path.read_text(encoding="utf-8")) if report_path else None
            if not isinstance(report, Mapping): raise TypeError()
            reports[leg_key] = report
        except (OSError,TypeError,ValueError,json.JSONDecodeError):
            report={}; errors.append(f"row c record {i} report cannot be read")
        expected = {"corpus_scene": scene, "blend_sha256": digest, "freeze_sha256": freeze_sha,
                    "build_id": build_id, "requested_device": backend.lower(),
                    "effective_device": backend.lower(), "engine": "CUSTOM_RAYTRACER",
                    "res_x": frozen.get("settings", {}).get("res_x"),
                    "res_y": frozen.get("settings", {}).get("res_y"),
                    "samples": frozen.get("settings", {}).get("samples"),
                    "resolved_seed": frozen.get("seed"), "animated_seed": False,
                    "module_sha256": freeze.get("module_sha256"), "addon_sha256": freeze.get("addon_sha256")}
        if any(report.get(key) != value for key, value in expected.items()):
            errors.append(f"row c record {i} observed engine/module/addon/build/device/settings/seed differs from freeze")
        if not isinstance(report.get("blender_version"), str) or not report["blender_version"].startswith("5.2"):
            errors.append(f"row c record {i} was not observed in Blender 5.2")
        if not isinstance(report.get("module_path"), str) or not report["module_path"] or not isinstance(report.get("addon_path"), str) or not report["addon_path"] or not isinstance(report.get("telemetry"), list):
            errors.append(f"row c record {i} lacks observed module/addon/device telemetry")
        bindings=report.get("bindings")
        if not isinstance(bindings, Mapping):
            errors.append(f"row c record {i} lacks observed graph bindings")
        else:
            for declared in frozen.get("controls", []):
                kind=declared.get("kind"); observed=bindings.get(kind)
                if not isinstance(observed, Mapping): errors.append(f"row c record {i} lacks observed {kind} binding"); continue
                checks = {"checker_flat": (("object", "object"), ("material", "material"), ("node", "node"), ("object_type", "MESH"), ("node_type", "ShaderNodeTexChecker")),
                          "hair_off": (("object", "object"), ("object_type", "CURVES")),
                          "hdri_off": (("world", "world"), ("node", "node"), ("node_type", "ShaderNodeTexEnvironment"))}.get(kind, ())
                for check in checks:
                    observed_key, expected_key = check
                    expected_value = declared.get(expected_key) if expected_key in declared else expected_key
                    if observed.get(observed_key) != expected_value:
                        errors.append(f"row c record {i} observed {kind} binding differs from freeze")
                        break
                if kind == "hair_off" and (observed.get("curve_count") != frozen.get("expected_curve_count")
                                             or observed.get("curve_point_count") != frozen.get("expected_curve_point_count")):
                    errors.append(f"row c record {i} observed hair census differs from freeze")
        receipt=report.get("mutation_receipt")
        if not isinstance(receipt, Mapping) or receipt.get("kind") != control or receipt.get("ok") is not True:
            errors.append(f"row c record {i} mutation receipt is missing or wrong")
        elif control == "baseline":
            if set(receipt) != {"kind", "ok"}: errors.append(f"row c record {i} baseline receipt is not inert")
        else:
            declared=next((item for item in frozen.get("controls", []) if item.get("kind") == control), {})
            if control == "checker_flat" and (receipt.get("object") != declared.get("object") or receipt.get("material") != declared.get("material") or receipt.get("node") != declared.get("node") or receipt.get("before") == receipt.get("after")):
                errors.append(f"row c record {i} checker mutation receipt is not the declared flat control")
            if control == "hair_off" and (receipt.get("object") != declared.get("object") or receipt.get("type") != "CURVES" or receipt.get("was_hide_render") is not False or receipt.get("after_hide_render") is not True):
                errors.append(f"row c record {i} hair mutation receipt is not the declared hide control")
            if control == "hdri_off" and (receipt.get("world") != declared.get("world") or receipt.get("node") != declared.get("node") or not receipt.get("image") or receipt.get("after_image", "not-none") is not None):
                errors.append(f"row c record {i} HDRI mutation receipt is not the declared world control")
        if control != "baseline":
            mask_path,why=_artifact(r.get("feature_mask"),base,f"row c record {i} feature mask"); errors.extend(why)
            try:
                mask=np.load(mask_path).astype(bool) if mask_path else None
                if mask is None or mask.ndim!=2 or not mask.any(): raise ValueError()
                masks[(role,backend,control)]=mask
            except (OSError,ValueError): errors.append(f"row c record {i} feature mask cannot be loaded")
            mask_receipt=report.get("mask_receipt")
            declared=next((item for item in frozen.get("controls", []) if item.get("kind") == control), {})
            if (not isinstance(mask_receipt, Mapping) or mask_receipt.get("control") != control
                    or mask_receipt.get("kind") != declared.get("mask", {}).get("kind")
                    or mask_receipt.get("path") != str(mask_path.resolve())
                    or mask_receipt.get("sha256") != (r.get("feature_mask") or {}).get("sha256")):
                errors.append(f"row c record {i} mask receipt is not bound to the frozen control artifact")
        else: pairs.add((role,backend)); hashes.setdefault(role,(scene,digest))
        if (r.get("settings",{}).get("gate_c_rois")!=frozen.get("rois") or r.get("settings",{}).get("gate_c_probes")!=frozen.get("non_vacuity")
                or any(r.get("settings", {}).get(key) != frozen.get("settings", {}).get(key) for key in ("res_x", "res_y", "samples"))): errors.append(f"row c record {i} configuration differs from hash-pinned freeze")
    if leg_keys != expected_legs: errors.append("row c records do not cover the exact frozen baseline/control legs")
    if pairs != {(s,b) for s in TRIO_ROLES for b in ("CPU","GPU")}: errors.append("row c records do not cover every required baseline role/backend pair")
    if not isinstance(expected_hashes,list) or set(expected_hashes)!={v[1] for v in hashes.values()} or len(expected_hashes)!=3: errors.append("row c record scene hashes do not equal frozen manifest scene hashes")
    for role in TRIO_ROLES:
        cpu,gpu=images.get((role,"CPU","baseline")),images.get((role,"GPU","baseline"))
        if cpu is None or gpu is None or cpu.shape!=gpu.shape: continue
        frozen=(freeze.get("roles") or {}).get(role,{})
        for name,roi in frozen.get("rois",{}).items():
            y0,y1,x0,x1=int(roi[1]*cpu.shape[0]),int(roi[3]*cpu.shape[0]),int(roi[0]*cpu.shape[1]),int(roi[2]*cpu.shape[1])
            try: ratio,_=compute_channel_mean_ratio(gpu,cpu,(y0,y1,x0,x1)); ssim,_=compute_ssim(gpu[y0:y1,x0:x1],cpu[y0:y1,x0:x1]); ratios.append(ratio*100); ssims.append(ssim)
            except ValueError: errors.append(f"row c {role} ROI {name} is too small for SSIM")
    mapping={"checker":"checker_flat","hair":"hair_off","hdri":"hdri_off"}
    for role in TRIO_ROLES:
        frozen=(freeze.get("roles") or {}).get(role,{})
        for backend in ("CPU","GPU"):
            baseline=images.get((role,backend,"baseline")); base_record=next((r for r in records if isinstance(r,Mapping) and r.get("role")==role and r.get("backend")==backend and r.get("control")=="baseline"),{})
            for probe in frozen.get("non_vacuity",[]):
                kind=probe.get("kind"); ck=mapping.get(kind)
                if ck is None: continue
                control,mask=images.get((role,backend,ck)),masks.get((role,backend,ck)); reported=next((x for x in base_record.get("non_vacuity",[]) if isinstance(x,Mapping) and x.get("kind")==kind),None)
                if baseline is None or control is None or mask is None or control.shape!=baseline.shape or mask.shape!=baseline.shape[:2] or not isinstance(reported,Mapping): errors.append(f"row c record {role}/{backend} lacks concrete {kind} paired probe"); continue
                if np.array_equal(baseline, control): errors.append(f"row c record {role}/{backend} {kind} control has no linear-image effect")
                floor=float(probe.get("min_delta",0)); coverage=float(probe.get("min_coverage",0)); delta=np.abs(baseline-control).mean(axis=-1)[mask]; value=float(delta.mean()); observed=float((delta>floor).mean())
                if (_number(reported.get("value")) is None or _number(reported.get("coverage")) is None or abs(float(reported["value"])-value)>1e-6 or abs(float(reported["coverage"])-observed)>1e-6 or value<=floor or observed<=coverage): errors.append(f"row c record {role}/{backend} {kind} non-vacuity is not derived from paired frozen-mask evidence")
    if not ratios or not ssims: errors.append("row c has no recomputable frozen ROI metrics")
    return errors,{"roi_pct_max":max(ratios) if ratios else None,"ssim_min":min(ssims) if ssims else None},{"cpu_exit_zero":all((s,"CPU") in pairs for s in TRIO_ROLES),"gpu_exit_zero":all((s,"GPU") in pairs for s in TRIO_ROLES),"pinned_images":not any("artifact" in e for e in errors),"non_vacuity":not any("non-vacuity" in e for e in errors)}

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


def _records_validate(payload: Mapping[str, Any], rid: str, base: Path) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list) or not records: return ["instrument payload requires non-empty typed records"], {}, {}
    if rid == "a": return _validate_a(records, base, payload.get("scene_sha256"))
    if rid == "c": return _validate_c(records, base, payload.get("scene_sha256"), payload.get("build_id"), payload.get("freeze"))
    if rid == "d": return _validate_d(records, base)
    if rid == "e": return _validate_e(records, base)
    if rid == "f": return _validate_f(records, base)
    return [f"row {rid} producer adapter is not yet available"], {}, {}


def _check_common(row: Mapping[str, Any], spec: Mapping[str, Any],
                  repo_root: Path) -> list[str]:
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
            elif not _bound(_number(value[key]), rule):
                reasons.append(f"value {key}={value[key]} outside frozen bound {rule}")
    payload, payload_base, payload_errors = _typed_payload(row, str(row.get("row")), spec, repo_root)
    reasons.extend(payload_errors)
    if payload is not None and payload_base is not None:
        record_errors, derived_value, derived_subchecks = _records_validate(payload, str(row.get("row")), payload_base)
        reasons.extend(record_errors)
        if derived_value and row.get("value") != derived_value:
            reasons.append("manifest value is not the value derived from concrete records")
        if derived_subchecks and row.get("subchecks") != derived_subchecks:
            reasons.append("manifest subchecks are not derived from concrete records")
    return reasons


def _check_scanner_823(row: Mapping[str, Any], repo_root: Path) -> tuple[bool, str]:
    entry = row.get("scanner_issue_823")
    if not isinstance(entry, Mapping) or entry.get("integrated") is not True:
        return False, "scanner issue #823 not integrated"
    path = entry.get("evidence_path")
    recorded = str(entry.get("evidence_sha256") or "").lower()
    if not path or not _HEX64.match(recorded):
        return False, "#823 evidence not hash-pinned"
    p = _resolve(repo_root, str(path))
    if not p.is_file() or sha256_file(p) != recorded:
        return False, "#823 evidence hash mismatch"
    return True, ""


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
    """Assemble the manifest so it ALWAYS has rows a-f. Returns (manifest, reasons)."""
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
        if row.get("instrument") not in {"viewport_latency", "coverage_report", "trio_parity", "native_panel_smoke", "issue_triage", "clean_install"}:
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
        if status == "green":
            reasons = _check_common(row, ROW_SPEC[rid], repo_root)
            if ROW_SPEC[rid].get("requires_scanner_823"):
                ok, why = _check_scanner_823(row, repo_root)
                if not ok:
                    reasons.append(f"scanner #823: {why}")
            if reasons:
                errors.append(f"row {rid}: green fails recomputation: {reasons[:3]}")
    return errors


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def load_instruments(instruments_dir: Path | None,
                     overrides: Mapping[str, Path] | None) -> dict[str, Any]:
    def adapt(path: Path) -> Any:
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Producer payloads are not manifest rows.  Wrap their own immutable
        # file as evidence and derive gate-e values/subchecks from its raw
        # artifacts; do not invent dimensions or accept producer pass flags.
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
