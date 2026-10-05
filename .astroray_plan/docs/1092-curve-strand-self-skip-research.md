# #1092 — whole-strand curve self-intersection skip: research notes

## Reference: Cycles (Apache-2.0), fetched 2026-10-06 from blender/blender `main`
- `intern/cycles/kernel/bvh/util.h`: `intersection_skip_self(self, object, prim)` =
  `self.prim == prim && self.object == object`; `_shadow` adds the light primitive.
- `intern/cycles/bvh/build.cpp` `add_reference_curves`: for each curve `j` and segment `k`,
  `packed_type = PRIMITIVE_PACK_SEGMENT(primitive_type, k)` and
  `BVHReference(bounds, j, object_index, packed_type)`: the BVH `prim_index` is the CURVE
  index; the segment lives in the primitive type.
- `kernel/bvh/shadow_all.h` / traversal: `prim = prim_index[prim_addr]`; `intersection_skip_self*`
  runs before the primitive-type switch, so thick curves are covered.
- `kernel/device/cpu/bvh.h` (Embree filter): for hair (`geomID & 1`) the Embree primitive is a
  segment, mapped back with `prim = kernel_data_fetch(curve_segments, prim).prim` (the curve index)
  before `intersection_skip_self_shadow`.
Net: a ray leaving any segment of a curve never re-hits any segment of that curve, closest-hit
and shadow, native BVH and Embree. Different curves (strands) are not skipped.

## Astroray port
- Strand id = process-unique int from `CurveStrip::buildCurveSegments` (one per strand, equal
  on all its segments); `Hittable::curveStrandId()` (virtual, -1 default) / `CurveSegment::setStrandId`.
- CPU: `CurveSegment::hit` returns false when `r.self == this` (segment, strand id -1 fallback) or
  `r.self->curveStrandId() == strandId_ >= 0`. `Ray::self` plumbing from #1037 is unchanged.
- GPU: `GCurveSegment::strandId` (uploaded from the CPU segment); `gpu_curve_skip_self`
  (gpu_bvh.h) replaces the `primId != skipPrim` test in `gpu_bvh_hit` / `gpu_bvh_occluded` curve
  leaves: exact-segment test first, else compare `curves[prims[skipPrim].index].strandId`
  (only when `skipPrim` is a curve). Evaluated on curve leaf candidates only, inside the
  `if constexpr (HasCurves)` branch; no new traversal-loop live state.
- Segments without a strand id (registry `curve_segment` shape) keep the exact-segment skip.

## Measured (CPU, MinGW, ortho 64x64, 512 spp, Cycles 5.2 CPU THICK, Chiang hair)
Bent single strand, image-sum / Cycles (R,G,B): sun in the V plane 0.33 -> 1.00; front-lit
1.19 -> 1.01; hairpin 1.37 -> 1.00; behind-lit (TT) 1.00 -> 1.00. Corpus v2 hair_tuft (5 seeds)
luminance 0.9705 -> 0.9762 (camera), 0.9638 -> 0.9773 (@ortho). Evidence:
`astra_run/batch-i/i12/`.
