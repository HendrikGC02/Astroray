# pkg230b — Affine Vector Math / Rotate coordinate chains

**Pillar:** 5 (Blender integration / shader-node coverage)
**Track:** A
**Status:** IN PROGRESS — implemented locally; independent final review pending
**Estimated effort:** M
**Depends on:** pkg219a, pkg230 Phase 2

## Problem and priority

pkg230 Phase 2 supports image → Vector Math/Rotate → color/scalar evaluation.
Its audit of base `31f3029` found that the same nodes *before* an image lookup
silently returned the default coordinates. Phase 2 adds a visible warning;
this follow-up adds support for a bounded affine subset.

This package does not outrank the owner's post-pkg230 choice in STATUS,
NEXT_STAGE_REPORT and ROADMAP. It neither unpauses Pillar 4 nor introduces a
universal coordinate VM. Confirm current source-package status before dispatch.

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
- Procedural textures: `load_procedural_texture` uses the same coordinate
  resolver but currently applies only the older 2D transform. A full-affine
  implementation must wire both its transform application and cache key.
- Program textures: `_maybe_build_program_texture` takes coordinates from the
  first image input. Preserve/document differing child-image mapping limits.

Reuse the existing texture cache key's matrix representation where sufficient;
change it only if needed to distinguish actual new variants. Constant, node,
link, coordinate-source and UV-layer changes must invalidate the right entries;
include small numeric edits that the current four-decimal matrix key can alias.
Candidate implementation ownership is `blender_addon/__init__.py` plus focused
resolver/cache tests. Inspect real call paths before fixing the file list.

## Acceptance (all UNRUN)

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
- Full tests, caller/binding sweep and independent Claude sign-off.

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
spec. At filing, detailed implementation readiness and every acceptance gate
were pending; the current delivery state below supersedes that factual status.

## Current delivery state — 2026-09-06

Architecture SIGN-OFF received; implementation and local verification completed
in `codex/pkg230b`, worktree `.claude/worktrees/pkg230b`. Source remains
uncommitted/unpushed pending required independent final review. Full split tests:
2370 passed, two reproduced native baseline failures (pkg237/pkg238); NOT green.
All 21 CPU/GPU/Cycles comparison legs and isolated CPU/CUDA package smokes passed
Astra inspection. Claude's weekly subscription limit blocks final source/ABI/
parity/visual review; reported reset 2026-09-10 13:00 Australia/Sydney.
Do not redispatch. The detailed implementation specification and full evidence
are retained in that worktree; factual handoff:
[round delivery status](../docs/round-20260906-delivery-status.md).
