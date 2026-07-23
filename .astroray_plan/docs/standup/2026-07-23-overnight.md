# Overnight standup — 2026-07-23 (08:00 → 2026-07-24 morning)

Follows the day-run standup at
`.astroray_plan/docs/standup/2026-07-21-dayrun.md`, which queued pkg145
(implementation) → pkg146 → pkg144 → pkg138 → pkg141 → pkg124 → pkg121-B
for this run. This run cleared pkg145/146/144/138 off that chain.

## Shipped (4 code + 1 doc merges, chronological)

| PR | What | Result |
|----|------|--------|
| [#513](https://github.com/HendrikGC02/Astroray/pull/513) | pkg145 (`531f5126`) — Disney diffuse-under-specular energy coupling (grazing overshoot fix) | Energy-grid worst case 1.2048 → 1.004014 across 270 configs (N=65536, gate 1.02); quarantine dict retired, all configs back on the strict gate. HW PASS on RTX (furnace mean 0.992, visuals clean). Cites Cycles `closure_layering_weight` (Apache-2.0), OpenPBR, Kulla & Conty 2017. |
| [#514](https://github.com/HendrikGC02/Astroray/pull/514) | pkg146 (`7c5be868`) — equal-wattage oracle reconciliation (measure-first, doc-only) | Root cause: pkg122's 1.07-1.16x offset was the pre-#505 `set_background_color` guard bug leaking a ~0.2 sky-gradient fallback into "black-background" oracle scenes (additive, light-type-independent; confirmed by ablation stable across 16x SPP). **No renderer bug** — pkg139's 0.96-1.01x stands. |
| [#515](https://github.com/HendrikGC02/Astroray/pull/515) | pkg144 (`1af7eca7`) — Cycles-style direct/indirect firefly clamp split | Removed always-on sLum>20 cap (biased delta-light NEE); `clampDirect`/`clampIndirect` wired CPU + both GPU megakernels. Bright-sun linearity ~0.9995 stable S=1e6→1e8 (was asymptoting ~14-20); clampIndirect=10 suppresses fireflies below baseline at <0.02% brightness delta. HW PASS on RTX. Un-xfailed `test_direct_and_indirect_clamp_controls`; 2 Disney-highlight xfails re-attributed to Disney-specular territory with measured evidence. |
| [#517](https://github.com/HendrikGC02/Astroray/pull/517) | pkg138 (`9bb058fc`) — rough dielectric reflection lobe in Disney `eval()` | Walter 2007 / pbrt-v4 port + GPU twin. **ADJUDICATED partial-scope**: merged as-is, chi² gate transferred to new specs pkg149/pkg150 rather than blocking on full closure. HW PASS. |

**Specs filed (all on main, no code change):**
- pkg147 (`833ac60`) — addon CPU render hang >16px, spin-off finding from pkg146's ablation.
- pkg148 (`2be223f`) — `integratorName_` empty default causing GPU dedicated-light silent black, spin-off finding from pkg144's HW verification.
- pkg149 + pkg150 (`d21006e`) — chi² gate transferred out of pkg138 (rough dielectric reflection lobe still red).
- pkg151 (`9734173`) — rough-transmission multi-scatter compensation, filed alongside the pkg149 HOLD adjudication.

## Parked / in-flight at close

- **PR #516 (pkg148)** — HELD by pr-merger. Everything green (CI + HW PASS, GPU/CPU ratio 0.998) but it adds a new public binding `get_integrator()`; needs owner approval on the API addition, then it is a one-command squash merge.
- **pkg149** — root cause FOUND: a pbrt-v4 `Lerp` azimuth-swap bug in `sampleGgxVNDF` (peak error 15.7° → 0.7°, chi² 143M → 35k, ~4092× improvement). **HELD unpushed** (architect adjudication `9734173`) because the corrected sampler exposes a furnace-energy deficit (0.94 → 0.09-0.82) attributable to missing transmission multi-scatter, not the sampler fix itself. Local commit `670e583` preserved on worktree `Astroray-pkg149` — **do not delete this worktree**, the commit is not on any pushed branch.

## Next-run queue (architect-ordered)

pkg151 → pkg149 (stacked as one chain — the chi² un-xfail only flips green with both pkg151 and the corrected pkg149 sampler in place) → pkg150 (re-baseline after the chain lands) → pkg141 as the alternate if the chain stalls.

**Note:** pkg118 Part-B's prior finding "multi-scatter rejected for transmission" is **CONFOUNDED** — it was measured on the swapped (buggy) sampler. Must be re-measured on `670e583`'s corrected sampler; this caveat is recorded in both the pkg151 and pkg149 specs.

## Action items for owner

1. **Decide PR #516's `get_integrator()` binding.** Approve → `gh pr merge 516 --squash` (already green, HW-verified).
2. **Morning HTML report:** report: see `overnight_report.html` in `test_results/overnight_report_2026-07-23/` (link to be added once built).
3. **The PowerShell harness tool broke session-wide mid-run** (exit 1 on everything, including `Write-Output`); all agents fell back to Git Bash / `cmd.exe //c` workarounds for the remainder of the run. Worth a fresh-session check + hook audit — see agent memory `powershell-hook-bom-or-ascii` for the known failure class.
4. **Process lesson recorded to memory (`hw-verify-branch-freeze`):** PR #517's branch moved 3× during active HW verification; the verdict survived only because the code was byte-identical across moves. Freeze branches during HW runs going forward.
5. **Task Scheduler orchestrator task is still DISABLED** (the team drove tonight's loop manually); re-enable if you want scheduled ticks to resume.
6. **Worktree cleanup:** `Astroray-pkg122` kept deliberately (holds oracle evidence). `Astroray-pkg145`/`144`/`138`/`146`/`148` remain in place with merged branches — safe to GC at leisure. **`Astroray-pkg149` must be KEPT** (holds the unpushed `670e583` commit above).

<!-- finalized -->
