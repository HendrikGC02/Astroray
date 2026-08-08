# pkg178 Stage 3 — D4 decision + anisotropy/alpha fork designs (Stage-3b plan)

**Author:** architect, 2026-08-09. **Status:** researched recommendation for the
lead/owner; design only, nothing implemented. Companion to
`pkg178-native-cycles-principled-bsdf.md` (spec, D4 fork),
`pkg174-per-material-kernel-dispatch-design.md`,
`pkg174-register-pressure-ledger.md`.

---

## 1. The measured problem (lead, 2026-08-09, branch `pkg178-stage3`)

Stage 3 added coat/sheen/approx-SSS/emission lobes and raised
`kMaxPrincipledLobes` 4→7 (`gpu_materials.h:1519`). Against a clean main
(Stage 2) build, identical CMake config:

| Metric | main (Stage 2) | Stage 3 | Delta |
| --- | --- | --- | --- |
| Non-principled wavefront scene (metal+diffuse+dielectric+area, 512², 128 spp, d8) | 648 ms | 987 ms | **+52%** |
| `stageShadeBucketed` STACK (cuobjdump) | 4456 B | 7696 B | **+3240 B** |
| `stageShadeNeeMis` / `stageAdvance` / `stageAdvanceQueued` STACK | — | — | each +3240 B |
| REG (all four fused kernels) | 254 | 255 | at ceiling |
| `stageShadeLambertian`/`Metal` (dedicated) | REG:107/STACK:56 | byte-identical | 0 |

This violates the spec's hard gate ("No wavefront perf regression on
non-principled scenes") — the D4 fork the spec reserved for the owner.

### 1.1 Mechanism — why a scene with zero principled materials pays

- All `gpu_principled_*` functions are `__device__ inline` and reach the fused
  kernels through `shadePathSlot` → `gpu_material_sample_spectral` /
  `_eval_spectral` / `_pdf` → the `GMAT_CLOSURE_GRAPH` arm →
  `gpu_closure_graph_is_principled` (`gpu_materials.h:1999`). Everything is
  **one compiled kernel**; ptxas allocates registers and sizes the stack frame
  globally across all arms. At the REG:254 saturation point (memory
  `wavefront-shade-kernels-register-saturated`; ledger: NEE alone and the BSDF
  union alone each independently pin 254 on a ~95-reg base), any growth in any
  arm degrades the *shared* allocation — spill decisions leak into the hot
  non-principled paths, and the frame (local-memory footprint per thread) grows
  for every launched thread.
- The `GPrincipledLobe lobes[7]` array itself is only ~392 B (7 × ~56 B; Stage
  2 was 4 × ~48 B ≈ 192 B). **The array accounts for ~200 B of the +3240 B.**
  The dominant growth is live-state/spill from the newly inlined lobe code
  (sheen LTC frame+fetch, coat Beer `powf`×3, the enlarged assemble/eval/pdf
  bodies) instantiated at every call site (NEE eval, pdf, sample re-eval, RGB
  + spectral variants) inside four kernels.
- Production per-bounce kernel set (from `gpu_wavefront_snapshot.cu:1492–1574`)
  is `stageQueueIota → stageRegen → stageIntersectQueued →
  stageShadeBucketed → stageShadow`. So `stageShadeBucketed` (4456→7696) is
  the perf vector; `stageAdvance`/`stageAdvanceQueued`/`stageShadeNeeMis` are
  snapshot/legacy instrumentation (no in-tree production caller —
  `stage_advance.cu:1232` note) and only bloat gate binaries.
- Note the measurement scene **contains a dielectric**, which lowers to
  `GMAT_CLOSURE_GRAPH` on GPU (memory `gpu-dielectric-lowers-to-closure-graph`).
  So "non-principled" scenes still *execute* the closure-graph arm — any fix
  must remove principled code from the closure-graph path those scenes run,
  not merely from unlaunched buckets.

---

## 2. D4 options assessed

### (a) Footprint reduction / streaming lobes — feasible, insufficient, a treadmill

`gpu_pr_assembleLobes` is deterministic in `(closure, rec, wo)`, so the array
can be eliminated: eval/pdf become a single streaming loop (assemble lobe *i*,
eval, accumulate, advance the running layering weight); sample becomes two
streaming passes (pass A accumulate `W = Σ sel`, draw the single `xi`, pass B
re-walk to the selected lobe) — this preserves the CPU RNG stream exactly (one
uniform, same as `principled.cpp` / `gpu_pr_chooseAndSampleDir:1885`).
Restructuring is real work but mechanical.

Why it is not the answer:
- The array is ~6% of the measured +3240 B. The spill is dominated by inlined
  code live-range growth, which streaming only partially addresses; at REG-254
  saturation ptxas' spill choices are chaotic and the yield is unpredictable
  without build-and-measure (which memory `gpu-perf-ab-clock-drift` makes slow
  to do honestly).
- Even a perfect result only buys back *this* stage. Stage 4 (thin-film Airy
  per-λ) and the alpha lobe (7→8) regrow the frame; every future lobe re-runs
  the fight. The principled path is *specified* to keep growing.
- Verdict: **rejected as the D4 answer**; retained as an optional later lever
  *inside* the isolated principled kernel if the principled-scene budget
  (§3, PR-2 gate) comes in unacceptable.

### (b) Compile-time isolation of the principled arm (pkg174-family) — RECOMMENDED

The pkg174 per-material-kernel-dispatch design doc is honest that per-bucket
dispatch cannot raise occupancy (NEE alone pins REG:254). **But occupancy is
not what D4 needs.** D4 needs non-principled scenes to compile-and-run a shade
kernel that does not contain the principled code at all — restoring main's
codegen for them. Compile-time specialization does exactly that, and it is the
only option that closes this bug-class permanently (Stage 4 thin film, alpha
lobe, future lobes then tax only the principled instantiation).

**Recommended minimal form — `template<bool HasPrincipled>`, host-selected,
NOT the full per-material dispatch:**

1. Add a `bool HasPrincipled` template parameter to `shadePathSlot` (which is
   already `template<bool Deferred>` since pkg174 Lever 3) and thread it
   through `gpu_material_sample_spectral` / `_eval_spectral` / `_pdf` /
   `gpu_material_sample` down to the `GMAT_CLOSURE_GRAPH` arm, where
   `if constexpr (HasPrincipled)` guards the `gpu_closure_graph_is_principled`
   branch and all `gpu_principled_*` calls. For `HasPrincipled == false` the
   compiler instantiates the closure-graph interpreter (dielectric, thin-glass,
   conductor closures) **without one byte of principled code**.
2. `scene_upload.cu` sets a host-side flag when any uploaded material lowers to
   a `GCLOSURE_PRINCIPLED` closure (it already inspects every closure). The
   `launchStageShadeBucketed` launcher (and the snapshot/NeeMis/advance
   launchers, for gate parity) selects the instantiation off that flag. Two
   instantiations of each affected kernel exist in the cubin; only one
   launches per scene.
3. No scatter/bucket changes, no new `GMaterialType` (all the enum traps the
   spec lists — `stage_advance.cu:1034` clamp, snapshot duplicate,
   `photon_caustic.cu:116` — stay untouched), no change to the RNG stream, no
   image change at all: for non-principled scenes the removed code was
   unreachable, so `tests/wavefront_diff/` bit-identity must hold exactly.

Expected outcome:
- `stageShadeBucketed<false>`: STACK **≤ 4456 B** (likely below main, since
  Stage-2's principled code is compiled out too); non-principled perf back to
  ~648 ms (gate: within measurement noise of main under the ledger's
  burn-in-P0 + min-of-10 protocol).
- `stageShadeBucketed<true>`: ≈ today's 7696 B; principled scenes pay it and
  get their own measured budget per the spec.
- Mixed scenes (principled + others) run everything in the `<true>` kernel —
  acceptable and documented; if a mixed-scene budget later fails, the
  escalation path is the *effective-bucket* sub-split (scatter closure-graph
  paths into "principled" vs "plain closure-graph" buckets and launch each
  bucket's specialization — a strict extension of this change and a first
  installment of pkg174's full `template<int MatType>` design, which remains
  filed for the plugin roadmap and is **not** a prerequisite here).

### (c) Raise the perf ceiling — rejected

There is no ceiling to raise: REG:254 is architectural, spill is the
consequence, and the "ceiling" that would move is the perf *gate* — i.e.
institutionalizing +52% on every non-principled render. pkg168 was parked over
exactly this class; pkg174's ledger shows the micro-levers (noinline,
launch_bounds) are exhausted/inert. Rejected outright.

**D4 recommendation: (b), minimal `HasPrincipled` form.** Isolation-by-scene
content is architecturally honest (the spec's own "principled scenes get their
own measured budget" line presupposes it), permanently future-proofs Stages
3b/4, and is the smallest change that can meet the hard gate deterministically
rather than probabilistically.

---

## 3. Anisotropy fork — confirm faithful anisotropic Smith, with a sharpened reason

**Confirmed, and strengthened.** The lead's lean (faithful aniso Smith; iso is
the exact limit; a discontinuous aniso-only branch is a parity wart) is right,
and code-reading shows the re-validation is not a regrettable cost but an
overdue parity *fix*:

- **Astroray's Stage-1/2 reflect lobes do not match Cycles today.**
  `smithG_k` (`principled.cpp:95,531,922`; `gpu_pr_smithG_k`
  `gpu_materials.h:1330`) is the Disney/UE4 Schlick-GGX `k=(r+1)²/8`
  approximation. Cycles uses the exact height-correlated Smith form for BOTH
  reflection and transmission
  (`bsdf_microfacet.h`, `bsdf_microfacet_eval`):
  `f = reflectance·common / (1 + λO + λI)` with
  `λ_GGX(t) = 0.5(√(1+t) − 1)`, `t = α²·max(1/cos²θ − 1, 0)`
  (`bsdf_lambda`/`bsdf_lambda_from_sqr_alpha_tan_n`), anisotropic via
  `bsdf_aniso_lambda: t = (α_x²V_x² + α_y²V_y²)/V_z²`.
- **The G1s already match.** `smithG1_GGX` = `2cosθ/(cosθ + √(α²+cos²θ−α²cos²θ))`
  is algebraically identical to `1/(1+λ_GGX)`; the transmission lobe and VNDF
  pdf are therefore already Cycles-exact per-G1. The divergences are exactly
  two: reflect lobes use Schlick-k instead of `1/(1+λI+λO)`, and the
  transmission lobe combines `G1·G1` (separable, `principled.cpp:553,565`)
  where Cycles is height-correlated `1/(1+λI+λO)`.
- **Iso is literally the a→0 limit in Cycles' own code**:
  `bsdf_microfacet_eval` branches
  `if (alpha_x == alpha_y || is_transmission) { alpha2 = alpha_x*alpha_y; iso
  formulas } else { aniso formulas }` — the aniso λ and D
  (`bsdf_aniso_D: H /= (α_x, α_y, 1); (1/π)/(α_x α_y ·|H|⁴)`) reduce exactly
  at `α_x = α_y`. Mirroring this branch structure IS the faithful port; a
  Schlick-k-iso / Smith-aniso hybrid would be discontinuous at
  `anisotropic → 0⁺` and permanently off-parity at 0.
- **Parameter mapping** (Cycles `svm/closure.h`, `CLOSURE_BSDF_PRINCIPLED_ID`):
  `aspect = sqrtf(1 − anisotropic·0.9)`; `α_x = roughness²/aspect`,
  `α_y = roughness²·aspect`; tangent `T` from the tangent input, rotated
  `T = rotate_around_axis(T, N, anisotropic_rotation·2π)`; aniso active only
  when `anisotropic > 0` and a tangent is valid. Aniso applies to the
  **metallic and specular** lobes; **transmission collapses to isotropic**
  with `α² = α_x·α_y` (the `|| is_transmission` branch above); coat/sheen/
  diffuse stay isotropic.
- **No new energy-compensation tables.** Cycles feeds its iso E-table with the
  geometric-mean roughness: `rough = sqrtf(sqrtf(alpha_x·alpha_y))`
  (`microfacet_ggx_preserve_energy`). At iso this is exactly `roughness`
  (√(√(r²·r²)) = r), so `gpu_ggxE`/`Eavg`/`CompensationFactor` are reused
  unchanged with that scalar.
- **VNDF sampling generalizes mechanically**: `gpu_pr_sampleGgxVNDF`
  (`gpu_materials.h:1400`) already stretches by `(α·x, α·y)`; the aniso form is
  `(α_x·x, α_y·y)` exactly as Cycles `microfacet_ggx_sample_vndf(local_I,
  alpha_x, alpha_y, rand)`. RNG draw count unchanged (2 uniforms) → stream
  alignment with CPU preserved.
- **Real prerequisite — shading tangent plumbing.** `HitRecord`/`GHitRecord`
  carry only an *arbitrary* `buildOrthonormalBasis` frame
  (`include/astroray/manifold/surface_partials.h:7` states this explicitly).
  Anisotropy needs a stable UV-aligned tangent (Blender's default is the
  active-UV tangent) + the rotation. `surface_partials.h` already computes
  dPdu for spheres/triangles (manifold lineage) — reuse it to populate a real
  shading tangent, gated on the material actually requesting aniso so
  isotropic scenes pay nothing.

### Re-validation plan (which gates re-open, and how iso stays exact)

The iso baseline **changes by design** (Schlick-k → height-correlated Smith) —
this is a deliberate re-bless toward Cycles, expected to *tighten* pkg119b /
pkg104 parity bands, not loosen them. Sequenced in two PRs so failures
attribute cleanly:

1. **Reflect-lobe G swap + aniso (specular, metallic; coat gets the G swap,
   stays iso).** Re-run: per-lobe CPU furnace floor+ceiling (linear, upper
   bound asserted — memory `gamma-furnace-cannot-detect-energy-gain`); pkg121
   chi² for specular/metallic/coat at `anisotropic ∈ {0, 0.5, 0.9} ×
   rotation {0°, 45°}` (NDF-sampled lobes: the G swap does not touch their
   pdf, but aniso D changes sampling and pdf together); CPU↔GPU byte-twin per
   lobe (pkg119b runbook build — both legs change in lockstep); rough-metal
   live-Cycles A/B (pkg129) re-run — bands expected to tighten; an
   **iso-continuity gate**: render `anisotropic = 1e-4` vs `0`, per-channel
   mean-ratio within noise band (the two code branches must agree in the
   limit, mirroring Cycles' own branch). Iso-limit exactness is by
   construction: mirror Cycles' `alpha_x == alpha_y` branch, so iso scenes
   run the iso formulas verbatim — the re-blessed iso baseline is the gate
   reference thereafter.
2. **Transmission height-correlated G fix** (separable `G1·G1` →
   `1/(1+λI+λO)`, iso, `α² = α_x·α_y`). Isolated because it re-opens the
   sensitive glass gates: rough-glass furnace (memory
   `rough-glass-residual-is-multiscatter` lineage), delta-glass energy, the
   quadrature-dominated `chi2_disney_glass` xfail (memory) — re-run with
   `--runxfail`, re-pin bands.

New parity scenes for the pkg119b harness: aniso sweep pair
(anisotropic 0/0.3/0.6/0.9 × rotation 0/45°) on metal + specular-dielectric
spheres, per-channel mean-ratio (not SSIM — memory
`ssim-wrong-gate-for-independent-rng`).

---

## 4. Alpha transparent lobe — integrator-safe design

**Cycles reference** (`svm/closure.h`, `CLOSURE_BSDF_PRINCIPLED_ID`):

```c
const float alpha = saturatef(stack_load(stack, data.alpha));
if (alpha < 1.0f) {
  bsdf_transparent_setup(sd, weight * (1.0f - alpha), path_flag);
  weight *= alpha;
}
```

**first, before every other closure** — sheen, coat, emission, metallic,
transmission, specular, diffuse all operate on the alpha-scaled weight
(emission is `emission_setup(emission·weight)` with the attenuated weight).
The transparent closure (`bsdf_transparent.h`): `eval` returns
`zero_spectrum()` with `pdf = 0` (never NEE-evaluated); `sample` returns
`wo = −wi`, labels `LABEL_TRANSMIT | LABEL_TRANSPARENT`, with matched
`pdf = eval = 1e6` (near-delta convention, ratio 1 — i.e. `f/pdf = weight`).

**Astroray design — a delta lobe inside the existing one-sample-MIS mixture:**

1. New lobe kind `GPR_TRANSPARENT`, `kMaxPrincipledLobes` 7→8. **Hard
   dependency: the D4 isolation (§2b) must land first** — the growth then
   taxes only the `<true>` principled instantiation.
2. `gpu_pr_assembleLobes` / CPU `assembleLobes`: at the very top (before
   sheen, matching Cycles' order):
   `if (c.alpha < 1): lobes[n++] = { kind=TRANSPARENT, weight=(1−alpha)·W₀,
   isDelta=true, sel=max(luminance(weight),1e-4) }; weight *= alpha;`
   (`W₀` = the entry weight, 1). At `alpha = 1` **no lobe is assembled and
   the code path is byte-identical to today** — the validated delta-glass
   gates are untouched by construction, exactly as Cycles' `if (alpha < 1)`.
3. `chooseAndSampleDir`: transparent arm sets `wi = −wo`, `isDelta = true`,
   `pdfInternal = 1`, `deltaRefract = false`, `eta = 1` (no medium change, no
   η² factor — Cycles applies none). Sample result: `f = L.weight`,
   `pdf = qj·1` → throughput `f/pdf = weight_T/qj`.
4. **Why this cannot break delta-glass energy** (the entanglement concern
   discharged): the delta path's estimator is `f/pdf = weight_j/qj` with
   `qj = sel_j/W` (`gpu_principled_sample:1977-1984`). The one-sample-MIS
   mixture is unbiased for ANY positive selection distribution:
   `E[contrib] = Σ_j qj·(weight_j/qj) = Σ_j weight_j` — `W` cancels inside
   each term, so "W≈1" was never load-bearing (Veach 1997 §9.2.4 / PBRT-v4
   §9.5, the citations `principled.cpp` already carries). Adding a transparent
   lobe changes `W` and every `qj`, which reallocates *variance*, never
   *expectation*. The glass lobe's `f/pdf` is `weight_glass/q_glass` before
   and after. Additionally, since glass lobes and transparency co-occur only
   when the user sets `alpha < 1` on a glass material, all existing gates
   (alpha = 1) are bit-identical.
5. Eval/pdf mixture loops already skip `isDelta` lobes
   (`gpu_principled_eval:1842`, `_pdf:1854`) → transparent contributes 0 to
   NEE bsdf-eval and to the MIS pdf — matching Cycles' zero eval/pdf exactly.
   No integrator change needed there.
6. Integrator semantics: the sampled transparent continuation sets
   `rec.isDelta = true` (the existing delta path), so a light hit through
   alpha accumulates with MIS weight 1 — correct for an unchanged ray. Ray
   origin offsets to the far side using the same offset helper the refraction
   branch uses (geometric normal, transmission side).
7. **Declared approximations** (Stage-0 table updates, pkg119-C report line):
   (i) transparent bounces consume regular `max_depth` (Cycles has a separate
   `transparent_max_bounce`, default 8) — stacked alpha surfaces may
   terminate early; follow-up if the parity scenes show it; (ii) **NEE shadow
   rays treat alpha surfaces as opaque occluders** — Cycles traces transparent
   shadows; this is an integrator feature (shadow transparency loop), out of
   lobe scope, visible on alpha-carded foliage. Named follow-up package;
   declared band on the alpha parity scene until then.
8. Gates: alpha=1 byte-identity across the existing suite; white-furnace at
   `alpha ∈ {0.25, 0.5, 0.75}` must hold 1.0 linear floor+ceiling (exact
   partition: `E = (1−α)·1 + α·E_bsdf`); delta-glass energy gates re-run
   green with `--runxfail` (memory `xfail-gated-features-must-unxfail`);
   alpha-card parity pair vs Cycles with the shadow gap declared; CPU↔GPU
   twin; chi² not applicable (delta lobe).

---

## 5. Stage-3b plan (ordered; one PR per numbered step)

**PR-0 (docs, this file):** decision record + Stage-0 map row updates
(aniso rows → in-progress Stage-3b; alpha row → Stage-3b lobe with declared
shadow/depth gaps). No code.

**PR-1 — D4 fix on MAIN: `template<bool HasPrincipled>` isolation.**
Base on main (Stage 2), not the stage3 branch — it is independently valuable
(compiles Stage-2's principled code out of non-principled scenes too) and
gives clean attribution. Scope: template plumbing through `shadePathSlot` +
`gpu_material_{sample,eval,pdf}{,_spectral}` + closure-graph dispatch; upload
flag; launcher selection (production + snapshot launchers).
Gates: `tests/wavefront_diff/` bit-identity (both flag states); cuobjdump
REG/STACK for BOTH instantiations of all four kernels in the PR (register
report — required on every GPU merge); `<false>` stack ≤ main's 4456 B;
non-principled perf A/B vs main within noise (burn-in-P0 + min-of-10, ledger
protocol); principled Stage-2 scene renders unchanged (mean-ratio gate).
Estimated effort: M.

**PR-2 — rebase `pkg178-stage3` onto PR-1; merge Stage 3.**
The lobes land inside the `<true>` instantiation only. Gates: the original
Stage-3 gate set (per-lobe furnace floor+ceiling linear, chi² for sheen,
CPU↔GPU twins, coat/sheen/SSS parity scenes) PLUS the re-measured D4 pair:
non-principled scene == main (hard, the 648 ms scene), and a **recorded
principled-scene budget** (new baseline number in the PR — the spec's "own
measured budget"). If that budget is unacceptable to the lead, apply §2a
streaming *inside* the isolated path as a follow-up lever — measure, don't
assume.

**PR-3 — tangent plumbing (prereq for aniso).**
Populate a UV-aligned shading tangent (reuse `surface_partials.h` dPdu;
Gram-Schmidt vs N; sphere radial fallback) on CPU `HitRecord` + GPU
`GHitRecord`, gated on material need. Gates: bit-identity when no material
requests it; tangent-continuity visual check on a UV sphere.

**PR-4 — anisotropy part 1: reflect lobes.**
Height-correlated Smith swap (specular/metallic/coat) + aniso D/λ/VNDF for
specular+metallic + `aspect` mapping + rotation. Gates per §3 item 1
(furnace, chi² aniso grid, byte-twin, iso-continuity, pkg129 A/B re-run,
aniso parity sweep into pkg119b). Every formula cites
`bsdf_microfacet.h`/`svm/closure.h` per CLAUDE.md §6.

**PR-5 — anisotropy part 2: transmission G correlation fix**
(`G1·G1` → `1/(1+λI+λO)`, `α² = α_x α_y`). Gates per §3 item 2 (glass
furnace, delta-glass energy, glass chi² with `--runxfail`, re-pinned bands).

**PR-6 — alpha transparent lobe** per §4 (kMax 7→8; depends on PR-1/PR-2).
Gates per §4 item 8.

**Closeout:** full RTX hardware sweep (CI has no GPU — memory
`ci_has_no_gpu_runtime_blindspot`), showcase render inspection, docs-updater
round: STATUS/spec status flips, Stage-0 map rows to their final states.

**Sequencing notes.** pkg174's full `template<int MatType>` per-bucket
dispatch is NOT a dependency — PR-1 is a compatible subset and folds into it
naturally when the plugin roadmap needs it (the closure-graph bucket kernel
then simply carries the `HasPrincipled` specialization pair). The
effective-bucket sub-split (separate scatter bucket for principled) is the
named escalation if mixed-scene budgets fail; not built speculatively.

---

## 6. Citations

- Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h` (Blender main,
  Apache-2.0): `bsdf_lambda_from_sqr_alpha_tan_n`, `bsdf_lambda`,
  `bsdf_aniso_lambda`, `bsdf_D`, `bsdf_aniso_D`, `bsdf_G` (height-correlated
  `1/(1+λI+λO)`, used for reflection AND transmission in
  `bsdf_microfacet_eval`; pdf uses `G1(wi) = 1/(1+λI)`),
  `microfacet_ggx_sample_vndf(local_I, α_x, α_y, rand)`,
  `microfacet_ggx_preserve_energy` (`rough = sqrtf(sqrtf(α_x·α_y))` into the
  iso E-table).
- Cycles `intern/cycles/kernel/svm/closure.h`, `CLOSURE_BSDF_PRINCIPLED_ID`:
  transparency-first `bsdf_transparent_setup(sd, weight·(1−alpha)); weight *=
  alpha;`, `aspect = sqrt(1 − 0.9·anisotropic)`, `α_x = r²/aspect`,
  `α_y = r²·aspect`, `rotate_around_axis(T, N, rot·2π)`,
  `emission_setup(emission·weight)` on the attenuated weight.
- Cycles `intern/cycles/kernel/closure/bsdf_transparent.h`:
  `wo = −wi`, `pdf = eval = 1e6` (ratio 1), zero eval/pdf outside sampling,
  `LABEL_TRANSMIT | LABEL_TRANSPARENT`.
- Veach 1997 §9.2.4 / PBRT-v4 §9.5 — one-sample MIS unbiasedness (the W-cancel
  argument in §4.4).
- Heitz 2018 (VNDF), Kulla & Conty 2017 (multiscatter tables) — existing
  lineage, unchanged.
- Laine, Karras, Aila 2013 — wavefront codegen/material-coherence argument
  (via `pkg174-per-material-kernel-dispatch-design.md`).
- Measured data: lead's 2026-08-09 A/B (this file §1);
  `pkg174-register-pressure-ledger.md` (REG attribution, measurement
  protocol).
