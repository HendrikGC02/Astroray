# pkg204 — GPU wavefront volume-pass direct/indirect split (closes pkg198 deferred limitation)

**Pillar:** Integration Milestone (GPU wavefront light-path AOV parity)
**Track:** A
**Status:** done (PR #625, 2026-08-19 — closes pkg198 Stage-2 volume-pass limitation; direct+indirect sum exactly to combined volume beauty on GPU, shade-kernel register HARD gate unchanged).
**Estimated effort:** S.
**Depends on:** **pkg198 Stage 2** (LANDED, PR #622 — the `HasLightPassAOVs`
fleet-isolation axis, the `lpAccumulate` global-scatter accumulators, and the
`PASS_VOLUME_*` slots this package fills). **pkg199 Stage 2** (LANDED, PR #619 —
`stageVolumeScatterKernel`, the HG in-scatter site whose contribution is what
gets split). Both merged; dispatchable now.

## Goal

pkg198 Stage 2 shipped the full GPU wavefront light-path render-pass mirror, but
routed **all** world-volume in-scatter into `PASS_VOLUME_INDIRECT` only — the
direct/indirect split was not mirrored (documented limitation, #622: "Volume
direct/indirect pass split not mirrored"). Cycles splits volume light-path
contributions the same way it splits surface ones: the in-scatter lit directly
by a light (the NEE/light-sampling leg at the scatter vertex) is
`PASS_VOLUME_DIRECT`; in-scatter arriving via a further bounce is
`PASS_VOLUME_INDIRECT`.

**Route the volume in-scatter contribution to `PASS_VOLUME_DIRECT` vs
`PASS_VOLUME_INDIRECT` by the same direct-vs-indirect category test already used
for the surface passes**, so a `Volume Direct` / `Volume Indirect` compositor
pass split matches Cycles.

## Specification

1. **Reuse the existing, register-proven shape — do NOT add a new template axis
   or new live registers.** The split MUST ride entirely inside the existing
   `HasLightPassAOVs` partition using the same `read-category → compute pass
   index → lpAccumulate` global-scatter shape that pkg198's probe measured at
   **zero STACK / zero register-tier change** (memory / pkg198 §"Isolation-axis
   analysis"). The `HasLightPassAOVs=false` fleet kernel MUST stay byte-identical
   (`<0,0,0,0,0>` = REG 254 / STACK 3352 / CONSTANT[0] 1700).

2. **Split site:** the volume in-scatter accumulation added by pkg199 Stage 2
   (`stageVolumeScatterKernel` / the HG in-scatter contribution that currently
   scatters into `PASS_VOLUME_INDIRECT`). Locate the exact `lpAccumulate` /
   `passAccum` call at implementation time from the merged pkg198-S2 + pkg199-S2
   diffs — do NOT assume file paths from this spec. The NEE/light-sampled
   in-scatter leg (direct light at the scatter vertex) → `PASS_VOLUME_DIRECT`;
   the in-scatter carried by the continuation ray / subsequent bounces →
   `PASS_VOLUME_INDIRECT`. Mirror the exact direct-vs-indirect predicate the
   surface passes already use (bounce depth / first-category lock), do not invent
   a new one.

3. **Sum-to-beauty must stay exact.** `PASS_VOLUME_DIRECT + PASS_VOLUME_INDIRECT`
   must equal the pre-split single-pass value bit-for-bit (the split only
   re-buckets an existing quantity; it adds nothing and drops nothing). Preserve
   pkg198's `rel_L1 0.0` sum-to-beauty invariant.

4. **CPU reference:** if the CPU wavefront/light-path classification already
   emits a combined volume pass, split it identically in the same PR so CPU↔GPU
   per-pass parity holds (memory: CPU/GPU pass work byte-mirrored, never split
   across sessions). If the CPU volume pass is genuinely absent (pkg198 Stage 1
   was CPU-classification for surfaces only — verify), state that explicitly and
   scope this package GPU-only, documenting the CPU gap as a carried follow-up
   rather than silently diverging.

## Acceptance

- [ ] **Register HARD gate:** `stageShadeBucketedKernel<0,0,0,0,0>` **and**
  `stageVolumeScatterKernel<…,false>` byte-identical to the landed pkg198-S2 /
  pkg199-S2 fleet baselines (REG 254 / STACK 3352 / CONSTANT[0] 1700 for the
  shade kernel; the pkg199-S2 volume-scatter baseline for that kernel). Verified
  via `cuobjdump --list-elf` (confirm sm_120 first) + `-res-usage` on the FINAL
  LINKED `.pyd`, mtime stated (memory `worktree-cmake-cuda-arch-stale-cache`,
  `stale_pyd_locations`).
- [ ] A fog-with-direct-light scene renders **non-zero** `PASS_VOLUME_DIRECT`
  and `PASS_VOLUME_INDIRECT`, with `DIRECT + INDIRECT == ` the pre-split single
  volume pass to `rel_L1 < 1e-5` (LINEAR EXRs, seed-pinned, sentinel-gated —
  not exit code). Record the measured per-pass means.
- [ ] Beauty byte-identical ON vs OFF (`HasLightPassAOVs` off path unchanged),
  and beauty identical before/after this change (the split does not touch
  beauty). `.pyd` mtime next to the render leg.
- [ ] CI green on all matrix jobs (`gh run view` on HEAD — memory
  `mingw_local_vs_gcc_ci_divergence`) AND the RTX hardware leg (memory
  `ci_has_no_gpu_runtime_blindspot`).

## Non-goals

- **No new AOV axis / no new template parameter** — rides the existing
  `HasLightPassAOVs` partition only.
- **No perf work** on the volume kernels (wavefront perf ceiling is an owner
  decision; do not touch it).
- **No numeric Cycles parity** on absolute volume-pass values beyond the
  sum-to-beauty invariant and the direct/indirect bucketing being correct.

## Provenance

Filed by the architect 2026-08-19 from pkg198 Stage 2's documented limitation
(#622: volume direct/indirect split not mirrored) and NEXT_STAGE_REPORT §2
item 7. Grounded in the pkg198 register probe (zero-STACK global-scatter shape,
pkg198 spec §"Measured table") and pkg199 Stage 2's `stageVolumeScatterKernel`.
Open-model implement candidate: the register-hostile part is already proven safe
by pkg198's probe; this is a re-bucketing of an existing quantity behind
build + CI + RTX gates, with Claude on the sum-to-beauty / register verification.
