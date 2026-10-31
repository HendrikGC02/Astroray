"""pkg328 Phase 1 -- gate (b) b4: a drop the per-render DegradationReport names is not a *silent* drop.

Layer 1 (no Blender): `reported_at_runtime` rows stay DROPPED-SILENT (no credit) but leave b4; an unreported one stays.
Layer 2 (committed artifacts): the matrix flags exactly the pkg321 / pkg328 reported drops, each flagged row's probe
  warning text exists in the addon source, the eight non-pkg321 rows carry their pkg328 resolution, and b4 on the
  candidate_v2 collection is empty.
Layer 3 (stub bpy): the addon fixes behind the resolutions (World Output Surface / active output, Material Output
  target, Map Range clamp, Image Texture interpolation report).
The probes themselves (real Blender) live in tests/test_pkg321_dropped_row_probes.py (`PROBE_VERDICT`).
"""
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from benchmarks.reference_corpus import coverage_report as CR  # noqa: E402

MATRIX = REPO / "docs" / "blender_parity" / "coverage_matrix.json"
EVIDENCE = REPO / "docs" / "blender_parity" / "evidence" / "pkg328" / "probe_results.json"
NODE_USES = REPO / "docs" / "blender_parity" / "evidence" / "gate_b" / "node_uses_v4_candidate_v2.json"


def _rows(*specs):
    return [{"bl_idname": n, "socket_or_prop": s, "classification": c, **({"reported_at_runtime": True} if r else {})}
            for n, s, c, r in specs]


# --------------------------------------------------------------------------- #
# layer 1
# --------------------------------------------------------------------------- #

def test_reported_drop_leaves_b4_and_still_earns_no_credit():
    key = CR.canonical_identity("N", "input:X")
    matrix = CR.matrix_by_identity(_rows(("N", "input:X", CR.DROPPED_SILENT, True)))
    assert matrix[key] == CR.DROPPED_SILENT                      # still dropped
    assert CR.silent_drops({key: {"S1"}}, matrix) == []         # but not silent
    assert CR._CLASS_RANK[matrix[key]] == min(CR._CLASS_RANK.values())    # lowest class: no matrix credit


def test_unreported_drop_stays_in_b4():
    key = CR.canonical_identity("N", "input:X")
    matrix = CR.matrix_by_identity(_rows(("N", "input:X", CR.DROPPED_SILENT, False)))
    assert CR.silent_drops({key: {"S1"}}, matrix) == [key]


def test_identity_with_one_unreported_dropped_row_stays_in_b4():
    # two rows answering one identity (legacy key + socket-id alias): one flagged, one not -> still counted
    rows = [{"bl_idname": "N", "socket_or_prop": "input:X", "socket_id": "X", "classification": CR.DROPPED_SILENT,
             "reported_at_runtime": True},
            {"bl_idname": "N", "socket_or_prop": "input:X[X_001]", "socket_id": "X", "classification": CR.DROPPED_SILENT}]
    matrix = CR.matrix_by_identity(rows)
    key = CR.canonical_identity("N", "input:X")
    assert CR.silent_drops({key: {"S1"}}, matrix) == [key]


def test_reported_flag_is_ignored_on_a_credited_row():
    key = CR.canonical_identity("N", "input:X")
    matrix = CR.matrix_by_identity(_rows(("N", "input:X", CR.SUPPORTED, True)))
    assert matrix[key] == CR.SUPPORTED and key not in matrix.reported


# --------------------------------------------------------------------------- #
# layer 2
# --------------------------------------------------------------------------- #

def _generator():
    spec = importlib.util.spec_from_file_location("pkg328_gen", REPO / "scripts" / "generate_blender_parity_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _matrix():
    return {(r["bl_idname"], r["socket_or_prop"]): r for r in json.loads(MATRIX.read_text(encoding="utf-8"))}


def test_matrix_flags_exactly_the_reported_drops():
    gen, rows = _generator(), _matrix()
    flagged = {k for k, r in rows.items() if r.get("reported_at_runtime")}
    assert flagged == set(gen.PKG321_REPORTED_DROPS)
    for key in flagged:
        assert rows[key]["classification"] == "DROPPED-SILENT", key        # never credited


def _addon_source():
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (REPO / "blender_addon").glob("*.py"))
    return re.sub(r"[\"']\s*\r?\n\s*[\"']", "", text)            # join adjacent string literals


def test_every_reported_drop_warning_text_exists_in_the_addon_source():
    test_mod = importlib.import_module("test_pkg321_dropped_row_probes")
    gen, src = _generator(), _addon_source()
    for key, (probe, _issue) in gen.PKG321_REPORTED_DROPS.items():
        warning = test_mod.PROBE_VERDICT[probe][1]
        assert warning, key
        # the warning is built with format arguments (`'%s'`): every literal fragment around a quoted value must exist
        fragments = [f.strip() for f in re.split(r"'[^']*'", warning) if len(f.strip()) > 8]
        if key == ("ShaderNodeVolumePrincipled", "input:Color Attribute"):   # volume_export composes label + reason
            fragments = ["volume 'Color Attribute'", "is not consumed"]
        assert fragments, (key, warning)
        for frag in fragments:
            # a leading `%s` label (the socket / node name) is substituted at runtime
            assert frag in src or frag.split(" ", 1)[-1] in src,                 f"{key}: warning fragment {frag!r} not found in blender_addon/*.py"


# (bl_idname, row) -> (classification, resolution). The eight rows #1088 / pkg321 left silent, resolved by pkg328.
PKG328_ROWS = {
    ("ShaderNodeOutputWorld", "input:Surface"): ("SUPPORTED", "scanner credit + addon fix; probes w_surface / w_bg_control"),
    ("ShaderNodeOutputWorld", "prop:is_active_output"): ("SUPPORTED", "scanner credit + addon fix; probe w_active_output"),
    ("ShaderNodeOutputMaterial", "prop:target"): ("SUPPORTED", "scanner credit + addon fix; probe o_target"),
    ("ShaderNodeOutputMaterial", "input:Thickness"): ("SUPPORTED", "Cycles ignores it too; probe o_thickness"),
    ("ShaderNodeTexEnvironment", "input:Vector"): ("APPROXIMATED", "probe credit; probe env_vector"),
    ("ShaderNodeMapRange", "prop:clamp"): ("SUPPORTED", "scanner credit + op-VM fix; probes mr_clamp_*"),
    ("ShaderNodeTexImage", "prop:interpolation"): ("DROPPED-SILENT", "reported drop #1215; probe img_interp"),
    ("ShaderNodeBsdfPrincipled", "input:Coat Normal"): ("DROPPED-SILENT", "reported drop #1130; probe n_principled_coat"),
}


@pytest.mark.parametrize("key", sorted(PKG328_ROWS))
def test_pkg328_row_resolution(key):
    cls, _why = PKG328_ROWS[key]
    row = _matrix()[key]
    assert row["classification"] == cls, row
    assert bool(row.get("reported_at_runtime")) == (cls == "DROPPED-SILENT"), row


def test_probe_credits_have_moving_probes_in_both_engines_and_cycles_ignored_rows_agree():
    gen = _generator()
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))["probes"]
    moved = lambda r: r["d_ab"] > 0 and (r["db_ab"] >= 3 * r["db_aa"] or r["d_ab"] >= 3 * r["d_aa"])  # noqa: E731
    for _key, (probe, _cls) in gen.PKG328_CYCLES_IGNORED.items():
        assert ev[probe]["cycles"]["d_ab"] == 0.0 and ev[probe]["astroray"]["d_ab"] == 0.0, probe
        assert ev[probe]["cycles"]["d_aa"] > 0.0                  # the Cycles leg really rendered (noise floor > 0)
    # every other new probe moves the render in Cycles and in Astroray (so the credit is not vacuous)
    for probe in ("w_bg_control", "w_surface", "w_active_output", "env_vector", "o_target", "mr_clamp_const",
                  "mr_clamp_linked"):
        assert moved(ev[probe]["cycles"]) and moved(ev[probe]["astroray"]), probe
    # the drop probe: Cycles moves, Astroray is bit-identical and names it
    assert moved(ev["img_interp"]["cycles"]) and ev["img_interp"]["astroray"]["d_ab"] == 0.0
    assert "#1215" in ev["img_interp"]["astroray"]["warn_A"]
    # Coat Normal alone is still inert on CPU (#1157 consumes it only when it follows Normal) and is named
    assert ev["n_principled_coat"]["astroray"]["d_ab"] == 0.0
    assert "'Coat Normal' is linked but not honoured" in ev["n_principled_coat"]["astroray"]["warn_B"]


def test_b4_on_candidate_v2_collection_is_empty():
    snapshot = json.loads(NODE_USES.read_text(encoding="utf-8"))
    uses = CR.extract_exercised_uses(CR._snapshot_node_trees(snapshot))
    matrix = CR.matrix_by_identity(json.loads(MATRIX.read_text(encoding="utf-8")))
    assert CR.silent_drops(uses, matrix) == []
    # the same exercised uses against the matrix without the flag: the reported rows come back (non-vacuity)
    plain = CR.IdentityMatrix(dict(matrix))
    assert len(CR.silent_drops(uses, plain)) >= 1


# --------------------------------------------------------------------------- #
# layer 3: the addon behaviour behind the resolutions (stub bpy)
# --------------------------------------------------------------------------- #
from _batch_a_stub import RecordingRenderer, load_addon  # noqa: E402


def _sock(value=None, linked_from=None):
    s = types.SimpleNamespace(default_value=value, is_linked=linked_from is not None, links=[])
    if linked_from is not None:
        s.links.append(types.SimpleNamespace(from_node=linked_from, from_socket=types.SimpleNamespace(name="Background")))
    return s


def _bg(name, gray):
    return types.SimpleNamespace(type="BACKGROUND", name=name,
                                 inputs={"Strength": _sock(1.0), "Color": _sock((gray, gray, gray, 1.0))})


def _world_out(name, src, active):
    return types.SimpleNamespace(type="OUTPUT_WORLD", name=name, is_active_output=active,
                                 inputs={"Surface": _sock(None, src), "Volume": _sock(None)})


def _setup(monkeypatch, tag, nodes):
    engine = load_addon(monkeypatch, tag).CustomRaytracerRenderEngine()
    r = RecordingRenderer()
    engine.setup_world(types.SimpleNamespace(world=types.SimpleNamespace(
        node_tree=types.SimpleNamespace(nodes=nodes), cycles=None)), r)
    return r.background_calls[-1]


def test_world_surface_link_picks_the_background(monkeypatch):
    x, y = _bg("BgX", 0.1), _bg("BgY", 0.9)
    assert _setup(monkeypatch, "w328a", [x, y, _world_out("O", x, True)])[0] == pytest.approx(0.1)
    assert _setup(monkeypatch, "w328b", [x, y, _world_out("O", y, True)])[0] == pytest.approx(0.9)


def test_world_active_output_picks_its_background(monkeypatch):
    x, y = _bg("BgX", 0.1), _bg("BgY", 0.9)
    o1, o2 = _world_out("O1", x, False), _world_out("O2", y, True)
    assert _setup(monkeypatch, "w328c", [x, y, o1, o2])[0] == pytest.approx(0.9)
    o1.is_active_output, o2.is_active_output = True, False
    assert _setup(monkeypatch, "w328d", [x, y, o1, o2])[0] == pytest.approx(0.1)


def test_image_interpolation_other_than_closest_is_reported(monkeypatch):
    addon = load_addon(monkeypatch, "w328e")
    for interp, reported in (("Linear", True), ("Cubic", True), ("Smart", True), ("Closest", False)):
        engine = addon.CustomRaytracerRenderEngine()
        engine._report_image_interpolation(types.SimpleNamespace(interpolation=interp, image=types.SimpleNamespace(name="i")))
        texts = [d for _f, d in engine._degradation_report().approximated]
        assert any("Interpolation '%s'" % interp in t and "#1215" in t for t in texts) == reported, (interp, texts)


def test_map_range_clamp_emits_a_range_clamp():
    """The op-VM Map Range kernel has no clamp bit; Cycles clamps to [To Min, To Max], so the compiler adds OP_CLAMP."""
    sys.path.insert(0, str(REPO / "blender_addon"))
    import shader_vm_compiler as svc

    class Sock:
        def __init__(self, name, default=0.0, link=None):
            self.name, self.default_value, self._link = name, default, link
            self.is_linked = link is not None
            self.links = [link] if link else []

    class Node:
        def __init__(self, ntype, inputs=(), **kw):
            self.type, self.inputs, self.outputs = ntype, _Socks(inputs), [types.SimpleNamespace(default_value=0.0)]
            self.__dict__.update(kw)

    class _Socks(list):
        def get(self, name):
            return next((s for s in self if s.name == name), None)

    tex = Node("TEX_IMAGE")
    link = types.SimpleNamespace(from_node=tex, from_socket=types.SimpleNamespace(name="Color"))
    ops = {}
    for clamp in (True, False):
        mr = Node("MAP_RANGE", interpolation_type="LINEAR", clamp=clamp, inputs=[
            Sock("Value", 0.0, link), Sock("From Min", 0.0), Sock("From Max", 0.5),
            Sock("To Min", 0.0), Sock("To Max", 0.25)])
        out_link = types.SimpleNamespace(from_node=mr, from_socket=types.SimpleNamespace(name="Value"))
        compiled = svc.compile_chain(Sock("Roughness", 0.5, out_link))
        flat = compiled["code_flat"]
        ops[clamp] = [flat[i] for i in range(0, len(flat), 8)]
    assert ops[True].count(svc.OP_CLAMP) == 1 and ops[False].count(svc.OP_CLAMP) == 0, ops
    assert ops[True][-1] == svc.OP_CLAMP            # the clamp is the program output
