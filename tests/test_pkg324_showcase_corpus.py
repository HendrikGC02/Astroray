"""pkg324 - spectral showcase corpus v1.

Fast part (CI, numpy + PIL only, no Blender, no engine):
  * manifest schema and the committed .blend files' sha256;
  * the analytic checks themselves (Airy thin film, Sellmeier prism edge separation, furnace, bounce cap) against
    known closed forms, and non-vacuity: a synthetic render built from the prediction passes, a perturbed one fails;
  * the driver's sheet writer and the runner's ``--preset spectral`` / render_leg ``--max-bounces`` wiring.

Slow part (opt-in: ASTRORAY_PKG324_BLENDER=1 + Blender 5.2 + a staged addon / CPU build in ASTRORAY_PYD_DIR; the
``gpu`` tests additionally need ASTRORAY_PKG324_GPU=1 and run under the GPU lock):
  * the scene digest of every committed .blend equals the manifest's (the .blend BYTES are not reproducible across
    Blender sessions, so the content digest is the determinism contract) and a fresh rebuild reproduces it;
  * thin-film ladder: sphere hue vs the Airy prediction within 10 deg at 300/600/900 nm;
  * prism fan: red-to-blue edge separation within 5 % of the Sellmeier ray-trace prediction;
  * film-layer white furnace: lossless to 3 %.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.showcase.spectral import build_scenes, checks, driver  # noqa: E402

MANIFEST = REPO / "benchmarks" / "showcase" / "spectral" / "manifest.json"
BLENDER = Path(os.environ.get("BLENDER_EXE", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
PYD_DIR = os.environ.get("ASTRORAY_PYD_DIR", "")
OPT_IN = os.environ.get("ASTRORAY_PKG324_BLENDER") == "1" and BLENDER.is_file() and bool(PYD_DIR)
GPU_OPT_IN = OPT_IN and os.environ.get("ASTRORAY_PKG324_GPU") == "1"
needs_blender = pytest.mark.skipif(not OPT_IN, reason="set ASTRORAY_PKG324_BLENDER=1, ASTRORAY_PYD_DIR and install Blender 5.2")
needs_gpu = pytest.mark.skipif(not GPU_OPT_IN, reason="set ASTRORAY_PKG324_GPU=1 (run under scripts/build/gpu_locked_run.py)")


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Fast: manifest + committed scenes
# --------------------------------------------------------------------------- #
@pytest.mark.cpu
def test_manifest_schema(manifest):
    assert manifest["schema"] == build_scenes.SCHEMA
    assert manifest["seed"] == build_scenes.SEED != 0  # 0 is the engine's random sentinel
    assert list(manifest["scenes"]) == build_scenes.SCENE_IDS + ["sp09_classroom"]
    kinds = {"airy_thin_film", "prism_fan_sellmeier", "white_furnace_energy", "bounce_cap_dead_spots",
             "see_check_scene", "roi_parity_vs_cycles", "none"}
    for sid, e in manifest["scenes"].items():
        rx, ry = e["res"]
        assert rx <= 640 and ry <= 640 and rx * ry <= 640 * 480, sid  # small renders (lane rule 12)
        assert isinstance(e["spp"], int) and e["spp"] > 0 and e["seed"] == manifest["seed"], sid
        assert e["check"]["kind"] in kinds, sid
        assert e["cycles"] in ("full", "no_dispersion"), sid
        for name, r in e["rois"].items():
            assert len(r) == 4 and 0.0 <= r[0] < r[2] <= 1.0 and 0.0 <= r[1] < r[3] <= 1.0, (sid, name)
    for sid in ("sp01_thinfilm_ladder", "sp02b_prism_check", "sp04b_film_furnace"):
        assert manifest["scenes"][sid]["check"]["kind"] != "none"
    assert manifest["scenes"]["sp07_tumbler_bounce_cap"]["reference_variant"] == "b64"
    assert [v["max_bounces"] for v in manifest["scenes"]["sp07_tumbler_bounce_cap"]["variants"]] == [4, 8, 12, 64]
    assert len(manifest["scenes"]["sp08_shader_ball_bench"]["rois"]) == 21 == len(manifest["scenes"]["sp08_shader_ball_bench"]["tiles"])
    assert sum(1 for e in manifest["scenes"].values() if e.get("gallery", True)) == 9  # nine gallery scenes


@pytest.mark.cpu
def test_committed_blend_sha256(manifest):
    for sid, e in manifest["scenes"].items():
        f = REPO / e["blend_path"]
        if sid == "sp09_classroom":  # linked, never committed: verify only when the local copy is present
            assert e["linked_not_copied"] and e["licence"] == "CC0 1.0"
            if f.is_file():
                assert hashlib.sha256(f.read_bytes()).hexdigest() == e["sha256"]
            continue
        assert f.is_file(), f"{sid}: {f} not committed"
        assert hashlib.sha256(f.read_bytes()).hexdigest() == e["sha256"], f"{sid}: .blend changed without a manifest update"
        assert len(e["scene_digest"]) == 64


# --------------------------------------------------------------------------- #
# Fast: the analytic checks against closed forms
# --------------------------------------------------------------------------- #
@pytest.mark.cpu
def test_airy_closed_forms():
    lam = np.array([450.0, 550.0, 650.0])
    n_s = 1.5
    fresnel = ((1.0 - n_s) / (1.0 + n_s)) ** 2
    assert checks.airy_reflectance(lam, 0.0, 1.33, n_s) == pytest.approx(fresnel, rel=1e-9)  # no film = bare substrate
    n_f = math.sqrt(n_s)  # quarter-wave anti-reflection: R = 0 at lambda0 = 4 n d
    lam0 = 550.0
    assert checks.airy_reflectance(np.array([lam0]), lam0 / (4 * n_f), n_f, n_s)[0] == pytest.approx(0.0, abs=1e-12)
    # half-wave film is absent (R == bare substrate) at lambda = 2 n d
    d = 400.0
    assert checks.airy_reflectance(np.array([2 * 1.33 * d]), d, 1.33, n_s)[0] == pytest.approx(fresnel, rel=1e-9)
    # lossless: R <= 1, and oblique incidence stays physical
    assert (checks.airy_reflectance(lam, 300.0, 1.33, 2.0, theta_deg=60.0) <= 1.0).all()


@pytest.mark.cpu
def test_airy_hues_are_distinct_at_the_ladder_thicknesses(manifest):
    chk = manifest["scenes"]["sp01_thinfilm_ladder"]["check"]
    hues = [checks.hue_deg(checks.spectrum_to_linear_srgb(
        lambda lam, d=d: checks.airy_reflectance(lam, d, chk["film_ior"], chk["substrate_ior"])))
        for d in chk["film_nm"].values()]
    for i in range(3):
        for j in range(i + 1, 3):
            assert checks.hue_diff_deg(hues[i], hues[j]) > 5 * chk["tolerance_deg"], hues  # the 10 deg gate is not vacuous
    assert checks.spectrum_to_linear_srgb(lambda lam: np.ones_like(lam)) == pytest.approx([1.0, 1.0, 1.0], abs=2e-3)


@pytest.mark.cpu
def test_sellmeier_and_prism_geometry(manifest):
    assert checks.sellmeier_n(587.56, "bk7") == pytest.approx(1.5168, abs=1e-4)  # Schott nd
    assert checks.sellmeier_n(587.56, "flint_sf11") == pytest.approx(1.7847, abs=2e-4)
    chk = manifest["scenes"]["sp02b_prism_check"]["check"]
    n = float(checks.sellmeier_n(587.56, chk["preset"]))
    assert chk["incidence_deg"] == pytest.approx(math.degrees(math.asin(n * math.sin(math.radians(30.0)))), abs=0.05)
    # the traced exit direction at the centre ray equals the closed-form minimum deviation 2 asin(n sin(A/2)) - A
    lam, lo, hi = checks.prism_edge_profile(chk, np.array([550.0]))
    dev = 2 * math.asin(float(checks.sellmeier_n(550.0, "bk7")) * 0.5) - math.radians(60.0)
    assert math.degrees(dev) == pytest.approx(38.65, abs=0.4)
    assert -chk["exit_dir_deg"] == pytest.approx(math.degrees(2 * math.asin(n * 0.5) - math.radians(60.0)), abs=0.01)
    assert np.isfinite(lo[0]) and hi[0] > lo[0]
    # dispersion: blue is deviated more than red (u grows to the right: red edge left of blue)
    lam, lo, hi = checks.prism_edge_profile(chk, np.array([450.0, 650.0]))
    assert lo[0] > lo[1]


def _prism_synthetic(entry, du_blue_m=0.0):
    chk = entry["check"]
    pred = checks.prism_fan_prediction(chk)
    pts = sorted((float(k), v) for k, v in chk["px_at_s_m"].items())
    slope = -(pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])
    w, h = entry["res"]
    u = (np.arange(w) - pts[1][1]) / slope
    img = np.zeros((h, w, 3))
    for c, uc in enumerate(pred["u_cross_m"]):
        shift = du_blue_m if c == 2 else 0.0
        img[:, :, c] = (1.0 / (1.0 + np.exp(-(u - uc - shift) / 0.004)))[None, :]
    return img


@pytest.mark.cpu
def test_diamond_scene_uses_peter_1923_coefficients():
    B, C = build_scenes.DIAMOND_B, build_scenes.DIAMOND_C
    l2 = (587.56e-3) ** 2
    assert math.sqrt(1 + sum(b * l2 / (l2 - c) for b, c in zip(B, C))) == pytest.approx(2.417, abs=2e-3)
    assert C[0] == pytest.approx(0.175 ** 2) and C[1] == pytest.approx(0.106 ** 2)


@pytest.mark.cpu
@pytest.mark.xfail(strict=True, reason="#1155: the engine's diamond Sellmeier preset has C = (0.0175, 0.106) (n_d = 2.758); "
                                        "remove this marker in the fix PR")
def test_engine_diamond_preset_matches_peter1923():
    text = (REPO / "include" / "astroray" / "optical_presets.h").read_text(encoding="utf-8")
    import re
    m = re.search(r'\{"diamond", [\d.]+f,\s*\{([^}]*)\},\s*\{([^}]*)\}', text)
    B = [float(v.strip().rstrip("f")) for v in m.group(1).split(",")]
    C = [float(v.strip().rstrip("f")) for v in m.group(2).split(",")]
    l2 = (587.56e-3) ** 2
    assert math.sqrt(1 + sum(b * l2 / (l2 - c) for b, c in zip(B, C))) == pytest.approx(2.417, abs=2e-3)


@pytest.mark.cpu
def test_prism_check_is_non_vacuous(manifest):
    e = manifest["scenes"]["sp02b_prism_check"]
    ok = checks.prism_fan_check(_prism_synthetic(e), e)
    assert ok["pass"] and ok["rel_err"] < 0.01, ok
    sep_m = 1e-3 * ok["pred_sep_RB_mm"]
    bad = checks.prism_fan_check(_prism_synthetic(e, du_blue_m=0.10 * sep_m), e)  # blue edge 10 % off
    assert not bad["pass"] and bad["rel_err"] == pytest.approx(0.10, abs=0.02), bad
    assert 0.5 < ok["pred_sep_RB_deg"] < 1.2  # ~0.86 deg for BK7 R-B at the 50 % channel crossings


@pytest.mark.cpu
def test_airy_check_is_non_vacuous(manifest):
    e = manifest["scenes"]["sp01_thinfilm_ladder"]
    chk = e["check"]
    img = np.full((360, 640, 3), 0.1)
    for label, d_nm in chk["film_nm"].items():
        rgb = checks.spectrum_to_linear_srgb(lambda lam, d=d_nm: checks.airy_reflectance(
            lam, d, chk["film_ior"], chk["substrate_ior"])) * 0.1
        x0, y0, x1, y1 = e["rois"][label]
        img[int(y0 * 360):int(y1 * 360) + 1, int(x0 * 640):int(x1 * 640) + 1] = rgb
    assert checks.airy_thin_film_check(img, e)["pass"]
    # rotate the Film600 colour 25 deg in hue: must fail the 10 deg gate
    import colorsys
    x0, y0, x1, y1 = e["rois"]["Film600"]
    sl = (slice(int(y0 * 360), int(y1 * 360) + 1), slice(int(x0 * 640), int(x1 * 640) + 1))
    h, s, v = colorsys.rgb_to_hsv(*img[sl][0, 0])
    img[sl] = colorsys.hsv_to_rgb((h + 25.0 / 360.0) % 1.0, s, v)
    res = checks.airy_thin_film_check(img, e)
    assert not res["pass"] and res["Film600"]["hue_err_deg"] == pytest.approx(25.0, abs=1.0)


@pytest.mark.cpu
def test_furnace_and_bounce_cap_checks(manifest):
    e = manifest["scenes"]["sp04b_film_furnace"]
    assert checks.furnace_check(np.ones((128, 256, 3)), e)["pass"]
    assert not checks.furnace_check(np.full((128, 256, 3), 0.93), e)["pass"]
    t = manifest["scenes"]["sp07_tumbler_bounce_cap"]
    ref = np.full((480, 640, 3), 0.5)
    low = ref.copy()
    x0, y0, x1, y1 = t["rois"]["tumbler"]
    low[int(y0 * 480):int(y1 * 480), int(x0 * 640):int((x0 + (x1 - x0) / 2) * 640)] = 0.01  # half the ROI goes dark
    r = checks.bounce_cap_check({"b04": low, "b64": ref}, t)
    assert r["b64"]["dark_pixel_fraction"] == 0.0 and r["b64"]["roi_mean_ratio_vs_ref"] == 1.0 == r["b64"]["roi_median_ratio_vs_ref"]
    assert r["b04"]["dark_pixel_fraction"] == pytest.approx(0.5, abs=0.02)
    assert r["b04"]["roi_mean_ratio_vs_ref"] < 0.6


# --------------------------------------------------------------------------- #
# Fast: driver sheets and wiring
# --------------------------------------------------------------------------- #
@pytest.mark.cpu
def test_sheet_writer_stamps_and_orders_columns(manifest, tmp_path):
    from PIL import Image
    sid = "sp07_tumbler_bounce_cap"
    e = manifest["scenes"][sid]
    rng = np.random.default_rng(324)
    results = {sid: {}}
    for v in e["variants"]:
        for leg in ("cpu", "cycles"):
            stem = driver._stem(tmp_path, sid, v["id"], leg)
            stem.parent.mkdir(parents=True, exist_ok=True)
            np.save(stem.with_suffix(".npy"), rng.random((48, 64, 3)).astype(np.float32))
            results[sid].setdefault(v["id"], {})[leg] = {"ok": True, "render_s": 1.5}
    sheet = driver.build_sheet(sid, e, tmp_path, results)
    im = Image.open(sheet)
    assert im.width == 2 * driver.PANEL_W + 14 and im.height > 4 * 300  # two legs wide, four bounce caps tall
    assert (np.asarray(im) != np.asarray(im)[0, 0]).any()


@pytest.mark.cpu
def test_runner_and_render_leg_wiring():
    out = subprocess.run([sys.executable, "-m", "benchmarks.showcase.runner", "--help"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8", timeout=180, env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
    assert "--preset" in out and "spectral" in out
    src = (REPO / "benchmarks" / "blender_parity" / "render_leg.py").read_text(encoding="utf-8")
    assert "--max-bounces" in src and "transmission_bounces" in src
    assert set(driver.LEGS) == {"cpu", "gpu", "cycles", "cycles_gpu"}
    sc = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenes"]
    assert [v["id"] for v in driver.scene_variants(sc["sp07_tumbler_bounce_cap"])] == ["b04", "b08", "b12", "b64"]
    assert driver.scene_variants(sc["sp01_thinfilm_ladder"]) == [{"id": "default"}]


# --------------------------------------------------------------------------- #
# Slow: Blender (opt-in)
# --------------------------------------------------------------------------- #
def _digest(blend: Path) -> str:
    out = subprocess.run([str(BLENDER), "-b", "--factory-startup", "--python", str(REPO / "benchmarks/showcase/spectral/build_scenes.py"),
                          "--", "--digest", str(blend), "--addon-dir", PYD_DIR], capture_output=True, text=True, timeout=300).stdout
    line = [l for l in out.splitlines() if l.startswith("SCENE_DIGEST ")]
    assert line, out[-2000:]
    return line[0].split()[1]


@pytest.mark.serial
@pytest.mark.slow
@needs_blender
@pytest.mark.parametrize("sid", ["sp01_thinfilm_ladder", "sp02b_prism_check", "sp04b_film_furnace"])
def test_scene_digest_reproduces(manifest, sid, tmp_path):
    e = manifest["scenes"][sid]
    assert _digest(REPO / e["blend_path"]) == e["scene_digest"]  # committed file == manifest
    subprocess.run([sys.executable, str(REPO / "benchmarks/showcase/spectral/build_scenes.py"), "--scene", sid, "--addon-dir", PYD_DIR,
                    "--out-dir", str(tmp_path), "--manifest", str(tmp_path / "m.json")], check=True, capture_output=True, timeout=300)
    assert json.loads((tmp_path / "m.json").read_text())["scenes"][sid]["scene_digest"] == e["scene_digest"]  # builder deterministic


def _render_and_check(manifest, sid, leg, tmp_path):
    e = manifest["scenes"][sid]
    variants = driver.scene_variants(e)
    imgs = {}
    for v in variants:
        r = driver.render_leg(sid, e, v, leg, tmp_path, PYD_DIR, None, 1.0, 8, True)
        assert r["ok"], r
        imgs[v["id"]] = np.load(driver._stem(tmp_path, sid, v["id"], leg).with_suffix(".npy"))
    return checks.run_check(e, imgs)


@pytest.mark.serial
@pytest.mark.slow
@needs_blender
@pytest.mark.parametrize("leg", ["cpu", "cycles"])
def test_thin_film_ladder_hue_vs_airy_cpu(manifest, leg, tmp_path):
    res = _render_and_check(manifest, "sp01_thinfilm_ladder", leg, tmp_path)
    print({k: v["hue_err_deg"] for k, v in res.items() if isinstance(v, dict)})
    assert res["pass"], res  # <= 10 deg at 300 / 600 / 900 nm


@pytest.mark.serial
@pytest.mark.slow
@needs_blender
def test_prism_fan_separation_vs_sellmeier_cpu(manifest, tmp_path):
    res = _render_and_check(manifest, "sp02b_prism_check", "cpu", tmp_path)
    print(res)
    assert res["pass"], res  # R-to-B separation within 5 %


@pytest.mark.serial
@pytest.mark.slow
@needs_blender
@pytest.mark.parametrize("leg", ["cpu", "cycles"])
def test_film_layer_furnace_cpu(manifest, leg, tmp_path):
    res = _render_and_check(manifest, "sp04b_film_furnace", leg, tmp_path)
    assert res["pass"], res


@pytest.mark.gpu
@pytest.mark.slow
@needs_gpu
@pytest.mark.parametrize("sid", ["sp01_thinfilm_ladder", "sp02b_prism_check", "sp04b_film_furnace"])
def test_analytic_checks_gpu(manifest, sid, tmp_path):
    res = _render_and_check(manifest, sid, "gpu", tmp_path)
    print(sid, res)
    assert res["pass"], res
