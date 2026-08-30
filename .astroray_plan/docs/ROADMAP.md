# Astroray Master Roadmap

**One document to navigate the whole plan.** Every other document exists
because this roadmap points at it. New to the project? Read this first.

---

## Vision in one paragraph

Astroray is a C++/CUDA path tracer with a Blender 5.1 addon, aiming to be
the best open-source engine for physically-accurate astrophysical
visualization while remaining competitive as a general-purpose PBR
renderer. The design goal is **pluggability** — new materials, shapes,
light transport techniques, and astrophysical phenomena should be
drop-in plugins that register into a small set of factory registries,
not patches to core files. A veteran engineer looking at the codebase
should think "this is the obvious way to do it," not "this is clever."

**Performance goal:** rival Cycles in simple enough cases on a single
RTX 5070 Ti (CUDA). **Fidelity goal:** surpass Cycles on spectral and
astrophysical scenes. **Simplicity tax:** every abstraction pays for
itself with a concrete caller today.

---

## Current sequencing (OWNER DIRECTIVE 2026-08-03 — supersedes older "next pickup" lists below)

After the 2026-08-01/02 correctness cascade (11 PRs), the owner issued a
course correction. The order is now:

**(a) Engine settlement — one SUPERVISED round.** ~~**PR #541 option
A**~~ **shipped 2026-08-06 (`bbf2d8c`)** — correctness v4 landed with the
temporary ceiling raise. ~~**pkg172 effect (A)**~~ **CLOSED** (PRs
#551/#553/#576, 2026-08-07 → 2026-08-10 — pbrt-v4 guarded-pdf form, the
universal 0.628%/bounce `f/(pdf+1e-3)` energy loss removed CPU+GPU across
all legs, coordinated clearcoat re-pin). **pkg174** register-pressure
recovery closed as owner-accepted ceiling (PR #554, 2026-08-08 — the
structural stage-split does not recover ≤1.0s on the current toolchain;
temporary raise stays; see the spec for the measured levers). **Phase (a)
COMPLETE.**

**Round closeout (2026-08-06→07, workflow restructure):** #541 merged
(`bbf2d8c`); local builds NMake→Ninja + native sm_120 + CUDA 12.8 (cold
320.7→61.1s, `50b1d93`); sccache shared across worktrees (`0ddfa49`); CI
docs-skip (~17min→11s on docs-only pushes) + concurrency-cancel + caches;
pytest CPU/GPU split + xdist (#545, `c2e7bc3`); opencode delegation layer
(`78b451b`) — open-model grunt/implement/verify tiers behind an
evidence-contract wrapper, Claude retained on all last-line-of-defense
seats. Full report: `.astroray_plan/docs/reports/2026-08-06-restructure.html`.

**(b) The Integration Milestone — BEFORE Pillar 4.** *"The purpose of
mimicking Cycles was to be able to use as much of the existing options and
settings in Blender as the steering wheel for this engine."* All four
originally-scoped milestone packages are now DONE, and the milestone grew
one owner-requested extension along the way:

- **pkg175** — DONE (PR #547, 2026-08-07): one-command dev loop
  (build → package → install → launch → headless smoke-render); 150s full
  rebuild / 5.8s `-SkipBuild`.
- **pkg176** — DONE, Stages 0–4 (PRs #555/#556/#561/#568, 2026-08-08 →
  2026-08-09): Blender's NATIVE render settings + Cycles-style panels +
  native world/light/camera properties are the steering wheel; the custom
  ground-up UI is retired down to one Astroray-only panel.
- **pkg177** — DONE (PR #546, ratified 2026-08-07): Route 1 (native
  `RenderEngine` plugin) + Route 2 (session-boundary discipline) adopted;
  Route 3 (Hydra) deferred. Research: `dcc-integration-research-2026-08.md`.
- **pkg119 Phases B/C** — DONE (PRs #550, #564): differential harness vs
  Cycles + graceful-degradation policy (never silently wrong).
- **pkg178 (owner-requested extension, filed 2026-08-08)** — DONE, Stages
  0–5 (PRs #566–#581, 2026-08-07 → 2026-08-10): a faithful native
  `"principled"` material plugin (Cycles main / Blender 5.2-era) — the
  Disney↔Principled structural mismatch the milestone's parity numbers
  kept running into. Full closure stack incl. coat/sheen/anisotropy/
  approx-SSS/emission/alpha/**thin film + thin wall** (Belcour-Barla),
  CPU+GPU, driven from the Blender addon Stage 5 socket routing.
  **pkg181** (dedicated-light BSDF visibility, PR #569) and **pkg182**
  (`ggxReflect` eval-D/pdf-D consistency, PR #582) are correctness
  prerequisites/side-findings this extension surfaced and closed along
  the way. **pkg179** (dielectric dead-sample "3× rate") was CLOSED by
  diagnosis — mislabel, no fix needed.

**Integration Milestone phase (b) is COMPLETE on its originally-scoped
package set.** Open, not blocking: thin-film-vs-Cycles saturation parity
verification + one coordinated pkg119-B/pkg129 harness band re-pin
(reflecting pkg181 + Smith-G + pkg172(A) + thin-film + pkg182 together).

**(c) Pillar 4 unpause** (pkg45/46/48/49/50/51 + pkg107) and the GR/astro
science layer, driven from inside Blender via the steering wheel the
milestone built, is next in sequence per the 2026-08-03 directive — **still
PAUSED pending an explicit owner go-ahead** (no unpause directive has been
issued; do not unpause unilaterally).

**Owner assessment (2026-08-29):** the originally-scoped Integration
Milestone package set (b) is COMPLETE, but the owner judges the Pillar 4
gate NOT MET — Blender integration is "still a ways off" in practice.
Specifically: socket coverage is 117 SUPPORTED / 22 APPROXIMATED / 385
DROPPED-SILENT of 524 (pkg219 per-texel shader eval, now DONE, is expected
to cascade into resolving many of the DROPPED-SILENT shader-node sockets —
re-audit the coverage numbers next pass); hair/curve rendering is entirely
absent (pkg225 spec filed, pkg225-S1 has an unbuilt/unverified WIP branch);
viewport UI fps is coupled to render fps rather than uncoupled as in Cycles
(a UX gap to investigate — Cycles uncouples viewport interaction fps from
render progressive-refinement fps). **All features being built should be
"future-aware"** — designed with awareness of what Pillar 4 and the
astrophysical pipeline will need from them (volumes for nebulae, curves for
filaments, spectral for emission lines).

**Current active queue (2026-08-31):** pkg131 (zero-knob adaptive sampling) is
now **FULLY DONE, both backends** (#659 CPU + #665 GPU) — sample-count AOV +
addon UI knob removal remain as a deferred follow-up, not a blocker. pkg219
(per-texel shader-graph eval, structural socket-coverage unlock) is also
DONE (#640/#641/#642 + #647/#655; a tracker revert bug reverted its Status
flip mid-round, restored 2026-08-31). Next up: **pkg225-S1** (hair
ray-curve intersection — a WIP branch exists, unbuilt/unverified, "no
half-assing hair" per owner directive), then pkg210/pkg180/pkg211 (spectral-
transport cluster) and pkg219d (scalar param-textures, the one residual
pkg219's completion audit surfaced). The exact dispatch order is an
architect decision per round.

**Explicitly de-prioritized (owner-endorsed):** the sub-percent GPU/CPU
parity tail — **pkg172 effect (B) / pkg173** (bounce-1 geometry-sampling
expectations) and the **pkg153** remainder — sits BELOW the Integration
Milestone unless the paper turns out to require bit-level parity.

---

## The agent tracks

Work happens on independent tracks. Each has its own agent and acceptance
criteria. Progress on one track rarely blocks another — that is by design, so
your single-developer throughput multiplies without coordination overhead.

| Track | Owner agent | Runs on | Purpose |
|---|---|---|---|
| **A. Core quality** | Claude Code (local) | Your RTX 5070 Ti | Correctness, foundational refactors — all package specs route here |
| **B. Feature breadth** | Retired 2026-04 era (was Copilot cloud) | — | Legacy `Track: B` specs route to Claude Code (`package-implementer`) |
| **C. Experiments** | Retired 2026-04 era (was Cline) | — | Same routing |
| **D. Grind work** | Open-weight models via the `delegate` skill (opencode) | Your machine | Bounded mechanical work; evidence-verified by Claude (CLAUDE.md §5) |
| **E. Coordination/review** | Retired 2026-07 (was Codex) | — | Legacy `Track: E` specs route to Claude Code (`package-implementer`) |

Coordination is done by the Claude Code `architect` and
`roadmap-orchestrator` agents (`.claude/agents/`), not by a separate
overseer. Retired-track handbooks are archived in
`docs/archive/agents-multitrack-2026-04/`.

**Simplicity principle per track:**
- Track A handles anything that *has* to be right.
- Track B handles anything that *matches a pattern* that is already right.
- Track C explores things that *might* be right.
- Track D mechanically converts known-right work into more of it.
- Track E keeps the other tracks aligned and turns context into actionable
  issues, reports, and PRs.

---

## Five pillars, in priority order

### Pillar 1 — Plugin architecture [FOUNDATIONAL, DO FIRST]

Convert materials, shapes, lights, textures, integrators, and passes into
plugins registered via `Registry<T>` templates. Everything below assumes
this is in place.

- Design: [`plugin-architecture.md`](plugin-architecture.md)
- Duration: 2–3 weeks of track A sessions
- **Blocks everything else.**

### Pillar 2 — Spectral core

Upgrade from hero-wavelength-at-GR-only to a fully spectral pipeline:
`SampledSpectrum`/`SampledWavelengths`, Jakob-Hanika RGB→spectrum
upsampling, spectral BSDFs and env maps. RGB backward-compat via
upsampling.

- Design: [`spectral-core.md`](spectral-core.md)
- Duration: 3–4 weeks
- Depends on Pillar 1.

### Pillar 3 — Light transport upgrades

ReSTIR DI as drop-in for NEE+MIS direct lighting; Neural Radiance Caching
via tiny-cuda-nn for indirect. Both as plugin integrators; classic path
tracer remains the fallback. When accelerated transport is available and
performance-positive, renderer defaults should pick it automatically and fall
back without user intervention.

- Design: [`light-transport.md`](light-transport.md)
- Duration: 4–6 weeks
- Depends on Pillars 1, 2.

### Pillar 4 — Astrophysics platform

> **PAUSED (2026-06-08, owner) — unpause is sequenced AFTER the Integration
> Milestone** (see "Current sequencing" at the top): the science layer gets
> built and exercised from inside Blender via the steering wheel.
> **Owner assessment (2026-08-29):** despite the Integration Milestone's
> original package set being COMPLETE, the owner judges the Pillar 4
> gate NOT MET — Blender integration has gaps (shader-node socket coverage,
> zero hair/curve support, viewport fps coupling). The specs from the
> Pillar 4 era are outdated and will receive a full audit pass when the
> owner is ready to unfreeze. Do not unpause unilaterally.

> **Thaw notice (2026-05-10) + shipping (2026-05-11+):** the strategic
> gate released, and Pillar 4 is actively shipping. pkg40 (Kerr
> metric) + **pkg41 (Kerr validation, PR #236)** + **pkg42 (synchrotron
> emission, PR #245 — VolumetricEmission interface, Pandya 2016 fits,
> bipolar jet plugin, 9 tests)** + **pkg43 (slim disk accretion model,
> PR #271 — Abramowicz 1988 / Sadowski 2009, 14/14 tests, T(9M,mdot=1) =
> 7.45e6 K)** + **pkg44 (ADAF accretion model, PR #310 — Narayan & Yi
> 1995 self-similar solution, 19 tests, Sgr A* profiles within tolerance)**
> + **pkg47 (FITS data loader, PR #292 — FITS I/O wrapper + FITSTexture
> plugin, gated `ASTRORAY_ENABLE_FITS` default OFF; FITSVolume deferred to
> pkg48)** all done. **Pillar 4 now ~50% complete.** pkg45–pkg51 specs
> queued.

Kerr metric, synchrotron emission, HII recombination lines, simulation
data import (FITS, HDF5, yt), telescope PSF. Each phenomenon is a
plugin. This is Astroray's unique niche.

- Design: [`astrophysics.md`](astrophysics.md)
- Duration: 6–10 weeks, parallel with other pillars
- Depends on Pillars 1, 2.

### Backend parity bridge — before Pillar 4 acceleration

The plugin and spectral systems are in place, but the CPU/GPU material
boundary still needs an explicit contract. Before leaning harder on
GPU-default rendering and before Pillar 4 adds more spectral phenomena,
material plugins should declare backend capabilities and either lower
to a shared CPU/GPU closure representation or clearly fall back to CPU.

**Status as of 2026-05-11 (Round 6 close, planned scope):** the
pkg34–pkg37 backend bridge is complete. The Cycles-parity / Blender
integration / denoiser push is **feature-complete on planned scope**
for Pillar 5; the user-facing competitive-parity claim (viewport
pan/zoom rivalling Cycles) is **not yet met** — pkg81's measurement
showed CUDA running *slower* than CPU on a 100k-tri viewport scene
(104 ms vs 58 ms), routed to **pkg55 Phase B** as the long-tail
fix:

- **Cycles parity wave done:** pkg52/53/57/58/59/60/61/62/63/65/66.
- **GPU multi-wavelength parity done end-to-end:** pkg54/54a/54b/54c/54d
  (all hardware-verified on RTX 5070 Ti; visible-band SSIM 0.999263 at
  spp=8192).
- **Denoiser story closed end-to-end:** pkg33 (OIDN integration), pkg68
  (OIDN persistent device + CUDA backend, **2.77× viewport speedup**
  post-pkg75), pkg69 (compositor Albedo pass), pkg70 (OptiX,
  **1.86× faster than OIDN-CUDA, SSIM 0.9987 vs OIDN**), pkg72
  (motion vector AOV), pkg75 (AOV normal-guide defect fixed), and
  **pkg73 OptiX TEMPORAL_AOV** (PR #249, 2026-05-11 — **53.1%
  inter-frame variance reduction vs ≥30% gate** on RTX 5070 Ti / OptiX
  9.1 / CUDA 12.8). Two compounding root causes for pkg73:
  `OptixDenoiserParams::temporalModeUsePreviousLayers` was zero-init
  in the plugin, AND the test's AOV reference was silently upgraded
  to TEMPORAL_AOV by sub-pixel float dust in `projectToPrevPixel`.
  Both fixed.
- **Caustics flagship done:** pkg64 Phases 1+2+3 — SMS now folded
  into the default `path_tracer` via per-bounce hook gated by
  `use_refractive_caustics` AND per-object `is_caustic_caster`.
  RTX-verified: **+8.83 dB PSNR delta, 1.18× receiver-energy ratio,
  +0.26 dB PSNR floor, 2.0% empty-hook overhead** — all gates met.
- **Cycles parity benchmark:** pkg71 framework + first canonical
  Cornell baseline shipped — **Astroray-CPU SSIM 0.9536 vs
  Cycles-CPU EXR; Astroray-GPU SSIM 0.9548 and 5.2× faster than
  Cycles-CUDA on Cornell**. **pkg76 .blend importer done** (PR #240,
  SDNA-walking Python reader, no `bpy` runtime); CSV row population
  on Classroom/Junkshop/BMW27 is a Round 6 RTX session.
- **Showcase framework done:** pkg74 Phases 1+2+3 (material zoo +
  full stat coverage + interactive PBRT-style HTML + weekly self-
  hosted CI).
- **Viewport sync done:** pkg52 + pkg56 Phases A+B+C — depsgraph-
  driven dispatch with idle frame ≤5 ms p99 on a 99k-tri scene.
  This was the **gate-releasing package**.
- **Wavefront SoA scaffold:** **pkg55 Phase A.0** (PR #238) —
  `ASTRORAY_PROFILE=1`-gated CUDA events + NVTX, baseline.json with
  **158 regs/thread + 1 active block/SM** measured as the Laine 2013
  occupancy cliff. **pkg55 Phase A.1** (PR #250, 2026-05-11) — SoA
  path-state struct + intersect queue gated behind
  `-DASTRORAY_WAVEFRONT_INTERSECT=ON` (default OFF), bit-identical
  AoS megakernel output verified. **pkg55 Phase B** (per-material
  shade kernels, ~4–6 weeks) is the next major delivery; it formally
  owns the viewport-parity acceptance gate documented by pkg81.
- **Blender daily workflow unblocked:** **pkg80** (PR #246) resolves
  `'auto'` integrator dropdown to a registered plugin before C++
  calls; the GPU-mode crash is gone.
- **Viewport-parity measurement complete:** **pkg81 Phase 1+2** (PR
  #248, 2026-05-11) — harness + 16-config Cycles A/B sweep + pkg81-
  diagnosis.md committed. Headline: **CUDA 104 ms vs CPU 58 ms** on
  identical 100k-tri load on RTX 5070 Ti. H4 (megakernel register
  pressure — pkg55-A.0's documented cliff) dominates. Phase 3 routes
  to pkg55 Phase B per the spec's escape clause; smaller H2/H5
  follow-ups split out as **pkg83** + **pkg84**.

**Round closeout (2026-08-30 → 2026-08-31): 12 PRs (#658/#659/#660/#661/#662/
#663/#664/#665/#666/#667/#668 + 1 direct-to-main docs commit) — pkg131
(zero-knob adaptive sampling) is now FULLY DONE both backends (#659 CPU +
#665 GPU, HW-verified); the pkg208/pkg209/pkg218 spectral/dispersion cluster
closes out (chromatic dispersion oracle, Cauchy/MNEE citation refresh, GPU
spectral emission device upload — the GPU lamp-colour-is-RGB-approximated
gap); pkg212 fixes a real GPU-vs-CPU wavefront pixel-center offset
(RTX-verified); pkg219's DONE flip, accidentally reverted by an in-flight
PR mid-round, is restored; pkg219d (scalar param-textures) filed open as
the one residual pkg219's completion audit surfaced. Full detail:
`STATUS.md`.**

**Round closeout (2026-08-29): 7 PRs (#648–#656) — pkg201-S3 items A+E
ship per-type bounce limits and native caustic toggles on BOTH backends,
pkg223b ships Bump node CPU+GPU parity, pkg224 progressive-sampler spec
filed (unblocking pkg131), and pkg225 hair-rendering spec filed.**
**pkg201-S3 item A DONE** (PR #651) — Cycles per-type bounce limits
(diffuse/glossy/transmission) honoured BOTH backends; runtime SoA compare
(owner option B). REG 254 unchanged, STACK +8, CONSTANT[0] +8 (perf-
neutral). **pkg201-S3 item E DONE** (PR #654) — native caustic toggles
(`caustics_reflective`/`caustics_refractive`) honoured BOTH backends via
sticky `hadDiffuseAncestor` flag + delta-caustic cull. Default ON →
byte-identical fleet. **pkg223b Bump node DONE** (PR #655) — Cycles
`svm_node_set_bump` surface-gradient (Mikkelsen 2010) on UV-aligned frame,
sharing `HasNormalPerturb` axis; fixed the UV-upload gate blind spot
(bump-only triangles shipped `hasUV=0`, GPU bump silently skipped). Fleet
`<0,...>` byte-identical. **pkg201-S3 item C PARKED** — filter_glossy needs
per-material floored-roughness refactor at ~4 inline alpha sites × 5
materials × 2 backends; disproportionate to one honour row. **Docs/infra:**
pkg126–137 audit (PR #648), tracker hygiene (PR #649), cite-algorithm
research notes (PRs #650/#652/#653), **pkg224 progressive-sampler spec**
(PR #656, owner-confirmed forks: hash-Owen Sobol' / opt-in `__constant__`
flag / GPU-only first), **pkg225 hair-rendering spec** filed (6-stage,
Pillar 3). Fleet register baseline: REG 254 / STACK 3368 / CONSTANT[0]
1716. Pillar 4 stays PAUSED. Full detail: `.astroray_plan/docs/STATUS.md`.

**In progress (2026-08-19 → 2026-08-21): 6 PRs merged (#624–#628), 1 open/HW-FAIL (#629) — pkg200's last filter honour row and the pkg198 volume-pass split both close, a test-hygiene chip lands, the light-intensity slider is exposed, and the sodium-vapor fix regressed mercury via peak-normalisation coupling.**
**pkg203 DONE** (PR #624, 2026-08-19) — Cycles-accurate pixel-filter width→σ
mapping, CPU+GPU byte-mirrored (cited Cycles `film.cpp` + PBRT-v4 §8.8);
closes pkg200's last filter-related HONEST-FAIL row. **pkg204 DONE** (PR
#625, 2026-08-19) — GPU wavefront volume-pass direct/indirect split,
closing the pkg198 Stage-2 documented limitation (first-interaction NEE bit,
sum-to-beauty exact). **pkg205 DONE** (PR #626, 2026-08-19) —
UnicodeEncodeError console-test hygiene, 3 tests ASCII-ized, test-only.
**pkg213 DONE** (PR #628, 2026-08-21) — light intensity (Power) exposed in
the Astroray light panel, UI-surfacing only (engine already consumed
`light.energy`); render-brighter gate ≥1.5×. **pkg214 OPEN, HW FAIL** (PR
#629, 2026-08-21) — sodium D-doublet broadening fix (black→amber) regressed
`mercury_vapor` ~4.5–8.6× via the shared peak-normalisation mechanism; a
physics-correct energy-normalisation fix is in progress on branch
`pkg214fix`, do not merge #629 as-is. **pkg206 released from its bias-hold**
(owner, 2026-08-21) and re-dispatched fresh (branch `pkg206impl*`) after PR
#627 was closed CI-red/biased — see the spec's 2026-08-21 triage note.
Pillar 4 stays PAUSED, unchanged. Full detail: `.astroray_plan/docs/STATUS.md`
top entry "2026-08-19 → 2026-08-21".

**Round closeout (2026-08-14 → 2026-08-15): 9 PRs (#615–#623), no open PRs at closeout — the GPU wavefront gains real god-rays (full HG scattering, both backends) and a full light-path AOV render-pass mirror, a legacy `.blend`-importer sun fix, and 3 more addon settings-honour rows flip PASS.**
**pkg190 follow-up DONE** (PR #615) — narrowed the GPU procedural bake to
Generated coord-mode only; Object-coord procedurals now degrade to a
guarded flat-albedo fallback instead of silently misrendering. **pkg200
DONE** (PR #616) — native-settings F12 pixel-honour matrix: 8 PASS / 13
HONEST-FAIL / 2 NEEDS-VISUAL / 2 LIMITATION, surfacing findings A–F (GPU
wavefront silently drops most steering-wheel controls). **pkg199 Stage 2
DONE, both backends** (PR #617 CPU, PR #619 GPU) — full HG in-scatter
homogeneous world-volume scattering; GPU `template<bool HasWorldScatter>`
fleet isolation keeps fog-free scenes byte-identical to Stage 1; god-ray
CPU↔GPU parity [1.0044, 0.9972, 0.9978]. GPU wavefront fog now delivers
real god-rays, not just absorption. **pkg201 Stage 1 DONE** (PR #618) —
`world_max_bounces` HONEST-FAIL→PASS (ratio 5.24), `use_light_tree`
reconciled, a latent `set_light_sampler` crash fixed. **pkg198 Stage 2
DONE** (probe PR #620 PROCEED verdict + full mirror PR #622) — GPU
wavefront light-path render-pass mirror, sum-to-beauty exact, fleet
register gate re-confirmed unchanged; **pkg198 is now COMPLETE across both
stages.** **pkg202 DONE** (PR #621) — legacy `add_sun_light` GPU
zero-contribution fix via upload-time dedicated-distant conversion (GPU
0.0→0.6333 vs analytic 0.6366); fixes every `.blend`-importer sun on GPU.
**pkg201 Stage 2 DONE, 2-of-6 rows shipped** (PR #623) — `film_transparent`
alpha (first implementation anywhere in the engine) and `filter_width`
flip PASS; `pixel_filter_type` stays HONEST-FAIL on a σ-mapping shortfall,
filed forward as **pkg203** (open, dispatchable); native-caustic-toggle
Finding E reclassified to pkg201 Stage 3 (register-hostile); `film_
transparent_glass` (F-glass) filed as a next-round follow-up feature.
**Open follow-ups:** pkg201 Stage 3 (register-hostile, probe-gated),
pkg203 (filter σ parity), pkg131, the F-glass compositing follow-up, the
CPU legacy-hittable delta-sun MIS gap, pkg198's volume-pass direct/
indirect split, and 3 pre-existing `UnicodeEncodeError` console-artifact
test failures (cp1252 vs π/✓/λ — hygiene, not a regression). Full detail:
`.astroray_plan/docs/STATUS.md` round-closeout section "2026-08-14 →
2026-08-15". Pillar 4 stays PAUSED — the owner has requested a
fresh architect-led run next session. **"Current sequencing" unchanged —
no new owner directive this round.**

**Round closeout (2026-08-13 → 2026-08-14): 8 PRs (#605–#612), no open PRs at closeout — viewport navigation is now interactive (5.97→18.52 fps, 3.1x combined), the spectral node system (pkg195) is fully complete, and the GPU wavefront gains denoise-guide AOVs, a working world-volume fog, and procedural textures.**
**pkg192 DONE** (PR #605) — viewport navigation interactivity Suspect A:
camera-only orbit/pan/zoom frames skip the ~48ms per-frame CPU BVH rebuild
(`skip_upload=True`); 5.97→8.44 fps. **pkg196 DONE** (PR #609) — Suspect B,
reduced-res navigation layered on pkg192 (Cycles-style, divisor N=2);
8.36→18.52 fps p50 (2.2x), 5.97→18.52 fps (3.1x) combined with pkg192.
**pkg193 DONE** (PR #607) — camera-view overlay alignment: off-center-
frustum matrix-cell bug + F12 film-fit shift scaling bug, both fixed;
worst-case corner offset 223px→0.00px. **pkg194 DONE** (PR #606) —
Principled tinted-layer spectral-carry + thin-wall per-λ, both pkg188
Finding-C descopes shipped CPU+GPU after a register-gate probe PASSED; band
error on coloured-tint-over-dark-base materials 72.46%→0.00%. **pkg197
DONE** (PR #608) — GPU wavefront denoise-guide AOVs (albedo/normal/depth,
intersect-stage capture, shade kernel untouched) plus `applyPasses`/OIDN
wired into the GPU route for the first time — GPU renders now actually
denoise (+8.0% edge-MSE improvement, guided vs guideless). **pkg199 Stage 1
DONE** (PR #611) — GPU wavefront homogeneous-world Beer-Lambert absorption
CPU+GPU, after a spec-premise correction (the CPU volume code had been dead
since pkg14); furnace Tr matches analytic to <2e-4. HW FAIL (1e30 occlusion
sentinel used as NEE path length, saturating fog to black) → fixed → HW
PASS. Stage 2 (full HG scattering, XL) filed spec-only, open. **pkg190
DONE** (PR #612) — first GPU procedural textures (checker/brick/magic/
wave) via 3D-voxel bake-at-upload; a mandated pkg119-B re-baseline found
the real TRANSLATION-BUG set was 4 nodes (not the stale "5" figure), all
now fixed — TRANSLATION-BUG 4→0, summary 25→30 pass. HW FAIL (`run_parity`
scene-routing + EXR-reader defects) → fixed → HW PASS. **pkg195 Stage C
DONE** (PR #610) — spectral node system remainder: `register_spectral_
profile`, Drawn/Preset/Blackbody spectrum nodes, in-band Replace mode
(bypasses Jakob-Hanika upsampling), IR/UV de-fang, Sellmeier B/C restored.
**pkg195 is now FULLY COMPLETE across all three stages.** **Specs filed,
open:** pkg198 (GPU light-path AOV passes, register-hostile, probe-first —
may park). **Open follow-ups:** pkg199 Stage 2, pkg131 (adaptive sampling
wavefront leg), the pkg176-line deep F12 per-setting pixel-honour matrix,
the caustic-integrator/CPU-wavefront-reference world-volume gap (fog is
invisible to caustics — pkg199 non-goal), the legacy `add_sun_light`
GPU-dimness finding (pkg194 review, undiagnosed), and an Object-coordinate-
mode guard for the pkg190 procedural bake (Generated-space only per spec
scope). Full detail: `.astroray_plan/docs/STATUS.md` round-closeout section
"2026-08-13 → 2026-08-14". Pillar 4 stays PAUSED.

**Round closeout (2026-08-12 → 2026-08-13): 15 PRs (#585–#599), no open PRs at closeout — GPU capability restoration (first GPU texture support, viewport progressive-refinement fix) + Principled spectral correctness (per-λ conductor thin-film, dispersion, transmission colour/scalar separation) + a build-integrity guard.**
**pkg183 DONE** (PR #592) — stale-object ABI-mixed-binary guard in all three
build wrappers, plus a cuobjdump ground-truth CUDA-arch gate (exit 6/7) that
catches the fleet-wide stale `CMAKE_CUDA_ARCHITECTURES=52` CMakeCache
incident this round also surfaced (worktree STACK 2640 readings were
Maxwell-PTX artifacts; true sm_120 `<false>` baseline is STACK 3608). Root
cause (CMakeLists non-cache `set()`, `configure_and_build.bat`,
`build_blender_addon.py` hardcoded arch/Debug revert) queued as a separate
infra follow-up PR. **pkg185 CLOSED** (PR #589) — the GPU glass-caustic
parity gate failure root-caused to an un-Ω-scaled test-scene sun light, not
GPU transport (SSIM 0.0101→0.9606 after the test fix); GPU transport
confirmed healthy. **pkg186 DONE** (PR #590) — first GPU image-texture
support (baked buffer + nearest fetch) + backend-aware `__gpu_features__`
so the addon Diagnostics panel stops overclaiming GPU capability. **pkg182
follow-up DONE** (PR #586) — per-λ-native Principled conductor thin-film
supersedes the RGB-upsample approximation (17/17 gates HW-verified); the
saturation-jump premise didn't hold at 4 samples, but this closes a real
JH-round-trip correctness gap. **pkg187 DONE** (PR #593) — Principled BSDF
dispersion, CPU-complete (OpenPBR/Cycles-WIP Cauchy fit, cited; prism
chromatic spread 4.267→5.345px), GPU wired but gated on the pre-existing
pkg189 no-op filed the same day. **pkg184 DONE** (PR #597) —
`template<bool HasPhotons>` isolation of the photon-caustic k-NN gather,
non-photon shade kernel −2.3% wall time. **pkg191 DONE** (PR #598) — GPU
viewport progressive refinement: the GPU dispatch ignored the
`renderSeed==0` fresh-random contract, making every viewport chunk render
identical noise; one-spot fix, MSE-to-256spp 7.0e-4→1.3e-5. **pkg188
DONE** (PR #599) — Principled film-off transmission colour/scalar
separation CPU+GPU retires the Stage-3b upsample hack; QUANTIFIED a ~72%
band-error residual on coloured-tint-over-dark-base materials, raising the
priority of the new **pkg194** descope. **pkg175 drift-gate fix**: flipped
to done (PR #547, 2026-08-07 — its spec had stayed "in review" past its
own merge). **HEADLINE ENGINE FINDING** from the pkg195 spectral-node
design session (PR #596): `multiwavelength_path_tracer` has NO light
sampling — every lamp-lit NIR/UV render is black end-to-end; Phase 1 spec
filed, not yet implemented. **Specs filed, open:** pkg189 (GPU dispersion
enablement, next up), pkg190 (GPU procedural textures), pkg192/pkg193
(viewport-addon diagnosis-first, from owner hands-on feedback), pkg194,
pkg195. **Owner decisions:** wavefront perf ceiling stays at 1.5s
(ratified); overnight autonomous run authorized. Full detail:
`.astroray_plan/docs/STATUS.md` round-closeout section "2026-08-12 →
2026-08-13". Pillar 4 stays PAUSED.

**Round closeout (2026-08-08 → 2026-08-10): 17 PRs (#566–#582) — Principled-BSDF completion run, no open PRs at closeout.**
**pkg178 native Cycles Principled BSDF is now fully COMPLETE** (Stages
0–5, PRs #566–#581): a faithful `"principled"` material plugin (core
lobes, coat/sheen/anisotropy/approx-SSS/emission/alpha, **thin film +
thin wall** per Belcour-Barla 2017), CPU+GPU byte-mirrored, driven from
the Blender addon's Stage-5 socket routing. The `template<bool
HasPrincipled>` D4 isolation (#570) permanently pins the non-principled
shade-path STACK at 3608 B, closing a +52% fleet-wide regression class a
naive lobe-count increase would otherwise reopen every time. Along the
way, **pkg182** (PR #582) fixed a pre-existing `ggxReflect` eval-D/pdf-D
regularizer mismatch that made low-roughness Principled metallic/specular
near-black (0.067→0.604 at r=0.02) — filed and closed same-day. **pkg172
effect (A) CLOSED** (PRs #551/#553/#576): the pbrt-v4 guarded-pdf form
removes the universal 0.628%/bounce `f/(pdf+1e-3)` energy loss CPU+GPU
across every leg; effect (B) remains pkg173's separate, lower-priority
scope. **pkg176 Blender native steering wheel is now fully COMPLETE**
(Stages 0–4, PRs #555/#556/#561/#568): native Blender/Cycles settings and
panels are the only steering wheel, custom UI retired to one Astroray
panel, owner-approved 2026-08-09. **pkg181** (PR #569) fixed the systemic
~12–20% Astroray-vs-Cycles dim and dark lamp reflections (dedicated
lights were invisible to BSDF-sampled rays) — a prerequisite the run's
Cycles-parity numbers rest on. **pkg179 CLOSED by diagnosis** (owner
ratified 2026-08-09): the "3× dead-sample rate" was a measurement
mislabel, not a bug; no engine code changed. **This closes the
Integration Milestone's originally-scoped package set** (pkg175/176/177/
119-B/C all DONE) plus its pkg178 extension — see "Current sequencing"
above. **Open, not blocking:** thin-film-vs-Cycles saturation parity +
one coordinated pkg119-B/pkg129 harness band re-pin (pkg181 + Smith-G +
pkg172(A) + thin-film + pkg182 together); the durable
`GLoweredMaterial` by-value-`GMaterial`-copy fix (prototyped in worktree
`.claude/worktrees/sad-maxwell-ff99d1`, uncommitted) needs re-apply on
settled main. Pillar 4 stays PAUSED pending explicit owner go-ahead.

**Round closeout (2026-07-25 evening → 2026-07-26): 6 PRs (#525–#530) — wavefront GPU-parity follow-ups after pkg55 Phase C's finale, no open PRs at closeout.**
**pkg55 is now fully COMPLETE** (both megakernels deleted, PR #524, 2026-07-25 — landed the prior session) and every package this round is downstream of that: restoring a GPU capability the deletion silently dropped, or fixing a defect the wavefront-only world finally made visible. **pkg88-B** (PR #525) — object motion blur addon bake; independent (different-model) review caught a real bug all 13 of the PR's own tests missed (only `t_end` was snapshotted, so CENTER swept half the arc and END silently disabled object blur entirely); a real headless-Blender run then found a **pre-existing pkg88-A defect** — `convert_scene`'s `clear()` wipes the camera before `set_camera_motion_blur()` runs, so **camera motion blur has failed outright in real Blender since it shipped**, invisible to every suite that mocks `bpy`; both fixed in #525, `scripts/verify_pkg88b_blender.py` promoted as a permanent real-host guard. **pkg157** (PR #526) — firefly clamps (`clampDirect`/`clampIndirect`) ported into the wavefront, restoring what C7's deletion sweep silently dropped; cross-binary no-op measured **2.48e-07 relative to peak**, ~40× inside the 1e-5 convention; exposed a **phantom `launchStageInit`-family overload** in `gpu_wavefront_state.h` (a declaration no definition matched), 3 of 4 instances fixed at the root. **pkg160** (PR #527) — plain `metal` (not Disney metal) was found **~3.5×/7× (mean/median) too dark on GPU**; Step-0 table comparison then found the CPU side was the physically wrong one (`GGXEnergyCompensationLUT`'s 256-sample hemisphere estimate cannot resolve a narrow GGX lobe, driving `Fms` to 96.5% of its ceiling exactly where multiscatter should vanish) — **owner chose to fix the CPU**, which turned out to be **creating energy** (white-furnace linear up to 1.77×, 66% of pixels > 1.0; a gamma-rendered furnace test structurally cannot detect energy gain — new memory `gamma-furnace-cannot-detect-energy-gain`). Fixed by routing plain metal through the same Kulla & Conty compensation `disney.cpp` has shipped since pkg60; ships the plain-metal GPU/CPU parity gate that never existed (31/32 green, one owner-approved asymmetric-band exception at roughness 0.9 owned by new spec **pkg163**). **pkg162** (PR #528) — the fourth and last phantom-overload instance (`launchStageInit`, a load-bearing default argument) closed; class now 4 found / 4 resolved; no dedicated spec, tracked in STATUS.md + standup. **pkg159** (PR #529) — GPU cryptomatte restored in the wavefront (a real capability regression from #524 nobody had filed); cross-path Psyop IoU **0.964–0.984** vs a 0.85 threshold, demonstrably discriminating (GPU leg distinct from CPU leg). **pkg161** (PR #530) — built a firefly-bearing gate scene to close a two-day gate hole (no scene in the library had a heavy-enough tail to demonstrate suppression): `firefly_window` measures **22.85×** peak/p99.9 (target ≥10×) vs a 1.07× negative control; un-skips pkg157's suppression gate. **Two investigations closed without shipping code:** pkg155 Phase 1 confirmed the ~5× GPU absolute slowdown on a corrected metric (total GPU ms/render, since the spec's per-launch metric died with #524) and convicted the shade stage (221 regs/thread, 1 block/SM, recovery target ≤128); the sm_120 build-config lever was **ruled out with numbers** (native AOT 1.68–1.80× SLOWER than the current sm_89-JIT build — the register problem is intrinsic to the kernel, not a build artifact). **Specs filed:** pkg163 (spectral-vs-RGB compensation colour-space parity, metal-only defect on a not-metal-only seam); pkg158 narrowed (Disney-metal reconciliation Step-0 re-baselines on a post-pkg160 SHA); pkg120 + pkg88 Phases B/D unblocked (stale pkg55-Phase-C blocker markers cleared). **Owner decisions:** fix-the-CPU direction on pkg160; the r=0.9 asymmetric band exception; GPU/CPU parity-band tightening project-wide and the `MAX_GLOSSY_PARITY_MSE` re-pin (branch `pkg164-glossy-mse-repin`, **PR #532** — re-pinned 0.04 → 0.006 on a measured 0.003411/0.003492/0.003415 spread, 1.72× headroom; pkg160's own defect measured 0.02474 and passed the old bound) remain open owner items. **Next pickup:** pkg163 (owns retiring pkg160's exception) → pkg158 (Disney metal reconciliation) → pkg156/pkg120 (share the `stage_advance.cu` wavefront lane, serialize) → pkg150 (Disney dielectric VNDF) → pkg88-D (wavefront motion, scope reworded post-#524) → pkg119-B/C (Blender differential harness). pkg155 Phase 2 stays an opportunistic GPU-lock gap-filler (needs the GPU at every bisect point, not compile-only as originally scoped); pkg153 (wavefront_diff env-gate disposition) remains in flight with the gate-failure-reviewer. Pillar 4 stays PAUSED.

**Round closeout (2026-07-19 → 2026-07-20): 9 PRs — pkg55 Phase C C3+C4 landed (C5 open-verified), pkg89 GPU dedicated lights, pkg121/pkg119 parity infra, 15 specs filed.**
**Overnight autonomous run on the travel laptop (RTX 3000 Ada sm_89, CUDA 13.2, no OptiX SDK).** **pkg55 Phase C advanced from 2 to 5 of 7 sessions.** C3 (PR #486) threaded non-visible-band + naive-multiwavelength support into the wavefront (NIR/UV naive parity SSIM 1.0000/0.9999 agreement-on-black, visible naive 0.9917); the committed lambda-threading had never compiled in Release and a stale shadow `.pyd` produced a phantom 573× "divergence" — fixed by completing a forward decl + rebuild, no emission change, and the prior "MW megakernel black in NIR" claim was RETRACTED (the real gap is CPU `path_tracer` band-unawareness → pkg125). C4 (PR #490) ported TLAS/instancing + deformation motion into the wavefront (2/3 gates pass; a miswritten exact-equality bit-identity gate was adjudicated to the architectural ~2e-7 atomic-accumulation floor → 1e-5 Monte-Carlo convention — **the GPU wavefront was never run-to-run bit-exact**). C5 (PR #494, OPEN-VERIFIED, not merged at closeout) ported spectral photon-map caustics (2/2 gates + 40-test regression green on RTX; the load-bearing bug was a photon-flush nested inside `if(hasRad)` dropping caustic energy on zero-radiance dead paths). Megakernel deletion stays LAST (C7). **pkg89 GAP-1 DONE** (PR #489) — dedicated lights uploaded to the GPU (`GDedicatedLight` tagged-union + device `sampleLi` + unified power CDF into the MW-megakernel NEE) so Blender-lamp scenes stop rendering DARK on GPU: **AREA 0.998 / POINT 0.997 GPU==CPU parity (black→parity)**; GAP-2 energy audit (CPU wattage→radiance mis-scaled vs Cycles — AREA 0.13×, point ~3.6× opposite, blackbody ~14×; not a clean factor) escalated to **pkg122** (spec PR #488). **pkg121 Phase A** (PR #485) — Mitsuba 3 chi² sampler harness ported (BSD-3), Lambertian anchor passes p=0.23, Disney spec-lobe sample/pdf mismatches xfail'd → **pkg123**; Phase B validation campaign spec'd with the first gallery already rendered (`test_results/chi2_visuals_2026-07/`). **pkg119-A** (PR #487) — first Blender parity coverage matrix (v4 AST-scanned, reworked four times under adversarial review to an honest **131 SUPPORTED / 23 APPROXIMATED / 370 DROPPED-SILENT / 20 stale sockets of 524 socket-level features**); Phases B+C open. **15 new specs filed (pkg123-137):** correctness/sampling (pkg123 Disney spec-lobe chi² adjudication, pkg124 VNDF sampling, pkg125 CPU band awareness, pkg126 mesh-emitter unification; PR #493), material+caustics (pkg127 Specular Polynomials, pkg128 thin-film iridescence, pkg129 Turquin reflection multiscatter LUTs; PR #491), and eight platform techniques (pkg130 light groups, pkg131 zero-knob adaptive sampling, pkg132 host-mapped memory fallback, pkg133 SRF spectral sensors, pkg134 Light Path Expressions, pkg135 demand-loaded sparse textures, pkg136 SVO wavefront path guiding, pkg137 partitioned SMS+ReSTIR caustics; PR #492). **Direct-to-main:** root-shadow-pyd trap killed (94ae956 — the C3 phantom-divergence root cause), permissions allowlist (1efe9bc), pkg115 Blender-verify CUDA-13 fix (3778f37), other-engines technique sweep (7a4c970 — the research base for pkg130-137). **Owner notes:** corpus runner cut from pkg119; `dist/` tcnn zip kept; `Google_Apps_Script.txt` kept (drives the owner's Sheets tracker — keep plan-doc formats compatible). **Hardware context:** development moving back to the RTX 5070 Ti workstation imminently — wipe + fresh-configure the OneDrive `build_cuda` on arrival (`DEVELOPMENT.md`); laptop-pinned observations (seed-flaky clamp gate, walltime baselines) may differ there. **Next pickup:** pkg55 Phase C C6 (ReSTIR SoA, GRIS-anchored) → C7 (2× gate + megakernel deletion) → pkg123 Disney spec-lobe adjudication → pkg122 energy calibration → pkg119-B differential harness + stale-socket fixes → pkg121-B visual campaign. Pillar 4 stays PAUSED.

**Round closeout (2026-07-18): 1 PR — pkg114 COMPLETE (exporter transform-only dispatch → TLAS refit), first travel-laptop session.**
**pkg114 is now fully COMPLETE.** The one remaining exporter INTEGRATION landed (PR #479, 2026-07-18, pure Python — no C++/CUDA change, bindings were in #468): the addon exporter's `Change.TRANSFORMS` viewport path now dispatches the inc-3d TLAS-only refit. `convert_objects` records `_renderer_instance_id_map` {source name → [instance_id…] in dupli order} + `_renderer_instancer_eligible` {instancer → not nested AND all duplis through a shared BLAS}; a pure-transform GPU batch whose changed objects are all instanced sources or eligible instancer empties re-walks `depsgraph.object_instances`, re-derives each dupli's fresh `matrix_world`, calls `update_instance_transform` per id + one `upload_instance_transforms()` + `render(skip_upload=True)`; everything else (mixed flat+instanced, poisoned/nested instancers, multi-domain, CPU) falls back to full sync. **Headless Blender 5.1 (RTX 3000 Ada):** refit render byte-identical to a full re-sync (mad 0.00000 < 0.02); moved/stale controls both 0.092 (non-vacuous). 7 dispatch + 13 pkg116 cache + 15 pkg56 dispatch + 80 addon + 5 GPU TLAS tests green; CI green; pr-reviewer verified the stale-map invariant and merged. **First session on the travel laptop (RTX 3000 Ada sm_89, CUDA 13.2, no OptiX SDK).** Direct-to-main (no package closed): CUDA-13 `bin\x64` DLL-layout portability + laptop-portable hooks/skills; dead-root-file cleanup; the 2026-07 PBR-advances research sweep + follow-up pass (Turquin albedo-scaling LUTs answer multiscatter GGX — `adobe/openpbr-bsdf` Apache-2.0 with 7 CUDA-ready LUTs; thin-film = Belcour-Barla; RTXDI DISQUALIFIED for ReSTIR-PT); `total_max_depth` cap gate promoted xfail→live; the pkg55 Phase C implementation plan (7 sessions, delete-megakernels-last). **Hardware state:** fresh clean CUDA-13.2 build sweep on the laptop **1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed** (the 32 skips are OptiX-SDK + OpenEXR-gated, unlocked on the workstation build — not a regression). **In flight:** pkg55 Phase C Session C1 (spectral-tables + light-tree-probe extraction), branch `feat/pkg55-c1-spectral-tables-extraction`. **Next pickup:** pkg55 Phase C (the active arc) → pkg115/pkg89 small follow-ups → pkg88 C.1/Phase B → pkg64 spectral caustics → post-Phase-C material candidates (Specular Polynomials SMS seed-finding, thin-film iridescence, Turquin multiscatter LUTs). Pillar 4 stays PAUSED.

**Round closeout (2026-06-12 morning): 4 PRs — pkg115 COMPLETE — Cycles-parity textures + GENERATED coords fix, 1289/0; pkg114 inc 3d — TLAS-only refit 19.5% of full upload.**
**pkg115 COMPLETE.** All Stage 2 chunks + the GENERATED-coordinates mesh fix landed (PRs #467/#471/#472, 2026-06-12): chunk 6 addon dedup (#467 — unified procedural param mappings onto Cycles-parity ports; review caught a shipped RIDGED↔HYBRID enum swap, fixed+regression-tested); visual-gate diagnosis (#471 — 4 root causes separated: GPU dark = pkg89 dedicated lights not on GPU; CPU hang = OpenMP deadlock inside Blender generalized to MSVC/vcomp — **ALL addon builds need `-DASTRORAY_DISABLE_OPENMP=ON`**; harness sample property; UV-vs-GENERATED coordinate space); GENERATED coords fix (#472 — `Texture::setGeneratedBBox` + `set_texture_generated_bbox` binding + addon bakes world bbox per object; **128-spp Blender stills: checker=3D blocks, brick=brickwork, wave=bands, voronoi patterned — semantic parity with Cycles**). Full suite **1289 passed / 0 failed**. pkg98 SIGN-OFF (Opus). **Remaining small follow-ups recorded in spec:** gradient + noise spheres near-black on addon path; pkg89 dedicated-light energy audit; per-object texture instancing for shared materials. **pkg114 inc 3d DONE** (PR #468, dedicated agent) — TLAS-only refit for transform-only edits: `updateInstanceTransform` (CPU in-place) + `uploadInstanceTransforms` (re-push only `d_instances`+`d_tlas` via `buildTlasOnly()` — **no BLAS geometry walk**) + `render(skip_upload=True)`. RTX: refit upload **19.5%** of full `upload_geometry` on 3200-tri ×16-instance (≤50% budget met); byte-identical vs from-scratch rebuild. **Remaining:** exporter `Change.TRANSFORMS` branch wiring (instance-id map integration). **Hardware state:** RTX sweep on merged main f11085c: 1289 passed / 0 failed / 23 skipped / 21 xfailed / 3 xpassed. The 3 xpassed gates are spectral-path-tracer ported flags.

**Round closeout (2026-06-12 overnight): 5 PRs — pkg55-B' Phase B' COMPLETE — viewport-parity gate MET: wavefront p99 = 0.84× Cycles-OPTIX.**
**pkg55-B' Phase B' COMPLETE.** All three Phase-B' acceptance criteria MET: perf gate 1.50× (PR #459 cool-GPU re-baseline), wavefront_path_tracer registered (PR #459), viewport-parity gate MET (PR #463 — wavefront steady-state pan-frame p99 = 0.84× Cycles-OPTIX, target ≤1.2×; mean 0.97×, p50 0.98×). Full RTX suite on merged main 3804dca: **1277 passed / 0 failed / 23 skipped / 22 xfailed / 2 xpassed**. **The "viewport feels like a slog" complaint is formally resolved: Astroray-wavefront ≤ Cycles on pan-frame p99, at parity-or-faster on every statistic.** Phase C (MIS audit + megakernel removal + 2× gate) remains open as the package's final phase. Deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.

**Round closeout (2026-06-11 afternoon): 8 PRs — pkg115 chunks 2-5 COMPLETE + pkg55-B' Sessions N+6/N+7 COMPLETE.**
**Two packages advanced major steps this round.** All RTX-verified. Final sweep on merged main 5e21bd5: **1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**. **pkg115 chunks 2-5 DONE** (PRs #441/#442/#445/#446, 2026-06-11) — Noise/Wave/Brick/Voronoi Cycles parity: Chunk 2 (#441) = Jenkins lookup3 hash (bit-exact) + Perlin core (BSD-3-Clause) + fractal stack + WhiteNoiseTexture + NoiseTextureCycles (Blender "Noise Texture" node); Chunk 3 (#442) = Wave (fixes ~6.4× density bug, signed-fBM detail distortion, band/ring direction enums) + Brick (3D input, `brick_noise` hash bit-identical, per-brick color variation, mortar_smooth smoothstep); Chunk 4 (#445) = full Cycles-parity Voronoi (distance metrics, Features F1/Smooth F1/F2/Distance to Edge/N-Sphere Radius, cell jitter, fractal layering, node conditioning), lead-review fixes (normalize at detail=0, Distance-to-edge midpoint term, fractal position accumulator shadowing); Chunk 5 (#446) = addon `ShaderNodeTexVoronoi` translation + factory full-param wiring (fixes latent regression where addon feature map was stale after #445 enum change — F2 would have rendered Smooth F1), backward-compatible. 1271 passed, 0 failed. pkg98 SIGN-OFF (chunks 2-3, line-by-line vs canonical Cycles `svm/*.h` sources). REMAINING: addon-side private texture-definition duplication removal + Blender-vs-Cycles RTX visual verify. **pkg55-B' Sessions N+6/N+7 DONE** (PRs #443/#444/#447/#448, 2026-06-11) — **GPU wavefront now produces IMAGES at megakernel parity.** N+6 (#443) = end-to-end pipeline with `stage_advance.cu` (one-bounce device twin of CPU `advance_one_bounce`, calls UNMODIFIED megakernel device functions — design decision #9: one generator of sampling math), `gpu_env_spectral.cuh` (env-miss eval factored VERBATIM out of MW kernel), `cuda_wavefront_render` host driver + binding; measured (RTX 5070 Ti, session_n1_envmap_cornell 64²×64spp): GPU-WF/CPU-WF per-channel mean ratio [1.089, 0.991, 1.045] (systematic, inherited from documented megakernel-BSDF↔CPU-plugin divergences); gate ≤0.12. PR #444 root-caused the ~1.85× "MAJOR FINDING" as a measurement artifact (applyGamma=True vs linear oracle) AND fixed a real latent bug (megakernel ignored `worldMaxBounces`); linear-vs-linear [1.091, 0.993, 1.050]. N+7 part 1 (#447) = host-overhead elimination, measured-first: device-side per-sample XYZ accumulation kernel, `launchStageAdvance` sync=false → ONE sync + ONE download per render; wavefront 0.300 s → 0.108 s (2.8× faster), gap to megakernel 1.55× (was 4.0×); WF/MK image ratio unchanged [0.997, 0.999, 0.997]. pkg98 SIGN-OFF (Opus): accumulation-kernel equivalence verified, sync=false safety traced, accumulator race-freedom confirmed. N+7 part 2 (#448) = alive-queue compaction — **MEGAKERNEL PARITY**: shared `advancePathSlot` device function (one generator, decision #9), ping-pong slot queues with device-side counters; measured: wavefront 0.074 s vs megakernel 0.070 s — **1.05×** (from 1.55× part 1, 4.0× N+6); WF/MK image ratio unchanged to 7 decimals [0.997, 0.999, 0.997]; full suite 1271 passed / 0 failed. pkg98 SIGN-OFF (Opus): refactor purity proven byte-identical, ping-pong race-freedom traced, alloc/free leak-safe. REMAINING for B' close: N+7 part 3 (sort-by-material + intersect/shade split — the 254-reg cliff; ≥1.5×-FASTER gate needs warp-coherent shading), wavefront_path_tracer plugin registration, 7-material contact-sheet perf gate, pkg81 viewport-parity gate; deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch. **Next pickup:** pkg55 Phase B completion (N+7 part 3 + plugin registration + perf gates), pkg115 dedup + RTX visual verify, pkg88 C.1 + Phase B (after pkg114 inc3), pkg64 spectral caustics. **Hardware state:** all verified on RTX 5070 Ti; full suite at #448 merge: 1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed; the 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics flags) STILL pass, promote next round; pkg114 inc3 (addon instancing) still pending with dedicated agent.

**Round closeout (2026-06-11 morning): 8 PRs — pkg108/pkg86-B/pkg116/pkg88-C.0/pkg115 chunk 1 COMPLETE + pkg114 inc 1+2.**
**Five packages shipped this round (morning).** All RTX-verified. Final sweep on merged main 75185a6: **1214 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**. **pkg108 DONE** (PR #432, 2026-06-10) — Addon residual bug triage: BUG-14 was REAL on CUDA only (`gpu_dielectric_sample` delta refraction dropped tint, fixed `s.f = baseColor*eta²`); BUG-16 GPU half fixed in BOTH shading paths (GMAT_DISNEY + closure-graph diffuse lowering) with Burley §5.3 HK subsurface mix, gated bit-identical at subsurface=0; BUG-09 verified non-reproducing via live headless Blender 5.1 routing. 6 regression tests. **pkg86-B DONE** (PRs #434/#436/#438, 2026-06-11) — GPU light tree Phases 2+3: device traversal mirrors Cycles `kernel/light/tree.h` (Apache-2.0, e52e5eb0) via `src/gpu/light_tree_device.cuh`; bit-trail pdf walk; both megakernels branch on `GLightTreeView`; Power mode bit-identical. RTX: pick parity ≥99.5%/10k queries (pdf rel-err <1e-4), upload 0.09–0.5ms @10k lights, single-light PSNR 100dB, SAOH two-cluster routing >95% both backends. GPU variance 1.110× — 2.0× gate xfail on BOTH backends (Phase-1 scene-structure limitation; parity gate proves GPU mirrors CPU tree). Deferred: wavefront wiring→pkg55-B; dedicated lights→power-CDF fallback+warning. **pkg116 DONE** (PR #435, 2026-06-11) — Exporter/cache refactor: `exporter.py` owns viewport sync; six per-domain caches with `diff()`; `Change` IntFlag aggregator; `RenderEngine` thin shim. 135 addon tests green, zero existing-test edits. **pkg88 Phase C.0 DONE** (PR #437, 2026-06-11) — Deformation motion blur: `add_triangles_bulk_motion` bulk binding, time-aware `Triangle::hit` + `gpu_triangle_hit_motion` (Cycles `motion_triangle.h`), union-AABB BVH, `GRay.time` end-to-end both megakernels. RTX: no-op bit-identity, CPU+GPU streak, union-AABB extremes, cross-backend motion/static energy-shift parity. REMAINING: C.1 per-primitive split (perf-gated), Phase B addon bake (after pkg114 inc3), Phase D wavefront (after pkg55-B). **pkg115 Stage 2 chunk 1 DONE** (PR #439, 2026-06-11) — Procedural texture parity: Stage-1 research audit committed (`.astroray_plan/docs/blender-procedural-parity-research.md`); chunk-1 = GENERATED coord default, signed Normal coord, (u,v,0) UV 3D point, Checker floor-parity, Gradient 4 formula fixes, Magic verbatim port, `eval_texture_at_3d` debug binding. REMAINING chunks: hash/WhiteNoise, Perlin/Noise, Wave, Brick, Voronoi, addon translator dedup + standalone CI example + RTX visual verify vs Cycles. **pkg114 inc 1+2** (PRs #430/#431 by parallel Opus agent, not this session): GPU core landed (structs + `gpu_tlas_hit` + identity + real multi-instance transforms with non-uniform scale/mirror). **Notable test-suite state change:** 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics flags) now PASS and should be promoted next round. Expected: 0 failures / 20 xfails (legacy pkg64-gpu SMS + pkg86 2× variance + others).

**Round closeout (2026-06-10): pkg118 + pkg113 + pkg112 COMPLETE.**
**pkg118 SOLVED** (PR #423, 2026-06-08) — the rough-glass furnace energy deficit was the **η²
albedo-LUT clamp** (the CPU twin of the #404 GPU glass-dark bug): `Material::sampleSpectral`
upsampled glass throughput through `RGBAlbedoSpectrum`, whose Jakob-Hanika ALBEDO LUT clamps
rgb>1 to 1, clipping the exit refraction's eta²=2.25 radiance recovery. Fix: factor the >1
magnitude out as a flat spectral scalar (mirrors GPU #404), upsample only the normalized tint.
CPU furnace 0.77/0.82/0.92/0.97/0.96 → 0.89/0.94/1.00/1.00/1.00; `test_disney_rough_glass_furnace_energy_cpu`
PASSES [0.92,1.03]; no regressions. The spec's Part B (Kulla-Conty multi-scatter table) was a
dead-end (the deficit was NOT single-scatter masking). Full diagnosis:
`.astroray_plan/docs/pkg118-multiscatter-energy-research.md`. **pkg113 DONE** (all 3 phases merged +
RTX-verified, PR #422 store, #424 emission, #425 gather) — GPU photon-map caustics: uniform hash-grid
store, GPU photon emission + bounce → deposit, adaptive k-NN cone gather wired into both GPU
integrators. Phase-3 follow-up resolved: the "GPU caustic 5.6x more spread" was REAL but the diagnosis
was INVERTED — the GPU was correct; the **CPU reference carried an exit-refraction sign bug** (both CPU
caustic loops keyed enter/exit off the ray-ORIENTED `rec.normal`, always taking the "entering" branch;
fix = recover geometric outward normal `ng = frontFace ? rec.normal : -rec.normal`). RTX-verified:
glass-sphere parity ROI ratio 1.09x, SSIM 0.962, peak 0.409; pkg110 conc 32.4; 26 caustic/GPU tests
pass, 0 regressions. Detail: `pkg113-phase3-gather-wiring-research.md` RESOLUTION section. **pkg112
DONE** (PR #427) — batched geometry upload: one `add_triangles_bulk` pybind call per mesh (looping in
C++), replacing the per-triangle `add_triangle` round-trip. Addon fills arrays with Blender's C-speed
`foreach_get`; **31.7× upload speedup** on 100,352 tris (692.7ms→21.9ms). Verified at four layers:
binding pixel-identity (bit-identical CPU render), extraction-parity unit test (non-uniform-scale +
inverse-transpose normals + multi-UV order), and a **real-Blender end-to-end bit-identical render**
(headless Blender 5.1). **Next pickup:** pkg114 (two-level BVH TLAS/BLAS) → pkg55 (wavefront SoA) →
pkg64 (spectral caustics) — all GPU-gated + RTX-verifiable.

**Round 15 Waves 3–5 (2026-05-29→30): forward-light-tracer prism rainbow → general caustics → GPU glass energy + showcase.**
**pkg106 FINISHED** (PR #393) — a triangulated BK7 prism throws a clean continuous rainbow caustic
(hue_spread 0.754 ≥0.7, bright_coverage 0.88) via a NEW forward light-tracer integrator
`plugins/integrators/light_tracer_caustic.cpp` (Arvo 1986 / Jensen 1996); camera-side MNEE is
ABANDONED for flat prisms (the MNEE math is kept for focusing casters). **General-caustics chain
CPU-complete: pkg109** (world-space photon-map kd-tree, PR #395) → **pkg110** (BSDF-driven photon
bounce — hybrid auto-select by caster geometry, PR #397) → **pkg111** (k-NN gather on any receiver,
into the default `path_tracer`, PR #403). "Drop ANY glass + light → caustics on ANY surface through
the default path" now works on CPU. Also: **pkg76 Classroom Gap 2** (non-Principled shader-graph
walk, PR #394), **integrator float-param** ergonomics (PR #396), mesh-caster caustics + scaled-mesh
visibility fix (PR #401), and the **glass-dark frontFace fix** (PR #402 — key enter/exit off
`rec.frontFace`, CPU+GPU). **Wave 5 quality:** **PR #404** fixes the dominant GPU clear-glass
energy bug (delta refraction eta^2 was albedo-clamped to [0,1] by the JH upsampler; white-furnace
0.705 → 0.991 flat @ ior 1.5) and lands a **Heitz-2018 VNDF microfacet-dielectric rough-transmission
rewrite** (PBRT-v4 `DielectricBxDF`, BSD-3-Clause — GPU rough glass now energy-conserving for R≥0.1);
**PR #405** re-authors 6 reference-bank showcase scenes (≥512², gate-green on RTX). The forward
photon-map caustics were CPU-only by design; **pkg113** (the GPU port) is now DONE (2026-06-10, see
closeout section above). The glass-energy fix legitimately moved GPU output, so **two pkg64-gpu HW
gates need re-baselining with written justification** (parity SSIM 0.835 < 0.85; Phase-3 prism PSNR
delta −0.59 < −0.5 dB) — these do not run on CI (no GPU); flagged for the next HW sweep.

**Round 15 Wave 2 (2026-05-28, 3 PRs merged): pkg106 Chunks B/C/D-seed — MNEE foundation complete.**
**pkg106 MNEE foundation COMPLETE** (PRs #389/#390/#391) — Chunks B/C/D-seed shipped: surface (u,v) partials (`manifold/surface_partials.h`), analytic Newton solver (`newton_iterate.h::solveAnalytic`), multi-vertex manifold chain (`manifold/manifold_chain.h` — block-tridiagonal Jacobian + damped Newton), mesh seed-ray + chain convergence on triangulated prism (`manifold/mesh_caustic.h`). All CPU-only header math + unit tests, validated to ~1e-11 vs finite-difference / analytic Snell. **Remaining: Chunk D-radiance** (wire multi-vertex MNEE into live integrator — transfer-matrix geometry term + finite prism faces + in-triangle validity + visibility; currently renders chromatic noise on wip/pkg106-chunk-d-radiance) + **Chunk E** (prism scene + hue_spread ≥0.7).

**Round 15 Wave 1 (2026-05-28, 3 PRs merged): pkg64-gpu Session 2 + pkg106 Chunk A + pkg105.**
**pkg64-gpu Session 2 DONE** (PR #385) — Hero-wavelength distribution bug fixed (lambda[0] violet-only → full-band). Gates re-spec'd (SSIM ≥0.85 + ROI luminance-parity; 0.97 unreachable for independent MC). Measured: SSIM 0.928, energy 1.38×, PSNR +2.19 dB. **pkg106 Chunk A DONE** (PR #387) — Analytic half-vector constraint Jacobian (Cycles mnee.h + Hanika 2015); foundation for Chunks B-E. **pkg105 DONE** (PR #381) — BH Blender addon params (r_obs_M + Kerr spin + ADAF). Pillar 4 Blender surface complete for BH objects.

**Round 14 closeout (2026-05-24, 12 PRs merged): CUDA-port Session N+4 + Sellmeier + pkg76 Classroom audit wave.**
**pkg55-B' Session N+4 COMPLETE** (PRs #355 + #356) — PostLightSample + PostRR CUDA kernel stages
shipped with full CPU↔GPU threshold gates enforced (p99.9 = 2.21e-6, threshold 3.5e-6). Session N+3
gates remain green (PostInit ULP=2, PostIntersect ULP=32). **CUDA-port track continues.**
**pkg64-gpu-sellmeier-upload DONE** (PR #354, `8f0eb03`) — GPU Sellmeier dispersion upload + hero-
wavelength IOR. Unblocks pkg64-gpu Phase 3 prism receiver-energy gate (measured 1.17× ≥ 1.10× PASS).
PSNR floor (−2.13 dB) and SSIM (0.52) deferred to Session 2 (per-wavelength multi-IOR): hero-only GPU
lacks chromatic spread, so per-pixel error is dominated by spatial caustic divergence by construction.
**pkg86-B Phase 1 DONE** (PR #362, `404509d`) — CPU SAOH split + full Conty 2018 importance. Measured
1.14× variance reduction (2× gate xfail retained pending scene tuning or Phase 2/3 GPU validation).
**pkg76 CSV baseline DONE** (PR #357, `e7816d0`) — Junkshop SSIM 0.972 PASS (≥0.85 gate). Classroom/
BMW27 gaps documented for follow-up. **pkg76-followup 4 gaps addressed** (PRs #360, #361, #363, #365) —
BMW27 Blender 4.x mesh layout fix, Classroom Gap 1 (image textures), Gap 2a (non-Principled shader graphs),
Gap 3 (false-positive doc), Gap 4 (area light shapes). **Classroom SSIM gate ≥0.85 not yet met** — Gap 2
(40/42 mats need non-Principled shader graph walk) remains as primary blocker. **pkg-add-cuda-syntax-ci
DONE** (PR #358, `58df412`) — Linux CI now compiles all .cu files with nvcc (syntax + typecheck only);
catches CUDA frontend errors before RTX build. **Deferred to Round 15**: pkg64-gpu Session 2 (multi-IOR),
pkg86-B Phase 2+3 (GPU port), pkg76-classroom Gap 2 (non-Principled shader graphs).

**Round 13 closeout (2026-05-23): CUDA-port milestone + Cryptomatte end-to-end.**
**pkg55-B' Session N+3 COMPLETE** — parts 1/2/2b + RNG/hero/harness fixes (PRs
#338/#343/#346/#349/#351). **CPU↔GPU PostInit gate CLOSED at ULP=2** (vs threshold
4). PostIntersect bounded at 32 ULP (pinned 64). 5-round build-fix saga (#343)
exposed Linux-CI-CUDA-blind gap (Action Item filed). **Session N+4** (next CUDA
port stage continuation) is top Round 14 track. **Cryptomatte end-to-end complete:**
pkg87a (infra, Round 12) + **pkg87b** (integrator integration, PR #344) + **pkg87c
part 1** (Blender pass+bindings, PR #345) + **pkg87d** (IoU + manifest + JSON
round-trip, PR #347) all shipped. IoU 0.85 gate (owner-authorized swap from 0.95
due to MC silhouette-edge noise floor at 64 spp); measured 0.977–0.984 across all 6
names. **pkg64-gpu Phase 2** (megakernel SMS integration, PR #348) + **Phase 3**
(acceptance gates + caustics toggle, PR #350) both shipped; hardware baseline-pinning
blocked on new **pkg64-gpu-sellmeier-upload** spec (Sellmeier dispersion not GPU-
uploadable). **pkg55-followup** (triangle normal shortcut, PR #351) tightens
`hit_normal` ULP on flat-shaded geometry (overall ULP=32 unchanged, dominated by
`hit_point` FMA fusion). **Orchestrator-meta infrastructure complete 2026-05-22**:
**pkg90** (hw-verifier worktree-parameterized CUDA build, PR #333) + **pkg97**
(merged-worktree auto-GC, PR #331) + **pkg98** (independent-review gate, PR #332) —
the HW gate now runs unattended, IMPL_CAP no longer silently saturates, and Track-A
fixes require different-model SIGN-OFF/BLOCK before push. **Blender addon
remediation** (first-principles plan landed PR #300; PR #295 triage): the staged set
is **pkg94** (Stage 1 / P1 build-integrity guard, ~½ day, **Round-10 first pickup,
depends on nothing**) → **pkg95** (Stage 2 / P3+P4 dead-UI-wires + Blender-native
camera, depends on pkg94) ∥ **pkg96** (Stage 3 / P2 reconcile-then-upload sync + P5
honesty guard, depends on pkg94, independent of pkg95). **P5's GPU parity
(BUG-02/10/11/12) is deferred into pkg55-B' as named acceptance gates (BUG-11 ≡
pkg85-D, done), NOT a separate addon GPU package** — pkg96 ships only the cheap
honesty guard. **pkg76 CSV** rows on RTX (unblocked since pkg100). pkg67 (metric-
aware path tracer) shipped PR #262.

**Pillar 4 thawed and shipping (2026-05-11+).** pkg40 (Kerr metric),
**pkg41 Kerr validation** (PR #236), **pkg42 synchrotron emission**
(PR #245 — VolumetricEmission interface, Pandya 2016 fits, bipolar jet
plugin), **pkg43 slim disk accretion model** (PR #271 — Abramowicz
1988 / Sadowski 2009, 14/14 tests), **pkg43 Blender accretion
selector** (PR #285 — black-hole panel dropdown for Novikov-Thorne /
Slim Disk / ADAF), and **pkg47 FITS data loader** (PR #292 — FITS I/O
wrapper + FITSTexture plugin, gated `ASTRORAY_ENABLE_FITS` default OFF;
FITSVolume registration deferred to pkg48 per owner ruling) all done.
**Pillar 4 now ~45% complete.** **pkg44 (ADAF)** is unblocked and
queued for Round 10; pkg45–pkg51 paste-ready specs queued.

- `pkg34-material-backend-capabilities.md` — capability metadata,
  no silent grey-Lambertian GPU fallback, CPU/GPU contact-sheet diffs.
- `pkg35-spectral-gpu-materials.md` — make CUDA material sampling
  spectral for the core material set.
- `pkg36-material-closure-graph.md` — shared material closure graph so
  many new plugins work on CPU and GPU without hand-written duplicates.
- `pkg37-blender-addon-backend-refresh.md` — bring the Blender addon up
  to the backend model: Auto/GPU/CPU device selection, viewport GPU parity,
  CUDA/tiny-cuda-nn-aware packaging, and clear runtime diagnostics.

### Pillar 5 — Production polish

Multi-GPU scaling, OIDN 2.x→3.0, Blender viewport render, motion blur,
output formats, documentation. Ongoing, opportunistic.

- Design: [`production.md`](production.md)
- Duration: ongoing
- Depends on Pillars 1, 3.

---

## The 12-week view

This is the original planning horizon, not a live schedule. For current package
state and next-up order, use `STATUS.md`.

```
Wk 1-2   [A] Plugin registries + migrate one material end-to-end (pkg01, pkg02)
         [D] Ralph begins improving test coverage

Wk 3-4   [A] Migrate remaining materials/shapes/textures (pkg03, pkg04)
         [B] First Copilot plugin as proof

Wk 5-6   [A] Integrator interface (pkg05) + spectral types (pkg10)
         [B] Spectral measured-BRDF loader (RGL database) as plugin
         [C] Cline prototypes tiny-cuda-nn integration

Wk 7-8   [A] Finish spectral migration (pkg11-14)
         [B] Fluorescence plugin, Principled Volume improvements

Wk 9-10  [A] ReSTIR DI integrator plugin
         [B] Kerr geodesic plugin, FITS loader

Wk 11-12 [A] Neural radiance cache (promote Cline prototype)
         [B] HII emission-line plugin, sim-data volumes
         [D] Blender viewport render polish
```

By week 12: spectral everything, ReSTIR, at least one neural integrator,
Kerr + working astrophysical plugins, clean plugin architecture.

---

## How to use this plan

- **Starting a coding session?** Pick an open package from `../packages/`.
- **Launching a cloud agent?** See `../agents/copilot-cloud.md`.
- **Running Claude Code locally?** See `../agents/claude-code.md`.
- **Spinning up Ralph?** See `../agents/ralph-loop.md` and
  `../scripts/ralph_loop.sh`.
- **Overseer duty?** See `../agents/overseer.md`.

When you finish a package: mark it `done` in its file header, update
[`STATUS.md`](STATUS.md), open a PR.

---

## Simplicity tax

Any PR that adds framework, abstraction layer, or "future flexibility"
without a concrete caller **today** gets rejected. The test:

> A veteran CS engineer, reading this diff cold, should say "yeah,
> that's how I'd do it" — not "clever" and not "this should have been a
> function."

Applies to humans and agents equally. Overseer enforces in first-pass
review before merges.

## Visual fidelity vs performance

Top priority is visual fidelity. Performance competitive with Cycles in
simple enough scenes on a single RTX 5070 Ti is a floor, not a ceiling.
When these conflict:
1. Visual fidelity wins for offline renders (F12).
2. Performance wins for interactive viewport preview.
3. Correctness wins over both, always.
