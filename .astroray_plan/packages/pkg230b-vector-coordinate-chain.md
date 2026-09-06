# pkg230b — Affine Vector Math / Rotate coordinate chains

**Pillar:** 5 (Blender integration / shader-node coverage)
**Track:** A
**Status:** DONE — PR #708, merge8217234b; owner-authorized Terra SIGN-OFF and PR CI passed
**Estimated effort:** M
**Depends on:** pkg219a, pkg230 Phase 2

## Problem and priority

pkg230 Phase 2 supports image → Vector Math/Rotate → color/scalar evaluation.
Its audit of base `31f3029` found that the same nodes *before* an image lookup
silently returned the default coordinates. Phase 2 adds a visible warning;
this follow-up adds support for a bounded affine subset.

The owner delegated next-package selection to Astra on 2026-09-06 after #703.
This round selects pkg230b for common Blender texture-placement fidelity, ahead
of specialized caustics/sampling extensions and the larger Principled arc.
pkg219a and pkg230 Phase 2 are landed; base `305caf5`, no open PRs at selection.
Pillar 4 remains PAUSED; no universal coordinate VM is introduced.

## Proposed scope

Fold Vector Math ADD, SUBTRACT, MULTIPLY and SCALE with one varying vector and
constant operands into the existing affine coordinate matrix. Include Vector
Rotate with constant axis/angle/center or constant Euler rotation/center.
Preserve operand order (including constant minus varying vector), rotation
inverse, Mapping composition order and UV/Generated/Object provenance.

A zero scale or mirrored transform has real semantics; do not turn it into
identity. Honor representable singular affine transforms; warn on cases the
existing consumer cannot represent. Reject/warn for operations outside the
chosen subset, multiple varying inputs, unsupported chains, depth exhaustion
and cycles. Some excluded operations are affine under special constant
operands; that does not expand this initial scope.

Trace all consumers before implementation:

- Image textures: `load_blender_image`, `_resolve_vector_input`,
  `_resolve_mapping_matrix`, `_apply_texture_transform`, `_texture_variant_key`.
- Procedural textures: `load_procedural_texture` currently applies only the
  older 2D transform, while native evaluation leaves procedural p unchanged.
  This addon-only phase warns for new unrepresentable affine chains; full 3D
  mapping and bake/cache integration belong to the separate native follow-up.
- Program textures: `_maybe_build_program_texture` takes coordinates from the
  first image input. Preserve/document differing child-image mapping limits.

Reuse the existing texture cache key's matrix representation where sufficient;
change it only if needed to distinguish actual new variants. Constant, node,
link, coordinate-source and UV-layer changes must invalidate the right entries;
include small numeric edits that the current four-decimal matrix key can alias.
Candidate implementation ownership is `blender_addon/__init__.py` plus focused
resolver/cache tests. Inspect real call paths before fixing the file list.

## Acceptance (results in delivery evidence)

The detailed architect pass must pin numerical tolerances before implementation.

- Real headless Blender coordinate-texture comparisons against Cycles in a
  common linear space, with CPU/GPU parity and saved qualitative visual proof.
- Noncommutative operation and Mapping order, zero/mirror/singular cases,
  nonzero rotation center, Euler inverse, and coordinate provenance tested.
- Image, procedural and program consumers each exercise the feature or emit
  an explicit warning; no silent default on unsupported chains.
- Distinct same-image transforms and subsequent edits preserve cache correctness.
- No GMaterial growth or new universal shader specialization. If engine code is
  needed, use fresh native builds, intended import path, GPU lock and linked
  kernel resource checks; addon-only changes still require visual review.
- Full tests, caller/binding sweep and independent sign-off (Terra authorized by
  the owner on 2026-09-06 while Claude is unavailable).

## References and limits

Use the pkg230 Phase 2 research note
`../docs/pkg230-phase2-vector-semantics-research.md`, the source package spec,
and Cycles v5.1.0 commit `adfe2921d5f3c0fe699149bcd9bc347543bbd82e`:
`intern/cycles/kernel/svm/math_util.h`, `vector_rotate.h`, `mapping_util.h`
and `intern/cycles/util/transform.h` (Apache-2.0).

No light-transport/physics changes, new UI, general per-texel coordinate VM,
or independent per-image program coordinates. The latter require their own
architecture if real usage warrants them.

Independent Claude review (2026-09-05): SIGN-OFF to file this bounded future
spec. Detailed implementation readiness and every acceptance gate remain pending.


## Implementation decision — 2026-09-06

This is an addon-only coordinate translation package. Reuse the existing 3x4
matrix binding and shared native image/program sampler. No C++/CUDA, GMaterial,
ABI, specialization, spectral transport or scientific-output changes.

### Resolver contract

- Introduce one bounded affine-chain resolver shared by the coordinate-source
  and matrix wrappers, keeping existing public helper signatures compatible.
  Return provenance (coordinate mode and UV layer) together with the matrix so
  they cannot follow different upstream operands. Preserve ordinary Mapping
  behavior and the legacy five-field wrapper used by tests/older callers.
- Support ADD, SUBTRACT, component-wise MULTIPLY and SCALE with at most one
  varying vector. Read duplicate Vector sockets by position; read only active
  operands. Preserve constant-minus-varying order. Fold unlinked constants and
  simple linked VALUE/RGB/constant Combine XYZ where straightforward; reject
  unsupported linked controls instead of reading their unused socket defaults.
- Rotate supports AXIS_ANGLE, X/Y/Z and EULER_XYZ with constant controls, a
  nonzero center and invert. Compose T(center) R T(-center) with the upstream
  affine. Euler inverse is transpose; axis inverse negates the angle; zero
  axis is identity. Normative reference remains pinned Cycles v5.1.0.
- Mapping composition is outer @ inner. An unlinked Mapping Vector uses its
  actual constant default, matching pinned Cycles `MappingNode::constant_fold`
  in `shader_nodes.cpp` and Blender `node_shader_mapping.cc` socket declaration;
  tests intending a varying source must link UV explicitly. This corrects the
  old implicit-UV approximation while retaining the five-tuple wrapper shape.
  Zero/mirror affine scales are valid.
  Preserve identity cancellation and tiny edits (do not use approximate
  identity detection that erases a meaningful transform). Handle a singular
  inverse Mapping without an uncaught exception: use pinned Cycles safe-divide
  semantics if representable, otherwise report a visible fallback. NORMAL
  mapping involves normalization; preserve and report its bounded existing
  approximation instead of claiming a general affine representation.
- Bound traversal and detect cycles by node identity along the current path.
  Unsupported operations, multiple varying sources, invalid controls, cycles,
  and depth exhaustion warn with the rejected node and fallback behavior.
  Valid outer Mapping operations may remain on the explicit fallback, matching
  the existing degradation contract; do not silently take the first operand.

### Consumers and cache identity

- Bare images receive resolved provenance and full affine matrix. Keys retain
  sufficient float precision to distinguish edits below 0.0001 and include
  mode, named UV layer and mapping. Exact identity may share the plain image.
- Image-program coordinates come from the first image input. Verify remaining
  image coordinate signatures; differing mappings must visibly degrade rather
  than silently sample the first mapping. Do not add a per-input coordinate VM.
- GPU upload deduplicates by child ImageTexture pointer but carries the parent
  ProgramTexture mapping in that descriptor (`scene_upload.cu:829-848`). Allocate
  distinct plain child samplers/cache variants for distinct parent coordinate
  signatures; child coordinates remain identity to avoid double transformation.
  This fixes same-image/different-program mapping aliasing without native edits.
- Procedural exception: native Texture::value/sampleSpectral currently transform
  UV only, passing original p to 3D procedural evaluation
  (`advanced_features.h:177-194,249-258`). Setting a matrix alone cannot implement
  the requested 3D transform. Preserve the existing procedural path and emit an
  explicit warning for new affine chains it cannot honor. Do not claim these
  consumers support full affine mapping. A separate procedural mapping/bake
  parity package will own the native change and cache/bake-domain integration.
- Missing matrix bindings must emit a visible degradation, rather than silently
  treating a full-affine transform as identity or its partial 2D projection.

### Ownership and measured gates (pin before implementation)

Implementation: `blender_addon/__init__.py`, focused
`tests/test_pkg230b_coordinate_chains.py`, and minimal updates to affected
pkg219a/pkg230 addon tests. Parent owns this spec, delivery evidence, and new
presets in the existing `benchmarks/blender_parity/scene_library.py`; extend the
existing harness instead of creating another renderer script.

1. Mathematical point probes: absolute/relative tolerance 1e-6 for transforms
   against explicit arithmetic/Blender mathutils oracles; include noncommuting
   Mapping, every rotation, nonzero center, inverse, zero/mirror and constant
   subtraction. Cache keys must distinguish a 1e-5 edit exactly.
2. Provenance, linked-operand rejection, dead sockets, cycles/depth and same-image
   variants tested. Image, program and procedural consumers either honor the
   feature or report the explicit limitation. No hidden program mapping alias.
3. Real Blender 5.1 saved comparisons: CPU-only, RTX GPU and Cycles, common
   linear float32, Closest image filtering and Extend extension, denoise/adaptive off, fixed nonzero
   seed, 256 spp. Use textured Principled/specular-zero carrier to isolate this
   feature from already-filed closure/filter gaps. Compare nonuniform patterns
   and transform placement qualitatively; per-channel interior mean ratios
   must lie within [0.95,1.05] CPU/GPU/Cycles. Transformed-vs-control image MAD
   must exceed 0.01 in representative non-identity cases. Preserve zero-scale
   and unsupported-chain cases as separate semantic probes, not this effect gate.
4. Fresh native artifacts before GPU tests, intended import path and exact
   native-source identity recorded. Reuse the canonical build and established
   build cache where source-identical; no post-commit GPU result without rebuild.
   Serialize GPU work under the project lock. No native resource-growth claim
   is needed beyond proving the native source remains unchanged.
5. Focused addon/program regressions, full local suite with isolated Blender
   user paths, differential lint and caller/binding sweep. Investigate failures
   against baseline; pkg237/238 remain documented debt, not assumed new bugs.
6. Independent Claude architecture and owner-authorized Terra final source/ABI/visual sign-off, green
   CI, autonomous merge and factual live-planning closeout.

Risks: coordinate provenance mismatch, cache aliasing, double transforms in
program children, false procedural support, rotation convention, and stale
native module selection. Current results and retained failed reference cases are
recorded in [delivery evidence](../docs/pkg230b-delivery-evidence.md).
Full tests and isolated CPU/CUDA package smokes are complete; the two baseline
failures remain unresolved. Final independent review passed; delivery completed in PR #708.
The owner explicitly approved commit/merge and Terra or DeepSeek independent
review on 2026-09-06 while Claude is unavailable. Terra approved the final
source/ABI/parity/visual evidence; the earlier architecture approval remains
separate. This round accepts documented baseline failures after adjudication,
without claiming a green full suite or relaxing rendering thresholds.

Terra final SIGN-OFF: `test_results/pkg230b/final-terra-review.txt` in the root
workspace. Independent adjudication found the two native-only failures do not
block this addon package under the owner's directive; neither failure is closed.

Independent Claude architecture SIGN-OFF (2026-09-06):
`test_results/pkg230b/architecture-claude.txt` in the root workspace.
Stale procedural-scope prose reconciled; production consumers must call the
shared resolver once and program-child salting must not duplicate bare-image keys.

The final visual fixtures keep arithmetic/mirror coordinates inside the image
domain to preserve pattern sensitivity. Out-of-domain Repeat and clamped-edge
failures remain retained, with untouched-addon equivalent-Mapping controls;
they are not counted as passing cases. See the delivery evidence.
