"""pkg276 + #840 — GPU wavefront IES and lamp-radius parity.

GPU leg of tests/test_pkg276_ies_spot_profile.py / tests/test_issue840_lamp_radius.py:
the same controlled scenes rendered with set_use_gpu(True). IES and radius > 0
lamps take the out-of-line gpu_lamp_sample_ext path (src/gpu/gpu_nee.cuh), which
evaluates the SAME astroray/ies_eval.h and astroray/lamp_sampling.h code as the
CPU. Gates: GPU radial + azimuth profile vs the Cycles-exact reference within
[0.95, 1.05]; GPU/CPU per-channel ROI mean ratio within 3 % (spec acceptance).
"""

import math

import numpy as np
import pytest

from test_pkg276_ies_spot_profile import (BAND, PROFILES, profile_tables, ref,
                                          render_astroray)


def _require_gpu(astroray):
    if not astroray.__features__.get("cuda", False):
        pytest.skip("CUDA build required")
    r = astroray.Renderer()
    if not getattr(r, "gpu_available", False):
        pytest.skip("no CUDA device")


def _bad(rows, label):
    return ["%s[%g,%g) %s=%.3f" % (label, r["lo"], r["hi"], c, x)
            for r in rows for c, x in zip("RGB", r["ratio"])
            if not math.isnan(x) and not (BAND[0] <= x <= BAND[1])]


@pytest.fixture(scope="module")
def ies_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("pkg276_gpu_ies")
    out = {}
    for name, gen in PROFILES.items():
        p = d / (name + ".ies")
        p.write_text(gen(), encoding="utf-8")
        out[name] = p
    return out


@pytest.mark.gpu
@pytest.mark.parametrize("profile", ["asym360", "wallwasher"])
@pytest.mark.parametrize("kind", ["SPOT", "POINT"])
def test_gpu_ies_profile_matches_reference_and_cpu(astroray_module, ies_files, kind, profile):
    _require_gpu(astroray_module)
    sc = ref.SpotScene(kind=kind)
    path = str(ies_files[profile])
    table = ref.parse_ies(ies_files[profile].read_text(encoding="utf-8"))
    gpu = render_astroray(astroray_module, sc, path, spp=64, use_gpu=True)
    radial, azim = profile_tables(gpu, sc, table)
    bad = _bad(radial, "") + _bad(azim, "azimuth ")
    assert not bad, "GPU %s %s IES off the Cycles reference: %s" % (kind, profile, bad)
    cpu = render_astroray(astroray_module, sc, path, spp=64, use_gpu=False)
    theta, _ = ref.pixel_geometry(sc, divisor=sc.res)
    roi = theta < 27.0
    ratio = gpu[roi].mean(axis=0) / cpu[roi].mean(axis=0)
    assert np.all(np.abs(ratio - 1.0) <= 0.03), ("GPU/CPU ROI mean ratio", ratio)


@pytest.mark.gpu
@pytest.mark.parametrize("radius,soft", [(0.0, True), (0.05, True), (0.1, True),
                                         (0.25, True), (1.0, True), (1.0, False)])
@pytest.mark.parametrize("kind", ["POINT", "SPOT"])
def test_gpu_lamp_radius_matches_reference(astroray_module, kind, radius, soft):
    _require_gpu(astroray_module)
    sc = ref.SpotScene(kind=kind, radius=radius, soft_falloff=soft)
    gpu = render_astroray(astroray_module, sc, "", spp=64, use_gpu=True)
    div = sc.res  # #845: engine raster divisor is res (was res - 1)
    refimg = ref.radiance(sc, None, sub=2, divisor=div)
    theta, _ = ref.pixel_geometry(sc, divisor=div)
    rows = ref.binned_ratio(gpu, refimg, theta, np.arange(0.0, 34.0, 2.0), min_ref_frac=0.05)
    assert sum(1 for r in rows if not math.isnan(r["ratio"][1])) >= 10
    bad = _bad(rows, "")
    assert not bad, "GPU %s r=%g soft=%s off the Cycles reference: %s" % (kind, radius, soft, bad)
