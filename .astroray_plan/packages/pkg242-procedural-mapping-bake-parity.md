# pkg242 — Procedural transformed-p and bake/cache-domain parity

**Pillar:** 5 (Blender integration / procedural texture parity)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** pkg115, pkg190, pkg219, pkg230b (DONE #708); the pkg230b
foundation has landed, while this package's architecture and gates remain OPEN

## Existing coverage and boundary

- [pkg59](pkg59-shader-graph-uv-vector.md) — UV plumbing baseline.
- [pkg115](pkg115-adopt-blender-shader-node-textures.md) — line 125: full-3D Mapping
  transform still TODO.
- [pkg190](pkg190-gpu-procedural-texture-support.md), PR #612/#615 — UV/Generated bake
  only; guarded Object-coordinate fallback.
- [pkg219](pkg219-per-texel-shader-graph.md), DONE — image Mapping acceptance.
- [pkg230b](pkg230b-vector-coordinate-chain.md), DONE #708 — owns the image/compatible-program affine
  path and warns on unsupported procedurals.

## Evidence

- `include/advanced_features.h:177`, `:187`, `:249` — HitRecord overloads of
  `Texture::value`, `valueOffset`, and `sampleSpectral` map UV but retain the
  original procedural `p` passed to the underlying evaluator.
- `src/gpu/scene_upload.cu:927` limits baking to UV/Generated; `:953` and
  `:979` evaluate procedural samples directly in the original bake domain.

### Additional 2026-09-06 baseline: standalone UV-less checker

The full rebuild's 192x144,256spp material chart shows CPU checker placement but
a flat GPU ground. This was independently reproduced through the unchanged
f30bc5f Python binding, so it is not caused by pkg250's new CLI caller. A default
UV CheckerTexture on two triangles without explicit UV arrays gives CPU image
luminance standard deviation 0.4182 versus GPU 0.0330. The case is NOT a visual
parity pass. Saved raw arrays/previews and imported-module identity are at
`test_results/rebuild-handoff-20260906/checker-binding-*`;
`standalone-{cpu,gpu}-scene2.png` shows the production CLI example.

Terra traced the precise gap: CPU triangles interpolate implicit fallback UVs
even without authored UV layers; GPU triangles set hasUV only for real UV layers,
so the shader skips their baked 2D texture and shades the flat fallback.
Include the default-coordinate/UV-availability contract in Phase 0: determine
whether UV-less primitives should use a documented generated/default domain or
report unsupported input. Reconcile CPU procedural evaluation with GPU baking
and sampling without hiding the mismatch by changing the fixture. This evidence
strengthens the existing bake/domain scope; implementation gates remain UNRUN.

## Goal

Building on landed pkg230b, deliver native procedural transformed-p and
bake/cache-domain parity: one transformed-coordinate contract covering CPU and
GPU bake domains. Support an explicitly bounded affine subset; report
unrepresentable coordinate chains visibly instead of implying full coverage.

## Scoped direction

Phase 0 records the baseline, then the detailed architect pass defines the single
transformed-coordinate contract for CPU+GPU bake domains covering: chain
order; negative/zero/singular transforms; shared/transformed-object
provenance; cache invalidation; and a visible unsupported policy. Quantify
finite bake error separately from the transform contract. Phase 1 implements
the approved native/bake/cache subset; Phase 2 verifies real Blender parity.
Reuse the pkg119 differential harness and existing procedural parity tests.

## Acceptance — all implementation gates UNRUN

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

## Non-goals / exclusions

- pkg230b's image/program child-sampler cache isolation (primary pkg230b
  scope).
- pkg234 image filtering; pkg233 standalone BSDF texture plumbing.
- Arbitrary coordinate VM; new procedural algorithms or physics.

## Risks

Finite bake resolution can hide transform errors or alias high-frequency fields;
unbounded Object coordinates need an explicit supported domain. Shared material
instances and stale bake keys can apply another object's coordinate frame.

## Key design decisions

- **UV-less primitives use the documented CPU implicit UV domain; the GPU
  uploads the same UVs.** The CPU `Triangle` always defines `(uv0,uv1,uv2)`:
  authored UV-layer 0 when present, else the implicit default domain
  `uv0=(0,0), uv1=(1,0), uv2=(0,1)` (`include/astroray/shapes.h` ctors,
  interpolated at `shapes.h:209`). So a UV-less triangle still yields a valid
  `rec.uv` and the CPU procedural/image sampler shades correctly. The GPU
  upload (`src/gpu/scene_upload.cu`) now sets `GTriangle.hasUV` and uploads
  `getUV0/1/2` — i.e. exactly that CPU fallback domain — for the 2D
  texture-sampling consumers (image/procedural base colour, normal map, bump,
  scalar op-VM program) regardless of authored layers. The
  anisotropic-Principled UV-tangent path stays gated on real authored layers
  (`tri->hasUVLayers()`) to mirror the CPU, which only computes a UV-aligned
  tangent when `!uvLayers.empty()` (`shapes.h`); a UV-less anisotropic surface
  keeps the arbitrary fallback frame on both backends. The fixture was NOT
  changed to hide the mismatch.

## Progress

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
