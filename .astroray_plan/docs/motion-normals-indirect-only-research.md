# #947 motion-blur shading normals, #36 indirect-only objects (research notes, 2026-10-06)

## #947 root cause
Not the motion matrices (captured correctly: Blender `frame_set` at shutter open/close gives
-10.9 / +10.9 deg for the corpus vane) and not the linear vertex blend (a +-11 deg chord shrinks
the vane 1.8 %). The engine interpolated motion-triangle VERTICES by ray time but kept the
shutter-open facet / vertex normals, and the addon fed normals of the current-frame pose.
A rotating object was lit as frozen; the Cycles reference shows the glossy highlight sweeping
with the pose. Evidence: emission-only vane matches Cycles (coverage 1.67 vs 1.71); the lit corpus
vane read 0.74 with only floor+vane in the scene; static (motion off) read 0.998.

## Reference (Apache-2.0, Blender/Cycles)
- `intern/cycles/kernel/geom/motion_triangle.h`: `motion_triangle_vertices` / `motion_triangle_normal`
  (facet normal from the time-interpolated vertices) and `motion_triangle_smooth_normal`
  (vertex normals lerped over the motion steps, then barycentric).
- Implemented as: smooth triangle -> `lerp(n_open, n_close, t)` per vertex, each NORMALISED
  before the barycentric blend, then the blend normalised, `is_zero(N) ? Ng : N`; flat triangle ->
  `cross(p1-p0, p2-p0)` of the interpolated vertices. CPU `Triangle::hit`; GPU
  `gpu_motion_triangle_finalize`, run once on the accepted hit at the end of `gpu_bvh_hit` (not
  per traversal candidate: keeps the intersect kernel's registers at the pre-#947 level). Two motion steps only (the addon bakes
  shutter open/close); >2 steps / decomposed rotation interpolation were not needed.

## #36 indirect-only
`intern/cycles/blender/object.cpp` (~l.186): `use_indirect_only = !use_holdout && base_parent &&
(base_parent->flag & BASE_INDIRECT_ONLY)` clears `PATH_RAY_VISIBILITY_CAMERA`. Blender exposes the
flag as `Object.indirect_only_get(view_layer=)` on the ORIGINAL object (the evaluated copy reads
False; verified in Blender 5.2). A camera ray is one with `LPF_CAMERA` set (Cycles
PATH_RAY_CAMERA: the primary ray plus rays that only passed straight through transparent
surfaces; light_path.h `next_surface`), not just `bounce == 0`. CPU re-traces from just past each
indirect-only hit (offset `max(1e-4, 1e-5 t)`); GPU skips the flagged primitives inside the one
traversal (Cycles visibility mask), so a closed shell is passed through on both. The GPU reads the
flag from `lp_state`, which scene_upload makes the shade kernel maintain (HasProgram variant) only
for scenes that contain an indirect-only object.
Not covered: GPU ReSTIR path (separate driver), instanced geometry (flags are per flat object),
the CPU wavefront oracle `reference_pt_production`, collection-level holdout.
