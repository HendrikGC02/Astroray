# pkg328 — Gate (b): b4 burn-down (reported is not silent) and the witness freeze on candidate_v2

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~7 h): Phase 1 ~3 h Python + CPU probe renders; Phase 2 ~4 h + GPU witness legs via the lead (~10 min)
**Depends on:** pkg318, pkg320, pkg321, pkg323

---

## Goal

Before: on the owner population (candidate_v2 = corpus v2 + production), b4 lists 19 exercised drops, b2/b3 read 0/474,
and only one witness is registered, on a legacy scene. 11 of the 19 drops are already named in the per-render
DegradationReport since pkg321, but b4 reads the static matrix class DROPPED-SILENT, so they count as silent.
After:
- b4 counts only drops no warning names, and each of the other 8 rows is resolved: credited by a probe render, reported, or
  fixed. b4 is green.
- The pkg323 witnesses on candidate_v2 scenes are frozen in the registry under the predicate the owner picks for #1087 and
  scored on both backends, so the owner population has its first nonzero S.

---

## Context

Stage 0 exit needs (b) green in the committed manifest. The full 0.95 target waits on owner question 1 of
`architect-plan-2026-11-01.md`, but b4 and the witness freeze are needed under any answer and are cheap. pkg278 defines b4 as
"zero silent drops in corpus scenes". Counting runtime-reported drops as silent is a gap in the instrument, not in the
engine, and the fix does not inflate S: reported drops still score 0 in b2/b3. The change bumps the scorer version and is
recorded in the plan doc so the owner can veto it.

---

## Evidence

- 2026-10-25: `docs/blender_parity/evidence/gate_b/candidate_v2/coverage_report.json` (#1169): `b4_zero_silent_drops` 19
  drops. The matrix notes on 11 of them say "dropped, reported at runtime": Glass Normal and distribution, Hair Random and
  Random Roughness, Metallic Normal and Tangent, Principled Coat Normal, Tangent, distribution and subsurface_method, Sky
  ground_albedo, Volume Principled Color Attribute.
- The other 8 have no runtime evidence:
  - OutputWorld Surface and is_active_output, OutputMaterial target and Thickness, TexEnvironment Vector: pkg320
    context-blind rows (#1088);
  - TexImage interpolation and MapRange clamp: no note.
  - Principled Coat Normal is consumed on CPU since #1157; the GPU half is #1153.
- 2026-10-18: `gate-b-witness-study-2026-10.md`. Of 27 witnesses, 11 pass, 8 show no effect and 8 fail SSIM, the same under
  rect and mask. Production hero witnesses fail SSIM at 0.58-0.73 with visually matching renders, which is independent MC
  noise. If every witness passed, candidate_v2 would score 0.127 under fan-out credit.

---

## Reference

- Definitions: `pkg278` (b1-b6), `gate-b-provisional-score-2026-10.md`, `gate-b-witness-study-2026-10.md`.
- Code: `benchmarks/reference_corpus/coverage_report.py` (`silent_drops`, `CASE_WITNESS_REGISTRY`, `--study*`, `--score`),
  `scripts/generate_blender_parity_matrix.py` (`PKG321_REPORTED_DROPS`, pkg320 traversal credits),
  `benchmarks/reference_corpus/silent_drop_audit.py` (`reported_entries`, `is_reported`: row (g) already treats reported as
  not silent), `benchmarks/reference_corpus/witness_candidates_v5.json`, `benchmarks/blender_parity/mc_compare.py`
  (`welch_tiles`, `welch_verdict`: the row (c) Welch-1b test).
- Issues: #1087 (predicate), #1088 (context-blind root rows), #1128-#1136, #1140.

---

## Prerequisites

- [ ] Staged CPU addon at main HEAD; `python scripts/project_index.py deps pkg328` read.
- [ ] Phase 2 only: the owner has answered #1087, choosing the frozen rect SSIM/dE predicate or a noise-aware one (Welch-1b).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg328_b4_reported_drops.py` | A reported DROPPED row is excluded from b4 and still scores 0; an unreported DROPPED row stays in b4; every `reported_at_runtime` row's warning text exists in the addon source |

### Files to modify

| File | What changes |
|---|---|
| `scripts/generate_blender_parity_matrix.py` | Rows in `PKG321_REPORTED_DROPS` and the hand-verified runtime-warning rows get `"reported_at_runtime": true`; classification unchanged. The 8 remaining rows are credited from probe renders (as pkg321 did) or stay DROPPED with an issue |
| `docs/blender_parity/coverage_matrix.json` | Regenerated |
| `benchmarks/reference_corpus/coverage_report.py` | `silent_drops` skips `reported_at_runtime` rows; scorer version bump; Phase 2: register the frozen candidate_v2 witnesses in `CASE_WITNESS_REGISTRY` with the chosen predicate (`welch_verdict` from `mc_compare.py` if the owner picks it, never a re-implementation) |
| `scripts/gate_manifest.py` | Accept the new scorer version for row (b); no subcheck renamed |
| `docs/blender_parity/evidence/gate_b/candidate_v2/coverage_report.json` | Re-scored |
| `blender_addon/degradation.py` | Only if a probe shows a real drop: name it in the DegradationReport, or fix it in the exporter if it is a one-liner (e.g. Environment Vector through Mapping); anything larger becomes an issue |

### Key design decisions

#### Phase 1: b4

- A field rather than a new class: `reported_at_runtime` leaves the three-class enum and every consumer untouched (fewer
  call sites than a DROPPED-REPORTED class). Run the CLAUDE.md call-site sweep on `silent_drops` and the matrix schema
  anyway.
- The flag comes from the same source the row (g) audit trusts, the addon's DegradationReport text, checked by the test.
  No hand-typed credit.
- TexEnvironment Vector matters to users (HDRI rotation via Mapping). If the probe shows it is dropped, report and file it
  as a likely high for (e).

#### Phase 2: witness freeze

- Take the candidate_v2 subset of `witness_candidates_v5.json` (selection rule R1-R5 unchanged). Render CPU and GPU (GPU
  under the lead's lock) and freeze under the owner's predicate. Score both populations, with CPU and GPU reported
  separately.
- The scanner receipt must be independent: a blind reviewer plus the flash critic, as #1169 did.

---

## Acceptance criteria

- [ ] b4 on candidate_v2 lists only unreported drops; the target is 0. Each of the 8 non-pkg321 rows has a probe verdict in
      the PR body.
- [ ] `tests/test_pkg328_b4_reported_drops.py` and the existing coverage tests pass. `coverage_report.py --score` exits 0
      on both populations.
- [ ] Phase 2: frozen witnesses registered, S_CPU and S_GPU on candidate_v2 recorded in `stage0-gate-scoring-*.md`, receipt
      independent.

---

## Non-goals

- Do not change b2/b3 credit rules, the 0.95 threshold or the population. Those wait for owner question 1.
- Do not implement the dropped engine features (#1128-#1136); this package makes them honest, not supported.
- Do not author new witnesses beyond the pkg323 candidates.

---

## Progress

- [ ] Phase 1: flag + probes for the 8 rows + matrix regen + b4 re-score
- [ ] Owner answer on #1087
- [ ] Phase 2: witness freeze + score + receipt

---

## Lessons

*(Fill in after the package is done.)*
