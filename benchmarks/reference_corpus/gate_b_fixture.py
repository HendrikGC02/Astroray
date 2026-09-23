"""Headless Blender fixture for the gate (b) computed-reachability collector.

Builds a synthetic material node graph in-memory (no render) with three
topologies the collector must get right, then runs the SAME ``_build_trees_from_bpy``
+ ``trace_reachable`` path the ``--collect`` command uses and asserts:

* a linked path (TexCoord -> Noise -> Principled -> Material Output) IS reached;
* an internally wired but DISCONNECTED branch (TexCoord2 -> Voronoi -> a second,
  unlinked Material Output) is NOT reached;
* a live ``ShaderNodeGroup`` path is traversed through Group Input/Output, and a
  disconnected node inside the group is NOT reached.

Run inside Blender:

    blender.exe -b --factory-startup --python benchmarks/reference_corpus/gate_b_fixture.py

Exits 0 iff every assertion holds.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _load_coverage_report():
    spec = importlib.util.spec_from_file_location(
        "pkg278_coverage_report", _REPO / "benchmarks" / "reference_corpus" / "coverage_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_fixture_material():
    import bpy

    scene = bpy.context.scene
    if not scene.objects:
        mesh = bpy.data.meshes.new("FixtureMesh")
        obj = bpy.data.objects.new("FixtureObj", mesh)
        scene.collection.objects.link(obj)
        scene.objects.active = obj

    mat = bpy.data.materials.new("GateBFixtureMat")
    mat.use_nodes = True
    nt = mat.node_tree
    obj = bpy.context.scene.objects[0]
    obj.data.materials.append(mat)
    nt.nodes.clear()

    output = nt.nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)

    principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (400, 0)
    nt.links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (200, 0)
    nt.links.new(noise.outputs["Color"], principled.inputs["Base Color"])

    texcoord = nt.nodes.new("ShaderNodeTexCoord")
    texcoord.location = (0, 0)
    nt.links.new(texcoord.outputs["UV"], noise.inputs["Vector"])

    # Disconnected, internally wired branch: its own Output Material that is
    # NOT active (is_active_output=False) so it must not be reached.
    disconnected_output = nt.nodes.new("ShaderNodeOutputMaterial")
    disconnected_output.is_active_output = False
    disconnected_output.location = (600, -400)
    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
    voronoi.location = (400, -400)
    nt.links.new(voronoi.outputs["Color"], disconnected_output.inputs["Surface"])
    texcoord2 = nt.nodes.new("ShaderNodeTexCoord")
    texcoord2.location = (200, -400)
    nt.links.new(texcoord2.outputs["UV"], voronoi.inputs["Vector"])

    # Live group path.
    group = bpy.data.node_groups.new("GateBFixtureGroup", "ShaderNodeTree")
    gi = group.nodes.new("NodeGroupInput")
    go = group.nodes.new("NodeGroupOutput")
    group.interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
    group.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    group_inner_bsdf = group.nodes.new("ShaderNodeBsdfDiffuse")
    group.links.new(gi.outputs["Color"], group_inner_bsdf.inputs["Color"])
    group.links.new(group_inner_bsdf.outputs["BSDF"], go.inputs["Shader"])
    # Disconnected node inside the group.
    group_inner_emission = group.nodes.new("ShaderNodeEmission")
    group_inner_emission.location = (0, -300)

    mat2 = bpy.data.materials.new("GateBGroupMat")
    mat2.use_nodes = True
    nt2 = mat2.node_tree
    nt2.nodes.clear()
    out2 = nt2.nodes.new("ShaderNodeOutputMaterial")
    group_node = nt2.nodes.new("ShaderNodeGroup")
    group_node.node_tree = group
    nt2.links.new(group_node.outputs["Shader"], out2.inputs["Surface"])

    # The collector intentionally ignores unused datablocks.  Put the second
    # material on a scene instance so the group route is part of the population.
    mesh2 = bpy.data.meshes.new("FixtureMeshGroup")
    obj2 = bpy.data.objects.new("FixtureObjGroup", mesh2)
    scene.collection.objects.link(obj2)
    mesh2.materials.append(mat2)

    return mat, mat2, group


def main() -> int:
    cr = _load_coverage_report()
    _build_fixture_material()
    trees = cr._build_trees_from_bpy()
    reachable, errors = cr.trace_reachable(trees)
    print(f"[gate_b_fixture] trees={len(trees)} reachable={len(reachable)} errors={len(errors)}")
    for err in errors:
        print(f"  collection error: {err}")

    failures: list[str] = []

    def reach_in(tree_id: str, bl_idname: str) -> bool:
        return any(trees[tid]["nodes"][name]["bl_idname"] == bl_idname
                   for (tid, name) in reachable if tid == tree_id)

    if errors:
        failures.append(f"unexpected collection errors: {errors}")
    for expected in ("ShaderNodeTexCoord", "ShaderNodeTexNoise", "ShaderNodeBsdfPrincipled"):
        if not reach_in("material:GateBFixtureMat", expected):
            failures.append(f"linked-path node {expected} not reached")
    if reach_in("material:GateBFixtureMat", "ShaderNodeTexVoronoi"):
        failures.append("disconnected branch node ShaderNodeTexVoronoi was wrongly reached")
    if not reach_in("group:GateBFixtureGroup", "ShaderNodeBsdfDiffuse"):
        failures.append("group-inner node ShaderNodeBsdfDiffuse not reached through the group")
    if reach_in("group:GateBFixtureGroup", "ShaderNodeEmission"):
        failures.append("group-inner disconnected node ShaderNodeEmission was wrongly reached")

    print(f"[gate_b_fixture] {'PASS' if not failures else 'FAIL'}")
    for failure in failures:
        print(f"  - {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
