"""pkg278 - focused tests for the exit-gate instruments.

Covers the omission-resistant coverage scorer (hand-computed synthetic fixture +
adversarial missing/hash/backend/dimension cases), the acceptance manifest
(always a-f, computed statuses, hand-edit rejection, frozen thresholds) and the
clean-install validator (ineligible dev machine, hash-locked checks).

    pytest tests/test_pkg278_gate_instruments.py -v
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CR = _load("pkg278_coverage_report", "benchmarks/reference_corpus/coverage_report.py")
HARNESS = _load("pkg278_blender_parity_harness", "benchmarks/blender_parity/harness.py")
GM = _load("pkg278_gate_manifest", "scripts/gate_manifest.py")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hex(seed: int) -> str:
    return hashlib.sha256(f"scene-{seed}".encode()).hexdigest()


# =========================================================================== #
# Coverage scorer
# =========================================================================== #

def test_scorer_self_test_passes():
    assert CR.run_self_test() is True


def test_synthetic_fixture_matches_hand_computed_weighted_score():
    fx = CR.synthetic_fixture()
    cpu = CR.score_backend("CPU", fx["uses"], fx["matrix"], fx["evidence"], None, fixture_mode=True)
    gpu = CR.score_backend("GPU", fx["uses"], fx["matrix"], fx["evidence"], None, fixture_mode=True)
    assert cpu.score == pytest.approx(5.0 / 7.0, abs=1e-12)
    assert gpu.score == pytest.approx(4.0 / 7.0, abs=1e-12)
    assert cpu.denominator == 7.0 and gpu.denominator == 7.0


def _canonical_production_record(tmp_path, *, backend="CPU", build_id="build-1",
                                 variant_digest="variant-1", module_sha256="m" * 64,
                                 addon_sha256="a" * 64):
    identity, scene_id, case_id = "ShaderNodeBsdfDiffuse|input:Color", "S1", "case-1"
    witness = {"roi": [0.25, 0.25, 0.75, 0.75],
               "control": {"kind": "checker_flat", "object": "card", "mask": {"kind": "object_polygon"}},
               "effect": {"min_delta": .05, "min_coverage": .02, "min_signal": .001}}
    settings = {"res_x": 16, "res_y": 16, "samples": 1, "seed": 7, "denoise": False,
                "adaptive": False, "resolution_percentage": 100, "film_transparent": False, "view_transform": "Standard"}
    case = {"case_id": case_id, "identity": identity, "scene_id": scene_id,
            "variant_digest": variant_digest, "backend": backend, "build_id": build_id,
            "module_sha256": module_sha256, "addon_sha256": addon_sha256,
            "witness": witness, "settings": settings}
    astro = tmp_path / "astroray_linear_npy.npy"; cycles = tmp_path / "cycles_linear_npy.npy"
    astro_control = tmp_path / "astroray_control_linear_npy.npy"; cycles_control = tmp_path / "cycles_control_linear_npy.npy"
    astro_mask = tmp_path / "astroray_feature_mask.npy"; cycles_mask = tmp_path / "cycles_feature_mask.npy"
    baseline = np.full((16, 16, 3), .5, dtype=np.float32); control = baseline.copy()
    control[4:12, 4:8] = .25; control[4:12, 8:12] = .75
    mask = np.zeros((16, 16), dtype=np.uint8); mask[4:12, 4:12] = 255
    np.save(astro, baseline); np.save(cycles, baseline); np.save(astro_control, control); np.save(cycles_control, control)
    np.save(astro_mask, mask); np.save(cycles_mask, mask)
    binding = {key: case[key] for key in ("case_id", "identity", "scene_id", "variant_digest", "backend", "build_id")}
    observed = {"identity": identity, "scene_id": scene_id, "variant_digest": variant_digest,
                "backend": backend, "build_id": build_id, "module_sha256": module_sha256,
                "addon_sha256": addon_sha256, "engine_id": "CUSTOM_RAYTRACER", "device": backend.lower()}
    blend_sha = _sha("frozen blend")
    raw = {"schema": "pkg278.gate_b.case_observation.v2", "case": binding, "witness": witness, "settings": settings,
           "mutation_receipt": {"kind": "baseline", "ok": True}, "graph": {"identity": identity, "variant_digest": variant_digest},
           "engine": "CUSTOM_RAYTRACER", "observed": observed, "blend_sha256": blend_sha}
    cycles_observed = {"schema": "pkg278.gate_b.case_observation.v2", "case": binding, "witness": witness, "settings": settings,
                       "mutation_receipt": {"kind": "baseline", "ok": True}, "graph": {"identity": identity, "variant_digest": variant_digest},
                       "engine": "CYCLES", "observed": {"identity": identity, "scene_id": scene_id,
                       "variant_digest": variant_digest, "engine_id": "CYCLES", "device": "cpu"},
                       "blend_sha256": blend_sha}
    raw["linear_npy"], raw["feature_mask_npy"] = str(astro.resolve()), str(astro_mask.resolve())
    cycles_observed["linear_npy"], cycles_observed["feature_mask_npy"] = str(cycles.resolve()), str(cycles_mask.resolve())
    astro_control_observed = dict(raw, linear_npy=str(astro_control.resolve()), mutation_receipt={"kind": "checker_flat", "ok": True})
    cycles_control_observed = dict(cycles_observed, linear_npy=str(cycles_control.resolve()), mutation_receipt={"kind": "checker_flat", "ok": True})
    astro_raw = tmp_path / "report.json"; astro_raw.write_text(json.dumps(raw), encoding="utf-8")
    cycles_raw = tmp_path / "cycles_report.json"; cycles_raw.write_text(json.dumps(cycles_observed), encoding="utf-8")
    astro_control_raw = tmp_path / "astroray_control_report.json"; astro_control_raw.write_text(json.dumps(astro_control_observed), encoding="utf-8")
    cycles_control_raw = tmp_path / "cycles_control_report.json"; cycles_control_raw.write_text(json.dumps(cycles_control_observed), encoding="utf-8")
    refs = {"astroray_linear_npy": {"path": astro.name, "sha256": CR.sha256_file(astro)},
            "cycles_linear_npy": {"path": cycles.name, "sha256": CR.sha256_file(cycles)},
            "report": {"path": astro_raw.name, "sha256": CR.sha256_file(astro_raw)},
            "cycles_report": {"path": cycles_raw.name, "sha256": CR.sha256_file(cycles_raw)},
            "astroray_control_report": {"path": astro_control_raw.name, "sha256": CR.sha256_file(astro_control_raw)},
            "cycles_control_report": {"path": cycles_control_raw.name, "sha256": CR.sha256_file(cycles_control_raw)},
            "astroray_control_linear_npy": {"path": astro_control.name, "sha256": CR.sha256_file(astro_control)},
            "cycles_control_linear_npy": {"path": cycles_control.name, "sha256": CR.sha256_file(cycles_control)},
            "astroray_feature_mask": {"path": astro_mask.name, "sha256": CR.sha256_file(astro_mask)},
            "cycles_feature_mask": {"path": cycles_mask.name, "sha256": CR.sha256_file(cycles_mask)}}
    effect, reason = CR.witness_metrics(baseline, baseline, control, control, mask, mask, witness)
    assert effect is not None, reason
    runner = {"schema": CR.RUNNER_RESULT_SCHEMA, "results": [HARNESS.gate_b_corpus_result(
        case, observed, effect, refs, effect=effect, settings=settings)]}
    runner_path = tmp_path / "runner.json"; runner_path.write_text(json.dumps(runner), encoding="utf-8")
    runner_sha = CR.sha256_file(runner_path)
    record = {"schema": CR.EVIDENCE_SCHEMA, "identity": identity, "scene_id": scene_id,
              "variant": scene_id, "variant_digest": variant_digest, "backend": backend,
              "build_id": build_id, "case_id": case_id, "result_kind": "test_result",
              "artifact": refs["astroray_linear_npy"],
              "verdict": {"schema": CR.VERDICT_SCHEMA, "pass": True, "identity": identity,
                          "scene_id": scene_id, "variant_digest": variant_digest, "backend": backend,
                          "build_id": build_id, "result": {"kind": "test_result", "artifact_sha256": runner_sha}},
              "verifier_result": {"path": runner_path.name, "sha256": runner_sha}}
    return record, {case_id: case}


def test_witness_metrics_rejects_wrong_local_region_empty_mask_and_dark_signal():
    witness = {"roi": [.25, .25, .75, .75], "effect": {"min_delta": .05, "min_coverage": .02, "min_signal": .001}}
    baseline = np.full((16, 16, 3), .5, dtype=np.float32)
    wrong_control = baseline.copy(); wrong_control[:4, :4] = .1
    mask = np.zeros((16, 16), dtype=np.uint8); mask[4:12, 4:12] = 255
    result, reason = CR.witness_metrics(baseline, baseline, wrong_control, wrong_control, mask, mask, witness)
    assert result is not None and not result["pass"]
    one_sided = baseline.copy(); one_sided[4:12, 4:12] = .25
    result, reason = CR.witness_metrics(baseline, baseline, one_sided, one_sided, mask, mask, witness)
    assert result is not None and not result["pass"]
    empty, reason = CR.witness_metrics(baseline, baseline, baseline, baseline, np.zeros_like(mask), mask, witness)
    assert empty is None and "empty" in reason
    dark = np.zeros_like(baseline); changed = dark.copy(); changed[4:12, 4:12] = .5
    result, reason = CR.witness_metrics(dark, dark, changed, changed, mask, mask, witness)
    assert result is not None and not result["pass"]


def test_production_evidence_rejects_tampered_frozen_settings(tmp_path):
    record, cases = _canonical_production_record(tmp_path)
    runner_path = tmp_path / "runner.json"; runner = json.loads(runner_path.read_text(encoding="utf-8"))
    runner["results"][0]["settings"]["seed"] = 99
    runner_path.write_text(json.dumps(runner), encoding="utf-8")
    digest = CR.sha256_file(runner_path)
    record["verifier_result"]["sha256"] = digest; record["verdict"]["result"]["artifact_sha256"] = digest
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]


def test_production_evidence_requires_frozen_case_and_canonical_metrics(tmp_path):
    record, cases = _canonical_production_record(tmp_path)
    assert CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases={})[0]
    record["verifier_result"]["path"] = "astroray_linear_npy.npy"
    record["verifier_result"]["sha256"] = CR.sha256_file(tmp_path / "astroray_linear_npy.npy")
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]


@pytest.mark.parametrize("field,value", [("backend", "GPU"), ("build_id", "wrong"),
                                           ("variant_digest", "wrong")])
def test_production_evidence_rejects_runner_case_mismatch(tmp_path, field, value):
    record, cases = _canonical_production_record(tmp_path)
    produced = json.loads((tmp_path / "runner.json").read_text(encoding="utf-8"))
    produced["results"][0][field] = value
    (tmp_path / "runner.json").write_text(json.dumps(produced), encoding="utf-8")
    record["verifier_result"]["sha256"] = CR.sha256_file(tmp_path / "runner.json")
    record["verdict"]["result"]["artifact_sha256"] = record["verifier_result"]["sha256"]
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]


@pytest.mark.parametrize("field,value", [("module_sha256", "bad-module"),
                                           ("addon_sha256", "bad-addon")])
def test_production_evidence_rejects_observed_native_identity_mismatch(tmp_path, field, value):
    record, cases = _canonical_production_record(tmp_path)
    cases["case-1"][field] = value
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]


def test_production_evidence_recomputes_runner_metrics_and_raw_graph(tmp_path):
    record, cases = _canonical_production_record(tmp_path)
    runner_path = tmp_path / "runner.json"
    runner = json.loads(runner_path.read_text(encoding="utf-8"))
    runner["results"][0]["metrics"]["ssim"] = .99
    runner_path.write_text(json.dumps(runner), encoding="utf-8")
    digest = CR.sha256_file(runner_path)
    record["verifier_result"]["sha256"] = digest
    record["verdict"]["result"]["artifact_sha256"] = digest
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]

    record, cases = _canonical_production_record(tmp_path)
    raw = tmp_path / "report.json"
    report = json.loads(raw.read_text(encoding="utf-8"))
    report["graph"]["variant_digest"] = "relabeled"
    raw.write_text(json.dumps(report), encoding="utf-8")
    runner_path = tmp_path / "runner.json"
    runner = json.loads(runner_path.read_text(encoding="utf-8"))
    runner["results"][0]["artifacts"]["report"]["sha256"] = CR.sha256_file(raw)
    runner_path.write_text(json.dumps(runner), encoding="utf-8")
    digest = CR.sha256_file(runner_path)
    record["verifier_result"]["sha256"] = digest
    record["verdict"]["result"]["artifact_sha256"] = digest
    assert not CR.evidence_is_valid(record, tmp_path, allowed_cases=cases)[0]


def test_render_cleanup_preserves_precomputed_gate_b_mask(tmp_path):
    render_leg = _load("pkg278_render_leg", "benchmarks/blender_parity/render_leg.py")
    stem = tmp_path / "cycles"
    mask = tmp_path / "cycles_mask.npy"; np.save(mask, np.ones((2, 2), dtype=np.uint8))
    stale = stem.with_suffix(".npy"); np.save(stale, np.zeros((2, 2), dtype=np.float32))
    (tmp_path / "cycles0001.exr").write_bytes(b"render")
    render_leg._clear_render_outputs(stem)
    assert mask.is_file() and not stale.exists() and not (tmp_path / "cycles0001.exr").exists()


def test_harness_emits_metric_derived_gate_b_result():
    result = HARNESS.FeatureResult("shader_node", "BSDF_DIFFUSE", "SUPPORTED", "pass",
                                   ssim=.99, delta_e=1.0)
    case = {"case_id": "case", "identity": "N|input:X", "scene_id": "S1",
            "variant_digest": "v", "feature": "shader_node:BSDF_DIFFUSE"}
    with pytest.raises(ValueError, match="generic FeatureResult"):
        HARNESS.gate_b_runner_results([result], [case], backend="CPU", build_id="b",
                                      module_sha256="m", addon_sha256="a")


def test_missing_evidence_scores_zero_never_raises():
    fx = CR.synthetic_fixture()
    u1 = CR.canonical_identity("ShaderNodeBsdfDiffuse", "input:Color")
    fx["evidence"][u1]["GPU"] = []
    gpu = CR.score_backend("GPU", fx["uses"], fx["matrix"], fx["evidence"], None, fixture_mode=True)
    # U1 drops from 1.0 to 0 -> (3*0 + 2*0.5)/7 = 1/7
    assert gpu.score == pytest.approx(1.0 / 7.0, abs=1e-12)


def test_hash_mismatch_invalidates_evidence():
    rec = {"variant": "S1", "behavior": "functioning", "warning": "",
           "content": "payload", "sha256": _sha("a different payload")}
    ok, why = CR.evidence_is_valid(rec, None, fixture_mode=True)
    assert not ok and "hash mismatch" in why


def test_evidence_path_hash_verified(tmp_path):
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("rendered", encoding="utf-8")
    good = {"variant": "S1", "behavior": "functioning", "warning": "",
            "artifact": {"path": "evidence.txt", "sha256": _sha("rendered")}}
    assert CR.evidence_is_valid(good, tmp_path, fixture_mode=True)[0]
    bad = dict(good, artifact={"path": "evidence.txt", "sha256": _sha("tampered")})
    assert not CR.evidence_is_valid(bad, tmp_path, fixture_mode=True)[0]


def test_inline_evidence_rejected_in_production_mode():
    rec = {"scene_id": "S1", "variant": "S1", "backend": "CPU", "build_id": "b1",
           "result_kind": "render", "behavior": "functioning", "warning": "",
           "content": "payload", "sha256": _sha("payload")}
    ok, why = CR.evidence_is_valid(rec, None, fixture_mode=False)
    assert not ok and "requires a file artifact" in why


def test_production_sidecar_requires_bindings(tmp_path):
    artifact = tmp_path / "render.png"
    artifact.write_bytes(b"\x89PNG\r\n\x1a\n")
    digest = CR.sha256_file(artifact)
    # Missing scene/variant/backend/build bindings -> invalid production evidence.
    bare = {"artifact": {"path": "render.png", "sha256": digest}}
    ok, why = CR.evidence_is_valid(bare, tmp_path, fixture_mode=False)
    assert not ok and "missing bindings" in why

    full = {"identity": "ShaderNodeBsdfDiffuse|input:Color", "scene_id": "S1", "variant": "S1",
            "variant_digest": "a" * 64, "backend": "CPU", "build_id": "b1",
                "result_kind": "render",
                "artifact": {"path": "render.png", "sha256": digest}}
    ok, why = CR.evidence_is_valid(full, tmp_path, fixture_mode=False)
    assert not ok and "semantic verdict" in why


def test_production_scoring_rejects_forged_inline_evidence():
    key = CR.canonical_identity("N", "input:X")
    inline = {"variant": "S1", "behavior": "functioning", "warning": "",
              "content": "x", "sha256": _sha("x")}
    score, reason = CR.score_use(key, {"S1"}, CR.SUPPORTED,
                                 {key: {"CPU": [inline]}}, "CPU", None, fixture_mode=False)
    assert score == 0.0 and "no hash-verified evidence" in reason


def test_approximation_without_warning_scores_zero():
    key = CR.canonical_identity("N", "input:X")
    ev = {"variant": "S1", "behavior": "functioning", "warning": "",
          "content": "x", "sha256": _sha("x")}
    score, reason = CR.score_use(key, {"S1"}, CR.APPROXIMATED, {key: {"CPU": [ev]}},
                                 "CPU", None, fixture_mode=True)
    assert score == 0.0 and "warning" in reason


def test_approximation_ignored_but_warned_scores_zero():
    key = CR.canonical_identity("N", "input:X")
    ev = {"variant": "S1", "behavior": "ignored", "warning": "dropped with a warning",
          "content": "x", "sha256": _sha("x")}
    score, _ = CR.score_use(key, {"S1"}, CR.APPROXIMATED, {key: {"CPU": [ev]}},
                            "CPU", None, fixture_mode=True)
    assert score == 0.0


def test_evidence_must_cover_every_exercised_variant():
    key = CR.canonical_identity("N", "input:X")
    ev = {"variant": "S1", "behavior": "functioning", "warning": "",
          "content": "x", "sha256": _sha("x")}
    score, reason = CR.score_use(key, {"S1", "S2"}, CR.SUPPORTED, {key: {"CPU": [ev]}},
                                 "CPU", None, fixture_mode=True)
    assert score == 0.0 and "S2" in reason


def test_weight_capped_at_three_distinct_scenes():
    uses = CR.extract_exercised_uses({
        f"S{i}": [{"bl_idname": "N", "sockets": ["input:X"]}] for i in range(5)
    })
    key = CR.canonical_identity("N", "input:X")
    assert len(uses[key]) == 5
    assert min(len(uses[key]), CR.WEIGHT_CAP) == 3


def test_silent_drops_reported_separately():
    uses = {CR.canonical_identity("N", "input:X"): {"S1"},
            CR.canonical_identity("M", "input:Y"): {"S1"}}
    matrix = {CR.canonical_identity("N", "input:X"): CR.SUPPORTED,
              CR.canonical_identity("M", "input:Y"): CR.DROPPED_SILENT}
    drops = CR.silent_drops(uses, matrix)
    assert drops == [CR.canonical_identity("M", "input:Y")]


# =========================================================================== #
# Computed reachability (disconnected subtrees, group routing, mute)
# =========================================================================== #

def _mk_node(bl_idname, *, inputs=None, outputs=None, internal_links=None,
             mute=False, is_group=False, group_tree=None, is_active_output=True):
    return {
        "name": bl_idname,
        "bl_idname": bl_idname,
        "mute": mute,
        "is_group": is_group,
        "group_tree": group_tree,
        "is_active_output": is_active_output,
        "inputs": inputs or {},
        "outputs": outputs or {},
        "internal_links": internal_links or [],
    }


def _mk_tree(kind, nodes, links):
    return {"kind": kind, "nodes": {n["name"]: n for n in nodes}, "links": links}


def test_reachability_excludes_disconnected_internally_wired_subtree():
    trees = {
        "material:M": _mk_tree("material", [
            _mk_node("ShaderNodeOutputMaterial", inputs={"Surface": True}),
            _mk_node("LinkedBSDF", inputs={"Base Color": False}, outputs={"BSDF": True}),
            _mk_node("DisconnectedTex", inputs={"Vector": True}, outputs={"Color": False}),
            _mk_node("DisconnectedSrc", outputs={"Generated": True}),
        ], [
            {"from_node": "LinkedBSDF", "from_socket": "BSDF",
             "to_node": "ShaderNodeOutputMaterial", "to_socket": "Surface"},
            {"from_node": "DisconnectedSrc", "from_socket": "Generated",
             "to_node": "DisconnectedTex", "to_socket": "Vector"},
        ]),
    }
    reachable, errors = CR.trace_reachable(trees)
    assert not errors
    assert ("material:M", "ShaderNodeOutputMaterial") in reachable
    assert ("material:M", "LinkedBSDF") in reachable
    assert ("material:M", "DisconnectedTex") not in reachable
    assert ("material:M", "DisconnectedSrc") not in reachable


def test_reachability_traverses_live_group_path_and_excludes_inner_disconnected():
    trees = {
        "material:M": _mk_tree("material", [
            _mk_node("ShaderNodeOutputMaterial", inputs={"Surface": True}),
            _mk_node("ShaderNodeGroup", is_group=True, group_tree="group:G",
                     inputs={"Color": True}, outputs={"Shader": True}),
            _mk_node("ShaderNodeTexImage", outputs={"Color": True}),
        ], [
            {"from_node": "ShaderNodeGroup", "from_socket": "Shader",
             "to_node": "ShaderNodeOutputMaterial", "to_socket": "Surface"},
            {"from_node": "ShaderNodeTexImage", "from_socket": "Color",
             "to_node": "ShaderNodeGroup", "to_socket": "Color"},
        ]),
        "group:G": _mk_tree("group", [
            _mk_node("NodeGroupInput", outputs={"Color": True, "Color2": False}),
            _mk_node("NodeGroupOutput", inputs={"Shader": True}),
            _mk_node("InnerBSDF", inputs={"Color": True}, outputs={"BSDF": True}),
            _mk_node("DisconnectedInner", inputs={"Color": False}, outputs={"Emission": False}),
        ], [
            {"from_node": "NodeGroupInput", "from_socket": "Color",
             "to_node": "InnerBSDF", "to_socket": "Color"},
            {"from_node": "InnerBSDF", "from_socket": "BSDF",
             "to_node": "NodeGroupOutput", "to_socket": "Shader"},
        ]),
    }
    reachable, errors = CR.trace_reachable(trees)
    assert not errors
    for pair in [("material:M", "ShaderNodeOutputMaterial"), ("material:M", "ShaderNodeGroup"),
                 ("material:M", "ShaderNodeTexImage"), ("group:G", "NodeGroupOutput"),
                 ("group:G", "InnerBSDF"), ("group:G", "NodeGroupInput")]:
        assert pair in reachable, pair
    assert ("group:G", "DisconnectedInner") not in reachable


def test_reachability_unresolvable_group_invalidates_collection():
    trees = {
        "material:M": _mk_tree("material", [
            _mk_node("ShaderNodeOutputMaterial", inputs={"Surface": True}),
            _mk_node("ShaderNodeGroup", is_group=True, group_tree="group:missing",
                     inputs={}, outputs={"Shader": True}),
        ], [
            {"from_node": "ShaderNodeGroup", "from_socket": "Shader",
             "to_node": "ShaderNodeOutputMaterial", "to_socket": "Surface"},
        ]),
    }
    reachable, errors = CR.trace_reachable(trees)
    assert errors  # missing group support must invalidate, never silently drop


def test_reachability_muted_node_is_bypassed_but_still_reachable():
    trees = {
        "material:M": _mk_tree("material", [
            _mk_node("ShaderNodeOutputMaterial", inputs={"Surface": True}),
            _mk_node("ShaderNodeMixRGB", mute=True, inputs={"Fac": True, "Color1": True, "Color2": True},
                     outputs={"Color": True}, internal_links=[("Color1", "Color")]),
            _mk_node("ShaderNodeTexImage", outputs={"Color": True}),
        ], [
            {"from_node": "ShaderNodeMixRGB", "from_socket": "Color",
             "to_node": "ShaderNodeOutputMaterial", "to_socket": "Surface"},
            {"from_node": "ShaderNodeTexImage", "from_socket": "Color",
             "to_node": "ShaderNodeMixRGB", "to_socket": "Color1"},
        ]),
    }
    reachable, errors = CR.trace_reachable(trees)
    assert not errors
    assert ("material:M", "ShaderNodeMixRGB") in reachable
    # internal link Color1 -> Color passes the signal through to TexImage.
    assert ("material:M", "ShaderNodeTexImage") in reachable


def test_exercised_sockets_enumerate_input_output_and_prop():
    node = {
        "bl_idname": "ShaderNodeMath",
        "inputs": {"Value": True, "Value_001": True, "Value_002": False},
        "outputs": {"Value": True},
        "prop_variants": {"operation": "MULTIPLY"},
        "op": "MULTIPLY",
    }
    sockets, fingerprint = CR.exercised_sockets_for(node)
    assert "input:Value" in sockets and "input:Value_001" in sockets
    assert "output:Value" in sockets
    assert "prop:operation" in sockets
    assert fingerprint["op"] == "MULTIPLY"
    # An enabled constant/default socket is a real exercised variant too.
    assert "input:Value_002" in sockets


def _find_blender() -> str | None:
    import shutil
    from pathlib import Path as _P
    candidates = [
        _P(r"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"),
        _P(r"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"),
        _P(r"C:/Program Files/Blender Foundation/Blender 4.3/blender.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("blender")
    return found or None


def test_headless_blender_collector_reachability_fixture():
    blender = _find_blender()
    if blender is None:
        pytest.skip("Blender not found; headless graph-only fixture skipped")
    import subprocess
    fixture = REPO_ROOT / "benchmarks" / "reference_corpus" / "gate_b_fixture.py"
    result = subprocess.run(
        [blender, "-b", "--factory-startup", "--python", str(fixture)],
        capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


# =========================================================================== #
# Frozen input manifest (binding, integrity, mandatory scene coverage)
# =========================================================================== #

def _corpus_manifest(scenes: dict) -> dict:
    return {"scenes": {sid: {"blend_path": f"benchmarks/reference_corpus/scenes/{sid}.blend",
                             "sha256": sha}
                       for sid, sha in scenes.items()}}


def _freeze_and_verify(tmp_path, scene_ids):
    """Build corpus .blend files + a collected snapshot, freeze, then verify.

    Lays out the same repo-relative layout the production scorer expects
    (``benchmarks/reference_corpus/scenes/...``) under ``tmp_path`` so the
    frozen manifest's relative paths resolve against the repo root.
    """
    scenes_dir = tmp_path / "benchmarks" / "reference_corpus" / "scenes"
    scenes_dir.mkdir(parents=True)
    scene_hashes = {}
    snapshot_scenes = {}
    for sid in scene_ids:
        blend = scenes_dir / f"{sid}.blend"
        blend.write_bytes(f"blend-{sid}".encode())
        scene_hashes[sid] = CR.sha256_file(blend)
        snapshot_scenes[sid] = {"blend_path": f"benchmarks/reference_corpus/scenes/{sid}.blend",
                                "scene_sha256": scene_hashes[sid],
                                "collection_errors": [],
                                "nodes": [{"bl_idname": "ShaderNodeBsdfDiffuse",
                                           "sockets": ["input:Color"], "fingerprint": {}}]}
    matrix = tmp_path / "coverage_matrix.json"
    matrix.write_text(json.dumps([{"category": "shader_node", "feature": "BSDF_DIFFUSE",
                                   "bl_idname": "ShaderNodeBsdfDiffuse",
                                   "socket_or_prop": "input:Color",
                                   "classification": CR.SUPPORTED}]), encoding="utf-8")
    corpus = _corpus_manifest(scene_hashes)
    corpus_file = scenes_dir / "manifest.json"
    corpus_file.write_text(json.dumps(corpus), encoding="utf-8")
    snapshot = {"schema": CR.NODE_USES_SCHEMA, "scenes": snapshot_scenes}
    frozen, errors = CR.freeze_coverage_input(corpus, matrix, snapshot)
    assert not errors, errors
    ok, verify_errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert ok, verify_errors
    return frozen, snapshot, scene_hashes, matrix


def test_freeze_v4_emits_only_registered_witness_cases(tmp_path, monkeypatch):
    _frozen, snapshot, _hashes, matrix = _freeze_and_verify(tmp_path, ["textures_mapping"])
    manifest_path = tmp_path / "benchmarks" / "reference_corpus" / "scenes" / "manifest.json"
    corpus = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus["scenes"]["textures_mapping"]["settings"] = {"res_x": 16, "res_y": 16, "samples": 1}
    manifest_path.write_text(json.dumps(corpus), encoding="utf-8")
    ledger = CR.materialize_use_ledger(snapshot)
    variant = ledger[0]["variants"][0]["variant_digest"]
    witness = {"roi": [.25, .25, .75, .75], "control": {"kind": "checker_flat", "object": "card", "mask": {"kind": "object_polygon"}}, "effect": {"min_delta": .05, "min_coverage": .02, "min_signal": .001}}
    monkeypatch.setattr(CR, "CASE_WITNESS_REGISTRY", {(ledger[0]["identity"], "textures_mapping", variant): witness})
    candidate = {"build_id": "b", "module_sha256": "m", "addon_sha256": "a"}
    frozen, errors = CR.freeze_coverage_input_v4(corpus, matrix, snapshot, candidate_build=candidate)
    assert not errors and frozen["schema"] == CR.INPUT_MANIFEST_SCHEMA_V4
    cases = frozen["evidence"]["runner_case_map"]["cases"]
    assert len(cases) == 2 and all(case["witness"] == witness and case["settings"]["seed"] == 7 for case in cases)
    ok, verify_errors, verified = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert ok, verify_errors
    assert set(verified["allowed_cases"]) == {case["case_id"] for case in cases}
    frozen["evidence"]["runner_case_map"]["status"] = "provisional"
    ok, verify_errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and "v4 runner case map is not ready" in verify_errors


def test_freeze_and_verify_roundtrip(tmp_path):
    frozen, snapshot, hashes, matrix = _freeze_and_verify(tmp_path, ["S1", "S2", "S3"])
    assert frozen["population"]["ratified"] is False
    assert frozen["population"]["expected_scene_ids"] == ["S1", "S2", "S3"]
    assert frozen["matrix"]["sha256"] == CR.sha256_file(matrix)
    assert frozen["collector"]["snapshot_sha256"]


def test_verify_rejects_missing_frozen_scene(tmp_path):
    frozen, snapshot, hashes, _ = _freeze_and_verify(tmp_path, ["S1", "S2", "S3"])
    snapshot["scenes"].pop("S2")
    ok, errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and any("missing frozen scenes" in e for e in errors)


def test_verify_rejects_changed_scene_bytes(tmp_path):
    frozen, snapshot, hashes, _ = _freeze_and_verify(tmp_path, ["S1", "S2", "S3"])
    blend = tmp_path / "benchmarks" / "reference_corpus" / "scenes" / "S1.blend"
    blend.write_bytes(b"tampered")
    ok, errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and any("bytes changed" in e for e in errors)


def test_verify_rejects_snapshot_hash_mismatch(tmp_path):
    frozen, snapshot, hashes, _ = _freeze_and_verify(tmp_path, ["S1", "S2", "S3"])
    snapshot["scenes"]["S1"]["nodes"].append({"bl_idname": "ShaderNodeEmission",
                                              "sockets": ["input:Color"], "fingerprint": {}})
    ok, errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and any("snapshot hash" in e for e in errors)


def test_verify_rejects_wrong_matrix_hash(tmp_path):
    frozen, snapshot, hashes, matrix = _freeze_and_verify(tmp_path, ["S1", "S2", "S3"])
    matrix.write_text(json.dumps([]), encoding="utf-8")
    ok, errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and any("matrix hash" in e for e in errors)


def test_verify_rejects_external_asset_tamper_and_ledger_drift(tmp_path):
    frozen, snapshot, hashes, matrix = _freeze_and_verify(tmp_path, ["S1"])
    asset = tmp_path / "benchmarks" / "reference_corpus" / "assets" / "volume.vdb"
    asset.parent.mkdir(parents=True); asset.write_bytes(b"vdb")
    asset_ref = {"path": "benchmarks/reference_corpus/assets/volume.vdb", "sha256": CR.sha256_file(asset)}
    corpus = _corpus_manifest(hashes)
    corpus["scenes"]["S1"]["assets"] = [asset_ref]
    (tmp_path / "benchmarks" / "reference_corpus" / "scenes" / "manifest.json").write_text(json.dumps(corpus), encoding="utf-8")
    frozen, errors = CR.freeze_coverage_input(corpus, matrix, snapshot)
    assert not errors, errors
    asset.write_bytes(b"changed")
    ok, errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and any("external asset bytes changed" in e for e in errors)
    asset.write_bytes(b"vdb")
    snapshot["scenes"]["S1"]["nodes"][0]["sockets"].append("input:Roughness")
    ok, errors, _ = CR.verify_frozen_input(frozen, tmp_path, snapshot)
    assert not ok and any("use ledger" in e for e in errors)


def test_freeze_rejects_unexpected_scene(tmp_path):
    scenes_dir = tmp_path / "benchmarks" / "reference_corpus" / "scenes"
    scenes_dir.mkdir(parents=True)
    scene_hashes = {}
    snapshot_scenes = {}
    for sid in ("S1", "S2", "EXTRA"):
        blend = scenes_dir / f"{sid}.blend"
        blend.write_bytes(f"blend-{sid}".encode())
        scene_hashes[sid] = CR.sha256_file(blend)
        snapshot_scenes[sid] = {"blend_path": f"benchmarks/reference_corpus/scenes/{sid}.blend",
                                "scene_sha256": scene_hashes[sid],
                                "collection_errors": [], "nodes": []}
    matrix = tmp_path / "coverage_matrix.json"
    matrix.write_text("[]", encoding="utf-8")
    corpus = _corpus_manifest({"S1": scene_hashes["S1"], "S2": scene_hashes["S2"]})
    snapshot = {"schema": CR.NODE_USES_SCHEMA, "scenes": snapshot_scenes}
    frozen, errors = CR.freeze_coverage_input(corpus, matrix, snapshot)
    assert any("unexpected scenes" in e for e in errors)


# =========================================================================== #
# Report assembly (fixture mode + scanner/population gates)
# =========================================================================== #

def _fixture_frozen(*, ratified=True, scanner=True, scene_ids=("S1", "S2", "S3"),
                    evidence_entries=None) -> dict:
    scanner_entry = {"integrated": True}
    if scanner:
        content = "issue-823-landed"
        scanner_entry.update({"content": content, "sha256": _sha(content)})
    return {
        "schema": CR.INPUT_MANIFEST_SCHEMA,
        "version": 1,
        "population": {"ratified": ratified,
                       "ratification": {"owner": "test"} if ratified else None,
                       "expected_scene_ids": list(scene_ids)},
        "scanner_issue_823": scanner_entry,
        "evidence": {"mode": "fixture"},
        "evidence_entries": evidence_entries or {},
    }


def test_scanner_823_blocks_any_score():
    fx = CR.synthetic_fixture()
    frozen = _fixture_frozen(ratified=False, scanner=False)
    frozen["evidence_entries"] = fx["evidence"]
    report = CR.build_report(frozen, {"scenes": {"S1": [], "S2": [], "S3": []}},
                             [], None, fixture_mode=True)
    assert report["status"] == "unmeasured"
    assert report["blocked"] is True
    assert report["cpu"]["score"] is None and report["gpu"]["score"] is None


def test_unratified_population_is_provisional_not_green():
    fx = CR.synthetic_fixture()
    u4 = CR.canonical_identity("ShaderNodeBsdfMetallic", "input:Base Color")
    for key in fx["evidence"]:
        for backend in ("CPU", "GPU"):
            if not fx["evidence"][key][backend]:
                fx["evidence"][key][backend] = [CR._inline_evidence(s)
                                                for s in sorted(fx["uses"][key])]
    assert u4 in fx["evidence"]
    scene_ids = tuple(f"S{i}" for i in range(9))  # nine-scene population
    frozen = _fixture_frozen(ratified=False, scene_ids=scene_ids,
                             evidence_entries=fx["evidence"])
    report = CR.build_report(frozen, {"scenes": {s: [] for s in scene_ids}},
                             [], None, fixture_mode=True)
    assert report["population"]["status"] == "provisional"
    assert report["population"]["gate_eligible"] is False
    assert report["status"] == "provisional"


def test_backend_scores_are_separate_not_averaged():
    u1 = CR.canonical_identity("ShaderNodeBsdfDiffuse", "input:Color")
    ev = {u1: {"CPU": [CR._inline_evidence("S1")], "GPU": []}}
    frozen = _fixture_frozen(evidence_entries=ev)
    node_trees = {"S1": [{"bl_idname": "ShaderNodeBsdfDiffuse", "sockets": ["input:Color"]}]}
    report = CR.build_report(frozen, {"scenes": node_trees},
                             [{"category": "shader_node", "feature": "BSDF_DIFFUSE",
                               "bl_idname": "ShaderNodeBsdfDiffuse",
                               "socket_or_prop": "input:Color",
                               "classification": CR.SUPPORTED}],
                             None, fixture_mode=True)
    assert report["cpu"]["score"] == pytest.approx(1.0)
    assert report["gpu"]["score"] == pytest.approx(0.0)
    assert report["status"] == "red"  # GPU fails 95 %; backends never averaged
    assert report["subchecks"]["b2_cpu_score"]["pass"] is True
    assert report["subchecks"]["b3_gpu_score"]["pass"] is False


def test_original_population_is_undefined():
    report = CR.population_status({"population": {"ratified": False,
                                                  "expected_scene_ids": []}})
    assert report["status"] == "undefined"
    assert report["original_population"]["status"] == "undefined"


def test_empty_owner_ratification_is_not_a_production_decision():
    report = CR.population_status({"population": {"ratified": True, "ratification": {},
                                                    "expected_scene_ids": [str(i) for i in range(9)]}})
    assert report["status"] == "provisional"


def test_production_build_report_requires_repo_root():
    frozen = _fixture_frozen()
    with pytest.raises(ValueError):
        CR.build_report(frozen, {"scenes": {}}, [], None, fixture_mode=False)


# =========================================================================== #
# Acceptance manifest
# =========================================================================== #

def test_manifest_always_has_rows_a_through_f():
    manifest, _ = GM.assemble({})
    assert set(manifest["rows"]) == set(GM.ROWS)
    for rid in GM.ROWS:
        assert manifest["rows"][rid]["status"] == "unmeasured"
        assert manifest["rows"][rid]["value"] is None
    assert GM.validate_shape(manifest) == []


def test_gate_b_adapter_recomputes_a_hash_pinned_canonical_report(tmp_path, monkeypatch):
    """End-to-end-shaped pure fixture: report text cannot supply its own score."""
    expected = {"schema": "pkg278.coverage_report.v1", "cpu": {"score": .97},
                "gpu": {"score": .96}, "subchecks": {key: {"pass": True}
                for key in GM.ROW_SPEC["b"]["required_subchecks"]}}
    frozen = {"schema": "pkg278.coverage_input_manifest.v4", "input_path": "input.json",
              "matrix": {"path": "matrix.json"},
              "evidence": {"runner_case_map": {"status": "ready",
                           "candidate_build": {"build_id": "candidate"}}}}
    snapshot, matrix = {"scenes": {}}, []
    for name, payload in (("input.json", frozen), ("snapshot.json", snapshot),
                          ("matrix.json", matrix), ("report.json", expected)):
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(GM, "REPO_ROOT", tmp_path)
    calls = []
    class Reducer:
        @staticmethod
        def build_report(got_frozen, got_snapshot, got_matrix, got_root):
            calls.append((got_frozen, got_snapshot, got_matrix, got_root))
            return expected
    monkeypatch.setattr(GM, "_coverage_reducer", lambda: Reducer)
    ref = lambda name: {"path": name, "sha256": GM.sha256_file(tmp_path / name)}
    record = {"kind": "coverage_reduction", "input": ref("input.json"),
              "snapshot": ref("snapshot.json"), "matrix": ref("matrix.json"),
              "report": ref("report.json")}
    errors, value, subchecks = GM._validate_b([record], tmp_path)
    assert not errors and value == {"cpu_score": .97, "gpu_score": .96}
    assert subchecks == expected["subchecks"] and len(calls) == 1
    adapted = GM.adapt_b_instrument(tmp_path / "report.json", tmp_path / "input.json",
                                    tmp_path / "snapshot.json", tmp_path / "matrix.json")
    assert adapted["build_id"] == "candidate" and adapted["value"] == value
    errors, adapted_value, _ = GM._validate_b(adapted["records"], tmp_path)
    assert not errors and adapted_value == value
    (tmp_path / "report.json").write_text(json.dumps({**expected, "cpu": {"score": 1.0}}), encoding="utf-8")
    record["report"] = ref("report.json")
    errors, _, _ = GM._validate_b([record], tmp_path)
    assert any("differs from the canonical recomputation" in error for error in errors)


def test_hand_edited_green_is_rejected(tmp_path):
    existing = {"rows": {"a": {"status": "green"}}}
    manifest, reasons = GM.assemble({}, tmp_path, existing)
    row = manifest["rows"]["a"]
    assert row["status"] == "red"
    assert row.get("hand_edit_detected") is True
    assert "hand-edited" in reasons["a"][0]


def test_green_row_without_evidence_is_red(tmp_path):
    raw = {
        "instrument": "viewport_latency", "scene_sha256": [_hex(1), _hex(2)],
        "build_id": "b1", "backend": ["GPU"], "settings": {}, "metric": {},
        "value": {"gpu_p95_ms": 50.0, "gpu_p99_ms": 50.0, "cancel_p95_ms": 100.0,
                  "cancel_p99_ms": 100.0, "stale_frames_after_ack": 0},
        "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                      "cancel_p99_ms": 300, "stale_frames_after_ack": 0},
        "evidence_path": None, "evidence_sha256": None,
        "dimensions": {"scene": True, "edit_kind": True, "repetitions": True},
        "subchecks": {k: {"pass": True} for k in GM.ROW_SPEC["a"]["required_subchecks"]},
        "date": "2026-09-23",
    }
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red"
    assert any("evidence" in r for r in reasons)


def _green_row_a(tmp_path) -> dict:
    evidence = tmp_path / "gate_a.json"
    pre, post = tmp_path / "pre.png", tmp_path / "post.png"
    pre.write_bytes(b"\x89PNG\r\n\x1a\npre-capture")
    post.write_bytes(b"\x89PNG\r\n\x1a\npost-capture")
    addon, module = tmp_path / "addon.py", tmp_path / "astroray.pyd"
    addon.write_bytes(b"observed addon identity")
    module.write_bytes(b"observed module identity")
    observed = {
        "engine": "CUSTOM_RAYTRACER", "requested_device": "gpu", "denoise_enabled": False,
        "actual_gpu_devices": [0],
        "addon": {"path": str(addon), "sha256": GM.sha256_file(addon)},
        "module": {"path": str(module), "sha256": GM.sha256_file(module)},
    }
    workloads = []
    for triangles in (10_000, 100_000):
        blend = tmp_path / f"workload_{triangles}.blend"
        blend.write_bytes(f"frozen workload with {triangles} triangles".encode())
        scene = GM.sha256_file(blend)
        workloads.append((scene, triangles, blend))

    def capture(scene, triangles, blend, edit_kind, batch):
        raw_events, edits = [{"name": "render_device", "generation": None, "epoch": None,
                               "t_ns": 0, "extra": {"device": 0}}], []
        base = (batch + 1) * 20_000_000_000
        for repetition in range(100):
            event_id, generation = repetition + 1, repetition + 1
            dispatch = base + repetition * 100_000_000
            publication = event_id
            fingerprint = [edit_kind, batch, repetition]
            edits.append({"event_id": event_id, "dispatch_ns": dispatch,
                          "generation": generation, "epoch": 7, "input_floor": generation,
                          "input_fingerprint": fingerprint})
            raw_events.extend([
                {"name": "viewport_pixels", "generation": None, "epoch": None,
                 "t_ns": dispatch - 1, "extra": {"event_id": event_id, "label": "pre",
                                                     "path": str(pre), "sha256": GM.sha256_file(pre)}},
                {"name": "input_applied", "generation": None, "epoch": None,
                 "t_ns": dispatch, "extra": {"event_id": event_id}},
                {"name": "request", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 1, "extra": {}},
                {"name": "edit_bound", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 1, "extra": {"event_id": event_id, "fingerprint": fingerprint}},
                {"name": "mailbox_enqueue", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 2, "extra": {"pub_id": publication}},
                {"name": "mailbox_dequeue", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 3, "extra": {"pub_id": publication}},
                {"name": "texture_upload_end", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 4, "extra": {"pub_id": publication}},
                {"name": "post_pixel_present", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 50_000_000, "extra": {"pub_id": publication}},
                {"name": "viewport_pixels", "generation": generation, "epoch": 7,
                 "t_ns": dispatch + 50_000_001, "extra": {"event_id": event_id, "label": "post",
                                                               "path": str(post), "sha256": GM.sha256_file(post)}},
            ])
        cancel = base + 10_000_000_010
        raw_events.extend([
            {"name": "cancel_stimulus", "generation": 100, "epoch": 7,
             "t_ns": cancel - 1, "extra": {"kind": "material_input"}},
            {"name": "cancel_request", "generation": 100, "epoch": 7, "t_ns": cancel, "extra": {}},
            {"name": "cancel_floor", "generation": 100, "epoch": 7, "t_ns": cancel + 5,
             "extra": {"cancelled_generation": 100, "cancelled_epoch": 7, "observed_floor": 101,
                       "desired_generation": 101, "stimulus": "material_view_update"}},
            {"name": "idle_ack", "generation": 100, "epoch": 7, "t_ns": cancel + 100_000_000, "extra": {}},
            {"name": "idle_drain", "generation": 100, "epoch": 7, "t_ns": cancel + 100_000_001, "extra": {}},
        ])
        return {"scene_sha256": scene, "edit_kind": edit_kind, "batch": batch, "backend": "GPU",
                "denoise_enabled": False, "observed_runtime": observed, "truncated": False,
                "workload": {"path": str(blend), "sha256": scene, "triangles": triangles,
                             "freeze": {"blend_sha256": scene, "observed_triangles": triangles}},
                "raw_events": raw_events, "edits": edits}

    records = [capture(scene, triangles, blend, edit_kind, batch)
               for scene, triangles, blend in workloads
               for edit_kind in ("camera", "material") for batch in range(3)]
    scene_hashes = [scene for scene, _triangles, _blend in workloads]
    payload = {
        "schema": "pkg278.instrument.v2", "row": "a", "instrument": "viewport_latency",
        "scene_sha256": scene_hashes, "build_id": "b1", "backend": ["GPU"],
        "settings": {"resolution": "128x128"}, "metric": {"name": "event_to_present"},
        "value": {"gpu_p95_ms": 50.0, "gpu_p99_ms": 50.0, "cancel_p95_ms": 100.0,
                  "cancel_p99_ms": 100.0, "stale_frames_after_ack": 0},
        "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                      "cancel_p99_ms": 300, "stale_frames_after_ack": 0}, "records": records,
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    digest = GM.sha256_file(evidence)
    return {
        "instrument": "viewport_latency",
        "scene_sha256": scene_hashes, "build_id": "b1", "backend": ["GPU"],
        "settings": {"resolution": "128x128"}, "metric": {"name": "event_to_present"},
        "value": {"gpu_p95_ms": 50.0, "gpu_p99_ms": 50.0, "cancel_p95_ms": 100.0,
                  "cancel_p99_ms": 100.0, "stale_frames_after_ack": 0},
        "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                      "cancel_p99_ms": 300, "stale_frames_after_ack": 0},
        "evidence_path": str(evidence), "evidence_sha256": digest,
        "dimensions": {"scene": "concrete", "edit_kind": "concrete", "repetitions": 100},
        "subchecks": {"both_pinned_scenes": True, "three_by_hundred_repetitions": True,
                      "denoise_excluded": True, "gpu_only_latency": True},
        "date": "2026-09-23",
    }


def test_valid_green_row_computes_green(tmp_path):
    row, reasons = GM.compute_row("a", _green_row_a(tmp_path), GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "green", reasons


def test_hash_pinned_empty_or_wrong_instrument_payload_is_red(tmp_path):
    raw = _green_row_a(tmp_path)
    evidence = Path(raw["evidence_path"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["instrument"] = "wrong-instrument"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("instrument mismatch" in r for r in reasons)

    evidence.write_text("{}", encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("schema" in r for r in reasons)


def test_green_requires_required_backend_and_dimensions(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["backend"] = ["CPU"]  # row (a) is a GPU-only latency oracle
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("backend" in r for r in reasons)

    raw = _green_row_a(tmp_path)
    raw["dimensions"] = {"scene": True}
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("dimension" in r for r in reasons)


def test_threshold_cannot_be_loosened(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["threshold"]["gpu_p95_ms"] = 9999
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("loosened" in r for r in reasons)


def test_value_outside_frozen_bound_is_red(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["value"]["gpu_p95_ms"] = 250  # > 100 ms
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("outside frozen bound" in r for r in reasons)


def test_incomplete_latency_lattice_is_red(tmp_path):
    raw = _green_row_a(tmp_path)
    evidence = Path(raw["evidence_path"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["records"].pop()
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("1200" in r or "cover" in r for r in reasons)


def test_latency_rejects_missing_artifact_and_nonconcrete_dimensions(tmp_path):
    raw = _green_row_a(tmp_path)
    evidence = Path(raw["evidence_path"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    pixels = next(event for event in payload["records"][0]["raw_events"]
                  if event["name"] == "viewport_pixels" and event["extra"]["label"] == "post")
    pixels["extra"] = {**pixels["extra"], "path": "DOES_NOT_EXIST.png", "sha256": "0" * 64}
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    raw["dimensions"] = {"scene": [], "edit_kind": 0, "repetitions": {}}
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red"
    assert any("correct presented generation chain" in reason for reason in reasons)
    assert any("dimension" in reason for reason in reasons)


def test_latency_rejects_wrong_outer_instrument_and_bad_numeric_without_crash(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["instrument"] = "issue_triage"
    raw["threshold"]["gpu_p95_ms"] = []
    raw["value"]["gpu_p99_ms"] = True
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red"
    assert any("manifest instrument mismatch" in reason for reason in reasons)
    assert any("finite number" in reason for reason in reasons)


def test_trio_requires_frozen_roles_paired_f12_runs_and_real_artifacts(tmp_path):
    image = tmp_path / "image.bin"; image.write_bytes(b"display image")
    image_ref = {"path": image.name, "sha256": GM.sha256_file(image)}
    hashes = [_hex(i) for i in (11, 12, 13)]
    records = []
    for role, actual, digest in zip(GM.TRIO_ROLES, ("gallery", "workshop", "terrace_hair"), hashes):
        for backend in ("CPU", "GPU"):
            linear = tmp_path / f"{actual}_{backend}.npy"
            pixels = np.full((12, 12, 3), 0.5, dtype=np.float32)
            if role != GM.TRIO_ROLES[-1]:
                pixels[:, :6] = .2; pixels[:, 6:] = .8
            else:
                pixels[:, 6:] = .8
            np.save(linear, pixels)
            probes = [{"kind": "checker", "value": .3, "threshold": .1, "ok": True}]
            cfg = {"gate_c_rois": {"all": [0, 0, 1, 1]},
                   "gate_c_probes": [{"kind": "checker", "roi": "all", "min": .1}]}
            if role == GM.TRIO_ROLES[-1]:
                probes = [{"kind": "hdri", "value": .5, "threshold": .1, "ok": True},
                          {"kind": "hair", "value": 1., "threshold": .1, "ok": True}]
                cfg = {"gate_c_rois": {"bg": [0, 0, .5, 1], "hair": [.5, 0, 1, 1], "all": [0,0,1,1]},
                       "gate_c_probes": [{"kind": "hdri", "roi": "bg", "min": .1},
                                             {"kind": "hair", "roi": "hair", "background_roi": "bg", "min": .1}]}
            records.append({"kind": "f12_run", "role": role, "scene_id": actual, "scene_sha256": digest,
                            "backend": backend, "build_id": "b1", "exit_code": 0, "sentinel": "PKG119B_LEG",
                            "image": image_ref, "linear_npy": {"path": linear.name, "sha256": GM.sha256_file(linear)},
                            "non_vacuity": probes, "settings": cfg,
                            "rois": [{"name": "all"}]})
    evidence = tmp_path / "gate_c.json"
    freeze = {"roles": {role: {"scene_id": actual, "scene_sha256": digest,
                                 "rois": next(r["settings"]["gate_c_rois"] for r in records if r["role"] == role),
                                 "non_vacuity": next(r["settings"]["gate_c_probes"] for r in records if r["role"] == role)}
                         for role, actual, digest in zip(GM.TRIO_ROLES, ("gallery", "workshop", "terrace_hair"), hashes)}}
    freeze_path = tmp_path / "gate_c.freeze.json"; freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    freeze_ref = {"path": freeze_path.name, "sha256": GM.sha256_file(freeze_path)}
    for record in records:
        report = {"corpus_scene": record["scene_id"], "blend_sha256": record["scene_sha256"],
                  "freeze_sha256": freeze_ref["sha256"]}
        report_path = tmp_path / f"report_{record['scene_id']}_{record['backend']}.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        record["report_artifact"] = {"path": report_path.name, "sha256": GM.sha256_file(report_path)}
    payload = {"schema": GM.PAYLOAD_SCHEMA, "row": "c", "instrument": "trio_parity", "scene_sha256": hashes,
               "build_id": "b1", "backend": ["CPU", "GPU"], "settings": {}, "metric": {}, "value": {},
               "threshold": {"roi_pct_max": 5, "ssim_min": .95}, "records": records, "freeze": freeze_ref}
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw = {**payload, "value": {"roi_pct_max": 0.0, "ssim_min": 1.0}, "evidence_path": str(evidence),
           "evidence_sha256": GM.sha256_file(evidence), "dimensions": {"backend": "paired", "scene": "role", "roi": "mask"},
           "subchecks": {"cpu_exit_zero": True, "gpu_exit_zero": True, "pinned_images": True, "non_vacuity": True}, "date": "2026-09-24"}
    row, reasons = GM.compute_row("c", raw, GM.ROW_SPEC["c"], tmp_path)
    assert row["status"] == "red" and any("paired" in reason or "control" in reason for reason in reasons)
    payload["records"][0]["settings"]["gate_c_rois"]["all"] = [0, 0, .5, 1]
    evidence.write_text(json.dumps(payload), encoding="utf-8"); raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("c", raw, GM.ROW_SPEC["c"], tmp_path)
    assert row["status"] == "red"
    payload["records"][0]["settings"]["gate_c_rois"]["all"] = [0, 0, 1, 1]
    payload["records"].pop(); evidence.write_text(json.dumps(payload), encoding="utf-8"); raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, _ = GM.compute_row("c", raw, GM.ROW_SPEC["c"], tmp_path)
    assert row["status"] == "red"


def test_triage_rejects_legacy_detached_snapshot_and_rating_flags(tmp_path):
    blob = tmp_path / "triage.json"; blob.write_bytes(b"triage")
    ref = {"path": blob.name, "sha256": GM.sha256_file(blob)}
    records = [{"kind": "snapshot", "phase": "baseline", "command": "gh issue list", "timestamp": "2026-09-24T00:00:00Z", "reported_total": 2, "issue_ids": [1, 2], "artifact": ref},
               {"kind": "snapshot", "phase": "recheck", "command": "gh issue list", "timestamp": "2026-09-24T01:00:00Z", "reported_total": 2, "issue_ids": [1, 2], "artifact": ref},
               {"kind": "rating", "issue_id": 1, "rater_id": "r1", "signed": True, "severity": "low", "signature": ref},
               {"kind": "rating", "issue_id": 2, "rater_id": "r2", "signed": True, "severity": "low", "signature": ref}]
    evidence = tmp_path / "gate_e.json"
    payload = {"schema": GM.PAYLOAD_SCHEMA, "row": "e", "instrument": "issue_triage", "scene_sha256": [], "build_id": "b1", "backend": [], "settings": {}, "metric": {}, "value": {}, "threshold": {"high_count": 0}, "records": records}
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw = {**payload, "value": {"high_count": 0}, "evidence_path": str(evidence), "evidence_sha256": GM.sha256_file(evidence), "dimensions": {"issue_snapshot": "ids", "ratings": "signed"}, "subchecks": {"snapshot_unique": True, "count_matches_total": True, "all_rated_independently": True, "delta_empty": True}, "date": "2026-09-24"}
    row, reasons = GM.compute_row("e", raw, GM.ROW_SPEC["e"], tmp_path)
    assert row["status"] == "red"


def test_row_b_unmeasured_until_scanner_823(tmp_path):
    raw = {"instrument": "coverage_report", "scene_sha256": [_hex(1)],
           "build_id": "b1", "backend": ["CPU", "GPU"], "settings": {}, "metric": {},
           "value": {"cpu_score": 0.99, "gpu_score": 0.99},
           "threshold": {"cpu_score": 0.95, "gpu_score": 0.95},
           "evidence_path": None, "evidence_sha256": None,
           "dimensions": {"backend": True, "variant": True},
           "scanner_issue_823": {"integrated": False},
           "subchecks": {k: {"pass": True} for k in GM.ROW_SPEC["b"]["required_subchecks"]},
           "date": "2026-09-23"}
    row, reasons = GM.compute_row("b", raw, GM.ROW_SPEC["b"], tmp_path)
    assert row["status"] == "unmeasured"
    assert any("823" in r for r in reasons)


def test_validate_manifest_rejects_green_without_evidence():
    manifest, _ = GM.assemble({})
    manifest["rows"]["a"]["status"] = "green"
    errors = GM.validate_manifest(manifest)
    assert errors


def test_validate_shape_detects_missing_row():
    manifest = {"schema": "pkg278.acceptance_manifest.v1", "rows": {}}
    errors = GM.validate_shape(manifest)
    assert any("missing" in e for e in errors)


# =========================================================================== #
# Harness verdict export + reference-bank channel_ratio gate
# =========================================================================== #

def test_harness_writes_feature_verdicts(tmp_path):
    sys.path.insert(0, str(REPO_ROOT))
    from benchmarks.blender_parity import harness as H

    results = [
        H.FeatureResult("shader_node", "TEX_NOISE", "SUPPORTED", "pass",
                        ssim=0.98, delta_e=1.0, ratio=(1.0, 1.0, 1.0)),
        H.FeatureResult("shader_node", "MIX_RGB", "SUPPORTED", "fail",
                        ssim=0.6, delta_e=15.0, ratio=(1.0, 0.7, 1.3),
                        triage_bucket="TRANSLATION-BUG"),
    ]
    H.write_reports(results, tmp_path)
    payload = json.loads((tmp_path / "feature_verdicts.json").read_text())
    assert payload["schema"] == "pkg278.feature_verdicts.v1"
    assert [v["feature"] for v in payload["verdicts"]] == [
        "shader_node:TEX_NOISE", "shader_node:MIX_RGB"]
    assert payload["verdicts"][1]["triage_bucket"] == "TRANSLATION-BUG"


def test_reference_bank_channel_ratio_gate():
    import numpy as np
    sys.path.insert(0, str(REPO_ROOT))
    from benchmarks.reference_bank import runner as RB

    reference = np.full((8, 8, 3), 0.5, np.float32)
    within = reference.copy()
    within[..., 1] *= 1.04  # +4 % on green -> inside +/-5 %
    worst, ratios = RB.compute_channel_mean_ratio(within, reference)
    assert worst == pytest.approx(0.04, abs=1e-6)
    assert ratios["g"] == pytest.approx(1.04, abs=1e-6)

    outside = reference.copy()
    outside[..., 2] *= 1.10  # +10 % on blue -> outside
    worst2, _ = RB.compute_channel_mean_ratio(outside, reference)
    assert worst2 == pytest.approx(0.10, abs=1e-6)
