# pkg64-gpu gate drift — HW-sweep evidence + recommendation (2026-05-31)

**Status:** evidence gathered on RTX; **gate changes left for owner adjudication**
(NEXT_STAGE_REPORT §2 open item 2 — the prior closeout left the floors UNCHANGED
"pending that adjudication"; this note supplies the documented evidence the owner
asked for, and does NOT change any gate).

## Measured on RTX 5070 Ti, 2026-05-31 (clean build of HEAD = `ce90316` + Wave-5 fixes)

| Gate | Floor | Measured now | Prior baseline | Test |
|------|-------|--------------|----------------|------|
| pkg64-gpu GPU↔CPU parity SSIM | ≥ 0.85 | **0.8352** | 0.9277 | `test_pkg64_gpu_cpu_parity.py::test_pkg64_gpu_cpu_parity_ssim` |
| pkg64-gpu Phase-3 prism PSNR delta | ≥ −0.5 dB | **−0.59 dB** (PSNR sms 35.00, base 35.59) | +2.19 dB | `test_pkg64_gpu_phase3_default_integrator.py::test_pkg64_gpu_phase3_prism_psnr_floor` |

Both numbers reproduce the NEXT_STAGE_REPORT §2 values exactly (0.835 / −0.59 dB).
CI is GPU-blind so both merged green; only the HW sweep sees them.

## Root cause (confirmed)
The Wave-5 GPU clear-glass energy fix + Heitz-2018 VNDF rough-transmission rewrite
(PR #404, `8b7184b`) **legitimately changed the GPU dielectric output for the better**
(white-furnace 0.705 → 0.991 flat). The two pkg64-gpu SMS gates measure the FROZEN
SMS-GPU caustic path against, respectively, the live CPU SMS render (SSIM parity) and
a stored high-spp prism reference (PSNR). Both now read below floor because the GPU
output shifted while their comparison targets did not. **Visual check:** the GPU prism
SMS render and the GPU/CPU parity renders are plausible dim caustics (a faint central
caustic spot) — no gross regression; the divergence lives in the dim caustic residual.

## The two gates need DIFFERENT fixes

1. **PSNR floor gate — stale stored reference.** This gate compares the SMS render to a
   stored high-spp `ref` captured pre-Wave-5. Re-blessing that reference (re-render at
   high spp on current HEAD) is a clean reference update after a correctness fix — NOT a
   floor change — and should restore a positive delta. *Recommendation: re-bless the
   high-spp reference; keep the −0.5 dB floor.* This is owner-blessable because it is a
   reference update, not a gate weakening.

2. **GPU↔CPU parity SSIM gate — live divergence on a frozen path.** No stored reference;
   it compares a fresh GPU SMS render to a fresh CPU SMS render. The GPU improved, the CPU
   SMS path is unchanged, so they agree less (0.835). Because **SMS-GPU is frozen/legacy**
   (owner 2026-05-30: photon map is the canonical caustic path on CPU+GPU; pkg113 is the
   GPU photon-map port), this parity will only drift further as the canonical paths evolve.
   *Two owner options, both documented (not a silent floor drop):*
   - **(a) xfail(strict=False) as legacy** — honest for a frozen path; the gate stops
     reporting a phantom regression and points to pkg113 as the canonical replacement.
   - **(b) recalibrate the floor** to ~0.80 with the Wave-5 justification, keeping a coarse
     regression guard. Fragile: a frozen-path gate against an evolving CPU path will keep
     re-breaking.
   *Author recommendation: (a) xfail-as-legacy* — consistent with the freeze decision; the
   real GPU-caustic correctness gate becomes pkg113's photon-map parity.

## What was NOT done (owner gate)
No gate floor was lowered and no reference was re-blessed. Per the prior closeout's
"pending owner adjudication" and the project rule "do not silently lower a floor," the
owner picks: re-bless PSNR reference (recommended), and (a) xfail vs (b) recalibrate for
the SSIM parity gate. Once chosen, it is a ~10-line test edit + one re-render.
