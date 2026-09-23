"""Pure contract tests for the real-Blender gate-(a) producer/reducer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


DRV = _load("pkg278_gate_a_driver", "benchmarks/viewport_parity/blender_driver.py")
GM = _load("pkg278_gate_a_manifest", "scripts/gate_manifest.py")
PIXELS = Path(tempfile.mkdtemp(prefix="pkg278_gate_a_"))
PNG = b"\x89PNG\r\n\x1a\nfixture"
for name in ("pre.png", "post.png"):
    (PIXELS / name).write_bytes(PNG)


def _sha(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


def _capture(scene, triangles, kind, batch, *, broken=None):
    raw, edits = [], []
    base = (batch + 1) * 10_000_000
    for i in range(100):
        g, pub, t = i + 1, i + 1, base + i * 1000
        edits.append({"event_id": i + 1, "dispatch_ns": t, "generation": g,
                      "epoch": 7, "input_floor": g, "input_fingerprint": [i],
                      "kind": kind, "bound": True})
        raw += [
            {"name": "viewport_pixels", "generation": None, "epoch": None, "t_ns": t - 1, "extra": {"event_id": i + 1, "label": "pre", "path": str(PIXELS / "pre.png"), "sha256": hashlib.sha256(PNG).hexdigest()}},
            {"name": "input_applied", "generation": None, "epoch": None, "t_ns": t + 0, "extra": {"event_id": i + 1, "fingerprint": [i]}},
            {"name": "request", "generation": g, "epoch": 7, "t_ns": t + 1, "extra": {}},
            {"name": "edit_bound", "generation": g, "epoch": 7, "t_ns": t + 1, "extra": {"event_id": i + 1, "input_floor": g, "fingerprint": [i]}},
            {"name": "mailbox_enqueue", "generation": g, "epoch": 7, "t_ns": t + 2, "extra": {"pub_id": pub}},
            {"name": "mailbox_dequeue", "generation": g, "epoch": 7, "t_ns": t + 3, "extra": {"pub_id": pub}},
            {"name": "texture_upload_end", "generation": g, "epoch": 7, "t_ns": t + 4, "extra": {"pub_id": pub}},
            {"name": "post_pixel_present", "generation": g, "epoch": 7, "t_ns": t + 5, "extra": {"pub_id": pub, "input_floor": g}},
            {"name": "viewport_pixels", "generation": g, "epoch": 7, "t_ns": t + 6, "extra": {"event_id": i + 1, "label": "post", "path": str(PIXELS / "post.png"), "sha256": hashlib.sha256(PNG).hexdigest()}},
        ]
    raw += [{"name": "cancel_request", "generation": 100, "epoch": 7, "t_ns": base + 100_010, "extra": {}},
            {"name": "idle_ack", "generation": 100, "epoch": 7, "t_ns": base + 100_020, "extra": {}},
            {"name": "idle_drain", "generation": 100, "epoch": 7, "t_ns": base + 100_030, "extra": {}}]
    if broken == "wrong_generation": raw[4]["generation"] = 999
    if broken == "no_present": raw = [e for e in raw if e["name"] != "post_pixel_present"]
    if broken == "no_ack": raw = [e for e in raw if e["name"] != "idle_ack"]
    if broken == "stale_after_ack":
        raw.append({"name": "post_pixel_present", "generation": 1, "epoch": 7,
                    "t_ns": base + 100_025, "extra": {"pub_id": 1, "input_floor": 100}})
    observed = {"engine": "CUSTOM_RAYTRACER", "requested_device": "gpu", "actual_gpu_devices": [0], "denoise_enabled": False,
                "addon": {"path": "addon.py", "sha256": _sha("addon")},
                "module": {"path": "module.pyd", "sha256": _sha("module")}}
    return {"scene_sha256": scene, "workload": {"path": f"{scene}.blend", "sha256": scene, "triangles": triangles,
                                                    "freeze": {"blend_sha256": scene, "observed_triangles": triangles}},
            "edit_kind": kind, "batch": batch, "backend": "GPU", "denoise_enabled": False,
            "observed_runtime": observed, "truncated": False, "raw_events": raw, "edits": edits}


def _payload(broken=None):
    scenes = [_sha("10k"), _sha("100k")]
    records = [_capture(scene, tri, kind, batch,
                        broken=broken if scene == scenes[0] and kind == "camera" and batch == 0 else None)
               for scene, tri in zip(scenes, (10000, 100000))
               for kind in ("camera", "material") for batch in range(3)]
    return {"schema": "pkg278.instrument.v2", "row": "a", "instrument": "viewport_latency",
            "scene_sha256": scenes, "build_id": "test-build", "backend": ["GPU"],
            "settings": {"denoise_enabled": False}, "metric": {},
            "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                          "cancel_p99_ms": 300, "stale_frames_after_ack": 0}, "records": records}


def test_gate_a_reducer_requires_ordered_actual_generation_chain():
    cap = _capture(_sha("s"), 10000, "camera", 0)
    result = DRV.reduce_gate_a_capture(cap["raw_events"], cap["edits"])
    assert result["complete"] and len(result["rows"]) == 100
    bad = _capture(_sha("s"), 10000, "camera", 0, broken="wrong_generation")
    assert DRV.reduce_gate_a_capture(bad["raw_events"], bad["edits"])["errors"]


def test_recorder_setup_executes_json_booleans_as_python_config():
    cfg = {"event_class": "camera", "gate_a": True, "evidence_dir": None}
    namespace = {}
    exec(DRV._recorder_setup(cfg).split(DRV._recorder_src(), 1)[0], namespace)
    assert namespace["_PKG241_CONFIG"] == cfg


def test_gate_a_requires_native_gpu_render_telemetry():
    assert DRV._actual_gpu_devices([
        {"name": "render_device", "extra": {"device": 0}},
        {"name": "render_device", "extra": {"device": 0}},
    ]) == [0]
    with pytest.raises(RuntimeError):
        DRV._actual_gpu_devices([])
    with pytest.raises(RuntimeError):
        DRV._actual_gpu_devices([{"name": "render_device", "extra": {"device": -1}}])


def test_recorder_uses_blender_52_screenshot_signature():
    source = (ROOT / "benchmarks/viewport_parity/blender_recorder.py").read_text(encoding="utf-8")
    assert "bpy.ops.screen.screenshot(filepath=path)" in source
    assert "bpy.ops.screen.screenshot(filepath=path, full=False)" not in source
    assert 'raw("viewport_pixels", generation, epoch,' in source
    assert '_capture_viewport("post", pending.get("generation"), pending.get("epoch"))' in source


def test_gate_a_reducer_rejects_stale_after_ack_and_missing_ack_or_present():
    for failure in ("stale_after_ack", "no_ack", "no_present"):
        cap = _capture(_sha("s"), 10000, "material", 0, broken=failure)
        assert DRV.reduce_gate_a_capture(cap["raw_events"], cap["edits"])["errors"]


def test_gate_a_stale_check_deduplicates_redraws_and_preserves_late_old_publication():
    cap = _capture(_sha("s"), 10000, "camera", 0)
    raw = cap["raw_events"]
    # A second UI redraw of an already-presented publication before ACK does
    # not create another post-ACK stale frame.
    raw.append({"name": "post_pixel_present", "generation": 1, "epoch": 7,
                "t_ns": 10_050_000, "extra": {"pub_id": 1}})
    # A newer publication after ACK is not an old-generation replay.
    raw.extend([
        {"name": "mailbox_enqueue", "generation": 101, "epoch": 7, "t_ns": 10_100_021, "extra": {"pub_id": 101}},
        {"name": "mailbox_dequeue", "generation": 101, "epoch": 7, "t_ns": 10_100_022, "extra": {"pub_id": 101}},
        {"name": "texture_upload_end", "generation": 101, "epoch": 7, "t_ns": 10_100_023, "extra": {"pub_id": 101}},
        {"name": "post_pixel_present", "generation": 101, "epoch": 7, "t_ns": 10_100_024, "extra": {"pub_id": 101}},
    ])
    result = DRV.reduce_gate_a_capture(raw, cap["edits"])
    assert result["complete"] and result["cancels"][0]["stale_frames_after_ack"] == 0

    # A canceled old generation presented after ACK is RED even after a newer
    # upload/dispatch would otherwise move the current input floor.
    raw.append({"name": "post_pixel_present", "generation": 1, "epoch": 7,
                "t_ns": 10_100_025, "extra": {"pub_id": 1}})
    result = DRV.reduce_gate_a_capture(raw, cap["edits"])
    assert result["errors"] and result["cancels"][0]["stale_frames_after_ack"] == 1


def test_gate_a_reducer_rejects_forged_or_misordered_pixel_evidence():
    cap = _capture(_sha("s"), 10000, "camera", 0)
    cap["raw_events"][0]["extra"]["label"] = "post"
    assert DRV.reduce_gate_a_capture(cap["raw_events"], cap["edits"])["errors"]
    cap = _capture(_sha("s"), 10000, "camera", 0)
    cap["raw_events"][0]["extra"]["sha256"] = _sha("forged")
    assert DRV.reduce_gate_a_capture(cap["raw_events"], cap["edits"])["errors"]


def test_gate_manifest_adapts_raw_producer_and_rejects_bad_captures(tmp_path):
    good = _payload()
    path = tmp_path / "instrument.json"; path.write_text(json.dumps(good), encoding="utf-8")
    row = GM.load_instruments(None, {"a": path})["a"]
    assert row["value"]["gpu_p95_ms"] is not None
    computed, reasons = GM.compute_row("a", row, GM.ROW_SPEC["a"], tmp_path)
    assert computed["status"] == "green", reasons
    bad = _payload("no_present")
    path.write_text(json.dumps(bad), encoding="utf-8")
    row = GM.load_instruments(None, {"a": path})["a"]
    computed, _ = GM.compute_row("a", row, GM.ROW_SPEC["a"], tmp_path)
    assert computed["status"] != "green"


def test_gate_manifest_rejects_wrong_device_truncation_and_forged_summary(tmp_path):
    for mutation in ("device", "actual_device", "truncated", "forged_stale"):
        payload = _payload()
        if mutation == "device":
            payload["records"][0]["backend"] = "CPU"
        elif mutation == "actual_device":
            payload["records"][0]["observed_runtime"]["actual_gpu_devices"] = [-1]
        elif mutation == "truncated":
            payload["records"][0]["truncated"] = True
        else:
            # Submitted summaries, including fractional stale-frame claims, are
            # ignored; only the retained raw events are reduced.
            payload["records"][0]["reduced"] = {"stale_frames_after_ack": 0.5}
            payload["records"][0]["raw_events"].append(
                {"name": "post_pixel_present", "generation": 1, "epoch": 7,
                 "t_ns": 10_100_025, "extra": {"pub_id": 1, "input_floor": 100}})
        path = tmp_path / f"{mutation}.json"; path.write_text(json.dumps(payload), encoding="utf-8")
        row = GM.load_instruments(None, {"a": path})["a"]
        computed, _ = GM.compute_row("a", row, GM.ROW_SPEC["a"], tmp_path)
        assert computed["status"] != "green"
