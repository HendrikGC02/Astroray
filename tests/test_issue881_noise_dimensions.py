"""#881 - Noise Texture parity with Blender/Cycles.

Two defects made Astroray's Noise differ from Cycles (corr 0.73 on the y847 fixture):
  * a Noise Fac output wired straight into a colour socket loaded the Color triple
    (fac, noise+offset3, noise+offset4) instead of grey Fac (Cycles svm/noisetex.h
    stores `value` on the Fac socket); the op-VM path already broadcast .x;
  * noise_dimensions 1D / 2D / 4D (and W) were evaluated as 3D.

The evaluator (astroray/procedural_tex.h, Cycles kernel/svm/noise.h BSD-3-Clause,
fractal_noise.h / noisetex.h Apache-2.0) is checked against Blender's own Noise
Texture at exact points: tests/data/issue881_noise_blender_reference.json, written by
tests/fixtures/gen_issue881_noise_reference.py (Blender 5.2 Geometry Nodes, the
blenlib twin of the Cycles kernel). The end-to-end Cycles render probe is in the PR.
"""
import json
from pathlib import Path

import pytest

astroray = pytest.importorskip("astroray")

_REF = json.loads((Path(__file__).parent / "data" / "issue881_noise_blender_reference.json")
                  .read_text(encoding="utf-8"))
_TYPES = {"FBM": 0, "MULTIFRACTAL": 1, "HYBRID_MULTIFRACTAL": 2,
          "RIDGED_MULTIFRACTAL": 3, "HETERO_TERRAIN": 4}
# Measured worst |engine - Blender| over all 28 cases: 1.1e-4 (2D hybrid); 1D/4D
# agree to <= 6e-7 without distortion. Float32 operation order, not semantics.
_TOL = 5e-4


def _params(case, w, fac_only=False):
    return {"scale": case["scale"], "detail": case["detail"], "roughness": case["roughness"],
            "lacunarity": case["lacunarity"], "offset": case["offset"], "gain": case["gain"],
            "distortion": case["distortion"], "noise_type": float(_TYPES[case["type"]]),
            "normalize": 1.0 if case["normalize"] else 0.0,
            "dimensions": float(int(case["dims"][0])), "w": w,
            "fac_only": 1.0 if fac_only else 0.0}


@pytest.mark.parametrize("idx", range(len(_REF["results"])),
                         ids=[f"{r['case']['dims']}-{r['case']['type']}-d{r['case']['distortion']}"
                              f"-n{int(r['case']['normalize'])}" for r in _REF["results"]])
def test_noise_matches_blender_reference(idx):
    r = astroray.Renderer()
    res = _REF["results"][idx]
    worst = 0.0
    for i, (p, w) in enumerate(zip(_REF["points"], _REF["w"])):
        v = r.eval_texture_at_3d("noise_perlin", _params(res["case"], w), *p)
        exp = [res["fac"][i]] + list(res["color"][i][1:3])
        worst = max(worst, max(abs(a - b) for a, b in zip(v[:3], exp)))
    assert worst < _TOL, f"{res['case']}: max |engine - Blender| = {worst:.3g}"


def test_fac_only_is_grey_fac():
    r = astroray.Renderer()
    case = _REF["results"][0]["case"]
    for dims in ("1D", "2D", "3D", "4D"):
        c = dict(case, dims=dims)
        for p, w in zip(_REF["points"][:6], _REF["w"][:6]):
            full = r.eval_texture_at_3d("noise_perlin", _params(c, w), *p)
            grey = r.eval_texture_at_3d("noise_perlin", _params(c, w, fac_only=True), *p)
            assert grey[0] == grey[1] == grey[2] == full[0]


def test_one_d_ignores_the_vector():
    r = astroray.Renderer()
    case = dict(_REF["results"][0]["case"], dims="1D")
    a = r.eval_texture_at_3d("noise_perlin", _params(case, 0.37), 0.1, 0.2, 0.3)
    b = r.eval_texture_at_3d("noise_perlin", _params(case, 0.37), 2.5, -1.0, 7.0)
    assert a[:3] == b[:3]
