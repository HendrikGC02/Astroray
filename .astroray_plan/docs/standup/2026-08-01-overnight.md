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
| **#534** | `feat(pkg120)`: two-sided MIS for the spectral integrator (restore BSDF-ray-hits-emitter term) — merged as `7495691` | CI all-pass + RTX HW re-gate PASS (absolute gate 0.9623; full pkg55 web + wavefront bit-identity + 278 furnace cases green); files pkg166 |

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

**pkg120 (PR #534, merged squash `7495691a55ee7dd36e3206f479131255df1ebce3`).**
Restores the BSDF-ray-hits-emitter two-sided MIS term. Scope grew from the
spec's 2 landing sites to **4**, per the pkg55 growing-oracle rule: CPU
`pathTraceSpectral`, wavefront `stage_advance.cu`, plus the two pkg55 CPU
oracles those integrators are pinned against, `reference_pt_production.cpp`
and the shared CPU wavefront `path_kernel.cpp`.

**A quality cycle that overturned its own first diagnosis.** The initial HW
run **FAILED** the PR's own analytic gate (0.745 vs a 0.75 floor). The first
gate-review pass diagnosed this as a transport bug. The fix-implementer
**overturned that diagnosis** with a patch-size control: comparing an 8×8
patch mean against a point oracle on a steep radiance gradient showed the
discrepancy was a sampling-resolution artifact, not a transport error —
verified three independent ways. A different-model (Fable 5) reviewer then
**quantitatively confirmed** the overturn by predicting the patch readings
from pure geometry alone, landing within 0.002–0.024 of the measured values.
The gate was re-scoped to measure a 2×2 patch (the numeric band left
unchanged) and the HW re-gate **PASSED**: absolute gate 0.9623, the complete
pkg55 web plus wavefront bit-identity plus all 278 furnace cases green,
visual inspection clean.

**Follow-up filed: pkg166.** The energy sweep behind this PR surfaced that
furnace/energy suites render with gamma applied, which clamps to `[0,1]` and
is therefore structurally blind to energy-*gain* regressions (see memory
`gamma-furnace-cannot-detect-energy-gain`, first surfaced by pkg160). Filed as
`pkg166-furnace-suites-linear-rendering.md` (commit `9930802`) — not
urgent-tier since nothing is red today, but every future energy-adding change
is under-gated until it lands.

## Session-limit freeze, ~01:35–04:00

The overnight run hit a session-limit gap between roughly 01:35 and 04:00 with
no dispatch activity — no PRs opened or merged in that window, both locks
free at resumption. Work picked back up afterward with pkg120's HW re-gate and
the pkg158/pkg165/pkg166 filings. No corruption or partial state found on
resumption; recorded here as a gap in the timeline, not an incident.

## Closed out (overnight leg)

**Three PRs merged overnight** (#533, #535, #534). No open PRs at the point
the owner extended the run into the day. **Two follow-up specs filed**
(pkg165, pkg166), neither dispatched yet. The owner extended the run through
2026-08-02 rather than closing out; continuation is
`.astroray_plan/docs/standup/2026-08-02-dayrun.md`. Carried into the day:
pkg150 resumed mid-implementation, pkg156 just dispatched, pkg165/pkg166
queued.

<!-- finalized 2026-08-02 -->
<!-- finalized -->
