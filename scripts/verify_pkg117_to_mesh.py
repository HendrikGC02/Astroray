"""Headless Blender 5.1 verify for pkg117: evaluated non-MESH objects yield
triangles via to_mesh() — the assumption convert_objects() relies on.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --python scripts/verify_pkg117_to_mesh.py
"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
results = []


def _eval_to_mesh(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    eobj = obj.evaluated_get(dg)
    me = eobj.to_mesh()
    n = 0 if me is None else len(me.polygons)
    eobj.to_mesh_clear()
    return n


# Curve with a bevel so it has surface geometry.
curve = bpy.data.curves.new("c", type="CURVE")
spline = curve.splines.new("BEZIER")
spline.bezier_points.add(2)
for i, bp in enumerate(spline.bezier_points):
    bp.co = (i * 1.0, 0.0, 0.0)
    bp.handle_left_type = bp.handle_right_type = "AUTO"
curve.bevel_depth = 0.1
cobj = bpy.data.objects.new("Curve", curve)
bpy.context.collection.objects.link(cobj)

# Text object.
txt = bpy.data.curves.new("t", type="FONT")
txt.body = "Hi"
tobj = bpy.data.objects.new("Text", txt)
bpy.context.collection.objects.link(tobj)

# Metaball.
mball = bpy.data.metaballs.new("m")
mball.elements.new()
mobj = bpy.data.objects.new("Meta", mball)
bpy.context.collection.objects.link(mobj)

bpy.context.view_layer.update()

for obj in (cobj, tobj, mobj):
    polys = _eval_to_mesh(obj)
    ok = polys > 0
    results.append((obj.name, obj.type, polys, ok))
    print(f"[pkg117-verify] {obj.name:6} ({obj.type:5}) -> {polys} polys  {'OK' if ok else 'FAIL'}")

if all(ok for *_, ok in results):
    print("[pkg117-verify] PASS: all non-MESH types produce triangles via to_mesh()")
else:
    print("[pkg117-verify] FAIL")
    raise SystemExit(1)
