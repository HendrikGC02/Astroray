"""Stage 0 acceptance-manifest row (g): pkg310 production node score (owner 2026-10-06).

Pure Python, synthetic evidence: renders are painted from the committed pkg310 band file
(each ROI at its Cycles/pinned mean, so the real ``mc_tolerance.score_material`` is in band) and
logs carry a hand-built sentinel report.  Nothing here renders or needs Blender/GPU.

    OMP_NUM_THREADS=8 pytest tests/test_pkg310_manifest_row_g.py -v
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import tomllib

from benchmarks.reference_corpus import mc_tolerance as MC
from benchmarks.reference_corpus import silent_drop_audit as AUDIT
from scripts import gate_manifest as GM

GATES = tomllib.loads((MC.CORPUS / "gates_production.toml").read_text(encoding="utf-8"))["scenes"]
MANIFEST = json.loads((MC.PROD / "manifest.json").read_text(encoding="utf-8"))["scenes"]
USES = json.loads((MC.PROD / "node_uses.json").read_text(encoding="utf-8"))["scenes"]
MATRIX = AUDIT.load_matrix()
MODULE_SHA = hashlib.sha256(b"module").hexdigest()


def _image(sid: str, backend: str, skew: tuple[str, str, float] | None = None) -> np.ndarray:
    """A render whose every ROI mean equals its reference mean (ratio 1); ``skew`` = (roi, channel, factor)."""
    g = GATES[sid]
    w, h = g["res"]
    img = np.full((h, w, 3), 0.001, dtype=np.float32)
    for roi in g["roi"]:
        den = roi[f"{backend.lower()}_mean"] if "expected_divergence" in roi else roi["cycles_mean"]
        x0, y0, x1, y1 = roi["rect"]
        patch = np.array(den[:3], dtype=np.float32)
        if skew and skew[0] == roi["name"]:
            patch = patch * (skew[2] if skew[1] == "all" else 1.0)
        img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)] = patch
    return img


def _log(sid: str, backend: str, *, report_all: bool, build_id: str = "test-build", **over) -> str:
    g = GATES[sid]
    report = {"corpus_scene": sid, "blend_sha256": MANIFEST[sid]["sha256"], "build_id": build_id,
              "requested_device": backend.lower(), "effective_device": backend.lower(),
              "engine": "CUSTOM_RAYTRACER", "res_x": g["res"][0], "res_y": g["res"][1],
              "samples": g["spp_gate"], "resolved_seed": g["seed"], "animated_seed": False,
              "blender_version": "5.2.0 LTS", "module_sha256": MODULE_SHA}
    report.update(over)
    info = {"adaptive": False, "denoise": False, "samples": g["spp_gate"]}
    lines = ["Blender 5.2", f"PKG119B_LEG REPORT {json.dumps(report)}", "PKG307_INFO " + json.dumps(info)]
    if report_all:
        silent = AUDIT.audit_scene(USES[sid]["pairs"], MATRIX, "")["silent"]
        names = sorted({" ".join(AUDIT.node_aliases(p["bl_idname"])[0]) for p in silent})
        if names:
            lines.append("Astroray degradation: fixture -- " + "; ".join(f"approximated {n}: fixture" for n in names))
    lines.append("PKG119B_LEG PASS")
    return "\n".join(lines) + "\n"


def _work_dir(tmp_path: Path, *, skew=None, report_all=True, **log_over) -> Path:
    """A PKG310_WORK-style dir. ``skew``: {(sid, BACKEND): (roi, 'all', factor)}."""
    work = tmp_path / "work"
    work.mkdir(parents=True)
    for sid in GATES:
        for backend in ("CPU", "GPU"):
            stem = work / f"{sid}_{backend.lower()}_s{GATES[sid]['seed']}"
            np.save(stem.with_suffix(".npy"), _image(sid, backend, (skew or {}).get((sid, backend))))
            stem.with_suffix(".log").write_text(_log(sid, backend, report_all=report_all, **log_over), encoding="utf-8")
    return work


def _evidence(tmp_path: Path, **kw) -> Path:
    out = tmp_path / "evidence_g" / "instrument.json"
    payload = GM.adapt_g_instrument(_work_dir(tmp_path, **kw), out)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _row(path: Path) -> dict:
    return GM.load_instruments(None, {"g": path})["g"]


def _rewrite(path: Path, edit) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    edit(payload)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _off_band(*materials, backends=("CPU", "GPU")):
    """Skew one ROI of each material out of band (x2) on the given backends."""
    return {(m, b): (GATES[m]["roi"][0]["name"], "all", 2.0) for m in materials for b in backends}


# --------------------------------------------------------------------------- structure

def test_row_g_is_declared_and_committed_unmeasured():
    assert GM.ROWS[-1] == "g" and GM.ROW_SPEC["g"]["instrument"] == "production_node_score"
    manifest = json.loads((GM.DEFAULT_OUT).read_text(encoding="utf-8"))
    assert manifest["rows"]["g"]["status"] == "unmeasured" and manifest["rows"]["g"]["value"] is None
    # Row g only: the committed row (d) evidence_path uses Windows separators and
    # does not resolve on the Linux CI runner (pre-existing, unrelated to row g).
    assert [e for e in GM.validate_manifest(manifest) if e.startswith("row g")] == []
    schema = json.loads(GM.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "g" in schema["properties"]["rows"]["required"]
    assert "production_node_score" in schema["$defs"]["row"]["properties"]["instrument"]["enum"]


def test_threshold_is_owner_6_of_8_on_both_backends_plus_zero_silent():
    # owner 2026-10-06: >= 6/8 scenes passing on BOTH CPU and GPU; 2026-09-29: zero silent degradations
    assert GM.ROW_SPEC["g"]["threshold"] == {
        "cpu_pass": {"min": 6}, "gpu_pass": {"min": 6},
        "cpu_silent_pairs": {"max": 0}, "gpu_silent_pairs": {"max": 0}}
    assert "owner_threshold_pending" not in GM.ROW_SPEC["g"]


def test_assemble_without_instrument_is_unmeasured_and_a_to_f_keep_their_instruments():
    manifest, _ = GM.assemble({})
    assert manifest["rows"]["g"]["status"] == "unmeasured" and GM.validate_shape(manifest) == []
    assert [GM.ROW_SPEC[r]["instrument"] for r in "abcdef"] == [
        "viewport_latency", "coverage_report", "trio_parity", "native_panel_smoke", "issue_triage", "clean_install"]


def test_hand_edited_green_without_instrument_is_rejected():
    row, why = GM.compute_row("g", None, GM.ROW_SPEC["g"], GM.REPO_ROOT, {"status": "green"})
    assert row["status"] == "red" and row["hand_edit_detected"] and "hand-edited" in why[0]


# --------------------------------------------------------------------------- recompute

def test_8_of_8_recomputes_green(tmp_path):
    row, why = GM.compute_row("g", _row(_evidence(tmp_path)), GM.ROW_SPEC["g"], GM.REPO_ROOT)
    assert row["value"] == {"cpu_pass": 8, "cpu_in_band": 8, "cpu_silent_pairs": 0,
                            "gpu_pass": 8, "gpu_in_band": 8, "gpu_silent_pairs": 0}
    assert row["subchecks"] == {"legs_complete": True, "identity_bound": True,
                                "bands_recomputed": True, "zero_silent_degradations": True}
    assert row["status"] == "green" and not why


def test_6_of_8_on_both_backends_is_green_and_validates(tmp_path):
    skew = _off_band("prod_wood", "prod_marble")
    manifest, _ = GM.assemble({"g": _row(_evidence(tmp_path, skew=skew))})
    row = manifest["rows"]["g"]
    assert row["value"]["cpu_pass"] == 6 and row["value"]["gpu_pass"] == 6
    assert row["status"] == "green"
    assert GM.validate_manifest(manifest) == []


def test_5_of_8_on_either_backend_is_red(tmp_path):
    for backends in (("CPU",), ("GPU",)):
        sub = tmp_path / backends[0]
        skew = _off_band("prod_wood", "prod_marble", "prod_car_paint", backends=backends)
        row, why = GM.compute_row("g", _row(_evidence(sub, skew=skew)), GM.ROW_SPEC["g"], GM.REPO_ROOT)
        key = f"{backends[0].lower()}_pass"
        assert row["value"][key] == 5 and row["status"] == "red" and any(key in r for r in why)


def test_silent_drop_reds_the_row_even_with_8_of_8_in_band(tmp_path):
    row, why = GM.compute_row("g", _row(_evidence(tmp_path, report_all=False)), GM.ROW_SPEC["g"], GM.REPO_ROOT)
    assert row["value"]["cpu_silent_pairs"] > 0 and row["value"]["cpu_silent_pairs"] == row["value"]["gpu_silent_pairs"]
    assert row["value"]["cpu_in_band"] == 8 and row["subchecks"]["zero_silent_degradations"] is False
    assert row["status"] == "red" and any("silent_pairs" in r for r in why)


def test_green_row_without_recomputable_evidence_is_rejected_by_validate(tmp_path):
    manifest, _ = GM.assemble({"g": _row(_evidence(tmp_path))})
    manifest["rows"]["g"]["value"]["cpu_pass"] = 5  # hand edit of a green row
    assert any("row g" in e for e in GM.validate_manifest(manifest))


# --------------------------------------------------------------------------- fail closed

def _status(path: Path, *, edit_row=None) -> tuple[str, list[str], dict]:
    raw = _row(path)
    if edit_row:
        edit_row(raw)
    row, why = GM.compute_row("g", raw, GM.ROW_SPEC["g"], GM.REPO_ROOT)
    return row["status"], why, row


def test_caller_supplied_status_and_value_are_never_trusted(tmp_path):
    path = _evidence(tmp_path, report_all=False)

    def forge(raw):
        raw["status"] = "green"
        raw["value"] = {"cpu_pass": 8, "gpu_pass": 8, "cpu_in_band": 8, "gpu_in_band": 8,
                        "cpu_silent_pairs": 0, "gpu_silent_pairs": 0}
    status, why, _ = _status(path, edit_row=forge)
    assert status == "red" and any("not the value derived" in r for r in why)


def test_missing_evidence_file_is_red(tmp_path):
    path = _evidence(tmp_path)
    status, why, _ = _status(path, edit_row=lambda r: r.update(evidence_path=str(tmp_path / "nope.json")))
    assert status == "red" and any("evidence invalid" in r for r in why)


def test_tampered_render_artifact_is_red(tmp_path):
    path = _evidence(tmp_path)
    victim = next((path.parent / "renders").glob("prod_wood_gpu_*.npy"))
    victim.write_bytes(victim.read_bytes() + b"\0")
    status, why, _ = _status(path)
    assert status == "red" and any("digest mismatch" in r for r in why)


def test_missing_leg_record_is_red(tmp_path):
    path = _evidence(tmp_path)
    _rewrite(path, lambda p: p["records"].pop())
    status, why, _ = _status(path)
    assert status == "red" and any("cover every material" in r for r in why)


def test_duplicate_leg_record_is_red(tmp_path):
    path = _evidence(tmp_path)
    _rewrite(path, lambda p: p["records"].append(dict(p["records"][0])))
    status, why, _ = _status(path)
    assert status == "red" and any("duplicates leg" in r for r in why)


def test_wrong_scene_hash_is_red(tmp_path):
    path = _evidence(tmp_path)
    _rewrite(path, lambda p: p["records"][0].update(scene_sha256="0" * 64))
    assert _status(path)[0] == "red"
    path2 = _evidence(tmp_path / "again")
    _rewrite(path2, lambda p: p.update(scene_sha256=sorted(["1" * 64] * 8)))
    assert _status(path2)[0] == "red"


def test_log_from_the_other_backend_is_red(tmp_path):
    """A GPU log pasted into the CPU slot (hash re-pinned) is caught by the observed device in its report."""
    path = _evidence(tmp_path)
    renders = path.parent / "renders"
    cpu, gpu = renders / "prod_wood_cpu_s278.log", renders / "prod_wood_gpu_s278.log"
    cpu.write_text(gpu.read_text(encoding="utf-8"), encoding="utf-8")
    digest = hashlib.sha256(cpu.read_bytes()).hexdigest()

    def repin(p):
        rec = next(r for r in p["records"] if r["material"] == "prod_wood" and r["backend"] == "CPU")
        rec["log"]["sha256"] = digest
    _rewrite(path, repin)
    status, why, _ = _status(path)
    assert status == "red" and any("prod_wood/CPU" in r and "effective_device" in r for r in why)


def test_build_id_or_seed_or_adaptive_mismatch_is_red(tmp_path):
    for over in ({"resolved_seed": 7}, {"samples": 1}, {"build_id": "other"}, {"blender_version": "5.1"},
                 {"engine": "CYCLES"}, {"animated_seed": True}):
        sub = tmp_path / ("c_" + "_".join(over))
        sub.mkdir()
        work = _work_dir(sub)
        log = work / "prod_marble_cpu_s278.log"
        log.write_text(_log("prod_marble", "CPU", report_all=True, **over), encoding="utf-8")
        with pytest.raises(ValueError, match="rejected|build id"):  # the adapter refuses to wrap it
            GM.adapt_g_instrument(work, sub / "ev" / "instrument.json")


def test_adaptive_or_denoise_on_is_red(tmp_path):
    work = _work_dir(tmp_path)
    log = work / "prod_marble_gpu_s278.log"
    log.write_text(log.read_text(encoding="utf-8").replace('"denoise": false', '"denoise": true'), encoding="utf-8")
    with pytest.raises(ValueError, match="adaptive/denoise"):
        GM.adapt_g_instrument(work, tmp_path / "ev" / "instrument.json")


def test_empty_black_render_is_rejected(tmp_path):
    work = _work_dir(tmp_path)
    np.save(work / "prod_car_paint_cpu_s278.npy", np.zeros((240, 320, 3), np.float32))
    with pytest.raises(ValueError, match="non-empty"):
        GM.adapt_g_instrument(work, tmp_path / "ev" / "instrument.json")


def test_missing_work_artifact_fails_the_adapter(tmp_path):
    work = _work_dir(tmp_path)
    (work / "prod_attributes_gpu_s278.log").unlink()
    with pytest.raises(ValueError, match="missing production render artifact"):
        GM.adapt_g_instrument(work, tmp_path / "ev" / "instrument.json")


def test_failed_leg_sentinel_is_red(tmp_path):
    work = _work_dir(tmp_path)
    log = work / "prod_pbr_group_cpu_s278.log"
    log.write_text(log.read_text(encoding="utf-8").replace("PKG119B_LEG PASS", "PKG119B_LEG FAIL boom"), encoding="utf-8")
    with pytest.raises(ValueError, match="sentinel"):
        GM.adapt_g_instrument(work, tmp_path / "ev" / "instrument.json")


def test_pinned_input_digest_mismatch_or_non_canonical_input_is_red(tmp_path):
    path = _evidence(tmp_path)
    _rewrite(path, lambda p: p["inputs"]["gates"].update(sha256="2" * 64))
    status, why, _ = _status(path)
    assert status == "red" and any("digest mismatch" in r for r in why)
    path2 = _evidence(tmp_path / "again")
    _rewrite(path2, lambda p: p["inputs"].update(gates=copy.deepcopy(p["inputs"]["manifest"])))
    status, why, _ = _status(path2)
    assert status == "red" and any("not the canonical" in r for r in why)


def test_loosened_frozen_threshold_in_payload_is_red(tmp_path):
    for key, loose in (("cpu_silent_pairs", 5), ("cpu_pass", 1), ("gpu_pass", 5)):
        path = _evidence(tmp_path / key)
        _rewrite(path, lambda p, key=key, loose=loose: p["threshold"].update({key: loose}))
        status, why, _ = _status(path)
        assert status == "red" and any("loosened" in r for r in why)


# --------------------------------------------------------------------------- CLI

def test_cli_adapt_g_then_validate(tmp_path):
    import subprocess
    import sys
    work = _work_dir(tmp_path)
    out = tmp_path / "ev" / "instrument.json"
    done = subprocess.run([sys.executable, str(GM.REPO_ROOT / "scripts" / "gate_manifest.py"),
                           "--adapt-g", str(work), "--out", str(out)], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert done.returncode == 0, done.stderr
    manifest = tmp_path / "manifest.json"
    done = subprocess.run([sys.executable, str(GM.REPO_ROOT / "scripts" / "gate_manifest.py"),
                           "--instruments-dir", str(tmp_path / "none"), "--instrument", f"g={out}",
                           "--out", str(manifest), "--json"], capture_output=True, text=True, cwd=tmp_path, check=False)
    result = json.loads(done.stdout)
    assert result["statuses"]["g"] == "green"  # 8/8 recomputed >= owner bound 6
    assert json.loads(manifest.read_text(encoding="utf-8"))["rows"]["g"]["value"]["cpu_pass"] == 8
