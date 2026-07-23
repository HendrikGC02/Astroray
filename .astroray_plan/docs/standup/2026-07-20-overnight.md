# Overnight standup — 2026-07-20 → 2026-07-21

**Note:** a session-limit outage ran roughly 02:50–08:00 local, pushing the
close of this round past the normal last-call. This file supersedes the
tick-generated `.astroray_plan/docs/standup/2026-07-20.md` (which only
captured the pre-outage PR list, #485–#496, and the in-flight dispatch
markers for pkg55-C6/pkg123 at tick time — reconciled below).

## Shipped (merged)

| PR | What | Result |
|----|------|--------|
| [#496](https://github.com/HendrikGC02/Astroray/pull/496) | Pre-overnight dispatch doc refresh | C5 merged, pkg122 unblocked, ReSTIR_PT license verified |
| [#499](https://github.com/HendrikGC02/Astroray/pull/499) | pkg125 — CPU `path_tracer` honors `set_wavelength_range` | CPU 24/24 + GPU spot-check; independent review SIGN-OFF |
| [#497](https://github.com/HendrikGC02/Astroray/pull/497) | pkg55-C6a — ReSTIR reservoir SoA infrastructure | HW PASS 64/0 on RTX at b76465c (see HW verifications); Phase C now 6/7 sessions merged |
| [#501](https://github.com/HendrikGC02/Astroray/pull/501) | pkg124 — license correction: Cycles `bsdf_microfacet.h` is BSD-3-Clause, not the previously-labeled license | docs-only |
| [#502](https://github.com/HendrikGC02/Astroray/pull/502) | pkg138 spec — Disney dielectric delta-vs-continuous sample/pdf mismatch (filed from #498 adjudication) | docs-only |
| [#504](https://github.com/HendrikGC02/Astroray/pull/504) | pkg139-141 specs — AREA orientation, delta-sun black, GPU near-delta metal (overnight verifier findings) | docs-only |

**Also direct-to-main (no PR):**
- Agent fleet moved to Claude 5 models (`15b1449`)
- Codex routing retired — owner no longer uses Codex (`2d0e42a`)
- Standup + pkg55 phase-C plan doc commits (this file's own commit chain)

## HW verifications

- **#497 (pkg55-C6a)** — verified twice on the RTX 5070 Ti workstation (owner-corrected 2026-07-21; this run was NOT on the travel laptop): `ed31cb1` then `b76465c` (post-fix). Full wavefront + RNG + ReSTIR regression suite, zero CUDA errors, 10 PNGs visually clean.
- **#500 (pkg122, HELD — see below)** — GPU==CPU 0.997–0.998 across all light types; live-Cycles oracle gross factors (0.13×/3.6×/14×/near-black) ELIMINATED. CI pass, caustic regression fixed. Residual ~10% vs Cycles is owner-reserved Defect-4 (see action items).
- **#498 (pkg123, PARKED — see below)** — chi² consistency green (163 → 0 real failures over four fix rounds), but CI caught render-level regressions reproduced locally.
- **#503 (pkg55-C6b, PARKED — see below)** — HW gate FAIL: temporal reuse produces no variance reduction.

## Final dispositions (not shipped)

1. **#498 (pkg123 Disney chi²) — PARKED.** CI caught 4 render-level regressions reproduced locally: Disney metal ~2.8× too dark vs reference metal, clearcoat energy gain 1.0206. chi² consistency is green (163 → 0 real failures over four rounds) but the eval()-side D changes altered rendered radiance. **Next session must reconcile eval-vs-sample usage of the canonical D** (analysis in the PR comment thread). All downstream adjudications (pkg138/pkg141/pkg124 boundaries) remain valid regardless of this fix.
2. **#500 (pkg122 light energy) — HELD by pr-merger checklist.** The PR relaxes the G4 spot gate floor (`center_lum` 0.3 → 0.1), an owner-decision trigger. Everything else is green: CI pass, HW PASS (GPU==CPU 0.997–0.998, Cycles oracle gross factors eliminated), caustic regression fixed. **OWNER DECIDES:** accept the relaxation (a byproduct of the physically-correct P/(4π) spot recalibration) or require a recalibrated tighter band.
3. **#503 (pkg55-C6b) — PARKED, HW gate FAIL.** Temporal reuse produces no variance reduction (0.0724 vs 0.0719) AND the gate test still carried its xfail marker (masking the failure). The 0.5s runtime suggests the GPU DI driver may not be reached at all. **Debug dispatch reachability first** next session, before revisiting the reuse math.

## Action items for owner (final list)

1. **Defect-4 emission-convention decision** — RGBIlluminant-vs-RGBUnbounded. Blocks both a tight Cycles band and #500's ~10% residual. Evidence: pkg122 verifier report + oracle renders in `Astroray-pkg122/test_results/pkg122_cycles_oracle/`.
2. **#500 G4 gate-floor decision** — accept the `center_lum` 0.3 → 0.1 relaxation or require a recalibrated tighter band (see disposition 2 above).
3. **pkg139 AREA-orientation bug** — artist-placed default-rotation area lights point AWAY from scenes in the Blender addon. Biggest remaining owner-visible dimness contributor. Spec'd and dispatchable now.
4. **#498 eval-side reconciliation** — eval-vs-sample usage of the canonical Disney D term (see disposition 1 above).
5. **#503 ReSTIR reuse debugging** — dispatch-reachability first, then temporal-reuse variance math (see disposition 3 above).

**Orchestrator note:** the Task Scheduler orchestrator remains DISABLED (it was disabled before this run started too — not a change made tonight). Owner re-enables when desired.

## Specs created

- **pkg138** — Disney dielectric delta-vs-continuous sample/pdf mismatch (from #498 adjudication)
- **pkg139** — addon AREA orientation + world-strength-0 fix
- **pkg140** — distant zero-angle black, sharpened mechanism
- **pkg141** — GPU near-delta Disney over-brightness

pkg139-141 filed and merged in [#504](https://github.com/HendrikGC02/Astroray/pull/504) (docs(pkg139-141): three specs from overnight verifier findings — AREA orientation, delta-sun black, GPU near-delta metal); pkg138 landed separately in #502.

## Next-run queue

pkg139 + pkg140 head the queue (dispatchable now). #498 needs eval-side D
reconciliation before it can land (disposition 1 above) — pkg138 →
pkg141/pkg124 follow-through → pkg121-B still queue behind it. #503 needs
GPU DI dispatch-reachability debugging before the ReSTIR reuse gate can be
re-attempted.

## Reconciliation with tick-generated 2026-07-20.md

The auto-tick file (`standup/2026-07-20.md`, last updated 22:31 pre-outage)
listed #485–#496 as CI-green + hardware-PASS and showed `pkg55-c6` /
`pkg123` as in-flight dispatches with an empty HW queue and free GPU lock.
Both of those in-flight items are accounted for above: pkg55-C6 shipped
its C6a half as #497 (HW-verified, merged) with C6b split out to #503
(now PARKED — HW gate FAIL); pkg123 is #498 (now PARKED — chi² green but
render-level regressions found, eval-side reconciliation needed next
session).

## Spec updates

- `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` — Session C6 status
  line added: **C6a done (PR #497, 2026-07-20, e6220c6)**; Phase C is 6/7
  sessions merged; C6b (#503) is the next pickup.

<!-- finalized -->
