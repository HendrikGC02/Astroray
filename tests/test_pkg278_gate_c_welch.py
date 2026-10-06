"""Gate (c) = pkg317 Welch tile test (candidate 1b) on 8 frozen seeds per backend (owner 2026-10-06).

Synthetic per-seed legs in the ``harness.py --seeds study`` layout -> ``gate_manifest.py
--adapt-c-seeds`` payload -> manifest reducer.  Green / red on a 3 % ROI bias, and every
fail-closed case.  CPU only, no Blender.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from benchmarks.blender_parity import harness as H
from scripts import gate_manifest as GM

RES = 32
SEEDS = H.STUDY_SEEDS
ROI = [0.25, 0.25, 0.75, 0.75]
CONTROLS = {
    "materials_hall": [],
    "textures_mapping": [{"kind": "checker_flat", "object": "TexChecker", "material": "TexCheckerMat",
                          "node": "GateCWorkshopChecker", "mask": {"kind": "object_polygon"}}],
    "world_sky:terrace-with-hair": [{"kind": "hair_off", "object": "TerraceHair", "mask": {"kind": "curves"}},
                                    {"kind": "hdri_off", "world": "W", "node": "GateCTerraceEnvironment",
                                     "mask": {"kind": "sky_rays"}}],
}
PROBES = {
    "materials_hall": [],
    "textures_mapping": [{"kind": "checker", "roi": "all", "min_delta": .05, "min_coverage": .02}],
    "world_sky:terrace-with-hair": [{"kind": "hair", "roi": "all", "min_delta": .05, "min_coverage": .02},
                                    {"kind": "hdri", "roi": "all", "min_delta": .05, "min_coverage": .02}],
}
BINDINGS = {
    "checker_flat": {"object": "TexChecker", "object_type": "MESH", "material": "TexCheckerMat",
                     "node": "GateCWorkshopChecker", "node_type": "ShaderNodeTexChecker"},
    "hair_off": {"object": "TerraceHair", "object_type": "CURVES", "curve_count": 320, "curve_point_count": 1920},
    "hdri_off": {"world": "W", "node": "GateCTerraceEnvironment", "node_type": "ShaderNodeTexEnvironment"},
}
RECEIPTS = {
    "checker_flat": {"object": "TexChecker", "material": "TexCheckerMat", "node": "GateCWorkshopChecker",
                     "before": [[0, 0, 0, 1], [1, 1, 1, 1]], "after": [[.5, .5, .5, 1], [.5, .5, .5, 1]]},
    "hair_off": {"object": "TerraceHair", "type": "CURVES", "was_hide_render": False, "after_hide_render": True},
    "hdri_off": {"world": "W", "node": "GateCTerraceEnvironment", "image": "sky.hdr", "after_image": None},
}


def _freeze() -> dict:
    roles = {}
    for role in GM.TRIO_ROLES:
        roles[role] = {"scene_id": role.replace(":", "_"), "scene_sha256": hashlib.sha256(role.encode()).hexdigest(),
                       "settings": {"res_x": RES, "res_y": RES, "samples": 4},
                       "rois": {"all": ROI}, "non_vacuity": PROBES[role], "controls": CONTROLS[role], "seed": 278,
                       "expected_curve_count": 320 if role.endswith("hair") else None,
                       "expected_curve_point_count": 1920 if role.endswith("hair") else None}
    return {"build_id": "build-1", "module_sha256": "a" * 64, "addon_sha256": "b" * 64, "roles": roles}


def _base(role: str) -> np.ndarray:
    y, x = np.mgrid[0:RES, 0:RES].astype(np.float32) / RES
    img = 0.3 + 0.3 * x + 0.1 * y
    if role == "textures_mapping":
        img = np.where(((np.arange(RES)[None, :] // 4 + np.arange(RES)[:, None] // 4) % 2) == 0, 0.7, 0.3)
    return np.repeat(img[..., None], 3, axis=-1).astype(np.float32) * np.array([1.0, 0.9, 0.8], np.float32)


def _report(freeze, freeze_sha, role, backend, kind, seed, mask=None) -> dict:
    frozen = freeze["roles"][role]
    report = {"corpus_scene": frozen["scene_id"], "blend_sha256": frozen["scene_sha256"], "freeze_sha256": freeze_sha,
              "build_id": freeze["build_id"], "requested_device": backend.lower(), "effective_device": backend.lower(),
              "engine": "CUSTOM_RAYTRACER", "res_x": RES, "res_y": RES, "samples": 4, "resolved_seed": seed,
              "animated_seed": False, "blender_version": "5.2.0", "module_path": "C:/b/astroray.pyd",
              "module_sha256": freeze["module_sha256"], "addon_path": "C:/b/__init__.py",
              "addon_sha256": freeze["addon_sha256"], "telemetry": [],
              "bindings": {c["kind"]: BINDINGS[c["kind"]] for c in CONTROLS[role]},
              "mutation_receipt": {"kind": kind, "ok": True, **RECEIPTS.get(kind, {})}, "mask_receipt": None}
    if mask is not None:
        declared = next(c for c in CONTROLS[role] if c["kind"] == kind)
        report["mask_receipt"] = {"control": kind, "kind": declared["mask"]["kind"], "path": str(mask),
                                  "sha256": hashlib.sha256(mask.read_bytes()).hexdigest(),
                                  "shape": [RES, RES], "pixels": RES * RES}
    return report


def _write_log(path, report):
    path.write_text(f"PKG307_INFO {{}}\n{H.SENTINEL} REPORT {json.dumps(report)}\n{H.SENTINEL} PASS\n\n",
                    encoding="utf-8")


def _build_legs(root, *, cv=0.02, bias=None):
    """Write freeze + seed_legs like ``run_gate_c_seed_legs``; ``bias`` = (role, factor) on GPU ROI."""
    freeze = _freeze()
    freeze_path = root / "gate_c.freeze.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    rng = np.random.default_rng(317)
    for role in GM.TRIO_ROLES:
        base = _base(role)
        for backend in ("CPU", "GPU"):
            for kind in ["baseline"] + [c["kind"] for c in CONTROLS[role]]:
                leg = root / "seed_legs" / f"{role.replace(':', '_')}_{backend.lower()}_{kind}"
                leg.mkdir(parents=True, exist_ok=True)
                for seed in (SEEDS if kind == "baseline" else (278,)):
                    img = base * (1 + cv * rng.standard_normal(base.shape)).astype(np.float32)
                    if kind == "checker_flat":
                        img = np.full_like(base, 0.5)
                    elif kind == "hair_off":
                        img = img - 0.2
                    elif kind == "hdri_off":
                        img = np.zeros_like(base)
                    if bias and bias[0] == role and backend == "GPU" and kind == "baseline":
                        img[RES // 4:3 * RES // 4, RES // 4:3 * RES // 4] *= np.float32(bias[1])
                    np.save(leg / f"s{seed}.npy", img.astype(np.float32))
                    mask = None
                    if kind != "baseline":
                        mask = leg / f"mask_s{seed}.npy"
                        np.save(mask, np.ones((RES, RES), np.uint8))
                    _write_log(leg / f"s{seed}.log", _report(freeze, freeze_sha, role, backend, kind, seed, mask))
                    (leg / f"s{seed}.json").write_text(json.dumps({"seed": seed}), encoding="utf-8")
    return freeze_path


def _adapt(root):
    out = root / "row_c_welch.json"
    payload = GM.adapt_c_seed_instrument(root, root / "gate_c.freeze.json", out)
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def _row(root):
    row = GM.load_instruments(None, {"c": _adapt(root)})["c"]
    return GM.compute_row("c", row, GM.ROW_SPEC["c"], root)


def _leg(root, role, backend, kind="baseline"):
    return root / "seed_legs" / f"{role.replace(':', '_')}_{backend.lower()}_{kind}"


def _edit_report(root, role, backend, seed, **changes):
    log = _leg(root, role, backend) / f"s{seed}.log"
    report, err = H._parse_gate_leg_report(log.read_text(encoding="utf-8"))
    assert err is None
    report.update(changes)
    _write_log(log, report)


def test_synthetic_legs_compute_green_and_validate(tmp_path):
    _build_legs(tmp_path)
    row, reasons = _row(tmp_path)
    assert row["status"] == "green", reasons
    assert row["value"]["welch_rejected_tiles"] == 0
    assert row["value"]["roi_pct_max"] < 1.0
    assert set(row["value"]["per_role"]) == set(GM.TRIO_ROLES)
    assert all(v["welch_tests"] == 48 for v in row["value"]["per_role"].values())  # 4x4 tiles x RGB
    assert all(row["subchecks"].values()) and set(row["subchecks"]) == set(GM.ROW_SPEC["c"]["required_subchecks"])
    assert len(row["records"]) == 3 * 2 * 8 + 2 * 3  # baselines + one control leg per declared control/backend
    manifest, _ = GM.assemble({"c": row}, tmp_path)
    assert manifest["rows"]["c"]["status"] == "green"
    assert not GM.validate_manifest(manifest, tmp_path)


def test_ssim_is_informational_only(tmp_path):
    _build_legs(tmp_path, cv=0.6)  # noise-bound single-seed SSIM, as on the real terrace
    row, reasons = _row(tmp_path)
    assert row["value"]["ssim_min_informational"] < 0.95
    assert row["status"] == "green", reasons


def test_three_percent_roi_bias_is_red_and_a_valid_measurement(tmp_path):
    _build_legs(tmp_path, bias=("textures_mapping", 1.03))
    row, reasons = _row(tmp_path)
    assert row["status"] == "red"
    assert row["value"]["per_role"]["textures_mapping"]["welch_rejected_tiles"] > 0
    assert row["value"]["roi_pct_max"] < 5.0  # the +-5 % guard alone would have passed it
    assert any("textures_mapping Welch-1b rejects" in r for r in reasons)
    manifest, _ = GM.assemble({"c": row}, tmp_path)
    assert not GM.validate_manifest(manifest, tmp_path)  # a measured RED is valid evidence


def _missing_seed(root):
    (_leg(root, "materials_hall", "GPU") / "s9371.npy").unlink()


def _seven_seeds(root):
    for leg in root.glob("seed_legs/*_baseline"):
        (leg / "s11027.npy").unlink()


def _foreign_seed(root):
    leg = _leg(root, "materials_hall", "CPU")
    for suffix in (".npy", ".log"):
        (leg / f"s1301{suffix}").rename(leg / f"s1302{suffix}")
    _edit_report(root, "materials_hall", "CPU", 1302, resolved_seed=1302)


def _seed_reuse(root):
    leg = _leg(root, "materials_hall", "CPU")
    shutil.copyfile(leg / "s278.npy", leg / "s1301.npy")


def _module(root):
    _edit_report(root, "textures_mapping", "GPU", 4177, module_sha256="c" * 64)


def _scene(root):
    _edit_report(root, "textures_mapping", "CPU", 278, blend_sha256="d" * 64)


def _build(root):
    _edit_report(root, "world_sky:terrace-with-hair", "GPU", 278, build_id="other-build")


def _device(root):
    _edit_report(root, "materials_hall", "GPU", 6113, effective_device="cpu")


def _changed_freeze(root):
    freeze_path = root / "gate_c.freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze["roles"]["materials_hall"]["rois"]["all"] = [0, 0, 1, 1]
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")


def _missing_log(root):
    (_leg(root, "materials_hall", "CPU") / "s278.log").unlink()


def _missing_mask(root):
    (_leg(root, "textures_mapping", "GPU", "checker_flat") / "mask_s278.npy").unlink()


def _missing_control(root):
    shutil.rmtree(_leg(root, "world_sky:terrace-with-hair", "CPU", "hdri_off"))


@pytest.mark.parametrize("mutate, expected", [
    (_missing_seed, "not exactly the 8 frozen spread seeds"),
    (_seven_seeds, "not exactly the 8 frozen spread seeds"),
    (_foreign_seed, "not in the frozen spread seed list"),
    (_seed_reuse, "reuses one render under several seeds"),
    (_module, "module_sha256"),
    (_scene, "blend_sha256"),
    (_build, "build_id"),
    (_device, "effective_device"),
    (_changed_freeze, "freeze_sha256"),
    (_missing_log, "identity is unproven"),
    (_missing_mask, "feature mask"),
    (_missing_control, "lacks a usable hdri_off control leg"),
])
def test_fail_closed_before_adaptation(tmp_path, mutate, expected):
    _build_legs(tmp_path)
    mutate(tmp_path)
    row, reasons = _row(tmp_path)
    assert row["status"] == "red"
    assert any(expected in r for r in reasons), reasons[:8]
    manifest, _ = GM.assemble({"c": row}, tmp_path)
    assert GM.validate_manifest(manifest, tmp_path)  # invalid evidence, not a measured red


def _edit_control_report(root, role, backend, kind, edit):
    log = _leg(root, role, backend, kind) / "s278.log"
    report, err = H._parse_gate_leg_report(log.read_text(encoding="utf-8"))
    assert err is None
    edit(report)
    _write_log(log, report)


@pytest.mark.parametrize("edit, expected", [
    (lambda r: r.update(resolved_seed=0), "resolved_seed"),
    (lambda r: r["mask_receipt"].update(sha256="0" * 64), "mask receipt"),
    (lambda r: r["mask_receipt"].update(pixels=0), "mask receipt"),
    (lambda r: r["mutation_receipt"].update(after=r["mutation_receipt"]["before"]), "checker mutation receipt"),
    (lambda r: r["bindings"]["checker_flat"].update(node_type="ShaderNodeTexNoise"), "binding differs"),
])
def test_control_receipts_are_bound_to_the_freeze(tmp_path, edit, expected):
    # pkg278 intent carried over from the single-seed reducer: the counterfactual must be the
    # declared one, on the frozen geometry mask, at the frozen seed.
    _build_legs(tmp_path)
    _edit_control_report(tmp_path, "textures_mapping", "CPU", "checker_flat", edit)
    row, reasons = _row(tmp_path)
    assert row["status"] == "red" and any(expected in r for r in reasons), reasons[:8]


@pytest.mark.parametrize("control", ["same_as_baseline", "one_sided"])
def test_vacuous_checker_control_is_a_measured_red(tmp_path, control):
    _build_legs(tmp_path)
    path = _leg(tmp_path, "textures_mapping", "GPU", "checker_flat") / "s278.npy"
    baseline = np.load(_leg(tmp_path, "textures_mapping", "GPU") / "s278.npy")
    # One-sided: a uniform brightness change is not a checker witness (both phases required).
    np.save(path, baseline if control == "same_as_baseline" else baseline - np.float32(0.2))
    row, reasons = _row(tmp_path)
    assert row["status"] == "red"
    assert any("textures_mapping/GPU checker non-vacuity witness failed" in r for r in reasons)
    manifest, _ = GM.assemble({"c": row}, tmp_path)
    assert not GM.validate_manifest(manifest, tmp_path)


def test_duplicate_record_is_rejected(tmp_path):
    _build_legs(tmp_path)
    out = _adapt(tmp_path)
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["records"].append(payload["records"][0])
    out.write_text(json.dumps(payload), encoding="utf-8")
    row = GM.load_instruments(None, {"c": out})["c"]
    computed, reasons = GM.compute_row("c", row, GM.ROW_SPEC["c"], tmp_path)
    assert computed["status"] == "red" and any("duplicate leg" in r for r in reasons)


@pytest.mark.parametrize("target", ["npy", "freeze", "evidence"])
def test_tampering_after_adaptation_is_red(tmp_path, target):
    _build_legs(tmp_path)
    out = _adapt(tmp_path)
    row = GM.load_instruments(None, {"c": out})["c"]
    if target == "npy":
        np.save(_leg(tmp_path, "materials_hall", "GPU") / "s278.npy", np.ones((RES, RES, 3), np.float32))
    elif target == "freeze":
        (tmp_path / "gate_c.freeze.json").write_text("{}", encoding="utf-8")
    else:
        row["evidence_sha256"] = "0" * 64
    computed, reasons = GM.compute_row("c", row, GM.ROW_SPEC["c"], tmp_path)
    assert computed["status"] == "red"
    assert any("digest mismatch" in r or "evidence" in r for r in reasons), reasons[:5]


def test_single_seed_trio_payload_is_no_longer_admissible(tmp_path):
    _build_legs(tmp_path)
    out = _adapt(tmp_path)
    payload = json.loads(out.read_text(encoding="utf-8"))
    for record in payload["records"]:
        record["kind"] = "f12_run"
    out.write_text(json.dumps(payload), encoding="utf-8")
    computed, reasons = GM.compute_row("c", GM.load_instruments(None, {"c": out})["c"], GM.ROW_SPEC["c"], tmp_path)
    assert computed["status"] == "red" and any("invalid kind" in r for r in reasons)


def test_cli_adapts_seed_legs_and_recomputes_the_manifest(tmp_path):
    _build_legs(tmp_path)
    out = tmp_path / "row_c_welch.json"
    cwd = tmp_path / "elsewhere"; cwd.mkdir()
    script = str(GM.REPO_ROOT / "scripts" / "gate_manifest.py")
    adapted = subprocess.run([sys.executable, script, "--adapt-c-seeds", str(tmp_path), "--out", str(out)],
                             cwd=cwd, text=True, capture_output=True, check=False)
    assert adapted.returncode == 0, adapted.stdout + adapted.stderr
    manifest_path = tmp_path / "manifest.json"
    result = subprocess.run([sys.executable, script, "--instrument", f"c={out}", "--out", str(manifest_path), "--json"],
                            cwd=cwd, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["rows"]["c"]["status"] == "green"


def test_harness_seed_legs_feed_the_reducer_end_to_end(tmp_path, monkeypatch):
    """``run_gate_c_seed_legs`` keeps each leg's log and frozen mask, renders every declared control
    (incl. checker_flat) and its output adapts to a green row without hand edits."""
    freeze = {**_freeze(), "manifest_path": str(tmp_path / "manifest.json")}
    freeze_path = tmp_path / "gate_c.freeze.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    by_scene = {v["scene_id"]: k for k, v in freeze["roles"].items()}
    rng = np.random.default_rng(5)

    def fake_leg(_blender, args, _env, _timeout):
        role, backend = by_scene[args[args.index("--corpus-scene") + 1]], args[args.index("--device") + 1].upper()
        seed, out = int(args[args.index("--seed") + 1]), args[args.index("--out") + 1]
        kind = args[args.index("--gate-c-control") + 1] if "--gate-c-control" in args else "baseline"
        img = _base(role) * (1 + 0.02 * rng.standard_normal((RES, RES, 3))).astype(np.float32)
        img = {"checker_flat": np.full_like(img, 0.5), "hair_off": img - 0.2, "hdri_off": 0 * img}.get(kind, img)
        np.save(out + ".npy", img.astype(np.float32))
        mask = None
        if kind != "baseline":
            mask = Path(args[args.index("--gate-c-mask-out") + 1])
            np.save(mask, np.ones((RES, RES), np.uint8))
        report = _report(freeze, freeze_sha, role, backend, kind, seed, mask)
        stdout = f"{H.SENTINEL} REPORT {json.dumps(report)}\n{H.SENTINEL} PASS\n"
        return 0, True, {**report, "_gate_leg_execution": {"stdout": stdout, "stderr": ""}}

    monkeypatch.setattr(H, "_find_blender", lambda: Path("blender.exe"))
    monkeypatch.setattr(H, "_run_gate_leg", fake_leg)
    assert H.run_gate_c_seed_legs(tmp_path, freeze_path) == 0
    assert (_leg(tmp_path, "textures_mapping", "CPU", "checker_flat") / "mask_s278.npy").is_file()
    assert (_leg(tmp_path, "materials_hall", "GPU") / "s11027.log").is_file()
    row, reasons = _row(tmp_path)
    assert row["status"] == "green", reasons


def test_frozen_metric_and_other_rows_unchanged():
    assert GM.GATE_C_WELCH == {"tile": 8, "alpha": 0.05, "margin_rel": 0.01}
    assert SEEDS == (278, 1301, 2711, 4177, 6113, 7919, 9371, 11027)
    assert GM.ROW_SPEC["c"]["threshold"] == {"welch_rejected_tiles": {"max": 0}, "roi_pct_max": {"max": 5.0}}
    pinned = {
        "a": ("viewport_latency", {"gpu_p95_ms": {"max": 100.0}, "gpu_p99_ms": {"max": 150.0},
                                   "cancel_p95_ms": {"max": 200.0}, "cancel_p99_ms": {"max": 300.0},
                                   "stale_frames_after_ack": {"max": 0}}),
        "b": ("coverage_report", {"cpu_score": {"min": 0.95}, "gpu_score": {"min": 0.95}}),
        "d": ("native_panel_smoke", {"mean_rel_error_max": {"max": 0.02}, "detail_preservation_min": {"min": 0.95}}),
        "e": ("issue_triage", {"high_count": {"max": 0}}),
        "f": ("clean_install", {}),
        "g": ("production_node_score", {"cpu_pass": {"min": 6}, "gpu_pass": {"min": 6},
                                        "cpu_silent_pairs": {"max": 0}, "gpu_silent_pairs": {"max": 0}}),
    }
    assert {r: (GM.ROW_SPEC[r]["instrument"], GM.ROW_SPEC[r]["threshold"]) for r in pinned} == pinned
