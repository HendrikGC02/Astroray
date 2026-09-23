"""Pure fail-closed contracts for pkg278's corpus gate-(c) producer."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib
import numpy as np

from benchmarks.blender_parity import harness as H
from benchmarks.blender_parity import scene_library as S


def test_current_corpus_refuses_world_variants_as_terrace_hair():
    try:
        S.resolve_gate_c_roles()
    except ValueError as exc:
        assert "world_sky:terrace-with-hair" in str(exc)
    else:
        raise AssertionError("world_sky_hdri/world_sky_sky must not satisfy the terrace-hair role")


def test_gate_c_cli_writes_fail_closed_payload_without_blender(tmp_path):
    assert H.run_gate_c_trio(tmp_path) == 1
    payload = json.loads((tmp_path / "instrument.json").read_text(encoding="utf-8"))
    assert payload["records"] == []
    assert "world_sky:terrace-with-hair" in payload["freeze_error"]


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
        probes = [{"kind": "checker", "roi": "all", "min": .01}]
        if role.endswith("terrace-with-hair"):
            probes = [{"kind": "hdri", "roi": "all", "min": .01}, {"kind": "hair", "roi": "all", "background_roi": "bg", "min": .01}]
        roles[role] = {"scene_id": scene, "blend_path": "x.blend", "scene_sha256": hashlib.sha256(scene.encode()).hexdigest(), "assets": [], "settings": {"res_x": 16, "res_y": 16, "samples": 4}, "rois": {"all": [0,0,1,1], "bg": [0,0,.5,1]}, "non_vacuity": probes}
    monkeypatch.setattr(H, "_gate_c_freeze", lambda _: roles)
    monkeypatch.setattr(H, "_find_blender", lambda: Path("fake-blender"))
    seen_freeze = []
    def fake_leg(_, args, __, ___):
        freeze = Path(args[args.index("--gate-c-freeze") + 1]); seen_freeze.append(freeze.is_file())
        out = Path(args[args.index("--out") + 1]); out.parent.mkdir(parents=True, exist_ok=True)
        pixels = np.full((16,16,3), .5, dtype=np.float32); pixels[:,8:] = .8
        np.save(out.with_suffix(".npy"), pixels)
        scene = args[args.index("--corpus-scene") + 1]; device = args[args.index("--device") + 1]
        report = {"corpus_scene": scene, "blend_sha256": roles[next(k for k,v in roles.items() if v["scene_id"] == scene)]["scene_sha256"], "freeze_sha256": args[args.index("--gate-c-freeze-sha256") + 1], "requested_device": device, "effective_device": device, "build_id": "b1", "module_path": "C:/candidate/astroray.pyd", "module_sha256": "a" * 64, "addon_path": "C:/candidate/addon/__init__.py", "addon_sha256": "b" * 64, "telemetry": [{"device": -1 if device == "cpu" else 0}], "engine": "CUSTOM_RAYTRACER", "res_x": 16, "res_y": 16, "samples": 4}
        return 0, True, report
    monkeypatch.setattr(H, "_run_gate_leg", fake_leg)
    assert H.run_gate_c_trio(tmp_path, manifest_path=manifest, build_id="b1", module_sha256="a" * 64) == 0
    payload = json.loads((tmp_path / "instrument.json").read_text(encoding="utf-8"))
    assert all(seen_freeze) and len(payload["records"]) == 6
    assert all("linear_npy" in r and "image" in r and "report_artifact" in r for r in payload["records"])
