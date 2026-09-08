"""Author the two-mesh regression fixture for the blend importer.

Run **once** with a real Blender:

    blender --background --python tests/fixtures/build_two_mesh.py

The output is committed at tests/fixtures/two_mesh.blend and exercised by
`tests/test_blend_import_format.py`. CI does not run this script — bpy is not
a CI dependency.

Why a second fixture: Blender writes each mesh's ``Attribute`` /
``AttributeArray`` / ``AttributeSingle`` DNA records from a temporary buffer,
so two separate mesh datablocks in one file get DATA blocks with *identical*
"old" addresses. Blender's own reader scopes DATA-block addresses to the
owning ID block; a file-global address map returns the wrong mesh's topology
(plane reading the sphere's corner_verts → IndexError). synthetic_min.blend
has a single mesh and cannot exercise this.
"""

from pathlib import Path

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)

# Two SEPARATE mesh datablocks. Plane: 4 verts / 1 quad. Sphere: kept small
# so the fixture stays lean; vertex count is asserted in the test.
bpy.ops.mesh.primitive_plane_add(size=4.0)
bpy.ops.mesh.primitive_uv_sphere_add(segments=8, ring_count=4, radius=1.0,
                                     location=(0.0, 0.0, 1.0))

out_path = Path(__file__).parent / "two_mesh.blend"
# compress=False keeps the file uncompressed so the format-level test can run
# without zstandard available.
bpy.ops.wm.save_as_mainfile(filepath=str(out_path), compress=False, copy=True)
print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")
