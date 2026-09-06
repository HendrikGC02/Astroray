# pkg234 — Honor Blender Image Texture filtering

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** pkg230

---

## Goal

**Before:** Blender Image Texture interpolation is not honored on CPU or GPU — sampling always selects one texel — so Astroray looks blocky beside Cycles with Linear interpolation. **After:** Image Texture Closest and Linear interpolation are honored on CPU and GPU, with a visible, documented fallback for unsupported Cubic/Smart modes.

---

## Context

This package serves Pillar 5 (Blender/DCC texture fidelity): Blender Image Texture interpolation must be honored, or DCC renders diverge visibly from Cycles. It depends on pkg230 and builds on the existing image-texture upload/sampling paths; pkg230 Phase 2 supplies the discovery evidence for this follow-up.

---

## Evidence

- `include/advanced_features.h::ImageTexture::value()` clamps UVs, flips V, and selects one texel; its comment near line 320 explicitly describes the matching GPU sampler as nearest-neighbour clamp plus V-flip.
- The addon does not read `ShaderNodeTexImage.interpolation`; its unrelated `interpolation_type` read is not image-filter support.
- The project index found no open image-filter package.
- The source session's real Blender 5.1 CPU/Cycles Principled charts showed the expected vector transforms/colors, but Astroray looked blocky beside Cycles with Linear interpolation — a filtering gap, not evidence of a VM error.
- Retained source capture: feature-worktree `test_results/pkg230-p2/blender_cpu_cycles_linear_filter_gap.png`. The common-Closest rerun isolates pkg230 opcode behavior.
- 2026-09-06: Independent Claude filing review: SIGN-OFF TO FILE ONLY. Evidence: `test_results/pkg232-235/claude-filing-review.txt`.

---

## Reference

- Code: `include/advanced_features.h` — `ImageTexture::value()` and the GPU-sampler comment near line 320.
- Retained source capture: `test_results/pkg230-p2/blender_cpu_cycles_linear_filter_gap.png`
- Filing review: `test_results/pkg232-235/claude-filing-review.txt`

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

- Trace image sampling through addon upload, ordinary and program textures, CPU RGB/spectral sampling, GPU sampling, and bindings before fixing the file scope.
- Pin Blender/Cycles texel-center conventions, UV edges/extension behavior, orientation, color-space and alpha handling; define tolerances before coding.
- Carry filter mode through per-texture metadata and cache variants/invalidation.
- Preserve constant textures and existing Closest behavior; implement Linear consistently on both backends.
- Warn visibly for unsupported Cubic/Smart requests.
- Reuse canonical parity/build tooling; do not create another verification script.

---

## Acceptance criteria

All implementation gates are UNRUN.

- [ ] Real headless Blender Closest/Linear A/B against Cycles in common linear space.
- [ ] CPU/GPU parity; texel-center, boundary, UV orientation, and extension cases.
- [ ] Color/alpha and RGB/spectral sampling contract; constant-texture regressions.
- [ ] Same-image filter variants and node changes cannot reuse an incompatible cache entry.
- [ ] Cubic/Smart fallback is visible and has focused tests.
- [ ] Fresh native build/import-path/architecture checks, ABI/caller sweep, and register evidence.
- [ ] Saved representative Blender renders receive Astra/Claude qualitative review.
- [ ] Documented tests and independent Astra/Claude sign-off; CUDA work uses the GPU lock.

---

## Non-goals

This follow-up does not change owner queue priority; Pillar 4 remains PAUSED.

- Risk: texel-center or alpha mismatches can look like transport errors; pin the sampling contract before implementation.
- Keep at most two isolated implementation worktrees.
- No VM opcode/math changes.
- No transport/physics changes.
- No new UI.
- No general coordinate VM.
- No universal filtering coverage claim.
- No astrophysics work.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
