"""Pure fail-closed contracts for pkg278's corpus gate-(c) producer."""
from __future__ import annotations

import json
from pathlib import Path

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
    payload = json.loads((tmp_path / "gate_c.json").read_text(encoding="utf-8"))
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
