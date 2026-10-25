"""pkg321 (#1089) -- counterfactual probes for the DROPPED-SILENT rows of the gate (b) audit.

Three layers:

1. Pure addon logic (stub bpy, CI-safe): every real drop the probes proved is NAMED in the DegradationReport, only
   when the input is actually used (linked / non-default), and an untouched node stays quiet.
2. Table consistency (no Blender): `scripts/generate_blender_parity_matrix.py` credits a row only with a probe that
   moves pixels and annotates a drop only with a probe that does not (PROBE_VERDICT below is the single source),
   and the committed `coverage_matrix.json` carries exactly those classifications.
3. The probes themselves (real `blender --background`, CPU, skips without Blender or an engine .pyd): one scene per
   family, variant A vs variant B differing in ONE input. `moves`: the render changes by more than the seed-noise
   floor (`faint`: it does not, yet the render is not bit-identical, so the row is neither credited nor called a
   drop). `inert`: the render is bit-identical under the same seed (the engine drops the input) AND the report names
   it. `reported`: the report names the lowering whatever the pixels do.

Probe scenes and driver: tests/pkg321_probe_blender.py. Verdicts and evidence:
.astroray_plan/docs/pkg321-dropped-row-audit.md. GPU legs are not part of this file (CPU is the oracle; the lead
runs a GPU confirmation of the same table under gpu_locked_run.py).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MATRIX = REPO / "docs" / "blender_parity" / "coverage_matrix.json"

# probe id -> (verdict, substring the DegradationReport must contain (union over variants A and B))
PROBE_VERDICT = {
    # Hair Principled
    "hair_color": ("moves", ""), "hair_roughness": ("moves", ""), "hair_radial_roughness": ("moves", ""),
    "hair_coat": ("moves", ""), "hair_ior": ("moves", ""), "hair_offset": ("moves", ""),
    "hair_melanin": ("moves", ""), "hair_melanin_redness": ("moves", ""),
    "hair_tint": ("faint", ""),          # not credited: <1% change at Melanin 0 (engine: spectral melanin path skips Tint)
    "hair_absorption": ("moves", ""), "hair_parametrization": ("moves", ""),
    "hair_model": ("inert", "Huang 2022 near-field hair model is approximated with Chiang"),
    "hair_random": ("inert", "no per-strand randomisation"),
    "hair_random_roughness": ("inert", "no per-strand randomisation"),
    "hair_random_color": ("inert", "no per-strand randomisation"),
    # BSDF Normal / Tangent / Coat Normal (n_principled_control = the probe is not vacuous)
    "n_principled_control": ("moves", ""),
    "n_diffuse": ("inert", "Normal input is linked but not honoured"),
    "n_diffuse_bump": ("inert", "Normal input is linked but not honoured"),
    "n_glass": ("inert", "Normal input is linked but not honoured"),
    "n_refraction": ("inert", "Normal input is linked but not honoured"),
    "n_sheen": ("inert", "Normal input is linked but not honoured"),
    "n_translucent": ("inert", "Normal input is linked but not honoured"),
    "n_anisotropic": ("inert", "Normal input is linked but not honoured"),
    "n_metallic": ("inert", "Normal input is not honoured by the native conductor"),
    "disp_normal": ("inert", "'Normal' input is dropped"),
    "n_principled_coat": ("inert", "'Coat Normal' is linked but not honoured"),
    "t_principled": ("inert", "'Tangent' is linked but not honoured"),
    "t_metallic": ("inert", "Tangent input is not honoured by the native conductor"),
    "t_anisotropic": ("inert", "Tangent not honoured: the Anisotropic BSDF is lowered"),
    "a_anisotropy": ("inert", "Anisotropy not honoured: the Anisotropic BSDF is lowered"),
    "a_rotation": ("inert", "Rotation not honoured: the Anisotropic BSDF is lowered"),
    # enum props
    "e_principled_distribution": ("inert", "Principled distribution 'GGX' is not honoured"),
    "e_glass_distribution": ("inert", "distribution 'BECKMANN' is not honoured"),
    "e_refraction_distribution": ("inert", "distribution 'GGX' is not honoured"),
    "e_sheen_distribution": ("inert", "distribution 'ASHIKHMIN' is not honoured"),
    "e_glossy_distribution": ("inert", "distribution 'BECKMANN' is not honoured"),
    "e_anisotropic_distribution": ("inert", "distribution 'BECKMANN' is not honoured"),
    "e_principled_subsurface_method": ("inert", "subsurface_method 'BURLEY' is not honoured"),
    "e_principled_subsurface_ior": ("inert", "'Subsurface IOR' (1.2) is not honoured"),
    # Principled Volume
    "v_absorption_color": ("moves", ""), "v_blackbody_tint": ("moves", ""),
    "v_density_attribute": ("moves", ""), "v_temperature_attribute": ("moves", ""),
    "v_color_attribute": ("inert", "ignored Volume Principled: volume 'Color Attribute'"),
    # Sky
    "s_sun_elevation_control": ("moves", ""),
    "s_altitude": ("moves", ""), "s_sun_intensity": ("moves", ""), "s_sun_size": ("moves", ""),
    "s_ground_albedo": ("inert", "NOT honoured: ground_albedo"),
    "s_sun_direction": ("inert", ""),                 # inert in Cycles for the Nishita types too (audit doc)
    "s_sun_direction_preetham": ("inert", "sun_direction (Cycles reads it for this sky_type"),
    # Glass thin film + misc
    # pkg326 (#1136): consumed on rough glass; #1162: on smooth glass (the delta path) too, but the
    # smooth sphere's noise floor is ~3x the rough one's, so its mean shift (as large as the rough
    # probe's) stays under the 3x-noise bar: d_ab 1.4e-2 vs d_aa 1.1e-2, db_ab 7.4e-3 vs db_aa 5.1e-3.
    # It was bit-identical (inert) before #1162; tests/test_pkg326_glass_thin_film.py layer 3 proves it.
    "g_thin_film_thickness": ("moves", ""),
    "g_thin_film_ior": ("moves", ""),
    "g_thin_film_smooth": ("faint", ""),
    "m_geometry_normal": ("reported", "Geometry output 'Normal' unsupported in the op-VM"),
}


def _load_generator():
    spec = importlib.util.spec_from_file_location("pkg321_matrix_generator",
                                                  REPO / "scripts" / "generate_blender_parity_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# layer 2: table consistency (no Blender)
# --------------------------------------------------------------------------- #

def test_every_credit_has_a_probe_that_moves_pixels():
    gen = _load_generator()
    assert gen.PKG321_PROBE_CREDITS
    for key, (probe, cls) in gen.PKG321_PROBE_CREDITS.items():
        assert PROBE_VERDICT[probe][0] == "moves", (key, probe)
        assert cls in ("SUPPORTED", "APPROXIMATED"), key


def test_every_reported_drop_has_an_inert_probe_and_an_issue():
    gen = _load_generator()
    for key, (probe, issue) in gen.PKG321_REPORTED_DROPS.items():
        assert PROBE_VERDICT[probe][0] in ("inert", "reported"), (key, probe)
        assert PROBE_VERDICT[probe][1], f"{key}: a drop needs a named DegradationReport entry"
        assert isinstance(issue, int) and issue > 0
    for key, (probe, _why, issue) in gen.PKG321_REPORTED_APPROXIMATIONS.items():
        assert PROBE_VERDICT[probe][0] == "inert", (key, probe)
        assert isinstance(issue, int) and issue > 0


def test_committed_matrix_carries_the_pkg321_classifications():
    gen = _load_generator()
    rows = {(r["bl_idname"], r["socket_or_prop"]): r for r in json.loads(MATRIX.read_text(encoding="utf-8"))}
    for key, (probe, cls) in gen.PKG321_PROBE_CREDITS.items():
        assert rows[key]["classification"] == cls, key
        assert probe in rows[key]["notes"], key
    for key, (probe, why, issue) in gen.PKG321_REPORTED_APPROXIMATIONS.items():
        assert rows[key]["classification"] == "APPROXIMATED", key
        assert f"(#{issue})" in rows[key]["notes"], key
    for key, (probe, issue) in gen.PKG321_REPORTED_DROPS.items():
        assert rows[key]["classification"] == "DROPPED-SILENT", key     # a drop is never credited
        assert f"(#{issue})" in rows[key]["notes"] and probe in rows[key]["notes"], key


# --------------------------------------------------------------------------- #
# layer 1: the addon names every proven drop (stub bpy, no engine)
# --------------------------------------------------------------------------- #
sys.path.insert(0, str(REPO / "tests"))
from test_pkg119c_degradation import _Node, _Socket, _engine, _load_blender_addon  # noqa: E402


def _texts(engine):
    r = engine._degradation_report()
    return [f"{f}: {d}" for f, d in r.approximated] + [f"{f}: {d}" for f, d in r.ignored]


def _linked(node_type="NORMAL_MAP"):
    return _Socket(default=(0.0, 0.0, 0.0), linked_to=_Node(ntype=node_type))


def test_hair_random_sockets_are_reported_only_when_used(monkeypatch):
    engine = _engine(_load_blender_addon(monkeypatch))
    quiet = _Node("BSDF_HAIR_PRINCIPLED", "ShaderNodeBsdfHairPrincipled", {
        "Random": _Socket(0.0), "Random Roughness": _Socket(0.0), "Random Color": None})
    engine._hair_shader_spec(quiet, "BSDF_HAIR_PRINCIPLED")
    assert not [t for t in _texts(engine) if "randomisation" in t]
    used = _Node("BSDF_HAIR_PRINCIPLED", "ShaderNodeBsdfHairPrincipled", {
        "Random": _Socket(0.0), "Random Roughness": _Socket(0.4), "Random Color": None})
    engine._hair_shader_spec(used, "BSDF_HAIR_PRINCIPLED")
    assert any("Random Roughness not honoured" in t for t in _texts(engine)), _texts(engine)


@pytest.mark.parametrize("ntype,bl", [
    ("BSDF_DIFFUSE", "ShaderNodeBsdfDiffuse"), ("BSDF_GLASS", "ShaderNodeBsdfGlass"),
    ("BSDF_REFRACTION", "ShaderNodeBsdfRefraction"), ("BSDF_SHEEN", "ShaderNodeBsdfSheen"),
    ("BSDF_TRANSLUCENT", "ShaderNodeBsdfTranslucent")])
def test_linked_normal_on_a_standalone_bsdf_is_reported(monkeypatch, ntype, bl):
    engine = _engine(_load_blender_addon(monkeypatch))
    plain = _Node(ntype, bl, {"Normal": _Socket((0, 0, 0))})
    engine._report_unhonoured_bsdf_props(plain)
    assert not [t for t in _texts(engine) if "Normal input" in t]
    engine._report_unhonoured_bsdf_props(_Node(ntype, bl, {"Normal": _linked()}))
    assert any("Normal input is linked but not honoured" in t and t.startswith(ntype) for t in _texts(engine))


def test_anisotropic_node_is_reported_as_lowered_isotropic(monkeypatch):
    engine = _engine(_load_blender_addon(monkeypatch))
    node = _Node("BSDF_GLOSSY", "ShaderNodeBsdfAnisotropic", {
        "Anisotropy": _Socket(0.8), "Rotation": _Socket(0.0), "Tangent": _Socket((0, 0, 0)),
        "Normal": _Socket((0, 0, 0))}, distribution="MULTI_GGX")
    engine._report_unhonoured_bsdf_props(node)
    assert any(t.startswith("BSDF_ANISOTROPIC: Anisotropy not honoured") for t in _texts(engine)), _texts(engine)
    glossy = _Node("BSDF_GLOSSY", "ShaderNodeBsdfGlossy", {"Normal": _Socket((0, 0, 0))}, distribution="MULTI_GGX")
    engine2 = _engine(_load_blender_addon(monkeypatch))
    engine2._report_unhonoured_bsdf_props(glossy)
    assert _texts(engine2) == []                                  # a default Glossy stays quiet


def test_distribution_and_thin_film_are_reported(monkeypatch):
    engine = _engine(_load_blender_addon(monkeypatch))
    engine._report_unhonoured_bsdf_props(_Node("BSDF_GLASS", "ShaderNodeBsdfGlass", {
        "Thin Film Thickness": _Socket(600.0), "Normal": _Socket((0, 0, 0))}, distribution="GGX"))
    texts = _texts(engine)
    assert any("distribution 'GGX' is not honoured" in t for t in texts), texts
    # pkg326 (#1136): the native route consumes the sockets, smooth glass included (#1162: no
    # Roughness socket in this stub = 0), so neither the legacy drop nor a smooth-glass line shows.
    assert not any("Thin Film" in t for t in texts), texts
    legacy = _engine(_load_blender_addon(monkeypatch))
    legacy._use_native_principled_flag = False
    legacy._report_unhonoured_bsdf_props(_Node("BSDF_GLASS", "ShaderNodeBsdfGlass", {
        "Thin Film Thickness": _Socket(600.0), "Normal": _Socket((0, 0, 0))}, distribution="MULTI_GGX"))
    assert any("Thin Film Thickness / Thin Film IOR" in t for t in _texts(legacy)), _texts(legacy)
    default = _engine(_load_blender_addon(monkeypatch))
    default._report_unhonoured_bsdf_props(_Node("BSDF_GLASS", "ShaderNodeBsdfGlass", {
        "Thin Film Thickness": _Socket(0.0), "Normal": _Socket((0, 0, 0))}, distribution="MULTI_GGX"))
    assert _texts(default) == []


def test_principled_enums_and_subsurface_ior_are_reported(monkeypatch):
    engine = _engine(_load_blender_addon(monkeypatch))
    node = _Node("BSDF_PRINCIPLED", "ShaderNodeBsdfPrincipled", {
        "Subsurface IOR": _Socket(1.8), "Coat Normal": _Socket((0, 0, 0)), "Tangent": _Socket((0, 0, 0))},
        distribution="GGX", subsurface_method="BURLEY")
    gaps = engine._native_principled_gaps(node, {"subsurface_weight": 1.0})
    for needle in ("distribution 'GGX' is not honoured", "subsurface_method 'BURLEY' is not honoured",
                   "'Subsurface IOR' (1.8) is not honoured"):
        assert any(needle in g for g in gaps), (needle, gaps)
    quiet = _Node("BSDF_PRINCIPLED", "ShaderNodeBsdfPrincipled", {"Subsurface IOR": _Socket(1.4)},
                  distribution="MULTI_GGX", subsurface_method="RANDOM_WALK")
    assert engine._native_principled_gaps(quiet, {"subsurface_weight": 0.0}) == []
    assert len(engine._native_principled_gaps(quiet, {"subsurface_weight": 1.0})) == 1   # the old SSS line only


def test_volume_report_label_matches_the_node_name():
    sys.path.insert(0, str(REPO / "blender_addon"))
    import volume_export as vol

    class S:
        def __init__(self, v, linked=False):
            self.default_value, self.is_linked, self.links = v, linked, []

    node = types.SimpleNamespace(type="PRINCIPLED_VOLUME", bl_idname="ShaderNodeVolumePrincipled",
                                 inputs={"Color Attribute": S("color"), "Density": S(1.0)})
    link = types.SimpleNamespace(from_node=node)
    out = types.SimpleNamespace(type="OUTPUT_MATERIAL", is_active_output=True, inputs={
        "Volume": types.SimpleNamespace(is_linked=True, links=[link]), "Surface": S(None)})
    mat = types.SimpleNamespace(node_tree=types.SimpleNamespace(nodes=[out, node]))
    pv = vol.principled_volume_from_material(mat)
    assert pv["label"] == "Volume Principled"
    # silent_drop_audit matches report entries by node-name tokens; this feature name must match the node
    sys.path.insert(0, str(REPO))
    from benchmarks.reference_corpus import silent_drop_audit as audit
    assert audit.is_reported("ShaderNodeVolumePrincipled",
                             [f"ignored {pv['label']}: {pv['degradations'][0]}"])


# --------------------------------------------------------------------------- #
# layer 3: the probes (real Blender, CPU)
# --------------------------------------------------------------------------- #

def _find_blender():
    exe = os.environ.get("BLENDER_EXE", "")
    cands = [Path(exe)] if exe else []
    cands += [Path(rf"C:\Program Files\Blender Foundation\Blender {v}\blender.exe") for v in ("5.2", "5.1")]
    return next((c for c in cands if c.is_file()), None)


def _pyd_dir():
    d = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO / "build_cuda"))
    return d if list(d.glob("astroray*.pyd")) else None


@pytest.fixture(scope="module")
def probe_results():
    """results.json of a probe run; PKG321_RESULTS_DIR reuses an existing run (the probe table is deterministic)."""
    reuse = os.environ.get("PKG321_RESULTS_DIR")
    if reuse and (Path(reuse) / "results.json").is_file():
        return json.loads((Path(reuse) / "results.json").read_text(encoding="utf-8"))
    blender, pyd = _find_blender(), _pyd_dir()
    if blender is None or pyd is None:
        pytest.skip("needs Blender 5.x and an engine .pyd (ASTRORAY_PYD_DIR)")
    out = tempfile.mkdtemp(prefix="pkg321_probes_")
    env = dict(os.environ, ASTRORAY_PYD_DIR=str(pyd), CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="8")
    proc = subprocess.run([str(blender), "--background", "--factory-startup", "--python",
                           str(REPO / "tests" / "pkg321_probe_blender.py"), "--", out],
                          capture_output=True, text=True, timeout=1500, env=env, check=False)
    assert "PKG321_PROBES_DONE" in proc.stdout, proc.stdout[-3000:] + proc.stderr[-2000:]
    return json.loads((Path(out) / "results.json").read_text(encoding="utf-8"))


def _moved(r):
    return r["d_ab"] > 0 and (r["db_ab"] >= 3 * r["db_aa"] or r["d_ab"] >= 3 * r["d_aa"])


@pytest.mark.serial
@pytest.mark.parametrize("probe", sorted(PROBE_VERDICT))
def test_probe(probe_results, probe):
    verdict, warning = PROBE_VERDICT[probe]
    r = probe_results[probe]
    assert "error" not in r, r
    assert r["finite"], r
    if verdict == "moves":
        assert _moved(r), f"{probe}: expected the input to move the CPU render, got {r}"
    elif verdict == "faint":
        assert not _moved(r), f"{probe}: expected no change above the noise floor, got {r}"
    elif verdict == "inert":
        assert r["d_ab"] == 0.0, f"{probe}: expected a bit-identical render (input dropped), d_ab={r['d_ab']}"
    if warning:
        assert warning in r["warn_A"] + " | " + r["warn_B"], (probe, r["warn_A"], r["warn_B"])


GPU_PROBES = sorted(p for p, (verdict, _w) in PROBE_VERDICT.items() if verdict == "moves")   # credits + controls


def _cuda_available():
    if os.environ.get("CUDA_VISIBLE_DEVICES") == "-1":
        return False
    try:
        sys.path.insert(0, str(REPO / "tests"))
        from runtime_setup import configure_test_imports
        configure_test_imports()
        import astroray
        return bool(astroray.__features__.get("cuda", False)) and bool(getattr(astroray.Renderer(), "gpu_available", False))
    except Exception:  # noqa: BLE001 - no module / no driver: skip
        return False


@pytest.fixture(scope="module")
def gpu_probe_results():
    """The credited `moves` probes and the two controls, rendered with the Astroray device set to GPU."""
    blender, pyd = _find_blender(), _pyd_dir()
    if blender is None or pyd is None:
        pytest.skip("needs Blender 5.x and an engine .pyd (ASTRORAY_PYD_DIR)")
    if not _cuda_available():
        pytest.skip("CUDA is hidden or unavailable")
    out = tempfile.mkdtemp(prefix="pkg321_gpu_probes_")
    env = dict(os.environ, ASTRORAY_PYD_DIR=str(pyd), PKG321_DEVICE="gpu", OMP_NUM_THREADS="8")
    proc = subprocess.run([str(blender), "--background", "--factory-startup", "--python",
                           str(REPO / "tests" / "pkg321_probe_blender.py"), "--", out, *GPU_PROBES],
                          capture_output=True, text=True, timeout=900, env=env, check=False)
    assert "PKG321_PROBES_DONE" in proc.stdout, proc.stdout[-3000:] + proc.stderr[-2000:]
    return json.loads((Path(out) / "results.json").read_text(encoding="utf-8"))


@pytest.mark.gpu
@pytest.mark.serial
@pytest.mark.parametrize("probe", GPU_PROBES)
def test_probe_moves_on_gpu(gpu_probe_results, probe):
    """Same `_moved` outcome as the CPU leg (the hardware lead runs this under gpu_locked_run.py)."""
    r = gpu_probe_results[probe]
    assert "error" not in r, r
    assert r["finite"], r
    assert _moved(r), f"{probe}: the input does not move the GPU render, got {r}"


@pytest.mark.serial
def test_probe_table_covers_every_driver_probe(probe_results):
    assert set(probe_results) == set(PROBE_VERDICT)
