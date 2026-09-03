# Astroray Next Stage Report

## 2026-09-03 SESSION HANDOFF — 8 packages landed/resolved; NEXT = architect re-vet (overnight queue exhausted)

**This session's landings (5 code PRs + 3 resolutions/docs):**
- **pkg225-S1 — hair ray-curve intersection, LANDED** (PR #670). The 2026-08-31
  "4/7, bug in curves.h" handoff was **wrong on the mechanism**: a standalone
  native harness proved the pbrt-ported primitive hits correctly (t, position,
  radial normal). The 4 failures were TEST-harness bugs (degenerate camera
  up-vector ∥ view dir; broken oblique geometry; a normal check ignoring
  `setFaceNormal`'s sign) + an **unfilled position AOV** (`SpectralPathTracer`
  never set `r.position` → `get_position_buffer()` was `Vec3(0)` for every
  shape; fixed). 7/7.
- **pkg225-S2 — CPU Principled Hair BSDF (Chiang 2016), LANDED** (PR #673).
  `include/astroray/hair_bsdf.h` (Mp/Np/Ap, header-only STL-free for GPU reuse)
  + `plugins/materials/principled_hair.cpp` (R/TT/TRT+residual, 3 σ_a
  parametrizations, view-dependent tangent frame, h=2·hair_v−1, coat→R-roughness).
  9/9 gates (energy ρ≤1 across β_m, absorption, colour, spectral render smoke).
  Research note: `docs/pkg225-hair-bsdf-research.md` (PR #672).
- **pkg219d — scalar parameter textures (op-VM → roughness/metallic/transmission/
  IOR), LANDED** (PR #674). Extends the `c_wfProgBinding` `__constant__`
  side-table (`matScalarProgId`/`matScalarTexId`) + CPU `DisneyPlugin::
  substituted()`. **Register gate byte-identical** (fleet `<0,…>` REG:254/
  STACK:3368/CONSTANT[0]:1716); 3/3 CPU+GPU parity tests; 297 regression;
  cpp-abi-guard APPROVE; **addon clean-rebuilt + headless-Blender node-chain
  render verified**. Known-bounded: metallic/transmission GPU parity approximate
  (closure lobe-mix baked at upload); roughness/IOR exact.
- **pkg210 — SUPERSEDED.** Premise stale: all 4 `terminateSecondary()` sites
  already refraction-gated (dielectric since pkg31, principled since pkg187).
- **pkg180 — CLOSED, no engine change.** The systemic ~12–20% Cycles-dim does
  NOT reproduce on the current build: common-linear-space A/B reads backdrop
  1.02 / world 1.01 / diffuse 0.997 / glossy 1.016 (all in `[0.90,1.10]`).
  Resolved by the intervening dielectric/metal/Principled parity work and/or a
  since-corrected harness view-transform. Full diagnosis in `docs/`.
- **Docs:** pkg219d fork-resolution + CPU-model pin; hair_v comment fix (Stage-1
  prose was inverted vs the code — v=0.5 is fiber centre).

**Fleet register baseline (unchanged, re-measured from the linked .pyd):
`stageShadeBucketedKernel<0,0,0,0,0,0,0>` REG:254 / STACK:3368 / CONSTANT[0]:1716.**
(pkg219d's scalar override rides the isolated `<HasProgram=true>` axis; the fleet
paid nothing.)

### UPDATE (later 2026-09-03): architect re-vet done (#675); pkg225-S3 landing
The architect re-vet ranked the next arc and filed Stage-3/4 implementation
detail. Since then:
- **pkg225-S3 (GPU curve geometry) — LANDED** (PR #676). Curves render on GPU
  (`GPRIM_CURVE` leaf, `gpu_curve_intersect.cuh`); the curve leaf is isolated
  behind `template<bool HasCurves>` so non-curve kernels are byte-identical
  (intersect 127/616, N3 61/272, shadow 108/584, fleet shade 254/3368/1716).
  GPU↔CPU parity + 25 regression pass; cpp-abi-guard APPROVE. Visually verified.
- **NEXT = pkg225-S4 (GPU hair BSDF).** Design pinned: `__noinline__` runtime-flag
  isolation (NOT a 9th shade axis), standalone `GMAT_HAIR_PRINCIPLED` branch.
  **HARD S3→S4 dependency:** S3 sets `hairV`/`uvTangent` in the curve leaf but
  does NOT persist `hairV` to the SoA `GPUWavefrontHitBuffers` — S4 must add a
  `hit_hair_v` lane (+ `loadHit`/`storeHit`) first, else the hair BSDF reads a
  stale centre value (cpp-abi-guard flagged this).
- **Research → detailed specs — DONE** (owner-directed 2026-09-03): deepseek-v4-pro
  web-research (opencode `architect` agent, webfetch+websearch; strict
  "web-verify or NOT FOUND, never fabricate" contract — 14/11/13 real searches,
  URL-cited, no fabrication) → notes `docs/pkg{127,211,136}-*-research.md`, then
  Opus spec-writers produced detailed design-choice specs, **all merged**:
  - **pkg127** — Specular Polynomials SMS-seed upgrade (**PR #679**). Highest-value
    bounded caustics-quality upgrade (drop-in SMS seed swap on landed pkg64). Ready
    to dispatch. Research fixed a wrong author cite + resolved the license
    (mollnn/spoly unlicensed → re-derive from the CC-BY paper + MIT cyPolynomial).
  - **pkg211** — per-bounce spectral MIS (**PR #677**). Prototype-first, **legitimate
    PARK outcome** (only ships if a CPU Stage-1 beats the pkg206 baseline by ≥10%);
    ray-differentials split to pkg211b. Architect's read: park unless a free slot.
  - **pkg136** — path guiding (**PR #678**). Renamed SVO→**SD-tree** (the honest
    structure call), CPU-first, gated GPU leg.
- **Long-tail parked:** pkg126/130/132/134/137 each a dedicated-day arc.

---

## 2026-08-31 SESSION HANDOFF — overnight round closed (12 PRs); pkg131 FULLY DONE both backends; NEXT = pkg225-S1 hair: fix localized straight-cylinder bug

**This round's landings (11 PRs + 1 direct-to-main docs commit):**
- **pkg131 — zero-knob adaptive sampling, NOW FULLY DONE** (PR #659 CPU leg
  + PR #665 GPU leg). GPU wavefront compacted active-pixel round
  (`stageRegenKernel`, gated `__constant__ c_wfAdaptive`, opt-in via pkg224's
  progressive sampler) HW-verified RTX 5070 Ti: byte-identical-off,
  unbiased-on, round loop engages; wavefront-diff + photon-caustic
  regression green. Deferred follow-up (not blocking DONE): sample-count
  AOV + addon UI knob removal.
- **pkg208** (#666 + #668) — chromatic-light-source dispersion oracle DONE:
  sodium_vapor chromaticity spread 0.0146 vs led_6500k 0.4917 (~33x, 3x
  margin asserted), CPU-only, CI-verifiable.
- **pkg209** (#664) — pkg187 Cauchy parity re-verify vs merged Cycles +
  MNEE citation fix, DONE, comment/doc-only.
- **pkg212** (#663) — wavefront ray-gen `+0.5f` pixel-center fix DONE,
  RTX-verified; GPU silhouette was ~0.4-0.6px off vs the CPU megakernel.
- **pkg218** (#667) — GPU spectral emission device upload DONE, HW-verified:
  fleet register probe byte-identical to baseline (REG:254/STACK:3368/
  CONSTANT[0]:1716), 9/9 CPU/GPU emission-colour parity tests within 5%.
  Closes the long-standing "GPU lamp colour is RGB-approximated" gap.
- **pkg207** (#658) — addon dispersion-socket probe DONE (prior-round
  landing, carried forward accurately).
- **pkg219 — tracker-hygiene fix, not new work:** #661 (prior round)
  correctly flipped this spec to DONE; an out-of-scope revert inside #664
  silently reverted it back to "open" (a real bug, not an owner decision).
  Restored the exact post-#661 DONE content this round — see STATUS.md for
  the full account.
- **pkg219d** — filed open (direct-to-main commit, no PR): the one genuine
  residual pkg219's completion audit surfaced (scalar param-textures —
  op-VM output wired only to Base Color, not roughness/metallic).
  Register-hostile GPU shade path; architect to detail before dispatch.
- **Docs infra:** #660 (status/tracker reconciliation), #662 (architect
  agent-ready specs + overnight routing) — both docs-only.

**Fleet register baseline unchanged: `stageShadeBucketedKernel<0,…>` REG 254
/ STACK 3368 / CONSTANT[0] 1716** (pkg131's GPU round and pkg218's emission
lookup are both off the REG:254 frame — side-table / trivial-store patterns;
re-measure from the actual `.pyd` before trusting, per usual).

---

### NEXT (highest-priority pickup): pkg225-S1 — hair ray-curve intersection, FIX the localized bug

**UPDATE 2026-08-31 (built + verified by the parent):** the WIP branch
`pkg225-s1-curve-intersect` now has TWO commits — the implementation plus a
recorded verify finding. It **compiles clean** and the analytic parity test
already exists (`tests/test_pkg225_curve_intersect.py`, a real closed-form
two-skew-lines gate). Result: **4 failed / 3 passed** — straight-cylinder hits
are wrongly REJECTED (returns no-hit) while the curved-strand smoke and all
miss cases PASS. So the miss logic + curved path work; the defect is specific.

The research (`.astroray_plan/docs/pkg225-curve-intersect-research.md`, its
"VERIFY FINDING" section) is genuinely rigorous — pbrt-v3 `Curve::Intersect`,
cite-verified; Catmull-Rom↔Bézier cross-checked vs Cycles. This is NOT
half-assed work; it has one localized bug.

**Next step is a focused DEBUG, not a rebuild:** the frame construction
(`include/astroray/curves.h:74-115`) is fine and for a straight strand
`L0==0` → `maxDepth==0`, so the bug is in the **depth-0 hit test
(`curves.h:217-282`)** — the endpoint edge functions, the closest-point `w`
(pbrt clamps it to [0,1]; check this port), the `distSq > hitRadius²` test, or
the `pc.z` t-bound — OR the Catmull-Rom→Bézier hull for a collinear strand.
Trace the perpendicular case (it aims through the strand centre, so the curve
point at w=0.5 has expected local (x,y)=(0,0); a nonzero distSq there localizes
it further). Get 7/7 + a math review vs pbrt-v3 `curve.cpp`, THEN merge Stage 1.
Only after that proceed to pkg225's later stages (shading, GPU) per the 6-stage
spec. Tier: Claude-last-line (the intersection math).

### Then: fresh grounded pickup queue (each Status verified this pass)

1. **pkg210 — companion wavelengths on specular reflection** (Pillar 3,
   open, filed 2026-08-19, register-sensitive). Claude-last-line: touches
   per-hit spectral state on the specular-reflection path, same risk class
   as the shade-kernel register work above.
2. **pkg180 — systemic Cycles-dim diagnosis** (open, dispatchable,
   diagnosis-first; no fix work until the offset mechanism is localized).
   Local Blender + RTX available for this.
3. **pkg211 — per-bounce spectral MIS + ray-differentials prototype**
   (Pillar 3, open, filed 2026-08-19, research-grade). May park if the
   research doesn't converge on a shippable design — treat as exploratory,
   not a committed deliverable.
4. **pkg219d — scalar parameter textures** (Pillar 5, open, filed
   2026-08-31, register-hostile). Needs an architect pass to detail the
   fork (new `GMaterial` scalar-param-texture field vs a side-table, same
   design question every recent shade-kernel feature has faced) before
   dispatch — do not implement ad hoc.
5. **Long-tail backlog, L-effort, no new urgency this pass** — pkg126
   (mesh-emitter unification), pkg127 (specular-polynomials SMS), pkg130
   (light-group emission decomposition), pkg132–137 (host-mapped memory
   fallback, SRF spectral sensors, LPE automata, SVO path guiding,
   partitioned-SMS ReSTIR caustics; pkg135 texture-overflow fallback is
   explicitly CONDITIONAL/dormant, do not implement pre-emptively). Audited
   2026-08-29 (#648) — still genuinely open, none superseded. Needs a
   dedicated day arc per package, not overnight-run shaped.
6. **De-prioritized below the Integration Milestone (owner-endorsed
   2026-08-03, unchanged):** pkg153 (wavefront-diff env-gate disposition,
   sub-percent tail), pkg155 (GPU absolute-slowdown investigation — the
   1.5s ceiling stays, memory `wavefront-perf-ceiling-owner-decision`, do
   NOT dispatch as a perf package), pkg173 (bounce-1 geometry-sampling
   parity, sub-percent tail). Re-enters the queue only if the paper turns
   out to require bit-level parity, or on explicit owner request.

**Paused, do not queue:** Pillar 4 (pkg45/pkg46/pkg48/pkg49/pkg50/pkg51/
pkg107 + `pkg218-spectral-colorimetry-fidelity.md` Thread B) — no unpause
directive issued; do not self-dispatch (memory `pillar4-on-pause`).

---

## 2026-08-30 SESSION HANDOFF — pkg224 + pkg201-S3 + pkg223b round closed; NEXT = pkg131 GPU leg

**This session's own landings (2 PRs, docs-only reconciliation otherwise):**
- **pkg207** (#658) — addon dispersion-socket probe now reads the merged
  Cycles 5.3 socket names (`Transmission Dispersion Scale`/`...Abbe Number`),
  short forms kept as fallback. Pure-Python, CI-gate only. **DONE.**
- **pkg131 session 1 of 3** (#659) — zero-knob adaptive sampling shared core
  (`include/astroray/sampling/adaptive_sampling.h`, cited to Cycles `main`,
  byte-exact) + CPU per-pixel leg wired into `Renderer::render`. **DONE for
  this slice; GPU leg + sample-count AOV + addon UI knob removal remain —
  see "NEXT" below.**
- Spec/tracker hygiene: flipped pkg207 (this session) and pkg220/pkg221/pkg222
  (code landed 2026-08-25 via #644/#645/#646, spec headers were never
  updated) to DONE. No engine/test changes.

**Prior session's landings, confirmed merged and still accurate (do not
re-verify): pkg224** (#657, progressive hash-Owen Sobol' sampler — the
pkg131 prerequisite, register probe byte-identical off-path), **pkg201-S3
items A** (#651, per-type bounce limits) **+ E** (#654, native caustic
toggles) both backends at REG 254, **pkg223b** (#655, Bump node, shared
`HasNormalPerturb` axis, no spill). Fleet register baseline unchanged since:
`stageShadeBucketedKernel<0,…>` **REG 254 / STACK 3368 / CONSTANT[0] 1716**
(pkg131's CPU-only session-1 diff and pkg224's off-path are both
byte-identical to this — re-measure from the actual `.pyd` before trusting,
per usual).

**NOTE (superseded by the 2026-08-31 entry above):** pkg131's GPU leg,
pkg212, pkg208/pkg209/pkg218 all landed since this entry was written; the
pickup queue below is historical, kept for the record.

### Then: fresh grounded pickup queue (each Status verified this pass)

1. **pkg225 — Hair rendering** (`packages/pkg225-hair-rendering.md`, Pillar 3,
   Status: open, filed 2026-08-29, 6-stage design). Owner-flagged gap: "hair/
   curve rendering is entirely absent" is one of the concrete reasons the
   Pillar 4 gate is judged NOT MET despite the Integration Milestone's
   original scope being complete (ROADMAP.md, 2026-08-29 owner assessment).
2. **pkg219 remainder / closure check** — 219a/b/c (coordinate+mapping,
   op-VM core, opcode fill-out) all LANDED (#640/#641/#642, HW-verified in
   the spec's own hardware-verification sections). The spec's own
   "deferred to pkg219d" note (Bump/Normal Map) was implemented as **pkg223**
   (#647) and **pkg223b** (#655) — both DONE. The parent spec
   `packages/pkg219-per-texel-shader-graph.md` Status line still reads
   "open (filed 2026-08-22; fork DECIDED + staged 2026-08-23)" and was
   **left as-is this pass** (out of this round's explicit verification list)
   — but the evidence strongly suggests it should flip to DONE next pass;
   flagged for the architect/owner rather than flipped unilaterally here.
3. **pkg212 — wavefront pixel-center half-pixel fix** (Pillar 5, open, filed
   2026-08-20). Small, well-scoped, no stated blocker.
4. **pkg208/pkg209/pkg210/pkg211** — Pillar 3 spectral-transport cluster
   filed 2026-08-19, all still open, no stated blockers: pkg208 (chromatic
   dispersion oracle, test-authoring only), pkg209 (pkg187 parity re-verify +
   doc refresh), pkg210 (companion wavelengths on specular reflection,
   register-sensitive), pkg211 (per-bounce spectral MIS + ray-differentials
   prototype). Not yet sequenced against each other — architect call.
5. **pkg218 — GPU spectral emission device upload** (`packages/pkg218-gpu-spectral-emission-device-upload.md`,
   open, filed 2026-08-22). Exact CPU↔GPU lamp-colour parity (memory
   `gpu-emission-is-rgb-approximated`); distinct from the Pillar-4-paused
   `pkg218-spectral-colorimetry-fidelity.md` Thread B (swappable CIE
   observer) — this one is NOT paused.
6. **pkg180 — systemic Cycles-dim diagnosis** (open, dispatchable,
   diagnosis-first; no fix work until the offset mechanism is localized).
7. **Long-tail backlog, L-effort, no new urgency this pass** — pkg126
   (mesh-emitter unification), pkg127 (specular-polynomials SMS), pkg130
   (light-group emission decomposition), pkg132–137 (host-mapped memory
   fallback, SRF spectral sensors, LPE automata, SVO path guiding,
   partitioned-SMS ReSTIR caustics; pkg135 texture-overflow fallback is
   explicitly CONDITIONAL/dormant, do not implement pre-emptively). Audited
   2026-08-29 (#648) — still genuinely open, none superseded. Needs a
   dedicated day arc per package, not overnight-run shaped.
8. **De-prioritized below the Integration Milestone (owner-endorsed
   2026-08-03, unchanged):** pkg153 (wavefront-diff env-gate disposition,
   sub-percent tail), pkg155 (GPU absolute-slowdown investigation — the
   1.5s ceiling stays, memory `wavefront-perf-ceiling-owner-decision`, do
   NOT dispatch as a perf package), pkg173 (bounce-1 geometry-sampling
   parity, sub-percent tail). Re-enters the queue only if the paper turns
   out to require bit-level parity, or on explicit owner request.

**Paused, do not queue:** Pillar 4 (pkg45/pkg46/pkg48/pkg49/pkg50/pkg51/
pkg107 + `pkg218-spectral-colorimetry-fidelity.md` Thread B) — no unpause
directive issued; do not self-dispatch (memory `pillar4-on-pause`).

---

## 2026-08-29 SESSION HANDOFF — round complete; next = pkg224 implementation

**Shipped & merged this session (7 PRs):**
- **pkg201-S3 item A** (#651) — per-type bounce limits (diffuse/glossy/transmission), CPU+GPU parity, OPTION-2 runtime compare. REG 254 unchanged (+8 STACK/+8 CONST accepted perf-neutral).
- **pkg201-S3 item E** (#654) — native caustic toggles (reflective/refractive), CPU+GPU parity, sticky diffuse-ancestor cull. REG 254 (+8 STACK/+8 CONST).
- **pkg223b Bump node** (#655) — height→normal perturbation, CPU+GPU parity, SHARED HasNormalPerturb axis (no new axis, no spill). Fixed the UV-upload-gate bug ([[uv-upload-gate-needs-new-normal-perturb-consumers]]) + texel-relative bump eps.
- **pkg126–137 status audit** (#648), **tracker+template hygiene** (#649), **pkg224 progressive-sampler spec** (#656) + Bump/filter_glossy/caustic research notes (#650/#652/#653).

**Parked (documented, follow-up filed):** pkg201-S3 **item C** filter_glossy — NOT a register spill; materials recompute GGX alpha inline at ~4 sites each (no single sd->closure point), so a faithful blur needs a per-material floored-roughness refactor ×5 materials ×2 backends. [[pkg201-filter-glossy-alpha-site-sprawl]].

**Fleet register baseline now: `stageShadeBucketedKernel<0,…>` REG 254 / STACK 3368 / CONSTANT[0] 1716** (measure from the actual .pyd, don't trust this).

**NEXT (owner-directed 2026-08-29): implement pkg224** — progressive (low-discrepancy) sampler for the wavefront, the prerequisite that unblocks pkg131 (blocked on white-noise RNG). Spec `.astroray_plan/packages/pkg224-progressive-sampler.md` (est. 2 sessions / ~6h) + research `.astroray_plan/docs/pkg224-progressive-sampler-research.md` are MERGED.

**OWNER CONFIRMED all three forks (2026-08-29) — DO NOT re-litigate, implement directly:**
- **(a) hash-Owen-scrambled Sobol'** (Burley 2020, "Practical Hash-based Owen Scrambling," JCGT 9(4); pbrt-v4 `FastOwenScrambler`, `src/pbrt/util/lowdiscrepancy.h`, Apache-2.0 — same license already cited in Astroray's `wavefront_rng.h`). NOT PMJ02. Owner: "prefer doing the hard work now so the foundations are solid for later."
- **(b) opt-in `__constant__` runtime flag** (pkg201-S3/pkg186/pkg223 pattern), NOT a compile-time axis. Default OFF = the existing PCG32 white-noise → byte-identical fleet shade kernel + CPU/GPU snapshot-parity gates. Fall back to an `if constexpr` axis ONLY if the register probe shows the runtime off-path spills the REG:254 kernel.
- **(c) GPU-only first.** CPU stays on `std::mt19937` (dozens of sites, no WavefrontRNG hook); CPU↔GPU progressive-sampler parity is a separately-scoped follow-up, filed if/when a snapshot gate needs the progressive mode.

**Implementation anchors:** swap the internal generator inside `WavefrontRNG::GenerateForDimension` (`include/astroray/sampling/wavefront_rng.h`, device mirror `wavefront_rng_device.h`) behind the flag — it already takes the exact `(pixel, sample, dimension, seed)` tuple Sobol needs. Sobol direction vectors → `__constant__`/side-table, NEVER `GMaterial`. **MANDATORY up-front cuobjdump probe** on the fleet `stageShadeBucketedKernel<0,…>` (current baseline REG 254 / STACK 3368 / CONSTANT[0] 1716 — re-measure from the actual `.pyd`) BEFORE feature code; the sampler is drawn at primary-ray gen (`stage_init.cu`) AND every BSDF/NEE draw in the shade kernel, so keep per-draw cost to integer ops + the direction-table read. Then build pkg131 adaptive sampling on top. `.pyd` was rebuilt at end of the 2026-08-29 session (current w.r.t. this HEAD) — verify `astroray.__file__` + `cuobjdump --list-elf` sm_120 before the first GPU gate anyway (memory `stale_pyd_locations`).

---

## 2026-08-26 SESSION HANDOFF — next-session agenda (owner-directed)

**Landed this session:** pkg223 (GPU tangent-space normal maps, PR #647 merged
be7cbec). Register probe CLEAN — the fleet paid nothing (normal-map data rides the
`c_wfTexBinding` side arrays; `GMaterial` stays 640 B) so there was no spill to fix.
Also fixed a latent CPU arbitrary-frame bug (→ UV-aligned Mikk-TSpace). Two memories
banked: `shade-axis-side-table-avoids-spill`, `pkg131-blocked-on-progressive-sampler`.

**Decisions banked (do not re-litigate):**
- **pkg201-S3 → OPTION 2** (owner, 2026-08-26): per-type bounce counters as a
  **runtime SoA comparison** in the shade kernel (5 counters in path state; cheap
  `if (depth[type] >= limit[type])` continuation check), **probe-first**. Only if
  the probe shows a spill on the fleet default do we fall back to a compile-time
  axis for the specific branch that spills — this AVOIDS the 8th-axis 256-kernel
  compile explosion (pkg223's 7th axis already put `stage_advance.cu` at 128
  specializations / ~9 min). Sets the pattern for items C (filter_glossy) and E
  (caustic toggles) too.
- **pkg131 → BLOCKED** on a progressive sampler: the wavefront RNG is PCG32
  white-noise, no PMJ/Sobol prefix property (memory
  `pkg131-blocked-on-progressive-sampler`). Needs a Sobol/PMJ sampler prereq or an
  architect re-scope to a white-noise first-cut — **surface the fork to the owner**,
  do not silently implement on white noise.

**NEXT-SESSION AGENDA (three tracks):**

1. **Open engine work next in line.** (a) pkg201-S3 **item A** via option 2
   (per-type bounce counters), threading the 5 limits into `cuda_wavefront_render`
   (sweep call sites: `blender_module.cpp:1863`, the ReSTIR variant, tests) — up-front
   `cuobjdump -res-usage` probe on the CURRENT-main 128-kernel fleet baseline BEFORE
   feature code, invest-to-fix on spill. Then items **C** (filter_glossy roughness
   accumulator) and **E** (caustic-toggle specular-path flag), same probe-first shape.
   (b) **Bump** node — the pkg223 follow-up (needs height-texture screen-space/analytic
   derivatives; register-hostile; file as pkg223b). (c) pkg131 progressive-sampler
   decision above.

2. **Review pkg126–137** (owner: fundamental at one point, must not be forgotten if
   still relevant). This block is the Disney/dielectric-rough/VNDF/thin-film/
   multiscatter-LUT/mesh-emitter/light-groups/adaptive-sampling era. For EACH:
   cross-check against merged PRs + STATUS.md, then set its spec `**Status:**` to
   done / superseded / dropped / still-open with a one-line reason. Several likely
   landed or were superseded by later packages (e.g. pkg131 is blocked, pkg129
   Turquin LUTs, pkg138/149/150/151 dielectric-rough series) — do not leave them
   ambiguous.

3. **Project-tracker + package-template hygiene** (Google Sheets tracker
   `https://docs.google.com/spreadsheets/d/1u94CR7njH-LdyGQxKT0vKr56uHEVAVaqZGxVaIFUepg`;
   script `Google_Apps_Script.txt`). Three concrete fixes:
   - **Pillar frontmatter (tracker mis-parses ~19 specs).** `**Pillar:**` must be a
     BARE number 1–5. Offenders + fix:
     - "Integration Milestone (…)" → tracker extracts NOTHING: pkg175, pkg176, pkg177,
       pkg200, pkg201, pkg202, pkg203, pkg204, pkg207, pkg209, pkg212, pkg213 →
       **Pillar 5** (Production polish / Blender parity).
     - "Blender/DCC integration (integration-first…2026…)" → tracker extracts **"2026"**:
       pkg219, pkg223 → **Pillar 5**.
     - EMPTY pillar: pkg215, pkg216 (project-index tooling → 5 or infra convention),
       pkg218 (spectral → **Pillar 2**).
     - Infra with no numeric pillar: `pkg-add-cuda-syntax-ci` ("0 (Infrastructure)"),
       pkg205 ("Infrastructure / test hygiene"). Pick a convention — the script only
       tallies 1–5, so infra can stay blank; decide and document.
   - **Status audit.** Some specs still read open/partial that are really done /
     superseded / dropped — cross-check each vs merged PRs and flip (pairs with track 2).
   - **Timeline sheet is EMPTY — fix the script.** `refreshTimeline_` regex requires
     `\n- **YYYY-MM-DD` but STATUS.md entries are `**YYYY-MM-DD (…)` bold-date
     paragraphs (no leading `- `, no `## Changelog` anchor) → only 2 stray lines match.
     Replace the regex in `Google_Apps_Script.txt` with:
     `const re = /(?:^|\n)\*\*(\d{4}-\d{2}-\d{2})([\s\S]*?)(?=\n\*\*\d{4}-\d{2}-\d{2}|\n## |$)/g;`
     (group 2 = entry body; the existing whitespace-collapse + 600-char truncation
     still apply). The `## Changelog` slice becomes a harmless no-op.
   - **Prevention.** Update `.astroray_plan/packages/TEMPLATE.md` to mandate
     `**Pillar:** <1-5>` as a bare number, and optionally harden `parsePackageMd_`
     (map a leading "integration"→5, "infrastructure"→blank) as defense-in-depth.

**Repo state for kickoff:** `.pyd` in `build_cuda/Release` is current w.r.t. source
(HEAD advanced only via docs commits since the pkg223 build) but the stale-guard hook
will flag it — rebuild before any GPU verification (memory `stale_pyd_locations`).

---

**Date:** 2026-08-25 (FRESH ARCHITECT-LED planning pass — autonomous-session
open). Regenerates the 2026-08-23 report (pkg219a/b/c + pkg217 have since LANDED —
#640/#641/#642/#643). Canonical pickup queue for the orchestrator / dispatch-next.
Every item is grounded in the live project index or a cited in-code finding; grep
`^**Status:**` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`).

> Strategy: `ROADMAP.md`. Full state: `STATUS.md` (top entry 2026-08-21→22).

---

## 0. Pending-state facts the orchestrator must carry (NOT tasks to redo)

- **Stale `.pyd`:** rebuild `build_cuda` before ANY GPU verification this session
  (memory `stale_pyd_locations`, `incremental-build-signature-staleness`; verify
  `astroray.__file__` canonical + `cuobjdump --list-elf` sm_120 before trusting a
  gate). CI has no GPU — never declare a caustic/normal-map round clean on CI alone
  (memory `ci_has_no_gpu_runtime_blindspot`).
- **pkg214fix** (sodium/mercury energy-normalization; PR #629 was HW-FAIL) may still
  be in flight on branch `pkg214fix`. It **BLOCKS pkg222** (same generator +
  `profiles.bin`). Confirm it landed before dispatching pkg222; re-verify sodium AND
  mercury together (peak-vs-energy normalization coupling).
- **Pillar 4 remains PAUSED** (pkg45/46/48/49/50/51/107, incl. pkg218 Thread B — the
  swappable observer / camera response function). Surface the unpause decision to
  the owner; do not self-dispatch it. pkg222 extracts ONLY the pkg218 Thread A data
  fix (spectral correctness), which is not Pillar-4-paused.

---

## 1. State in one screen

- Spectral milestone + Blender-integration sweep shipped. Shader-node compatibility
  advanced hard: **pkg219a (coordinate/Mapping unification), pkg219b (bounded op-VM
  core), pkg219c (opcode fill-out) all LANDED** (#640/#641/#642). **pkg217 caustics
  LANDED via Path A** (#643) — but see §2: the caustic wiring exposed two deeper
  physics bugs the wiring fix did NOT address.
- Owner live priorities: **Blender shader-node compatibility, caustics, Cycles +
  CPU/GPU parity, opportunistic perf** (1.5s perf ceiling STAYS — no dedicated perf
  packages, memory `wavefront-perf-ceiling-owner-decision`).
- **New this pass (two caustic physics findings, CONFIRMED IN CODE):** the
  now-wired GPU caustic (a) rebuilds a byte-identical photon map every iteration so
  its noise never averages (→ pkg220), and (b) samples photon λ uniformly and
  deposits SPD-blind power so a narrow-line lamp throws an impossible rainbow caustic
  (→ pkg221). These are separate from pkg217's addon-wiring fix.

---

## 2. Prioritized set for THIS session (4–7, ordered)

Tier key: **grunt** = open-weight via `delegate`, evidence-verified; **impl** =
`package-implementer`; **dv4** = deepseek-v4-pro / sonnet (well-specified, gated);
**Claude** = last-line judgment (register/ABI/parity); **hw** = `hardware-verifier`.

### FILED THIS PASS (thorough, self-contained specs — dispatch-ready)

1. **pkg220 — Progressive GPU photon-caustic seed.** *What:* thread a per-iteration
   seed into `kEmitSceneCaustic`/`buildCausticAim` so successive photon maps are
   independent and the caustic averages ~1/√N. *Why now:* caustics are permanently
   grainy — a visible quality bug that the pkg217 wiring fix newly exposed. *Effort:*
   S–M. *Tier:* **dv4** (plumbing + a clean convergence gate; register-neutral).
   *Gating:* none. **Cheapest high-value win — dispatch first.**

2. **pkg221 — Photon λ importance-sampled from the light SPD.** *What:* draw photon
   wavelengths ∝ the emitting light's SPD (CDF built host-side, CPU+GPU), weight the
   deposit so white stays white and narrow-line lamps throw line-colored caustics.
   *Why now:* emission-line dispersion is physically impossible today (SPD-blind,
   engine-wide). *Effort:* M–L. *Tier:* **dv4** + `cite-algorithm` (PBRT spectral IS)
   + `cycles-parity-reviewer`. *Gating:* shares `kEmitSceneCaustic` with pkg220 —
   land pkg220 first, rebase this on top.

3. **pkg222 — Atomic-line lamp SPDs: cited, chromatically-correct.** *What:* re-derive
   preset atomic-line lamp line intensities from NIST/measured data, regenerate
   `profiles.bin`, audit every lamp's chromaticity (mercury magenta→greenish-white).
   *Why now:* every atomic-line lamp renders the wrong color; makes pkg221's
   emission-line dispersion *correct-colored*. *Effort:* M (data, no engine C++).
   *Tier:* **dv4** (citation + A/B render discipline). *Gating:* **BLOCKED by
   pkg214fix** (same generator) — confirm it landed first.

4. **pkg223 — Normal Map node (pkg219d part 1).** *What:* tangent-space normal-texture
   perturbation of the shading normal, CPU+GPU, behind `<bool HasNormalPerturb>`.
   Bump deferred. *Why now:* normal maps are ubiquitous and silently do nothing today
   — the biggest remaining shader-node usability gap after pkg219a-c. *Effort:* M–L.
   *Tier:* **dv4** implement, but the **GPU shade-kernel register budget is
   Claude-last-line** — HARD `cuobjdump` REG probe gate + `cpp-abi-guard` + Claude
   review before merge; spill → escalate. *Gating:* reuses pkg219a coordinate path.

### EXISTING OPEN WORK — weighed, sequenced behind the above

5. **pkg201 Stage 3 — per-type bounce counters + `filter_glossy` + native caustic
   toggles.** Closes the last register-hostile pkg200 honour-matrix rows. *Effort:* L.
   *Tier:* **Claude** (register-hostile). *Note:* the caustic-toggle row now LOGICALLY
   couples to the landed pkg217 + the new pkg220/221 caustic work — wire the toggle to
   the existing pipeline, don't reimplement. Non-caustic rows (bounce counters,
   filter_glossy) can go independently as a **dv4** slice. Pick up behind 220–223.

6. **pkg131 — Zero-knob adaptive sampling, wavefront leg.** Long-standing; convergence
   quality (not raw perf — respects the ceiling). *Effort:* L. *Tier:* impl/dv4.
   *Gating:* none; fill a free slot behind Themes above.

### NOT this session (surface to owner)

- **pkg218 Thread B** (swappable CIE observer / camera spectral-sensitivity) —
  Pillar-4-paused; research-grade capability, owner said "not the current main
  focus." Leave paused; do not dispatch. pkg222 already carves out Thread A.
- **pkg217 SMS-NEE-cull quality upgrade** — the sharper forward-caustic method noted
  in pkg217's CORRECTION; only if the photon caustic (post-220/221) shows residual
  quality limits. Do not pre-empt.

---

## 3. Real forks for the owner (not an artificial ballot)

- **Caustic depth:** pkg220 (decorrelate) + pkg221 (SPD λ) make the *existing* photon
  caustic converge and be spectrally correct — cheap, high-value, dv4-implementable.
  The alternative "sharper" path (SMS-NEE-cull, pkg217's deferred design) is L,
  register-hostile, and Claude-only. **Recommendation:** ship 220+221 first; only
  invest in SMS if their converged quality proves insufficient. Owner: agree, or go
  straight for SMS?
- **pkg222 vs pkg214fix ordering:** both touch `build_spectral_profiles.py` /
  `profiles.bin`. pkg222 is BLOCKED on pkg214fix landing. If pkg214fix has stalled,
  the owner may want to fold the mercury green-line fix INTO the pkg214fix branch
  rather than a separate pkg222. **Flag:** is pkg214fix still open?
- **pkg223 register risk:** Normal Map perturbs the REG:254 shade normal. If the probe
  spills despite `<bool HasNormalPerturb>` isolation, do we accept a bounded non-map
  STACK cost, or hold the feature? Default: hold + escalate (never ship a fleet-wide
  regression).

---

## 4. Top items to dispatch first (with routing)

1. **pkg220** → `package-implementer` (dv4 tier). Independent, cheapest high-value
   caustic fix; clean convergence gate. Rebuild the stale `.pyd` first.
2. **pkg221** → dv4 implementer + `cite-algorithm` + `cycles-parity-reviewer`, AFTER
   pkg220 (shared kernel).
3. **pkg223** → dv4 implementer, HARD REG-probe gate + `cpp-abi-guard` + Claude
   review before merge.
4. **pkg222** → dv4 implementer — ONLY after confirming pkg214fix landed.

Breadth research (NIST line intensities for pkg222, extra caustic/normal-map parity
scenes, Cycles Normal Map handedness confirmation) → `delegate` open-weight,
evidence-verified, scoped to ONE narrow deliverable each (memory
`delegate-grunt-budget-bound-tight`).

---

## 5. Specs filed this pass

- **pkg220** — `packages/pkg220-caustic-per-iteration-seed.md` (Track A, dv4).
- **pkg221** — `packages/pkg221-photon-wavelength-spd-importance-sampling.md`
  (Track A, dv4).
- **pkg222** — `packages/pkg222-atomic-line-lamp-spd-chromaticity.md` (Track A, dv4;
  extracts pkg218 Thread A; BLOCKED on pkg214fix).
- **pkg223** — `packages/pkg223-normal-map-node.md` (Track A, dv4 + Claude gate;
  pkg219d part 1, Bump deferred).
