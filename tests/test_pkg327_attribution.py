"""pkg327 Phase A: the attribution tooling's pure-python parts (no Blender, no Mitsuba)."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
ARB = REPO / "benchmarks" / "reference_corpus" / "arbitration"
sys.path[:0] = [str(ARB), str(REPO / "benchmarks" / "reference_corpus")]

import attribution as AT  # noqa: E402
import mitsuba_scenes as MS  # noqa: E402


def test_bowl_is_an_open_outward_sphere_cap():
    p = MS.PARAMS["arb_chroma_bowl"]["bowl"]
    tris = np.array(MS.bowl_triangles(p), dtype=float)
    c = np.array(p["center"])
    assert tris[..., 2].max() <= c[2] + p["cut_z"] + 1e-9
    for a, b, d in tris:
        assert np.cross(b - a, d - a) @ ((a + b + d) / 3 - c) > 0  # outward winding
        assert np.allclose(np.linalg.norm([a - c, b - c, d - c], axis=1), p["radius"])
    # open at the top: the area is that of the cap of height r + cut_z (Archimedes), within the facet error
    area = sum(np.linalg.norm(np.cross(b - a, d - a)) / 2.0 for a, b, d in tris)
    assert area == pytest.approx(2.0 * math.pi * p["radius"] * (p["radius"] + p["cut_z"]), rel=2e-3)


def test_chroma_proxies_have_a_world_or_hdri_and_need_no_anchor():
    for sid in MS.CHROMA_SCENES:
        p = MS.PARAMS[sid]
        assert ("world" in p) != ("hdri" in p) and p["anchor"] is None and "lamp" not in p and "sun" not in p
        assert ("stage" in p) == (sid in AT.HDRI_PROXIES and sid != "arb_chroma_warm_hdri")
    sun = MS.PARAMS["arb_chroma_patches"]["stage"]["sun"]  # the production stage sun: direction to the sun (0.55, -0.35, 0.75)
    assert -np.array(MS.sun_direction(sun)) == pytest.approx(np.array((0.55, -0.35, 0.75)) / math.sqrt(0.55 ** 2 + 0.35 ** 2 + 0.75 ** 2))


def test_variant_specs_name_every_control_and_the_1199_recipe():
    for scene in AT.TARGETS:
        v = AT.variant_specs(scene)
        assert {"baseline", "albedo_grey", "world_flat_white", "grey_flat"} <= set(v)
        assert v["baseline"] == []
    lp = AT.variant_specs("prod_light_path")
    assert "lambertian" in lp and sum(k.startswith("rsweep_") for k in lp) >= 4


def test_ratio_of_means_and_standard_error():
    num = np.array([[2.0, 2.0, 2.0, 2.0], [2.2, 2.2, 2.2, 2.2], [1.8, 1.8, 1.8, 1.8]])
    den = np.array([[1.0, 1.0, 1.0, 1.0], [1.1, 1.1, 1.1, 1.1], [0.9, 0.9, 0.9, 0.9]])
    r, se = AT._ratio(num, den)
    assert r == pytest.approx([2.0] * 4)
    assert se == pytest.approx([2.0 * math.sqrt(2) * (0.2 / math.sqrt(3) / 2.0)] * 4)
