# pkg198 — Light-path-expression render passes (diffuse/glossy/transmission direct+indirect, emission, environment)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** Stage 1 (CPU classification) — done (PR #614, 2026-08-14 — sum-to-beauty rel_L1
0.0000, per-channel ratio 1.000/1.000/1.000; isolated-lobe leak <1e-2). Stage 2 (GPU wavefront
mirror + register probe) — register probe **PROCEED** (2026-08-15, branch `pkg198-s2-probe`;
fleet `<…,false>` shade kernel byte-identical 254/3352/1700, pass-AOV kernels add zero
STACK/no tier crossing — see "Stage 2 REGISTER PROBE" evidence block below); full mirror
**open, ready to dispatch**.
**Estimated effort:** Stage 1 = M (landed). Stage 2 = L (register-hostile — the up-front probe
decides whether it ships at all).
**Depends on:** Stage 2 depends on Stage 1 (this PR — the CPU reference to mirror) and pkg197
(first-hit guide AOVs — its intersect-stage capture + `__constant__` binding is the template);
[[wavefront-shade-kernels-register-saturated]]; [[closure-graph-lobe-count-spills-fused-kernel]].

---

## Why this exists (premise CORRECTED 2026-08-14 — implementer finding)

The package was filed as "the GPU half of a CPU↔GPU light-path-AOV parity gap: passes work on
CPU, are black on GPU." **That premise was false.** Verified on `main` (grep, whole repo, code
files only):

- `SampleResult.passes` (`include/raytracer.h:1731`) was zero-initialised and **no integrator or
  BSDF ever wrote to it** — the single reference outside the struct definition was the read at
  `include/raytracer.h:3228` (`sPass = ir.passes`), accumulated into `cam.renderPassBuffers`.
- The default integrator `spectral_path_tracer.cpp::sampleFull` filled color/albedo/normal/depth
  but left `r.passes` zero; `pathTraceSpectral` took no pass-output parameter and had no
  first-bounce-lobe / direct-indirect / emission-environment classification.
- The two tests touching these passes used **mocked** renderers returning constant buffers.

So `PASS_DIFFUSE_DIRECT … PASS_ENVIRONMENT` were plumbed end-to-end (registry, Python bindings
`module/blender_module.cpp:2241-2257`, addon viewport selector) but returned **black on BOTH
backends**. This was a whole-feature gap, not a GPU-parity gap — which makes it more valuable to
fix, not less. Coordinator decision (2026-08-14): **Option A**, staged like pkg199 — build the
CPU classification first (Stage 1), then mirror it on the GPU wavefront (Stage 2).

---

## Stage 1 — CPU light-path pass classification  ✅ DONE (this PR)

Implement the classification in the default spectral path tracer so the existing plumbing lights
up: first-bounce lobe category (diffuse/glossy/transmission), direct vs indirect split, and
emission/environment tagging — **citing Cycles** `kernel/film/light_passes.h` +
`integrator/shade_surface.h` (Apache-2.0). Research notes:
`.astroray_plan/docs/pkg198-lightpath-pass-classification-research.md`.

Design (adapted to Astroray's granularity — single combined `evalSpectral`, no per-closure
split, so the coarser single-path-label variant of the Cycles model is used):
- `pathTraceSpectral` gained an optional `outPasses` accumulator; every `color += X` is paired
  with exactly one `passes[p] += X` (total partition → Σpasses == beauty EXACTLY in spectral
  space). Passes carry XYZ (same convention as `SampleResult.color`) and are converted to linear
  sRGB in the render loop with the same matrix as beauty, so the invariant holds in linear sRGB.
- Category locked at the first BSDF interaction (Cycles locks pass weights at bounce 0):
  TRANSMISSION if the sampled `wi` crossed the surface (geometric sign test — no distance/
  sentinel, per [[occlusion-sentinel-as-distance-class-of-bug]]); else GLOSSY for a delta/mirror
  reflection or glossy material; else DIFFUSE. Direct = light gathered before that lock; indirect
  = after. Directly-visible emission → `PASS_EMISSION`; directly-visible background →
  `PASS_ENVIRONMENT`; both fold into `<firstCat>_INDIRECT` after a bounce.

Stage 1 acceptance — all met:
- [x] Σ(light-path passes) == beauty (LINEAR) on an all-lobe scene: per-channel ratio
      `[1.000, 1.00000001, 1.00000001]`, pixelwise rel_L1 `0.0000`.
- [x] Isolated-lobe sanity: pure-diffuse → glossy/transmission < diffuse·1e-2 (measured 0.0);
      metal → diffuse < glossy·1e-2 (measured 0.0); glass → transmission carries the refraction.
- [x] Emission and environment passes populate for directly-visible emitters/background.
- [x] Real-binding tests (`tests/test_pkg198_lightpath_passes.py`) replace reliance on the mocks
      (mocks kept); the two pre-existing `xfail`-gated pass tests in `test_python_bindings.py`
      un-xfailed and passing.

## Stage 2 — GPU wavefront mirror + register probe  (OPEN, probe-first, may-park)

Mirror the Stage-1 classification on the GPU wavefront so the passes agree CPU↔GPU on the
default backend. This is the register-hostile half.

### MANDATORY FIRST STEP — decide feasibility before building
1. Design the GPU pass-accumulation layout against the Stage-1 CPU reference + Cycles film model.
   Per-path pass accumulators are per-hit live state in the shade kernel that is already
   REG-254-saturated. Study whether some passes can be captured OFF the shade kernel (pkg197's
   intersect-stage capture; emission/environment may be accumulatable outside shade).
2. Register-probe the minimal version — carry pass accumulators as SoA global-memory scatter
   (per-pixel pass buffers written incrementally per bounce), so the shade kernel holds pointers,
   not ~10 accumulators. Isolate behind a compile-time `HasLightPassAOVs` axis (pkg184/pkg189
   if-constexpr) so the pass-less fleet specialization is byte-identical by construction.
3. **HARD gate:** `stageShadeBucketedKernel<…,false>` (pass-less) stays at the verified fleet
   baseline **REG 254 / STACK 3352 / CONSTANT[0] 1700** — confirm on the FINAL linked `.pyd` via
   `cuobjdump` (sm_120 confirmed via `--list-elf` first; never `ptxas -v`). NB: **3352 is
   correct**; the earlier `3608` figure in this spec was the stale pre-pkg184/4-axis number —
   pkg190's HW verification re-confirmed 3352 independently.
4. If even the global-scatter form spills the pass-less specialization or regresses non-AOV perf,
   **STOP and park with the cuobjdump evidence** — a clean park is a valid outcome (pkg194
   discipline). The value (a compositor power-user feature) does not justify a fleet-wide
   regression on every GPU render.

### Stage 2 scope (only if the probe clears)
- Fill the same passes on the wavefront, matching Stage-1 CPU semantics; copy-back alongside the
  beauty/guide plumbing established by pkg197 (one path, do not fork).
- Parity gate: CPU vs GPU per-pass per-channel mean-ratio (not SSIM) on the Stage-1 scenes; GPU
  beauty must still equal the sum of the GPU passes (energy closure).
- Non-AOV GPU renders show no perf regression (min-of-N, burn-in — [[gpu-perf-ab-clock-drift]]).
- Headless Blender 5.1: passes populate on the GPU backend and round-trip through the compositor.
- **RTX 5070 Ti hardware gate** ([[ci_has_no_gpu_runtime_blindspot]]), bound to HEAD.

## Hard non-goals (both stages)
- **No lobe-array shrink or shared live-state widening** to buy register room (pkg178/pkg184).
- **No volume passes** until pkg199 lands GPU volumes (`PASS_VOLUME_*` left untouched).
- **No cryptomatte rework** (pkg159) and **no first-hit guide AOVs** (pkg197) — light-path split
  only.
- **Do not force Stage 2 to ship.** A clean park with evidence is a valid, expected outcome.

---

## Hardware verification 2026-08-14 (independent re-measure, PR #614, Stage 1 only)

**Verifier scope:** PR #614 (pkg198 Stage 1 -- CPU light-path pass classification,
`include/raytracer.h` + `plugins/integrators/spectral_path_tracer.cpp`). Stage 2
(GPU wavefront mirror) not started; this verification's GPU-side concern was
**regression only** (raytracer.h is CUDA-reachable).

**Hardware/software:** RTX 5070 Ti, driver 610.47, Windows 11 Enterprise
10.0.26200, CUDA 12.8 (nvcc V12.8.61), sm_120 (native), MSVC 14.44.35207.
Worktree: `Astroray-pkg198` @ `c4c77a9efe25cb4fd79e6f7dd641bf98659cdcab`
(= PR #614 head, confirmed via `gh pr view`). No rebase/push performed
(branch freeze honored).

### 1. Build / staleness
Foreground rebuild via `build_cuda_worktree.bat` -- exit clean, `[pkg183] arch-verify OK:
astroray.cp313-win_amd64.pyd embeds sm_120 (embedded=[sm_120])`. `.pyd` was already
up to date (mtime 07:49:42 postdates the last code commit 060f6c3 @ 07:31:58; the two
commits after that are test/doc-only). Incremental rebuild was a no-op (unchanged
mtime/size) -- confirms nothing was stale.

### 2. Register gate -- `stageShadeBucketedKernel<false,false,false,false>`
Independently re-measured via `cuobjdump -res-usage` on the linked `.pyd`
(sm_120 cubin confirmed via `--list-elf` first):

```
REG:254 STACK:3352 SHARED:0 LOCAL:0 CONSTANT[0]:1700 TEXTURE:0 SURFACE:0 SAMPLER:0
```

**Byte-identical to the corrected baseline (254 / 3352 / 1700).** raytracer.h's Stage-1
change had zero device-side impact -- confirms the spec's `3608`->`3352` correction
independently (matches pkg190's prior re-confirmation cited in the PR's spec edit).


### 3. `tests/test_pkg198_lightpath_passes.py` (7/7 pass) -- re-measured verbatim

```
test_all_light_path_passes_readable PASSED
test_sum_to_beauty_linear: sum-to-beauty per-channel ratio = [1.00000013 1.00000011 1.00000012], rel_L1 = 0.0000  PASSED
test_isolated_diffuse: diffuse-scene: d_direct=0.0089 d_indirect=0.0015 glossy=0.000000 trans=0.000000  PASSED
test_isolated_glossy: glossy-scene: glossy=0.0358 diffuse=0.000000  PASSED
test_isolated_transmission: transmission-scene: trans=0.0342  PASSED
test_emission_pass: emission-scene: emission=0.8696  PASSED
test_environment_pass: environment-scene: environment=0.3685  PASSED
7 passed in 0.87s
```

Close to but not bit-identical to the PR's claimed numbers (ratio
`[1.000, 1.00000001, 1.00000001]`; transmission 0.0344; emission 0.8744;
environment 0.3692) -- **expected**, not a discrepancy: none of these tests call
`set_seed()`, and seed 0 is the engine's random-device sentinel
([[seed-zero-is-random-sentinel]]), so each run draws an independent MC sample.
Both runs agree well within MC noise on a scene of this sample count; the sum-to-beauty
invariant (the load-bearing gate) reproduced at rel_L1 0.0000 both times.


### 4. Beauty byte-identity / no-math-change claim
No Python-level "passes requested" toggle exists for Stage 1 -- `spectral_path_tracer.cpp`
always allocates and fills the `passSpectra` accumulator (the `outPasses` pointer is
optional only at the `pathTraceSpectral` C++ signature level; other call sites like
`neural_cache.cpp` pass nullptr and pay only the branch cost). So "requested vs not
requested" beauty-identity has no in-repo toggle to test.

Instead cross-checked pre-PR `main` (build `4643de3`, `.pyd` mtime confirmed current)
vs this PR's build, same scene/seed (1337), CPU path_tracer, 16spp/depth5, 64x64:
mean **0.07392490150800768** (pkg198) vs **0.07392490150755293** (main); max abs
pixel diff **7.45e-9** (2 of 12288 float32 components differ, both float32-ULP scale).
**Not literally bit-identical, but ULP-level only** -- consistent with the PR's claim of
"no RNG calls, no beauty math changed"; the observed diff is attributable to compiler
instruction-scheduling/FMA differences from the code-shape change, not a semantic delta.

### 5. Firefly/clamp partition-leak probe
Rendered a high-variance dielectric-caustic-prone scene (glass sphere + Lambertian
floor + a 400-intensity point light) at 4 spp / depth 8 (64x64), WITH passes read back:
- beauty mean 0.09024327712053075, max 0.7697820663452148
- Sum(passes) mean 0.09024513699479793, max 0.7697820924222469
- per-channel ratio **[1.00002128, 1.00002111, 1.00001953]**, rel_L1 **2.0704e-05**,
  max abs pixel diff **0.0019** (well inside the test suite's `atol=0.03` / `rel_L1<0.03`
  gate). No NaN/Inf in either buffer. **No partition leak found** -- the classic
  firefly-clamp-applies-to-beauty-but-not-passes failure mode did not manifest.


### 6. GPU regression slice (hardware)
`test_gpu_multiwavelength.py` (6/6), `test_pkg55_c3_wavefront_nonvisible.py` (4/4) -- **10/10
passed**, no change vs pre-PR baseline behavior. GPU wavefront path confirmed untouched.

### 7. Broader regression re-measure
- `tests/test_python_bindings.py`: **78 passed, 10 xfailed** (88 collected total). The PR
  body states "95 passed... the 9 that fail under --runxfail" -- **this PR-body figure does
  not match independent re-measurement** (main and this branch both collect 88 tests
  total in this file; 78 pass, 10 are pre-existing xfails, not 9). This looks like a
  reporting/count error in the PR description, not an actual regression: the 3 un-xfail
  diffs are verified correct (`git diff` shows exactly 3 `@pytest.mark.xfail` lines
  removed, all 3 now pass), and 0 previously-passing tests newly fail. Flagging the
  number mismatch per "numbers verbatim" -- does not change the verdict.
- Furnace/energy/reflection surface suite (`test_material_properties`,
  `test_disney_reflection_not_black`, `test_dielectric_glass_furnace`,
  `test_disney_opaque_furnace`, `test_pkg122_light_energy_calibration`): **35 passed, 3
  skipped, 2 xfailed** -- matches the PR's claimed "35 passed" exactly.


### 8. Visual inspection
Re-rendered the all-lobe scene at 256x256/128spp for a legible decomposition (the
repo's own 48x48 test PNGs are too small to inspect reliably). All 8 light-path
passes + emission + environment + Sum(passes) reconstructed:
- `diffuse_direct`/`diffuse_indirect`: floor only, metal/glass spheres correctly
  silhouetted black (non-diffuse).
- `glossy_direct`: isolates just the metal sphere's specular highlight from the point
  light -- correct.
- `glossy_indirect`: metal sphere's full environment reflection AND the glass sphere's
  Fresnel (mirror) reflection highlight -- correct per the documented "delta reflection
  off dielectric -> glossy" classification choice.
- `transmission_direct`: pure black -- correct (NEE never fires through a delta/glass
  lobe, so this pass is always empty by construction, as documented).
- `transmission_indirect`: isolates exactly the glass sphere's refracted content -- this
  is precisely the "transmission pass shows the glass content only" check the dispatch
  asked for, confirmed.
- `emission`: isolates only the emissive sphere, no leakage.
- `environment`: shows only unoccluded background, correctly punched out by every
  occluder including the emissive sphere's silhouette.
- Sum(passes) reconstruction is visually indistinguishable from beauty.
- No fireflies, no banding/quantization artifacts, no NaN pixels (checked numerically
  too), no mode regressions observed in any pass.

### Verdict
**HW PASS.** Register gate byte-identical, all functional/regression suites reproduce
(with one PR-body test-count discrepancy noted above, not a gate failure), sum-to-beauty
holds under both nominal and firefly-stress conditions, GPU wavefront path unaffected,
visual decomposition is physically plausible and clean. Merge decision left to the
architect/reviewer -- this is a measurement report only.

---

## Stage 2 REGISTER PROBE — evidence + verdict (2026-08-15, branch `pkg198-s2-probe`)

**Verdict: PROCEED with the safe design.** The register-hostility that gated this
package does NOT manifest. Both the fleet pass-less shade kernel AND the pass-AOV shade
kernels stay byte-identical to their respective pre-probe baselines: zero STACK delta,
zero register-tier change, no occupancy crossing. The isolation axis protects the fleet
by construction (proven, not assumed).

### Probe design (the measured shape — this is the design the full mirror should ship)
Mirrors pkg186 (texture) / pkg197 (guide) / pkg199-S2 (volume) fleet-isolation exactly:
1. **New compile-time axis** `bool HasLightPassAOVs` on `stageShadeBucketedKernel` /
   `shadePathSlot` (5th template bool, defaults false → all existing call sites unchanged).
2. **Pass output pointers live in a `__constant__` binding** (`GWavefrontLightPassBinding`
   via a new `c_wfLpBinding` symbol), NOT in the kernel signature and NOT in
   `GPUWavefrontState`. This is the load-bearing choice — the pkg186 lesson is that a
   signature pointer bumps CONSTANT[0] and costs the fleet `<false,…>` kernel +STACK even
   when the code is `if constexpr`'d out. Constant memory keeps the pass-less signature at
   its pre-probe footprint. `passAccum == nullptr` (every non-AOV driver) ⇒ the whole
   partition compiles out.
3. **Per-slot global-scatter accumulators** (`lpAccumulate`): the shade kernel holds only
   the constant-mem base pointer + the already-live spectral contrib, RMW-adds into global
   memory. No per-path register accumulators → adds memory traffic, not live registers.
   Since REG is already pinned at 254, "no new live registers" is exactly what keeps STACK
   flat.
4. **Representative shade-kernel work exercised by the probe:** (a) first-bounce lobe
   category lock at bounce 0 (Stage-1 geometric sign test → `firstCat[idx]`), and (b) the
   immediate/non-deferred NEE `color +=` site mirrored into `passAccum` (read category,
   compute direct/indirect pass index, scatter-add). Both are non-dead (global stores with
   side effects; `c_wfLpBinding` is runtime-set so the compiler cannot fold it away). Two
   `<…,true>` specializations were forced into the linked cubin via a reference sink.

### Measured table — cuobjdump `-res-usage`, FINAL LINKED `.pyd`
- `.pyd`: `Astroray-pkg198s2/build_cuda/Release/astroray.cp313-win_amd64.pyd`, mtime
  2026-08-15 07:38, built via `build_cuda_worktree.bat` (exit 0, arch-verify OK).
- sm_120 confirmed via `cuobjdump --list-elf` first (`astroray…1.sm_120.cubin`), never
  `ptxas -v`. RTX 5070 Ti, CUDA 12.8 (nvcc V12.8), MSVC 14.44, native sm_120.
- Mangling: `stageShadeBucketedKernelILb{P}ELb{T}ELb{Ph}ELb{D}ELb{LP}E`
  = `<HasPrincipled, HasTexture, HasPhotons, HasDispersion, HasLightPassAOVs>`.

| Kernel specialization | REG | STACK | CONSTANT[0] | CONSTANT[2] | vs baseline |
|---|---|---|---|---|---|
| `<0,0,0,0,0>` **FLEET pass-less** (HARD gate) | 254 | **3352** | 1700 | – | **== 254/3352/1700** ✅ |
| `<0,0,0,0,1>` pass-AOV, non-principled | 254 | **3352** | 1700 | – | **byte-identical to fleet** |
| `<1,0,0,0,0>` principled pass-less baseline | 254 | 7720 | 1700 | 368 | (principled reference) |
| `<1,0,0,0,1>` pass-AOV, principled | 254 | **7720** | 1700 | 368 | **byte-identical to `<1,0,0,0,0>`** |
| `stageIntersectQueuedKernel<false>` | 127 | 616 | 1696 | – | untouched (127 baseline) |

**HARD gate:** `stageShadeBucketedKernel<…,false>` = **REG 254 / STACK 3352 / CONSTANT[0]
1700**, byte-identical to the verified fleet baseline (254/3352/1700, re-confirmed by
pkg190/PR-#614 HW). **PASS.** The 3608 figures also present in the dump belong to the
`HasTexture=true` (`<*,1,*,*,0>`) specializations — the fleet runs `<0,0,0,0,0>`.

### Isolation-axis analysis (why the fleet is safe by construction)
The `HasLightPassAOVs=false` specialization is generated from the SAME template body with
the pass code behind `if constexpr` — identical to how pkg186/pkg189/pkg199-S2 produce a
byte-identical fleet kernel across their axes. The measured 254/3352/1700 confirms the
compiler stripped the partition entirely. **This is not a "we hope it's under budget"
result — the fleet kernel is provably the same object it was before the probe.**

The stronger-than-required finding: even the `HasLightPassAOVs=true` kernels add **zero
STACK and no register-tier change** over their pass-less twins. The global-scatter design
converts the pass partition into extra memory transactions that slot into the existing
254-register / 3352-stack envelope rather than raising the spill peak or the live-register
count. So AOV-on renders pay latency (expected, acceptable when a compositor pass is
explicitly requested), not occupancy.

### Residual risk (honest scope of what the probe did NOT exhaust)
The probe implemented ONE representative shade-kernel accumulation site (immediate NEE) +
the bounce-0 classification — the register-hostile part, and the only part that could kill
the package. The full Stage-2 mirror additionally needs, at NON-hostile sites:
- deferred-NEE pass attribution in **`stageShadowKernel`** (separate, leaner kernel);
- emission / environment / lamp-MIS partition in **`intersectPathSlot`** (REG 127, ~2
  blocks/SM — clear headroom);
- one or two more shade-kernel `color +=` mirrors (BSDF-emission MIS) — SAME
  `read-category + lpAccumulate` shape as the measured NEE mirror, which cost zero, so a
  spill from these is very unlikely but **must be re-measured on the full-impl `.pyd`**;
- per-slot `passAccum` SoA allocation + accumulate-at-death XYZ conversion in
  `stageRegenKernel` + copy-back, reusing the pkg197 guide/beauty plumbing (one path);
- the CPU↔GPU per-pass mean-ratio parity gate + energy-closure (Σpasses == GPU beauty) +
  headless-Blender compositor round-trip + the RTX HW gate bound to HEAD (Stage-2 scope §).

None of these touch the REG-254 budget in a way the probe leaves unquantified; the gating
question ("does the shade kernel spill when it must write the partition?") is answered
**no**. Recommend dispatching the full Stage-2 mirror with the design above; re-run this
exact cuobjdump check on the full-impl `.pyd` as the acceptance gate (the fleet `<…,false>`
kernel must still read 254/3352/1700).

**Probe branch is evidence-only** — the probe code (the `[pkg198-diag]`-marked axis + sink
in `stage_advance.cu` / `gpu_types.h`) is NOT part of this docs commit; it was the
measurement instrument and is reverted. The full-impl PR re-adds the production
(non-diag) version.
