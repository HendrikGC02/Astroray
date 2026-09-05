# pkg234 — Honor Blender Image Texture filtering

**Pillar:** 5 (Blender/DCC texture fidelity)
**Track:** A
**Status:** OPEN — detailed architect review required before dispatch
**Estimated effort:** TBD at architect review
**Depends on:** Existing image-texture upload/sampling paths; pkg230 Phase 2 supplies discovery evidence

## Goal

Honor Image Texture Closest and Linear interpolation on CPU and GPU, with a
visible, documented fallback for unsupported Cubic/Smart modes. This follow-up
does not change owner queue priority; Pillar 4 remains PAUSED.

## Evidence

`include/advanced_features.h::ImageTexture::value()` clamps UVs, flips V, and
selects one texel. Its comment near line 320 explicitly describes the matching
GPU sampler as nearest-neighbour clamp plus V-flip. The addon does not read
`ShaderNodeTexImage.interpolation`; its unrelated `interpolation_type` read is
not image-filter support. The project index found no open image-filter package.
The source session's real Blender 5.1 CPU/Cycles Principled charts showed the
expected vector transforms/colors, but Astroray looked blocky beside Cycles
with Linear interpolation. This is a filtering gap, not evidence of a VM error.
Retained source capture: feature-worktree
`test_results/pkg230-p2/blender_cpu_cycles_linear_filter_gap.png`.
The common-Closest rerun isolates pkg230 opcode behavior.

## Scoped direction — architect review first

Trace image sampling through addon upload, ordinary and program textures, CPU
RGB/spectral sampling, GPU sampling, and bindings before fixing the file scope.
Pin Blender/Cycles texel-center conventions, UV edges/extension behavior,
orientation, color-space and alpha handling; define tolerances before coding.
Carry filter mode through per-texture metadata and cache variants/invalidation.
Preserve constant textures and existing Closest behavior; implement Linear
consistently on both backends. Warn visibly for unsupported Cubic/Smart requests.
Reuse canonical parity/build tooling; do not create another verification script.

## Acceptance — all implementation gates UNRUN

- [ ] Real headless Blender Closest/Linear A/B against Cycles in common linear space.
- [ ] CPU/GPU parity; texel-center, boundary, UV orientation, and extension cases.
- [ ] Color/alpha and RGB/spectral sampling contract; constant-texture regressions.
- [ ] Same-image filter variants and node changes cannot reuse an incompatible cache entry.
- [ ] Cubic/Smart fallback is visible and has focused tests.
- [ ] Fresh native build/import-path/architecture checks, ABI/caller sweep, and register evidence.
- [ ] Saved representative Blender renders receive Astra/Claude qualitative review.
- [ ] Documented tests and independent Astra/Claude sign-off; CUDA work uses the GPU lock.

## Risks and non-goals

Texel-center or alpha mismatches can look like transport errors; pin the sampling
contract before implementation. Keep at most two isolated implementation worktrees.
No VM opcode/math changes, transport/physics changes, new UI, general coordinate
VM, universal filtering coverage claim, or astrophysics work.

Independent Claude filing review: SIGN-OFF TO FILE ONLY, 2026-09-06.
Evidence: `test_results/pkg232-235/claude-filing-review.txt`.
