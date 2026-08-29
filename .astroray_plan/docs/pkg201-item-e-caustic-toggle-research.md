# pkg201 Stage 3 item E — native caustic toggle research (`caustics_reflective` / `caustics_refractive`)

**Status:** research only, per CLAUDE.md §6 (cite-algorithm). No source edited. No build. No test run.

## 1. Cycles reference (cited)

Source: `blender/blender` (Apache-2.0), verified via `gh search code` + raw fetch on
2026-08-29, files `intern/cycles/kernel/closure/bsdf_microfacet.h`,
`intern/cycles/kernel/svm/closure.h`, `intern/cycles/kernel/integrator/path_state.h`.

**The exact rule is enforced at BSDF-closure-setup time, not at contribution/NEE
time.** Every specular/glossy/refractive closure setup function computes:

```c
#ifdef __CAUSTICS_TRICKS__
const bool reflective_caustics = (kernel_data.integrator.caustics_reflective ||
                                  (ray_visibility & PATH_RAY_VISIBILITY_DIFFUSE) == 0);
const bool refractive_caustics = (kernel_data.integrator.caustics_refractive ||
                                  (ray_visibility & PATH_RAY_VISIBILITY_DIFFUSE) == 0);
#endif
```

— i.e. the closure is suppressed (`break;`, no BSDF lobe created at all for this
path at this vertex) **only when the toggle is off AND the incoming path's
`ray_visibility` already carries `PATH_RAY_VISIBILITY_DIFFUSE`**. Reflective
(GGX/Beckmann/conductor/glossy-toon closures) is gated on `caustics_reflective`;
refractive (GGX/Beckmann refraction closures) on `caustics_refractive`; the
combined glass closure (reflect+refract lobes in one BSDF) is gated on the OR of
both — it only drops out entirely when *both* are disallowed.

`PATH_RAY_VISIBILITY_DIFFUSE` is a **sticky, path-lifetime bit**, not "previous
bounce type." It is set in `path_state.h`'s post-bounce update:

```c
/* diffuse/glossy/singular */
if (label & LABEL_DIFFUSE) {
  visibility |= PATH_RAY_VISIBILITY_DIFFUSE;
  flag |= PATH_RAY_DIFFUSE_ANCESTOR;
}
else if (label & LABEL_GLOSSY) {
  visibility |= PATH_RAY_VISIBILITY_GLOSSY;
}
```

Once a path's sampled bounce is labeled `LABEL_DIFFUSE` (a genuinely rough/Lambertian-like
scatter — **not** `LABEL_GLOSSY`), the bit is OR'd in and never cleared for the
rest of the path. `path_state_ray_visibility()` strips the diffuse/glossy bits
only when the *current* ray is itself a transmission ray (`PATH_RAY_VISIBILITY_TRANSMIT`
set) — a separate, transient masking for camera/light visibility groups, not
part of the caustic-ancestor logic.

**Net effect:** a path that has ever bounced off a true diffuse surface can no
longer sample a specular/glossy (reflective) or refractive closure on any
subsequent surface when the corresponding toggle is off — that surface's BSDF
returns empty for this path, so the path dies there (zero further transport)
instead of continuing on to a light and forming a caustic. Reflective vs.
refractive is distinguished purely by **which closure type** is being set up
(reflection-only microfacet/conductor closures vs. refraction closures), not by
any additional per-ray classification — the ancestor bit itself is the same for
both toggles; only the closure being gated differs.

Quote used under the 15-word/attribution limit: "Use reflective caustics,
resulting in a brighter image" — `intern/cycles/blender/addon/properties.py`
(Blender Foundation, Apache-2.0).

## 2. Astroray mapping

### Why this is NOT `was_specular`

Astroray's existing `was_specular` (CPU: `raytracer.h:2613` local `bool
wasSpecular`; GPU: `GPUWavefrontState::was_specular` int SoA field,
`include/astroray/gpu_wavefront_state.h:155`) is reset every bounce to the
**current** vertex's `bss.isDelta` (`raytracer.h:3021`, GPU
`src/gpu/wavefront/stage_advance.cu:1375`). It answers "was the immediately
preceding bounce delta?" — used for two-sided MIS on emissive hits. Item E
needs the Cycles-shaped question instead: "has this path **ever** bounced off
a diffuse surface, however many vertices ago?" That is a **sticky flag**, set
once, never cleared (mirroring `PATH_RAY_DIFFUSE_ANCESTOR`), and it must use
the DIFFUSE label specifically — Astroray already has this diffuse/glossy
split baked into the existing `firstCat` classification (pkg198 Stage 1):

```cpp
// raytracer.h:3033-3037 (CPU); GPU twin at stage_advance.cu ~1375-1383
float sWo = wo.dot(rec.normal);
float sWi = bss.wi.dot(rec.normal);
bool transmitted = (sWo * sWi) < 0.0f;
firstCat = transmitted ? 2
         : ((bss.isDelta || rec.material->isGlossy()) ? 1 : 0);
// 0 = diffuse, 1 = glossy, 2 = transmission
```

The DIFFUSE case Cycles' ancestor bit needs is exactly `firstCat == 0`'s test:
`!bss.isDelta && !rec.material->isGlossy()` (GPU device twin:
`gpu_material_is_glossy(mat)`, `src/gpu/wavefront/stage_init.cu:218-227`,
already written and already used behind `if constexpr(HasLightPassAOVs)`).
**Caveat:** `firstCat` is locked ONCE at the first bounce only (`if (firstCat <
0)` guard, `raytracer.h:3032`); item E's ancestor flag must be evaluated at
**every** bounce, not just the first, since a diffuse bounce at depth 3 must
still gate a specular bounce at depth 5. This is the one place item E cannot
reuse the item-A/pkg198 pattern verbatim — it needs its own always-on sticky
bit, not a first-bounce lock.

### Flag: what to carry, where set, where read

**CPU** (`pathTraceSpectral`, `include/raytracer.h`, currently ~L2611-3040 as of
this HEAD — matches the spec's line numbers loosely; the file has drifted since
pkg201 Stage 2 landed, so treat these as approximate, re-grep before editing):

- Declare `bool hadDiffuseAncestor = false;` next to `bool wasSpecular = true;`
  (~L2613).
- After the BSDF sample (`bss = rec.material->sampleSpectral(...)`, ~L3019),
  and after the existing `sWo`/`sWi`/`transmitted` computation is available
  (promote that computation out of the `if (firstCat < 0)` guard so it runs
  every bounce, or duplicate a cheap local copy — small, correctness-neutral,
  simplicity-first choice for the implementer to make explicitly):
  - if `!bss.isDelta && !rec.material->isGlossy()`: `hadDiffuseAncestor = true;`
    (mirrors `LABEL_DIFFUSE` → sticky bit; glossy bounces do NOT set it, matching
    Cycles' `LABEL_GLOSSY` branch which sets a *different*, non-caustic-gating
    bit).
  - if `hadDiffuseAncestor && bss.isDelta`: this bounce is the candidate
    caustic-forming specular/refractive event. Classify with the same
    `transmitted` test: `transmitted` → gate on `useRefractiveCaustics`;
    `!transmitted` → gate on `useReflectiveCaustics`. If the relevant toggle is
    `false`, terminate the path here (`break;`) instead of taking the sample —
    the closest same-shape equivalent to Cycles dropping the closure at setup
    time. **This is a one-bounce-later approximation** of Cycles' mechanism
    (Cycles never lets the BSDF sample happen at all; Astroray samples it, then
    kills the resulting ray) — behaviourally identical for a pure-delta
    material (mirror/glass: nothing else could have happened at that vertex
    anyway), but see the open question below for mixed/Principled materials.

- `getUseReflectiveCaustics()` / `getUseRefractiveCaustics()` already exist
  (`include/raytracer.h:2355-2356`; storage `:2142-2143`, setters `:2352-2353`
  — **note these line numbers are ~20 lower than the pkg201 spec's stated
  2124/2125 and 2260/2261**, drifted by the Stage 2 F-alpha/filter-importance
  additions; re-grep at implementation time). No new CPU storage needed, only
  the read-site.

**GPU** (`src/gpu/wavefront/`):

- New sticky SoA field in `GPUWavefrontState`
  (`include/astroray/gpu_wavefront_state.h:154-156`, next to `was_specular`):
  `int* had_diffuse_ancestor = nullptr;  // 0/1, sticky, never cleared`. Needs
  matching alloc/free in `allocateGPUWavefrontState`/`freeGPUWavefrontState`
  (`src/gpu/wavefront/wavefront_state.cu` — not read in this pass, but the
  same file that owns `was_specular`'s allocation).
- Zero it in `initPathSlot` (`src/gpu/wavefront/stage_init.cu:364-365`, right
  next to `state.was_specular[idx] = 1;` / `state.path_alive[idx] = 1;`):
  `state.had_diffuse_ancestor[idx] = 0;`
- Set/read it in `shadePathSlot`, right where the GPU already computes the
  `transmitted` sign test for `firstCat` (`src/gpu/wavefront/stage_advance.cu`
  ~L1375-1383, `wasSpecular = bss.isDelta;` then the geometric sign test —
  same caveat as CPU: that block is currently first-bounce-locked and would
  need to run every bounce for item E, using `gpu_material_is_glossy(mat)`
  (`stage_init.cu:218`) for the diffuse-label test).
- Toggle values reach the device the same way `pixelFilterType`/`Width` do
  (pkg201 Stage 2, Finding D): a small `__constant__` POD struct, e.g.
  `__constant__ GCausticGate c_wfCausticGate = {true, true};` (mirrors
  `__constant__ GPixelFilterParams c_wfPixelFilter` at `stage_init.cu:43`),
  published once per frame from the host driver via a
  `setWavefrontCausticGate(bool reflective, bool refractive)` function
  (mirrors `cudaMemcpyToSymbol` calls at `stage_advance.cu:2149` for
  `c_wfMissCoverage`). This is CONSTANT memory, not per-ray live state — reading
  it costs a compare, not a register-resident field, unlike the sticky ancestor
  bit which IS per-ray live state.
- Cull action mirrors CPU: when `had_diffuse_ancestor[idx] && bss.isDelta` and
  the relevant gate constant is false, set `state.path_alive[idx] = 0;` and
  `return;` before writing the continuation ray (same shape as the existing
  early-terminate pattern used elsewhere in `shadePathSlot`, e.g. the
  `bss.pdf <= 0.0f` early-return at ~L1367-1374).

### Reflective vs. refractive distinguishing mechanism

Confirmed reusable: the existing geometric sign test `(wo·N)·(wi·N) < 0` (CPU
`raytracer.h:3035`, GPU twin in `stage_advance.cu`) already classifies a delta
bounce as transmission (refractive) vs. reflection — exactly the distinction
Cycles makes by closure *type* rather than a runtime test. No new geometry math
is needed; item E reuses item A/pkg198's existing sign test, just evaluated at
every specular bounce instead of only the first.

## 3. Register-cost prediction

**Correction to the task's stated baseline:** pkg201 Stage 3 item A has **not**
landed yet as of this HEAD (STATUS.md still lists "pkg201 Stage 3 ... carried
forward", `.astroray_plan/docs/STATUS.md:254-255`, and the fleet register gate
recorded in the pkg201 spec's own Stage 2 HW-verification table
(`.astroray_plan/packages/pkg201-gpu-wavefront-settings-honour.md:96-97`) is
still **REG 254 / STACK 3352 / CONSTANT[0] 1700** for
`stageShadeBucketedKernel<0,0,0,0,0>` — not the STACK 3360 the task prompt
assumed. Treat 3352/1700 as the current probe baseline until item A actually
lands and updates it.

Predicted cost of item E on top of that baseline:
- **+1 SoA global field** (`had_diffuse_ancestor`, like `was_specular`): global
  memory bandwidth, not register pressure — Stage 2's own experience (F-alpha's
  `c_wfMissCoverage`, filter importance sampling) shows SoA-global fields that
  are read/written once per bounce and don't participate in the hot per-ray
  compute graph cost effectively nothing in REG.
- **+1 local bool per shade invocation** (`hadDiffuseAncestor` loaded from SoA,
  used in one branch) — comparable to the existing `wasSpecular` local, which
  is already load-bearing in the same kernel; expect low single-digit REG
  delta at most, similar in shape to item A's own prediction in the task
  framing (+8 STACK, REG unchanged) — plausible that item E lands at REG 254
  unchanged with a small STACK bump, but this is a prediction, not a measured
  number; the mandatory up-front cuobjdump probe (CLAUDE.md / pkg201 Stage 3
  discipline) is the actual gate, not this estimate.
- **Risk factor:** promoting the `sWo`/`sWi`/`transmitted` computation from
  "only at first bounce" (`if (firstCat < 0)`) to "every bounce" adds live
  computation to the hot path on GPU that currently only runs once per path.
  If `HasLightPassAOVs`-style if-constexpr isolation isn't available (item E's
  gate is a real transport toggle, not an AOV-only bookkeeping path, so it
  likely CANNOT be compiled out the way `gpu_material_is_glossy` currently is
  restricted to `if constexpr(HasLightPassAOVs)`), this could cost more than a
  first glance suggests. This is the most likely spill risk and should be the
  first thing the probe checks.

## 4. Gate reality

`scripts/pkg200_honour_matrix.py:427-439`: both `caustics_reflective` and
`caustics_refractive` rows are `kind="visual"`, predicate `p_changes_pixels`
(`scripts/pkg200_honour_matrix.py:252-260`) — **NOT monotone-energy**.
`p_changes_pixels` only checks per-pixel `|dLum|` mean against a 1e-4
threshold: mean > 1e-4 → **NEEDS_VISUAL** ("setting changes pixels; confirm
direction visually" — requires a multimodal `Read` verdict to become PASS);
mean ≤ 1e-4 → **HONEST_FAIL** ("setting produced no pixel change"). So "PASS"
for this item genuinely means: (1) the driver's automatic per-pixel diff
clears the 1e-4 bar, AND (2) a human/multimodal visual read confirms the
*direction* (toggle off → caustic bright spot fades/vanishes) is correct —
matching the pkg201 spec's own stated acceptance ("NEEDS-VISUAL→PASS (a
multimodal Read verdict)").

Both rows share **one scene**: `build_caustic`
(`scripts/verify_pkg200_honour_matrix.py:270-281`) — a smooth-shaded glass
sphere over a diffuse floor, lit by a small bright emitter overhead, camera
looking at the floor. This is a **refraction-dominated** caustic (light
focused by passing through the glass sphere); it has essentially no strong
reflective-caustic component (Fresnel reflection off a smooth sphere spreads
specular highlights, not a focused caustic). Flagged as an open risk in §5 —
`caustics_reflective` may show a much smaller `|dLum|` than
`caustics_refractive` on this same scene even with a fully correct
implementation, risking a borderline/sub-threshold NEEDS_VISUAL→HONEST_FAIL
result for reasons unrelated to correctness (cf. the `pixel_filter_type`
sub-threshold precedent from Stage 2).

## 5. Open questions / risks

1. **Mixed-material lobes.** Cycles' mechanism suppresses ONE closure among
   several possibly-coexisting closures on the same shader (e.g. Principled
   BSDF's diffuse + specular lobes are set up as separate closures; only the
   specular one is dropped, the diffuse lobe survives). Astroray's
   `sampleSpectral()` returns a single stochastically-chosen `BSDFSample` per
   call for materials like Principled/Disney — there is no per-lobe closure
   list to selectively suppress at the CPU/GPU BSDF-sample level (aside from
   the GPU closure-graph path, `GMAT_CLOSURE_GRAPH`, which DOES enumerate
   individual closures per `gpu_material_is_glossy`). Terminating the whole
   path when a delta sample is drawn from a mixed material is the closest
   `break;`-equivalent, but is NOT identical to Cycles for materials where the
   specular lobe is only stochastically selected some fraction of the time —
   this needs an explicit design decision at implementation time, not an
   assumption.
2. **Scene asymmetry (§4):** the shared `build_caustic` scene may not exercise
   `caustics_reflective` strongly. Consider (in the PR, not this note) whether
   a second reflective-focused scene variant is warranted, or whether the
   existing scene's weak reflective signal is accepted as a known threshold
   risk.
3. **Every-bounce sign test cost (§3):** promoting the transmission sign test
   from first-bounce-only to every-bounce is new hot-path work on both CPU and
   GPU; confirm it doesn't perturb existing RNG draw counts or `firstCat`
   locking semantics (the sign test itself consumes no RNG, so this should be
   safe, but the refactor — extracting it from inside `if (firstCat < 0)` —
   must not accidentally change `firstCat`'s lock-once behavior).
4. **`GMaterial::isGlossy` vs `gpu_material_is_glossy` divergence risk.** The
   GPU twin is explicitly commented as needing to scan the closure graph
   because `scene_upload.cu` lowers ALL materials producing a valid closure
   graph to `GMAT_CLOSURE_GRAPH` (`stage_init.cu:209-217`) — any future
   material type added to that lowering path needs its glossy/diffuse
   classification kept in sync between the CPU `Material::isGlossy()` and this
   GPU scan, or the ancestor flag will silently diverge CPU vs GPU for that
   material. Pre-existing risk (shared with pkg198), not new to item E, but
   item E inherits it.
5. **Line-number drift.** The pkg201 spec's cited line numbers for
   `useReflectiveCaustics`/`useRefractiveCaustics` (2124-2125 storage,
   2260-2261 setters) are stale by ~18-20 lines against current HEAD
   (2142-2143 / 2352-2353) due to Stage 2 insertions. Re-grep before editing;
   do not trust either the spec's or this note's absolute line numbers as
   load-bearing.
