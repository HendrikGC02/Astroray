"""pkg310 -- production node-tree corpus: Cycles parity + silent-drop gate.

Eight realistic production materials (``benchmarks/reference_corpus/production/prod_*.blend``, built by
``build_corpus.py``) rendered on Astroray CPU and GPU and compared with the committed 1024 spp Cycles
references through the pkg284 MC-band machinery (``mc_tolerance.py --suite production``,
``gates_production.toml``). One test per (material, backend):

* ``test_production_material_parity``: every non-excluded (ROI, channel) inside its band.
* ``test_production_silent_drops``: ``silent_drop_audit`` finds no exercised (node, socket) pair that is
  neither SUPPORTED in the frozen coverage matrix nor named in the render's DegradationReport.

Failing materials are ``xfail(strict=True)`` tied to a GitHub issue in ``provisional_production.toml``
(memory ``xfail-gated-features-must-unxfail``): the fixing PR deletes the row and the test must then pass.
Rows the owner declared documented divergences are pinned against Astroray's own mean instead of Cycles.

Needs headless Blender 5.2 and an OpenMP-ON/OFF staged addon (``ASTRORAY_PYD_DIR``); skipped otherwise.
GPU legs run under the GPU lock: ``python scripts/build/gpu_locked_run.py <lane> -- pytest ...``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
import tomllib
from results_layout import results_dir

from benchmarks.reference_corpus import mc_tolerance as MC
from benchmarks.reference_corpus import silent_drop_audit as AUDIT

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "reference_corpus"
PROD = CORPUS / "production"
GATES = tomllib.loads((CORPUS / "gates_production.toml").read_text(encoding="utf-8"))
PROVISIONAL = tomllib.loads((CORPUS / "provisional_production.toml").read_text(encoding="utf-8")).get("row", [])
MANIFEST = json.loads((PROD / "manifest.json").read_text(encoding="utf-8"))
SCENES = sorted(GATES["scenes"])
BACKENDS = ("cpu", "gpu")
WORK = Path(os.environ.get("PKG310_WORK", str(results_dir("textures-nodes", "production-corpus-work", create=False))))
_cache: dict = {}


def _prov(scene, backend, kind):
    return next((r for r in PROVISIONAL if (r["scene"], r["backend"], r["kind"]) == (scene, backend, kind)), None)


def _cases(kind):
    out = []
    for sid in SCENES:
        for backend in BACKENDS:
            marks = [pytest.mark.slow] + ([pytest.mark.gpu] if backend == "gpu" else [pytest.mark.serial])
            row = _prov(sid, backend, kind)
            if row:
                marks.append(pytest.mark.xfail(strict=True, reason=f"{row['issue']}: {row['reason']}"))
            out.append(pytest.param(sid, backend, marks=marks, id=f"{sid}-{backend}"))
    return out


def _render(sid, leg):
    key = (sid, leg)
    if key not in _cache:
        if not MC.BLENDER.is_file() or not os.environ.get("ASTRORAY_PYD_DIR"):
            pytest.skip("needs Blender 5.2 (ASTRORAY_BLENDER) and a staged addon (ASTRORAY_PYD_DIR)")
        s = GATES["scenes"][sid]
        stem = WORK / f"{sid}_{leg}_s{s['seed']}"
        img = MC.render(sid, leg, s["seed"], s["spp_gate"], stem, manifest=PROD / "manifest.json")
        _cache[key] = (img, stem.with_suffix(".log").read_text(encoding="utf-8", errors="replace"))
    return _cache[key]


@pytest.mark.parametrize("sid,backend", _cases("parity"))
def test_production_material_parity(sid, backend):
    img, _ = _render(sid, backend)
    rows = MC.score_material(GATES["scenes"][sid], img, backend)
    bad = [r for r in rows if not r["ok"]]
    assert not bad, f"{sid} {backend}: {len(bad)}/{len(rows)} ROI channels outside band: " + "; ".join(
        f"{r['roi']}.{r['channel']} {r['ratio']:.3f} (tol {r['tol']:.3f})" for r in bad[:6])


@pytest.mark.parametrize("sid,backend", _cases("silent"))
def test_production_silent_drops(sid, backend):
    _, log = _render(sid, backend)
    uses = json.loads((PROD / "node_uses.json").read_text(encoding="utf-8"))["scenes"][sid]
    res = AUDIT.audit_scene(uses["pairs"], AUDIT.load_matrix(), log)
    silent = sorted({f"{p['bl_idname']}|{p['socket']}" for p in res["silent"]})
    assert not silent, f"{sid} {backend}: {len(silent)} silent drops: " + ", ".join(silent[:8])


# ---- metadata / non-vacuity: fast profile, no Blender ----------------------------------------------------

def test_corpus_has_eight_pinned_materials():
    assert len(SCENES) == 8 and all(s.startswith("prod_") for s in SCENES)
    assert set(MANIFEST["scenes"]) == set(SCENES)
    for sid in SCENES:
        e = MANIFEST["scenes"][sid]
        assert e["assets"], f"{sid}: HDRI asset (with licence) not recorded"
        assert all(a["license"] and a["sha256"] for a in e["assets"])
        assert 2 <= len(GATES["scenes"][sid]["roi"]) <= 5
    from benchmarks.blender_parity import (
        scene_library as sl,  # fail-closed: blend + asset digests match the manifest
    )
    assert set(sl.load_corpus_manifest(PROD / "manifest.json")) == set(SCENES)


def test_node_uses_snapshot_matches_scenes():
    snap = json.loads((PROD / "node_uses.json").read_text(encoding="utf-8"))["scenes"]
    assert set(snap) == set(SCENES)
    for sid in SCENES:
        assert snap[sid]["scene_sha256"] == MANIFEST["scenes"][sid]["sha256"], f"{sid}: node_uses.json is stale"
        assert not snap[sid]["collection_errors"] and snap[sid]["pairs"]


def test_silent_drop_audit_is_not_vacuous():
    """The fixture material (an unhandled Hair Info node) is flagged; naming it in the report clears it."""
    assert AUDIT.self_test()


def test_audit_credits_the_handled_attribute_and_light_path_materials():
    """pkg320 (#1039): #990 / #991 handle Attribute / Color Attribute / Object Info outputs, Light Path outputs
    and the Mix Shader closure switch. The generated matrix now carries output-socket and Mix Shader evidence,
    so with an empty report neither scene has a silent pair (they were the two `silent` rows of
    provisional_production.toml)."""
    scenes = json.loads((PROD / "node_uses.json").read_text(encoding="utf-8"))["scenes"]
    matrix = AUDIT.load_matrix()
    for sid in ("prod_attributes", "prod_light_path"):
        res = AUDIT.audit_scene(scenes[sid]["pairs"], matrix, "Render completed in 1s\n")
        assert not res["silent"], (sid, [(p["bl_idname"], p["socket"]) for p in res["silent"]])


def test_audit_still_flags_an_unhandled_output_socket():
    """No false credit: Geometry's Pointiness is refused by the compiler (VMCompileError) and stays a silent pair."""
    scenes = json.loads((PROD / "node_uses.json").read_text(encoding="utf-8"))["scenes"]
    matrix = AUDIT.load_matrix()
    flagged = {(p["bl_idname"], p["id"]) for scene in scenes.values()
               for p in AUDIT.audit_scene(scene["pairs"], matrix, "Render completed in 1s\n")["silent"]}
    assert ("ShaderNodeNewGeometry", "Pointiness") in flagged


def test_provisional_rows_reference_real_cases_and_issues():
    ids = {p.id for kind in ("parity", "silent") for p in _cases(kind)}
    for row in PROVISIONAL:
        assert re.fullmatch(r"#\d+", row["issue"]), f"provisional row without an issue id: {row}"
        assert row["kind"] in ("parity", "silent"), row
        assert f"{row['scene']}-{row['backend']}" in ids, f"provisional row matches no case: {row}"


@pytest.mark.slow
def test_rebuild_is_structurally_identical():
    """Blender 5.2 .blend bytes differ between two builds of one script, so a rebuild cannot be byte-identical
    (verified on v2_textures_opvm and prod_car_paint); the manifest SHA pins the committed file and this checks
    that a fresh build reproduces everything the gates depend on: ROIs, node ids, object census, triangles."""
    import shutil
    import subprocess
    if not MC.BLENDER.is_file():
        pytest.skip("needs Blender 5.2 (ASTRORAY_BLENDER)")
    sid = "prod_pbr_group"  # images + node group + procedural textures: the least trivial builder
    tmp = PROD / "_rebuild"  # inside the repo: build_corpus records blend_path relative to it
    try:
        out = subprocess.run([str(MC.BLENDER), "-b", "--factory-startup", "--python", str(CORPUS / "build_corpus.py"),
                              "--", "--families", sid, "--out-dir", str(tmp)],
                             capture_output=True, text=True, timeout=300, check=False)
        assert "reopen_verified=True" in out.stdout, out.stdout[-800:]
        fresh = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))["scenes"][sid]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ref = MANIFEST["scenes"][sid]
    for key in ("crops", "node_ids", "object_counts", "triangle_count", "assets", "settings"):
        assert fresh[key] == ref[key], f"{sid}: rebuilt {key} differs from the committed manifest"
