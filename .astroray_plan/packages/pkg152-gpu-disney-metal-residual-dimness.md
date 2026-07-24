# pkg152 — GPU Disney-metal residual dimness (stable 0.60–0.77 GPU/CPU after the pkg141 dispatch fix)

**Pillar:** 3 (GPU/CPU parity)
**Track:** A (GPU lane; RTX-gated — CI is blind to it)
**Codex-paste-ready:** no (measure-first parity investigation; the fix is chosen by instrumentation, not in advance)
**Status:** open — dispatchable AFTER PR #518 (pkg141) merges; NOT for the 2026-07-24/25 overnight run (same GPU region Lane B just changed — let the pkg141 state settle and re-anchor on merged main)
**Estimated effort:** S–M (the pkg141 instrumentation pattern is reusable; likely one or a few missing terms to mirror)
**Depends on:** pkg141/PR #518 merged (this package's baseline IS that PR's post-fix state). Related: pkg129 (Turquin reflection multiscatter LUTs) may be the fix vehicle if the missing term turns out to be the CPU-side reflection compensation — do not implement pkg129 from here; hand over if convicted.

**Origin:** pkg141 hardware verification (2026-07-25, PR #518, RTX 5070 Ti). After the closure-dispatch fix, GPU/CPU per-channel mean ratios are a stable, bit-deterministic 0.60–0.77 at near-delta (roughness ≤ 0.1), 0.86–0.94 at mid roughness, and 0.64–0.89 at roughness 0.9 — inside pkg141's deliberately wide [0.4, 2.5] acceptance band (the package closed on its contract), but structurally dim, channel-ordered R < G < B, and the opposite sign of the original 2.7–4.0× defect.

---

## Defect

GPU renders Disney metal consistently dimmer than the canonical CPU (pkg123-adjudicated) reference. The ratio is stable across seeds and channel-ordered — per memory `mc-noise-vs-deterministic`, a stable per-channel ratio that does not decrease with √SPP is a structural (matrix/units/term) divergence, NOT sampler noise.

## Leading hypotheses (measure first — pkg141's discipline)

1. **Un-mirrored CPU-side energy terms (the pkg141 Lessons hypothesis).** The pkg60/pkg118/pkg138/pkg145 energy-fix series touched `plugins/materials/disney.cpp` only; `gpu_disney_eval` (`include/astroray/gpu_materials.h`) may lack the CPU's reflection multiscatter compensation (`1 + Fms·(1−E)/E`, `disney.cpp:384` region, fed by `table_ggx_E`/`table_ggx_Eavg`) and/or the pkg145 diffuse-under-specular coupling. A missing `≥1` compensation factor on the GPU predicts GPU-dim with the deficit growing where (1−E)/E grows — check against the measured roughness/channel profile. Note pkg151/PR #519 just added GPU-side table-upload infrastructure for the glass LUTs — the same mechanism can carry `table_ggx_E`/`Eavg` to the GPU if this hypothesis convicts.
2. **Channel ordering R < G < B suggests a Fresnel/F0 spectral term difference** (conductor F0 color path diverging between `disney.cpp` and the GPU twin) — dump `F` per channel for identical `(wo, wi)`.
3. The pkg141 fix's second stacked bug (`/(4·NdotL·NdotV+0.001f)` stale divide) was removed — verify no OTHER stale denominator/epsilon remains in the newly-reachable `gpu_disney_eval` path (the function was dead weight pre-#518 and never previously audited live).

## Fix contract

1. Reuse the pkg141 instrumentation: per-event `(f, pdf, throughput)` dump CPU-vs-GPU for identical `(wo, wi)` grids at roughness {0.0, 0.1, 0.3, 0.9}; convict the term(s) before editing.
2. Mirror the convicted CPU term(s) into `gpu_materials.h` with the same citations the CPU code carries (CLAUDE.md §6); CPU stays untouched (canonical).
3. If the convicted term is the full pkg129 reflection-LUT scope, STOP and hand over to pkg129 rather than partially duplicating it.

## Gates

- GPU/CPU per-channel mean ratio within [0.90, 1.10] across the pkg123 parity grid (near-delta AND mid/high roughness rows — tighten from pkg141's [0.4, 2.5] band; propose the tightened band in the PR for architect sign-off).
- pkg141's promoted (un-xfail'd) rows stay green; furnace/energy suites green; wavefront-diff attribution per the pkg153 protocol while that package is open.
- Build evidence per CLAUDE.md; RTX verification serialized (memory `cuda_verifier_concurrency`).

## Non-goals

- The CPU implementation (canonical post-#498; do not touch `disney.cpp`).
- pkg129's LUT port itself (hand over if convicted).
- The dielectric/transmission lobes (pkg149/pkg151/pkg154 territory).

## Provenance

Filed by the architect from the PR #518 adjudication (2026-07-25) — measured ratios in the pkg141 spec's "Hardware verification 2026-07-25" section; the un-mirrored-twin hypothesis is the pkg141 implementer's own Lessons entry.
