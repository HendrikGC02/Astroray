"""Pure fail-closed contracts for pkg278's corpus gate-(c) producer."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib
import numpy as np
import pytest

from benchmarks.blender_parity import harness as H
from benchmarks.blender_parity import scene_library as S


def test_terrace_role_resolves_only_to_the_hdri_corpus_scene():
    roles = S.resolve_gate_c_roles()
    terrace = roles["world_sky:terrace-with-hair"]
    assert terrace["scene_id"] == "world_sky_hdri"
    assert terrace["gate_c"]["expected_curve_count"] == 320
    assert terrace["gate_c"]["expected_curve_point_count"] == 1920
    assert terrace["gate_c"]["rois"]["terrace_hair"] == [0.2424, 0.28, 0.3485, 0.78]
    assert "gate_c" not in S.load_corpus_manifest()["world_sky_sky"]


def test_gate_c_cli_writes_fail_closed_payload_without_blender(tmp_path):
    assert H.run_gate_c_trio(tmp_path) == 1
    payload = json.loads((tmp_path / "instrument.json").read_text(encoding="utf-8"))
    assert payload["records"] == []
    assert "requires an expected 64-hex module SHA-256" in payload["freeze_error"]


def test_entire_trio_freezes_real_declared_metadata():
    frozen = H._gate_c_freeze(S.CORPUS_MANIFEST)
    assert set(frozen) == set(S.GATE_C_ROLES)
    assert frozen["materials_hall"]["non_vacuity"][0]["kind"] == "luminance_std"
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
                    "gate_c": {"rois": {"all": [0, 0, 1, 1]},
                               "non_vacuity": [{"kind": "checker", "roi": "all", "min": .01}]}}
             for role in S.GATE_C_ROLES}
    terrace = roles["world_sky:terrace-with-hair"]
    terrace.update({"curve_count": 319, "curve_point_count": 1920})
    terrace["gate_c"].update({"expected_curve_count": 320, "expected_curve_point_count": 1920})
    roles["textures_mapping"]["gate_c"]["controls"] = [{"kind": "checker_flat", "mask": {}}]
    terrace["gate_c"]["controls"] = [{"kind": "hair_off", "mask": {}}]
    monkeypatch.setattr(S, "resolve_gate_c_roles", lambda _: roles)
    with pytest.raises(ValueError, match="expected_curve_count"):
        H._gate_c_freeze(tmp_path / "manifest.json")


def test_gate_leg_timeout_has_structured_missing_report(monkeypatch):
    def timeout(*args, **kwargs):
        raise H.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(H.subprocess, "run", timeout)
    code, sentinel, report = H._run_gate_leg(Path("blender"), [], {}, 7)
    assert (code, sentinel) == (124, False)
    assert report == {"error": "timeout", "reason": "TIMEOUT after 7s"}


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
            pixels[:] = .2
            mask = Path(args[args.index("--gate-c-mask-out") + 1]); np.save(mask, np.ones((16,16), dtype=np.uint8))
        np.save(out.with_suffix(".npy"), pixels)
        scene = args[args.index("--corpus-scene") + 1]; device = args[args.index("--device") + 1]
        report = {"corpus_scene": scene, "blend_sha256": roles[next(k for k,v in roles.items() if v["scene_id"] == scene)]["scene_sha256"], "freeze_sha256": args[args.index("--gate-c-freeze-sha256") + 1], "requested_device": device, "effective_device": device, "build_id": "b1", "module_path": "C:/candidate/astroray.pyd", "module_sha256": "a" * 64, "addon_path": "C:/candidate/addon/__init__.py", "addon_sha256": "b" * 64, "telemetry": [{"device": -1 if device == "cpu" else 0}], "engine": "CUSTOM_RAYTRACER", "res_x": 16, "res_y": 16, "samples": 4, "resolved_seed": 278, "animated_seed": False, "mutation_receipt": {"kind": args[args.index("--gate-c-control") + 1], "ok": True} if "--gate-c-control" in args else {"kind": "baseline", "ok": True}}
        return 0, True, report
    monkeypatch.setattr(H, "_run_gate_leg", fake_leg)
    assert H.run_gate_c_trio(tmp_path, manifest_path=manifest, build_id="b1", module_sha256="a" * 64) == 0
    payload = json.loads((tmp_path / "instrument.json").read_text(encoding="utf-8"))
    assert all(seen_freeze) and len(payload["records"]) == 12
    assert all("linear_npy" in r and "image" in r and "report_artifact" in r for r in payload["records"])
