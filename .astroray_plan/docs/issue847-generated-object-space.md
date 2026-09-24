# #847 — Generated coordinates in object space

**Reference (Apache-2.0):** Cycles `intern/cycles/blender/mesh.cpp`
`mesh_texture_space` + the `ATTR_STD_GENERATED` vertex attribute: Generated =
`(co - texspace_location) * 0.5 / texspace_size + 0.5` on OBJECT-local vertex
positions, stored per vertex and interpolated at the hit. `BKE_mesh_texspace_calc`
forces a zero-size axis to 1 (already mirrored by #834).

**Engine port.** The addon bakes world transforms into vertices, so it composes
the texture-space map with `matrix_world^-1` into one world->Generated 3x4 affine
per object (`_generated_texspace_affine`) and calls
`set_objects_generated_transform(begin, end, m)` on the object's triangle range.
The binding stores `m * v_i` as per-vertex Generated coords on each `Triangle`
(like Cycles' attribute). Consumers:

- CPU `Texture::textureCoordinates` (Generated): `hitObject->generatedCoord(p)`,
  barycentrics recomputed from the hit point (Ericson, RTCD §3.4).
- GPU wavefront: `SceneUploadResult::triGenerated` (3 GVec3 per triangle, NaN
  sentinel = none) on the `c_wfTexBinding` side table; `gpu_generatedCoord`
  (`__noinline__`) in `stage_advance.cu` interpolates it for 3D bakes.

The per-texture world bbox (`set_texture_generated_bbox`) stays the fallback for
non-triangle prims, instanced GPU scenes and old callers.

**Known cuts.** GPU instanced meshes keep the bbox frame. Motion-blurred
triangles interpolate on the shutter-start pose. Generated stays clamped to
[0,1] (GPU bake domain); Cycles does not clamp (only differs for custom texspace).
