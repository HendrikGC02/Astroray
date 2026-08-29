# pkg223b research note — Cycles Bump node citation (verified 2026-08-29)

CLAUDE.md §6 (`cite-algorithm`): source verified by fetching the live Blender
Cycles repository, not recalled from memory.

## Source

- `github.com/blender/cycles/blob/main/src/kernel/svm/displace.h` —
  `svm_node_set_bump` (the Bump node's SVM implementation, dispatched from
  `svm.h`'s `NODE_SET_BUMP` case).
- `github.com/blender/cycles/blob/main/src/kernel/svm/bump.h` —
  `svm_node_enter_bump_eval` / `svm_node_leave_bump_eval` (the sub-shader-eval
  path used when Bump samples a linked node graph rather than a single texture).

## Verified formula (`svm_node_set_bump`, abridged to the load-bearing lines)

```c
differential3 dP;
if (node.bump_state_offset == SVM_STACK_INVALID) {
  dP = differential_from_compact(sd->Ng, sd->dP);   // true camera-ray differential
} else {
  dP.dx = stack_load_float3(stack, node.bump_state_offset + 4);
  dP.dy = stack_load_float3(stack, node.bump_state_offset + 7);
}
const float3 Rx = cross(dP.dy, normal_in);
const float3 Ry = cross(normal_in, dP.dx);
const float h_c = stack_load_float(stack, node.center_offset);
const float h_x = stack_load_float(stack, node.dx_offset);
const float h_y = stack_load_float(stack, node.dy_offset);
const float det = dot(dP.dx, Rx);
const float3 surfgrad = (h_x - h_c) * Rx + (h_y - h_c) * Ry;
float3 normal_out = safe_normalize(node.bump_filter_width * fabsf(det) * normal_in
                                    - scale * signf(det) * surfgrad);
if (is_zero(normal_out)) normal_out = normal_in;
else normal_out = normalize(strength * normal_out + (1.0f - strength) * normal_in);
// node.invert negates `scale`; node.use_object_space transforms in/out of object space.
```

`svm_node_enter_bump_eval` (the `bump_state_offset != SVM_STACK_INVALID` path)
stashes `sd->P`/`sd->dP`, resets `sd->P` to the *undisplaced* surface position
attribute, and saves that attribute's own dual-number differential
(`attr.dx`/`attr.dy`, a `dual3`) as the `dP.dx`/`dP.dy` bump will use — i.e. a
**parametric surface differential**, not the camera-ray footprint, in this path.

## What this means for Astroray

Cycles' *default* path (`bump_state_offset == SVM_STACK_INVALID`) truly needs a
propagated ray differential (Igehy 1999-style `dPdx`/`dPdy`) — infrastructure
Astroray does not have anywhere (no texture-LOD ray differentials either). The
*other* path proves the `Rx`/`Ry`/`surfgrad`/`det` formula itself only needs
**some** pair of non-parallel tangent-plane offset vectors, not specifically the
screen footprint — it is a general tangent-space-free "surface gradient" bump
technique. This technique traces to:

- Morten S. Mikkelsen, **"Bump Mapping Unparametrized Surfaces on the GPU"**
  (2010) — the same author as the Mikk-TSpace tangent convention pkg223 already
  cites for Normal Map. The cross-product/`surfgrad` construction above is this
  technique; it avoids needing an explicit tangent basis by deriving one
  on-the-fly from whatever two "offset" position vectors are available.

pkg223b's recommended approach (Option 2 in the spec) substitutes Astroray's
existing UV-aligned tangent frame (`gpu_pr_uvAlignedTangent`'s `nT`/`B`, already
built for pkg223 Normal Map and pkg178 anisotropic Principled) scaled by the
node's Distance input, in place of the true ray-differential `dP.dx`/`dP.dy`,
while keeping Cycles' exact `Rx`/`Ry`/`surfgrad`/`det`/`safe_normalize` formula
and sign convention. This reproduces correct relief direction, magnitude, and
Strength/Distance response, but will not reproduce Cycles' derivative-driven
antialiasing/minification of bump detail at grazing angles or distance — an
explicit, accepted approximation (see spec §The derivatives problem for the
full fork and the rejected-for-now ray-differential alternative).

## Open question flagged for the implementer

Whether Cycles' height-channel reduction for a colour bump-height input uses
the same Rec.709 luma weights (`0.2126/0.7152/0.0722`) already present in
Astroray's dead `heightValue()` (`plugins/materials/normal_mapped.cpp`), or a
different convention (many practical Bump setups feed a non-color/grayscale
texture where the channel weighting is moot). Not verified in this pass —
confirm before assuming the existing dead-code weights are correct Cycles
parity, not just a reasonable guess.
