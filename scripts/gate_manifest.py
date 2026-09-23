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
import json
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

PAYLOAD_SCHEMA = "pkg278.instrument.v1"


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


def _typed_payload(row: Mapping[str, Any], rid: str, spec: Mapping[str, Any],
                   repo_root: Path) -> tuple[Mapping[str, Any] | None, list[str]]:
    """Read the hash-pinned instrument result; hashes alone do not prove meaning."""
    ok, why = _evidence_valid(row, repo_root)
    if not ok:
        return None, [f"evidence invalid: {why}"]
    path = _resolve(repo_root, str(row["evidence_path"]))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"instrument payload is not JSON: {exc}"]
    if not isinstance(payload, Mapping):
        return None, ["instrument payload must be an object"]
    errors: list[str] = []
    if payload.get("schema") != PAYLOAD_SCHEMA:
        errors.append(f"instrument payload schema must be {PAYLOAD_SCHEMA!r}")
    if payload.get("row") != rid:
        errors.append("instrument payload row mismatch")
    if payload.get("instrument") != spec["instrument"]:
        errors.append("instrument payload instrument mismatch")
    records = payload.get("records")
    if not isinstance(records, list) or not records or not all(isinstance(x, Mapping) for x in records):
        errors.append("instrument payload requires non-empty typed records")
    for name in ("build_id", "scene_sha256", "backend", "settings", "metric", "value", "threshold"):
        if payload.get(name) != row.get(name):
            errors.append(f"manifest {name} disagrees with instrument payload")
    return (payload if not errors else None), errors


def _records_validate(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    records = payload.get("records", [])
    errors: list[str] = []
    dimensions = set()
    backends = set()
    subchecks = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        backend = record.get("backend")
        if isinstance(backend, str):
            backends.add(backend)
        dims = record.get("dimensions", {})
        if isinstance(dims, Mapping):
            for name, value in dims.items():
                # True/false flags are declarations, never observations.
                if value not in (None, "") and not isinstance(value, bool):
                    dimensions.add(name)
        if record.get("kind") == "subcheck" and record.get("result") == "pass":
            name = record.get("name")
            artifact = record.get("artifact")
            if isinstance(name, str) and isinstance(artifact, Mapping) and artifact.get("sha256"):
                subchecks.add(name)
    for dim in spec.get("required_dimensions", ()):
        if dim not in dimensions:
            errors.append(f"typed records omit required dimension: {dim}")
    for backend in spec.get("required_backends", ()):
        if backend not in backends:
            errors.append(f"typed records omit required backend: {backend}")
    for name in spec.get("required_subchecks", ()):
        if name not in subchecks:
            errors.append(f"typed records omit passing hash-linked subcheck: {name}")
    return errors


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
        if not dims.get(dim):
            reasons.append(f"required dimension absent: {dim}")
    # Frozen thresholds: the row may not loosen (or drop) a bound.
    supplied = row.get("threshold") or {}
    for key, rule in spec.get("threshold", {}).items():
        if key not in supplied:
            reasons.append(f"threshold missing frozen bound: {key}")
            continue
        if "max" in rule and float(supplied[key]) > float(rule["max"]):
            reasons.append(f"threshold {key} loosened: {supplied[key]} > {rule['max']}")
        if "min" in rule and float(supplied[key]) < float(rule["min"]):
            reasons.append(f"threshold {key} loosened: {supplied[key]} < {rule['min']}")
    # Value must be inside the frozen bounds.
    value = row.get("value")
    if not isinstance(value, Mapping):
        reasons.append("value must be an object of measured metrics")
    else:
        for key, rule in spec.get("threshold", {}).items():
            if key not in value or value[key] is None:
                reasons.append(f"value missing measured metric: {key}")
            elif not _bound(float(value[key]), rule):
                reasons.append(f"value {key}={value[key]} outside frozen bound {rule}")
    payload, payload_errors = _typed_payload(row, str(row.get("row")), spec, repo_root)
    reasons.extend(payload_errors)
    if payload is not None:
        reasons.extend(_records_validate(payload, spec))
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
        if row.get("status") == "green":
            if not row.get("evidence_path"):
                errors.append(f"row {rid}: green without evidence_path")
            if not _HEX64.match(str(row.get("evidence_sha256") or "").lower()):
                errors.append(f"row {rid}: green without valid evidence_sha256")
            if row.get("value") is None:
                errors.append(f"row {rid}: green without value")
            if not str(row.get("build_id") or "").strip():
                errors.append(f"row {rid}: green without build_id")
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
    out: dict[str, Any] = {r: None for r in ROWS}
    if instruments_dir is not None:
        for rid in ROWS:
            candidate = Path(instruments_dir) / rid / "instrument.json"
            if candidate.is_file():
                out[rid] = json.loads(candidate.read_text(encoding="utf-8"))
    for rid, path in (overrides or {}).items():
        if rid in out and Path(path).is_file():
            out[rid] = json.loads(Path(path).read_text(encoding="utf-8"))
    return out


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
    args = p.parse_args(argv)

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
