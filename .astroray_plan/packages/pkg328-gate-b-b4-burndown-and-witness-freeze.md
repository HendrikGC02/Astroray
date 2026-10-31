# pkg328 — Gate (b): b4 burn-down, Welch-1b witness freeze and the audited-matrix score on candidate_v2

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~8 h): Phase 1 ~3 h Python + CPU probe renders; Phase 2 ~5 h + GPU witness legs via the lead (~10 min)
**Depends on:** pkg278, pkg318, pkg320, pkg321, pkg323

---

## Goal

Before: on the owner population (candidate_v2 = corpus v2 + production), b4 lists 19 exercised drops, b2/b3 read 0/474,
b1 is unsigned, and only one witness is registered, on a legacy scene. 11 of the 19 drops are already named in the
per-render DegradationReport since pkg321, but b4 reads the static matrix class DROPPED-SILENT, so they count as silent.
After:
- b4 counts only drops no warning names, and each of the other 8 rows is resolved: credited by a probe render, reported, or
  fixed. b4 is green.
- b1 is recorded as ratified from the owner's 10-06 population decision.
- b2/b3 use the owner's 2026-10-31 model: the static matrix, audited by a sampled witness set frozen under Welch-1b.
- CPU and GPU scores are measured, and the PR proposes a threshold (measured ceiling minus a margin) for the owner to sign.

---

## Context

Stage 0 exit needs (b) green in the committed manifest. On 2026-10-31 the owner answered `architect-plan-2026-11-01.md`
§5, items 1-4:
- credit = the static matrix audited by a sampled witness set;
- predicate = Welch-1b, as for (c) (#1087);
- threshold = measured ceiling minus a margin, signed by the owner; 0.95 is retired;
- b1 = the 10-06 population decision.

pkg278 defines b4 as "zero silent drops in corpus scenes". Counting runtime-reported drops as silent is an instrument gap,
not an engine gap. Fixing it does not inflate S, because reported drops still earn no matrix credit.

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
  noise, the case Welch-1b handles for (c).
- 2026-10-06: `gate-b-provisional-score-2026-10.md`. The matrix-only ceiling is 0.426 on candidate_v2, about 0.69-0.81 once
  the pkg320 credits are counted and Principled is lifted to SUPPORTED.

---

## Reference

- Definitions: `pkg278` (b1-b6), `gate-b-provisional-score-2026-10.md`, `gate-b-witness-study-2026-10.md`,
  `architect-plan-2026-11-01.md` §5.
- Code:
  - `benchmarks/reference_corpus/coverage_report.py`: `SCORE_MIN`, `silent_drops`, `CASE_WITNESS_REGISTRY`,
    `population_status`, `--study*`, `--score`;
  - `scripts/generate_blender_parity_matrix.py`: `PKG321_REPORTED_DROPS`, pkg320 traversal credits;
  - `benchmarks/reference_corpus/silent_drop_audit.py`: `reported_entries`, `is_reported` (row (g) already treats reported
    as not silent);
  - `benchmarks/reference_corpus/witness_candidates_v5.json`, `benchmarks/reference_corpus/populations/candidate_v2.json`;
  - `benchmarks/blender_parity/mc_compare.py`: `welch_tiles`, `welch_verdict`, the row (c) Welch-1b test;
  - `scripts/gate_manifest.py`: row (b) threshold.
- Issues: #1087 (predicate), #1088 (context-blind root rows), #1128-#1136, #1140.

---

## Prerequisites

- [x] Owner answers 2026-10-31 recorded (`architect-plan-2026-11-01.md` §5).
- [ ] Staged CPU addon at main HEAD; `python scripts/project_index.py deps pkg328` read.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg328_b4_reported_drops.py` | A reported DROPPED row is excluded from b4 and still earns no credit; an unreported DROPPED row stays in b4; every `reported_at_runtime` row's warning text exists in the addon source |
| `tests/test_pkg328_audited_matrix_score.py` | Audited-matrix scoring: a passing witness leaves its identities at matrix credit; a failing witness zeroes the identities it covers; Welch-1b verdicts come from `mc_compare.welch_verdict` |
| `docs/blender_parity/evidence/gate_b/candidate_v2/b1_ratification.md` | The owner's b1 sign-off (10-06 population decision, confirmed 10-31), hashed into `populations/candidate_v2.json` |

### Files to modify

| File | What changes |
|---|---|
| `scripts/generate_blender_parity_matrix.py` | Rows in `PKG321_REPORTED_DROPS` and the hand-verified runtime-warning rows get `"reported_at_runtime": true`; classification unchanged. The 8 remaining rows are credited from probe renders (as pkg321 did) or stay DROPPED with an issue |
| `docs/blender_parity/coverage_matrix.json` | Regenerated |
| `benchmarks/reference_corpus/populations/candidate_v2.json` | `ratified: true` with the `ratification` path + sha256 of the b1 file |
| `benchmarks/reference_corpus/coverage_report.py` | Phase 1: `silent_drops` skips `reported_at_runtime` rows. Phase 2: an audited-matrix scoring mode (matrix credit per identity, zeroed where an audit witness fails); witness predicate = `welch_verdict`; `SCORE_MIN` replaced by the owner-signed threshold value; scorer version bump |
| `scripts/gate_manifest.py` | Row (b) threshold read from the signed value instead of 0.95; no subcheck renamed |
| `.astroray_plan/packages/pkg278-exit-gate-instrumentation.md` | b2/b3 text: audited-matrix credit, Welch-1b, owner-signed threshold (2026-10-31) |
| `docs/blender_parity/evidence/gate_b/candidate_v2/coverage_report.json` | Re-scored |
| `blender_addon/degradation.py` | Only if a probe shows a real drop: name it in the DegradationReport, or fix it in the exporter if it is a one-liner (e.g. Environment Vector through Mapping); anything larger becomes an issue |

### Key design decisions

#### Phase 1: b4 and b1

- A field rather than a new class: `reported_at_runtime` leaves the three-class enum and every consumer untouched, so there
  are fewer call sites than with a DROPPED-REPORTED class. Run the CLAUDE.md call-site sweep on `silent_drops` and the
  matrix schema anyway.
- The flag comes from the same source the row (g) audit trusts, the addon's DegradationReport text, checked by the test.
  No hand-typed credit.
- TexEnvironment Vector matters to users (HDRI rotation via Mapping). If the probe shows it is dropped, report and file it
  as a likely high for (e).
- b1 uses the existing `population_status` ratification path (approval file + sha256); no new mechanism.

#### Phase 2: audited matrix under Welch-1b

- Credit is the matrix's per-identity credit (the "matrix-only ceiling" computation). The audit sample is the candidate_v2
  subset of `witness_candidates_v5.json` (selection rule R1-R5), plus at least one witness each for Metallic, Sky and
  Principled-advanced, which b5 names. Witnesses are not added for identities beyond those.
- Render each witness on CPU and GPU (GPU under the lead's lock) and judge it with `welch_verdict` from `mc_compare.py`,
  never a re-implementation. A witness that fails zeroes the identities it covers and gets an issue. A witness with no
  effect is recorded, not credited.
- Report S_CPU, S_GPU, the measured ceiling (every identity at matrix credit) and a proposed threshold = ceiling minus a
  margin. The margin is the seed-to-seed spread of S over the witness legs plus one witness's weight. The owner signs the
  number in the PR; until then row (b) stays red.
- The scanner receipt must be independent: a blind reviewer plus the flash critic, as #1169 did.

---

## Acceptance criteria

- [ ] b4 on candidate_v2 lists only unreported drops; the target is 0. Each of the 8 non-pkg321 rows has a probe verdict in
      the PR body.
- [ ] b1 passes from the hashed ratification file.
- [ ] Both new tests and the existing coverage tests pass. `coverage_report.py --score` exits 0 on both populations.
- [ ] Phase 2: audit witnesses frozen under Welch-1b. S_CPU, S_GPU, the ceiling and the proposed threshold recorded in
      `stage0-gate-scoring-*.md`. Receipt independent; owner sign-off on the threshold recorded in the PR.

---

## Non-goals

- Do not change the population or the matrix classification rules beyond the `reported_at_runtime` flag.
- Do not implement the dropped engine features (#1128-#1136); this package makes them honest, not supported.
- Do not add a Displacement scene (separate corpus item) or witnesses beyond the audit sample above.

---

## Progress

- [ ] Phase 1: flag + probes for the 8 rows + matrix regen + b1 ratification + b4 re-score
- [ ] Phase 2: audit witnesses under Welch-1b + audited-matrix score + proposed threshold + receipt
- [ ] Owner signs the threshold

---

## Lessons

*(Fill in after the package is done.)*
