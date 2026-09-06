# pkg114 — Cycles Two-Level BVH (TLAS over BLAS) Research

Research note per CLAUDE.md §6. Source: Blender Cycles, **Apache-2.0**
(SPDX-License-Identifier: Apache-2.0, SPDX-FileCopyrightText: 2011-2022
Blender Foundation; traversal also carries 2009-2010 NVIDIA Corp /
2009-2012 Intel Corp headers — all Apache-2.0 compatible).

GitHub mirror: `blender/cycles` (src/), main checkout: `blender/blender`
(intern/cycles/). Both kept in sync.

## Files mirrored

| Concept | File (cycles src/ path) | blender/ path |
|---|---|---|
| BVH2 build + two-level pack | `src/bvh/bvh2.cpp`, `src/bvh/bvh2.h` | `intern/cycles/bvh/bvh2.cpp` |
| Device traversal loop | `src/kernel/bvh/traversal.h` | `intern/cycles/kernel/bvh/traversal.h` |
| Dispatcher / scene_intersect | `src/kernel/bvh/bvh.h` | `intern/cycles/kernel/bvh/bvh.h` |
| Instance push/pop + dir helpers | `src/kernel/bvh/util.h` (clamp/inverse dir); push/pop in `src/kernel/geom/object.h` on main | — |
| object_fetch_transform | `src/kernel/geom/object.h` | — |
| Transform math | `src/util/transform.h` | `intern/cycles/util/transform.h` |

## 1. Build / data layout (bvh2.cpp)

`Transform` = 4x3 affine matrix, 3 rows of float4:
```c
struct Transform { float4 x, y, z; };   // util/transform.h
```
Each `KernelObject` (objects array) stores `.tfm` (object→world) and
`.itfm` (world→object inverse).

Two-level merge in `BVH2::pack_instances(nodes_size, leaf_nodes_size)`:
comment — *"Adjust primitive index to point to the triangle in the global
array, for geometry with transform applied and already in the top level
BVH."* It concatenates every per-mesh (BLAS) BVH's node array + prim arrays
into ONE global flat array, offsetting child pointers, and records where
each object's BLAS root lives:

```cpp
if (bvh->pack.root_index == -1)          // BLAS root is a single leaf
  pack.object_node[object_offset++] = -noffset_leaf - 1;
else
  pack.object_node[object_offset++] = noffset;   // node-array offset
```

Global parallel arrays produced:
- `pack.prim_index`  — geometry-local primitive id (or -1 for the
  instance-marker leaf), adjusted by `geom->prim_offset`.
- `pack.prim_type`   — encodes triangle/curve/point + segment.
- `pack.prim_object` — object index; for an instance leaf this is what the
  traversal reads to know which object to descend into.
- `pack.prim_visibility` — `ob->visibility_for_tracing()`.
- `pack.object_node[object]` — node address of object's BLAS root.

`pack_leaf()`: for a single-triangle object with prim_index -1 it negates
the entry to mark an **object/instance leaf** (vs primitive leaf).
`refit_nodes()`/`refit_primitives()` allow refit instead of full rebuild
when transforms/objects change (the stated reason for two-level: lower mem,
fast rebuild, at a small tree-quality cost).

## 2. Device traversal (traversal.h)  — entry `BVH_FUNCTION_FULL_NAME(BVH)`

Top of function:
```c
int traversal_stack[BVH_STACK_SIZE];
traversal_stack[0] = ENTRYPOINT_SENTINEL;
int object = OBJECT_NONE;            // (classic: int object = ~0;)
isect->t = ray->tmax;
float3 P = ray->P, dir = bvh_clamp_direction(ray->D), idir = bvh_inverse_direction(dir);
```

Node discrimination by SIGN:
- `node_addr >= 0` → inner node (push children).
- `node_addr < 0`  → leaf; fetch leaf, `prim_addr = leaf.x`.
  - `prim_addr >= 0` → primitive leaf (triangle/curve/point intersect).
  - `prim_addr < 0`  → **object/instance leaf** → push into object space.

Instance push branch (main):
```c
object = kernel_data_fetch(prim_object, -prim_addr - 1);
#if BVH_FEATURE(BVH_MOTION)
  bvh_instance_motion_push(kg, object, ray, &P, &dir, &idir);
#else
  bvh_instance_push(kg, object, ray, &P, &dir, &idir);
#endif
++stack_ptr;
traversal_stack[stack_ptr] = ENTRYPOINT_SENTINEL;   // sentinel = "pop back to world"
node_addr = kernel_data_fetch(object_node, object); // jump to BLAS root
```

Instance pop (when node_addr hits ENTRYPOINT_SENTINEL with stack non-empty):
```c
if (stack_ptr >= 0) {
  kernel_assert(object != OBJECT_NONE);
  bvh_instance_pop(ray, &P, &dir, &idir);
  object = OBJECT_NONE;
  node_addr = traversal_stack[stack_ptr];
  --stack_ptr;
}
```
One unified `traversal_stack`; the ENTRYPOINT_SENTINEL pushed at instance
entry is what triggers the pop. Only ONE level of instancing (no recursive
nesting) — `object` is a single scalar, not a stack.

## 3. Instance push/pop transforms — THE tMax / len(dir) TRICK

### Modern (main, kernel/geom/object.h) — implicit scaling, no `t` param
```c
ccl_device_inline void bvh_instance_push(KernelGlobals kg, int object,
    const Ray *ray, float3 *P, float3 *dir, float3 *idir) {
  const Transform tfm = object_fetch_transform(kg, object, OBJECT_INVERSE_TRANSFORM);
  *P   = transform_point(&tfm, ray->P);
  *dir = bvh_clamp_direction(transform_direction(&tfm, ray->D));  // NOT renormalized
  *idir = bvh_inverse_direction(*dir);
}
ccl_device_inline void bvh_instance_pop(const Ray *ray, float3 *P, float3 *dir, float3 *idir) {
  *P = ray->P; *dir = bvh_clamp_direction(ray->D); *idir = bvh_inverse_direction(*dir);
}
```
Key: `transform_direction` does **not** normalize. The object-space ray
direction has length `s = |M_inv · D|`. Because intersection routines use
this same un-normalized `dir`, the parametric `t` they compute is already in
**world units** — t measures world distance along the un-normalized object
dir, so `isect->t` (= ray->tmax world distance) stays directly comparable
across world and object space with NO extra scaling. Pop just restores the
saved world P/dir/idir. This is why modern push/pop take no `t` argument.

### Classic (kernel_bvh.h, ≤2.7x) — explicit `*t *= len` scaling
```c
// push:
Transform tfm = object_fetch_transform(kg, object, OBJECT_INVERSE_TRANSFORM);
*P = transform_point(&tfm, ray->P);
float3 dir = transform_direction(&tfm, ray->D);
float len; dir = normalize_len(dir, &len);   // HERE it normalizes...
*idir = bvh_inverse_direction(dir);
if (*t != FLT_MAX) *t *= len;                 // ...so t must be scaled into object space
// pop:
if (*t != FLT_MAX) {
  Transform tfm = object_fetch_transform(kg, object, OBJECT_TRANSFORM);
  *t *= len(transform_direction(&tfm, 1.0f/(*idir)));   // scale back to world
}
*P = ray->P; *idir = bvh_inverse_direction(ray->D);
```
Classic traversal passed t by ref: `bvh_instance_push(kg, object, ray, &P,
&idir, &isect->t, tmax);`. The two formulations are mathematically
equivalent — modern avoids the normalize+rescale by keeping dir un-normalized.

**Astroray decision point:** pick ONE convention. The modern un-normalized
approach is simpler (no len() per push/pop, no FLT_MAX guards) but requires
the triangle/AABB intersectors to consume the same un-normalized dir/idir.

### object_fetch_transform
```c
ccl_device_inline Transform object_fetch_transform(KernelGlobals kg, int object, ObjectTransform type) {
  if (type == OBJECT_INVERSE_TRANSFORM) return kernel_data_fetch(objects, object).itfm;
  return kernel_data_fetch(objects, object).tfm;
}
```
Motion variant `object_fetch_transform_motion_test` interpolates tfm at
`ray->time` and inverts when `SD_OBJECT_MOTION` set.

## 4. Transform math (util/transform.h)
- `struct Transform { float4 x, y, z; };` (4x3 affine).
- `transform_point(t, p)` — full affine (dot rows incl. translation .w).
- `transform_direction(t, a)` — rotation/scale only (ignores translation),
  does NOT normalize.
- `transform_direction_transposed(t, a)` — applies transposed 3x3; used for
  transforming NORMALS by the INVERSE transform (i.e. `N_world =
  normalize(transform_direction_transposed(&itfm, N_object))`), the standard
  inverse-transpose normal rule.
- `transform_inverse(tfm)` — adjoint/determinant, AVX2 fast path.

## Normal transform rule (for shading after hit)
Cycles transforms the geometric normal back to world with the
inverse-transpose: it applies `transform_direction_transposed(&itfm, Ng)`
(itfm = world→object, so its transpose acts as the inverse-transpose of the
object→world matrix), then normalizes. Astroray must do the same or
non-uniform-scaled instances get wrong normals.

## Pitfalls
1. Single-level instancing only: `object` is scalar, not a stack — no nested
   instances in this loop.
2. tMax convention is load-bearing: classic scales `*t`, modern keeps dir
   un-normalized; mixing them double-scales or unscales t. The intersectors
   MUST match whichever push convention you choose.
3. `ENTRYPOINT_SENTINEL` on the traversal stack is the pop trigger — must be
   pushed exactly once at instance entry.
4. object_node offset can be a negated "leaf root" (`-noffset_leaf-1`) for
   single-leaf BLAS — handle both inner-node and leaf-root object roots.
5. Normals need inverse-transpose (`transform_direction_transposed` with
   itfm), not the forward tfm, or non-uniform scale breaks shading.
6. prim_object for an instance-marker leaf is set 0 / unused; the real object
   id for descent comes from `prim_object[-prim_addr-1]`.

## References
- Aila & Laine, "Understanding the Efficiency of Ray Traversal on GPUs"
  (HPG 2009) — basis of the Cycles GPU traversal stack loop (cited in
  traversal.h NVIDIA header).
- Cycles source, Apache-2.0, files listed above.
