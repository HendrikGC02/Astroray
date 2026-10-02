"""#881 - Blender Noise Texture reference values at exact points (run inside Blender).

Evaluates Blender's own Noise Texture (Geometry Nodes, blenlib noise.cc - the CPU
twin Blender keeps identical to Cycles kernel/svm/noisetex.h) at fixed points for
every dimension (1D-4D), noise type, a fractional detail and distortion, and writes
Fac + Color per point. tests/test_issue881_noise_dimensions.py compares the engine's
evaluator (astroray/procedural_tex.h) against this file.

    blender --background --factory-startup --python tests/fixtures/gen_issue881_noise_reference.py

Output: tests/data/issue881_noise_blender_reference.json
"""
import json
import random
from pathlib import Path

import bpy

OUT = Path(__file__).resolve().parents[1] / "data" / "issue881_noise_blender_reference.json"
TYPES = ["FBM", "MULTIFRACTAL", "HYBRID_MULTIFRACTAL", "RIDGED_MULTIFRACTAL", "HETERO_TERRAIN"]
CASES = []
for dims in ("1D", "2D", "3D", "4D"):
    for ntype in TYPES:
        CASES.append(dict(dims=dims, type=ntype, scale=2.3, detail=2.5, roughness=0.55,
                          lacunarity=2.1, offset=0.3, gain=1.1, distortion=0.0,
                          normalize=True))
    CASES.append(dict(dims=dims, type="FBM", scale=1.7, detail=3.0, roughness=0.5,
                      lacunarity=2.0, offset=0.0, gain=1.0, distortion=1.3, normalize=True))
    CASES.append(dict(dims=dims, type="FBM", scale=3.1, detail=1.0, roughness=0.6,
                      lacunarity=2.0, offset=0.0, gain=1.0, distortion=0.0, normalize=False))

rng = random.Random(881)
POINTS = [[rng.uniform(-3.0, 3.0) for _ in range(3)] for _ in range(24)]
WS = [rng.uniform(-2.0, 2.0) for _ in range(24)]

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("pts")
mesh.from_pydata([tuple(p) for p in POINTS], [], [])
obj = bpy.data.objects.new("pts", mesh)
bpy.context.scene.collection.objects.link(obj)
attr = mesh.attributes.new("w_in", "FLOAT", "POINT")
attr.data.foreach_set("value", WS)



def _sock(node, name):
    # Blender 5.2 key lookup misses disabled sockets (e.g. Offset under fBM).
    return next(s for s in node.inputs if s.name == name)


results = []
for case in CASES:
    tree = bpy.data.node_groups.new("ref", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = tree.nodes
    gin, gout = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    pos = n.new("GeometryNodeInputPosition")
    win = n.new("GeometryNodeInputNamedAttribute"); win.data_type = "FLOAT"
    win.inputs["Name"].default_value = "w_in"
    nz = n.new("ShaderNodeTexNoise")
    nz.noise_dimensions = case["dims"]
    nz.noise_type = case["type"]
    nz.normalize = case["normalize"]
    for k, sock in (("scale", "Scale"), ("detail", "Detail"), ("roughness", "Roughness"),
                    ("lacunarity", "Lacunarity"), ("offset", "Offset"), ("gain", "Gain"),
                    ("distortion", "Distortion")):
        _sock(nz, sock).default_value = case[k]
    tree.links.new(pos.outputs["Position"], _sock(nz, "Vector"))
    tree.links.new(win.outputs["Attribute"], _sock(nz, "W"))
    s_fac = n.new("GeometryNodeStoreNamedAttribute"); s_fac.data_type = "FLOAT"
    s_fac.inputs["Name"].default_value = "fac_out"
    s_col = n.new("GeometryNodeStoreNamedAttribute"); s_col.data_type = "FLOAT_COLOR"
    s_col.inputs["Name"].default_value = "col_out"
    fac_sock = nz.outputs.get("Fac") or nz.outputs.get("Factor")
    tree.links.new(gin.outputs["Geometry"], s_fac.inputs["Geometry"])
    tree.links.new(fac_sock, s_fac.inputs["Value"])
    tree.links.new(s_fac.outputs["Geometry"], s_col.inputs["Geometry"])
    tree.links.new(nz.outputs["Color"], s_col.inputs["Value"])
    tree.links.new(s_col.outputs["Geometry"], gout.inputs["Geometry"])
    mod = obj.modifiers.new("ref", "NODES"); mod.node_group = tree
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg).data
    fac = [0.0] * len(POINTS); col = [0.0] * (4 * len(POINTS))
    ev.attributes["fac_out"].data.foreach_get("value", fac)
    ev.attributes["col_out"].data.foreach_get("color", col)
    results.append({"case": case, "fac": fac,
                    "color": [col[4 * i:4 * i + 3] for i in range(len(POINTS))]})
    obj.modifiers.remove(mod)
    bpy.data.node_groups.remove(tree)

OUT.write_text(json.dumps({"blender": bpy.app.version_string, "points": POINTS, "w": WS,
                           "results": results}, indent=0), encoding="utf-8")
print("ISSUE881_REF OK", OUT, len(results))
