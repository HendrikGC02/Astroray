# pkg161 — Build a firefly-bearing gate scene (the test library has no high-variance tail anywhere)

**Pillar:** 3 (light transport / integrator correctness — test infrastructure)
**Track:** A (RTX-gated; the deliverable is a scene + gate, validated by measurement)
**Codex-paste-ready:** no (the scene must be tuned against measured tail statistics, not assumed)
**Status:** done (PR #530, 2026-07-26 — `1393b13`). RTX 5070 Ti: `firefly_window` peak/p99.9 = **22.85×** (target ≥10×, 12.6× heavier than the next-worst library scene at 1.82×); `metal_cornell` negative control **1.07×** (limit ≤3.0×, confirms the gate discriminates). 12 gates green; un-skips pkg157's `test_gpu_wavefront_clamp_indirect_suppresses_fireflies_without_energy_loss` (skipped since PR #526).
**Estimated effort:** S–M (one scene + one gate; the work is measurement/tuning, not new engine code)
**Depends on:** none. Unblocks: pkg157's skipped firefly gate; pkg144 contract item 3.

---

## Origin — a measured hole, not a hypothesis

pkg157 (PR #526) ported pkg144's `clampDirect`/`clampIndirect` firefly clamp into
the GPU wavefront. Its gate for the pkg144 headline behaviour — *"clampIndirect
suppresses fireflies without meaningful energy loss"* — could not be made to pass
in **three** hardware rounds on an RTX 5070 Ti, each failing for a different
reason, and the root cause turned out to be the scene library rather than the
test or the code.

Measured tail-heaviness (`peak / p99.9` of output luminance) across the suite:

| scene | spp | peak | p99.9 | peak/p99.9 |
|---|---|---|---|---|
| diffuse_light_cornell | 16 / 64 | 1.1962 / 1.0406 | 0.6571 / 0.6791 | **1.82× / 1.53×** |
| thin_glass_cornell | 16 / 64 | 1.1745 / 1.0369 | 0.7067 / 0.6822 | **1.66× / 1.52×** |
| disney_cornell | 16 / 64 | 1.1749 / 1.0373 | 0.7067 / 0.6822 | **1.66× / 1.52×** |
| dielectric_cornell | 16 / 64 | 0.6610 / 0.4869 | 0.4730 / 0.4319 | **1.40× / 1.13×** |
| metal_cornell | 16 / 64 | 0.4705 / 0.4514 | 0.4411 / 0.4331 | **1.07× / 1.04×** |

**Not one scene has a firefly tail — not even at 16 spp.** A genuine firefly
population shows a ratio in the tens to hundreds; these are 1.04–1.82×.

The consequence is that the claim is *unfalsifiable* on current scenes: any clamp
limit high enough to touch only outliers touches **nothing** (measured: a p99.9
limit is 99.5% of peak, `max|Δ| = 4.77e-07`, below the noise floor), while any
limit low enough to bite removes **genuine signal** (measured: 0.5× peak moved
mean brightness 4.166%). The two halves of the claim are mutually exclusive here.

pkg157's gate is therefore `pytest.mark.skip`-ped with this measurement as its
reason (deliberately **not** xfail — the code is not expected to fail, and an
xfail is never acceptable evidence for a gated feature, memory
`xfail-gated-features-must-unxfail`).

## Why this matters beyond pkg157

Firefly suppression is the entire justification for the `clampIndirect` control,
and **pkg144 contract item 3 is currently undemonstrable** for the same reason.
Any future work on clamping, denoising, adaptive sampling, Russian-roulette
tuning, or variance-reduction generally has no scene on which to show an effect.
This is a standing gap in the test infrastructure, not a pkg157 artifact.

---

## Contract

1. **Add a purpose-built firefly-bearing scene** to the test/benchmark library.
   The standard construction is a **small, very bright emitter reached through a
   specular or caustic path, rendered at low spp** — a small bright sphere light
   plus a glossy/refractive caster, so that rare high-energy paths land in few
   pixels. Cite the construction (Cycles' own firefly discussions, or PBRT's
   variance/clamping treatment) per CLAUDE.md §6; do not invent a scene shape and
   assert it works.
2. **Validate by measurement, not by eye.** The scene qualifies only if
   `peak / p99.9 ≳ 10×` at the gate's spp (target the tens-to-hundreds range that
   distinguishes a real tail from the 1.0–1.8× the current suite shows). Record
   the measured ratio in the spec on completion. A scene that merely *looks*
   noisy does not qualify.
3. **Un-skip pkg157's gate**
   (`tests/test_pkg157_wavefront_firefly_clamp_port.py::test_gpu_wavefront_clamp_indirect_suppresses_fireflies_without_energy_loss`)
   and point it at the new scene. Its body is already correct and asserts both
   halves — that the clamp binds, and that it preserves energy — with the binding
   assertion first so a vacuous pass is impossible. Removing the skip marker is
   part of this package's definition of done (memory
   `xfail-gated-features-must-unxfail` applies to skips used as feature gates).
4. **Re-examine pkg144 contract item 3** against the new scene and report whether
   the original "`clampIndirect=10` → <0.02% brightness delta" headline
   reproduces. It was measured on a bright-sun scene whose dynamic range no
   current gate scene shares; the constant is very likely scene-specific and the
   contract should be restated in scene-relative terms (a tail percentile, or a
   multiple of the scene's peak) rather than an absolute number.

## Gates

- New scene's measured `peak / p99.9` recorded and ≥ the threshold in item 2.
- pkg157's firefly gate un-skipped and GREEN on RTX against the new scene.
- No regression in the existing suite (the new scene is additive).
- CPU and GPU wavefront both exercised, so the scene serves as a parity fixture
  too — fireflies are exactly where CPU/GPU transport differences show up.

## Non-goals

- Changing clamp defaults or semantics (pkg144's contract is the contract;
  pkg157 shipped the wavefront wiring).
- Denoising, adaptive sampling, or any other variance-reduction feature. This
  package builds the *measurement substrate* those would need, nothing more.
- Retuning pkg157's other gates — they pass on hardware and are unaffected.
