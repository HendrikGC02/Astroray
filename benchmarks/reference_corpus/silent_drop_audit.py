"""pkg310 -- silent-drop audit for the production node-tree corpus.

A *silent drop* is an exercised (node type, socket) pair that the frozen coverage matrix
(``docs/blender_parity/coverage_matrix.json``, pkg278) does not classify SUPPORTED AND that the
render's ``DegradationReport`` never mentions: the export lost or approximated it and told nobody.

"Exercised" follows pkg278's reachability rules (``coverage_report.trace_reachable``: backward from the
active Material/World/Light Output across links, group routing and mute) and the pkg310 spec: a reachable
input socket counts only if it is LINKED or holds a NON-DEFAULT value; a linked output and a non-default
known property count too. ``coverage_report --collect`` records every active input, so ``collect`` here
reuses its tree builder and reachability trace and adds the non-default filter (compared against a fresh
twin node with the same enum properties).

Deliberate deviations from the plain definition (each keeps the audit honest, none hides a drop):

* trace roots (Output Material / World / Light nodes) are never drops: the matrix marks their sockets
  DROPPED-SILENT because scene conversion, not the shader dispatch, consumes them;
* pairs in the ``world:`` tree are excluded and only counted (``world_pairs_excluded``): the shared stage HDRI
  world is identical in all eight scenes and is gated by the v2 world rows;
* output-socket pairs are judged only for node types the matrix has ``output:`` rows for (inputs-less nodes such as
  Attribute or Light Path); for every other node a linked output is evidence of use, not a classifiable pair;
* an APPROXIMATED pair with no report entry is listed under ``approximated_unreported`` and NOT scored: the matrix
  marks all 28 Principled sockets APPROXIMATED from an AST scan, so scoring that bucket would fail every material
  on matrix coarseness. It is still reported per scene so it can be tightened later.

Report matching is node-granular: the addon's report entries name a node type (``shader node 'X'``,
``_warn_shader_fallback(node_type, ...)``), not a socket, so any entry that names the node covers all of
its exercised pairs. That is the most generous reading; a pair listed here really has no trace in the report.

Steps (run from the repo root):

1. Collect (inside Blender; writes ``production/node_uses.json``)::

       blender -b --factory-startup --python benchmarks/reference_corpus/silent_drop_audit.py -- \\
           collect --manifest benchmarks/reference_corpus/production/manifest.json \\
           --out benchmarks/reference_corpus/production/node_uses.json

2. Audit (plain Python; reads the render logs ``mc_tolerance.render`` keeps next to each ``.npy``)::

       python benchmarks/reference_corpus/silent_drop_audit.py audit --work-dir <dir> [--out drops.json]

3. ``coverage``: the pkg278 weighted score formula over the matrix classification alone (an upper bound for gate (b))
   for the gate population snapshot and the production corpus; the gate score itself stays ``unmeasured`` until
   hash-verified evidence exists (``coverage_report --score``).
4. ``--self-test``: a fixture material with a deliberately unhandled node must be flagged, the same
   material must NOT be flagged once its node is reported, and a supported / unlinked node never is.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.reference_corpus import coverage_report as CR

MATRIX = REPO / "docs" / "blender_parity" / "coverage_matrix.json"
PROD = REPO / "benchmarks" / "reference_corpus" / "production"
# Structural nodes: they route or terminate the graph and carry no shading semantics of their own.
STRUCTURAL = frozenset({"NodeGroupInput", "NodeGroupOutput", "ShaderNodeGroup", "NodeReroute", "NodeFrame"})
# Trace roots: the matrix marks the Output node sockets DROPPED-SILENT ("no handler in the translation
# layer") because scene conversion, not the shader dispatch, consumes them. Never a drop.
ROOTS = frozenset({"ShaderNodeOutputMaterial", "ShaderNodeOutputWorld", "ShaderNodeOutputLight"})
# Blender node.type names the addon reports under, where they are not the CamelCase split of the bl_idname.
ALIASES = {
    "ShaderNodeValToRGB": ("valtorgb", "color ramp"),
    "ShaderNodeRGBCurve": ("curve rgb", "rgb curves"),
    "ShaderNodeFloatCurve": ("curve float", "float curve"),
    "ShaderNodeVectorMath": ("vect math", "vector math"),
    "ShaderNodeNewGeometry": ("new geometry", "geometry"),
    "ShaderNodeVertexColor": ("vertex color", "color attribute"),
    "ShaderNodeTexImage": ("tex image", "image texture"),
    "ShaderNodeBsdfPrincipled": ("bsdf principled", "principled"),
    "ShaderNodeMixShader": ("mix shader",),
    "ShaderNodeAddShader": ("add shader",),
    "ShaderNodeHueSaturation": ("hue sat", "hue saturation"),
}


# --------------------------------------------------------------------------- #
# Pure audit logic (no Blender)
# --------------------------------------------------------------------------- #

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).lower())


def node_aliases(bl_idname: str) -> list[list[str]]:
    """Token sequences under which a report entry can name this node type."""
    base = bl_idname.removeprefix("ShaderNode")
    seqs = [_tokens(base)] + [_tokens(a) for a in ALIASES.get(bl_idname, ())]
    return [s for s in seqs if s]


def reported_entries(log_text: str) -> list[str]:
    """The DegradationReport entries in a render log (``approximated/degraded/ignored <feature>: <detail>``).

    ``DegradationReport.emit`` prints one ``Astroray degradation: <summary> -- e1; e2; ...`` line."""
    out: list[str] = []
    for line in log_text.splitlines():
        if "Astroray degradation:" in line and " -- " in line:
            out.extend(e.strip() for e in line.split(" -- ", 1)[1].split("; ") if e.strip())
    return out


def is_reported(bl_idname: str, entries: list[str]) -> bool:
    for entry in entries:
        toks = _tokens(entry)
        for seq in node_aliases(bl_idname):
            n = len(seq)
            if any(toks[i:i + n] == seq for i in range(len(toks) - n + 1)):
                return True
    return False


def classification(matrix: dict[str, str], bl_idname: str, pair: dict) -> str:
    """Matrix classification for an exercised pair, trying identifier, UI name and ``name[identifier]``
    (the matrix keys inputs by UI name, the collector by identifier). ``UNCLASSIFIED`` when absent."""
    kind, _, ident = pair["socket"].partition(":")
    names = [pair.get("id") or ident, pair.get("name") or ident]
    keys = [f"{kind}:{n}" for n in names]
    if pair.get("name") and pair.get("id"):
        keys.append(f"{kind}:{pair['name']}[{pair['id']}]")
    for k in keys:
        cls = matrix.get(CR.canonical_identity(bl_idname, k))
        if cls:
            return cls
    return "UNCLASSIFIED"


def audit_scene(pairs: list[dict], matrix: dict[str, str], log_text: str) -> dict:
    """Silent drops of one scene under one backend's render log.

    ``pairs``: ``[{"bl_idname", "socket", "id", "name", "why"}]`` (the ``collect`` output for the scene)."""
    entries = reported_entries(log_text)
    # The matrix classifies output sockets only for nodes that have no inputs (Attribute, Light Path, ...);
    # for every other node a linked output is evidence of use, not a classifiable pair.
    out_nodes = {k.split("|", 1)[0] for k in matrix if "|output:" in k}
    silent, reported, approx_unreported, supported, world = [], [], [], 0, 0
    for p in pairs:
        if p["bl_idname"] in ROOTS:
            continue
        if p.get("tree", "").startswith("world:"):
            world += 1  # the shared stage HDRI world: identical in all eight scenes, gated by the v2 world rows
            continue
        if p["socket"].startswith("output:") and p["bl_idname"] not in out_nodes:
            continue
        cls = classification(matrix, p["bl_idname"], p)
        if cls == CR.SUPPORTED:
            supported += 1
        elif is_reported(p["bl_idname"], entries):
            reported.append({**p, "matrix": cls})
        elif cls == CR.APPROXIMATED:
            # The matrix says "approximated (emits a fallback warning)" but this render printed none.
            # Tracked separately and NOT scored: the matrix marks whole nodes (all 28 Principled sockets)
            # APPROXIMATED from an AST scan, so this bucket is dominated by matrix coarseness.
            approx_unreported.append({**p, "matrix": cls})
        else:
            silent.append({**p, "matrix": cls})
    return {"exercised": len(pairs), "supported": supported, "reported": reported, "silent": silent,
            "approximated_unreported": approx_unreported, "world_pairs_excluded": world,
            "report_entries": entries}


def load_matrix(path: Path = MATRIX) -> dict[str, str]:
    return CR.matrix_by_identity(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# In-Blender collector
# --------------------------------------------------------------------------- #

def _twin_defaults(bpy, node, cache: dict) -> tuple[dict, dict]:
    """``(socket defaults, property defaults)`` of a fresh node of ``node``'s type. The socket defaults are
    read from a twin that copies the node's known enum properties (they change which sockets exist and
    what they default to); the property defaults come from a pristine twin (Blender's node defaults differ
    from the RNA defaults ``coverage_report`` compares against, e.g. Principled ``distribution``)."""
    props = {k: getattr(node, k) for k in CR.KNOWN_NODE_PROPERTIES if hasattr(node, k)}
    key = (node.bl_idname, tuple(sorted((k, str(v)) for k, v in props.items())))
    if key in cache:
        return cache[key]
    tree = bpy.data.node_groups.new("_pkg310_twin", "ShaderNodeTree")
    try:
        pristine = tree.nodes.new(node.bl_idname)
        pdefaults = {k: getattr(pristine, k) for k in props}
        twin = tree.nodes.new(node.bl_idname)
        for k, v in props.items():
            try:
                setattr(twin, k, v)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass  # read-only / pointer-valued: leave at default
        sdefaults = {s.identifier: CR._json_safe(getattr(s, "default_value", None)) for s in twin.inputs}
        cache[key] = (sdefaults, pdefaults)
    finally:
        bpy.data.node_groups.remove(tree)
    return cache[key]


def _tree_of(bpy, tid: str):
    kind, _, name = tid.partition(":")
    if kind == "group":
        return bpy.data.node_groups[name]
    return {"material": bpy.data.materials, "world": bpy.data.worlds, "light": bpy.data.lights}[kind][name].node_tree


def collect_scene(bpy, blend_path: str) -> dict:
    """Exercised (node, socket) pairs of one .blend (reachable AND linked/non-default)."""
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    trees = CR._build_trees_from_bpy()
    reachable, errors = CR.trace_reachable(trees)
    cache: dict = {}
    pairs: list[dict] = []
    for tid, name in sorted(reachable):
        rec = trees[tid]["nodes"][name]
        if rec.get("mute") or rec["bl_idname"] in STRUCTURAL:
            continue
        node = _tree_of(bpy, tid).nodes[name]
        defaults, prop_defaults = _twin_defaults(bpy, node, cache)
        bl = rec["bl_idname"]
        for s in node.inputs:
            if not s.enabled:
                continue
            if s.is_linked:
                why = "linked"
            elif s.identifier in defaults and CR._json_safe(getattr(s, "default_value", None)) != defaults[s.identifier]:
                why = "value"
            else:
                continue
            pairs.append({"bl_idname": bl, "socket": f"input:{s.identifier}", "id": s.identifier,
                          "name": s.name, "why": why, "tree": tid, "node": name})
        for s in node.outputs:
            if s.is_linked:
                pairs.append({"bl_idname": bl, "socket": f"output:{s.identifier}", "id": s.identifier,
                              "name": s.name, "why": "linked", "tree": tid, "node": name})
        for prop in sorted(rec.get("prop_variants", {})):
            if prop in prop_defaults and getattr(node, prop) == prop_defaults[prop]:
                continue  # coverage_report's RNA-default test; the node's own default is what counts here
            pairs.append({"bl_idname": bl, "socket": f"prop:{prop}", "id": prop, "name": prop,
                          "why": "prop", "tree": tid, "node": name})
    return {"blend_path": str(blend_path), "scene_sha256": CR._sha256_file(Path(blend_path)),
            "collection_errors": errors, "pairs": pairs}


def cmd_collect(a) -> int:
    import bpy
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    scenes = {sid: collect_scene(bpy, e["blend_path"]) for sid, e in sorted(manifest["scenes"].items())}
    bad = {s: v["collection_errors"] for s, v in scenes.items() if v["collection_errors"]}
    if bad:
        print(f"[silent_drop_audit] collection errors: {bad}", file=sys.stderr)
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "pkg310.node_uses.v1", "scenes": scenes}, indent=1, sort_keys=True)
                   + "\n", encoding="utf-8", newline="\n")
    print(f"[silent_drop_audit] wrote {out}: " + ", ".join(f"{s}={len(v['pairs'])}" for s, v in scenes.items()))
    return 0


# --------------------------------------------------------------------------- #
# Audit over render logs
# --------------------------------------------------------------------------- #

def cmd_audit(a) -> int:
    uses = json.loads(Path(a.node_uses).read_text(encoding="utf-8"))["scenes"]
    matrix = load_matrix(a.matrix)
    work = Path(a.work_dir)
    result = {}
    for sid, scene in sorted(uses.items()):
        for backend in ("cpu", "gpu"):
            log = work / f"{sid}_{backend}_s{a.seed}.log"
            if not log.is_file():
                continue
            r = audit_scene(scene["pairs"], matrix, log.read_text(encoding="utf-8", errors="replace"))
            result[f"{sid}|{backend}"] = r
            print(f"{sid:22s} {backend}: exercised {r['exercised']:3d}  supported {r['supported']:3d}  "
                  f"reported {len(r['reported']):3d}  approx-unreported {len(r['approximated_unreported']):3d}  "
                  f"SILENT {len(r['silent']):3d}")
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


# --------------------------------------------------------------------------- #
# Weighted coverage ceiling (classification only)
# --------------------------------------------------------------------------- #

def weighted_ceiling(use_classes: dict[str, tuple[set, str]]) -> dict:
    """pkg278's weighted socket-coverage formula, S = sum(min(n, 3) * s) / sum(min(n, 3)), with ``s`` taken from
    the MATRIX CLASSIFICATION alone (SUPPORTED 1, APPROXIMATED 0.5, else 0) -- the upper bound gate (b) can reach.
    The gate score itself additionally needs a hash-verified per-backend, per-variant evidence artifact for
    every nonzero use (``coverage_report.score_use``), so it reads ``unmeasured`` until those exist; the matrix is
    backend-agnostic, so CPU and GPU share one ceiling."""
    num = den = 0.0
    silent = []
    for key, (scenes, cls) in sorted(use_classes.items()):
        w = min(len(scenes), CR.WEIGHT_CAP)
        num += w * (CR.SCORE_SUPPORTED if cls == CR.SUPPORTED else CR.SCORE_APPROXIMATION if cls == CR.APPROXIMATED else 0.0)
        den += w
        if cls == CR.DROPPED_SILENT or not cls:
            silent.append(key)
    return {"uses": len(use_classes), "weight": den, "ceiling": (num / den) if den else None,
            "matrix_silent": silent}


def gate_population_classes(snapshot: dict, matrix: dict[str, str]) -> dict[str, tuple[set, str]]:
    """key -> (scenes, matrix class) for a ``coverage_report --collect`` snapshot (the gate (b) population)."""
    uses = CR._ledger_uses(CR.materialize_use_ledger(snapshot))
    return {k: (scenes, matrix.get(k, "")) for k, scenes in uses.items()}


def production_classes(scenes: dict, matrix: dict[str, str]) -> dict[str, tuple[set, str]]:
    """Same, for the pkg310 production ``node_uses.json`` (the audit's pair filters apply)."""
    out_nodes = {k.split("|", 1)[0] for k in matrix if "|output:" in k}
    out: dict[str, tuple[set, str]] = {}
    for sid, scene in scenes.items():
        for p in scene["pairs"]:
            if p["bl_idname"] in ROOTS or p.get("tree", "").startswith("world:"):
                continue
            if p["socket"].startswith("output:") and p["bl_idname"] not in out_nodes:
                continue
            key = f"{p['bl_idname']}|{p['socket']}[{p['id']}]"
            out.setdefault(key, (set(), classification(matrix, p["bl_idname"], p)))[0].add(sid)
    return out


def cmd_coverage(a) -> int:
    matrix = load_matrix(a.matrix)
    gate = gate_population_classes(json.loads(Path(a.gate_node_uses).read_text(encoding="utf-8")), matrix)
    prod = production_classes(json.loads(Path(a.node_uses).read_text(encoding="utf-8"))["scenes"], matrix)
    for label, classes in (("gate (b) population", gate), ("production corpus", prod)):
        r = weighted_ceiling(classes)
        print(f"{label:22s}: {r['uses']:3d} uses, weight {r['weight']:.0f}, matrix-only ceiling "
              f"{r['ceiling']:.4f} (CPU = GPU), matrix-silent {len(r['matrix_silent'])}")
    return 0


# --------------------------------------------------------------------------- #
# Non-vacuity fixture
# --------------------------------------------------------------------------- #

def _fixture_graph(with_dead_branch: bool = True) -> dict:
    """A one-material graph: Output <- Principled (Base Color <- Attribute[unhandled], Roughness <- Noise
    [supported]); plus an unlinked Layer Weight that must NOT be exercised."""
    def node(bl, inputs=(), outputs=()):
        return {"bl_idname": bl, "mute": False, "is_group": False, "group_tree": None,
                "inputs": {i: {"linked": lk, "enabled": True} for i, lk in inputs},
                "outputs": {o: lk for o, lk in outputs}, "internal_links": []}
    nodes = {
        "Out": node("ShaderNodeOutputMaterial", [("Surface", True)]),
        "P": node("ShaderNodeBsdfPrincipled", [("Base Color", True), ("Roughness", True)], [("BSDF", True)]),
        "Attr": node("ShaderNodeAttribute", [], [("Color", True)]),
        "Noise": node("ShaderNodeTexNoise", [("Scale", False)], [("Fac", True)]),
    }
    links = [{"from_node": "P", "from_socket": "BSDF", "to_node": "Out", "to_socket": "Surface"},
             {"from_node": "Attr", "from_socket": "Color", "to_node": "P", "to_socket": "Base Color"},
             {"from_node": "Noise", "from_socket": "Fac", "to_node": "P", "to_socket": "Roughness"}]
    if with_dead_branch:
        nodes["Dead"] = node("ShaderNodeLayerWeight", [("Blend", False)], [("Fresnel", False)])
    return {"material:Fixture": {"kind": "material", "nodes": nodes, "links": links}}


def _fixture_pairs() -> list[dict]:
    trees = _fixture_graph()
    reachable, errors = CR.trace_reachable(trees)
    assert not errors, errors
    pairs = []
    for tid, name in sorted(reachable):
        node = trees[tid]["nodes"][name]
        for sock in CR.exercised_sockets_for(node)[0]:
            kind, _, ident = sock.partition(":")
            linked = (node["inputs"].get(ident, {}).get("linked") if kind == "input"
                      else node["outputs"].get(ident)) if kind in ("input", "output") else True
            if linked:  # collect() also keeps non-default values; the fixture has only links
                pairs.append({"bl_idname": node["bl_idname"], "socket": sock, "id": ident, "name": ident,
                              "why": "linked"})
    return pairs


def self_test() -> bool:
    matrix = load_matrix()
    pairs = _fixture_pairs()
    ids = {p["bl_idname"] for p in pairs}
    assert "ShaderNodeLayerWeight" not in ids, "an unreachable node must not be exercised"
    empty = audit_scene(pairs, matrix, "Render completed in 0.3s\n")
    flagged = {p["bl_idname"] for p in empty["silent"]}
    assert flagged == {"ShaderNodeAttribute"}, f"expected exactly the unhandled Attribute node, got {flagged}"
    assert {p["bl_idname"] for p in empty["approximated_unreported"]} == {"ShaderNodeBsdfPrincipled"}
    assert not [p for p in empty["silent"] if p["bl_idname"] == "ShaderNodeTexNoise"], "supported Noise flagged"
    told = audit_scene(pairs, matrix, "Astroray degradation: 0 approximated / 1 ignored -- "
                       "ignored shader node 'ATTRIBUTE': unsupported -> neutral grey\n")
    assert not [p for p in told["silent"] if p["bl_idname"] == "ShaderNodeAttribute"], "reported node still flagged"
    assert any(p["bl_idname"] == "ShaderNodeAttribute" for p in told["reported"])
    print(f"self-test OK: fixture flagged {sorted(flagged)}; reported-node case clean")
    return True


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("collect", help="(inside Blender) write the exercised-pair snapshot")
    c.add_argument("--manifest", default=str(PROD / "manifest.json"))
    c.add_argument("--out", default=str(PROD / "node_uses.json"))
    u = sub.add_parser("audit", help="diff the snapshot against each render log")
    u.add_argument("--node-uses", default=str(PROD / "node_uses.json"))
    u.add_argument("--matrix", default=str(MATRIX))
    u.add_argument("--work-dir", required=True)
    u.add_argument("--seed", type=int, default=278)
    u.add_argument("--out", default="")
    v = sub.add_parser("coverage", help="matrix-only weighted coverage ceiling (gate (b) formula, no evidence)")
    v.add_argument("--node-uses", default=str(PROD / "node_uses.json"))
    v.add_argument("--gate-node-uses", default=str(REPO / "docs" / "blender_parity" / "evidence" / "gate_b" / "node_uses_v3.json"))
    v.add_argument("--matrix", default=str(MATRIX))
    a = p.parse_args(argv)
    if a.self_test:
        return 0 if self_test() else 1
    if a.cmd == "collect":
        return cmd_collect(a)
    if a.cmd == "audit":
        return cmd_audit(a)
    if a.cmd == "coverage":
        return cmd_coverage(a)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
