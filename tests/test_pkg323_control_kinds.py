"""pkg323: gate (b) witness control kinds, the mask predicate and the candidate witness map.

* Control kinds (``noise_const``, ``brick_const``, ``wave_const``, ``bump_zero``, ``mapping_identity``) are exercised
  inside a real headless Blender on a synthetic five-card scene (Cycles CPU, tiny): each mutates only its target node,
  and the counterfactual changes the masked card and nothing else.
* ``witness_metrics(region=...)``: ``rect`` is the frozen behaviour, ``mask`` averages the same maps over the feature.
* The committed candidate map (``witness_candidates_v5.json``) is well formed and uses only known control kinds.
* One ``@pytest.mark.gpu`` smoke test renders GPU legs for one cheap witness per family (the lead runs it under the
  GPU lock with ASTRORAY_PYD_DIR set to a CUDA build).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from benchmarks.blender_parity import harness
from benchmarks.blender_parity import render_leg as R
from benchmarks.reference_corpus import coverage_report as C

CANDIDATES = REPO / "benchmarks" / "reference_corpus" / "witness_candidates_v5.json"

# --------------------------------------------------------------------------- #
# witness_metrics regions (pure numpy, no Blender)
# --------------------------------------------------------------------------- #


def _scene(h=48, w=64, seed=3):
    rng = np.random.default_rng(seed)
    base = 0.25 + 0.5 * rng.random((h, w, 3), dtype=np.float32)
    return base.astype(np.float32)


WITNESS = {"roi": [0.1, 0.1, 0.9, 0.9],
           "control": {"kind": "bump_zero"},
           "effect": {"kind": "changed", "min_delta": 0.01, "min_coverage": 0.05, "min_signal": 0.001}}


def _mask(h=48, w=64):
    m = np.zeros((h, w), dtype=np.uint8)
    m[16:32, 20:44] = 255
    return m


def test_rect_region_is_the_frozen_behaviour():
    from benchmarks.reference_bank.metrics import compute_delta_e_2000, compute_ssim

    ref = _scene()
    act = ref.copy()
    act[:8] *= 0.5  # damage outside the ROI only
    ctl = ref * 0.8
    m = _mask()
    result, reason = C.witness_metrics(act, ref, ctl, ctl, m, m, WITNESS)
    assert result is not None, reason
    roi = C._witness_roi(act.shape, WITNESS)
    ssim, _ = compute_ssim(act[roi], ref[roi])
    de, _ = compute_delta_e_2000(act[roi], ref[roi])
    assert result["ssim"] == float(ssim) and result["delta_e"] == float(de)
    assert set(result) == {"ssim", "delta_e", "effects", "roi", "pass"}  # no key added to the frozen result
    default, _ = C.witness_metrics(act, ref, ctl, ctl, m, m, WITNESS, "rect")
    assert default == result


def test_mask_region_ignores_non_feature_pixels():
    ref = _scene()
    act = ref.copy()
    m = _mask()
    near = np.zeros(m.shape, dtype=bool)  # the 7x7 SSIM window reaches 3 px past the mask: keep a 4 px margin clean
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            near |= np.roll(m > 0, (dy, dx), axis=(0, 1))
    act[~near] *= 0.4  # the non-feature area is darker, the feature itself matches exactly
    ctl = ref * 0.8
    rect, _ = C.witness_metrics(act, ref, ctl, ctl, m, m, WITNESS, "rect")
    mask, _ = C.witness_metrics(act, ref, ctl, ctl, m, m, WITNESS, "mask")
    assert rect["ssim"] < 0.95 and rect["delta_e"] > 5.0
    assert mask["ssim"] > 0.999 and mask["delta_e"] < 1e-3
    assert mask["pass"] and rect["pass"]  # effect verdict is region independent


def test_mask_region_still_sees_a_bad_feature_and_rejects_bad_input():
    ref = _scene()
    act = ref.copy()
    m = _mask()
    act[m > 0] *= 0.5
    ctl = ref * 0.8
    mask, _ = C.witness_metrics(act, ref, ctl, ctl, m, m, WITNESS, "mask")
    assert mask["delta_e"] > 5.0
    bad, reason = C.witness_metrics(act, ref, ctl, ctl, m, m, WITNESS, "disk")
    assert bad is None and "region" in reason
    empty = np.zeros_like(m)
    none, reason = C.witness_metrics(act, ref, ctl, ctl, m, empty, WITNESS, "mask")
    assert none is None and "empty" in reason


def test_effect_kind_defaults_to_the_two_sided_checker_probe():
    ref = _scene()
    m = _mask()
    one_sided = ref * 0.8  # baseline brighter than control everywhere: no dark phase around the midpoint
    checker = dict(WITNESS, effect={"min_delta": 0.01, "min_coverage": 0.05, "min_signal": 0.001})
    result, _ = C.witness_metrics(ref, ref, one_sided, one_sided, m, m, checker)
    assert not result["pass"]  # default kind = checker
    result, _ = C.witness_metrics(ref, ref, one_sided, one_sided, m, m, WITNESS)
    assert result["pass"]  # kind "changed" only needs a magnitude


# --------------------------------------------------------------------------- #
# study credit rule (synthetic ledger)
# --------------------------------------------------------------------------- #


def _node(name, digest_marker, sockets):
    fingerprint = {"active_inputs": {}, "linked_inputs": [digest_marker], "linked_outputs": [], "prop_variants": {}}
    return {"bl_idname": name, "fingerprint": fingerprint, "sockets": sockets}


def test_provisional_score_needs_every_variant_and_fanout_reads_per_node(tmp_path):
    a1, a2 = _node("ShaderNodeBump", "x", ["input:Strength", "input:Distance"]), _node("ShaderNodeBump", "y", ["input:Strength"])
    snapshot = {"schema": "pkg278.node_uses.v1", "scenes": {
        "s1": {"nodes": [a1], "blend_path": "s1.blend"}, "s2": {"nodes": [a2], "blend_path": "s2.blend"}}}
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps([
        {"bl_idname": "ShaderNodeBump", "socket_or_prop": "input:Strength", "classification": "SUPPORTED"},
        {"bl_idname": "ShaderNodeBump", "socket_or_prop": "input:Distance", "classification": "SUPPORTED"}]), encoding="utf-8")
    d1, d2 = C.variant_digest(a1["fingerprint"]), C.variant_digest(a2["fingerprint"])

    def witness(scene, digest, identities):
        return {"id": f"{scene}/w", "population": "p", "scene_id": scene, "variant_digest": digest,
                "identity": identities[0], "identities": identities}
    pass_row = {"rect": {"pass": True}, "mask": {"pass": True}}
    cands = {"witnesses": [witness("s1", d1, ["ShaderNodeBump|input:Strength", "ShaderNodeBump|input:Distance"]),
                           witness("s2", d2, ["ShaderNodeBump|input:Strength"])]}
    rows = [{"id": "s1/w", **pass_row}, {"id": "s2/w", **pass_row}]
    out = C._study_provisional_scores(cands, rows, {"p": snap_path}, matrix_path)["p"]
    # Strength: scenes s1+s2 (weight 2); Distance: s1 only (weight 1); denominator 3.
    assert out["denominator"] == 3.0
    assert out["mask_fanout"]["numerator"] == 3.0
    # rep credit: s1's representative is Strength, s2's is Strength -> Strength credited (2), Distance not (0).
    assert out["mask_rep"]["numerator"] == 2.0
    # a failing witness for s2 removes Strength (every variant must be covered) but keeps Distance under fan-out.
    rows[1] = {"id": "s2/w", "rect": {"pass": False}, "mask": {"pass": False}}
    out = C._study_provisional_scores(cands, rows, {"p": snap_path}, matrix_path)["p"]
    assert out["mask_fanout"]["numerator"] == 1.0 and out["mask_rep"]["numerator"] == 0.0


# --------------------------------------------------------------------------- #
# candidate map
# --------------------------------------------------------------------------- #


def test_candidate_map_is_well_formed():
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    assert data["schema"] == C.STUDY_SCHEMA and data["selection_rule"] and "CANDIDATE" in data["status"]
    witnesses = data["witnesses"]
    assert len(witnesses) >= 10
    assert {w["family"] for w in witnesses} >= {"Noise", "Brick", "Wave", "Bump", "Mapping"}
    assert len({w["id"] for w in witnesses}) == len(witnesses)
    for w in witnesses:
        control = w["witness"]["control"]
        assert control["kind"] in R.GATE_B_CONTROL_NODE_TYPES
        assert R.GATE_B_CONTROL_NODE_TYPES[control["kind"]] == next(
            k for k, v in C.STUDY_FAMILIES.items() if v[1] == control["kind"])
        assert w["identity"] in w["identities"]
        assert C._witness_roi((270, 480, 3), w["witness"]) is not None
        assert control["mask"]["kind"] == "object_faces"
        assert w["mask_px"] >= C.STUDY_MIN_MASK_PX


def test_frozen_registry_and_checker_control_untouched():
    assert len(C.CASE_WITNESS_REGISTRY) == 1
    (identity, _scene_id, _digest), witness = next(iter(C.CASE_WITNESS_REGISTRY.items()))
    assert identity == "ShaderNodeTexChecker|input:Color1" and witness["control"]["kind"] == "checker_flat"
    assert "kind" not in witness["effect"]  # so the checker keeps the two-sided phase probe


# --------------------------------------------------------------------------- #
# control kinds in a real (headless) Blender
# --------------------------------------------------------------------------- #

BLENDER_SCRIPT = textwrap.dedent('''
    import importlib.util, json, sys
    from pathlib import Path
    import bpy
    import numpy as np

    repo, out_json, work = sys.argv[sys.argv.index("--") + 1:][:3]
    spec = importlib.util.spec_from_file_location("render_leg", str(Path(repo) / "benchmarks/blender_parity/render_leg.py"))
    leg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(leg)

    W, H = 160, 90
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = W, H
    world = bpy.data.worlds.new("W")
    sc.world = world
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type, cam_data.ortho_scale = "ORTHO", 5.0
    cam = bpy.data.objects.new("Cam", cam_data)
    cam.location = (0.0, 0.0, 5.0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (0.5, 0.3, 0.0)
    sc.collection.objects.link(sun)

    def new_card(name, x):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(-.5, -.5, 0), (.5, -.5, 0), (.5, .5, 0), (-.5, .5, 0)], [], [(0, 1, 2, 3)])
        obj = bpy.data.objects.new(name, mesh)
        obj.location = (x, 0.0, 0.0)
        sc.collection.objects.link(obj)
        mat = bpy.data.materials.new(name + "Mat")
        mat.use_nodes = True
        mat.node_tree.nodes.clear()
        mesh.materials.append(mat)
        return obj, mat

    def node(tree, kind, name=None, **inputs):
        n = tree.nodes.new(kind)
        if name:
            n.name = name
        for k, v in inputs.items():
            n.inputs[k.replace("_", " ")].default_value = v
        return n

    def emit(tree, colour_socket):
        out = tree.nodes.new("ShaderNodeOutputMaterial")
        e = tree.nodes.new("ShaderNodeEmission")
        tree.links.new(colour_socket, e.inputs["Color"])
        tree.links.new(e.outputs[0], out.inputs["Surface"])

    cards = {}
    # noise: Fac -> Emission colour
    obj, mat = new_card("NoiseCard", -2.0)
    t = mat.node_tree
    tc = t.nodes.new("ShaderNodeTexCoord")
    n = node(t, "ShaderNodeTexNoise", "Target", Scale=4.0)
    t.links.new(tc.outputs["Generated"], n.inputs["Vector"])
    emit(t, n.outputs["Fac"])
    cards["noise_const"] = (obj, mat, {"const": 0.5})
    # brick
    obj, mat = new_card("BrickCard", -1.0)
    t = mat.node_tree
    tc = t.nodes.new("ShaderNodeTexCoord")
    n = node(t, "ShaderNodeTexBrick", "Target", Scale=3.0)
    t.links.new(tc.outputs["Generated"], n.inputs["Vector"])
    emit(t, n.outputs["Color"])
    cards["brick_const"] = (obj, mat, {})
    # wave
    obj, mat = new_card("WaveCard", 0.0)
    t = mat.node_tree
    tc = t.nodes.new("ShaderNodeTexCoord")
    n = node(t, "ShaderNodeTexWave", "Target", Scale=4.0, Distortion=1.0)
    t.links.new(tc.outputs["Generated"], n.inputs["Vector"])
    emit(t, n.outputs["Color"])
    cards["wave_const"] = (obj, mat, {"const": 0.5})
    # bump on a lit diffuse card; the height comes from a (non-target) noise
    obj, mat = new_card("BumpCard", 1.0)
    t = mat.node_tree
    tc = t.nodes.new("ShaderNodeTexCoord")
    h = node(t, "ShaderNodeTexNoise", "Height", Scale=6.0)
    t.links.new(tc.outputs["Generated"], h.inputs["Vector"])
    b = node(t, "ShaderNodeBump", "Target", Strength=1.0, Distance=1.0)
    t.links.new(h.outputs["Fac"], b.inputs["Height"])
    d = t.nodes.new("ShaderNodeBsdfDiffuse")
    t.links.new(b.outputs["Normal"], d.inputs["Normal"])
    out = t.nodes.new("ShaderNodeOutputMaterial")
    t.links.new(d.outputs["BSDF"], out.inputs["Surface"])
    cards["bump_zero"] = (obj, mat, {})
    # mapping scale 3 in front of a checker
    obj, mat = new_card("MapCard", 2.0)
    t = mat.node_tree
    tc = t.nodes.new("ShaderNodeTexCoord")
    m = node(t, "ShaderNodeMapping", "Target")
    m.inputs["Scale"].default_value = (3.0, 3.0, 3.0)
    ck = node(t, "ShaderNodeTexChecker", "Checker", Scale=2.0)
    t.links.new(tc.outputs["Generated"], m.inputs["Vector"])
    t.links.new(m.outputs["Vector"], ck.inputs["Vector"])
    emit(t, ck.outputs["Color"])
    cards["mapping_identity"] = (obj, mat, {})

    leg._configure_render(sc, "CYCLES", W, 8, res_y=H, seed=7)
    sc.cycles.device = "CPU"
    sc.cycles.max_bounces = 0  # direct light only: cards cannot influence each other
    masks = {k: leg._object_faces_mask(bpy, sc, obj, (H, W), 4) > 0 for k, (obj, mat, extra) in cards.items()}
    away = {}  # everything farther than 3 px from the card's silhouette
    for k, (obj, mat, extra) in cards.items():
        ys, xs = np.nonzero(leg._object_faces_mask(bpy, sc, obj, (H, W), 0))
        keep = np.ones((H, W), dtype=bool)
        keep[max(0, ys.min() - 3):ys.max() + 4, max(0, xs.min() - 3):xs.max() + 4] = False
        away[k] = keep

    def snapshot():
        state = {}
        for mat in bpy.data.materials:
            t = mat.node_tree
            nodes = {}
            for n in t.nodes:
                nodes[n.name] = {"type": n.bl_idname, "inputs": {
                    i.identifier: [round(float(x), 6) for x in (list(i.default_value) if hasattr(i.default_value, "__len__") else [i.default_value])]
                    for i in n.inputs if hasattr(i, "default_value") and not isinstance(i.default_value, (str, type(None)))}}
            links = sorted([l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier] for l in t.links)
            state[mat.name] = {"nodes": nodes, "links": links}
        return state

    def render(tag):
        return np.load(leg._render_to_npy(bpy, sc, Path(work) / tag, W))

    results = {"kinds": {}}
    previous_image = render("base")
    previous_state = snapshot()
    results["baseline_noise"] = float(np.abs(render("base2") - previous_image).max())
    for kind, (obj, mat, extra) in cards.items():
        spec_ = {"kind": kind, "object": obj.name, "material": mat.name, "node": "Target", **extra}
        receipt = leg._gate_c_control(bpy, sc, spec_)
        state = snapshot()
        image = render(kind)
        record = {"receipt_ok": receipt["ok"], "receipt_kind": receipt["kind"]}
        record["other_materials_changed"] = sorted(m for m in state if m != mat.name and state[m] != previous_state[m])
        before, after = previous_state[mat.name], state[mat.name]
        record["added_nodes"] = sorted(set(after["nodes"]) - set(before["nodes"]))
        record["removed_nodes"] = sorted(set(before["nodes"]) - set(after["nodes"]))
        record["changed_nodes"] = sorted(n for n in before["nodes"] if n in after["nodes"] and before["nodes"][n] != after["nodes"][n])
        record["changed_inputs"] = sorted(k for n in record["changed_nodes"] for k in before["nodes"][n]["inputs"]
                                          if before["nodes"][n]["inputs"][k] != after["nodes"][n]["inputs"].get(k))
        record["links_removed_from"] = sorted({l[0] for l in before["links"] if l not in after["links"]})
        record["links_added_from"] = sorted({l[0] for l in after["links"] if l not in before["links"]})
        diff = np.abs(image - previous_image).mean(axis=-1)
        mk = masks[kind]
        record["inside_mean"] = float(diff[mk].mean())
        record["inside_cover"] = float((diff[mk] > 0.01).mean())
        record["outside_max"] = float(diff[away[kind]].max())
        try:
            leg._gate_c_control(bpy, sc, spec_)
            record["second_apply"] = "applied"
        except ValueError as exc:
            record["second_apply"] = str(exc)
        results["kinds"][kind] = record
        previous_image, previous_state = image, state
    results["mask_px"] = {k: int(v.sum()) for k, v in masks.items()}
    Path(out_json).write_text(json.dumps(results), encoding="utf-8")
    print("PKG323_TEST_DONE")
''')


@pytest.fixture(scope="module")
def blender_results(tmp_path_factory):
    blender = harness._find_blender()
    if blender is None:
        pytest.skip("Blender not found (set BLENDER_EXE)")
    work = tmp_path_factory.mktemp("pkg323")
    script = work / "scene_script.py"
    script.write_text(BLENDER_SCRIPT, encoding="utf-8")
    out = work / "results.json"
    env = dict(os.environ)
    proc = subprocess.run([str(blender), "--background", "--factory-startup", "--python", str(script), "--",
                           str(REPO), str(out), str(work)], capture_output=True, text=True, timeout=600, env=env, check=False)
    assert out.is_file(), (proc.stdout + proc.stderr)[-3000:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_cycles_render_is_reproducible_so_outside_diffs_mean_something(blender_results):
    assert blender_results["baseline_noise"] == 0.0
    assert all(px >= 300 for px in blender_results["mask_px"].values())


@pytest.mark.parametrize("kind", ["noise_const", "wave_const"])
def test_const_kinds_replace_only_the_targets_consumers(blender_results, kind):
    r = blender_results["kinds"][kind]
    assert r["receipt_ok"] and r["receipt_kind"] == kind
    assert r["added_nodes"] and all(n.startswith("Target_Const_") for n in r["added_nodes"])
    assert r["removed_nodes"] == [] and r["changed_nodes"] == []  # the target node itself is untouched
    assert r["links_removed_from"] == ["Target"] and set(r["links_added_from"]) == set(r["added_nodes"])
    assert r["other_materials_changed"] == []
    assert r["second_apply"] != "applied"  # no linked output left: a repeat would be a no-op and is refused


@pytest.mark.parametrize("kind,inputs", [("brick_const", {"Color1", "Color2", "Mortar"}), ("bump_zero", {"Strength"}),
                                         ("mapping_identity", {"Location", "Rotation", "Scale"})])
def test_in_node_kinds_change_only_their_target_inputs(blender_results, kind, inputs):
    r = blender_results["kinds"][kind]
    assert r["receipt_ok"] and r["receipt_kind"] == kind
    assert r["changed_nodes"] == ["Target"] and set(r["changed_inputs"]) <= inputs and r["changed_inputs"]
    assert r["added_nodes"] == [] and r["removed_nodes"] == []
    assert r["links_removed_from"] == [] and r["links_added_from"] == []
    assert r["other_materials_changed"] == []
    assert r["second_apply"] != "applied"


@pytest.mark.parametrize("kind", ["noise_const", "brick_const", "wave_const", "bump_zero", "mapping_identity"])
def test_counterfactual_changes_the_masked_card_and_nothing_else(blender_results, kind):
    r = blender_results["kinds"][kind]
    assert r["inside_mean"] > 0.01 and r["inside_cover"] > 0.2, r
    assert r["outside_max"] == 0.0, r  # every pixel outside the card is bit-identical (fixed seed, no bounces)


# --------------------------------------------------------------------------- #
# GPU smoke (lead runs under the GPU lock): one cheap witness per family, both engines must show the effect
# --------------------------------------------------------------------------- #

GPU_WITNESSES = ["v2_textures_opvm/CardNoise/Noise Texture", "v2_textures_opvm/CardWave/Wave Texture",
                 "v2_textures_opvm/CardMapAfterWarp/Mapping", "prod_wood/Hero/Bump"]


@pytest.mark.gpu
def test_gpu_legs_show_the_counterfactual_effect(tmp_path):
    pyd = os.environ.get("ASTRORAY_PYD_DIR")
    if not pyd or not list(Path(pyd).glob("astroray*.pyd")):
        pytest.skip("ASTRORAY_PYD_DIR does not point at an astroray build")
    if harness._find_blender() is None:
        pytest.skip("Blender not found")
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    ids = {w["id"] for w in candidates["witnesses"]}
    assert set(GPU_WITNESSES) <= ids
    manifests = {name: C.write_population_manifest(name, REPO, tmp_path / "manifests") for name in sorted(C.POPULATIONS)}
    failures = C.study_render_legs(candidates, manifests, tmp_path, "GPU", pyd_dir=Path(pyd), only=GPU_WITNESSES)
    assert failures == {}
    result = C.study_score(candidates, tmp_path, "GPU", {}, REPO / "docs/blender_parity/coverage_matrix.json", sheets=False)
    rows = {r["id"]: r for r in result["rows"] if r["id"] in GPU_WITNESSES}
    assert set(rows) == set(GPU_WITNESSES)
    for row in rows.values():
        assert "error" not in row, row
        assert row["effect_pass"], row  # the feature shows up in both engines (parity verdicts are reported, not asserted)
