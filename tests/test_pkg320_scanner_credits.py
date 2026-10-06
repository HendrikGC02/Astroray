"""pkg320 (#1039, #1088) -- the coverage-matrix scanner credits output sockets, the root / scene-level nodes and
the Mix Shader branch from mechanical evidence, and the collector's socket identifiers resolve.

Pure Python (no Blender, no astroray): fixture compilers / addons with known handled and unhandled outputs are
scanned by ``scripts/generate_blender_parity_matrix``; the shipped compiler and addon are scanned for the real
claims; the committed matrix is joined through ``coverage_report.matrix_by_identity``.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("gen_matrix_pkg320", REPO / "scripts" / "generate_blender_parity_matrix.py")
GEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GEN)  # bpy is optional at import time

from benchmarks.reference_corpus import coverage_report as CR

MATRIX = REPO / "docs" / "blender_parity" / "coverage_matrix.json"
ADDON = REPO / "blender_addon" / "__init__.py"
VM = REPO / "blender_addon" / "shader_vm_compiler.py"

FIXTURE_COMPILER = '''
class VMCompileError(Exception):
    pass

OUTS = ('A', 'B')


def _compile_socket_value(socket, builder, depth=0):
    node, out_name = socket
    ntype = node.type
    if ntype == 'GUARDED':
        return _guarded(node, out_name, builder)
    if ntype == 'SHARED_1' or ntype == 'SHARED_2':
        return _shared(node, out_name, builder)
    if ntype == 'OPEN':
        return 0
    if ntype == 'DICT':
        comp = {'X': 0, 'Y': 1}.get(out_name)
        if comp is None:
            raise VMCompileError("unsupported component")
        return comp
    if ntype == 'REJECT':
        if out_name == 'Bad':
            raise VMCompileError("refused")
        return 0
    if ntype == 'DISPATCH':
        if out_name in ('P',):
            return 1
        return 0
    if ntype == 'APPROX_NODE':
        if out_name in APPROX and out_name not in builder.node_approx:
            builder.node_approx.append(out_name)
        if out_name in ('Soft', 'Hard'):
            builder.log.append(out_name)  # NEGATIVE: not an approximation report
        return 0
    if _is_leaf(node):
        return _push_leaf(node, out_name)
    return None


APPROX = ('Soft',)
_LEAVES = frozenset(('LEAF_TEX', 'LEAF_IMG'))


def _is_leaf(node):
    return getattr(node, 'type', None) in _LEAVES


def _push_leaf(node, out_name):
    if out_name not in ('Fac', 'Factor'):
        return 0
    return 1


def _guarded(node, out_name, builder):
    if out_name not in OUTS:
        raise VMCompileError("unsupported output")
    return 0


def _shared(node, out_name, builder):
    ntype = node.type
    if ntype == 'SHARED_1':
        if out_name != 'only':
            raise VMCompileError("only 'only'")
        return 1
    return 2
'''

FIXTURE_ENGINE = '''
def _node_input(node, name):
    return None


class CustomRaytracerRenderEngine:
    def material(self, nt):
        output = None
        for node in nt.nodes:
            if node.type == 'OUT_A' and getattr(node, 'is_active_output', True):
                output = node
                break
        vol = output.inputs.get('Volume')
        surf = output.inputs.get('Surface')
        self.disp(output, 1)
        unrelated = nt.inputs.get('Thickness')
        return vol, surf, unrelated

    def disp(self, output, mat):
        return output.inputs.get('Displacement')

    def world(self, nt):
        for node in nt.nodes:
            if node.type == 'BG':
                s = node.inputs['Strength']
                c = node.inputs.get('Color')
            elif node.type == 'ENV':
                img = node.image

    def light(self, ld):
        outs = [n for n in ld.nodes if getattr(n, 'type', '') == 'OUT_L']
        out = next((n for n in outs if getattr(n, 'is_active_output', False)), outs[0] if outs else None)
        surf = _node_input(out, 'Surface')
        em = surf.links[0].from_node
        c = _node_input(em, 'Color')

    def fold(self, node):
        ntype = getattr(node, 'type', '')
        if ntype == 'IES':
            return _node_input(node, 'Strength')

    def other_receivers(self, nt, other):
        for node in nt.nodes:
            if node.type == 'OUT_B':
                surf = node.inputs.get('Surface')
                thick = other.inputs['Thickness']
                prop = getattr(other, 'target', None)
            if not (node.type == 'NEG'):
                foo = node.inputs['Foo']
'''

FIXTURE_WALKER = '''
def walk(edge, node):
    kind = getattr(node, 'type', None)
    if kind in ('COORDS',):
        name = getattr(edge.from_socket, 'name', '')
        modes = {'UV': 1, 'Generated': 2}
        mode = modes.get(name)
        if mode is None:
            raise ValueError(name)
    if kind == 'PLAIN':
        name = edge.from_socket.name
        other = name
'''


@pytest.fixture(scope="module")
def fx_out(tmp_path_factory):
    root = tmp_path_factory.mktemp("fx")
    path = root / "shader_vm_compiler.py"
    path.write_text(FIXTURE_COMPILER, encoding="utf-8")
    walker = root / "walker.py"
    walker.write_text(FIXTURE_WALKER, encoding="utf-8")
    return GEN.scan_output_evidence(None, vm_path=path, addon_path=walker)


@pytest.fixture(scope="module")
def fx_root(tmp_path_factory):
    path = tmp_path_factory.mktemp("fx") / "addon_init.py"
    path.write_text(FIXTURE_ENGINE, encoding="utf-8")
    return GEN.scan_root_node_evidence(None, addon_path=path)


def _addon_namespace():
    """An object `inspect.getfile(ns.CustomRaytracerRenderEngine)` resolves to the shipped addon source."""
    mod = types.ModuleType("pkg320_addon_stub")
    mod.__file__ = str(ADDON)
    sys.modules["pkg320_addon_stub"] = mod
    cls = type("CustomRaytracerRenderEngine", (), {"__module__": "pkg320_addon_stub"})
    return types.SimpleNamespace(CustomRaytracerRenderEngine=cls)


# --- output evidence: the fixture compiler -------------------------------------------------------------------

def _rule(fx, node_type):
    return {k: fx[node_type][k] for k in ("accepted", "rejected")}


def test_guard_membership_in_a_module_tuple_is_an_allow_list(fx_out):
    assert _rule(fx_out, "GUARDED") == {"accepted": frozenset({"A", "B"}), "rejected": frozenset()}
    assert fx_out["GUARDED"]["named"] == frozenset({"A", "B"})


def test_helper_shared_by_two_node_types_is_pruned_per_node_type(fx_out):
    assert fx_out["SHARED_1"]["accepted"] == frozenset({"only"})
    assert fx_out["SHARED_2"]["accepted"] is None  # the `ntype == 'SHARED_1'` guard is not taken for SHARED_2


def test_literal_dict_lookup_followed_by_a_none_raise_is_an_allow_list(fx_out):
    assert fx_out["DICT"]["accepted"] == frozenset({"X", "Y"})


def test_explicit_rejection_and_non_rejecting_dispatch(fx_out):
    assert _rule(fx_out, "REJECT") == {"accepted": None, "rejected": frozenset({"Bad"})}
    assert _rule(fx_out, "DISPATCH") == {"accepted": None, "rejected": frozenset()}  # compares, never raises
    assert fx_out["DISPATCH"]["named"] == frozenset({"P"})
    assert _rule(fx_out, "OPEN") == {"accepted": None, "rejected": frozenset()}      # never looks at out_name
    assert fx_out["OPEN"]["named"] == frozenset()


def _out(name, ident=None, **kw):
    return {"name": name, "identifier": ident or name, "type": "VALUE", **kw}


def _classify_out(node_type, sock, fx, evidence=None, vm=None, props=(), outputs=None):
    return GEN.classify_output_socket(node_type, sock, evidence or {}, frozenset(), vm or {k: {} for k in fx}, fx,
                                      props, outputs)[0]


# --- #1101 review finding 1: on a multi-output node, the absence of a refusal is not evidence ----------------

def test_multi_output_open_branch_credits_only_the_default_output_negative_fixture(fx_out):
    """NEGATIVE (#1101 finding 1): the OPEN branch never looks at out_name, so it computes ONE value whatever
    output is linked: only the first output is credited (Color Ramp's Alpha, Vector Math's Value pattern)."""
    outs = [_out("Color"), _out("Alpha")]
    assert _classify_out("OPEN", outs[0], fx_out, outputs=outs) == "SUPPORTED"
    assert _classify_out("OPEN", outs[1], fx_out, outputs=outs) == "DROPPED-SILENT"
    # a single-output node (or same-named data-type variants) has nothing to distinguish
    assert _classify_out("OPEN", _out("Value"), fx_out, outputs=[_out("Value")]) == "SUPPORTED"
    variants = [_out("Result", "Result_Float"), _out("Result", "Result_Color")]
    assert _classify_out("OPEN", variants[1], fx_out, outputs=variants) == "SUPPORTED"


def test_multi_output_named_by_an_out_name_test_is_credited(fx_out):
    outs = [_out("Q"), _out("P"), _out("R")]
    assert [_classify_out("DISPATCH", o, fx_out, outputs=outs) for o in outs] == \
        ["SUPPORTED", "SUPPORTED", "DROPPED-SILENT"]


def test_texture_leaf_predicate_branch_credits_color_fac_and_first_only(fx_out):
    """A predicate branch (`if _is_leaf(node)`) resolves to its module-constant node types; a texture leaf's
    default load is its colour, so Color, the out_name-tested Fac and the first output are credited and
    nothing else (NEGATIVE: Voronoi's Position / W / Radius, Image's Alpha)."""
    assert fx_out["LEAF_TEX"]["texture_leaf"] and fx_out["LEAF_IMG"]["texture_leaf"]
    voronoi = [_out("Distance"), _out("Color"), _out("Position"), _out("W"), _out("Radius")]
    assert [_classify_out("LEAF_TEX", o, fx_out, outputs=voronoi) for o in voronoi] == \
        ["SUPPORTED", "SUPPORTED", "DROPPED-SILENT", "DROPPED-SILENT", "DROPPED-SILENT"]
    noise = [_out("Factor", "Fac"), _out("Color")]
    assert [_classify_out("LEAF_TEX", o, fx_out, outputs=noise) for o in noise] == ["SUPPORTED", "SUPPORTED"]
    image = [_out("Color"), _out("Alpha")]
    assert [_classify_out("LEAF_IMG", o, fx_out, outputs=image) for o in image] == ["SUPPORTED", "DROPPED-SILENT"]


def test_addon_output_name_lookup_is_evidence_and_a_plain_read_is_not(fx_out):
    """The addon's `modes.get(from_socket name)` names Texture Coordinate's outputs; a bare read of the name
    (PLAIN) distinguishes nothing (NEGATIVE)."""
    assert fx_out["COORDS"]["named"] == frozenset({"UV", "Generated"})
    assert "PLAIN" not in fx_out or fx_out["PLAIN"]["named"] == frozenset()
    ev = {"COORDS": {"classification": "SUPPORTED", "sockets": set()}}
    outs = [_out("Generated"), _out("Normal"), _out("UV")]
    assert [_classify_out("COORDS", o, fx_out, evidence=ev, vm={}, outputs=outs) for o in outs] == \
        ["SUPPORTED", "DROPPED-SILENT", "SUPPORTED"]


# --- #1101 review finding 2: the compiler's approximation report caps an output at APPROXIMATED ---------------

def test_output_appended_to_an_approx_report_is_approximated_negative_fixture(fx_out):
    assert fx_out["APPROX_NODE"]["approximate"] == frozenset({"Soft"})  # `builder.log` is not a report
    outs = [_out("Soft"), _out("Hard")]
    assert [_classify_out("APPROX_NODE", o, fx_out, outputs=outs) for o in outs] == ["APPROXIMATED", "SUPPORTED"]


def test_unread_output_stays_dropped_silent_negative_fixture(fx_out):
    """NEGATIVE: an output the compiler refuses is not credited, an accepted one is."""
    assert _classify_out("GUARDED", _out("A"), fx_out) == "SUPPORTED"
    assert _classify_out("GUARDED", _out("Z"), fx_out) == "DROPPED-SILENT"
    assert _classify_out("REJECT", _out("Bad"), fx_out) == "DROPPED-SILENT"
    assert _classify_out("REJECT", _out("Good"), fx_out) == "SUPPORTED"
    assert _classify_out("DICT", _out("W"), fx_out) == "DROPPED-SILENT"


def test_output_matches_by_name_or_identifier(fx_out):
    assert _classify_out("GUARDED", _out("Factor", "A"), fx_out) == "SUPPORTED"
    assert _classify_out("GUARDED", _out("A", "Other"), fx_out) == "SUPPORTED"


def test_a_node_with_no_handler_drops_every_output():
    cls, note = GEN.classify_output_socket("NOPE", _out("Color"), {}, frozenset(), {}, {})
    assert cls == "DROPPED-SILENT" and "no handler" in note


def test_handled_node_output_inherits_the_node_class():
    ev = {"APPROX": {"classification": "APPROXIMATED", "sockets": set()},
          "FULL": {"classification": "SUPPORTED", "sockets": set()}}
    assert GEN.classify_output_socket("APPROX", _out("BSDF"), ev, frozenset(), {}, {})[0] == "APPROXIMATED"
    assert GEN.classify_output_socket("FULL", _out("BSDF"), ev, frozenset(), {}, {})[0] == "SUPPORTED"


def test_output_variant_of_an_unread_data_type_is_not_credited():
    """Map Range's Vector output exists only for data_type FLOAT_VECTOR, which its branch never reads."""
    vm = {"MAP": {"props_read": {"interpolation_type"}, "accepted_types": None}}
    props = {"data_type": {}, "interpolation_type": {}}
    assert GEN.classify_output_socket("MAP", _out("Result"), {}, frozenset(), vm, {}, props)[0] == "SUPPORTED"
    assert GEN.classify_output_socket("MAP", _out("Vector", enabled=False), {}, frozenset(), vm, {}, props)[0] \
        == "DROPPED-SILENT"
    vm["MAP"]["props_read"].add("data_type")  # a branch that reads it owns the variant
    assert GEN.classify_output_socket("MAP", _out("Vector", enabled=False), {}, frozenset(), vm, {}, props)[0] \
        == "SUPPORTED"


def test_data_type_gate_credits_only_accepted_output_variants():
    vm = {"MIX": {"props_read": {"data_type"}, "accepted_types": {"VALUE", "RGBA"}}}
    assert GEN.classify_output_socket("MIX", {"name": "Result", "identifier": "Result_Float", "type": "VALUE"},
                                      {}, frozenset(), vm, {})[0] == "SUPPORTED"
    assert GEN.classify_output_socket("MIX", {"name": "Result", "identifier": "Result_Rotation", "type": "ROTATION"},
                                      {}, frozenset(), vm, {})[0] == "DROPPED-SILENT"


# --- output evidence: the shipped compiler -------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_out():
    return GEN.scan_output_evidence(None, vm_path=VM)


def test_real_light_path_accepts_the_compiler_tuple_and_not_portal_depth(real_out):
    accepted = real_out["LIGHT_PATH"]["accepted"]
    assert {"Is Camera Ray", "Is Shadow Ray", "Ray Length", "Transmission Depth"} <= accepted
    assert "Portal Depth" not in accepted and len(accepted) == 14


def test_real_object_info_and_attribute_outputs(real_out):
    assert real_out["OBJECT_INFO"]["accepted"] == frozenset(
        {"Location", "Color", "Alpha", "Object Index", "Material Index", "Random"})
    # `Fac` (the identifier) and `Factor` (Blender 5's name) are both in the compiler's dict.
    assert {"Color", "Vector", "Fac", "Factor", "Alpha"} <= real_out["ATTRIBUTE"]["accepted"]
    assert real_out["VERTEX_COLOR"]["accepted"] == real_out["ATTRIBUTE"]["accepted"]


def test_real_geometry_only_backfacing_and_layer_weight_two_outputs(real_out):
    assert real_out["NEW_GEOMETRY"]["accepted"] == frozenset({"Backfacing"})
    assert real_out["LAYER_WEIGHT"]["accepted"] == frozenset({"Fresnel", "Facing"})
    assert real_out["SEPXYZ"]["accepted"] == frozenset({"X", "Y", "Z"})
    assert real_out["MATH"]["accepted"] is None  # one output, never inspected


def test_real_light_path_approximations_are_the_reported_four(real_out):
    """#1101 finding 2: the four outputs in LIGHT_PATH_APPROXIMATE (reported via builder.light_path_approx ->
    _warn_shader_fallback) are approximate. Transparent Depth is NOT: since #1033 / PR #1078 the engine counts
    transparent pass-throughs in transparentDepth on CPU and GPU (astroray/light_path.h next_surface)."""
    assert real_out["LIGHT_PATH"]["approximate"] == frozenset(
        {"Is Diffuse Ray", "Is Glossy Ray", "Diffuse Depth", "Glossy Depth"})


def test_real_texture_leaves_and_the_outputs_they_distinguish(real_out):
    for t in ("TEX_IMAGE", "TEX_NOISE", "TEX_VORONOI", "TEX_CHECKER", "TEX_BRICK", "TEX_WAVE", "TEX_GRADIENT",
              "TEX_MAGIC"):
        assert real_out[t]["texture_leaf"], t
    assert real_out["TEX_VORONOI"]["named"] == frozenset({"Color", "Fac", "Factor"})
    assert "Color" not in real_out["TEX_NOISE"]["named"]  # only Voronoi's branch tests Color
    assert real_out["VALTORGB"]["named"] == frozenset() and real_out["VECT_MATH"]["named"] == frozenset()


def test_real_texture_coordinate_outputs_come_from_the_affine_resolver():
    out = GEN.scan_output_evidence(None, vm_path=VM, addon_path=ADDON)
    assert out["TEX_COORD"]["named"] >= {"UV", "Generated", "Object", "Camera", "Window", "Reflection", "Normal"}


# --- root / scene-level nodes: the fixture addon --------------------------------------------------------------

def test_root_branch_and_variable_reads_are_credited(fx_root):
    assert fx_root["OUT_A"]["sockets"] == {"Volume", "Surface", "Displacement"}  # Displacement via the one-level helper
    assert fx_root["OUT_A"]["properties"] == {"is_active_output"}
    assert fx_root["BG"]["sockets"] == {"Strength", "Color"}
    assert fx_root["OUT_L"]["sockets"] == {"Surface"} and fx_root["OUT_L"]["properties"] == {"is_active_output"}
    assert fx_root["IES"]["sockets"] == {"Strength"}


def test_root_reads_on_other_receivers_are_not_credited(fx_root):
    """NEGATIVE: `nt.inputs.get('Thickness')` is not the output node; the light Emission's `Color` is reached
    through a link, not selected by the type test; an environment node that reads no socket gets none."""
    assert "Thickness" not in fx_root["OUT_A"]["sockets"]
    assert "Color" not in fx_root["OUT_L"]["sockets"]
    assert fx_root["ENV"]["sockets"] == set()


def test_root_branch_credits_only_reads_on_the_tested_node_negative_fixture(fx_root):
    """NEGATIVE (#1101 finding 4): inside `if node.type == 'OUT_B'`, `other.inputs['Thickness']` and
    `getattr(other, 'target')` are another node's; `not (node.type == 'NEG')` is no evidence for NEG."""
    assert fx_root["OUT_B"]["sockets"] == {"Surface"}
    assert fx_root["OUT_B"]["properties"] == set()
    assert not fx_root.get("NEG", {"sockets": set()})["sockets"]


def test_root_evidence_records_the_consuming_methods(fx_root):
    assert fx_root["BG"]["methods"] == {"world"}
    assert fx_root["OUT_A"]["methods"] == {"material", "disp"}


def test_root_evidence_applies_only_to_live_sockets_and_unhandled_types():
    nodes = [{"node_type": "OUT_A", "sockets_in": [_out("Surface"), _out("Thickness")],
              "properties": {"is_active_output": {}, "target": {}}},
             {"node_type": "HANDLED", "sockets_in": [_out("Surface")], "properties": {}}]
    reads = {"OUT_A": {"sockets": {"Surface", "Gone"}, "properties": {"is_active_output"}, "source_lines": [3]},
             "HANDLED": {"sockets": {"Surface"}, "properties": set(), "source_lines": [4]}}
    ev = GEN._apply_root_node_evidence({"HANDLED": {"sockets": set(), "classification": "SUPPORTED"}}, reads, nodes,
                                       set())
    assert ev["OUT_A"]["sockets"] == {"Surface"} and ev["OUT_A"]["properties"] == {"is_active_output"}
    assert ev["HANDLED"]["sockets"] == set()  # a type with scanned evidence is not overwritten


def test_group_inline_evidence_is_the_inline_shader_nodes_call(tmp_path):
    src = tmp_path / "a.py"
    src.write_text("class CustomRaytracerRenderEngine:\n    def f(self, mat):\n        return mat.inline_shader_nodes()\n",
                   encoding="utf-8")
    assert GEN.scan_group_inline_evidence(None, addon_path=src) is True
    src.write_text("class CustomRaytracerRenderEngine:\n    def f(self, mat):\n        return mat.node_tree\n",
                   encoding="utf-8")
    assert GEN.scan_group_inline_evidence(None, addon_path=src) is False


def test_scans_are_deterministic(fx_out, tmp_path):
    path = tmp_path / "shader_vm_compiler.py"
    path.write_text(FIXTURE_COMPILER, encoding="utf-8")
    walker = tmp_path / "walker.py"
    walker.write_text(FIXTURE_WALKER, encoding="utf-8")
    assert GEN.scan_output_evidence(None, vm_path=path, addon_path=walker) == fx_out


# --- root / scene-level nodes and the Mix Shader branch: the shipped addon ------------------------------------

@pytest.fixture(scope="module")
def real_root():
    return GEN.scan_root_node_evidence(None, addon_path=ADDON)


def test_real_root_nodes_credit_what_the_engine_reads(real_root):
    assert {"Surface", "Volume", "Displacement"} <= real_root["OUTPUT_MATERIAL"]["sockets"]
    assert "is_active_output" in real_root["OUTPUT_MATERIAL"]["properties"]
    assert real_root["OUTPUT_WORLD"]["sockets"] >= {"Volume"}
    assert {"Color", "Strength"} <= real_root["BACKGROUND"]["sockets"]
    assert {"Surface"} <= real_root["OUTPUT_LIGHT"]["sockets"]
    assert "is_active_output" in real_root["OUTPUT_LIGHT"]["properties"]
    assert "Strength" in real_root["TEX_IES"]["sockets"]


def test_real_root_nodes_without_a_read_get_no_credit(real_root):
    """NEGATIVE: Material Output's Thickness, World Output's Surface (only the UI panel reads it), the
    Environment texture's Vector and the IES texture's Vector are read nowhere in the engine."""
    assert "Thickness" not in real_root["OUTPUT_MATERIAL"]["sockets"]
    assert "Surface" not in real_root["OUTPUT_WORLD"]["sockets"]
    assert "Vector" not in real_root.get("TEX_ENVIRONMENT", {"sockets": set()})["sockets"]
    assert "Vector" not in real_root["TEX_IES"]["sockets"]
    assert "is_active_output" not in real_root["OUTPUT_WORLD"]["properties"]


def test_real_addon_scans_the_mix_and_add_shader_branches():
    ev = GEN.scan_addon_source_for_evidence(_addon_namespace())
    assert {"Shader", "Shader_001", "Fac"} <= ev["MIX_SHADER"]["sockets"]
    assert {"Shader", "Shader_001"} <= ev["ADD_SHADER"]["sockets"]


def test_real_addon_inlines_groups():
    assert GEN.scan_group_inline_evidence(None, addon_path=ADDON) is True
    # #1101 finding 6 (documented, not restricted): only material trees are inlined
    assert GEN.scan_group_inline_methods(None, addon_path=ADDON) == ("convert_node_material",)


# --- #1101 review finding 5: a duplicate-named socket is credited only by its own identifier ------------------

MIX_LIKE_SOCKETS = [_out("Fac"), _out("Shader"), _out("Shader", "Shader_001")]


def _generic_ids(sockets):
    node = {"node_type": "MIXLIKE", "sockets_in": MIX_LIKE_SOCKETS, "properties": {}}
    ev = {"MIXLIKE": {"sockets": set(sockets), "properties": set(), "classification": "SUPPORTED",
                      "source_lines": [1]}}
    return GEN.classify_shader_node(node, ev, [])["supported_socket_ids"]


def test_reading_only_shader_does_not_credit_shader_001_negative_fixture():
    assert _generic_ids({"Fac", "Shader"}) == {"Fac", "Shader"}  # NEGATIVE: Shader_001 is never read
    assert _generic_ids({"Fac", "Shader", "Shader_001"}) == {"Fac", "Shader", "Shader_001"}


def test_mix_like_addon_branch_reading_one_shader_credits_one(tmp_path):
    """The same negative through the addon scanner: a `_shader_input_node(node, 'Shader')` branch alone."""
    src = tmp_path / "mixlike_addon.py"
    src.write_text(
        "class CustomRaytracerRenderEngine:\n"
        "    def _shader_spec_from_node(self, node, renderer=None, node_tree=None, depth=0):\n"
        "        ntype = node.type\n"
        "        if ntype == 'MIXLIKE':\n"
        "            a = self._shader_input_node(node, 'Shader')\n"
        "            return a\n", encoding="utf-8")
    mod = types.ModuleType("pkg320_mixlike_stub")
    mod.__file__ = str(src)
    sys.modules["pkg320_mixlike_stub"] = mod
    cls = type("CustomRaytracerRenderEngine", (), {"__module__": "pkg320_mixlike_stub"})
    ev = GEN.scan_addon_source_for_evidence(types.SimpleNamespace(CustomRaytracerRenderEngine=cls))
    assert ev["MIXLIKE"]["sockets"] == {"Shader"}
    node = {"node_type": "MIXLIKE", "sockets_in": MIX_LIKE_SOCKETS, "properties": {}}
    assert GEN.classify_shader_node(node, ev, [])["supported_socket_ids"] == {"Shader"}


# --- #1101 review finding 3: partially honoured root sockets are capped at APPROXIMATED -----------------------

def test_partial_handling_caps_lower_only():
    rows = [{"category": "shader_node", "feature": f, "socket_or_prop": s, "classification": c, "notes": ""}
            for (f, s), c in ((("OUTPUT_MATERIAL", "input:Displacement"), "SUPPORTED"),
                              (("OUTPUT_WORLD", "input:Volume"), "DROPPED-SILENT"),
                              (("BACKGROUND", "input:Strength"), "SUPPORTED"))]
    out = GEN._apply_scanner_blind_overrides(rows)
    assert [r["classification"] for r in out] == ["APPROXIMATED", "DROPPED-SILENT", "SUPPORTED"]


def test_partial_handling_caps_still_describe_the_addon():
    """Each cap cites a silent fallback that must still exist; delete the cap when the addon reports it."""
    src = ADDON.read_text(encoding="utf-8")
    assert "if getattr(disp_node, 'type', None) != 'DISPLACEMENT':" in src
    assert "volume_node.type in {'VOLUME_SCATTER', 'PRINCIPLED_VOLUME'}" in src
    assert "evaluated = self._get_socket_color(color_input)" in src
    assert set(GEN.PARTIAL_HANDLING_CAPS) == {("OUTPUT_MATERIAL", "input:Displacement"),
                                              ("OUTPUT_WORLD", "input:Volume"), ("BACKGROUND", "input:Color")}


# --- #1101 review finding 7: a stale scanner review cannot score a changed scanner ----------------------------

def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


def test_scanner_proof_rejects_a_scanner_changed_since_the_review(tmp_path):
    repo, origin = tmp_path / "repo", tmp_path / "origin.git"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "core.autocrlf", "false")
    source = repo / CR.SCANNER_SOURCE_PATH
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# reviewed scanner\n")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "scanner")
    commit = _git(repo, "rev-parse", "HEAD")
    source_sha = hashlib.sha256(b"# reviewed scanner\n").hexdigest()
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    receipt_path = repo / "receipt.json"
    receipt_path.write_text(json.dumps({
        "schema": CR.SCANNER_REVIEW_RECEIPT_SCHEMA, "issue": 823, "commit": commit,
        "source_path": CR.SCANNER_SOURCE_PATH, "source_sha256": source_sha, "verdict": "ACCEPT",
        "reviewer": {"id": "independent-fixture", "signature": "a" * 64, "signed_at": "2026-10-06T00:00:00Z"}}),
        encoding="utf-8")
    proof = {"schema": CR.SCANNER_PROOF_SCHEMA, "required": 823, "integrated": True, "commit": commit,
             "source_path": CR.SCANNER_SOURCE_PATH, "source_sha256": source_sha,
             "review_receipt": {"path": "receipt.json", "sha256": CR.sha256_file(receipt_path)}}
    assert CR.verify_scanner_integration_proof(proof, repo) == (True, "")
    source.write_bytes(b"# reviewed scanner\r\n")  # a CRLF checkout of the same source is the same source
    assert CR.verify_scanner_integration_proof(proof, repo) == (True, "")
    source.write_bytes(b"# reviewed scanner\n# new credit rule\n")  # NEGATIVE: the scanner changed since
    assert CR.verify_scanner_integration_proof(proof, repo) == (
        False, "scanner source on disk differs from the reviewed source (re-review required)")
    source.unlink()
    assert CR.verify_scanner_integration_proof(proof, repo) == (False, "scanner source missing on disk")


# --- one socket identity on both sides -----------------------------------------------------------------------

def _row(bl, prop, cls, sid=None, category="shader_node"):
    r = {"category": category, "feature": bl, "bl_idname": bl, "socket_or_prop": prop, "classification": cls}
    if sid is not None:
        r["socket_id"] = sid
    return r


def test_identifier_and_legacy_key_resolve_to_one_row():
    m = CR.matrix_by_identity([
        _row("ShaderNodeMixShader", "input:Factor", "APPROXIMATED", "Fac"),
        _row("ShaderNodeMath", "input:Value[Value_001]", "SUPPORTED", "Value_001"),
        _row("ShaderNodeMix", "input:A[A_Color]", "SUPPORTED", "A_Color"),
        _row("ShaderNodeMath", "input:Value", "SUPPORTED", "Value"),
    ])
    for key in ("ShaderNodeMixShader|input:Factor", "ShaderNodeMixShader|input:Fac"):
        assert m[key] == "APPROXIMATED"
    for key in ("ShaderNodeMath|input:Value[Value_001]", "ShaderNodeMath|input:Value_001"):
        assert m[key] == "SUPPORTED"
    assert m["ShaderNodeMix|input:A_Color"] == "SUPPORTED"
    assert len(m) == 7  # the identifier alias adds no row when it equals the legacy key


def test_wildcard_rows_answer_dynamic_group_sockets_only_for_their_node():
    m = CR.matrix_by_identity([
        _row("NodeGroupOutput", "input:*", "SUPPORTED", "*", "structural"),
        _row("ShaderNodeGroup", "input:*", "SUPPORTED", "*", "structural"),
        _row("ShaderNodeMath", "input:Value", "SUPPORTED", "Value"),
    ])
    assert m.get("NodeGroupOutput|input:Socket_0") == "SUPPORTED"
    assert m.get("NodeGroupOutput|input:__extend__") == "SUPPORTED"
    assert m.get("ShaderNodeGroup|input:Socket_1") == "SUPPORTED"
    assert m.get("NodeGroupOutput|output:Socket_0") is None            # a direction without a row
    assert m.get("ShaderNodeMath|input:Missing") is None               # NEGATIVE: no wildcard for an ordinary node
    assert m.get("ShaderNodeMath|input:Missing", "ABSENT") == "ABSENT"


def test_worst_case_class_wins_when_two_rows_share_an_identity():
    m = CR.matrix_by_identity([_row("N", "input:X", "SUPPORTED", "Y"), _row("N", "input:Y", "DROPPED-SILENT", "Y")])
    assert m["N|input:Y"] == "DROPPED-SILENT"


# the identities #1088 lists as "absent from the matrix"
ISSUE_1088_IDENTITIES = (
    "ShaderNodeMath|input:Value_001",
    "ShaderNodeMix|input:A_Color", "ShaderNodeMix|input:B_Color", "ShaderNodeMix|input:A_Float",
    "ShaderNodeMix|input:B_Float", "ShaderNodeMix|input:A_Vector", "ShaderNodeMix|input:B_Vector",
    "ShaderNodeMix|input:Factor_Float",
    "ShaderNodeMixShader|input:Shader_001",
    "ShaderNodeHueSaturation|input:Fac", "ShaderNodeInvert|input:Fac", "ShaderNodeMixRGB|input:Fac",
    "ShaderNodeRGBCurve|input:Fac", "ShaderNodeVectorCurve|input:Fac", "ShaderNodeValToRGB|input:Fac",
    "ShaderNodeBrightContrast|input:Bright",
    "NodeGroupOutput|input:Socket_0", "NodeGroupOutput|input:__extend__", "ShaderNodeGroup|input:Socket_1",
)


def test_every_issue_1088_identity_resolves_in_the_committed_matrix():
    m = CR.matrix_by_identity(json.loads(MATRIX.read_text(encoding="utf-8")))
    unresolved = [k for k in ISSUE_1088_IDENTITIES if m.get(k) is None]
    assert not unresolved, unresolved


def test_no_identifier_alias_collides_with_another_sockets_legacy_key():
    """The identifier alias must never merge two sockets (the worst-case join would hide a drop)."""
    rows = json.loads(MATRIX.read_text(encoding="utf-8"))
    owner: dict[str, tuple] = {}
    clashes = []
    for row in rows:
        ident = (row["category"], row["feature"], row["bl_idname"], row["socket_or_prop"])
        for key in CR.matrix_identity_keys(row):
            if owner.setdefault(key, ident) != ident:
                clashes.append((key, owner[key], ident))
    assert not clashes, clashes[:5]


def test_committed_matrix_credits_the_listed_rows_and_keeps_the_negatives():
    m = CR.matrix_by_identity(json.loads(MATRIX.read_text(encoding="utf-8")))
    credited = (
        "ShaderNodeLightPath|output:Is Camera Ray", "ShaderNodeLightPath|output:Is Shadow Ray",
        "ShaderNodeLightPath|output:Ray Length", "ShaderNodeAttribute|output:Fac", "ShaderNodeVertexColor|output:Color",
        "ShaderNodeObjectInfo|output:Random", "ShaderNodeMixShader|input:Fac", "ShaderNodeMixShader|input:Shader",
        "ShaderNodeMixShader|input:Shader_001", "ShaderNodeOutputMaterial|input:Surface",
        "ShaderNodeOutputMaterial|input:Volume", "ShaderNodeOutputMaterial|input:Displacement",
        "ShaderNodeOutputMaterial|prop:is_active_output", "ShaderNodeOutputLight|input:Surface",
        "ShaderNodeOutputWorld|input:Volume", "ShaderNodeBackground|input:Color", "ShaderNodeBackground|input:Strength",
        "ShaderNodeTexIES|input:Strength", "ShaderNodeBsdfDiffuse|output:BSDF", "ShaderNodeTexNoise|output:Fac",
    )
    for key in credited:
        assert m[key] in ("SUPPORTED", "APPROXIMATED"), key
    refused = (  # nothing in the compiler or the engine consumes these: no false credit
        "ShaderNodeLightPath|output:Portal Depth", "ShaderNodeNewGeometry|output:Normal",
        "ShaderNodeNewGeometry|output:Pointiness", "ShaderNodeMapRange|output:Vector",
        "ShaderNodeMix|output:Result_Rotation", "ShaderNodeOutputMaterial|input:Thickness",
        "ShaderNodeOutputWorld|input:Surface", "ShaderNodeTexEnvironment|input:Vector",
        "ShaderNodeTexIES|input:Vector", "ShaderNodeHairInfo|output:Intercept", "ShaderNodeRaycast|output:Is Hit",
    )
    for key in refused:
        assert m[key] == "DROPPED-SILENT", key


def test_committed_matrix_has_no_review_1101_false_credits():
    """#1101 review: each named false credit is fixed in the regenerated matrix."""
    m = CR.matrix_by_identity(json.loads(MATRIX.read_text(encoding="utf-8")))
    dropped = (  # finding 1: the handler computes the default output whichever output is linked
        "ShaderNodeValToRGB|output:Alpha", "ShaderNodeTexVoronoi|output:Position", "ShaderNodeTexVoronoi|output:W",
        "ShaderNodeTexVoronoi|output:Radius", "ShaderNodeTexImage|output:Alpha",
    )
    for key in dropped:
        assert m[key] == "DROPPED-SILENT", key
    approximated = (  # finding 2: reported approximations; finding 3: partially honoured root sockets
        "ShaderNodeLightPath|output:Is Diffuse Ray", "ShaderNodeLightPath|output:Is Glossy Ray",
        "ShaderNodeLightPath|output:Diffuse Depth", "ShaderNodeLightPath|output:Glossy Depth",
        "ShaderNodeOutputMaterial|input:Displacement", "ShaderNodeOutputWorld|input:Volume",
        "ShaderNodeBackground|input:Color",
    )
    for key in approximated:
        assert m[key] == "APPROXIMATED", key
    # finding 2, Transparent Depth: the review relied on a stale compiler comment ("always 0"); #1033 / PR #1078
    # made the engine count transparent pass-throughs (light_path.h next_surface, CPU + GPU), so the credit stands.
    assert m["ShaderNodeLightPath|output:Transparent Depth"] == "SUPPORTED"
    kept = (  # the outputs the code does distinguish stay credited
        "ShaderNodeValToRGB|output:Color", "ShaderNodeTexVoronoi|output:Distance", "ShaderNodeTexVoronoi|output:Color",
        "ShaderNodeTexImage|output:Color", "ShaderNodeTexNoise|output:Fac", "ShaderNodeTexNoise|output:Color",
        "ShaderNodeTexCoord|output:UV", "ShaderNodeTexCoord|output:Object", "ShaderNodeSeparateColor|output:Green",
        "ShaderNodeMix|output:Result_Color", "ShaderNodeLightPath|output:Is Camera Ray",
    )
    for key in kept:
        assert m[key] in ("SUPPORTED", "APPROXIMATED"), key
