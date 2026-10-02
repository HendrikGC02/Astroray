"""#996 -- the coverage-matrix scanner credits what the op-VM compiler actually handles.

Pure Python (no Blender, no astroray): a FIXTURE compiler with known handled / unhandled nodes is scanned
by ``scripts/generate_blender_parity_matrix`` and classified with hand-built node introspection records
(what the in-Blender enumerator records: sockets, enum properties, and the sockets Blender enables per enum
value).  The committed matrix is then checked against the production corpus: its only silent pairs are the
real drops.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("gen_matrix", REPO / "scripts" / "generate_blender_parity_matrix.py")
GEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GEN)  # bpy is optional at import time (#996)

FIXTURE_COMPILER = '''
class VMCompileError(Exception):
    pass

OPS = {'ADD': 0, 'MUL': 1, 'MAD': 2, 'WRAPLIKE': 3}
TERNARY = {'MAD'}
USE_SCALE = {'SCALE', 'REFRACT'}
VEC_OPS = {'ADD': 0, 'SCALE': 1, 'REFRACT': 2}
TRIG = {'SIN'}


def _get_input(node, *names):
    for n in names:
        s = node.inputs.get(n)
        if s is not None:
            return s
    return None


def compile_socket(socket, builder, depth=0):
    return _compile_socket_value(socket, builder, depth)


def _compile_socket_value(socket, builder, depth=0):
    node, out_name = socket
    ntype = node.type
    if ntype == 'MATH':
        op = node.operation
        if op not in OPS:
            raise VMCompileError("unsupported op")
        a = compile_socket(node.inputs[0], builder, depth + 1)
        b = compile_socket(node.inputs[1], builder, depth + 1)
        if op in TERNARY and len(node.inputs) > 2:
            compile_socket(node.inputs[2], builder, depth + 1)
        if getattr(node, 'use_clamp', False):
            pass
        return a
    if ntype == 'TM' and getattr(node, 'operation', None) in TRIG:   # compound dispatch test
        compile_socket(node.inputs[0], builder, depth + 1)
        return 0
    if ntype == 'TM':
        op = node.operation
        if op not in OPS:
            raise VMCompileError("unsupported op")
        compile_socket(node.inputs[0], builder, depth + 1)
        compile_socket(node.inputs[1], builder, depth + 1)
        return 0
    if ntype == 'RAMP':
        return compile_socket(_get_input(node, 'Fac'), builder, depth + 1)
    if ntype == 'VMATH':
        op = getattr(node, 'operation', None)
        ins = list(getattr(node, 'inputs', []))
        compile_socket(ins[0], builder, depth + 1)
        if op in USE_SCALE and len(ins) > 3:
            compile_socket(ins[3], builder, depth + 1)
        return 0
    return None
'''

FIXTURE_ADDON = '''
class Engine:
    def get_base_color_texture(self, node, input_name, renderer):
        linked_node = node
        PROC_TYPES = {'TEX_NOISE', 'TEX_WAVE'}
        if linked_node.type in PROC_TYPES:
            vector_inp = linked_node.inputs.get('Vector')
            return vector_inp
        if linked_node.type == 'TEX_IMAGE':
            return linked_node.inputs.get('Other')
'''


def _sock(name, ident=None):
    return {"name": name, "identifier": ident or name, "type": "VALUE"}


@pytest.fixture(scope="module")
def vm(tmp_path_factory):
    path = tmp_path_factory.mktemp("fx") / "shader_vm_compiler.py"
    path.write_text(FIXTURE_COMPILER, encoding="utf-8")
    return GEN.scan_vm_socket_evidence(None, vm_path=path)


def _classify(vm, node_type, sockets, props, enum_configs):
    info = {"node_type": node_type, "sockets_in": sockets,
            "properties": {p: {"type": t} for p, t in props.items()}, "enum_configs": enum_configs}
    return GEN._classify_compiler_node(info, {}, vm[node_type])


def test_dispatch_discovers_exactly_the_handled_nodes(vm):
    assert set(vm) == {"MATH", "RAMP", "VMATH", "TM"}  # an unhandled node type has no branch and no evidence


def test_name_or_identifier_read_credits_the_socket(vm):
    """Color Ramp's compiler read is `_get_input(node, 'Fac')`; Blender 5 names that socket `Factor`."""
    res = _classify(vm, "RAMP", [_sock("Factor", "Fac")], {}, {})
    assert res["supported_socket_ids"] == {"Fac"}


def test_properties_the_branch_reads_are_credited(vm):
    res = _classify(vm, "MATH", [_sock("Value"), _sock("Value", "Value_001")],
                    {"operation": "ENUM", "use_clamp": "BOOLEAN", "unrelated": "ENUM"}, {})
    assert res["properties_supported"] == ["operation", "use_clamp"]


def test_guarded_socket_credited_when_guard_holds_for_every_accepted_configuration(vm):
    third = _sock("Value", "Value_002")
    cfg = {"operation": {"ADD": ["Value", "Value_001"], "MAD": ["Value", "Value_001", "Value_002"],
                         "COMPARE": ["Value", "Value_001", "Value_002"]}}  # COMPARE not in OPS -> reported reject
    res = _classify(vm, "MATH", [_sock("Value"), _sock("Value", "Value_001"), third], {"operation": "ENUM"}, cfg)
    assert "Value_002" in res["supported_socket_ids"]


def test_guarded_socket_not_credited_when_an_accepted_configuration_skips_the_read(vm):
    third = _sock("Value", "Value_002")
    cfg = {"operation": {"MAD": ["Value", "Value_001", "Value_002"],
                         "WRAPLIKE": ["Value", "Value_001", "Value_002"]}}  # accepted by OPS, not TERNARY
    res = _classify(vm, "MATH", [_sock("Value"), _sock("Value", "Value_001"), third], {"operation": "ENUM"}, cfg)
    assert "Value_002" not in res["supported_socket_ids"]


def test_guarded_socket_without_enabled_configuration_not_credited(vm):
    third = _sock("Value", "Value_002")
    res = _classify(vm, "MATH", [_sock("Value"), _sock("Value", "Value_001"), third],
                    {"operation": "ENUM"}, {"operation": {"ADD": ["Value", "Value_001"]}})
    assert "Value_002" not in res["supported_socket_ids"]


def test_positional_guarded_read_with_arity_conjunct(vm):
    """`op in USE_SCALE and len(ins) > 3`: the arity conjunct is dropped, the membership guard evaluated."""
    socks = [_sock("Vector"), _sock("Vector", "Vector_001"), _sock("Vector", "Vector_002"), _sock("Scale")]
    ok = _classify(vm, "VMATH", socks, {"operation": "ENUM"},
                   {"operation": {"ADD": ["Vector", "Vector_001"], "SCALE": ["Vector", "Scale"],
                                  "REFRACT": ["Vector", "Scale"]}})
    assert "Scale" in ok["supported_socket_ids"]
    bad = _classify(vm, "VMATH", socks, {"operation": "ENUM"},
                    {"operation": {"SCALE": ["Vector", "Scale"], "ADD": ["Vector", "Scale"]}})
    assert "Scale" not in bad["supported_socket_ids"]  # ADD enables Scale in this config but the compiler skips it


def test_compound_dispatch_test_guards_its_branch_and_the_later_branches(vm):
    """`if ntype == 'TM' and op in TRIG:` reads only operand 0; the plain `ntype == 'TM'` branch is reached only
    for the other operations. A socket Blender enables for a TRIG operation is therefore NOT consumed."""
    socks = [_sock("Value"), _sock("Value", "Value_001")]
    leaky = _classify(vm, "TM", socks, {"operation": "ENUM"},
                      {"operation": {"ADD": ["Value", "Value_001"], "SIN": ["Value", "Value_001"]}})
    assert leaky["supported_socket_ids"] == {"Value"}
    tight = _classify(vm, "TM", socks, {"operation": "ENUM"},
                      {"operation": {"ADD": ["Value", "Value_001"], "SIN": ["Value"]}})
    assert tight["supported_socket_ids"] == {"Value", "Value_001"}


def test_procedural_vector_read_only_for_the_proc_types(tmp_path):
    path = tmp_path / "addon_init.py"
    path.write_text(FIXTURE_ADDON, encoding="utf-8")
    reads = GEN.scan_procedural_input_evidence(None, addon_path=path)
    assert reads == {"TEX_NOISE": {"Vector"}, "TEX_WAVE": {"Vector"}}  # TEX_IMAGE's 'Other' is not a proc branch
    ev = GEN._apply_procedural_input_evidence(
        {"TEX_NOISE": {"sockets": {"Scale"}}, "TEX_GABOR": {"sockets": set()}}, {**reads, "TEX_GABOR": {"Vector"}})
    assert ev["TEX_NOISE"]["sockets"] == {"Scale", "Vector"}


def test_real_compiler_scan_credits_the_issue_996_sockets():
    """The shipped compiler: Math/Vector Math `operation`, Mix `data_type`, Color Ramp Fac and Vector Math
    Scale are handled (the six stale-row families of #996)."""
    ev = GEN.scan_vm_socket_evidence(None, vm_path=REPO / "blender_addon" / "shader_vm_compiler.py")
    assert {"MATH", "MIX", "VALTORGB", "VECT_MATH", "COMBXYZ", "MAPPING"} <= set(ev)
    assert "operation" in ev["MATH"]["props_read"] and "operation" in ev["VECT_MATH"]["props_read"]
    assert "data_type" in ev["MIX"]["props_read"]
    assert "Fac" in ev["VALTORGB"]["named"]
    assert "MATH_TERNARY" in ev["MATH"]["consts"]


# --- the committed matrix against the production corpus ------------------------------------------------

REAL_SILENT_DROPS = {  # bl_idname -> why it is a real drop (no handler; the render is wrong)
    "ShaderNodeAddShader": "#955 Add Shader keeps the first BSDF",
    "ShaderNodeMixShader": "#991 Mix Shader Fac from Light Path ray type",
    "ShaderNodeVertexColor": "#990 Color Attribute",
    "ShaderNodeRGBCurve": "#992 RGB Curves",
}


def test_committed_matrix_leaves_only_real_drops_on_the_production_corpus():
    """With an empty DegradationReport the audit may flag only nodes with NO handler: every op-VM / texture
    chain pair (Mapping, Noise/Wave Vector, Math operation, Mix data_type, Color Ramp Fac, Combine XYZ ...)
    must classify handled.  Attribute / Object Info / Light Path / Float Curve / New Geometry are real
    gaps that the render's report names (the audit's report match), so they may appear here."""
    from benchmarks.reference_corpus import silent_drop_audit as AUDIT
    uses = json.loads((REPO / "benchmarks/reference_corpus/production/node_uses.json").read_text("utf-8"))["scenes"]
    matrix = AUDIT.load_matrix()
    allowed = set(REAL_SILENT_DROPS) | {
        "ShaderNodeAttribute", "ShaderNodeObjectInfo", "ShaderNodeLightPath", "ShaderNodeFloatCurve",
        "ShaderNodeNewGeometry"}
    flagged: dict[str, set] = {}
    for sid, scene in uses.items():
        for p in AUDIT.audit_scene(scene["pairs"], matrix, "")["silent"]:
            flagged.setdefault(p["bl_idname"], set()).add(f"{sid}:{p['id']}")
    assert set(flagged) <= allowed, {k: sorted(v) for k, v in flagged.items() if k not in allowed}
    for stale in ("prod_marble", "prod_wood", "prod_pbr_group", "prod_car_paint"):
        assert not [v for v in flagged.values() for x in v if x.startswith(stale + ":")], stale


def test_weighted_ceiling_matches_the_pkg278_formula():
    """S = sum(min(n,3) s) / sum(min(n,3)); s = 1 SUPPORTED, 0.5 APPROXIMATED, 0 otherwise."""
    from benchmarks.reference_corpus import silent_drop_audit as AUDIT
    r = AUDIT.weighted_ceiling({
        "a": ({"s1", "s2", "s3", "s4"}, "SUPPORTED"),     # weight 3 (capped), 1.0
        "b": ({"s1"}, "APPROXIMATED"),                    # weight 1, 0.5
        "c": ({"s1", "s2"}, "DROPPED-SILENT"),            # weight 2, 0
    })
    assert r["weight"] == 6 and r["ceiling"] == pytest.approx((3 + 0.5) / 6)
    assert r["matrix_silent"] == ["c"]
