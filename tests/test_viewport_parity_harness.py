#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg81 — viewport-parity harness smoke test.

Runs ``benchmarks/viewport_parity/run.py --smoke`` against a tiny scene
in-process (no Blender), and validates the JSON output's shape. The
smoke gate is "harness completes and emits a config block" — we don't
assert on absolute timings (CI wall times are noisy and the gate-numbers
in pkg81 are owner-station gates, not CI gates).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pkg81_harness_smoke(tmp_path, astroray_module):
    sys.path.insert(0, str(REPO_ROOT / "benchmarks" / "viewport_parity"))
    import run as harness  # noqa: WPS433

    rc = harness.main([
        "--smoke",
        "--cpu-only",
        "--no-h3",  # smoke skips OIDN — keeps the test fast
        "--with-transform-edit",  # exercise both code paths in CI
        "--out", str(tmp_path),
        "--tag", "smoke",
    ])
    assert rc == 0
    json_path = tmp_path / "smoke.json"
    html_path = tmp_path / "summary.html"
    assert json_path.exists()
    assert html_path.exists()

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["schema"] == "astroray.viewport_parity.v1"
    assert doc["package"] == "pkg81"
    # 1 tris × 1 backend × 1 oidn × 2 paths = 2 configs.
    assert len(doc["configs"]) == 2, doc["configs"]
    paths = sorted(c["config"]["path"] for c in doc["configs"])
    assert paths == ["camera_only", "transform_edit"]
    cam_cfg = next(c for c in doc["configs"]
                   if c["config"]["path"] == "camera_only")
    xform_cfg = next(c for c in doc["configs"]
                     if c["config"]["path"] == "transform_edit")
    cfg = cam_cfg
    # Required fields used by the diagnosis report.
    for key in (
        "frame", "render", "dispatch",
        "first_minus_steady_ms",
        "h1_upload_geometry_calls_per_frame_max",
        "h2_spp_trace_unique_values",
        "viewport_perf_stats",
        "config",
    ):
        assert key in cfg, key
    assert cfg["frame"]["n"] == 6
    # camera_only: the addon's view_draw never reaches the dispatcher
    # for pure camera moves, so uploader call counts MUST be zero.
    # This is the H1 baseline.
    assert cam_cfg["h1_upload_geometry_calls_per_frame_total"] == 0
    assert cam_cfg["h1_upload_materials_calls_per_frame_total"] == 0
    # transform_edit: every tick fires a transform-only depsgraph
    # update; with the single-level BVH this currently promotes to
    # one upload_geometry per frame (pkg56-C documented limitation).
    assert xform_cfg["h1_upload_geometry_calls_per_frame_max"] >= 1
