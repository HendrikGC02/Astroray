"""Row (g) seed-mean gate (owner 2026-11-02, #986): band math, generated keys, seed spacing, fail-closed scoring.

Pure Python on the committed ``gates_production.toml`` and synthetic arrays: no Blender, no render, no GPU.

    pytest tests/test_rowg_mean_bands.py -v
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pytest
import tomllib

from benchmarks.reference_corpus import mc_tolerance as MC
from benchmarks.reference_corpus import report_tools as RT

DOC = tomllib.loads((MC.CORPUS / "gates_production.toml").read_text(encoding="utf-8"))
GATES, META = DOC["scenes"], DOC["meta"]
SEEDS = MC.SUITES["production"]["gate_seeds"]
FLOORS = {"cpu_mean_tol": 0.02, "gpu_mean_tol": 0.02, "cpu_mean_pin_tol": 0.02, "gpu_mean_pin_tol": 0.02,
          "gpu_cpu_mean_tol": 0.05}


# --------------------------------------------------------------------------- seeds

def test_gate_seeds_are_the_audit_set_and_contain_the_band_seeds():
    assert SEEDS == [278, 1301, 2711, 4177, 6113, 7919, 9371, 11027]
    assert META["gate_seeds"] == SEEDS and SEEDS[:len(META["mc_seeds"])] == META["mc_seeds"]


def test_gate_seeds_do_not_share_cpu_tile_streams_at_320x240():
    # 320x240 / 16 px tiles = 20 x 15 = 300 tiles; mt19937(seed + tile) streams of seeds closer than that collide (#986)
    assert MC.seed_streams_disjoint(SEEDS, 320, 240)
    assert min(b - a for a, b in itertools.pairwise(SEEDS)) == 1023
    assert all(g["res"] == [320, 240] for g in GATES.values())


def test_seed_stream_check_is_exact_at_the_tile_count():
    assert not MC.seed_streams_disjoint([278, 279], 320, 240)  # the 278-282 band seeds of v2: shifted by one tile
    assert not MC.seed_streams_disjoint([278, 577], 320, 240)  # 299 apart: tile 299 of seed 278 == tile 0 of 577
    assert MC.seed_streams_disjoint([278, 578], 320, 240)
    assert not MC.seed_streams_disjoint([278, 278], 320, 240)


# --------------------------------------------------------------------------- band math

def test_mean_bands_follow_the_owner_formula():
    sig = [0.10, 0.05, 0.01, 0.02]
    roi = {"excluded": [False, False, False, True], "cycles_sigma": [0.08, 0.04, 0.01, 0.0],
           "cpu_sigma": sig, "gpu_sigma": [0.12, 0.06, 0.02, 0.02]}
    b = MC.mean_bands(roi, n_gate=8, spp_gate=64, spp_ref=1024, n_pin=5)
    # sigma_den = sigma_cycles * sqrt(64/1024) = sigma_cycles / 4: the denominator is ONE 1024 spp render
    want0 = 3 * math.sqrt((0.08 / 4) ** 2 + 0.10 ** 2 / 8)
    assert b["cpu_mean_tol"][0] == pytest.approx(want0) and want0 > 0.02
    assert b["cpu_mean_tol"][2] == 0.02  # floor wins
    assert b["cpu_mean_tol"][3] == 0.0  # excluded channel
    assert b["cpu_mean_pin_tol"][0] == pytest.approx(3 * 0.10 * math.sqrt(1 / 8 + 1 / 5))
    assert b["gpu_mean_pin_tol"][1] == pytest.approx(3 * 0.06 * math.sqrt(1 / 8 + 1 / 5))
    assert b["gpu_cpu_mean_tol"][0] == pytest.approx(max(0.05, 3 * math.sqrt((0.10 ** 2 + 0.12 ** 2) / 8)))
    assert b["gpu_cpu_mean_tol"][2] == 0.05  # twin floor


def test_mean_band_is_tighter_than_the_single_render_band():
    """Averaging N renders can only shrink the statistic's noise: sigma_den/4 + sigma_a/sqrt(8) < the 64 spp pair."""
    for sc in (0.0, 0.01, 0.1):
        for sa in (0.0, 0.01, 0.1):
            roi = {"excluded": [False] * 4, "cycles_sigma": [sc] * 4, "cpu_sigma": [sa] * 4}
            mean = MC.mean_bands(roi, 8, 64, 1024, 5)["cpu_mean_tol"][0]
            single = max(MC.BAND_FLOOR, 3 * math.hypot(sc, sa))
            assert mean <= single + 1e-12


def test_committed_mean_keys_are_recomputed_from_the_stored_sigmas():
    n_pin = len(META["mc_seeds"])
    assert n_pin == 5
    for sid, sc in GATES.items():
        assert sc["n_gate"] == len(SEEDS)
        for roi in sc["roi"]:
            want = MC.mean_bands(roi, len(SEEDS), sc["spp_gate"], sc["spp_reference"], n_pin)
            assert set(want) == set(FLOORS), (sid, roi["name"])
            for k, vec in want.items():
                assert roi[k] == pytest.approx(vec, abs=5e-5), (sid, roi["name"], k)
                assert all(v >= FLOORS[k] or (v == 0.0 and k.endswith("mean_tol") and roi["excluded"][c])
                           for c, v in enumerate(roi[k])), (sid, roi["name"], k)


def test_mean_band_never_exceeds_the_single_render_band_in_the_committed_file():
    for sid, sc in GATES.items():
        for roi in sc["roi"]:
            for leg in ("cpu", "gpu"):
                assert all(m <= s + 5e-5 for m, s in zip(roi[f"{leg}_mean_tol"], roi[f"{leg}_tol"])), (sid, roi["name"], leg)


def test_add_mean_bands_is_idempotent_and_touches_only_its_own_keys(tmp_path):
    src = (MC.CORPUS / "gates_production.toml").read_text(encoding="utf-8")
    drop = tuple(f"{k} =" for k in MC.MEAN_KEYS) + ("n_gate =", "gate_seeds =")
    stripped = "\n".join(ln for ln in src.splitlines() if not ln.startswith(drop) and ln not in MC.MEAN_NOTE) + "\n"
    assert stripped != src and "_mean_tol" not in stripped
    f = tmp_path / "g.toml"
    f.write_text(stripped, encoding="utf-8", newline="\n")
    MC.add_mean_bands(f, SEEDS)
    assert f.read_text(encoding="utf-8") == src  # round trip: the committed file IS the generator's output
    MC.add_mean_bands(f, SEEDS)
    assert f.read_text(encoding="utf-8") == src


def test_full_regeneration_path_emits_the_same_keys(monkeypatch):
    monkeypatch.setattr(MC, "GATE_SEEDS", SEEDS)
    entry = {"v2": {"spp_gate": 64, "spp_reference": 1024}, "crops": {"a": [0, 0, 1, 1]}}
    samples = lambda m, s: [[m * (1 + s * d)] * 4 for d in (-1, 0, 1, 0, 0)]
    res = {"ref": {"a": [1.0, 1.0, 1.0, 1.0]}, "seeds": [1, 2, 3, 4, 5],
           "legs": {"cycles": {"a": samples(1.0, 0.1)}, "cpu": {"a": samples(1.0, 0.05)}, "gpu": {"a": samples(1.0, 0.02)}}}
    (r,) = MC.build_rois(entry, res)
    want = MC.mean_bands(r, len(SEEDS), 64, 1024, 5)
    assert set(MC.MEAN_KEYS) <= set(r) and all(r[k] == want[k] for k in MC.MEAN_KEYS)
    monkeypatch.setattr(MC, "GATE_SEEDS", [])
    (r0,) = MC.build_rois(entry, res)
    assert not set(MC.MEAN_KEYS) & set(r0)  # suites without gate seeds (v2) are unchanged


# --------------------------------------------------------------------------- scoring

def _scene_and_image(sid="prod_wood", factor=1.0, leg="cpu"):
    g = GATES[sid]
    w, h = g["res"]
    img = np.full((h, w, 3), 0.001, dtype=np.float32)
    for roi in g["roi"]:
        den = MC.roi_reference(roi, leg)[0]
        x0, y0, x1, y1 = roi["rect"]
        img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)] = np.array(den[:3], np.float32) * np.float32(factor)
    return g, img


def test_seed_mean_in_band_while_each_render_is_out():
    g, hi = _scene_and_image(factor=1.5)
    _, lo = _scene_and_image(factor=0.5)
    imgs = [hi, lo] * 4
    assert not all(r["ok"] for r in MC.score_material(g, hi, "cpu"))
    assert all(r["ok"] for r in MC.score_material_mean(g, imgs, "cpu"))
    rows = MC.score_material_mean(g, [hi] * 8, "cpu")
    assert not any(r["ok"] for r in rows) and all("sigma_obs" in r for r in rows)


def test_mean_score_uses_the_mean_bands_and_pins():
    g, img = _scene_and_image()
    rows = MC.score_material_mean(g, [img] * 8, "cpu")
    by = {(r["roi"], r["channel"]): r for r in rows}
    for roi in g["roi"]:
        _, tol, pinned = MC.roi_reference(roi, "cpu", mean=True)
        for c, ch in enumerate(MC.CH):
            if roi["excluded"][c]:
                continue
            assert by[(roi["name"], ch)]["tol"] == tol[c] and by[(roi["name"], ch)]["pinned"] == pinned[c]
            assert by[(roi["name"], ch)]["sigma_obs"] == pytest.approx(0.0, abs=1e-12)
    assert any(r["pinned"] for r in rows)  # prod_wood carries pkg327 pins: they take *_mean_pin_tol


def test_wrong_render_count_or_missing_mean_bands_fail_closed():
    g, img = _scene_and_image()
    for n in (1, 5, 7, 9):
        with pytest.raises(ValueError, match="exactly 8"):
            MC.score_material_mean(g, [img] * n, "cpu")
    legacy = {k: v for k, v in g.items() if k != "n_gate"}
    with pytest.raises(ValueError, match="n_gate"):
        MC.score_material_mean(legacy, [img] * 8, "cpu")
    roi0 = {k: v for k, v in g["roi"][0].items() if k != "cpu_mean_tol"}
    with pytest.raises(KeyError):
        MC.score_material_mean({**g, "roi": [roi0]}, [img] * 8, "cpu")


def test_single_render_scoring_is_unchanged():
    g, img = _scene_and_image()
    rows = MC.score_material(g, img, "gpu")
    assert all(r["ok"] for r in rows) and not any("sigma_obs" in r for r in rows)
    for roi in g["roi"]:
        assert MC.roi_reference(roi, "gpu")[1] == MC.roi_reference(roi, "gpu", mean=False)[1]


# --------------------------------------------------------------------------- report instrument

def _paint(work: Path, skip=None):
    for sid in GATES:
        for leg in ("cpu", "gpu"):
            for s in SEEDS:
                if (sid, leg, s) != skip:
                    np.save(work / f"{sid}_{leg}_s{s}.npy", _scene_and_image(sid, leg=leg)[1])


def test_report_fails_closed_on_a_missing_seed_render(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _paint(work, skip=("prod_marble", "gpu", SEEDS[-1]))
    with pytest.raises(FileNotFoundError, match="prod_marble_gpu_s11027"):
        RT.build_production_report(work, tmp_path / "out")
    assert not (tmp_path / "out" / "production_summary.json").exists()


def test_report_rejects_a_seed_list_other_than_the_pinned_gate_seeds(tmp_path):
    with pytest.raises(ValueError, match="pinned gate seeds"):
        RT.build_production_report(tmp_path, tmp_path / "out", seeds=SEEDS[:5])


def test_report_records_seed_list_and_n_and_scores_the_mean(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _paint(work)
    s = RT.build_production_report(work, tmp_path / "out")
    assert s["seeds"] == SEEDS and s["n_seeds"] == 8 and "mean" in s["statistic"]
    assert s["cpu"] == {"pass": 8, "of": 8} and s["gpu"] == {"pass": 8, "of": 8}
    assert (tmp_path / "out" / "production_summary.json").is_file()
    rows = RT.production_xfail_clearance(s)
    assert rows and all(r.endswith("CLEARED") for r in rows)
