"""Pure fail-closed contracts for pkg278's corpus gate-(c) producer."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from benchmarks.blender_parity import harness as H
from benchmarks.blender_parity import render_leg as R
from benchmarks.blender_parity import scene_library as S
from scripts import gate_manifest as GM


def _artifact(tmp_path, name, data):
    path = tmp_path / name
    if isinstance(data, np.ndarray):
        np.save(path, data)
    else:
        path.write_bytes(data)
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _valid_gate_c_records(tmp_path):
    hashes = {role: hashlib.sha256(role.encode()).hexdigest() for role in S.GATE_C_ROLES}
    controls = {
        "materials_hall": [],
        "textures_mapping": [{"kind": "checker_flat", "object": "TexChecker", "material": "TexCheckerMat", "node": "GateCWorkshopChecker", "mask": {"kind": "object_polygon"}}],
        "world_sky:terrace-with-hair": [{"kind": "hair_off", "object": "TerraceHair", "mask": {"kind": "curves"}}, {"kind": "hdri_off", "world": "W", "node": "GateCTerraceEnvironment", "mask": {"kind": "sky_rays"}}],
    }
    probes = {"materials_hall": [], "textures_mapping": [{"kind": "checker", "min_delta": .05, "min_coverage": .02}], "world_sky:terrace-with-hair": [{"kind": "hair", "min_delta": .05, "min_coverage": .02}, {"kind": "hdri", "min_delta": .05, "min_coverage": .02}]}
    freeze = {"build_id": "build-1", "module_sha256": "a" * 64, "addon_sha256": "b" * 64, "roles": {}}
    for role in S.GATE_C_ROLES:
        freeze["roles"][role] = {"scene_id": role, "scene_sha256": hashes[role], "settings": {"res_x": 16, "res_y": 16, "samples": 4}, "rois": {"all": [0, 0, 1, 1]}, "non_vacuity": probes[role], "controls": controls[role], "seed": 278, "expected_curve_count": 320 if role.endswith("hair") else None, "expected_curve_point_count": 1920 if role.endswith("hair") else None}
    freeze_ref = _artifact(tmp_path, "freeze.json", json.dumps(freeze).encode())
    freeze_sha = freeze_ref["sha256"]
    image = _artifact(tmp_path, "image.png", b"display-only")
    records = []
    for role in S.GATE_C_ROLES:
        bindings = {}
        for control in controls[role]:
            if control["kind"] == "checker_flat": bindings[control["kind"]] = {"object": "TexChecker", "object_type": "MESH", "material": "TexCheckerMat", "node": "GateCWorkshopChecker", "node_type": "ShaderNodeTexChecker"}
            elif control["kind"] == "hair_off": bindings[control["kind"]] = {"object": "TerraceHair", "object_type": "CURVES", "curve_count": 320, "curve_point_count": 1920}
            else: bindings[control["kind"]] = {"world": "W", "node": "GateCTerraceEnvironment", "node_type": "ShaderNodeTexEnvironment"}
        for backend in ("CPU", "GPU"):
            for control in [{"kind": "baseline"}] + controls[role]:
                kind = control["kind"]
                pixels = np.full((16, 16, 3), .5 if kind == "baseline" else .3, np.float32)
                if role == "textures_mapping":
                    pixels.fill(.5)
                    if kind == "baseline":
                        pixels[:, :8] = .7
                        pixels[:, 8:] = .3
                linear = _artifact(tmp_path, f"{role.replace(':', '_')}_{backend}_{kind}.npy", pixels)
                report = {"corpus_scene": role, "blend_sha256": hashes[role], "freeze_sha256": freeze_sha, "build_id": "build-1", "requested_device": backend.lower(), "effective_device": backend.lower(), "engine": "CUSTOM_RAYTRACER", "res_x": 16, "res_y": 16, "samples": 4, "resolved_seed": 278, "animated_seed": False, "module_sha256": "a" * 64, "addon_sha256": "b" * 64, "blender_version": "5.2.0", "module_path": "C:/build/astroray.pyd", "addon_path": "C:/build/addon/__init__.py", "telemetry": [], "bindings": bindings}
                if kind == "baseline":
                    report["mutation_receipt"] = {"kind": "baseline", "ok": True}
                elif kind == "checker_flat":
                    report["mutation_receipt"] = {"kind": kind, "ok": True, "object": "TexChecker", "material": "TexCheckerMat", "node": "GateCWorkshopChecker", "before": [[0, 0, 0, 1], [1, 1, 1, 1]], "after": [[.5, .5, .5, 1], [.5, .5, .5, 1]]}
                elif kind == "hair_off":
                    report["mutation_receipt"] = {"kind": kind, "ok": True, "object": "TerraceHair", "type": "CURVES", "was_hide_render": False, "after_hide_render": True}
                else:
                    report["mutation_receipt"] = {"kind": kind, "ok": True, "world": "W", "node": "GateCTerraceEnvironment", "image": "sky.hdr", "after_image": None}
                non_vacuity = [{"kind": p["kind"], "value": .2, "coverage": 1.0} for p in probes[role]]
                for probe in non_vacuity:
                    if probe["kind"] == "checker":
                        probe.update({"positive_coverage": .5, "negative_coverage": .5})
                record = {"kind": "f12_run", "control": kind, "role": role, "scene_id": role, "scene_sha256": hashes[role], "backend": backend, "build_id": "build-1", "exit_code": 0, "sentinel": "PKG119B_LEG", "image": image, "linear_npy": linear, "settings": {"res_x": 16, "res_y": 16, "samples": 4, "gate_c_rois": {"all": [0, 0, 1, 1]}, "gate_c_probes": probes[role]}, "non_vacuity": non_vacuity}
                if kind != "baseline":
                    mask = _artifact(tmp_path, f"{role.replace(':', '_')}_{backend}_{kind}_mask.npy", np.ones((16, 16), np.uint8))
                    record["feature_mask"] = mask
                    report["mask_receipt"] = {"control": kind, "kind": control["mask"]["kind"], "path": str((tmp_path / mask["path"]).resolve()), "sha256": mask["sha256"], "shape": [16, 16], "pixels": 256}
                report_ref = _artifact(tmp_path, f"{role.replace(':', '_')}_{backend}_{kind}.json", json.dumps(report).encode())
                record["report_artifact"] = report_ref
                record["leg_report"] = report
                stdout = f"{H.SENTINEL} REPORT {json.dumps(report)}\n{H.SENTINEL} PASS\n"
                record["stdout_artifact"] = _artifact(
                    tmp_path, f"{role.replace(':', '_')}_{backend}_{kind}_stdout.log", stdout.encode())
                record["stderr_artifact"] = _artifact(
                    tmp_path, f"{role.replace(':', '_')}_{backend}_{kind}_stderr.log", b"")
                record["execution_artifact"] = _artifact(
                    tmp_path, f"{role.replace(':', '_')}_{backend}_{kind}_execution.json",
                    json.dumps({"command": ["fake-blender"], "exit_code": 0}).encode())
                records.append(record)
    return records, list(hashes.values()), freeze_ref


def test_terrace_role_resolves_only_to_the_hdri_corpus_scene():
    roles = S.resolve_gate_c_roles()
    terrace = roles["world_sky:terrace-with-hair"]
    assert terrace["scene_id"] == "world_sky_hdri"
    assert terrace["gate_c"]["expected_curve_count"] == 320
    assert terrace["gate_c"]["expected_curve_point_count"] == 1920
    assert terrace["gate_c"]["rois"]["terrace_hair"] == [0.2424, 0.28, 0.3485, 0.78]
    assert "gate_c" not in S.load_corpus_manifest()["world_sky_sky"]


def test_sky_ray_mask_uses_integer_ranges_for_fractional_frozen_roi():
    rows, columns = R._gate_c_mask_pixel_ranges([.45, .04, .62, .22], (10, 10))
    assert list(rows) == [0, 1]
    assert list(columns) == [4, 5]


def test_default_reference_discovery_is_corpus_backed_with_historical_aliases():
    corpus = S.load_corpus_manifest()
    assert set(S.REFERENCE_SCENES) == set(corpus)
    assert set(S.HISTORICAL_EXPORT_SCENES) == {
        "cornell_interior", "material_zoo", "hdri_exterior_hair"}
    assert all(row["astroray_leg"] == "addon" for row in S.REFERENCE_SCENES.values())


def test_gate_c_freeze_loader_returns_json_roles_before_graph_access(tmp_path):
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps({"roles": {"workshop": {"scene_id": "textures_mapping"}}}), encoding="utf-8")
    digest = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    assert R._load_gate_c_freeze(freeze_path, digest)["roles"]["workshop"]["scene_id"] == "textures_mapping"
    with pytest.raises(ValueError, match="hash mismatch"):
        R._load_gate_c_freeze(freeze_path, "0" * 64)


def test_reducer_recomputes_valid_paired_control_receipts(tmp_path):
    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    errors, value, subchecks = GM._validate_c(records, tmp_path, hashes, "build-1", freeze)
    assert not errors
    assert value == {"roi_pct_max": 0.0, "ssim_min": 1.0}
    assert all(subchecks.values())


def test_reducer_rejects_observed_seed_or_mask_receipt_mismatch(tmp_path):
    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    record = next(item for item in records if item["control"] == "checker_flat")
    report_path = tmp_path / record["report_artifact"]["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["resolved_seed"] = 0
    report_path.write_text(json.dumps(report), encoding="utf-8")
    record["report_artifact"]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    errors, _, _ = GM._validate_c(records, tmp_path, hashes, "build-1", freeze)
    assert any("settings/seed" in error for error in errors)

    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    record = next(item for item in records if item["control"] == "checker_flat")
    report_path = tmp_path / record["report_artifact"]["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["mask_receipt"]["sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    record["report_artifact"]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    errors, _, _ = GM._validate_c(records, tmp_path, hashes, "build-1", freeze)
    assert any("mask receipt" in error for error in errors)

    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    record = next(item for item in records if item["control"] == "checker_flat")
    report_path = tmp_path / record["report_artifact"]["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["mask_receipt"]["pixels"] = 0
    report_path.write_text(json.dumps(report), encoding="utf-8")
    record["report_artifact"]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    errors, _, _ = GM._validate_c(records, tmp_path, hashes, "build-1", freeze)
    assert any("mask receipt" in error for error in errors)

    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    control = next(item for item in records if item["control"] == "checker_flat")
    baseline = next(item for item in records if item["role"] == control["role"] and item["backend"] == control["backend"] and item["control"] == "baseline")
    control_path = tmp_path / control["linear_npy"]["path"]
    control_path.write_bytes((tmp_path / baseline["linear_npy"]["path"]).read_bytes())
    control["linear_npy"]["sha256"] = hashlib.sha256(control_path.read_bytes()).hexdigest()
    errors, _, _ = GM._validate_c(records, tmp_path, hashes, "build-1", freeze)
    assert any("non-vacuity witness failed" in error for error in errors)


def _raw_gate_c_payload(records, hashes, freeze):
    return {
        "schema": GM.PAYLOAD_SCHEMA,
        "row": "c",
        "instrument": "trio_parity",
        "scene_sha256": hashes,
        "build_id": "build-1",
        "backend": ["CPU", "GPU"],
        "settings": {},
        "metric": {"source": "raw_c_capture"},
        "value": {},
        "threshold": {"roi_pct_max": 5.0, "ssim_min": 0.95},
        "records": records,
        "freeze": freeze,
    }


def _adapted_valid_red_c(tmp_path):
    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    for record in records:
        if record["control"] == "hdri_off":
            control_path = tmp_path / record["linear_npy"]["path"]
            np.save(control_path, np.zeros((16, 16, 3), np.float32))
            record["linear_npy"]["sha256"] = hashlib.sha256(control_path.read_bytes()).hexdigest()
            baseline = next(item for item in records if item["role"] == record["role"]
                            and item["backend"] == record["backend"] and item["control"] == "baseline")
            next(probe for probe in baseline["non_vacuity"] if probe["kind"] == "hdri").update(
                {"value": .5, "coverage": 1.0}
            )
    gpu_checker = next(item for item in records if item["role"] == "textures_mapping"
                       and item["backend"] == "GPU" and item["control"] == "checker_flat")
    gpu_baseline = next(item for item in records if item["role"] == "textures_mapping"
                        and item["backend"] == "GPU" and item["control"] == "baseline")
    control_path = tmp_path / gpu_checker["linear_npy"]["path"]
    control_path.write_bytes((tmp_path / gpu_baseline["linear_npy"]["path"]).read_bytes())
    gpu_checker["linear_npy"]["sha256"] = hashlib.sha256(control_path.read_bytes()).hexdigest()
    next(probe for probe in gpu_baseline["non_vacuity"] if probe["kind"] == "checker").update(
        {"value": 0.0, "coverage": 0.0, "positive_coverage": 0.0, "negative_coverage": 0.0}
    )
    raw_path = tmp_path / "instrument.json"
    raw_path.write_text(json.dumps(_raw_gate_c_payload(records, hashes, freeze)), encoding="utf-8")
    return raw_path


def _manifest_with_c_row(row, tmp_path):
    manifest, _ = GM.assemble({"c": row}, tmp_path)
    return manifest


def test_adapter_accepts_valid_measured_red_with_black_hdri_control(tmp_path):
    raw_path = _adapted_valid_red_c(tmp_path)
    row = GM.load_instruments(None, {"c": raw_path})["c"]
    assert row["value"]["roi_pct_max"] == pytest.approx(0.0)
    assert row["value"]["ssim_min"] == pytest.approx(1.0)
    assert any("textures_mapping/GPU checker non-vacuity witness failed" in failure
               for failure in row["measurement_failures"])
    computed, reasons = GM.compute_row("c", row, GM.ROW_SPEC["c"], tmp_path)
    assert computed["status"] == "red"
    assert any("textures_mapping/GPU checker non-vacuity witness failed" in reason for reason in reasons)
    assert not GM.validate_manifest(_manifest_with_c_row(row, tmp_path), tmp_path)


def test_gate_manifest_cli_adapts_c_from_external_working_directory(tmp_path):
    raw_path = _adapted_valid_red_c(tmp_path)
    external_cwd = tmp_path / "external-cwd"
    external_cwd.mkdir()
    out_path = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(GM.REPO_ROOT / "scripts" / "gate_manifest.py"),
         "--instrument", f"c={raw_path}", "--out", str(out_path), "--json"],
        cwd=external_cwd, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(out_path.read_text(encoding="utf-8"))
    assert manifest["rows"]["c"]["status"] == "red"
    assert not GM.validate_manifest(manifest, tmp_path)


@pytest.mark.parametrize("field", ["stdout_artifact", "stderr_artifact", "execution_artifact"])
def test_adapter_rejects_missing_raw_execution_artifact(tmp_path, field):
    raw_path = _adapted_valid_red_c(tmp_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    for record in payload["records"]:
        (tmp_path / record[field]["path"]).unlink()
    row = GM.adapt_c_instrument(raw_path)
    manifest = _manifest_with_c_row(row, tmp_path)
    assert manifest["rows"]["c"]["status"] == "red"
    assert GM.validate_manifest(manifest, tmp_path)


@pytest.mark.parametrize("tamper", ["npy", "mask", "report", "seed", "identity", "metrics", "digest"])
def test_adapter_rejects_tampered_measured_red_evidence(tmp_path, tamper):
    raw_path = _adapted_valid_red_c(tmp_path)
    row = GM.adapt_c_instrument(raw_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    if tamper == "npy":
        record = next(item for item in payload["records"] if item["control"] == "hdri_off")
        np.save(tmp_path / record["linear_npy"]["path"], np.ones((16, 16, 3), np.float32))
    elif tamper == "mask":
        record = next(item for item in payload["records"] if item["control"] == "hdri_off")
        np.save(tmp_path / record["feature_mask"]["path"], np.zeros((16, 16), np.uint8))
    elif tamper == "report":
        record = next(item for item in payload["records"] if item["control"] == "hdri_off")
        report_path = tmp_path / record["report_artifact"]["path"]
        report = json.loads(report_path.read_text(encoding="utf-8")); report["engine"] = "OTHER"
        report_path.write_text(json.dumps(report), encoding="utf-8")
    elif tamper == "seed":
        record = next(item for item in payload["records"] if item["control"] == "hdri_off")
        report_path = tmp_path / record["report_artifact"]["path"]
        report = json.loads(report_path.read_text(encoding="utf-8")); report["resolved_seed"] = 0
        report_path.write_text(json.dumps(report), encoding="utf-8")
        record["report_artifact"]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        raw_path.write_text(json.dumps(payload), encoding="utf-8"); row = GM.adapt_c_instrument(raw_path)
    elif tamper == "identity":
        payload["records"][0]["scene_id"] = "wrong-scene"
        raw_path.write_text(json.dumps(payload), encoding="utf-8"); row = GM.adapt_c_instrument(raw_path)
    elif tamper == "metrics":
        record = next(item for item in payload["records"] if item["control"] == "baseline")
        record["rois"] = [{"name": "all", "ratio": {"r": 0.5, "g": 1.0, "b": 1.0}, "ratio_max": 0.5, "ssim": 1.0}]
        raw_path.write_text(json.dumps(payload), encoding="utf-8"); row = GM.adapt_c_instrument(raw_path)
    else:
        row["evidence_sha256"] = "0" * 64
    manifest = _manifest_with_c_row(row, tmp_path)
    assert manifest["rows"]["c"]["status"] == "red"
    assert GM.validate_manifest(manifest, tmp_path)


def test_reducer_rejects_one_sided_checker_brightness_change(tmp_path):
    records, hashes, freeze = _valid_gate_c_records(tmp_path)
    baseline = next(record for record in records if record["role"] == "textures_mapping"
                    and record["backend"] == "CPU" and record["control"] == "baseline")
    baseline_path = tmp_path / baseline["linear_npy"]["path"]
    np.save(baseline_path, np.full((16, 16, 3), .7, np.float32))
    baseline["linear_npy"]["sha256"] = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    checker = next(probe for probe in baseline["non_vacuity"] if probe["kind"] == "checker")
    checker.update({"value": .2, "coverage": 1.0, "positive_coverage": 1.0,
                    "negative_coverage": 0.0})
    errors, _, _ = GM._validate_c(records, tmp_path, hashes, "build-1", freeze)
    assert any("checker non-vacuity" in error for error in errors)


def test_gate_c_cli_writes_fail_closed_payload_without_blender(tmp_path):
    assert H.run_gate_c_trio(tmp_path) == 1
    payload = json.loads((tmp_path / "instrument.json").read_text(encoding="utf-8"))
    assert payload["records"] == []
    assert "requires an expected 64-hex module SHA-256" in payload["freeze_error"]


def test_entire_trio_freezes_real_declared_metadata():
    frozen = H._gate_c_freeze(S.CORPUS_MANIFEST)
    assert set(frozen) == set(S.GATE_C_ROLES)
    assert frozen["materials_hall"]["non_vacuity"] == []
    assert frozen["materials_hall"]["seed"] == 278
    assert frozen["textures_mapping"]["rois"]["workshop_checker"] == [
        0.2912, 0.3603, 0.4079, 0.4804]
    assert frozen["textures_mapping"]["controls"][0]["kind"] == "checker_flat"
    assert {c["kind"] for c in frozen["world_sky:terrace-with-hair"]["controls"]} == {"hair_off", "hdri_off"}
    assert frozen["world_sky:terrace-with-hair"]["scene_id"] == "world_sky_hdri"


def test_duplicate_logical_terrace_role_is_rejected(tmp_path):
    manifest = json.loads(S.CORPUS_MANIFEST.read_text(encoding="utf-8"))
    manifest["scenes"]["world_sky_sky"]["gate_c"] = {
        "role": "world_sky:terrace-with-hair"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="world_sky:terrace-with-hair"):
        S.resolve_gate_c_roles(path)


def test_terrace_freeze_requires_reopened_curves_census(monkeypatch, tmp_path):
    roles = {role: {"scene_id": role, "blend_path": "x.blend", "sha256": "a" * 64,
                    "assets": [], "settings": {"res_x": 16, "res_y": 16, "samples": 4},
                    "gate_c": {"rois": {"all": [0, 0, 1, 1]}, "seed": 278,
                               "non_vacuity": [{"kind": "checker", "roi": "all", "min": .01}]}}
             for role in S.GATE_C_ROLES}
    terrace = roles["world_sky:terrace-with-hair"]
    terrace.update({"curve_count": 319, "curve_point_count": 1920})
    terrace["gate_c"].update({"expected_curve_count": 320, "expected_curve_point_count": 1920})
    roles["textures_mapping"]["gate_c"]["controls"] = [{"kind": "checker_flat", "object": "card", "material": "mat", "node": "node", "mask": {"kind": "object_polygon"}}]
    terrace["gate_c"]["controls"] = [{"kind": "hair_off", "object": "hair", "mask": {"kind": "curves"}}]
    monkeypatch.setattr(S, "resolve_gate_c_roles", lambda _: roles)
    with pytest.raises(ValueError, match="expected_curve_count"):
        H._gate_c_freeze(tmp_path / "manifest.json")


def test_gate_leg_timeout_has_structured_missing_report(monkeypatch):
    def timeout(*args, **kwargs):
        raise H.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(H.subprocess, "run", timeout)
    code, sentinel, report = H._run_gate_leg(Path("blender"), [], {}, 7)
    assert (code, sentinel) == (124, False)
    assert report["error"] == "timeout"
    assert report["reason"] == "TIMEOUT after 7s"
    assert report["_gate_leg_execution"]["exit_code"] == 124


def test_gate_leg_parses_one_glued_sentinel_report_and_rejects_duplicates(monkeypatch):
    expected = {"corpus_scene": "materials_hall", "resolved_seed": 278}

    class Process:
        returncode = 0
        stdout = "warning text truncated" + H.SENTINEL + " REPORT " + json.dumps(expected) + "\n" + H.SENTINEL + " PASS"
        stderr = "native warning"

    monkeypatch.setattr(H.subprocess, "run", lambda *args, **kwargs: Process())
    code, sentinel, report = H._run_gate_leg(Path("blender"), ["--corpus-scene", "materials_hall"], {}, 7)
    assert (code, sentinel) == (0, True)
    assert report["corpus_scene"] == "materials_hall"
    assert report["_gate_leg_execution"]["stdout"] == Process.stdout
    duplicate = Process.stdout + H.SENTINEL + " REPORT " + json.dumps(expected)
    assert H._parse_gate_leg_report(duplicate)[0] == {}
    assert "expected one" in H._parse_gate_leg_report(duplicate)[1]


def test_checker_paired_probe_rejects_one_sided_brightness_shift():
    baseline = np.full((8, 8, 3), .8, np.float32)
    control = np.full((8, 8, 3), .5, np.float32)
    probe = H._gate_c_paired_probe(baseline, control, np.ones((8, 8), np.uint8),
                                   {"kind": "checker", "min_delta": .05, "min_coverage": .02})
    assert probe["coverage"] == 1.0 and probe["positive_coverage"] == 1.0
    assert probe["negative_coverage"] == 0.0 and not probe["ok"]


def test_manifest_duplicate_scene_id_is_rejected_before_render(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"scenes":{"x":{},"x":{}}}', encoding="utf-8")
    try:
        S.load_corpus_manifest(manifest)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate manifest keys must fail closed")


def test_fake_six_leg_capture_freezes_before_spawn_and_keeps_npy_png(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"; manifest.write_text("{}", encoding="utf-8")
    roles = {}
    for role, scene in zip(S.GATE_C_ROLES, ("gallery", "workshop", "terrace")):
        probes = []
        controls = []
        if role == "textures_mapping":
            probes = [{"kind": "checker", "roi": "all", "min_delta": .01, "min_coverage": .01}]
            controls = [{"kind": "checker_flat", "mask": {}}]
        if role.endswith("terrace-with-hair"):
            probes = [{"kind": "hdri", "roi": "all", "min_delta": .01, "min_coverage": .01}, {"kind": "hair", "roi": "all", "min_delta": .01, "min_coverage": .01}]
            controls = [{"kind": "hdri_off", "mask": {}}, {"kind": "hair_off", "mask": {}}]
        roles[role] = {"scene_id": scene, "blend_path": "x.blend", "scene_sha256": hashlib.sha256(scene.encode()).hexdigest(), "assets": [], "settings": {"res_x": 16, "res_y": 16, "samples": 4}, "rois": {"all": [0,0,1,1], "bg": [0,0,.5,1]}, "non_vacuity": probes, "controls": controls}
    monkeypatch.setattr(H, "_gate_c_freeze", lambda _: roles)
    monkeypatch.setattr(H, "_find_blender", lambda: Path("fake-blender"))
    seen_freeze = []
    def fake_leg(_, args, __, ___):
        freeze = Path(args[args.index("--gate-c-freeze") + 1]); seen_freeze.append(freeze.is_file())
        out = Path(args[args.index("--out") + 1]); out.parent.mkdir(parents=True, exist_ok=True)
        pixels = np.full((16,16,3), .5, dtype=np.float32); pixels[:,8:] = .8
        if "--gate-c-control" in args:
            pixels[:] = .65
            mask = Path(args[args.index("--gate-c-mask-out") + 1]); np.save(mask, np.ones((16,16), dtype=np.uint8))
        np.save(out.with_suffix(".npy"), pixels)
        scene = args[args.index("--corpus-scene") + 1]; device = args[args.index("--device") + 1]
        report = {"corpus_scene": scene, "blend_sha256": roles[next(k for k,v in roles.items() if v["scene_id"] == scene)]["scene_sha256"], "freeze_sha256": args[args.index("--gate-c-freeze-sha256") + 1], "requested_device": device, "effective_device": device, "build_id": "b1", "module_path": "C:/candidate/astroray.pyd", "module_sha256": "a" * 64, "addon_path": "C:/candidate/addon/__init__.py", "addon_sha256": hashlib.sha256((H._REPO_ROOT / "blender_addon" / "__init__.py").read_bytes()).hexdigest(), "telemetry": [{"device": -1 if device == "cpu" else 0}], "engine": "CUSTOM_RAYTRACER", "res_x": 16, "res_y": 16, "samples": 4, "resolved_seed": 278, "animated_seed": False, "blender_version": "5.2.0", "bindings": {}, "mutation_receipt": {"kind": args[args.index("--gate-c-control") + 1], "ok": True} if "--gate-c-control" in args else {"kind": "baseline", "ok": True}}
        if "--gate-c-control" in args:
            report["mask_receipt"] = {"control": args[args.index("--gate-c-control") + 1]}
        report["_gate_leg_execution"] = {"command": ["fake-blender", *args], "exit_code": 0,
                                          "stdout": "raw stdout", "stderr": "raw stderr"}
        return 0, True, report
    monkeypatch.setattr(H, "_run_gate_leg", fake_leg)
    assert H.run_gate_c_trio(tmp_path, manifest_path=manifest, build_id="b1", module_sha256="a" * 64) == 0
    payload = json.loads((tmp_path / "instrument.json").read_text(encoding="utf-8"))
    assert all(seen_freeze) and len(payload["records"]) == 12
    assert all("linear_npy" in r and "image" in r and "report_artifact" in r for r in payload["records"])
    assert all("execution_artifact" in r and "stdout_artifact" in r and "stderr_artifact" in r
               for r in payload["records"])
