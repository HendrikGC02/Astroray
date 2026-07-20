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

**Also direct-to-main (no PR):**
- Agent fleet moved to Claude 5 models (`15b1449`)
- Codex routing retired — owner no longer uses Codex (`2d0e42a`)

## HW verifications

- **#497 (pkg55-C6a)** — verified twice on RTX 3000 Ada: `ed31cb1` then `b76465c` (post-fix). Full wavefront + RNG + ReSTIR regression suite, zero CUDA errors, 10 PNGs visually clean.
- **#500 (pkg122, still open)** — GPU==CPU 0.997–0.998 across all light types; live-Cycles oracle 1.07–1.16× (the gross factors 0.13×/3.6×/14×/near-black are ELIMINATED). Residual is owner-reserved Defect-4 (see action items).
- **#498 (pkg123, still open)** — chi² failures went 163 → 1 across three fix rounds; final state 399 passed with adjudicated xfails.

## Pending at close (2-3 items still resolving)

- **#498** — final xfail commit + CI + merge. Near-certain to land as-is; not yet merged at write time.
- **#500** — caustic-test recalibration. A real regression CI caught: the caustic scene's expected values were calibrated to the old, broken distant-light units. Needs recalibration before merge.
- **#503** — pkg55-C6b (temporal/spatial reuse + driver integration on the GPU wavefront). Opened, stacked on C6a, awaiting the RTX ReSTIR gate.

## Action items for owner

1. **Defect-4 decision** — RGBIlluminant-vs-RGBUnbounded emission convention. The residual ~7–16% divergence vs Cycles across all light types (pkg122) hangs on this call. Evidence: pkg122 verifier report + oracle renders in `Astroray-pkg122/test_results/pkg122_cycles_oracle/`.
2. **pkg139 AREA-orientation bug** — artist-placed default-rotation area lights point AWAY from scenes in the Blender addon. This is the biggest remaining owner-visible dimness contributor. Spec'd and ready to dispatch next run.

## Specs created

- **pkg138** — Disney dielectric delta-vs-continuous sample/pdf mismatch (from #498 adjudication)
- **pkg139** — addon AREA orientation + world-strength-0 fix
- **pkg140** — distant zero-angle black, sharpened mechanism
- **pkg141** — GPU near-delta Disney over-brightness

All four filed in [#504](https://github.com/HendrikGC02/Astroray/pull/504) (docs(pkg139-141): three specs from overnight verifier findings — AREA orientation, delta-sun black, GPU near-delta metal — plus pkg138 landed separately in #502). #504 pending CI at close.

## Next-run queue

pkg139 + pkg140 head the queue. Post-#498 merge: pkg138 → pkg141/pkg124 follow-through → pkg121-B. Plus: pkg55-C6b gate + merge (#503).

## Reconciliation with tick-generated 2026-07-20.md

The auto-tick file (`standup/2026-07-20.md`, last updated 22:31 pre-outage)
listed #485–#496 as CI-green + hardware-PASS and showed `pkg55-c6` /
`pkg123` as in-flight dispatches with an empty HW queue and free GPU lock.
Both of those in-flight items are accounted for above: pkg55-C6 shipped
its C6a half as #497 (HW-verified, merged) with C6b split out to #503
(still open); pkg123 is #498 (still open, chi² adjudication complete,
pending final merge).

## Spec updates

- `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` — Session C6 status
  line added: **C6a done (PR #497, 2026-07-20, e6220c6)**; Phase C is 6/7
  sessions merged; C6b (#503) is the next pickup.
