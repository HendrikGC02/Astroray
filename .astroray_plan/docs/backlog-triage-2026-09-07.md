# Backlog triage — 2026-09-07 (overnight course-correction)

Owner authority: "You may remove and edit as need be" (2026-09-07). Lead: Claude Fable 5.1.
Rule applied: a spec is closed when it has no caller today, its premise no longer reproduces, or a
newer package owns the same defect. Closed specs keep their file (status `superseded`, previous
status text preserved under `## Progress`) unless they carried no unique content, in which case
they were deleted (git history retains them).

## Closed (status -> `superseded`)

| Spec | One-line rationale | Successor |
|---|---|---|
| pkg137 partitioned SMS + ReSTIR caustics | never started; pkg227 (specular polynomials, Phase 2a landed) is the caustics line | pkg227 |
| pkg135 demand-loaded sparse textures | conditional trigger (VRAM overflow) never fired in 5 months | refile on trigger |
| pkg132 host-mapped memory fallback | never needed; research doc retained | refile on trigger |
| pkg153 wavefront_diff env-scene gates | July dossier stale; live baseline failures owned by pkg237/pkg238 | pkg237, pkg238 |
| pkg165 Disney-metal GPU-dim residual | verify-and-close done: premise does not reproduce (pkg129 A/B) | none |
| pkg173 bounce-1 geometry-sampling parity | below the Integration Milestone; bit-level parity not required by any deliverable | reopen on demand |
| pkg228 forward light-tracer rainbow | PROPOSED, never owner-approved; overlaps pkg227 Track S | pkg227 |
| pkg152 GPU Disney metal residual + rough-transmission deficit | metal symptom gone (pkg165); transmission deficit owned by pkg179 | pkg179 |
| pkg156 wavefront naive bounce-2 residual | quantified 1-1.5 % after PR #537 and accepted | reopen if a gate tightens |
| pkg167 dielectric reflection multiscatter | Part 1 landed (#562); Part 2 is pkg179 | pkg179 |

## Deleted (no unique content)

| Spec | Where its facts live |
|---|---|
| pkg240 CI workflow cost audit | `.astroray_plan/docs/pkg240-ci-baseline-audit.md` (host tests = 90-92 % of job time); CI is healthy and not a bottleneck |
| pkg231 CUDA build latency diagnosis | build facts in `scripts/build/README.md` and the 2026-09-06 rebuild handoff (clean CUDA addon build ~30 min) |

## Kept open (re-scoped or untouched)

- **pkg179** now the single owner of the Disney GPU residual line (dead-sample redistribution into transmission).
- **pkg127 Phase 2**: spec flag name corrected `sms_polynomial_seed` -> `sms_specular_poly` (the shipped flag).
- **pkg88** motion blur B/D, **pkg124** VNDF, **pkg126** mesh-emitter unification, **pkg134** LPE, **pkg136** GPU leg,
  **pkg201** remaining honour rows, **pkg211** (owner: prototype-or-park), **pkg218** colorimetry Thread A.
- **Science-foundational side lane** (owner 2026-09-07): **pkg243** raw band provenance, **pkg133** SRF spectral sensors,
  **pkg130** light groups. These serve both the Blender product and Pillar 4 and may run while Pillar 4 stays paused.
- **Pillar 4** pkg45-51, pkg107: untouched, paused.
- The 2026-09-06 wave (pkg233-239, 241-249, 251, 252) stays open pending the TEMPLATE v2 rewrite; pkg241/242/245/237/238
  are in tonight's implementation lanes.

## Test debt folded into a spec

The ten `strict=False` xfails in `tests/test_python_bindings.py` ("not ported to the spectral path_tracer") get an
owning spec, **pkg254 spectral path_tracer feature parity** (pkg253 = Principled advanced inputs), and become `strict=True` so an accidental fix is noticed.
