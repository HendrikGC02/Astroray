# Overnight standup — 2026-08-01 (night → 2026-08-02 morning)

Follows `.astroray_plan/docs/standup/2026-07-26-dayrun.md`. At that hand-off,
main was clean and synced, no open PRs, both locks free. Queued and specced
but not yet dispatched: pkg163 (spectral-vs-RGB compensation colour-space
parity), pkg158 (Step-0 reconciliation on a post-pkg160 SHA), pkg150, pkg156,
pkg120, pkg88-D, pkg119-B/C, and pkg155 Phase 2 (opportunistic GPU gap-filler).
Still owner's from that hand-off: re-pinning `MAX_GLOSSY_PARITY_MSE` and
deleting the dead `stage_shade_metal.cu` — both since resolved (see
`.astroray_plan/packages/` and PR #532, `6a8b867`).

## Shipped

| PR | What | Gate |
|---|---|---|
| **#533** | `feat(pkg163)`: GPU metal spectral response per-wavelength for CPU/GPU colour-space parity — merged as `b036ac9` | CI all-pass + RTX HW PASS (7/7 gates); retires pkg160's roughness-0.9-only `[0.95,1.10]` band, restores standard `[0.95,1.05]` at all roughnesses |
| **#535** | `docs(pkg158)`: Step 0 Disney-metal remainder reconciliation, Outcome A — merged as `7c340f6` | Doc-only; near-delta discrepancy re-measured and superseded (0.60–0.77 does not reproduce); files pkg165 for the out-of-scope uniform-dim finding |

## Notes

**pkg163 (PR #533, merged 2026-08-01T14:31:49Z UTC, `b036ac93029b147ad94957a8dfa52fe3ebc2601c`).**
Direction A shipped per the spec's fix contract: GPU metal now builds its
spectral response per-wavelength (`gpu_metal_eval_spectral`), mirroring
`MetalPlugin::evalSpectral` instead of computing in RGB and upsampling once.
Retires pkg160's asymmetric roughness-0.9 `[0.95,1.10]` band exception —
parity is back to a uniform `[0.95,1.05]` at every roughness, HW-confirmed at
r=0.9 with R/G/B mean ratios 1.0153/1.0171/1.0112.

Full quality cycle worth recording: initial HW run **FAILED** on the decisive
chromatic-spread control (0.0133 vs the ≤0.01 bound, single seed, 256 spp).
The gate-failure diagnostic proved this was MC noise in the statistic itself,
not a real defect — multi-seed + 2560-spp scaling showed chromatic and
neutral converging to the same ~0.0006 floor. The test was re-statisticized
(2560 spp, 4-seed-averaged spread) with the **bound left unchanged at
≤0.01** — the fix is a better statistic, not a loosened gate. A different-model
(Fable 5) sign-off followed, then the HW re-gate **PASSED** at a seed-averaged
spread of 0.0025.

Owner-visible, informational: the pkg163 chromatic gate now reports a
seed-averaged spread statistic rather than a single-seed one; the numeric
bound itself was never changed. Diagnostic detail lives in the spec's
"Hardware verification 2026-08-02" section
(`.astroray_plan/packages/pkg163-metal-spectral-compensation-colorspace-parity.md`).

**pkg158 (PR #535, merged 2026-08-01T15:03:06Z UTC, `7c340f65e2076da6554b932d8e806990aefd8c1b`).**
Step 0 verdict is **Outcome A: the historical near-delta discrepancy is
SUPERSEDED, not reconciled by measurement.** The two "credible" prior readings
(0.60–0.77 vs ~1.0) turned out to be the **same test**
(`test_pkg123_disney_metal_gpu_cpu_parity.py`) run against **different
builds** — not two independent measurements in conflict. Re-measured once on
`b036ac93` (post-#518/#523/pkg160/pkg163): linear near-delta ratios 0.92–0.98
across the full roughness sweep, no near-delta cliff, everything inside the
`[0.90, 1.10]` band. pkg152's Symptom-(a) table now carries a supersession
note rather than an open discrepancy. No code changed — doc-only PR, spec
already flipped to `done` by the implementer inside the PR (verified, not
re-edited here).

**Out-of-scope finding, filed forward as pkg165.** A **uniform ~5–8%
Disney-metal GPU-dim** persists across every roughness (0.92–0.98,
channel-ordered R>G>B) — inside the current band, so nothing is red, but
unexplained and not near-delta-specific. Filed as
`pkg165-disney-metal-uniform-dim-residual.md` (architect commit `d02fe07`),
scoped diagnosis-first with a 2×2 material×scene un-confounding matrix, marked
open/dispatchable but not urgent-tier.

**In flight, not yet mergeable:** PR #534 (pkg120) HW-FAILED its analytic
form-factor gate. Diagnosed as a real solid-angle-dependent transport bug in
the BSDF-sampled emitter-hit leg, not a gate miscalibration. Fix in progress
in the worktree; not pushed; awaiting sign-off flow. pkg150 implementation has
also started. Will update this section as either lands or is escalated.
