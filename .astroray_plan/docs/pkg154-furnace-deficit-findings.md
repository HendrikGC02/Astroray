# pkg154 — Rough-transmission furnace deficit: root-cause findings

**Spec:** `.astroray_plan/packages/pkg154-rough-transmission-furnace-deficit-root-cause.md`
**Result:** TWO convicted, unambiguous bugs, both fixed and measured. On the
pkg149 (`670e583`) + pkg151 (PR #519) stack, the rough-glass furnace goes from
**0.11–0.82** (spec baseline) to **0.997–0.999** across every roughness in the
gate grid (0.05, 0.1, 0.3, 0.6, 1.0), well inside `[0.92, 1.03]`. Peak
alignment stays green. Chi² glass[0.3-45] is measured unchanged (as expected —
these are `eval()`-magnitude fixes, not sampler fixes; ownership stays with
pkg149). **Both fixes are measured no-ops on main's current (pre-pkg149,
azimuth-buggy) sampler** — see "Shipping strategy" below for why the code
change ships as a patch file, not a direct main PR, this round.

---

## H1 CONVICTED — `entering` was never anything but `true` (frontFace bug)

**Mechanism.** `roughTransmissionEval`/`roughTransmissionPdf`
(`plugins/materials/disney.cpp`) derived the enter/exit direction from
`bool entering = cosO > 0.0f`, where `cosO = rec.normal.dot(wo)`. But
`rec.normal` is the **front-facing** shading normal
(`HitRecord::setFaceNormal`, `include/raytracer.h:433`):

```cpp
void setFaceNormal(const Ray& r, const Vec3& outwardNormal) {
    frontFace = r.direction.dot(outwardNormal) < 0;
    normal = frontFace ? outwardNormal : -outwardNormal;
    ...
}
```

`normal` is *always* re-oriented to face back along the incoming ray direction
(this is the classic "hit_record set_face_normal" convention). With
`wo = -ray.direction`, algebra shows `cosO = rec.normal.dot(wo) >= 0`
**unconditionally**, regardless of whether the ray is truly entering the glass
(air→glass) or exiting it (glass→air). `cosO`'s sign carries zero enter/exit
information — the "entering" test was dead code that always evaluated `true`.

**Consequence.** Both a true entrance AND a true exit refraction event
computed `etap = ior_` (never `1/ior_`), so the PBRT-v4 radiance-transport
correction `ft /= etap*etap` (a real, necessary asymmetry — see "Why
`ft/=etap²`" below) applied the *same* compressive factor at both ends of a
round trip instead of cancelling. At ior=1.5: `(1/2.25)² ≈ 0.1975`, matching
the spec's own arithmetic (`0.198 ≈ 0.217` measured floor at roughness=0.1)
almost exactly.

**Direct measurement** (instrumented build, atomic counters in
`roughTransmissionEval`, removed before commit): rendering the furnace scene
at roughness=0.1 on the pkg149+pkg151 stack:

```
roughTransmissionEval calls=274809
  frontFace=true:  106047 (38.59%)
  frontFace=false: 168762 (61.41%)   <- TRUE exit events
  entering(cosO>0)=true: 274809 (100.00%)   <- includes ALL 168,762 exit events
```

100.00% of calls — including 61% that were genuine exit events — evaluated
`entering=true`. This is not a subtle statistical leaning; the sign test never
fires `false`.

**Precedent (already known and already fixed elsewhere in this exact
codebase, never ported here):**
- `plugins/materials/dielectric.cpp` (smooth glass) has the identical fix,
  with the identical diagnosis in-comment: *"Enter/exit MUST come from
  rec.frontFace, not the sign of wo·rec.normal. rec.normal is the
  front-facing (setFaceNormal'd) shading normal, so wo·rec.normal is ALWAYS >
  0 and the old sign test read every hit as 'entering' -> eta = 1/ior at BOTH
  surfaces -> the eta^2 radiance factor never cancelled (glass rendered too
  dark, loss growing with IOR)."* (memory `refraction-frontface-bug`)
- `photon_caustic.cu`/photon-loop exit refraction had the same class of bug
  (memory `photon-caustic-exit-refraction-oriented-normal`): using the
  ray-oriented normal instead of the geometric outward normal at the exit
  event.
- GPU: `gpu_materials.h`'s smooth dielectric path
  (`gpu_dielectric_sample`, ~line 313) and the plain dielectric transmission
  branch (~line 378) already key off `rec.frontFace` correctly. Only the
  Disney rough-transmission twins (`gpu_disney_roughTransmissionEval`/
  `gpu_disney_roughTransmissionPdf`) had the stale sign test.

`sample()`'s own eta computation (`disney.cpp`, the smooth-fallback setup,
`rec.frontFace ? 1.0f : ior_`) was **already correct** — it just wasn't
consulted by `roughTransmissionEval`/`roughTransmissionPdf`, which
independently recomputed a *different, wrong* eta orientation for the exact
same sampled event. The refracted direction (`refractThroughMicroNormal`,
called with the correct externally-computed `eta`) was right; only the BSDF
value/pdf re-derivation for that direction was wrong.

**Why `ft /= etap²` is correct in the first place** (so this is clearly a
sign-of-`entering` bug, not a case for removing the correction): radiance is
not conserved across a refracting interface — only *basic radiance* `L/n²`
is (Veach 1997 §5.2, non-symmetric scattering; pbrt-v4 `DielectricBxDF::f`,
Apache-2.0/BSD-3, `etap = cosTheta_o > 0 ? eta : (1/eta); if (mode ==
Radiance) ft /= Sqr(etap);`). A single transmission event in radiance-transport
mode must multiply by `1/etap²`; the *reciprocal* event (the same ray later
exiting) must multiply by `1/(1/etap)² = etap²`. The two exactly cancel over
a closed round trip, which is exactly the invariant the furnace test is
checking. pkg149's own research note observed the single-scatter estimator
median ≈ `G1(wi)/etap²` "matches theory" for *entering* events — true, and
NOT itself the bug (as the spec's H1 write-up asked us to check): the bug is
that the *exiting* estimator's `etap` was silently also `ior_` instead of
`1/ior_`, so it never got the compensating `×etap²` factor. After the fix,
directly measured (mean single-scatter estimator `f·|cosI|/pdf`, no
compensation, split by true frontFace):

| roughness | entering mean (theory 1/ior²=0.444) | exiting mean (theory ior²=2.25) | product |
|---|---|---|---|
| 0.1 | 0.444 | 2.25 | 1.00 |
| 0.3 | 0.444 | 2.26 | 1.00 |
| 0.6 | 0.435 | 2.42 | 1.05 |
| 1.0 | 0.365 | 3.05 | 1.11 |

Textbook cancellation (small drift at high roughness from G1 asymmetry
between the two directions, not a bug — see H2 below for why the *aggregate*
furnace value is nonetheless clean at those roughnesses too).

**Fix** (mirrored CPU + GPU, `roughTransmissionEval` and
`roughTransmissionPdf`/`gpu_disney_roughTransmissionEval` and
`gpu_disney_roughTransmissionPdf`):

```cpp
bool entering = rec.frontFace;   // was: cosO > 0.0f
```

**Measured effect of H1 alone** (compensation and clamp both held fixed —
compensation temporarily disabled, clamp still present — to isolate this
term): furnace goes from 0.217/0.357/0.597/0.822 to
0.176/0.365/0.850/0.978 (roughness 0.1/0.3/0.6/1.0). Fully closes the gate at
roughness ≥ 0.6, makes essentially no difference at roughness ≤ 0.3, and
*worsens* roughness=0.1 slightly. H1 is real and necessary but insufficient
alone — see H4 below for the second term that explains the low-roughness
residual.

---

## H4 (new) CONVICTED — closure-level `clamp(0,4)` truncates the low-roughness estimator

**This mechanism is not one of the spec's three ranked hypotheses (H1/H2/H3)
— it was found empirically while isolating why the H1 fix alone left a
strong, LOW-roughness-specific residual** (worse, not better, at
roughness=0.1; the spec's H2/H3 predicted a Jacobian-shaped or
Fresnel-shaped residual, neither of which matches "gets worse at low
roughness, near-perfect by roughness=0.6–1.0").

**Diagnosis path.** With H1 fixed, a branch-outcome ledger (instrumented,
removed before commit) showed the *transmission* sub-branch of `sample()`'s
VNDF roulette **never fails** (`transFail=0` at every roughness/frontFace
combination tested) — so the residual isn't a missing-sample/masking effect,
it has to be a magnitude bug in `roughTransmissionEval` itself. `D_GTR2`
(Trowbridge-Reitz GGX NDF) grows without bound as `alpha -> 0` for
near-perfectly-aligned half-vectors (`NdotH -> 1`); at roughness=0.1,
`alpha = max(0.1², 0.0064) = 0.01`, a very peaked lobe. `roughTransmissionEval`
had a **hard `std::clamp(result, 0.0f, 4.0f)`** on its return value — a
closure-level magnitude cap that silently discards the rare, high-value tail
samples an *unbiased* Monte-Carlo estimator legitimately needs (the mean of a
truncated distribution is not the mean of the true one; the truncation loss
is largest exactly when the tail is heaviest, i.e. at low roughness, and
vanishes as roughness grows and the lobe flattens — the observed profile).

**This is the exact same bug class already found, diagnosed, and fixed in
this same file for the METAL REFLECTION lobe (pkg123)** — the comment sits a
few dozen lines above `fresnelDielectric` in `disney.cpp` and states the
principle directly:

> *"floor at 0 only — NO upper cap. A finite cap clips the near-delta GGX
> specular peak... the importance-sampled f/pdf ratio then no longer cancels
> D and metal reflection collapses to black (`test_disney_metal_reflection_
> not_black`: 0.215 vs 0.604, ~2.8x too dark)... Firefly control belongs at
> the integrator (raytracer.h clampDirect/clampIndirect...), mirroring Cycles'
> kernel_accum_clamp — never a closure-level cap on the BRDF value (Cycles
> bsdf_microfacet.h returns the true D)."*

`roughReflectionEval` (the pkg138 rough-glass *reflection* lobe, same file)
was never given this cap and returns the bare `D*G*F/(4·cosO·cosI)` — the
transmission twin had it, inconsistently, since the original rough-glass
commit (`5604ab7 feat: add rough Disney glass transmission`).

**Direct measurement** (H1 fix + pkg151 compensation both held in place,
clamp toggled):

| roughness | with clamp(0,4) | clamp removed | gate |
|---|---|---|---|
| 0.1 | 0.178 | **0.9986** | [0.92, 1.03] |
| 0.3 | 0.365 | **0.9987** | [0.92, 1.03] |
| 0.6 | 0.850 | **0.9985** | [0.92, 1.03] |
| 1.0 | 0.978 | **0.9970** | [0.92, 1.03] |

And at roughness=0.05 (also in the spec's grid): **0.9986**.

**Fix** (mirrored CPU + GPU): replace `clamp(result, 0, 4)` with
`clampColor(result)` (the existing floor-at-0-only helper `disney.cpp`
already uses for the metal/reflection paths), i.e. delete the upper cap
entirely; GPU mirrors with a bare `fmaxf(x, 0.f)`.

---

## Combined result (both fixes, pkg151 compensation active, pkg149 sampler stacked)

Full furnace sweep, `test_disney_rough_glass_furnace_energy_cpu` methodology
(seed 7, spp 256, sphere-centre 24×24 patch mean):

| roughness | furnace | gate |
|---|---|---|
| 0.05 | 0.9986 | [0.92, 1.03] |
| 0.1 | 0.9986 | [0.92, 1.03] |
| 0.3 | 0.9987 | [0.92, 1.03] |
| 0.6 | 0.9985 | [0.92, 1.03] |
| 1.0 | 0.9970 | [0.92, 1.03] |

`test_disney_rough_glass_furnace_energy_cpu`, `_converges`,
`test_disney_smooth_glass_furnace_cpu` all **PASS**.
`test_transmission_sample_pdf_peak_alignment[45.0-0.3-1.5]` (pkg149's own
gate) **PASSES** unchanged — these are `eval()`-magnitude-only fixes, they do
not touch `sampleGgxVNDF`.
`test_chi2_disney_glass[0.3-45]` (`--runxfail`, reporting only): chi²
statistic **34,987.970271**, identical to pkg149's own pre-existing
measurement — expected and correct, since chi² tests `sample()`/`pdf()`
*self-consistency*, and both functions moved together (both switched from the
same wrong `cosO`-sign test to the same `rec.frontFace` test), so their
relative agreement is unaffected. Ownership of that gate stays with pkg149
per the spec's non-goals.

Full local suite on the pkg149+pkg151+both-fixes stack: **1391 passed, 131
skipped, 21 xfailed, 1 xpassed** (`--ignore=tests/wavefront_diff`, minus the
pre-existing unrelated
`test_wavefront_photon_caustic_parity` deselect pkg151's own PR already
documented as unrelated/pre-existing on this machine). The single xpass
(`test_disable_reflective_caustics_reduces_mirror_caustic_outliers`,
`xfail(strict=False)`) is a metal-mirror Cornell-box percentile test wholly
unrelated to Disney glass transmission (metal material, roughness=0.001);
not investigated further as out of scope, and `strict=False` means it does
not fail the suite either way.

Visual sanity check (memory `general-photon-loop-needs-solid-glass`): a rough
Disney glass sphere (roughness=0.2, ior=1.5) over a diffuse floor with an
area light renders as a plausible frosted/refractive sphere — no black holes,
no fireflies, no NaN/inf artifacts.

---

## H2/H3 (spec's other ranked hypotheses) — not separately investigated further

H2 (VNDF Jacobian/branch mismatch) and H3 (Fresnel double-counting) were the
spec's other ranked candidates. Once H1 and H4 together fully closed the
furnace gate to 0.997–0.999 across the entire roughness grid, there was no
observable residual left to attribute to H2 or H3 — both are exonerated as
*dominant* causes for this deficit (a small H3-magnitude effect, ~4-9% at
most per the spec's own estimate, could not survive underneath a result this
close to 1.0 without showing up as a systematic bias, and none was seen).

---

## Shipping strategy — why this ships as a patch file, not a direct main PR

Both fixes were also measured on **main's current (pre-pkg149) sampler**,
independently of the pkg149/pkg151 stack, per the dispatch contract's
"measure both" requirement:

| roughness | main (unmodified) | main + both pkg154 fixes |
|---|---|---|
| 0.0 | 1.0000 | 1.0000 |
| 0.03 | 1.0000 | 1.0000 |
| 0.05 | 0.8864 | 0.8864 |
| 0.1 | 0.9374 | 0.9374 |
| 0.3 | 0.9997 | 0.9997 |
| 0.6 | 0.9999 | 0.9999 |
| 1.0 | 0.9995 | 0.9995 |

**Bit-for-bit identical to 4 decimal places.** Both fixes are provable no-ops
on main's current sampler — full local suite also confirms this
(1381 passed on both, no diffs beyond the two test files pkg149/pkg151 add
that don't exist on plain main). This makes sense in retrospect: `entering`
being stuck at `true` only matters when a meaningful fraction of sampled
half-vectors actually populate the "true exit" configuration with correctly
azimuth-aligned Fresnel/backfacing checks; the pre-pkg149 sampler's
azimuth-inversion bug (see pkg149's research note) apparently distorts that
population enough that this specific magnitude bug doesn't manifest the same
way. Likewise the clamp(0,4) truncation only bites once the corrected VNDF
sampler is actually exploring the true (heavy-tailed) half-vector
distribution near grazing/aligned configurations.

Per the dispatch contract ("if the fix only makes sense with the corrected
sampler, note that it ships via the pkg149 rebase instead and put it in the
findings doc + a patch file"): **this package does NOT open a code PR against
`disney.cpp`/`gpu_materials.h` this round.** Reasons, both independently
sufficient:

1. The fix is measurably inert on main today — there is no main-branch
   regression to justify, and no observable improvement to point to either
   (both are 0.0000 deltas across the whole grid).
2. `plugins/materials/disney.cpp`'s `roughTransmissionEval` is **already
   being edited by the still-unmerged pkg151/PR #519** (the
   `ggxGlassCompensationFactor` multiply lands in the same function this
   package's H1 fix touches). Landing a second, independent PR against the
   same function before #519 merges risks an avoidable merge conflict and
   violates the architect's stated "disney.cpp single-writer discipline"
   for this lane.

**The full, ready-to-apply fix is captured at
`.astroray_plan/docs/pkg154-frontface-and-clamp-fix.patch`** (generated as
`git diff origin/main <fix-commits>` — applies cleanly with `git apply` or
`git am` against `plugins/materials/disney.cpp` + `include/astroray/
gpu_materials.h` at the current main tip). It contains exactly the two
convicted fixes (frontFace + clamp removal), fully commented/cited, nothing
else.

## Recommended path forward for pkg149/pkg151

1. Let pkg151/PR #519 merge on its own adjudicated terms (groundwork, main
   sampler unchanged, independent of this package).
2. When pkg149 rebases its held `670e583` commit onto the post-#519 main, it
   should **also cherry-pick or apply
   `pkg154-frontface-and-clamp-fix.patch`** (or hand-merge the same two
   one-line changes) as part of that same stack. That combination is what
   was actually measured here (furnace 0.997–0.999, peak alignment green,
   chi² unchanged/still red — pkg149's to un-xfail on its own terms).
3. pkg149's furnace-gate blocker is closed by this combination; pkg149 can
   proceed to ship its azimuth fix + this patch together, un-hold, and open
   its PR with the measured numbers above.
4. pkg150 (VNDF reflection-candidate masking) should re-baseline after that
   stack lands, per its own note (unaffected by either pkg154 fix — both are
   `eval()`-magnitude changes on the transmission sub-branch only, not the
   shared `sampleGgxVNDF`/reflection-candidate logic).

## Citations (CLAUDE.md §6)

- Veach, E. (1997). *Robust Monte Carlo Methods for Light Transport
  Simulation*, PhD thesis, Stanford — §5.2, non-symmetric scattering /
  radiance-transport correction at refracting interfaces (the reason
  `ft /= etap²` exists and must cancel over a closed path).
- pbrt-v4, `src/pbrt/bxdfs.cpp` `DielectricBxDF::f`/`Sample_f`/`PDF`
  (Apache-2.0/BSD-3, Matt Pharr, Wenzel Jakob, Greg Humphreys) — the
  `etap = cosTheta_o > 0 ? eta : (1/eta)` convention and the
  `if (mode == Radiance) ft /= Sqr(etap)` correction; already the cited
  reference for `roughTransmissionEval`/`roughTransmissionPdf`'s D/G/Jacobian
  terms (unchanged by this fix).
- Walter, Marschner, Li, Torrance (2007). "Microfacet Models for Refraction
  through Rough Surfaces," EGSR — already cited for the D/G/Jacobian forms;
  unaffected by either fix here (both fixes are about eta-orientation
  selection and output clamping, not the Walter formulas themselves).
- In-repo precedents (no external citation needed, same codebase):
  `plugins/materials/dielectric.cpp` (frontFace fix, memory
  `refraction-frontface-bug`), `photon_caustic.cu` (memory
  `photon-caustic-exit-refraction-oriented-normal`), and the pkg123 metal
  `clampColor` comment in `disney.cpp` (closure-level-cap-breaks-f/pdf
  precedent, `test_disney_metal_reflection_not_black`).
