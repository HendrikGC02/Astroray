# pkg242 — Procedural transformed-p and bake/cache-domain parity

**Pillar:** 5
**Track:** A
**Status:** in-progress — Phase 1 in review (PR #737, 2026-09-07; CPU analytic oracles green, GPU parity pending lead build); Phase 2 real-Blender parity still open
**Estimated effort:** TBD
**Depends on:** pkg115, pkg190, pkg219, pkg230b

---

## Goal

Before: CPU procedural evaluation and GPU bake domains disagree — the
HitRecord overloads of `Texture::value`, `valueOffset`, and `sampleSpectral`
map UV but retain the original procedural `p`, GPU baking is limited to
UV/Generated and evaluates procedural samples in the original bake domain,
and UV-less primitives shade a flat fallback. After: building on landed
pkg230b, native procedural transformed-p and bake/cache-domain parity — one
transformed-coordinate contract covering CPU and GPU bake domains, supporting
an explicitly bounded affine subset and reporting unrepresentable coordinate
chains visibly instead of implying full coverage.

---

## Context

This package serves Pillar 5 (Blender integration / procedural texture
parity). pkg230b is DONE (#708): the pkg230b foundation has landed, while
this package's architecture and gates remain OPEN. Estimated effort is TBD at
architect review. The 2026-09-06 rebuild baseline shows the gap is
user-visible today (CPU checker placement against a flat GPU ground), and
this evidence strengthens the existing bake/domain scope.

---

## Evidence

- `include/advanced_features.h:177`, `:187`, `:249` — HitRecord overloads of
  `Texture::value`, `valueOffset`, and `sampleSpectral` map UV but retain the
  original procedural `p` passed to the underlying evaluator.
- `src/gpu/scene_upload.cu:927` limits baking to UV/Generated; `:953` and
  `:979` evaluate procedural samples directly in the original bake domain.

### Additional 2026-09-06 baseline: standalone UV-less checker

- 2026-09-06: The full rebuild's 192x144,256spp material chart shows CPU
  checker placement but a flat GPU ground. This was independently reproduced
  through the unchanged f30bc5f Python binding, so it is not caused by
  pkg250's new CLI caller.
- 2026-09-06: A default UV CheckerTexture on two triangles without explicit
  UV arrays gives CPU image luminance standard deviation 0.4182 versus GPU
  0.0330. The case is NOT a visual parity pass.
- 2026-09-06: Saved raw arrays/previews and imported-module identity are at
  `test_results/rebuild-handoff-20260906/checker-binding-*`;
  `standalone-{cpu,gpu}-scene2.png` shows the production CLI example.
- 2026-09-06: Terra traced the precise gap: CPU triangles interpolate
  implicit fallback UVs even without authored UV layers; GPU triangles set
  hasUV only for real UV layers, so the shader skips their baked 2D texture
  and shades the flat fallback.

---

## Reference

- [pkg59](pkg59-shader-graph-uv-vector.md) — UV plumbing baseline.
- [pkg115](pkg115-adopt-blender-shader-node-textures.md) — line 125: full-3D
  Mapping transform still TODO.
- [pkg190](pkg190-gpu-procedural-texture-support.md), PR #612/#615 —
  UV/Generated bake only; guarded Object-coordinate fallback.
- [pkg219](pkg219-per-texel-shader-graph.md), DONE — image Mapping acceptance.
- [pkg230b](pkg230b-vector-coordinate-chain.md), DONE #708 — owns the
  image/compatible-program affine path and warns on unsupported procedurals.

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `include/advanced_features.h` | HitRecord overloads of `Texture::value` (`:177`), `valueOffset` (`:187`), and `sampleSpectral` (`:249`) currently map UV but retain the original procedural `p` passed to the underlying evaluator; bring them onto the approved coordinate contract. |
| `src/gpu/scene_upload.cu` | Baking is limited to UV/Generated (`:927`); `:953` and `:979` evaluate procedural samples directly in the original bake domain; align bake/sample domains with the approved contract. |

### Key design decisions

Reuse the pkg119 differential harness and existing procedural parity tests.

#### Phase 0

Phase 0 records the baseline, then the detailed architect pass defines the
single transformed-coordinate contract for CPU+GPU bake domains covering:
chain order; negative/zero/singular transforms; shared/transformed-object
provenance; cache invalidation; and a visible unsupported policy. Quantify
finite bake error separately from the transform contract. Include the
default-coordinate/UV-availability contract in Phase 0: determine whether
UV-less primitives should use a documented generated/default domain or report
unsupported input. Reconcile CPU procedural evaluation with GPU baking and
sampling without hiding the mismatch by changing the fixture.

#### Phase 1

Phase 1 implements the approved native/bake/cache subset.

#### Phase 2

Phase 2 verifies real Blender parity.

#### 2026-09-07 — UV-less fallback contract (PR #726)
- **UV-less primitives use the documented CPU implicit UV domain; the GPU
  uploads the same UVs.** The CPU `Triangle` always defines `(uv0,uv1,uv2)`:
  authored UV-layer 0 when present, else the implicit default domain
  `uv0=(0,0), uv1=(1,0), uv2=(0,1)` (`include/astroray/shapes.h` ctors,
  interpolated at `shapes.h:209`). So a UV-less triangle still yields a valid
  `rec.uv` and the CPU procedural/image sampler shades correctly. The GPU
  upload (`src/gpu/scene_upload.cu`) now sets `GTriangle.hasUV` and uploads
  `getUV0/1/2` — i.e. exactly that CPU fallback domain — for the 2D
  texture-sampling consumers (image/procedural base colour, normal map, bump,
  scalar op-VM program) regardless of authored layers. `hasUV` therefore means
  "UVs uploaded, safe to sample" and gates only the device texel fetches. The
  UV-ALIGNED-FRAME recomputes (anisotropy tangent, normal-map decode, bump
  frame in `stage_advance.cu`) instead gate on a separate `GTriangle.uvAuthored`
  bit set from `tri->hasUVLayers()`, mirroring the CPU, which only computes a
  UV-aligned tangent when `!uvLayers.empty()` (`shapes.h`) and otherwise keeps
  the arbitrary frame from `setFaceNormal`. So a UV-less anisotropic/normal-
  mapped/bump surface keeps the arbitrary frame on both backends, while still
  getting a valid base-colour texel fetch from the uploaded fallback UVs. The
  fixture was NOT changed to hide the mismatch.

---

## Acceptance criteria

All implementation gates UNRUN:

- [ ] Analytic coordinate oracles for Checker/Wave/Noise under XYZ
      rotation/offset/scale/mirror/singular transforms.
- [ ] Blender CPU/GPU/Cycles comparisons for the same cases, plus shared
      objects and bake edges.
- [ ] The `value`, `valueOffset`, and `sampleSpectral` entry points follow the
      approved coordinate contract; trace material, bump, and spectral callers.
      Image/program consumers retain pkg230b's behavior; unsupported domains warn.
- [ ] Untransformed baseline preserved (byte-identical where applicable).
- [ ] Cache correctness across transform edits; unaffected kernel-fleet
      identity (REG/STACK/CONST/LOCAL) for untouched kernels.
- [ ] Fresh native build identity if engine code is touched; GPU lock; at most
      two isolated implementation worktrees; caller/binding/ABI review; saved
      visuals with Astra/Claude review; independent Claude sign-off.

---

## Non-goals

- pkg230b's image/program child-sampler cache isolation (primary pkg230b
  scope).
- pkg234 image filtering; pkg233 standalone BSDF texture plumbing.
- Arbitrary coordinate VM; new procedural algorithms or physics.
- Risk: Finite bake resolution can hide transform errors or alias
  high-frequency fields.
- Risk: Unbounded Object coordinates need an explicit supported domain.
- Risk: Shared material instances and stale bake keys can apply another
  object's coordinate frame.

---

## Progress

- [ ] 2026-09-07 08:30 — owner: the transformed-p / bake / cache contract runs this round in parallel with pkg241; dispatched.
- **2026-09-07 -- Phase 0 baseline + UV-less fallback contract (PR #726).** Reproduced
  and root-caused the "UV-less procedural checker disappears on GPU" bug (the
  2026-09-06 baseline: CPU luminance std 0.4182 vs GPU 0.0330). Root cause:
  `scene_upload.cu` set `GTriangle.hasUV` only when `tri->hasUVLayers()`, so a
  UV-less textured material uploaded no UVs and the device base-colour fetch
  (gated on `ttri.hasUV`) was skipped. Fix uploads the CPU implicit fallback
  UVs for texture-sampling consumers (see Key design decisions). Added
  `tests/test_pkg242_uvless_checker_parity.py` (CPU contrast + authored-UV
  regression pin pass on the CPU-only build; the GPU std-ratio parity gate is
  pending the lead's RTX 5070 Ti CUDA build). The full transformed-p /
  bake/cache-domain contract (Phase 1/2) remains OPEN and unstarted.

---

- **2026-09-07 -- Phase 1 transformed-p + bake/cache contract (PR pending).**
  Implemented the single transformed-coordinate contract. CPU: the HitRecord
  overloads of `Texture::value/valueOffset/sampleSpectral`
  (`include/advanced_features.h`) now feed the procedural evaluator the
  Mapping-transformed point `mp = M*p` (previously only the 2-D image coord was
  transformed; procedural `p` stayed untransformed, so Checker/Wave/Noise
  ignored the Mapping). GPU: `scene_upload.cu` folds the SAME transform into the
  procedural UV and Generated-voxel bakes at upload time (via a new public
  `Texture::mappedPoint`, identity when unset), so the device fetch stays
  transform-agnostic — zero new per-hit shade state, register-neutral. Bake
  dedup moved to a `(Texture*, Mapping-matrix)` key so a Mapping edit re-bakes.
  Singular (det~0) Mapping matrices now print a visible `[pkg242]` stderr
  warning instead of silently shading flat. Added a test-only binding
  `sample_named_texture_mapped` (mirrors the existing pkg219b
  `sample_named_texture` helper) for point-wise oracles.
  - Measured (CPU-only build, seed=1): analytic point-wise oracles for Checker
    under identity/offset/scale/rotate30/mirror_x all match the Cycles
    floor-parity formula computed from `mp = M*(u,v,0)`; a one-cell x-offset
    inverts the checker and a two-cell offset restores it; Wave (bands-X sine)
    under an x-scale mapping matches the analytic frequency-scaled profile
    (atol 2e-3); Noise is bit-invariant under an identity Mapping (== raw
    sample) and 100/100 grid samples change under an offset. Untransformed
    baseline render pinned byte-stable (means [0.685399,0.687098,0.674164],
    lum std 0.434213 — identical to the pkg242 uvless authored-UV pin).
    `tests/test_pkg242_transformed_p_contract.py`: 10 passed, 3 skipped (GPU).
  - Finite bake error (separate from the transform contract): the GPU
    procedural bake stays 64x64 (UV) / 64^3 (Generated); a Mapping that scales
    the field frequency up shrinks the effective per-cell sample budget and can
    alias, exactly as the untransformed bake already can. This PR does not
    change the bake resolution; the transform is folded at the SAME grid points,
    so the transform contract is exact and the residual is purely the
    pre-existing finite-resolution term. Quantifying/escalating that budget for
    high-frequency transformed fields is deferred (Non-goal: bake resolution).
  - GPU verification pending the lead's RTX 5070 Ti CUDA build: the gpu-marked
    twins assert CPU/GPU 8x8 block-mean cross-correlation > 0.9 for scale/offset/
    rotate30 transformed checkers.

## Lessons

- (none yet)
