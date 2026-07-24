# pkg149 — Disney dielectric rough-TRANSMISSION lobe: sample()/pdf() re-derivation (owns the glass[0.3-45] chi² un-xfail)

**Pillar:** 3 (BSDF correctness / MIS density consistency)
**Track:** A
**Codex-paste-ready:** no (sampling-math re-derivation with a chi² + furnace + CPU/GPU parity validation loop)
**Status:** draft PR #522 OPEN — **CPU contract FULLY MET; merge BLOCKED on a low-roughness GPU-only furnace defect** (2026-07-25 last-call state). On the #522 stack (post-pkg154/#521): CPU rough-glass furnace **0.997–0.999** across the grid, transmission peak alignment **0.45°** (gate <2°), the azimuth-swap root cause is closed — everything this spec's CPU-side contract demands. The GPU leg is red at low roughness: HW re-verify @ `e0fe9d8` measured GPU furnace R=0.1 → **0.130** (byte-unchanged by the signed-off frontFace/TIR fix), R=0.3 → **0.283**, R=0.6 → 0.896 (recovered +0.325, 0.0037 short of the floor), R=1.0 → 1.0, vs gate band [0.90, 1.06] — a second, low-roughness-dominant GPU-only defect remains (see "Hardware re-verification 2026-07-25" below). **That defect is now owned by pkg152** (GPU Disney twin divergence — promoted to head the next run's queue); #522 stays a draft until pkg152's conviction lands and the GPU furnace gate is re-measured — no future HW result is asserted here. The chi² glass[0.3-45] un-xfail ownership is unchanged: flips only when alignment AND furnace (CPU+GPU) are green together, `--runxfail`-verified. The `670e583` lineage is on the pushed #522 branch now; keep worktree `Astroray-pkg149` until #522 merges. Do NOT rebase/push the branch while a hardware-verifier is mid-run (memory `hw-verify-branch-freeze`).

> **✅ ADJUDICATION (2026-07-24 ~04:30, architect — overnight last-call ~06:15): Option 1 — HOLD tonight; pkg151 filed; pkg149+pkg151 stack heads the day queue.**
>
> **What the implementer found (accepted as the true root cause):** `sampleGgxVNDF` transcribed pbrt-v4's `Lerp(t, a, b)` disk-warp with two arguments SWAPPED, biasing every sampled half-vector to the azimuth opposite `wo`. Fix measured: transmission sample/pdf peak offset **15.7° → 0.7°** (gate <2°, N=181k); chi² glass[0.3-45] **143,140,779 → 34,988** (~4092×, still red, xfail honestly kept); side effect: pkg150's reflection-candidate masking improves **100% → ~5–22% acceptance** without touching pkg150 scope. Citations pbrt-v4 `scattering.h`/`math.h` (Apache-2.0). This is exactly the class predicted by the spec ("half-vector sign/normalization ... inconsistent between the two functions").
>
> **Why HOLD, not ship (option 3 rejected):** the corrected sampler regresses the rough-glass furnace **0.94–1.0 → 0.09–0.82**. This spec's gates call the furnace **non-negotiable**, and 0.09 means visibly dark rough glass — it would fail the HW visual gate and poison the morning report with a visible regression dressed as a correctness win. The broken sampler was evidently **masking a missing rough-transmission multi-scatter/energy-compensation term** (single-scatter estimator median matches `G1(wi)/ior²` theory almost exactly; three alternative hypotheses ruled out by rebuild-and-measure — full trail in `.astroray_plan/docs/pkg149-disney-rough-transmission-research.md`, worktree). Shipping a correct sampler without the compensation term trades an invisible density bug for a visible energy bug.
>
> **Why not scope-expand tonight (option 2 rejected for tonight, ADOPTED for the day queue):** ~04:20 vs ~06:15 last-call — a compensation-table derivation + furnace re-gate is a multi-hour loop. For the **day queue** this is the recommended path: **pkg151 first (or jointly), then pkg149 rebases/stacks on it, and one PR chain ships peak-alignment + furnace-green together.** The un-xfail of chi² glass[0.3-45] stays owned by this package and may only flip when BOTH alignment and furnace gates are green.
>
> **Critical supersession note (recorded in pkg151):** pkg118's Part-B conclusion "Kulla-Conty multi-scatter for transmission correctly REJECTED" was measured **with the azimuth-swapped sampler** — that rejection is confounded and must be re-measured on the corrected sampler. Do not cite pkg118 Part B as evidence against pkg151's compensation term.
>
> **Worktree/commit `670e583` stays in place for the day team.** Do not delete `Astroray-pkg149`.
**Estimated effort:** M
**Depends on:** pkg138/PR #517 merged (the eval() reflection fix + re-xfailed chi² gate this package inherits). Coordinate with **pkg150** (reflection-candidate masking, same gate's secondary term) and **pkg124** (VNDF, opaque lobe) — all edit `disney.cpp`; serialize merges.

**Origin:** pkg138/PR #517 adjudication (2026-07-23). Measured there: at chi²
glass[0.3-45] the rough transmission lobe carries **~92–96% of sampled weight**
and has a **~16–18° sample/pdf peak mismatch** — `pdf()` peaks at 152° (per
Snell), `sample()` peaks at 168–170°. Transmission was an explicit pkg138
Non-goal; the defect dominates the chi² statistic, so **this package owns
un-xfailing the glass[0.3-45] chi² gate** (with pkg150 as the secondary
contributor — neither closes while the gate is xfail; memory
`xfail-gated-features-must-unxfail`).

---

## Defect

Sampled transmission directions and the reported transmission pdf disagree in
*shape*: a stable ~16–18° angular offset between the sampled-direction density
peak and the pdf's predicted peak. This is a wrong-construction bug (half-vector
/ refraction mapping or its Jacobian), not a tolerance issue — the same class as
pkg138's delta-vs-continuous mismatch, on the other lobe.

## Canonical references (cite in code; CLAUDE.md §6)

- **Walter et al. 2007, "Microfacet Models for Refraction through Rough
  Surfaces," EGSR 2007** — §5.2 sampling (sample the microfacet normal from
  D, refract through it via eq. 40's half-vector convention
  `h_t = −(η_i·ω_i + η_o·ω_o)` normalized) and **eq. 17/38 Jacobian**
  `‖dω_h/dω_o‖ = η_o²·|ω_o·h| / (η_i(ω_i·h) + η_o(ω_o·h))²` — the pdf MUST be
  D(h)·(visible-normal or plain-D weighting, matching the sampler)·this
  Jacobian. A peak offset like 152° vs 168° is the classic symptom of the
  half-vector sign/normalization or the Jacobian denominator being inconsistent
  between the two functions.
- **pbrt-v4 `DielectricBxDF::Sample_f` / `PDF` refraction branches**
  (`src/pbrt/bxdfs.cpp`, Apache-2.0, github.com/mmp/pbrt-v4) — the reference
  implementation pairing `Refract()` through the sampled microfacet normal with
  the matching `dwm/dwi` denominator `Sqr(Dot(wi, wm) + Dot(wo, wm)/eta)`.
  License verified Apache-2.0 (pbrt-v4 repo LICENSE.txt); mirror with
  attribution.
- Implementer's measurement record: `pkg138-disney-dielectric-rough-reflection-research.md`
  (landed with PR #517) — contains the peak-mismatch evidence and N≥100k
  histograms.

## Fix contract

1. Re-derive `sample()`'s transmission construction and `pdf()`'s transmission
   term **from the same half-vector convention and the same Jacobian**
   (Walter eq. 40 + eq. 17/38, or the pbrt-v4 equivalent) — one derivation,
   two call sites; no independent re-tuning of either side.
2. Mirror on the GPU dielectric/closure-graph path (memory
   `gpu-dielectric-lowers-to-closure-graph`); RTX parity gate.
3. Do NOT touch the reflection candidate's same-hemisphere masking — that is
   pkg150; keep the diffs disjoint so the two chi² contributions stay
   attributable.

## Gates

- **chi² glass[0.3-45] un-xfailed and green** (run with `--runxfail` first;
  never accept XFAIL as evidence). If pkg150 has not landed, quantify the
  residual reflection-masking contribution and show transmission's term is
  fixed (peak alignment <2°, N≥100k); the un-xfail may then be joint with
  pkg150 — state which PR flips it.
- Sampled-vs-pdf transmission peak alignment demonstrated (histogram overlay,
  before/after — the 152°-vs-168° figure goes green).
- **Furnace/white-furnace + rough-glass furnace unchanged**; glass caustic +
  prism refbank scenes visually verified (memory
  `general-photon-loop-needs-solid-glass`).
- CPU==GPU parity on a rough-glass render (per-channel mean-ratio band).
- Build evidence per CLAUDE.md (`.pyd` mtime, canonical path).

## Non-goals

- Reflection-candidate masking compensation (pkg150).
- VNDF swap for the opaque specular lobe (pkg124).

## Hardware re-verification 2026-07-25 (verifier notes, folded in from the `Astroray-pkg149` worktree by the architect at last-call; the prior `19d4e9f` verification section it references is committed on the PR #522 branch and arrives at merge — pr-merger: union/dedupe the two HW sections, main's Status wins)

**Scope:** focused re-check bound to `e0fe9d816f50b8c03feb881dfbf71b868bedc552`
(PR #522 draft stack), after a signed-off GPU-twin fix targeting the `19d4e9f`
FAIL — frontFace-aware Fresnel in `gpu_disney_roughReflectionEval` (TIR was
unreachable for internal/glass→air reflection events) + restoration of #518's
merged GPU fixes that the stale base had reverted. Only GPU-side code changed;
focused protocol (furnace gate + two regression guards), sole CUDA job under
the orchestrator GPU lock. RTX 5070 Ti; `.pyd` mtime confirmed at the fix
commit; `astroray.__file__` at the worktree's `build_cuda/Release/`.

**Verdict: FAIL — gate still red, but materially and unevenly recovered.**

| Gate | Result |
|---|---|
| `test_disney_smooth_glass_furnace_cpu` / `_gpu` | PASS / PASS |
| `test_disney_rough_glass_furnace_converges` | PASS |
| `test_disney_rough_glass_furnace_energy_cpu` | PASS |
| **`test_disney_rough_glass_furnace_energy_gpu`** | **FAIL (hard gate)** — see table |
| `test_pkg123_disney_metal_gpu_cpu_parity.py` | PASS 7/7 (no regression from the fix) |
| `test_gpu_caustic_parity.py` | PASS (1 passed, 1 xfailed — pre-existing flat-prism limitation) |

GPU furnace before/after the frontFace/TIR fix (gate band [0.90, 1.06]):

| Roughness | `19d4e9f` | `e0fe9d8` | Δ | In band? |
|---|---|---|---|---|
| R=0.1 | 0.1295251101 | 0.1295252442 | ~0.0000 | No — byte-unchanged, still deeply broken |
| R=0.3 | 0.2690328062 | 0.2832989395 | +0.014 | No |
| R=0.6 | 0.5711650848 | 0.8962805271 | +0.325 | No — 0.0037 short of the floor |
| R=1.0 | 0.9705997109 | 1.0 | +0.029 | Yes |

The fixed sub-lobe (internal/TIR-adjacent reflection events) is sampled more
often as roughness grows, so its recovery scales with roughness; a separate,
still-unfixed, low-roughness-dominant GPU-only bug remains → **pkg152**.
Visuals: R=0.1/0.3 GPU discs still dark/speckled grey against the white
furnace (unchanged severity by eye), R=0.6 mostly blends (consistent with the
0.896 near-miss); CPU legs correct at all roughness; no NaN/fireflies/mode
regressions. **Parity-render caveat:** the original `19d4e9f` parity-render
script was not preserved; an independent scene reconstruction produced a
different R=0.6 trend and is recorded as a secondary, uncontrolled data point
only — the furnace pytest gate is the authoritative measurement. Full
numbers: `test_results/overnight_report_2026-07-24/pkg149_hw_numbers.json`
key `reverify_e0fe9d8` + `pkg149_furnace_R{0.1,0.3,0.6}_{gpu,cpu}_e0fe9d8.png`.
Verdict comment: https://github.com/HendrikGC02/Astroray/pull/522#issuecomment-5073008663
