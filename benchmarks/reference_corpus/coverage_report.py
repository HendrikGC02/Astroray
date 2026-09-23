"""pkg278 gate (b) - weighted socket-coverage scorer (pkg259 Phase 4 gap).

This is the omission-resistant scorer the north-star exit gate (b) requires.
It joins the frozen reference corpus to ``docs/blender_parity/coverage_matrix.json``
and scores exercised *socket uses* per backend:

    S_b = sum_i min(n_i, 3) * s_{i,b} / sum_i min(n_i, 3)

where ``i`` is a canonical socket identity (``bl_idname`` + socket identifier),
``n_i`` the number of distinct corpus scenes exercising it, and
``s_{i,b} in {1 SUPPORTED, 0.5 bounded approximation, 0}``.

Omission-resistant rules (frozen here, never caller-supplied):

* exercised uses come from a COMPUTED reachability trace backward from the
  active Material/World/Light Output inputs across links and group
  output/input routing -- never from builder ``feature_tags`` labels and never
  from a caller-supplied ``reachable`` flag;
* a nonzero classification must link a per-backend, per-variant evidence
  artifact whose recorded SHA-256 matches, bound to scene/socket/variant/
  backend/build by a structured sidecar; an unproven claim defaults to 0;
* inline (``content``) evidence exists only behind an explicit test-fixture
  mode -- production scoring requires a file plus a structured sidecar;
* a bounded approximation (0.5) additionally needs a functioning behaviour and
  a user-visible attributable warning; "ignored but warned" scores 0;
* CPU and GPU are scored separately and EACH must clear 95 %; they are never
  averaged;
* zero silent drops is reported as its own Boolean (b4), not folded into the
  score;
* the nine-scene population is PROVISIONAL until the owner ratifies it; the
  unfrozen original "~50 scenes" population is UNDEFINED, not computed;
* gate (b) is NOT scored until scanner issue #823 has landed. Until then the
  report is ``unmeasured``/blocked, never green.

The scorer is validated on a synthetic 3-scene fixture against a hand-computed
weighted score (``python -m benchmarks.reference_corpus.coverage_report --self-test``).

Pipeline (three explicit steps; never a caller-supplied score or scene count):

1. Collect inside Blender (writes the computed-reachability snapshot):

       blender --background --factory-startup \
           --python benchmarks/reference_corpus/coverage_report.py -- \
           --collect --manifest benchmarks/reference_corpus/scenes/manifest.json \
           --out docs/blender_parity/evidence/gate_b/node_uses.json

2. Freeze the versioned input manifest (binds corpus scene IDs/paths/SHA-256,
   matrix hash and the collector snapshot hash; verifies the collected scene
   set equals the committed corpus exactly):

       python -m benchmarks.reference_corpus.coverage_report \
           --freeze --manifest benchmarks/reference_corpus/scenes/manifest.json \
           --matrix docs/blender_parity/coverage_matrix.json \
           --node-uses docs/blender_parity/evidence/gate_b/node_uses.json \
           --out docs/blender_parity/coverage_input_v2.json

3. Score (re-verifies the frozen input against disk + the collected snapshot
   before calculating; no score is published before #823 lands):

       python -m benchmarks.reference_corpus.coverage_report \
           --score --input-manifest docs/blender_parity/coverage_input_v2.json \
           --matrix docs/blender_parity/coverage_matrix.json \
           --node-uses docs/blender_parity/evidence/gate_b/node_uses.json \
           --out docs/blender_parity/evidence/gate_b
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import subprocess
import sys
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Frozen scoring constants (pkg278; owner-ratified 2026-09-07 / 2026-09-08).
# The gate is these numbers. A caller may NOT supply a status or a threshold.
# --------------------------------------------------------------------------- #
WEIGHT_CAP = 3              # distinct corpus scenes per socket, capped at 3
SCORE_SUPPORTED = 1.0
SCORE_APPROXIMATION = 0.5
SCORE_UNPROVEN = 0.0
SCORE_MIN = 0.95            # EACH backend must pass 95 % separately
REQUIRED_SCANNER_ISSUE = 823
NINE_SCENE_COUNT = 9
ORIGINAL_POPULATION_LABEL = "~50 scenes"

INPUT_MANIFEST_SCHEMA = "pkg278.coverage_input_manifest.v2"
INPUT_MANIFEST_SCHEMA_V3 = "pkg278.coverage_input_manifest.v3"
INPUT_MANIFEST_SCHEMA_V4 = "pkg278.coverage_input_manifest.v4"
NODE_USES_SCHEMA = "pkg278.node_uses.v1"
EVIDENCE_SCHEMA = "pkg278.gate_b.evidence.v2"
VERDICT_SCHEMA = "pkg278.gate_b.verdict.v1"
RUNNER_RESULT_SCHEMA = "pkg278.gate_b.runner_result.v1"
RESULT_KINDS = ("render", "test_result")

# A nonzero Gate-B claim needs an explicit per-identity/scene/variant pixel
# witness. This registry intentionally contains one reviewed checker case;
# every other collected variant remains unproven until separately registered.
CASE_WITNESS_REGISTRY: dict[tuple[str, str, str], dict[str, Any]] = {
    ("ShaderNodeTexChecker|input:Color1", "textures_mapping",
     "35ff18873b07e2120a2556a973fe831021dd6c1e1714c8fce90208e5d37f83c2"): {
        "roi": [0.2912, 0.3603, 0.4079, 0.4804],
        "control": {"kind": "checker_flat", "material": "TexCheckerMat",
                    "node": "GateCWorkshopChecker", "object": "TexChecker",
                    "mask": {"kind": "object_polygon", "inset": 0.16}},
        "effect": {"min_delta": 0.05, "min_coverage": 0.02,
                   "min_signal": 0.001},
    },
}

# b5: the four shader families the north star names explicitly. Each exercised
# use of these nodes must be SUPPORTED or APPROXIMATED-with-warning on BOTH
# backends. A node with no exercised use is not evidence of anything, so it
# cannot make the subcheck pass.
NAMED_NODE_CHECKS: dict[str, str] = {
    "principled_advanced": "ShaderNodeBsdfPrincipled",
    "metallic_bsdf": "ShaderNodeBsdfMetallic",
    "sky_texture": "ShaderNodeTexSky",
    "displacement": "ShaderNodeDisplacement",
}

SUPPORTED = "SUPPORTED"
APPROXIMATED = "APPROXIMATED"
DROPPED_SILENT = "DROPPED-SILENT"

# Worst-case precedence when one identity appears in several matrix rows.
_CLASS_RANK = {SUPPORTED: 2, APPROXIMATED: 1, DROPPED_SILENT: 0}

# Shader-node properties the matrix keys as ``prop:<name>``. Only these, and
# only when set to a non-default value on a reachable node, become exercised
# uses -- a node that merely *has* a property at its default is not exercising
# a variant of it. (Enum values compare by identifier.)
KNOWN_NODE_PROPERTIES: frozenset[str] = frozenset({
    "active_index", "aerosol_density", "air_density", "altitude", "attribute_type",
    "axis", "bands_direction", "base", "blend_type", "clamp", "clamp_factor",
    "clamp_result", "clamp_type", "component", "convention", "convert_from",
    "convert_to", "data_type", "direction_type", "distance", "distribution",
    "extension", "factor_mode", "falloff", "feature", "fresnel_type",
    "from_instancer", "gabor_type", "gradient_type", "ground_albedo", "inside",
    "interpolation", "interpolation_type", "invert", "is_active_output", "mode",
    "model", "noise_dimensions", "noise_type", "normalize", "offset",
    "offset_frequency", "only_local", "operation", "ozone_density",
    "parametrization", "phase", "projection", "projection_blend", "rings_direction",
    "rotation_type", "samples", "sky_type", "space", "squash", "squash_frequency",
    "subsurface_method", "sun_direction", "sun_disc", "sun_elevation",
    "sun_intensity", "sun_rotation", "sun_size", "target", "turbidity",
    "turbulence_depth", "use_alpha", "use_auto_update", "use_clamp",
    "use_pixel_size", "use_tips", "vector_type", "voronoi_dimensions",
    "wave_profile", "wave_type",
})

# Active inputs that carry the scene's result for each output-node family.
_OUTPUT_ACTIVE_SOCKETS: dict[str, tuple[str, ...]] = {
    "ShaderNodeOutputMaterial": ("Surface", "Volume", "Displacement"),
    "ShaderNodeOutputWorld": ("Surface", "Volume"),
    "ShaderNodeOutputLight": ("Surface",),
}


# --------------------------------------------------------------------------- #
# Identity + evidence helpers (pure)
# --------------------------------------------------------------------------- #

def canonical_identity(bl_idname: str, socket_or_prop: str) -> str:
    """The frozen canonical socket identity: ``bl_idname`` + socket identifier."""
    return f"{bl_idname}|{socket_or_prop}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def sha256_file(path: Path) -> str:
    """Public hash helper (stable alias used by tests and the freeze step)."""
    return _sha256_file(Path(path))


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":")).encode("utf-8")


def variant_digest(fingerprint: Mapping[str, Any]) -> str:
    """Stable identity for one collected socket configuration."""
    return _sha256_bytes(_canonical_json(dict(fingerprint)))


def materialize_use_ledger(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Freeze every exact scene/socket/variant use and its capped weight.

    The ledger is deliberately derived at freeze time, rather than reconstructed
    by whatever collector/scorer code happens to be installed at score time.
    """
    by_key: dict[str, set[tuple[str, str]]] = {}
    for scene_id, nodes in _snapshot_node_trees(snapshot).items():
        for node in nodes:
            name = node.get("bl_idname")
            if not name:
                continue
            sockets = node.get("sockets") or exercised_sockets_for(node)[0]
            digest = variant_digest(node.get("fingerprint") or exercised_sockets_for(node)[1])
            for socket in sockets:
                if socket:
                    by_key.setdefault(canonical_identity(name, str(socket)), set()).add((str(scene_id), digest))
    ledger = []
    for identity in sorted(by_key):
        variants = [{"scene_id": scene, "variant_digest": digest}
                    for scene, digest in sorted(by_key[identity])]
        ledger.append({"identity": identity, "variants": variants,
                       "scene_ids": sorted({v["scene_id"] for v in variants}),
                       "weight": min(len({v["scene_id"] for v in variants}), WEIGHT_CAP),
                       "exclusions": []})
    return ledger


def _ledger_uses(ledger: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    return {str(row["identity"]): set(row.get("scene_ids") or []) for row in ledger
            if isinstance(row.get("identity"), str)}


def _canonical_runner_result(payload: Mapping[str, Any], case_id: str) -> Mapping[str, Any] | None:
    """Select one runner-produced result from a direct result or its envelope."""
    if payload.get("schema") != RUNNER_RESULT_SCHEMA:
        return None
    if isinstance(payload.get("results"), list):
        matches = [row for row in payload["results"]
                   if isinstance(row, Mapping) and row.get("case_id") == case_id]
        return matches[0] if len(matches) == 1 else None
    return payload


def _runner_artifact(ref: Any, repo_root: Path | None) -> Path | None:
    """Resolve and hash-check one runner-retained artifact reference."""
    if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
        return None
    path = Path(ref["path"])
    if not path.is_absolute() and repo_root is not None:
        path = Path(repo_root) / path
    if not path.is_file() or ref.get("sha256") != _sha256_file(path):
        return None
    return path


def _witness_roi(shape: tuple[int, ...], witness: Mapping[str, Any]) -> tuple[slice, slice] | None:
    roi = witness.get("roi")
    if (not isinstance(roi, list) or len(roi) != 4
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   for value in roi)):
        return None
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    height, width = shape[:2]
    left, right = int(x0 * width), int(x1 * width)
    top, bottom = int(y0 * height), int(y1 * height)
    if left >= right or top >= bottom:
        return None
    return slice(top, bottom), slice(left, right)


def witness_metrics(actual, reference, actual_control, reference_control,
                    actual_mask, reference_mask, witness: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Compute local parity and counterfactual effect from frozen case data."""
    import numpy as np

    from benchmarks.blender_parity.harness import _gate_c_paired_probe
    from benchmarks.reference_bank.metrics import compute_delta_e_2000, compute_ssim

    arrays = (actual, reference, actual_control, reference_control)
    if any(getattr(array, "shape", None) != actual.shape or array.ndim != 3 or array.shape[-1] != 3
           for array in arrays) or not all(np.isfinite(array).all() for array in arrays):
        return None, "witness arrays have incompatible shape or non-finite pixels"
    roi = _witness_roi(actual.shape, witness)
    effect = witness.get("effect")
    if roi is None or not isinstance(effect, Mapping):
        return None, "case witness has invalid ROI or effect threshold"
    if any(not isinstance(effect.get(key), (int, float)) for key in ("min_delta", "min_coverage", "min_signal")):
        return None, "case witness has invalid effect thresholds"
    results: dict[str, Any] = {}
    for name, baseline, control, mask in (("astroray", actual, actual_control, actual_mask),
                                          ("cycles", reference, reference_control, reference_mask)):
        if getattr(mask, "shape", None) != actual.shape[:2]:
            return None, f"{name} witness mask has wrong shape"
        selected = np.asarray(mask[roi], dtype=bool)
        base = baseline[roi]
        changed = control[roi]
        if not selected.any():
            return None, f"{name} witness mask is empty in frozen ROI"
        signal = float(base[selected].mean())
        paired = _gate_c_paired_probe(base, changed, selected,
                                      {"kind": "checker", "min_delta": effect["min_delta"],
                                       "min_coverage": effect["min_coverage"]})
        results[name] = {"signal": signal, **paired,
                         "ok": signal > float(effect["min_signal"]) and paired["ok"]}
    patch_actual, patch_reference = actual[roi], reference[roi]
    ssim, _ = compute_ssim(patch_actual, patch_reference)
    delta_e, _ = compute_delta_e_2000(patch_actual, patch_reference)
    return {"ssim": float(ssim), "delta_e": float(delta_e), "effects": results,
            "roi": list(witness["roi"]), "pass": all(result["ok"] for result in results.values())}, ""


def _runner_metrics_match(produced: Mapping[str, Any], repo_root: Path | None) -> tuple[bool, str]:
    """Recompute the frozen metric predicate from the retained linear arrays."""
    artifacts = produced.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return False, "canonical runner result lacks corpus render artifacts"
    astro = _runner_artifact(artifacts.get("astroray_linear_npy"), repo_root)
    cycles = _runner_artifact(artifacts.get("cycles_linear_npy"), repo_root)
    raw = _runner_artifact(artifacts.get("report"), repo_root)
    cycles_raw = _runner_artifact(artifacts.get("cycles_report"), repo_root)
    astro_control_raw = _runner_artifact(artifacts.get("astroray_control_report"), repo_root)
    cycles_control_raw = _runner_artifact(artifacts.get("cycles_control_report"), repo_root)
    astro_control = _runner_artifact(artifacts.get("astroray_control_linear_npy"), repo_root)
    cycles_control = _runner_artifact(artifacts.get("cycles_control_linear_npy"), repo_root)
    astro_mask = _runner_artifact(artifacts.get("astroray_feature_mask"), repo_root)
    cycles_mask = _runner_artifact(artifacts.get("cycles_feature_mask"), repo_root)
    astro_control_mask = _runner_artifact(artifacts.get("astroray_control_feature_mask"), repo_root)
    cycles_control_mask = _runner_artifact(artifacts.get("cycles_control_feature_mask"), repo_root)
    if not all((astro, cycles, raw, cycles_raw, astro_control_raw, cycles_control_raw, astro_control, cycles_control, astro_mask, cycles_mask, astro_control_mask, cycles_control_mask)):
        return False, "canonical runner artifact is missing or hash-mismatched"
    # Each baseline/control pair is rendered from the same frozen feature region,
    # so the retained control mask must describe that one region -- a mask
    # swapped for an unrelated (or differently shaped) artifact is rejected even
    # when its own recorded hash matches.
    for engine, baseline_mask, control_mask in (("astroray", astro_mask, astro_control_mask),
                                                ("cycles", cycles_mask, cycles_control_mask)):
        if _sha256_file(baseline_mask) != _sha256_file(control_mask):
            return False, (f"canonical runner {engine} baseline/control feature masks "
                           "do not describe the same frozen region")
    try:
        import numpy as np
        witness = produced.get("witness")
        if not isinstance(witness, Mapping):
            return False, "canonical runner result lacks a registered case witness"
        witness_result, witness_reason = witness_metrics(
            np.load(astro), np.load(cycles), np.load(astro_control), np.load(cycles_control),
            np.load(astro_mask), np.load(cycles_mask), witness)
        if witness_result is None:
            return False, witness_reason
        raw_observed = json.loads(raw.read_text(encoding="utf-8"))
        cycles_observed = json.loads(cycles_raw.read_text(encoding="utf-8"))
        astro_control_observed = json.loads(astro_control_raw.read_text(encoding="utf-8"))
        cycles_control_observed = json.loads(cycles_control_raw.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, ImportError):
        return False, "canonical runner artifacts cannot be decoded"
    metrics = produced.get("metrics")
    if not isinstance(metrics, Mapping) or not all(isinstance(metrics.get(k), (int, float)) for k in ("ssim", "delta_e")):
        return False, "canonical runner result lacks re-derivable metrics"
    if (not math.isclose(float(metrics["ssim"]), witness_result["ssim"], rel_tol=1e-7, abs_tol=1e-7)
            or not math.isclose(float(metrics["delta_e"]), witness_result["delta_e"], rel_tol=1e-7, abs_tol=1e-7)):
        return False, "canonical runner metrics do not match retained linear arrays"
    if produced.get("effect") != witness_result or not witness_result["pass"]:
        return False, "canonical runner witness effect is missing or does not pass"
    expected = {key: produced.get(key) for key in ("case_id", "identity", "scene_id", "variant_digest", "backend", "build_id")}
    for report in (raw_observed, cycles_observed, astro_control_observed, cycles_control_observed):
        if not isinstance(report, Mapping) or report.get("schema") != "pkg278.gate_b.case_observation.v2":
            return False, "canonical runner raw observation has wrong schema"
        if report.get("case") != expected:
            return False, "canonical runner raw observation does not bind its case"
        graph = report.get("graph")
        if not isinstance(graph, Mapping) or graph.get("identity") != produced.get("identity") or graph.get("variant_digest") != produced.get("variant_digest"):
            return False, "canonical runner raw observation does not confirm identity/variant"
    reports = (raw_observed, cycles_observed, astro_control_observed, cycles_control_observed)
    if any(report.get("witness") != produced.get("witness") or report.get("settings") != produced.get("settings")
           for report in reports):
        return False, "canonical runner raw observations lack frozen witness/settings"
    receipts = tuple(report.get("mutation_receipt") for report in reports)
    control_kind = produced["witness"].get("control", {}).get("kind") if isinstance(produced.get("witness"), Mapping) else None
    if (any(not isinstance(receipt, Mapping) or receipt.get("ok") is not True for receipt in receipts)
            or any(receipt.get("kind") != "baseline" for receipt in receipts[:2])
            or any(receipt.get("kind") != control_kind for receipt in receipts[2:])):
        return False, "canonical runner raw observations lack the declared baseline/control receipts"
    if (raw_observed.get("engine") != "CUSTOM_RAYTRACER" or cycles_observed.get("engine") != "CYCLES"
            or astro_control_observed.get("engine") != "CUSTOM_RAYTRACER"
            or cycles_control_observed.get("engine") != "CYCLES"):
        return False, "canonical runner raw observations have the wrong engines"
    for report, linear, mask in ((raw_observed, astro, astro_mask), (cycles_observed, cycles, cycles_mask),
                                 (astro_control_observed, astro_control, astro_control_mask),
                                 (cycles_control_observed, cycles_control, cycles_control_mask)):
        if (not isinstance(report.get("linear_npy"), str) or not isinstance(report.get("feature_mask_npy"), str)
                or Path(report["linear_npy"]).resolve() != linear.resolve()
                or Path(report["feature_mask_npy"]).resolve() != mask.resolve()):
            return False, "canonical runner raw observation does not bind retained linear/mask artifacts"
    if raw_observed.get("observed") != produced.get("observed"):
        return False, "canonical runner result does not match the observed native render leg"
    blend_sha = raw_observed.get("blend_sha256")
    if (not isinstance(blend_sha, str) or len(blend_sha) != 64
            or cycles_observed.get("blend_sha256") != blend_sha):
        return False, "canonical runner paired legs do not bind the same corpus blend"
    return True, ""


def evidence_is_valid(rec: Mapping[str, Any], repo_root: Path | None = None,
                      *, fixture_mode: bool = False,
                      allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[bool, str]:
    """A linked evidence artifact is valid iff its recorded SHA-256 matches.

    Production (``fixture_mode=False``) requires a structured sidecar: a real
    file ``artifact.path`` (hash-verified on disk) plus bindings for scene,
    variant, backend, build id and result kind. An inline ``content`` string is
    NOT production evidence -- it is accepted only in explicit fixture mode.
    """
    recorded = str(rec.get("sha256") or "").lower()
    artifact = rec.get("artifact")
    if isinstance(artifact, Mapping):
        recorded = str(artifact.get("sha256") or "").lower()
    if len(recorded) != 64:
        return False, "missing or malformed sha256"

    if not fixture_mode:
        if not isinstance(artifact, Mapping):
            return False, "production evidence requires a file artifact (inline content is not evidence)"
        missing = [field for field in ("identity", "scene_id", "variant", "variant_digest", "backend", "build_id")
                   if not str(rec.get(field) or "").strip()]
        if missing:
            return False, f"production evidence sidecar missing bindings: {missing}"
        if rec.get("result_kind") not in RESULT_KINDS:
            return False, "production evidence sidecar has invalid result_kind"
        verdict = rec.get("verdict")
        if not isinstance(verdict, Mapping):
            return False, "production evidence requires a machine-readable semantic verdict"
        if verdict.get("schema") != VERDICT_SCHEMA or verdict.get("pass") is not True:
            return False, "production verdict has wrong schema or is not a passing verdict"
        for field in ("identity", "scene_id", "variant_digest", "backend", "build_id"):
            if verdict.get(field) != rec.get(field):
                return False, f"production verdict does not bind {field}"
        result = verdict.get("result")
        if not isinstance(result, Mapping) or result.get("kind") not in RESULT_KINDS:
            return False, "production verdict has no genuine render/test result"
        verifier = rec.get("verifier_result")
        if not isinstance(verifier, Mapping) or not isinstance(verifier.get("path"), str):
            return False, "production evidence requires a canonical runner result"
        vp = Path(verifier["path"])
        if not vp.is_absolute() and repo_root is not None:
            vp = Path(repo_root) / vp
        if not vp.is_file() or verifier.get("sha256") != _sha256_file(vp):
            return False, "canonical runner result is missing or hash-mismatched"
        try:
            produced = json.loads(vp.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False, "canonical runner result is not JSON"
        produced = _canonical_runner_result(produced, str(rec.get("case_id") or ""))
        if produced is None or produced.get("status") != "pass":
            return False, "canonical runner result is not a passing typed result"
        for field in ("case_id", "identity", "scene_id", "variant_digest", "backend", "build_id"):
            if produced.get(field) != rec.get(field):
                return False, f"canonical runner result does not bind {field}"
        observed = produced.get("observed")
        if not isinstance(observed, Mapping):
            return False, "canonical runner result lacks observed engine identity"
        case = (allowed_cases or {}).get(str(rec.get("case_id") or ""))
        if not isinstance(case, Mapping):
            return False, "canonical runner case is not in the frozen v3 case map"
        for field in ("identity", "scene_id", "variant_digest", "backend", "build_id",
                      "module_sha256", "addon_sha256"):
            actual = observed.get(field) if field in ("module_sha256", "addon_sha256") else produced.get(field)
            expected = case.get(field)
            if not isinstance(expected, str) or not expected or actual != expected:
                return False, f"canonical runner result does not match frozen case {field}"
        if produced.get("witness") != case.get("witness") or produced.get("settings") != case.get("settings"):
            return False, "canonical runner result does not match frozen witness/settings"
        if result.get("artifact_sha256") != verifier.get("sha256"):
            return False, "production verdict is not tied to the generated runner artifact"
        if "feature" in produced:
            return False, "generic FeatureResult cannot prove a corpus case"
        metrics_ok, metrics_reason = _runner_metrics_match(produced, repo_root)
        if not metrics_ok:
            return False, metrics_reason
        metrics = produced["metrics"]
        if float(metrics["ssim"]) < 0.95 or float(metrics["delta_e"]) > 5.0:
            return False, "canonical runner metrics do not pass the frozen predicate"

    if isinstance(artifact, Mapping):
        path = artifact.get("path")
        if not isinstance(path, str) or not path.strip():
            return False, "artifact path missing"
        p = Path(path)
        if not p.is_absolute() and repo_root is not None:
            p = Path(repo_root) / p
        if not p.is_file():
            return False, f"evidence artifact does not exist: {path}"
        actual = _sha256_file(p)
        if actual != recorded:
            return False, f"evidence artifact hash mismatch: {path}"
        return True, ""

    if fixture_mode:
        content = rec.get("content")
        if content is not None:
            actual = _sha256_bytes(str(content).encode("utf-8"))
            if actual != recorded:
                return False, "inline evidence hash mismatch"
            return True, ""
    return False, "evidence has neither a file artifact nor (fixture-mode) inline content"


def _valid_records(records: Iterable[Mapping[str, Any]], repo_root: Path | None,
                   fixture_mode: bool, allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> list[Mapping[str, Any]]:
    return [r for r in records if evidence_is_valid(r, repo_root, fixture_mode=fixture_mode,
                                                    allowed_cases=allowed_cases)[0]]


# --------------------------------------------------------------------------- #
# Computed reachability (pure; the in-Blender collector feeds this)
# --------------------------------------------------------------------------- #
#
# The graph model is a plain dict so both the Blender adapter and unit tests can
# build it without importing Blender:
#
#     trees = {
#         "<tree id>": {
#             "kind": "material" | "world" | "light" | "group",
#             "nodes": {
#                 "<node name>": {
#                     "bl_idname": str,
#                     "mute": bool,
#                     "is_group": bool,
#                     "group_tree": "<tree id>|None",
#                     "inputs": {socket_id: linked_bool},
#                     "outputs": {socket_id: linked_bool},
#                     "internal_links": [(from_in_id, to_out_id), ...],
#                 },
#             },
#             "links": [{"from_node","from_socket","to_node","to_socket"}, ...],
#         },
#     }
#
# Group nodes (``is_group``) reference ``group_tree``; that tree contains one
# ``NodeGroupInput`` and one ``NodeGroupOutput`` node whose socket identifiers
# match the group node's input/output socket identifiers. A group node whose
# tree or Group Input/Output nodes cannot be resolved is a collection error --
# reachability is never silently reduced by dropping a group.

def trace_reachable(trees: Mapping[str, Mapping[str, Any]]) -> tuple[set[tuple[str, str]], list[str]]:
    """Return ``(reachable, errors)`` where ``reachable`` is the set of
    ``(tree_id, node_name)`` pairs on a path to an active output, and ``errors``
    are collection errors (a non-empty list invalidates the whole collection).
    """
    errors: list[str] = []
    def linked(value: Any) -> bool:
        return bool(value.get("linked")) if isinstance(value, Mapping) else bool(value)
    link_index: dict[tuple[str, str, str], list[tuple[str, str, str]]] = {}
    for tid, tree in trees.items():
        for link in tree.get("links", []):
            key = (tid, link["to_node"], link["to_socket"])
            link_index.setdefault(key, []).append((tid, link["from_node"], link["from_socket"]))

    # Group boundary maps: (outer group output) -> (group tree output input)
    # and (group tree input output) -> (outer group input). Sockets are matched
    # by identifier (Blender keeps the group node's interface identifiers in
    # sync with the Group Input/Output node socket identifiers).
    group_output_map: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    group_input_map: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for tid, tree in trees.items():
        for name, node in tree.get("nodes", {}).items():
            if not node.get("is_group"):
                continue
            gt = node.get("group_tree")
            if not gt or gt not in trees:
                errors.append(f"group node {name!r} in {tid!r} has no resolvable node_tree")
                continue
            gtree = trees[gt]
            go_name = None
            gi_name = None
            for n2_name, n2 in gtree.get("nodes", {}).items():
                if n2["bl_idname"] == "NodeGroupOutput":
                    go_name = n2_name
                elif n2["bl_idname"] == "NodeGroupInput":
                    gi_name = n2_name
            if go_name is None or gi_name is None:
                errors.append(f"group tree {gt!r} lacks Group Input/Output nodes")
                continue
            go_node = gtree["nodes"][go_name]
            gi_node = gtree["nodes"][gi_name]
            for out_socket in node.get("outputs", {}):
                if out_socket not in go_node.get("inputs", {}):
                    errors.append(f"group {name!r} output {out_socket!r} missing in {gt!r} Group Output")
                    continue
                group_output_map[(tid, name, out_socket)] = (gt, go_name, out_socket)
            for in_socket in node.get("inputs", {}):
                if in_socket not in gi_node.get("outputs", {}):
                    errors.append(f"group {name!r} input {in_socket!r} missing in {gt!r} Group Input")
                    continue
                group_input_map[(gt, gi_name, in_socket)] = (tid, name, in_socket)

    reachable: set[tuple[str, str]] = set()
    visited_in: set[tuple[str, str, str]] = set()
    queue: deque[tuple[str, str, str]] = deque()

    def enqueue_input(tid: str, node_name: str, in_socket: str) -> None:
        key = (tid, node_name, in_socket)
        if key in visited_in:
            return
        visited_in.add(key)
        queue.append(key)

    def visit_output(tid: str, node_name: str, out_socket: str) -> None:
        reachable.add((tid, node_name))
        node = trees[tid]["nodes"][node_name]
        if node.get("is_group"):
            key = (tid, node_name, out_socket)
            if key in group_output_map:
                gt, go_name, go_in = group_output_map[key]
                reachable.add((gt, go_name))
                enqueue_input(gt, go_name, go_in)
            return
        if node.get("bl_idname") == "NodeGroupInput":
            # The group interface input feeds this node's output; map it back to
            # the outer group node's input socket to continue tracing outside.
            key = (tid, node_name, out_socket)
            if key in group_input_map:
                outer_tid, outer_node, outer_in = group_input_map[key]
                enqueue_input(outer_tid, outer_node, outer_in)
            return
        if node.get("mute"):
            # A muted node is bypassed: only its internal_links pass the signal
            # through, so trace those instead of its own wired inputs.
            for from_s, to_s in node.get("internal_links", []):
                if to_s == out_socket:
                    enqueue_input(tid, node_name, from_s)
            return
        for in_s in node.get("inputs", {}):
            if linked(node["inputs"][in_s]):
                enqueue_input(tid, node_name, in_s)
        for from_s, to_s in node.get("internal_links", []):
            if to_s == out_socket:
                enqueue_input(tid, node_name, from_s)

    for tid, tree in trees.items():
        if tree.get("kind") not in ("material", "world", "light"):
            continue
        for name, node in tree.get("nodes", {}).items():
            if node["bl_idname"] not in _OUTPUT_ACTIVE_SOCKETS:
                continue
            if node.get("is_active_output") is False:
                continue
            reachable.add((tid, name))
            for active_socket in _OUTPUT_ACTIVE_SOCKETS[node["bl_idname"]]:
                if active_socket in node.get("inputs", {}):
                    enqueue_input(tid, name, active_socket)

    while queue:
        tid, node_name, in_socket = queue.popleft()
        for stid, from_node, from_socket in link_index.get((tid, node_name, in_socket), []):
            visit_output(stid, from_node, from_socket)
        node = trees[tid]["nodes"][node_name]
        for from_s, to_s in node.get("internal_links", []):
            if to_s == in_socket:
                enqueue_input(tid, node_name, from_s)

    return reachable, errors


# --------------------------------------------------------------------------- #
# Exercised-use extraction (pure; the in-Blender collector feeds this)
# --------------------------------------------------------------------------- #

def exercised_sockets_for(node: Mapping[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Enumerate the canonical socket IDs a reachable node exercises, plus a
    fingerprint recording operation/data-type/link/default variants.

    ``node`` is a collector node model with ``bl_idname``, ``inputs`` (socket_id
    -> linked), ``outputs`` (socket_id -> linked), ``prop_variants`` (name ->
    value for non-default known properties), and optional ``op``/``data_type``/
    ``blend_type``.
    """
    sockets: list[str] = []
    fingerprint: dict[str, Any] = {}
    active_inputs = {sid: value for sid, value in node.get("inputs", {}).items()
                     if not isinstance(value, Mapping) or value.get("enabled", True)}
    linked_inputs = sorted(sid for sid, value in active_inputs.items()
                           if (value.get("linked") if isinstance(value, Mapping) else value))
    linked_outputs = sorted(sid for sid, linked in node.get("outputs", {}).items() if linked)
    for sid in sorted(active_inputs):
        sockets.append(f"input:{sid}")
    for sid in linked_outputs:
        sockets.append(f"output:{sid}")
    for name in sorted(node.get("prop_variants", {})):
        sockets.append(f"prop:{name}")
    fingerprint["linked_inputs"] = linked_inputs
    fingerprint["active_inputs"] = {sid: (value if isinstance(value, Mapping) else {"linked": bool(value)})
                                    for sid, value in sorted(active_inputs.items())}
    fingerprint["linked_outputs"] = linked_outputs
    fingerprint["prop_variants"] = dict(sorted(node.get("prop_variants", {}).items()))
    for key in ("op", "data_type", "blend_type"):
        if node.get(key) is not None:
            fingerprint[key] = node[key]
    return sockets, fingerprint


def _snapshot_node_trees(snapshot: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    """Normalise a snapshot's ``scenes`` into ``{scene_id: [node records]}``.

    Accepts either the collector shape (``{scene_id: {"nodes": [...]}}``) or a
    plain ``{scene_id: [records]}`` used by fixtures.
    """
    out: dict[str, list[Mapping[str, Any]]] = {}
    for scene_id, scene in snapshot.get("scenes", {}).items():
        if isinstance(scene, list):
            out[scene_id] = scene
        elif isinstance(scene, Mapping):
            out[scene_id] = scene.get("nodes", []) or []
        else:
            out[scene_id] = []
    return out


def extract_exercised_uses(node_trees: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, set[str]]:
    """Return ``{identity: {scene_id, ...}}`` from the computed-reachable records.

    ``node_trees`` maps ``scene_id`` -> list of reachable node records. Only the
    collector emits records, and it emits ONLY nodes the reachability trace
    reached -- there is no ``reachable`` flag to trust, and a caller-supplied
    flag on a record is ignored (reachability is computed, never claimed).
    """
    uses: dict[str, set[str]] = {}
    for scene_id, nodes in node_trees.items():
        for node in nodes:
            bl_idname = node.get("bl_idname")
            if not bl_idname:
                continue
            sockets = node.get("sockets")
            if sockets is None:
                sockets = exercised_sockets_for(node)[0]
            for socket in sockets:
                if not socket:
                    continue
                key = canonical_identity(bl_idname, str(socket))
                uses.setdefault(key, set()).add(scene_id)
    return uses


def matrix_by_identity(matrix_rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Worst-case classification per canonical identity."""
    out: dict[str, str] = {}
    for row in matrix_rows:
        bl_idname = row.get("bl_idname")
        socket = row.get("socket_or_prop")
        if not bl_idname or not socket:
            continue
        key = canonical_identity(bl_idname, socket)
        cls = str(row.get("classification") or "")
        if key not in out or _CLASS_RANK.get(cls, -1) < _CLASS_RANK.get(out[key], 99):
            out[key] = cls
    return out


def silent_drops(uses: Mapping[str, set[str]], matrix: Mapping[str, str]) -> list[str]:
    """Exercised uses the matrix marks DROPPED-SILENT (b4 denominator)."""
    return sorted(k for k in uses if matrix.get(k) == DROPPED_SILENT)


# --------------------------------------------------------------------------- #
# Per-use scoring
# --------------------------------------------------------------------------- #

class UseScore:
    __slots__ = ("cpu", "cpu_reason", "gpu", "gpu_reason", "key", "scenes", "weight")

    def __init__(self, *, key: str, scenes: list[str], weight: int,
                 cpu: float, gpu: float, cpu_reason: str, gpu_reason: str) -> None:
        self.key = key
        self.scenes = scenes
        self.weight = weight
        self.cpu = cpu
        self.gpu = gpu
        self.cpu_reason = cpu_reason
        self.gpu_reason = gpu_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.key,
            "scenes": self.scenes,
            "weight": self.weight,
            "cpu": self.cpu,
            "gpu": self.gpu,
            "cpu_reason": self.cpu_reason,
            "gpu_reason": self.gpu_reason,
        }


class BackendScore:
    __slots__ = ("backend", "denominator", "numerator", "score", "use_scores")

    def __init__(self, *, backend: str, score: float | None, numerator: float,
                 denominator: float, use_scores: list[UseScore]) -> None:
        self.backend = backend
        self.score = score
        self.numerator = numerator
        self.denominator = denominator
        self.use_scores = use_scores

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "score": self.score,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "use_count": len(self.use_scores),
            "uses": [u.to_dict() for u in self.use_scores],
        }


def _records_for(evidence: Mapping[str, Any], key: str, backend: str) -> list[Mapping[str, Any]]:
    entry = evidence.get(key)
    if not isinstance(entry, Mapping):
        return []
    records = entry.get(backend)
    return list(records) if isinstance(records, list) else []


def score_use(key: str, scenes: set[str], classification: str,
              evidence: Mapping[str, Any], backend: str,
              repo_root: Path | None, fixture_mode: bool,
              variants: set[tuple[str, str]] | None = None,
              allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[float, str]:
    """Score one exercised use on one backend. Never raises; unproven -> 0."""
    if classification == DROPPED_SILENT or not classification:
        return SCORE_UNPROVEN, "dropped-silent or absent from the matrix"
    if classification not in (SUPPORTED, APPROXIMATED):
        return SCORE_UNPROVEN, f"unknown classification {classification!r}"

    records = _valid_records(_records_for(evidence, key, backend), repo_root, fixture_mode, allowed_cases)
    if not records:
        return SCORE_UNPROVEN, "no hash-verified evidence artifact for this backend"

    covered = {str(r.get("variant")) for r in records if r.get("variant")}
    missing = sorted(scenes - covered)
    if missing:
        return SCORE_UNPROVEN, f"evidence does not cover variants: {missing}"

    # In production every record must bind the backend and a scene in this use's set.
    if not fixture_mode:
        for r in records:
            if str(r.get("backend") or "") != backend:
                return SCORE_UNPROVEN, "evidence sidecar backend does not match the scored backend"
            if str(r.get("scene_id") or "") not in scenes:
                return SCORE_UNPROVEN, "evidence sidecar scene_id is not an exercised scene"
            if variants is not None and (str(r.get("scene_id")), str(r.get("variant_digest"))) not in variants:
                return SCORE_UNPROVEN, "evidence sidecar variant digest is not a frozen exercised variant"
        if variants is not None:
            missing_variants = sorted(variants - {(str(r.get("scene_id")), str(r.get("variant_digest"))) for r in records})
            if missing_variants:
                return SCORE_UNPROVEN, "evidence does not cover every frozen socket variant"

    if classification == APPROXIMATED:
        bad = [r for r in records
               if r.get("behavior") != "functioning" or not str(r.get("warning") or "").strip()]
        if bad:
            return SCORE_UNPROVEN, "approximation without a functioning behaviour and warning"
        return SCORE_APPROXIMATION, "functioning bounded approximation with attributable warning"

    return SCORE_SUPPORTED, "supported with per-variant evidence"


def score_backend(backend: str, uses: Mapping[str, set[str]], matrix: Mapping[str, str],
                  evidence: Mapping[str, Any], repo_root: Path | None,
                  fixture_mode: bool, ledger: Iterable[Mapping[str, Any]] | None = None,
                  allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> BackendScore:
    numerator = 0.0
    denominator = 0.0
    use_scores: list[UseScore] = []
    variant_index = {str(row.get("identity")): {(str(v.get("scene_id")), str(v.get("variant_digest")))
                     for v in row.get("variants", []) if isinstance(v, Mapping)}
                     for row in (ledger or []) if isinstance(row, Mapping)}
    weights = {str(row.get("identity")): row.get("weight") for row in (ledger or []) if isinstance(row, Mapping)}
    for key in sorted(uses):
        scenes = uses[key]
        weight = weights.get(key, min(len(scenes), WEIGHT_CAP))
        if not isinstance(weight, int) or weight != min(len(scenes), WEIGHT_CAP):
            weight = min(len(scenes), WEIGHT_CAP)
        classification = matrix.get(key, "")
        variants = variant_index.get(key) if ledger is not None else None
        cpu_score, cpu_reason = score_use(key, scenes, classification, evidence, "CPU", repo_root, fixture_mode, variants, allowed_cases)
        gpu_score, gpu_reason = score_use(key, scenes, classification, evidence, "GPU", repo_root, fixture_mode, variants, allowed_cases)
        s = cpu_score if backend == "CPU" else gpu_score
        numerator += weight * s
        denominator += weight
        use_scores.append(UseScore(
            key=key, scenes=sorted(scenes), weight=weight,
            cpu=cpu_score, gpu=gpu_score, cpu_reason=cpu_reason, gpu_reason=gpu_reason,
        ))
    score = (numerator / denominator) if denominator > 0 else None
    return BackendScore(backend=backend, score=score, numerator=numerator,
                        denominator=denominator, use_scores=use_scores)


def compute(uses: Mapping[str, set[str]], matrix: Mapping[str, str],
            evidence: Mapping[str, Any], repo_root: Path | None,
            fixture_mode: bool, ledger: Iterable[Mapping[str, Any]] | None = None,
            allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    cpu = score_backend("CPU", uses, matrix, evidence, repo_root, fixture_mode, ledger, allowed_cases)
    gpu = score_backend("GPU", uses, matrix, evidence, repo_root, fixture_mode, ledger, allowed_cases)
    return {"cpu": cpu, "gpu": gpu}


# --------------------------------------------------------------------------- #
# Subchecks (b1-b6) + population + #823 guard
# --------------------------------------------------------------------------- #

def _named_node_checks(uses: Mapping[str, set[str]], matrix: Mapping[str, str],
                       evidence: Mapping[str, Any], repo_root: Path | None,
                       fixture_mode: bool,
                       allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for label, bl_idname in NAMED_NODE_CHECKS.items():
        keys = [k for k in uses if k.split("|", 1)[0] == bl_idname]
        if not keys:
            checks[label] = {"bl_idname": bl_idname, "exercised": False,
                             "pass": False, "reason": "no exercised use in the corpus"}
            continue
        failing = []
        for key in keys:
            scenes = uses[key]
            cls = matrix.get(key, "")
            for backend in ("CPU", "GPU"):
                score, _ = score_use(key, scenes, cls, evidence, backend, repo_root, fixture_mode,
                                     allowed_cases=allowed_cases)
                if score <= 0.0:
                    failing.append(f"{key} [{backend}]")
        checks[label] = {"bl_idname": bl_idname, "exercised": True,
                         "pass": not failing, "failing": failing}
    return checks


def evaluate_subchecks(uses: Mapping[str, set[str]], matrix: Mapping[str, str],
                       evidence: Mapping[str, Any], repo_root: Path | None,
                       frozen: Mapping[str, Any],
                       cpu: BackendScore, gpu: BackendScore,
                       fixture_mode: bool, hash_locked: bool,
                       allowed_cases: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    drops = silent_drops(uses, matrix)
    named = _named_node_checks(uses, matrix, evidence, repo_root, fixture_mode, allowed_cases)
    unlinked: list[str] = []
    for use in cpu.use_scores:
        if use.cpu > 0.0 and not _valid_records(_records_for(evidence, use.key, "CPU"), repo_root, fixture_mode, allowed_cases):
            unlinked.append(f"{use.key} [CPU]")
        if use.gpu > 0.0 and not _valid_records(_records_for(evidence, use.key, "GPU"), repo_root, fixture_mode, allowed_cases):
            unlinked.append(f"{use.key} [GPU]")
    ratified = population_status(frozen, repo_root, fixture_mode)["ratified"]
    return {
        "b1_input_manifest_ratified": {
            "pass": bool(ratified and hash_locked),
            "ratified": ratified, "hash_locked": hash_locked,
        },
        "b2_cpu_score": {"pass": cpu.score is not None and cpu.score >= SCORE_MIN,
                         "score": cpu.score, "min": SCORE_MIN},
        "b3_gpu_score": {"pass": gpu.score is not None and gpu.score >= SCORE_MIN,
                         "score": gpu.score, "min": SCORE_MIN},
        "b4_zero_silent_drops": {"pass": len(drops) == 0, "drops": drops},
        "b5_named_node_checks": {"pass": all(c["pass"] for c in named.values()), "checks": named},
        "b6_nonzero_links_evidence": {"pass": len(unlinked) == 0, "unlinked": unlinked},
    }


def scanner_823_integrated(frozen: Mapping[str, Any], repo_root: Path | None,
                           fixture_mode: bool) -> tuple[bool, str]:
    """#823 must land before gate (b) is scored. Evidence is hash-verified."""
    entry = frozen.get("scanner_issue_823")
    if not isinstance(entry, Mapping):
        return False, "no scanner_issue_823 declaration in the frozen input manifest"
    if not entry.get("integrated"):
        return False, f"scanner issue #{entry.get('required', REQUIRED_SCANNER_ISSUE)} not declared integrated"
    if not fixture_mode:
        if repo_root is None:
            return False, "scanner integration requires a repository root"
        commit, path, recorded = entry.get("commit"), entry.get("source_path"), entry.get("source_sha256")
        if not isinstance(commit, str) or not isinstance(path, str) or not isinstance(recorded, str):
            return False, "scanner integration needs landed commit and pinned scanner source"
        try:
            landed = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "origin/main"],
                                    cwd=repo_root, capture_output=True, check=False).returncode == 0
            shown = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo_root, capture_output=True, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return False, "cannot verify #823 commit ancestry/source"
        if not landed:
            return False, "#823 commit is not an ancestor of origin/main"
        if _sha256_bytes(shown) != recorded.lower():
            return False, "#823 pinned scanner source does not match landed commit"
    ok, why = evidence_is_valid(entry, repo_root, fixture_mode=fixture_mode)
    if not ok:
        return False, f"#823 integration evidence invalid: {why}"
    return True, ""


def population_status(frozen: Mapping[str, Any], repo_root: Path | None = None,
                      fixture_mode: bool = False) -> dict[str, Any]:
    """PROVISIONAL nine-scene vs UNDEFINED unfrozen original.

    The scene count is derived from the frozen ``expected_scene_ids`` -- never
    from a caller-supplied ``scene_count``. Ratification requires a recorded
    owner-ratification artifact, not a flag.
    """
    pop = frozen.get("population", {})
    expected = list(pop.get("expected_scene_ids") or [])
    ratification = pop.get("ratification")
    ratified = bool(pop.get("ratified")) and isinstance(ratification, Mapping) and bool(ratification)
    if not fixture_mode:
        ratified = (ratified and isinstance(ratification.get("path"), str)
                    and len(str(ratification.get("sha256") or "")) == 64
                    and bool(ratification.get("owner")))
        if ratified and repo_root is not None:
            approval = Path(repo_root) / str(ratification["path"])
            ratified = approval.is_file() and _sha256_file(approval) == str(ratification["sha256"]).lower()
    if ratified:
        status = "ratified"
    elif len(expected) == NINE_SCENE_COUNT:
        status = "provisional"
    else:
        status = "undefined"
    return {
        "scene_count": len(expected),
        "expected_scene_ids": sorted(expected),
        "ratified": ratified,
        "status": status,
        "gate_eligible": status == "ratified",
        "original_population": {
            "label": ORIGINAL_POPULATION_LABEL,
            "status": "undefined",
            "reason": "the original population was never frozen; no score is computed",
        },
    }


# --------------------------------------------------------------------------- #
# Synthetic fixture + hand-computed validation
# --------------------------------------------------------------------------- #

def _inline_evidence(variant: str, *, behavior: str = "functioning",
                     warning: str = "") -> dict[str, Any]:
    content = f"{variant}:{behavior}:{warning}"
    return {"variant": variant, "behavior": behavior, "warning": warning,
            "content": content, "sha256": _sha256_bytes(content.encode("utf-8"))}


def synthetic_fixture() -> dict[str, Any]:
    """A 3-scene fixture whose weighted score is hand-computed.

    U1 Diffuse Color   : scenes S1,S2,S3 -> n=3, w=3, SUPPORTED
    U2 Glass Roughness : scenes S1,S2    -> n=2, w=2, APPROXIMATED (warned)
    U3 Sky sky_type    : scene  S1       -> n=1, w=1, SUPPORTED
    U4 Metallic Color  : scene  S1       -> n=1, w=1, SUPPORTED, no evidence

    CPU: U1=1.0, U2=0.5, U3=1.0, U4=0 (unproven)
         S_CPU = (3*1 + 2*0.5 + 1*1 + 1*0)/(3+2+1+1) = 5.0/7 = 0.7142857143
    GPU: U1=1.0, U2=0.5, U3=0 (no evidence), U4=0
         S_GPU = (3*1 + 2*0.5 + 1*0 + 1*0)/7 = 4.0/7 = 0.5714285714
    """
    u1 = canonical_identity("ShaderNodeBsdfDiffuse", "input:Color")
    u2 = canonical_identity("ShaderNodeBsdfGlass", "input:Roughness")
    u3 = canonical_identity("ShaderNodeTexSky", "sky_type")
    u4 = canonical_identity("ShaderNodeBsdfMetallic", "input:Base Color")
    uses = {u1: {"S1", "S2", "S3"}, u2: {"S1", "S2"}, u3: {"S1"}, u4: {"S1"}}
    matrix = {u1: SUPPORTED, u2: APPROXIMATED, u3: SUPPORTED, u4: SUPPORTED}
    evidence = {
        u1: {"CPU": [_inline_evidence("S1"), _inline_evidence("S2"), _inline_evidence("S3")],
             "GPU": [_inline_evidence("S1"), _inline_evidence("S2"), _inline_evidence("S3")]},
        u2: {"CPU": [_inline_evidence("S1", behavior="functioning", warning="bounded roughness"),
                     _inline_evidence("S2", behavior="functioning", warning="bounded roughness")],
             "GPU": [_inline_evidence("S1", behavior="functioning", warning="bounded roughness"),
                     _inline_evidence("S2", behavior="functioning", warning="bounded roughness")]},
        u3: {"CPU": [_inline_evidence("S1")], "GPU": []},
        u4: {"CPU": [], "GPU": []},
    }
    return {
        "uses": uses, "matrix": matrix, "evidence": evidence,
        "expected_cpu": 5.0 / 7.0, "expected_gpu": 4.0 / 7.0,
    }


def run_self_test() -> bool:
    """Validate the scorer against the hand-computed synthetic fixture."""
    fx = synthetic_fixture()
    cpu = score_backend("CPU", fx["uses"], fx["matrix"], fx["evidence"], None, fixture_mode=True)
    gpu = score_backend("GPU", fx["uses"], fx["matrix"], fx["evidence"], None, fixture_mode=True)
    ok = (cpu.score is not None and abs(cpu.score - fx["expected_cpu"]) < 1e-9
          and gpu.score is not None and abs(gpu.score - fx["expected_gpu"]) < 1e-9)
    capped = extract_exercised_uses({
        "S1": [{"bl_idname": "N", "sockets": ["input:X"]}],
        "S2": [{"bl_idname": "N", "sockets": ["input:X"]}],
        "S3": [{"bl_idname": "N", "sockets": ["input:X"]}],
        "S4": [{"bl_idname": "N", "sockets": ["input:X"]}],
    })
    key = canonical_identity("N", "input:X")
    capped_weight = min(len(capped[key]), WEIGHT_CAP)
    ok = ok and capped_weight == 3
    print(f"self-test CPU={cpu.score:.6f} (expected {fx['expected_cpu']:.6f}) "
          f"GPU={gpu.score:.6f} (expected {fx['expected_gpu']:.6f}) "
          f"capped_weight={capped_weight} -> {'OK' if ok else 'FAIL'}")
    return ok


# --------------------------------------------------------------------------- #
# Frozen coverage-input manifest (freeze + verify)
# --------------------------------------------------------------------------- #

def _corpus_manifest_entries(corpus_manifest: Mapping[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Validate the corpus manifest and return ``{scene_id: {blend_path, sha256}}``."""
    scenes = corpus_manifest.get("scenes")
    if not isinstance(scenes, Mapping) or not scenes:
        return {}, ["corpus manifest has no scenes"]
    entries: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for scene_id, scene in scenes.items():
        if not isinstance(scene, Mapping):
            errors.append(f"corpus scene {scene_id!r} is not an object")
            continue
        blend_path = scene.get("blend_path")
        sha = scene.get("sha256")
        if not isinstance(blend_path, str) or not blend_path.strip():
            errors.append(f"corpus scene {scene_id!r} has no blend_path")
            continue
        if not isinstance(sha, str) or len(sha) != 64:
            errors.append(f"corpus scene {scene_id!r} has malformed sha256")
            continue
        assets = []
        for asset in scene.get("assets", []) or []:
            if not isinstance(asset, Mapping) or not isinstance(asset.get("path"), str) or not isinstance(asset.get("sha256"), str) or len(asset["sha256"]) != 64:
                errors.append(f"corpus scene {scene_id!r} has malformed external asset")
                continue
            assets.append({"path": asset["path"], "sha256": asset["sha256"].lower()})
        settings = scene.get("settings", {})
        if settings is not None and not isinstance(settings, Mapping):
            errors.append(f"corpus scene {scene_id!r} has malformed settings")
            settings = {}
        entries[scene_id] = {"blend_path": blend_path, "sha256": sha.lower(),
                             "assets": sorted(assets, key=lambda a: a["path"]),
                             "settings": dict(settings or {})}
    return entries, errors


def freeze_coverage_input(corpus_manifest: Mapping[str, Any],
                          matrix_path: Path,
                          snapshot: Mapping[str, Any],
                          *, scanner_integrated: bool = False,
                          scanner_reason: str = "#823 not on origin/main") -> tuple[dict[str, Any], list[str]]:
    """Build the versioned, committed coverage-input manifest (v2).

    Verifies the collected snapshot's scene set equals the committed corpus
    exactly and that each scene's collected bytes hash matches the corpus hash.
    The population is PROVISIONAL (owner ratification absent) and the original
    "~50 scenes" population is UNDEFINED -- no score is frozen here.
    """
    errors: list[str] = []
    corpus_entries, corpus_errors = _corpus_manifest_entries(corpus_manifest)
    errors.extend(corpus_errors)

    snapshot_scenes = snapshot.get("scenes")
    if not isinstance(snapshot_scenes, Mapping):
        return {}, errors + ["snapshot has no scenes"]

    expected = sorted(corpus_entries)
    collected = sorted(snapshot_scenes)
    if collected != expected:
        missing = sorted(set(expected) - set(collected))
        extra = sorted(set(collected) - set(expected))
        if missing:
            errors.append(f"collected snapshot missing frozen scenes: {missing}")
        if extra:
            errors.append(f"collected snapshot has unexpected scenes: {extra}")

    scene_manifest: dict[str, dict[str, str]] = {}
    for scene_id in expected:
        entry = corpus_entries[scene_id]
        snap_scene = snapshot_scenes.get(scene_id) or {}
        snap_sha = str(snap_scene.get("scene_sha256") or "").lower()
        if snap_sha != entry["sha256"]:
            errors.append(f"scene {scene_id!r} collected bytes hash {snap_sha!r} "
                          f"!= corpus sha256 {entry['sha256']!r}")
        if snap_scene.get("collection_errors"):
            errors.append(f"scene {scene_id!r} has collection errors: {snap_scene.get('collection_errors')}")
        scene_manifest[scene_id] = {"blend_path": entry["blend_path"], "sha256": entry["sha256"], "assets": entry["assets"]}

    matrix_sha = _sha256_file(matrix_path)
    snapshot_sha = _sha256_bytes(_canonical_json(snapshot_scenes))
    ledger = materialize_use_ledger(snapshot)
    ledger_sha = _sha256_bytes(_canonical_json(ledger))

    frozen = {
        "schema": INPUT_MANIFEST_SCHEMA,
        "version": 1,
        "input_path": "docs/blender_parity/coverage_input_v2.json",
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "population": {
            "ratified": False,
            "ratification": None,
            "expected_scene_ids": expected,
            "original_population_label": ORIGINAL_POPULATION_LABEL,
            "original_population_status": "undefined",
        },
        "corpus": {
            "manifest_path": "benchmarks/reference_corpus/scenes/manifest.json",
            "scenes": scene_manifest,
        },
        "matrix": {"path": str(matrix_path), "sha256": matrix_sha},
        "collector": {"snapshot_sha256": snapshot_sha, "use_ledger": ledger,
                      "use_ledger_sha256": ledger_sha},
        "scanner_issue_823": {
            "required": REQUIRED_SCANNER_ISSUE,
            "integrated": scanner_integrated,
            "reason": "" if scanner_integrated else scanner_reason,
        },
        "evidence": {"mode": "production",
                     "sidecar_dir": "docs/blender_parity/evidence/gate_b/sidecars"},
    }
    return frozen, errors


def freeze_coverage_input_v3(corpus_manifest: Mapping[str, Any], matrix_path: Path,
                             snapshot: Mapping[str, Any], *,
                             candidate_build: Mapping[str, str] | None = None,
                             case_features: Mapping[str, str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Freeze v3 with the exact runner-case/build map, or a provisional empty map.

    A live candidate supplies build/module/addon hashes and a feature mapping.
    Until then this records an explicit unmeasured placeholder which cannot
    validate any production evidence.
    """
    frozen, errors = freeze_coverage_input(corpus_manifest, matrix_path, snapshot)
    frozen["schema"] = INPUT_MANIFEST_SCHEMA_V3
    frozen["version"] = 3
    frozen["input_path"] = "docs/blender_parity/coverage_input_v3.json"
    build = dict(candidate_build or {})
    required = ("build_id", "module_sha256", "addon_sha256")
    ready = all(isinstance(build.get(field), str) and build[field] for field in required)
    cases: list[dict[str, str]] = []
    if case_features is None:
        try:
            rows = json.loads(matrix_path.read_text(encoding="utf-8"))
            case_features = {canonical_identity(str(row["bl_idname"]), str(row["socket_or_prop"])):
                             f"{row['category']}:{row['feature']}" for row in rows
                             if isinstance(row, Mapping) and row.get("bl_idname") and row.get("socket_or_prop")
                             and row.get("category") and row.get("feature")}
        except (OSError, json.JSONDecodeError):
            case_features = {}
    if ready and case_features:
        for row in frozen["collector"]["use_ledger"]:
            feature = case_features.get(row["identity"])
            if not isinstance(feature, str) or not feature:
                continue
            for variant in row["variants"]:
                for backend in ("CPU", "GPU"):
                    case = {"identity": row["identity"], "scene_id": variant["scene_id"],
                            "variant_digest": variant["variant_digest"], "backend": backend,
                            "build_id": build["build_id"], "module_sha256": build["module_sha256"],
                            "addon_sha256": build["addon_sha256"], "feature": feature}
                    case["case_id"] = _sha256_bytes(_canonical_json(case))
                    cases.append(case)
    frozen["evidence"]["runner_case_map"] = {
        "status": "ready" if cases else "provisional",
        "candidate_build": {field: build.get(field) if ready else None for field in required},
        "cases": sorted(cases, key=lambda row: row["case_id"]),
    }
    frozen["evidence"]["runner_case_map"]["sha256"] = _sha256_bytes(
        _canonical_json(frozen["evidence"]["runner_case_map"]["cases"]))
    return frozen, errors


def freeze_coverage_input_v4(corpus_manifest: Mapping[str, Any], matrix_path: Path,
                             snapshot: Mapping[str, Any], *,
                             candidate_build: Mapping[str, str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Freeze only explicitly registered, locally measurable Gate-B cases.

    Unlike v3's broad provisional map, v4 carries immutable render settings and
    a reviewed pixel witness for each case.  A collected use without an exact
    registry entry is deliberately absent and therefore remains unproven.
    """
    frozen, errors = freeze_coverage_input(corpus_manifest, matrix_path, snapshot)
    frozen["schema"] = INPUT_MANIFEST_SCHEMA_V4
    frozen["version"] = 4
    frozen["input_path"] = "docs/blender_parity/coverage_input_v4.json"
    build = dict(candidate_build or {})
    required = ("build_id", "module_sha256", "addon_sha256")
    ready = all(isinstance(build.get(field), str) and build[field] for field in required)
    corpus_entries, corpus_errors = _corpus_manifest_entries(corpus_manifest)
    errors.extend(corpus_errors)
    for scene_id, entry in corpus_entries.items():
        declared = entry.get("settings", {})
        frozen_settings = {key: declared.get(key) for key in ("res_x", "res_y", "samples")}
        if all(isinstance(value, int) and value > 0 for value in frozen_settings.values()):
            frozen["corpus"]["scenes"][scene_id]["settings"] = frozen_settings
    cases: list[dict[str, Any]] = []
    if ready:
        for row in frozen["collector"]["use_ledger"]:
            for variant in row["variants"]:
                registration = CASE_WITNESS_REGISTRY.get(
                    (row["identity"], variant["scene_id"], variant["variant_digest"]))
                entry = corpus_entries.get(variant["scene_id"])
                if registration is None or entry is None:
                    continue
                declared = entry.get("settings", {})
                settings = {
                    "res_x": declared.get("res_x"), "res_y": declared.get("res_y"),
                    "samples": declared.get("samples"), "seed": 7, "denoise": False,
                    "adaptive": False, "resolution_percentage": 100,
                    "film_transparent": False, "view_transform": "Standard",
                }
                if any(not isinstance(settings[key], int) or settings[key] <= 0
                       for key in ("res_x", "res_y", "samples")):
                    errors.append(f"registered case {row['identity']!r} has invalid corpus settings")
                    continue
                for backend in ("CPU", "GPU"):
                    case = {
                        "identity": row["identity"], "scene_id": variant["scene_id"],
                        "variant_digest": variant["variant_digest"], "backend": backend,
                        **{field: build[field] for field in required},
                        "settings": settings, "witness": registration,
                    }
                    case["case_id"] = _sha256_bytes(_canonical_json(case))
                    cases.append(case)
    frozen["evidence"]["runner_case_map"] = {
        "status": "ready" if cases else "provisional",
        "candidate_build": {field: build.get(field) if ready else None for field in required},
        "cases": sorted(cases, key=lambda row: row["case_id"]),
    }
    frozen["evidence"]["runner_case_map"]["sha256"] = _sha256_bytes(
        _canonical_json(frozen["evidence"]["runner_case_map"]["cases"]))
    return frozen, errors


def verify_frozen_input(frozen: Mapping[str, Any], repo_root: Path,
                        snapshot: Mapping[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    """Re-verify a frozen input manifest against disk + the collected snapshot.

    Returns ``(ok, errors, verified)``. Absence or mismatch of the matrix hash,
    any corpus scene path/bytes, the exact scene set, or the collector snapshot
    hash makes the run RED/UNMEASURED -- never silently scored.
    """
    errors: list[str] = []
    verified: dict[str, Any] = {}

    if frozen.get("schema") not in (INPUT_MANIFEST_SCHEMA, INPUT_MANIFEST_SCHEMA_V3, INPUT_MANIFEST_SCHEMA_V4):
        return False, ["input manifest schema must be a supported v2, v3, or v4 manifest"], {}

    corpus_path = (frozen.get("corpus", {}).get("manifest_path")
                   or "benchmarks/reference_corpus/scenes/manifest.json")
    corpus_file = Path(corpus_path)
    if not corpus_file.is_absolute():
        corpus_file = Path(repo_root) / corpus_file
    if not corpus_file.is_file():
        return False, [f"corpus manifest missing: {corpus_path}"], {}
    try:
        corpus_manifest = json.loads(corpus_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"corpus manifest unreadable: {exc}"], {}
    corpus_entries, corpus_errors = _corpus_manifest_entries(corpus_manifest)
    errors.extend(corpus_errors)

    frozen_scenes = frozen.get("corpus", {}).get("scenes", {})
    expected = sorted(frozen.get("population", {}).get("expected_scene_ids") or [])
    if sorted(frozen_scenes) != expected:
        errors.append("frozen scene list disagrees with frozen expected_scene_ids")
    if sorted(corpus_entries) != expected:
        errors.append("corpus scene set disagrees with frozen expected_scene_ids")

    for scene_id in expected:
        frozen_entry = frozen_scenes.get(scene_id)
        corpus_entry = corpus_entries.get(scene_id)
        if not isinstance(frozen_entry, Mapping) or corpus_entry is None:
            errors.append(f"frozen scene {scene_id!r} is missing from frozen/corpus manifests")
            continue
        if frozen_entry.get("blend_path") != corpus_entry["blend_path"]:
            errors.append(f"frozen scene {scene_id!r} blend_path disagrees with corpus")
        if frozen_entry.get("sha256") != corpus_entry["sha256"]:
            errors.append(f"frozen scene {scene_id!r} sha256 disagrees with corpus")
        blend_file = Path(corpus_entry["blend_path"])
        if not blend_file.is_absolute():
            blend_file = Path(repo_root) / blend_file
        if not blend_file.is_file():
            errors.append(f"corpus scene file missing: {corpus_entry['blend_path']}")
        elif _sha256_file(blend_file) != corpus_entry["sha256"]:
            errors.append(f"corpus scene bytes changed: {corpus_entry['blend_path']}")
        frozen_assets = frozen_entry.get("assets", [])
        if frozen_assets != corpus_entry.get("assets", []):
            errors.append(f"corpus scene {scene_id!r} external asset set disagrees with corpus")
        for asset in corpus_entry.get("assets", []):
            asset_file = Path(asset["path"])
            if not asset_file.is_absolute():
                asset_file = Path(repo_root) / asset_file
            if not asset_file.is_file():
                errors.append(f"corpus external asset missing: {asset['path']}")
            elif _sha256_file(asset_file) != asset["sha256"]:
                errors.append(f"corpus external asset bytes changed: {asset['path']}")

    if frozen.get("schema") == INPUT_MANIFEST_SCHEMA_V4:
        for scene_id in expected:
            frozen_settings = frozen_scenes.get(scene_id, {}).get("settings")
            actual_settings = corpus_entries.get(scene_id, {}).get("settings")
            if frozen_settings != {key: actual_settings.get(key) for key in ("res_x", "res_y", "samples")}:
                errors.append(f"v4 frozen settings disagree with corpus scene {scene_id!r}")
    matrix_path = frozen.get("matrix", {}).get("path") or "docs/blender_parity/coverage_matrix.json"
    matrix_file = Path(matrix_path)
    if not matrix_file.is_absolute():
        matrix_file = Path(repo_root) / matrix_file
    if not matrix_file.is_file():
        errors.append(f"matrix missing: {matrix_path}")
    elif _sha256_file(matrix_file) != frozen.get("matrix", {}).get("sha256"):
        errors.append("matrix hash does not match the frozen input manifest")

    snapshot_scenes = snapshot.get("scenes")
    if not isinstance(snapshot_scenes, Mapping):
        errors.append("snapshot has no scenes")
    else:
        if sorted(snapshot_scenes) != expected:
            missing = sorted(set(expected) - set(snapshot_scenes))
            extra = sorted(set(snapshot_scenes) - set(expected))
            if missing:
                errors.append(f"snapshot missing frozen scenes: {missing}")
            if extra:
                errors.append(f"snapshot has unexpected scenes: {extra}")
        snapshot_sha = _sha256_bytes(_canonical_json(snapshot_scenes))
        if snapshot_sha != frozen.get("collector", {}).get("snapshot_sha256"):
            errors.append("collector snapshot hash does not match the frozen input manifest")
        ledger = materialize_use_ledger(snapshot)
        if ledger != frozen.get("collector", {}).get("use_ledger"):
            errors.append("collector use ledger does not match the frozen input manifest")
        if _sha256_bytes(_canonical_json(ledger)) != frozen.get("collector", {}).get("use_ledger_sha256"):
            errors.append("collector use ledger hash does not match the frozen input manifest")
        for scene_id in snapshot_scenes:
            if snapshot_scenes[scene_id].get("collection_errors"):
                errors.append(f"scene {scene_id!r} has collection errors")

    verified["expected_scene_ids"] = expected
    verified["use_ledger"] = frozen.get("collector", {}).get("use_ledger", [])
    sidecar_dir = frozen.get("evidence", {}).get("sidecar_dir") or "docs/blender_parity/evidence/gate_b/sidecars"
    verified["sidecar_dir"] = Path(sidecar_dir)
    if not verified["sidecar_dir"].is_absolute():
        verified["sidecar_dir"] = Path(repo_root) / verified["sidecar_dir"]
    if frozen.get("schema") in (INPUT_MANIFEST_SCHEMA_V3, INPUT_MANIFEST_SCHEMA_V4):
        case_map = frozen.get("evidence", {}).get("runner_case_map", {})
        cases = case_map.get("cases") if isinstance(case_map, Mapping) else None
        if not isinstance(cases, list):
            errors.append("runner case map has no cases list")
            cases = []
        if _sha256_bytes(_canonical_json(cases)) != case_map.get("sha256"):
            errors.append("runner case map hash does not match frozen input")
        if frozen.get("schema") == INPUT_MANIFEST_SCHEMA_V4:
            if case_map.get("status") != "ready":
                errors.append("v4 runner case map is not ready")
            for case in cases:
                if (not isinstance(case, Mapping) or not isinstance(case.get("witness"), Mapping)
                        or not isinstance(case.get("settings"), Mapping)
                        or CASE_WITNESS_REGISTRY.get((case.get("identity"), case.get("scene_id"),
                                                      case.get("variant_digest"))) != case.get("witness")):
                    errors.append("v4 runner case lacks its exact registered witness/settings")
                    break
        verified["allowed_cases"] = {str(case.get("case_id")): case for case in cases
                                     if isinstance(case, Mapping) and isinstance(case.get("case_id"), str)}
    else:
        verified["allowed_cases"] = {}
    return (not errors), errors, verified


def load_production_evidence(sidecar_dir: Path, repo_root: Path) -> tuple[dict[str, Any], list[str]]:
    """Load structured evidence sidecars into ``{identity: {backend: [records]}}``.

    Each sidecar is a ``*.json`` file that binds scene/socket/variant/backend/
    build/result-kind and references a hash-verified artifact. Sidecars that do
    not parse or that fail validation are collection errors -- never silently
    dropped from the denominator.
    """
    evidence: dict[str, Any] = {}
    errors: list[str] = []
    if not sidecar_dir.is_dir():
        return evidence, []  # no evidence yet: every nonzero claim scores 0
    for path in sorted(sidecar_dir.glob("*.json")):
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"sidecar {path.name!r} is not JSON: {exc}")
            continue
        if not isinstance(sidecar, Mapping) or sidecar.get("schema") != EVIDENCE_SCHEMA:
            errors.append(f"sidecar {path.name!r} has the wrong schema")
            continue
        identity = sidecar.get("identity")
        backend = sidecar.get("backend")
        if not identity or backend not in ("CPU", "GPU"):
            errors.append(f"sidecar {path.name!r} lacks identity/backend")
            continue
        record = dict(sidecar)
        record.setdefault("variant", sidecar.get("variant") or sidecar.get("scene_id"))
        evidence.setdefault(identity, {}).setdefault(backend, []).append(record)
    return evidence, errors


# --------------------------------------------------------------------------- #
# Report assembly
# --------------------------------------------------------------------------- #

def _unmeasured_report(pop: dict[str, Any], uses: Mapping[str, set[str]],
                       matrix: Mapping[str, str], subchecks: dict[str, Any],
                       reason: str, integrity_errors: list[str]) -> dict[str, Any]:
    return {
        "schema": "pkg278.coverage_report.v1",
        "status": "unmeasured",
        "blocked": True,
        "reason": reason,
        "integrity_errors": integrity_errors,
        "scanner_issue_823": {"required": REQUIRED_SCANNER_ISSUE,
                              "integrated": False, "reason": reason},
        "population": pop,
        "exercised_use_count": len(uses),
        "silent_drop_count": len(silent_drops(uses, matrix)),
        "silent_drops": silent_drops(uses, matrix),
        "cpu": {"backend": "CPU", "score": None, "status": "unmeasured"},
        "gpu": {"backend": "GPU", "score": None, "status": "unmeasured"},
        "subchecks": {k: {"pass": v["pass"]} for k, v in subchecks.items()},
    }


def build_report(frozen: Mapping[str, Any], snapshot: Mapping[str, Any],
                 matrix_rows: Iterable[Mapping[str, Any]],
                 repo_root: Path | None = None, *,
                 fixture_mode: bool = False) -> dict[str, Any]:
    """Assemble the gate (b) report. Integrity and #823 gates run first."""
    matrix = matrix_by_identity(matrix_rows)
    node_trees = _snapshot_node_trees(snapshot)

    if fixture_mode:
        uses = extract_exercised_uses(node_trees)
        evidence = frozen.get("evidence_entries", {}) or {}
        pop = population_status(frozen, fixture_mode=True)
        hash_locked = True
        integrity_errors: list[str] = []
    else:
        if repo_root is None:
            raise ValueError("production scoring requires repo_root")
        ok, integrity_errors, verified = verify_frozen_input(frozen, repo_root, snapshot)
        uses = _ledger_uses(verified.get("use_ledger", [])) if ok else extract_exercised_uses(node_trees)
        evidence = {}
        pop = population_status(frozen, repo_root)
        if ok:
            evidence, sidecar_errors = load_production_evidence(verified["sidecar_dir"], repo_root)
            integrity_errors.extend(sidecar_errors)
        hash_locked = ok

        # A production score may only consume the exact input bytes currently
        # committed at HEAD.  The freeze command can create v2 before commit;
        # scoring cannot turn that draft into a claim.
        input_path = frozen.get("input_path", "docs/blender_parity/coverage_input_v2.json")
        try:
            disk = Path(repo_root) / str(input_path)
            head = subprocess.run(["git", "show", f"HEAD:{input_path}"], cwd=repo_root,
                                  capture_output=True, check=True).stdout
            if not disk.is_file() or disk.read_bytes() != head:
                integrity_errors.append("frozen input bytes are not the exact committed HEAD version")
        except (OSError, subprocess.SubprocessError):
            integrity_errors.append("frozen input manifest is not committed at HEAD")

    scanner_ok, scanner_reason = scanner_823_integrated(frozen, repo_root, fixture_mode)
    ledger = None if fixture_mode else verified.get("use_ledger", [])
    allowed_cases = None if fixture_mode else verified.get("allowed_cases", {})
    computed = compute(uses, matrix, evidence, repo_root, fixture_mode, ledger, allowed_cases)
    subchecks = evaluate_subchecks(uses, matrix, evidence, repo_root, frozen,
                                   computed["cpu"], computed["gpu"],
                                   fixture_mode, hash_locked, allowed_cases)

    if integrity_errors:
        return _unmeasured_report(pop, uses, matrix, subchecks,
                                  f"gate (b) not scored: frozen input integrity failed "
                                  f"({len(integrity_errors)} error(s))", integrity_errors)

    if not scanner_ok:
        return _unmeasured_report(pop, uses, matrix, subchecks,
                                  f"gate (b) not scored: {scanner_reason}", [])

    green = all(v["pass"] for v in subchecks.values()) and pop["gate_eligible"]
    status = "green" if green else ("provisional" if not pop["gate_eligible"] else "red")
    return {
        "schema": "pkg278.coverage_report.v1",
        "status": status,
        "blocked": False,
        "reason": "" if green else "one or more subchecks failed or population not ratified",
        "integrity_errors": integrity_errors,
        "scanner_issue_823": {"required": REQUIRED_SCANNER_ISSUE,
                              "integrated": True, "reason": ""},
        "population": pop,
        "exercised_use_count": len(uses),
        "silent_drop_count": len(silent_drops(uses, matrix)),
        "silent_drops": silent_drops(uses, matrix),
        "cpu": computed["cpu"].to_dict(),
        "gpu": computed["gpu"].to_dict(),
        "subchecks": subchecks,
    }


def report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Gate (b) - frequency-weighted socket coverage (pkg278)",
        "",
        f"- Status: **{report['status'].upper()}**",
        f"- Reason: {report.get('reason') or 'n/a'}",
        f"- Exercised uses: {report.get('exercised_use_count')}",
        f"- Silent drops: {report.get('silent_drop_count')}",
        "",
        "## Population",
        "",
        f"- nine-scene: `{report['population']['status']}` (ratified={report['population']['ratified']})",
        f"- original {ORIGINAL_POPULATION_LABEL}: `undefined` (never frozen)",
        "",
    ]
    for backend in ("cpu", "gpu"):
        entry = report.get(backend, {})
        lines.append(f"## {backend.upper()} - S_{backend.upper()} = {entry.get('score')}")
        lines.append("")
    lines.append("## Subchecks")
    lines.append("")
    for name, value in report.get("subchecks", {}).items():
        lines.append(f"- {name}: {'PASS' if value.get('pass') else 'FAIL'}")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# In-Blender computed-reachability collector
# --------------------------------------------------------------------------- #

def _json_safe(value: Any) -> Any:
    """Coerce a Blender property value into a JSON-serializable scalar/list."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "to_list"):
        return [float(x) for x in value.to_list()]
    return str(value)


def _node_prop_variants(node: Any) -> dict[str, Any]:
    """Record non-default values of the matrix's known node properties."""
    out: dict[str, Any] = {}
    rna = getattr(node, "bl_rna", None)
    props = getattr(rna, "properties", None) if rna is not None else None
    for name in KNOWN_NODE_PROPERTIES:
        if not hasattr(node, name):
            continue
        value = getattr(node, name)
        val_key = getattr(value, "identifier", value)
        default = None
        if props is not None:
            prop_def = props.get(name)
            if prop_def is not None:
                default = getattr(prop_def, "default", None)
        def_key = getattr(default, "identifier", default)
        if default is not None and val_key == def_key:
            continue
        if default is None and _json_safe(val_key) in (None, "", 0, False):
            continue
        out[name] = _json_safe(val_key)
    return out


def _build_trees_from_bpy() -> dict[str, Any]:
    """Build the pure graph model from the current Blender scene (no render).

    Tree ids are derived from the OWNING datablock name (``material:``/``light:``/
    ``world:``/``group:`` prefix), never from ``node_tree.name`` -- corpus
    materials created programmatically can all report the default
    ``node_tree.name`` ("Shader Nodetree") while still being distinct data
    blocks, and collapsing them would silently drop denominator entries.
    """
    import bpy

    trees: dict[str, Any] = {}

    def _add_tree(tree: Any, kind: str, tid: str) -> None:
        if tree is None or tid in trees:
            return
        nodes: dict[str, Any] = {}
        links: list[dict[str, str]] = []
        for node in tree.nodes:
            is_group = node.bl_idname == "ShaderNodeGroup"
            group_tree = None
            if is_group and node.node_tree is not None:
                group_tree = f"group:{node.node_tree.name}"
                _add_tree(node.node_tree, "group", group_tree)
            nodes[node.name] = {
                "name": node.name,
                "bl_idname": node.bl_idname,
                "mute": bool(getattr(node, "mute", False)),
                "is_group": is_group,
                "group_tree": group_tree,
                "is_active_output": bool(getattr(node, "is_active_output", True)),
                "inputs": {s.identifier: {"linked": bool(s.is_linked), "enabled": bool(s.enabled),
                                           "default_value": _json_safe(getattr(s, "default_value", None))}
                           for s in node.inputs},
                "outputs": {s.identifier: bool(s.is_linked) for s in node.outputs},
                "internal_links": [(il.from_socket.identifier, il.to_socket.identifier)
                                   for il in getattr(node, "internal_links", [])],
                "prop_variants": _node_prop_variants(node),
                "op": getattr(node, "operation", None),
                "data_type": getattr(node, "data_type", None),
                "blend_type": getattr(node, "blend_type", None),
            }
        for node in tree.nodes:
            for in_socket in node.inputs:
                for link in in_socket.links:
                    links.append({
                        "from_node": link.from_node.name,
                        "from_socket": link.from_socket.identifier,
                        "to_node": node.name,
                        "to_socket": in_socket.identifier,
                    })
        trees[tid] = {"kind": kind, "nodes": nodes, "links": links}

    # Only datablocks actually reachable from the opened scene form the gate
    # population.  This includes object instances and their material slots.
    scene_objects = set(bpy.context.scene.objects)
    # Depsgraph instances include geometry supplied by collection instances;
    # those materials are part of the rendered scene even when their source
    # object is absent from Scene.objects.
    for instance in bpy.context.evaluated_depsgraph_get().object_instances:
        original = getattr(getattr(instance, "object", None), "original", None)
        if original is not None:
            scene_objects.add(original)
    used_materials = set()
    for obj in scene_objects:
        if getattr(obj, "type", None) in {"MESH", "CURVE", "CURVES", "SURFACE", "FONT", "META", "GPENCIL"}:
            for slot in getattr(obj, "material_slots", []):
                if slot.material is not None:
                    used_materials.add(slot.material)
    for mat in used_materials:
        if getattr(mat, "node_tree", None) is not None:
            _add_tree(mat.node_tree, "material", f"material:{mat.name}")
    for obj in scene_objects:
        light = getattr(obj, "data", None) if getattr(obj, "type", None) == "LIGHT" else None
        if light is not None and getattr(light, "use_nodes", False) and getattr(light, "node_tree", None) is not None:
            _add_tree(light.node_tree, "light", f"light:{light.name}")
    world = bpy.context.scene.world
    if world is not None and getattr(world, "use_nodes", False) and getattr(world, "node_tree", None) is not None:
        _add_tree(world.node_tree, "world", f"world:{world.name}")
    return trees


def _collect_one_scene(blend_path: str) -> dict[str, Any]:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene_sha256 = _sha256_file(Path(blend_path))
    trees = _build_trees_from_bpy()
    reachable, errors = trace_reachable(trees)

    nodes: list[dict[str, Any]] = []
    for tid, name in sorted(reachable):
        node = trees[tid]["nodes"][name]
        sockets, fingerprint = exercised_sockets_for(node)
        if node.get("mute"):
            # A muted node is bypassed; its wiring is still reachable but its
            # sockets are not exercised, so it contributes no denominator entry.
            continue
        nodes.append({
            "bl_idname": node["bl_idname"],
            "sockets": sockets,
            "fingerprint": fingerprint,
        })
    nodes.sort(key=lambda n: (n["bl_idname"], n["sockets"], n["fingerprint"]["linked_inputs"]))
    return {
        "blend_path": blend_path,
        "scene_sha256": scene_sha256,
        "collection_errors": errors,
        "nodes": nodes,
    }


def collect_node_uses_in_blender(blend_paths: Iterable[str]) -> dict[str, Any]:
    """Reopen each corpus .blend and record the computed-reachability snapshot.

    Runs inside Blender. Emits ONLY the nodes a backward reachability trace
    reached from the active Material/World/Light Output inputs, crossing group
    output/input routing and respecting mute/internal links. A disconnected but
    internally wired subtree does NOT appear. A group node whose tree cannot be
    resolved raises ``collection_errors`` (invalidating the collection), never a
    silent denominator drop.
    """
    scenes: dict[str, Any] = {}
    for path in blend_paths:
        scene_id = Path(path).stem
        scenes[scene_id] = _collect_one_scene(str(path))
    return {
        "schema": NODE_USES_SCHEMA,
        "collected": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "scenes": scenes,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    # When run inside Blender via ``--python script.py -- <args>``, Blender
    # hands the FULL command line to sys.argv (including ``--``), so split on
    # the separator the same way build_corpus.py / render_leg.py do.
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(description="Gate (b) weighted coverage scorer (pkg278).")
    p.add_argument("--self-test", action="store_true",
                   help="validate the scorer against the hand-computed synthetic fixture")
    p.add_argument("--collect", action="store_true",
                   help="(inside Blender) reopen corpus .blend files and write the computed-reachability snapshot")
    p.add_argument("--freeze", action="store_true",
                   help="verify the snapshot against the corpus and write the versioned input manifest")
    p.add_argument("--freeze-v3", action="store_true",
                   help="freeze v3 with an explicitly provisional runner case map")
    p.add_argument("--freeze-v4", action="store_true",
                   help="freeze v4 with registered pixel witnesses and immutable render settings")
    p.add_argument("--candidate-build", type=Path,
                   help="JSON with build_id/module_sha256/addon_sha256 for a ready v3/v4 case map")
    p.add_argument("--score", action="store_true",
                   help="verify the frozen input + snapshot against disk, then score")
    p.add_argument("--manifest", type=Path,
                   default=Path("benchmarks/reference_corpus/scenes/manifest.json"))
    p.add_argument("--matrix", type=Path,
                   default=Path("docs/blender_parity/coverage_matrix.json"))
    p.add_argument("--input-manifest", type=Path, default=None,
                   help="frozen scoring input manifest (population, evidence, #823 status)")
    p.add_argument("--node-uses", type=Path, default=None,
                   help="node-use snapshot produced by --collect")
    p.add_argument("--out", type=Path, default=Path("docs/blender_parity/evidence/gate_b"))
    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]

    if args.self_test:
        return 0 if run_self_test() else 1

    if args.collect:
        manifest = _load_json(args.manifest)
        blend_paths = [s["blend_path"] for s in manifest["scenes"].values()]
        payload = collect_node_uses_in_blender(blend_paths)
        out_path = args.node_uses or (args.out / "node_uses.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
        print(f"wrote {out_path}")
        return 0

    if args.freeze or args.freeze_v3 or args.freeze_v4:
        if args.node_uses is None:
            print("--freeze needs --node-uses", file=sys.stderr)
            return 2
        corpus_manifest = _load_json(args.manifest)
        snapshot = _load_json(args.node_uses)
        if args.freeze_v4:
            candidate = _load_json(args.candidate_build) if args.candidate_build else None
            frozen, errors = freeze_coverage_input_v4(corpus_manifest, args.matrix, snapshot,
                                                       candidate_build=candidate)
        elif args.freeze_v3:
            candidate = _load_json(args.candidate_build) if args.candidate_build else None
            frozen, errors = freeze_coverage_input_v3(corpus_manifest, args.matrix, snapshot,
                                                       candidate_build=candidate)
        else:
            frozen, errors = freeze_coverage_input(corpus_manifest, args.matrix, snapshot)
        default_input = ("docs/blender_parity/coverage_input_v4.json" if args.freeze_v4 else
                         "docs/blender_parity/coverage_input_v3.json" if args.freeze_v3 else
                         "docs/blender_parity/coverage_input_v2.json")
        out_path = args.input_manifest or Path(default_input)
        if args.input_manifest is not None:
            out_path = args.input_manifest
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(frozen, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
        for err in errors:
            print(f"[freeze] error: {err}", file=sys.stderr)
        print(f"[freeze] wrote {out_path} (errors={len(errors)})")
        return 1 if errors else 0

    if args.score:
        if args.input_manifest is None or args.node_uses is None:
            print("--score needs --input-manifest and --node-uses", file=sys.stderr)
            return 2
        frozen = _load_json(args.input_manifest)
        snapshot = _load_json(args.node_uses)
        matrix_rows = _load_json(args.matrix)
        report = build_report(frozen, snapshot, matrix_rows, repo_root)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "coverage_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
        (args.out / "corpus_coverage.md").write_text(
            report_markdown(report), encoding="utf-8", newline="\n")
        print(f"[pkg278] gate (b) status={report['status']} -> {args.out}")
        return 0 if report["status"] in ("green", "provisional") else 1

    print("choose --self-test, --collect, --freeze or --score", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
