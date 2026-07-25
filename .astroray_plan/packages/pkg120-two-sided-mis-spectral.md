# pkg120 — Two-sided MIS for the spectral integrator (restore the BSDF-ray-hits-emitter term)

**Pillar:** 3 (light transport / NEE + MIS correctness)
**Track:** A (CPU-gated furnace/ground-truth test runs on CI; wavefront leg needs RTX verify)
**Codex-paste-ready:** no (transport-correctness change with a ground-truth gate; CPU + wavefront mirror)
**Status:** open — **dispatchable**. pkg55 Phase C completed via PR #524 (2026-07-25): both megakernels are deleted and the wavefront is now the only GPU path, so the two-sided term lands in exactly the two places this spec targets (CPU `pathTraceSpectral` + the wavefront `stage_advance.cu` emissive-hit block), not four — the blocker the old Status recorded has dissolved.
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

- [ ] A — CPU `pathTraceSpectral` two-sided term + light-tree-consistent pdf reconstruction.
- [ ] B — wavefront (GPU) mirror; CPU↔GPU lockstep verified.
- [ ] C — large-near-light ground-truth gate (direction + magnitude); no-regression sweep.

---

## Lessons

*(Fill in after the package is done.)*
