"""pkg327 Phase B: per-channel expected-divergence pins in ``gates_production.toml`` (pure Python, no Blender).

A pin moves only its listed channels to Astroray's own seed mean; every other channel of the ROI still compares
to Cycles, and no pin exists without an arbitration artefact in the repo (owner 2026-10-31).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tomllib

from benchmarks.reference_corpus import mc_tolerance as MC

REPO = Path(__file__).resolve().parents[1]
GATES = tomllib.loads((MC.CORPUS / "gates_production.toml").read_text(encoding="utf-8"))["scenes"]
KNOWN = tomllib.loads((MC.CORPUS / "provisional_production.toml").read_text(encoding="utf-8"))
PINNED = [(sid, roi) for sid, g in GATES.items() for roi in g["roi"] if "expected_divergence" in roi]


def _on(roi, leg):
    return leg in roi.get("pin_legs", ("cpu", "gpu"))


def _image(g: dict, leg: str, scale: dict) -> np.ndarray:
    """Every ROI painted at its reference means (per channel: Cycles or the pin); ``scale`` = {roi: [r, g, b]}."""
    w, h = g["res"]
    img = np.full((h, w, 3), 0.001, dtype=np.float32)
    for roi in g["roi"]:
        x0, y0, x1, y1 = roi["rect"]
        den = np.array(MC.roi_reference(roi, leg)[0][:3], dtype=np.float32)
        img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)] = den * np.array(scale.get(roi["name"], [1, 1, 1]), np.float32)
    return img


def _rows(sid: str, leg: str, scale: dict) -> dict:
    rows = MC.score_material(GATES[sid], _image(GATES[sid], leg, scale), leg)
    return {(r["roi"], r["channel"]): r for r in rows}


def test_pins_exist_and_are_all_per_channel():
    assert PINNED, "pkg327 Phase B pins missing"
    for sid, roi in PINNED:
        assert roi["pin_channels"], f"{sid}/{roi['name']}: whole-ROI pin (pkg327: per channel only)"
        assert set(roi["pin_channels"]) <= {"r", "g", "b"}, f"{sid}/{roi['name']}: luminance is never pinned"


def test_every_pin_names_an_existing_arbitration_artefact():
    for sid, roi in PINNED:
        art = REPO / roi["arbitration"]
        assert art.is_file(), f"{sid}/{roi['name']}: arbitration artefact {roi['arbitration']} not in the repo"
        assert "smooth" in art.name, f"{sid}/{roi['name']}: pins cite the smooth-HDRI proxies, not the raw ones"
        assert "pkg327" in roi["expected_divergence"]


def test_pins_match_the_divergence_rows_that_generate_them():
    """mc_tolerance writes pin_channels/arbitration from provisional_production.toml [[divergence]] rows."""
    rows = {(d["scene"], d["roi"]): d for d in KNOWN.get("divergence", [])}
    assert set(rows) == {(sid, roi["name"]) for sid, roi in PINNED}
    for sid, roi in PINNED:
        d = rows[(sid, roi["name"])]
        assert roi["pin_channels"] == d["channels"] and roi["arbitration"] == d["arbitration"]
        assert roi.get("pin_legs") == d.get("legs")
        assert roi["expected_divergence"] == d["reason"]


@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_a_pin_moves_only_its_channels(leg):
    for sid, roi in PINNED:
        den, tol, pinned = MC.roi_reference(roi, leg)
        for c, ch in enumerate(MC.CH):
            on_pin = ch in roi["pin_channels"] and _on(roi, leg)
            assert pinned[c] == on_pin
            assert den[c] == (roi[f"{leg}_mean"][c] if on_pin else roi["cycles_mean"][c])
            assert tol[c] == (roi[f"{leg}_pin_tol"][c] if on_pin else roi[f"{leg}_tol"][c])


@pytest.mark.parametrize("leg", ["cpu", "gpu"])
def test_unpinned_channels_of_a_pinned_roi_still_compare_to_cycles(leg):
    sid, roi = next((s, r) for s, r in PINNED if len(r["pin_channels"]) < 3 and _on(r, leg))
    free = [c for c, ch in enumerate("rgb") if ch not in roi["pin_channels"] and not roi["excluded"][c]]
    assert free, "no unpinned colour channel to check"
    c = free[0]
    ch = "rgb"[c]
    tol = roi[f"{leg}_tol"][c]
    off = [1.0, 1.0, 1.0]
    off[c] = 1.0 + 2.0 * tol  # outside the Cycles band
    assert not _rows(sid, leg, {roi["name"]: off})[(roi["name"], ch)]["ok"]
    assert _rows(sid, leg, {})[(roi["name"], ch)]["ok"]
    # the pinned channel at the same relative offset is judged against the pin mean, not against Cycles
    p = next(i for i, x in enumerate("rgb") if x in roi["pin_channels"])
    inside = [1.0, 1.0, 1.0]
    inside[p] = 1.0 + 0.5 * roi[f"{leg}_pin_tol"][p]
    assert _rows(sid, leg, {roi["name"]: inside})[(roi["name"], "rgb"[p])]["ok"]
    outside = [1.0, 1.0, 1.0]
    outside[p] = 1.0 + 2.0 * roi[f"{leg}_pin_tol"][p]
    assert not _rows(sid, leg, {roi["name"]: outside})[(roi["name"], "rgb"[p])]["ok"]


def test_a_pin_limited_to_one_leg_leaves_the_other_leg_on_cycles():
    roi = {"name": "x", "expected_divergence": "d", "pin_channels": ["b"], "pin_legs": ["cpu"],
           "cycles_mean": [1, 1, 1, 1], "cpu_mean": [2, 2, 2, 2], "gpu_mean": [3, 3, 3, 3],
           "cpu_pin_tol": [.1] * 4, "gpu_pin_tol": [.1] * 4, "cpu_tol": [.5] * 4, "gpu_tol": [.5] * 4}
    assert MC.roi_reference(roi, "cpu")[2] == [False, False, True, False]
    assert MC.roi_reference(roi, "gpu") == ([1, 1, 1, 1], [.5] * 4, [False] * 4)


def test_whole_roi_pins_of_other_gate_files_keep_working():
    roi = {"name": "x", "expected_divergence": "d", "cycles_mean": [1, 1, 1, 1], "cpu_mean": [2, 2, 2, 2],
           "cpu_pin_tol": [.1] * 4, "cpu_tol": [.5] * 4}
    assert MC.roi_reference(roi, "cpu") == ([2, 2, 2, 2], [.1] * 4, [True] * 4)
    del roi["expected_divergence"]
    assert MC.roi_reference(roi, "cpu")[2] == [False] * 4


def test_channels_pin_without_arbitration_is_refused(tmp_path, monkeypatch):
    known = tmp_path / "known.toml"
    known.write_text('[[divergence]]\nscene = "prod_wood"\nroi = "lower"\nreason = "r"\nchannels = ["b"]\n', encoding="utf-8")
    monkeypatch.setattr(MC, "KNOWN", known)
    manifest = {"scenes": {"prod_wood": {"v2": {"divergence": {}}, "crops": {}}}}
    with pytest.raises(SystemExit, match="arbitration"):
        MC.scene_entry(manifest, "prod_wood")
