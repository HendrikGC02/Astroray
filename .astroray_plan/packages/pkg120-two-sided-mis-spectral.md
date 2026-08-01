# pkg120 — Two-sided MIS for the spectral integrator (restore the BSDF-ray-hits-emitter term)

**Pillar:** 3 (light transport / NEE + MIS correctness)
**Track:** A (CPU-gated furnace/ground-truth test runs on CI; wavefront leg needs RTX verify)
**Codex-paste-ready:** no (transport-correctness change with a ground-truth gate; CPU + wavefront mirror)
**Status:** done (PR #534, 2026-08-02 — `7495691`. Two-sided MIS landed in 4 sites, not the spec's 2: CPU `pathTraceSpectral` + wavefront `stage_advance.cu`, plus the two pkg55 CPU oracles those integrators are pinned against, `reference_pt_production.cpp` and the shared CPU wavefront `path_kernel.cpp` (pkg55 growing-oracle rule). Quality cycle: initial HW FAIL on the analytic gate (0.745 vs 0.75) was first diagnosed as a transport bug, then OVERTURNED by an 8x8-patch-mean-vs-point-oracle control (a steep-gradient sampling artifact, not a transport error) — verified 3 independent ways and quantitatively confirmed by an independent Fable-5 review predicting the patch readings from geometry alone within 0.002-0.024. Gate re-scoped to a 2x2 patch measurement with the band unchanged; HW re-gate PASS — absolute gate 0.9623, full pkg55 web + wavefront bit-identity + 278 furnace cases green, visual clean. Sweep motivated pkg166 (furnace suites render gamma, cannot detect energy gain).)
**Estimated effort:** M (add one MIS term in two mirrored places + a ground-truth gate proving direction and magnitude)
**Depends on:** ~~pkg55 Phase C (megakernel removal — single spectral pipeline first)~~ **SATISFIED by PR #524 (2026-07-25)**. There is now exactly one CPU path (`pathTraceSpectral`) and one GPU path (the wavefront), so the change lands in two places, not four; the RGB `bsdf_mis` branch and `multiwavelength_kernel.cu` referenced below no longer exist.

---

## Goal

**Before:** Astroray's spectral integrator uses **one-sided MIS**. The NEE
light-sample contribution is down-weighted by the power heuristic
`wt = lightPdf² / (lightPdf² + bsdfPdf²)` (`src/gpu/gpu_nee.cuh:207-210`,
returns `f·L·(wt / lightPdf)`), but the **complementary BSDF-ray-hits-emitter
term is dropped** for diffuse bounces: a surface's emitted radiance is added only
when `bounce == 0 || wasSpecular` (`src/gpu/wavefront/stage_advance.cu:201`;
CPU `pathTraceSpectral` uses the same `wasSpecular` gate — `include/raytracer.h`
around the spectral path loop). The BSDF-side MIS weight
`bsdfPdf² / (lightPdf² + bsdfPdf²)` is never applied to anything. This is faithfully
mirrored across CPU / MW-megakernel / wavefront — so the three agree with each
other — but **all three are biased relative to ground truth**. The only two-sided
`bsdf_mis` branch in the codebase lives in the RGB megakernel
(`src/gpu/path_trace_kernel.cu:348-372`,
`direct += bs.f·Le·powerHeuristic(bs.pdf, lightPdf)/(bs.pdf+ε)`), which pkg55
Phase C **deletes** — so after Phase C the production spectral path has *no*
two-sided MIS anywhere.

**After:** The spectral integrator is **two-sided**, matching Cycles. When a
BSDF-sampled continuation ray hits an emitter at a diffuse bounce, the integrator
adds `throughput · Le · w_B`, where `w_B = powerHeuristic(bsdfPdf, lightPdf_hit)`
and `lightPdf_hit` is the light-sampling pdf (selection × area-to-solid-angle,
including the light-tree traversal pdf) that would have generated that same
emitter hit. Combined with the existing light-side term, direct illumination
converges to the unbiased result for **all** light sizes. Implemented CPU-first in
`pathTraceSpectral`, mirrored into the wavefront shade/emissive-hit handling
(GPU). A ground-truth gate proves both the fix **direction** (one-sided reads
dark, two-sided matches) and its **magnitude** on a large-near-light scene.

---

## Root cause (the bias, stated precisely)

The power heuristic combines two unbiased estimators of the direct-light integral
`L = ∫ f(ω)·Le(ω) dω` — light sampling and BSDF sampling — with weights
`w_L(ω) = pdf_L² / (pdf_L² + pdf_B²)` and `w_B(ω) = pdf_B² / (pdf_L² + pdf_B²)`,
where `w_L + w_B = 1` for every direction. The correct MIS estimate is:

```
L ≈ w_L·f·Le/pdf_L   (light-sampled leg)   +   w_B·f·Le/pdf_B   (BSDF-sampled leg)
```

Astroray computes **only the first leg** (`gpu_nee.cuh:210` applies `w_L` to NEE)
and **drops the second** (the `bounce==0||wasSpecular` gate discards BSDF-sampled
emitter hits on diffuse bounces). The expected value of what we compute is
therefore `∫ w_L(ω)·f·Le dω`, which is short of the true `L` by exactly
`∫ w_B(ω)·f·Le dω` — the BSDF-weighted portion of the light. So the estimator is
**biased low (dark)**, and the deficit scales with how much of the light's
contribution comes from directions where BSDF sampling dominates (`w_B` large):

| Light regime | `bsdfPdf` vs `lightPdf` | Dropped fraction `w_B` | Visible effect |
|---|---|---|---|
| Compact / distant light | `bsdfPdf ≪ lightPdf` | ≈ 0 | Unbiased in practice — why this has gone unnoticed. |
| Large / close area light (softbox) | `bsdfPdf ~ lightPdf` | O(0.3–0.5) | **Biased dark** — a real Cycles-parity gap for the most common studio-lighting setup. |

The C2 MIS audit (`.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md §4`) verified
the one-sidedness is **internally consistent** (wavefront == CPU == MW to
tolerance) and correctly flagged that this consistency is *relative to the
reference*, not to ground truth; and that the RGB `bsdf_mis` branch — the only
two-sided implementation — is RGB-only and slated for deletion. pkg120 is the
follow-up that closes the ground-truth gap in the surviving spectral pipeline.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

Add the BSDF-side MIS term to the spectral emissive-hit handling. The
implementation already exists in RGB form and in Cycles; mirror it into the
spectral path.

### A. CPU first — `pathTraceSpectral` (`include/raytracer.h`)

At a **diffuse** bounce (`bounce > 0 && !wasSpecular`), when the continuation ray
hits an emissive surface, instead of dropping the emission, add:

```
color += throughput · Le_spec(lambdas) · powerHeuristic(bsdfPdf_prev, lightPdf_hit)
```

- `bsdfPdf_prev` = the BSDF pdf that generated the continuation ray (already
  available from the sample at the previous bounce; park it in the loop state
  next to `wasSpecular`, mirroring how the RGB kernel carries `bs.pdf`).
- `lightPdf_hit` = the light-sampling pdf **for this emitter as seen from the
  previous shading point** — selection pdf × solid-angle pdf
  `(dist² / (NdotWi · area))`, and the **light-tree traversal pdf** when a light
  tree is resident (so the two legs use consistent selection probabilities). This
  is exactly the `lightPdf` reconstruction the RGB branch does at
  `path_trace_kernel.cu:355-372`. Reuse the existing `LightList` / light-tree pdf
  query rather than re-deriving it.
- Keep the `bounce==0 || wasSpecular` **full-emission** path unchanged (camera and
  post-specular rays still take the whole `Le`, `w_B = 1` there because there is no
  NEE leg competing).

**Cite:** Veach 1997 "Robust Monte Carlo Methods for Light Transport Simulation"
§9.2 (power heuristic) — already cited at `gpu_nee.cuh:208` and
`path_trace_kernel.cu:132-136`; Cycles
`intern/cycles/kernel/integrator/shade_light.h` +
`intersect_closest.h::light_sample_from_intersection()` (Apache-2.0) — the
canonical "BSDF ray hit a light → reconstruct its light-sampling pdf → apply
`w_B`" ordering; Cycles `kernel/light/sample.h::light_sample_mis_weight` /
`power_heuristic`.

### B. Mirror into the wavefront (GPU)

Apply the same term in the wavefront's emissive-hit handling
(`src/gpu/wavefront/stage_advance.cu:201` block, the diffuse branch). The
wavefront already parks `path_light_pdf` / `path_mis_pdf` as SoA fields from the
C2 audit (`pkg55-phase-c-plan-2026-07.md §4`), and already computes
`gpu_mw_powerHeuristic` at shade — so the BSDF-side weight reuses machinery that
is present, not new. The continuation-ray `bsdfPdf` must be carried in the SoA to
the next intersect/shade (add a `path_bsdf_pdf` field if the C2 instrumentation
field is not already load-bearing for transport — promote it from
instrumentation to transport, or add a sibling).

CPU and GPU must stay in **lockstep** (same power-heuristic form, same
`lightPdf_hit` reconstruction incl. tree pdf) — verify with the existing
CPU↔GPU wavefront-diff parity gate.

### C. Ground-truth gate (proves direction + magnitude)

Add a **large-near-light** scene where the one-sided bias is large and
measurable:

- **Oracle:** a high-spp **NEE-only-without-MIS-weight** estimate (set `w_L = 1`,
  no BSDF leg) is an *unbiased* estimator of direct illumination — just higher
  variance. Render it at high spp as the ground-truth reference (self-contained;
  no Cycles dependency required for the gate to pass). Optionally cross-check
  against Cycles at equal settings as confirmation, not as the gate oracle.
- **Assertions:**
  1. **Direction:** the current one-sided integrator reads measurably **dark**
     vs. the oracle on the large-near-light scene (quantify the deficit — this is
     the magnitude the fix must recover).
  2. **Fix:** the two-sided integrator matches the oracle within a tight
     tolerance (e.g. mean radiance ratio ∈ [0.98, 1.02]), while the one-sided
     value stays outside it.
  3. **No regression:** a compact/distant-light scene is unchanged (both
     estimators already agreed there — the fix must not perturb it beyond noise),
     and the white-furnace / existing NEE-MIS parity gates stay green.

Structure the scene set like the pkg118 furnace gate (CPU-gated, CI-runnable). The
wavefront leg is verified on RTX against the CPU result via the wavefront-diff
harness.

---

## Acceptance criteria

- [ ] Two-sided MIS term added to `pathTraceSpectral` (CPU) and the wavefront
      emissive-hit handling (GPU), gated to diffuse bounces; `bounce==0 ||
      wasSpecular` full-emission path unchanged.
- [ ] `lightPdf_hit` reconstruction includes selection × solid-angle **and the
      light-tree traversal pdf**, consistent with the NEE leg (no
      selection-pdf mismatch between the two legs).
- [ ] Ground-truth gate: one-sided reads dark vs. the high-spp NEE-no-MIS oracle
      on the large-near-light scene; two-sided matches within tolerance
      (direction + magnitude both asserted).
- [ ] No regression: compact-light scene unchanged; white-furnace gate and the
      C2 `PostNEE_MIS` per-stage parity gate stay green; CPU↔GPU wavefront-diff
      parity holds for the new term.
- [ ] CPU and GPU spectral paths kept in lockstep (same heuristic + pdf
      reconstruction, verified by the parity gate).
- [ ] Research/citation note: Veach 1997 §9.2 + Cycles `shade_light.h` /
      `light_sample_from_intersection` recorded in the code and in
      `.astroray_plan/docs/` (extend the C2 MIS note rather than starting a new
      one if convenient).

---

## Non-goals

- **Not a re-architecture of NEE.** The light-side NEE leg and its power-heuristic
  weight are already correct; this package only adds the missing BSDF-side leg.
- **Not the RGB megakernel.** Its `bsdf_mis` branch is deleted by pkg55 Phase C;
  do not resurrect or maintain it. pkg120 restores two-sidedness in the
  **spectral** pipeline only.
- **Not env-map / background MIS.** Background-as-light MIS is a separate concern
  (the spectral path handles env on miss without NEE — `pathTraceSpectral` comment
  "No env NEE"); this package is surface-emitter MIS. File a follow-up if
  env-light MIS parity is wanted.
- **Not ReSTIR.** ReSTIR-DI reservoir reuse (pkg55 Phase C Session C6) has its own
  weighting; leave it untouched.
- **No new light types or sampling strategies.** Uses the existing `LightList` /
  light-tree pdf query.

---

## Provenance

Filed from the **pkg55 Phase C Session C2 MIS audit (2026-07-18)** finding
(`.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md §4`; companion audit doc lands
in the C2 PR). The audit proved the wavefront's one-sided MIS is internally
consistent with the CPU/MW reference and correctly identified that (a) the only
two-sided `bsdf_mis` implementation is RGB-only and is deleted by Phase C, and (b)
one-sidedness is unbiased for compact lights but biased-dark for large/near area
lights — a genuine Cycles-parity gap for softbox-style lighting. This package is
the roadmap follow-up the audit flagged: close the ground-truth gap in the
surviving spectral pipeline, after Phase C unifies to a single CPU + single GPU
spectral path.

---

## Progress

- [x] A — CPU `pathTraceSpectral` two-sided term + light-tree-consistent pdf reconstruction
      (`lights.pdfValue` reuse). Mirrored into the two CPU oracles the pkg55
      parity/trip-wire gates pin: `reference_pt_production.cpp` (bit-exact
      trip-wire) and the shared CPU wavefront kernel `path_kernel.cpp`
      (+ `bsdf_pdf_prev` carried through the CPU wavefront SoA round-trip).
- [x] B — wavefront (GPU) mirror in `stage_advance.cu` (`gpu_reconstruct_light_pdf`
      in `gpu_nee.cuh`, `path_bsdf_pdf` SoA field); CPU↔GPU lockstep by
      construction. **Awaits team-lead RTX build + HW verification** (subagent
      cannot build the CUDA .pyd).
- [x] C — large-near-light ground-truth gate
      (`tests/test_pkg120_two_sided_mis.py`): direction (one-sided dark via
      `max_depth=1`), magnitude (two-sided ≈ analytic `ρ·L_e·(R/d)²` via
      `max_depth=2`), no-regression (compact light). CPU-gated on CI.

---

## Lessons

## Hardware verification 2026-08-02

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, CUDA v12.8, OptiX 9.1.0.
**OS:** Windows 11 Enterprise 10.0.26200.
**Worktree/SHA:** `.claude/worktrees/pkg120` pinned to `4f0c2a7fce4d31a057354808e3d40634092a1c81` (PR #534 head). Foreground build via `build_cuda_worktree.bat` succeeded; up-to-date rebuild (the delta from the previously-built SHA was test-only, no C++ recompile needed). `.pyd` import verified from the worktree `build_cuda/` path (not a shadow copy).

**Context:** an earlier verifier run stopped at `test_two_sided_matches_analytic_formfactor` (0.745 vs 0.75 tolerance), since diagnosed as an 8x8-patch-vs-point-oracle measurement artifact and fixed test-only in `4f0c2a7`. This is the full sweep the earlier run never reached.

### Pass/fail table

| Gate | Result | Measured |
|---|---|---|
| `test_two_sided_recovers_large_near_light` | PASS | one_sided=0.74320, two_sided=0.95497, ratio=1.2849 (gate: >1.20) |
| `test_two_sided_matches_analytic_formfactor` | PASS | L_e=3.9974, analytic=1.27917, one_sided=0.87924 (one_sided/analytic=0.6874, gate <0.85), two_sided=1.23093 (two_sided/analytic=0.9623, gate 0.75<r<1.35) |
| `test_no_regression_distant_compact_light` | PASS | one_sided=0.00763, two_sided=0.00763, ratio=1.0000 (gate 0.94<r<1.12) |
| `test_reference_pt_production_parity` | PASS | max diff 6.258487701416016e-07 (tol 1e-05) |
| `test_reference_pt_oracles_equivalent` | PASS | R ratio=1.0006, G ratio=0.9918, B ratio=0.9868 (all within 5%) |
| `test_cpu_wavefront_ssim_parity` | PASS | R ratio=1.0023, G ratio=1.0000, B ratio=0.9989 (all within 5%) |
| `test_cpu_wavefront_nonzero_output` | PASS | mean=0.1316, max=0.4988, 760/768 nonzero |
| `test_cpu_wavefront_diffuse_light_bit_identity` | PASS | max_abs_diff = 0.0 exactly, 0 diverging fields, all stages BIT-IDENTICAL |
| `test_cpu_wavefront_lambertian/metal/dielectric/disney/closure_graph/thin_glass/session_n1_bit_identity` (+ determinism variants) | PASS (14 tests) | all max_abs_diff = 0.0, 0 diverging fields |
| `test_cpu_to_cpu_baseline_bit_identity` | PASS | max diff = 0.0, 0 diverging fields |
| `test_cpu_to_gpu_threshold_gate` | PASS | PostInit ULP=2 p99.9=1.435664e-07; PostIntersect ULP=32 p99.9=2.170602e-06; PostShade p99.9=2.165780e-06; PostLightSample p99.9=2.211559e-06; PostRR p99.9=0.0 |
| `test_post_nee_mis_gate` (C2 PostNEE_MIS) | PASS | Tier1 CPU-wf<->CPU-ref exact: 0 diverging fields; Tier1b CPU power-heuristic max residual 6.932e-08 over 99 rows; Tier2 GPU power-heuristic max residual 7.472e-08 over 97 rows (tol 1e-05) |
| `test_wavefront_dedicated_light_nee[point_only/area_only/mixed]` | PASS | WF/CPU = [0.9965,0.997,0.9967] / [0.9965,0.9972,0.9967] / [0.9973,0.9972,0.9971] |
| `test_dielectric_glass_furnace`, `test_disney_rough_glass_furnace`, `test_disney_energy_conservation` (278 param cases total) | PASS | all green, no regression |

**Skipped (pkg153 quarantine, per dispatch instructions):** `test_megakernel_open_env_scene_mean_ratio`, `test_megakernel_world_max_bounces_env_gate`, `test_gpu_wavefront_final_image_mean_ratio` — R-channel ratio drift, owned by pkg153, unrelated to pkg120.

### Energy-gate linearity note

The dielectric/Disney furnace tests (`test_dielectric_glass_furnace.py`, `test_disney_rough_glass_furnace.py`) render with `apply_gamma=True` (4th positional `render()` arg `True`). Per the gamma-furnace-cannot-detect-energy-gain finding, gamma clamps to [0,1] and cannot detect an energy **gain** — only loss. pkg120 *adds* energy (recovers the previously-dropped BSDF-side MIS leg), so a hypothetical energy-gain regression from this change would NOT be caught by these two furnace tests; they passing is necessary but not sufficient evidence against over-counting. The pkg120 gate itself (`test_pkg120_two_sided_mis.py`) is the one that correctly measures gain, and it renders `apply_gamma=False` (linear) by design.

### Visual inspection

Rendered the large-near-light scene (R=1.6, d=2.0, matching the gate scene) at 256x256/256spp for both `max_depth=1` (one-sided) and `max_depth=2` (two-sided): floor directly under the sphere is smoothly bright in both, fading gradually outward with no fireflies, no banding/quantization steps, no NaN pixels (`np.isnan` false on both), no dark ring near the light, and no mode regression (still monochrome/RGB as expected, not spectral). The two-sided render is visibly brighter in the floor region near the light base, consistent with the measured +28-38% energy recovery. No visual anomalies.

### Anomalies worth watching

- None found in this sweep. The `test_two_sided_matches_analytic_formfactor` patch-size sensitivity (8x8 vs 2x2 vs point) documented in the test file's own comment is a measurement-methodology property of the analytic oracle, not a rendering defect — reconfirmed here since transport correctness was independently triple-checked per that comment (center-point accumulator, single-pixel match, independent Python cosine-MC oracle at 0.9999x analytic).
