# Overnight standup — 2026-07-23 (running)

Follows the day-run standup at
`.astroray_plan/docs/standup/2026-07-21-dayrun.md`, which queued pkg145
(implementation) → pkg146 → pkg144 → pkg138 → pkg141 → pkg124 → pkg121-B
for this run. This file is live — appended on each ship event, finalized
at last call.

## Shipped so far

| PR | What | Result |
|----|------|--------|
| [#513](https://github.com/HendrikGC02/Astroray/pull/513) | pkg145 — Disney diffuse-under-specular energy coupling (grazing overshoot fix) | Energy-grid worst case 1.2048 → 1.004014 across 270 configs (N=65536, gate 1.02); quarantine dict retired, all configs back on the strict gate. HW PASS on RTX (furnace mean 0.992, visuals clean). Cites Cycles `closure_layering_weight` (Apache-2.0), OpenPBR, Kulla & Conty 2017. |
| [#514](https://github.com/HendrikGC02/Astroray/pull/514) | pkg146 — equal-wattage oracle reconciliation (measure-first, doc-only) | Root cause: pkg122's 1.07-1.16x offset was the pre-#505 `set_background_color` guard bug leaking a ~0.2 sky-gradient fallback into "black-background" oracle scenes (additive, light-type-independent; confirmed by ablation stable across 16x SPP). No renderer change needed — pkg139's 0.96-1.01x stands. |
| [#515](https://github.com/HendrikGC02/Astroray/pull/515) | pkg144 — Cycles-style direct/indirect firefly clamp split | Removed always-on sLum>20 cap (biased delta-light NEE); `clampDirect`/`clampIndirect` wired CPU + both GPU megakernels. Bright-sun linearity ~0.9995 stable S=1e6→1e8 (was asymptoting ~14-20); clampIndirect=10 suppresses fireflies below baseline at <0.02% brightness delta. HW PASS on RTX. Un-xfailed `test_direct_and_indirect_clamp_controls`; 2 Disney-highlight xfails re-attributed to Disney-specular territory with measured evidence. |

**Also direct-to-main (no PR, spec filings):**
- pkg147 filed (`833ac60`) — addon CPU-render hang >16px, spin-off finding from pkg146's ablation.
- pkg148 spec filed (`2be223f`) — `integratorName_` empty default causing GPU dedicated-light silent black, spin-off finding from pkg144's HW verification.

## In-flight (not yet shipped)

- **pkg138** — Disney dielectric rough-reflection eval, implementer dispatched.
- **pkg148** — default-integrator empty-string fix, implementer dispatched.

## Action items for owner (running list)

1. The PowerShell harness tool broke session-wide mid-run; all agents fell
   back to Git Bash / `cmd.exe //c` workarounds for the remainder of the
   run.
2. Baseline + after-render assets for the morning report are accumulating
   in `test_results/overnight_report_2026-07-23/`.

<!-- in progress — will be finalized at last call -->
