# pkg99 — ADAF quasi-spherical glow re-investigation

**Pillar:** 4
**Track:** B (plugin/physics-adjacent render path — needs the RTX HW visual gate; no Track-A engine work)
**Codex-paste-ready:** no — requires empirical render iteration on RTX hardware (visual gate); the fix cannot be verified by CI alone (see memory `ci_has_no_gpu_runtime_blindspot`).
**Status:** done (PR #335, 2026-05-22 — dropped exposureScale from volumetric emission path; jet intensity_scale 1e28→5e13; regression test asserts ADAF ON ≠ OFF; ADAF should now glow at spec intensity_scale=1e30; empirical RTX visual tuning is separate follow-up)
**Estimated effort:** ~1 day (~6 h, including RTX render iteration)
**Depends on:** pkg44 (the ADAF plugin + the merged scene-wiring fix, PR #310 → `main` `11644df`; the camera/param/enable_adaf wiring is DONE and is *not* in scope to re-do)

---

## Goal

**Before:** pkg44 ADAF shipped (PR #310, merged `11644df`). The
post-merge HW gate PASSED a *signal-presence* check
(`shadow_fraction 0.0015`), and the three scene-wiring steps from
memory `gr-emission-model-wiring-checklist` (the `enable_adaf`
branch in `addBlackHole`, the `adaf_`-prefix param mapping, the
render-unit camera) are all present and correct on `main`.

But visual inspection of the gate renders
(`astroray-wt-pkg44/test_results/adaf_sgra_gate_a84f48a.png` and
`…_enhanced.png`) shows the fix is only **partial**: there is a
crisp central BH shadow disk plus a faint emission sliver, but
pkg44 spec acceptance L243 — *"a quasi-spherical glow around the
black hole with the shadow visible as a dark silhouette"* — is
**not** achieved. The frame is dominated by uniform background
noise; the ADAF glow barely reads. The wiring works; the glow
does not.

The two automated checks that should have caught this both passed
hollow:
- pkg44 `tests/test_adaf.py::test_tiny_adaf_scene_renders_visible_signal`
  asserts only `arr.max() > 0` and `arr.min() ≈ 0` — true for a
  noisy black field with one bright sliver. No radial structure
  is checked.
- The orchestrator gate measured `shadow_fraction` (a darkness
  metric) and read 0.0015, which a near-black frame trivially
  satisfies. It does not test that there is a *concentrated glow*
  surrounding the dark region.

**After:** The Sgr A*-like gate render shows a genuine
**quasi-spherical glow with a central dark silhouette** (matches
the working synchrotron-jet render's visual character — diffuse
emission concentrated around the hole, not a single sliver on
noise). The plugin/scene change that achieves this is committed.
A new end-to-end integration test asserts **radial structure**
(central dark region + monotone-ish outward intensity falloff),
replacing the hollow `max>0` check so this exact regression
cannot ship green again.

---

## Context — why this matters now

The ADAF is the accretion model for the Event Horizon Telescope's
two primary targets (Sgr A*, M87*) and is the regime where the
black-hole shadow is most cleanly visible. A render that is "a
dark disk on noise" is not a usable ADAF visualization — it is
indistinguishable from a broken emitter. pkg44's acceptance
criterion L243 is the *defining* visual property of an ADAF;
shipping without it means Pillar 4's ADAF deliverable is not
actually met despite the green status line.

This package is the corrective second pass that
`gr-emission-model-wiring-checklist` explicitly anticipates:
*"Add an end-to-end scene render assertion (central-dark-region +
radial falloff), not just a 'renders some signal' check — the
latter passes hollow on the BH background."* pkg44 added the
hollow check; pkg99 adds the real one **and** fixes whatever the
real check then exposes.

This is render/physics-adjacent and depends on the RTX visual
gate — CI has no GPU and is structurally blind to this class of
defect (memory `ci_has_no_gpu_runtime_blindspot`,
`gr-emission-model-wiring-checklist`). It contends for the
serialized hardware slot.

---

## Reference

### Internal (read first — cite the relevant ones in code/PR)

- [`.astroray_plan/packages/pkg44-adaf.md`](pkg44-adaf.md) —
  **acceptance L243** ("quasi-spherical glow … shadow visible as
  a dark silhouette"), the parameter table (L202-211),
  §Radiative transfer, and the Lessons §2 *research-note
  numerical discrepancy* note (n_e and B are ~10⁴–10⁵× larger
  than the research note's hand-calc — relevant to whether
  `adaf_intensity_scale` is mis-tuned).
- [`tests/scenes/adaf_sgra.py`](../../tests/scenes/adaf_sgra.py)
  — the current post-fix scene (camera `dist=75`, FOV 35°,
  influence-sphere arg `20.0`, `adaf_intensity_scale 1.0e30`,
  `adaf_r_outer 100.0`). This is what produces the partial render.
- [`tests/scenes/synchrotron_jet.py`](../../tests/scenes/synchrotron_jet.py)
  — **the calibrated working analog** (same M = 4e6, same GR
  `add_black_hole` dispatch; camera dist 70, FOV 28°,
  influence-sphere arg `16.0`, `intensity_scale 1.0e28`,
  `base_density 1.0e12`, `magnetic_field 1.0e6`). Its render is
  the visual target and the calibration reference for every
  scale/camera judgement in this package.
- [`include/astroray/adaf.h`](../../include/astroray/adaf.h) —
  `ADAF::emissivity` / `integrateSegment` / `contains` /
  `densityAt`. Note: `densityAt` uses `r_in_RS = r_M / 2`, the
  Y14 power-law `n_e ∝ r^(-3/2+s)`; `emissivity` clamps
  `j_total` at `1.0e30` *before* multiplying by
  `intensity_scale_` — inspect whether this clamp flattens the
  radial profile (everything saturated → no inward brightening →
  no concentrated glow).
- [`module/blender_module.cpp`](../../module/blender_module.cpp)
  — the **merged `enable_adaf` branch (~L569-598)**. Confirmed
  correct; in scope only as a read reference to confirm the
  `adaf_`→un-prefixed param mapping matches what the scene sets
  (do **not** modify it unless a param the scene relies on is
  provably not forwarded).
- [`tests/test_adaf.py`](../../tests/test_adaf.py) —
  `test_tiny_adaf_scene_renders_visible_signal` (L386-399, the
  hollow check to replace); `test_radial_bounds` (L301) for the
  existing assertion idiom.
- Memory
  `C:\Users\hgcom\.claude\projects\C--Users-hgcom-OneDrive-Astroray-Astroray-repo-Astroray\memory\gr-emission-model-wiring-checklist.md`
  — **cite in the spec/PR and in the new test's docstring**: the
  three wiring steps (already satisfied) and the explicit
  requirement for a central-dark-region + radial-falloff
  end-to-end assertion.
- Memory `ci_has_no_gpu_runtime_blindspot`,
  `mc-noise-vs-deterministic` — the latter is directly relevant:
  if signal-to-background ratios are *stable and do not improve
  with √SPP*, the cause is a scale/units/integration issue, not
  RNG; re-render at SPP an order apart before any noise
  hypothesis.
- pkg44 gate artifacts:
  `astroray-wt-pkg44/test_results/adaf_sgra_gate_a84f48a.png`
  and `…_enhanced.png` — the partial-render evidence; the
  before-image for the visual acceptance.
- Sibling structure templates: `pkg97`, `pkg98`, `pkg82`,
  `pkg83`, `pkg84`.

### External (read for understanding only — cite, do not mirror)

- Yuan & Narayan 2014 ARA&A 52, 529 §2.1 eqs. 8-16 — the ADAF
  self-similar profiles already implemented in `adaf.h`. Relevant
  here only to confirm the *radial shape* (`n_e ∝ r^(-3/2+s)`,
  `B ∝ r^(-5/4+s/2)`) the integrated emission should inherit.
- Broderick & Loeb 2006; GYOTO `Astrobj/ThinDisk.C` ADAF analog
  — qualitative cross-reference for what a Sgr A*-like ADAF image
  *looks like* (centrally-concentrated glow + shadow), to
  calibrate the "does this read as quasi-spherical" judgement.
  **No code mirrored** (license fence per pkg44; CLAUDE.md §6 —
  this is cross-validation, not algorithm import).

---

## Specification

### Phase 0 — instrument & isolate the cause (~1.5 h, RTX)

**No fix in Phase 0.** First reproduce and measure; do not
pre-judge which candidate cause is dominant.

1. Build per CLAUDE.md "Build & Verification" (show `.pyd` mtime
   vs `git log -1 --format=%cd HEAD`; rebuild if stale; confirm
   `astroray.__file__` is the canonical `build_cuda/Release/`
   path, not a repo-root shadow — memory `stale_pyd_locations`).
2. Render the **synchrotron-jet scene** and the **adaf_sgra
   scene** at identical resolution and at two SPP values an order
   apart (e.g. 4 and 64) — this is the
   `mc-noise-vs-deterministic` discriminator. Save both PNGs to
   `test_results/`.
3. For each, compute and record a **radial intensity profile**:
   azimuthally-averaged luminance in concentric annuli from image
   centre outward. Report the profiles side by side.
4. From the profiles + images, attribute the missing glow to one
   (or a ranked combination) of the candidate causes — judge from
   the data, do not assume:
   - **(a) camera scale vs influence sphere.** The
     `add_black_hole` 3rd arg is `20.0` (adaf) vs `16.0`
     (jet) and bounds the visible structure; `adaf_r_outer` is
     `100.0` M but the GR influence sphere is what actually
     clips emission. Is the emitting volume mostly *outside* the
     influence sphere (so only a thin shell renders → the
     "sliver"), or collapsed to sub-pixel?
   - **(b) `adaf_intensity_scale` too low.** pkg44 Lessons §2
     says actual `n_e`/`B` are 10⁴–10⁵× the research-note
     hand-calc; `1.0e30` was tuned against the wrong magnitude.
     Does the glow read against the background sky at a higher
     scale? (Compare jet's working `1.0e28` with its
     `base_density 1.0e12`.)
   - **(c) radial profile not concentrating in screen space.**
     Does the azimuthal profile actually show inward brightening,
     or is it flat? The `j_total` clamp at `1.0e30` *before*
     `intensity_scale_` in `emissivity` (adaf.h L298) can
     saturate the inner flow so the ρ∝r^(-3/2) gradient never
     reaches the image — a deeper emission/integration bug, not a
     scale knob.
   - **(d) low-res / low-SPP washout.** If the signal-to-noise
     ratio *improves* with √SPP, it is RNG washout and the gate
     scene SPP/res is the lever. If ratios are *stable* across
     the 4-vs-64 SPP pair, it is **not** RNG (memory
     `mc-noise-vs-deterministic`) — do not chase SPP.

Record the Phase-0 measured profiles + the cause attribution in
the PR description before touching any fix code.

### Phase 1 — minimal fix to produce the glow (~2 h, RTX iterate)

Apply the **smallest change** that makes the gate render show a
genuine quasi-spherical glow + dark silhouette, traceable to the
Phase-0 attribution. Per CLAUDE.md §2/§3 — **no speculative
extras**. The change is expected to be one of (in rough order of
locality; the Phase-0 data picks it):

- **Scene-only** (`tests/scenes/adaf_sgra.py`): retune
  `adaf_intensity_scale`, the `add_black_hole` influence-sphere
  arg, `adaf_r_outer`, and/or camera dist/FOV so the emitting
  volume fills a meaningful screen fraction and reads against the
  sky — **calibrated explicitly against `synchrotron_jet.py`**
  (state the jet→adaf scaling argument in the PR). Preferred if
  Phase-0 shows (a) or (b) dominates.
- **Plugin** (`include/astroray/adaf.h`): only if Phase-0 shows
  (c) — e.g. the pre-`intensity_scale_` `1.0e30` clamp flattens
  the inner radial gradient. The minimal correct fix is to clamp
  *after* the scale (or remove the inner-saturation flattening)
  so the ρ∝r^(-3/2) profile survives into the image. Any plugin
  math change MUST cite the Y14 equation it preserves and keep
  the existing pkg44 unit tests green (power-law exponents,
  β-convention — `tests/test_adaf.py`). Do **not** invent a new
  emission model (CLAUDE.md §6).

Iterate on RTX until the render visually matches the
quasi-spherical-glow target. Use the `visual-check` skill against
the synchrotron-jet render as the reference for the qualitative
acceptance.

### Phase 2 — radial-structure integration test (~1.5 h)

Replace the hollow check with a **structural** end-to-end test.
In `tests/test_adaf.py`, replace
`test_tiny_adaf_scene_renders_visible_signal` (do not add a
parallel test — the old assertion is the bug):

- Render the `adaf_sgra` scene through `add_black_hole` (the real
  scene path, not direct `*_at` pybind helpers — that is the
  whole point per `gr-emission-model-wiring-checklist`).
- Compute the azimuthally-averaged radial luminance profile
  (same routine as Phase 0; factor it into a small test helper).
- Assert **all** of:
  1. **Central dark region:** mean luminance of the inner annulus
     (the shadow) is below a fraction of the peak ring luminance
     (the silhouette is genuinely dark relative to the glow —
     not "min≈0 somewhere").
  2. **Concentrated glow:** there exists a bright annulus at
     intermediate radius whose mean luminance is materially
     greater than both the centre and the outermost annulus
     (a *ring/halo of emission around the hole*, the
     quasi-spherical-glow signature — not a single corner
     sliver).
  3. **Outward falloff:** beyond the bright annulus, mean
     luminance decreases monotone-ish with radius (the ρ∝r^(-3/2)
     ADAF profile reaching the image), tolerant to Monte-Carlo
     noise (e.g. allow small non-monotone steps but require net
     decrease from peak annulus to outer annulus).
- Thresholds must be derived from the **Phase-1 fixed render's
  measured profile** with documented margin (cite the numbers in
  the test docstring, pkg82 gate-from-measurement precedent), not
  guessed. The test must FAIL on the pre-fix `main` render
  (demonstrate this — render pre-fix once and show the new test
  red) and PASS on the Phase-1 render.
- Test docstring cites `gr-emission-model-wiring-checklist` and
  pkg44 L243.

Keep resolution/SPP low enough for CI runtime parity with the old
test (pkg44 Lessons §6: 32×32, 4 SPP, <1 s) **only if** Phase 0
proved the structure is SPP-stable (not RNG-washed). If Phase 0
shows the structure needs more SPP to be stable, bump the scene
SPP to the minimum that makes the three assertions robust and
note the runtime (pkg82 precedent: a justified, measured bump is
acceptable; a fudge is not).

### Files to modify

| File | Change |
|---|---|
| `tests/scenes/adaf_sgra.py` | (Likely) retune intensity scale / influence-sphere arg / r_outer / camera, calibrated against `synchrotron_jet.py`. Only the parameters Phase 0 implicates. |
| `include/astroray/adaf.h` | **Only if** Phase 0 attributes the cause to (c). Minimal: fix the pre-`intensity_scale_` clamp / inner-saturation so the radial gradient survives. Cite the Y14 eq. preserved. |
| `tests/test_adaf.py` | Replace `test_tiny_adaf_scene_renders_visible_signal` with the radial-structure test (dark centre + concentrated glow ring + outward falloff). Add the shared radial-profile helper. |
| `.astroray_plan/packages/pkg44-adaf.md` | Append a "pkg99 visual follow-up" note under Lessons referencing this package + the corrected acceptance evidence (do not rewrite pkg44's body). |
| `.astroray_plan/packages/pkg99-adaf-quasi-spherical-glow.md` | Fill in Lessons (Phase-0 profiles table, cause attribution, the chosen fix + measured before/after, the new gate numbers). |

### Acceptance criteria

- [ ] Phase 0 radial-profile table (jet vs adaf, two SPP an order
      apart) committed in the spec Lessons; cause attributed to a
      specific candidate (a)/(b)/(c)/(d) with the supporting
      numbers.
- [ ] Gate render of `adaf_sgra` shows a **quasi-spherical glow
      with a central dark silhouette** — qualitatively matching
      the synchrotron-jet render's emission character (attach
      before `adaf_sgra_gate_a84f48a.png` vs after PNG; use
      `visual-check` against the jet render as the reference).
      This satisfies pkg44 L243.
- [ ] At ṁ/ṁ_Edd = 1e-8 the render is still visibly dimmer than
      a thin-disk render at the same camera (pkg44 L244 not
      regressed by any intensity-scale bump).
- [ ] New `tests/test_adaf.py` radial-structure test: **FAILS on
      pre-fix `main`** (shown explicitly) and **PASSES on the
      fix**; asserts dark centre + concentrated glow ring +
      outward falloff with thresholds traced to the measured
      Phase-1 profile.
- [ ] The hollow `test_tiny_adaf_scene_renders_visible_signal`
      assertion is **gone** (replaced, not duplicated).
- [ ] All existing pkg44 unit tests still green (power-law
      exponents, β-convention, emissivity, bremsstrahlung) —
      `pytest tests/test_adaf.py`.
- [ ] Full local test suite green; call-site sweep done for any
      changed `adaf.h` signature (per CLAUDE.md "Before you
      push") — treat tests/mocks/pybind as call sites.
- [ ] Build-state hygiene shown: `.pyd` mtime vs HEAD,
      `astroray.__file__` canonical path (memory
      `stale_pyd_locations`); RTX gate run on HEAD, not CI-green
      alone (memory `ci_has_no_gpu_runtime_blindspot`).
- [ ] CI green on the PR.

### Hard non-goals

- **Do not re-do the pkg44 scene wiring.** The `enable_adaf`
  branch, the `adaf_`-prefix param mapping, and the render-unit
  camera are correct on `main`. Touch `blender_module.cpp` only
  if Phase 0 *proves* a scene-relied param is not forwarded
  (state the proof if so).
- **No new emission physics / no invented algorithm.** Any
  `adaf.h` change is a clamp/scaling-order correction that
  *preserves* the Y14 profiles already implemented, cited per
  CLAUDE.md §6. No Comptonisation, no polarisation, no new
  transfer model (pkg44 non-goals stand).
- **No retuning to "just pass the metric."** The fix must
  produce a genuine quasi-spherical glow judged visually against
  the jet reference, not merely move `shadow_fraction` /
  `arr.max()`. The structural test exists precisely to forbid a
  hollow pass.
- **No gate/metric softening.** This package *adds* a stricter
  structural assertion; it does not relax `shadow_fraction` or
  any pkg44 numerical gate.
- **No broad scene/test refactor.** Only `adaf_sgra.py`, the one
  `test_adaf.py` test being replaced, and (conditionally) the
  minimal `adaf.h` clamp. Surgical per CLAUDE.md §3.
- **No Blender UI work** (pkg44 deferred it; out of scope here).

---

## Why this matters

pkg44's status line says "done" but its single defining visual
acceptance (L243) is unmet — the ADAF, the EHT's headline
accretion model, currently renders as a dark disk on noise. This
package closes the real gap *and* installs the structural test
that `gr-emission-model-wiring-checklist` says every GR emission
model needs, so the next emitter (and a future ADAF regression)
cannot ship green-but-hollow. It also reinforces the project
invariant — green CI is not evidence for a render-path feature;
only the empirical RTX visual gate is (memory
`ci_has_no_gpu_runtime_blindspot`).

---

## Lessons (filled in on completion)
