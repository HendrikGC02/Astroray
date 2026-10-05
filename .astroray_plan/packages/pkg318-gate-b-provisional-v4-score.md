# pkg318 — Gate (b) provisional v4 freeze and score: numbers before ratification

**Pillar:** 5
**Track:** A
**Status:** in-progress — provisional measurement on branch batch-f6/pkg318 (2026-10-06): S_CPU = S_GPU = 0.000 on both populations; the one registered witness fails on both backends; ranked backlog in `.astroray_plan/docs/gate-b-provisional-score-2026-10.md`; issues #1087 #1088 #1089 filed; evidence legs on a pre-#1069/#1071 build, re-run pending; owner ratification open
**Estimated effort:** 1 session (~3–4 h) + ~30 min of GPU evidence renders under the lead's lock
**Depends on:** pkg278, pkg284, pkg310

---

## Goal

Before: gate (b) is unmeasured. The frozen v3 input fails integrity against the current corpus (scene and matrix
hashes), the evidence sidecar map is empty (`cases: []`), and the only number is the matrix-only upper bound from
`silent_drop_audit.py coverage`: 0.4185 on the nine-scene population, 0.7686 on the production corpus. Nobody knows
which uses keep (b) far from 0.95.
After: a provisional `coverage_input_v4.json` is frozen on the current corpus with `ratified: false`, per-backend,
per-variant evidence sidecars exist for every nonzero use, `coverage_report.py --score` reports provisional
S_CPU / S_GPU and b1–b6, and a weight-ranked backlog lists the uses that score 0. The owner's remaining step is a
signed ratification artifact (b1).

---

## Context

Gate (b) is the Stage 0 row furthest from green and the only one with no measured value. The scorer and the
`--freeze-v4` path exist (pkg278; #823 closed 2026-09-23). Owner 2026-09-25: the nine legacy scenes may be scrapped
and redone, which leaves the population choice open; this package scores both candidate populations so the
choice is made on numbers. Tooling and evidence only; no engine change.

---

## Evidence

- `docs/blender_parity/coverage_input_v3.json`: population nine scenes, `ratified: false`; scanner #823
  `integrated: false` at freeze time; evidence `runner_case_map.cases: []`, `status: provisional`.
- `pkg310-production-corpus-burndown.md` (2026-10-03): matrix-only weighted coverage 0.4185 (297 uses, 120
  matrix-silent) nine-scene; 0.7686 (71 uses) production; 47 SUPPORTED textures_mapping rows in
  `proof_pending.json`.

---

## Reference

- `pkg278-exit-gate-instrumentation.md` §Gate (b) weighted coverage (formula, b1–b6, scoring rules (a)–(e)).
- `benchmarks/reference_corpus/coverage_report.py` (`--collect`, `--freeze-v4 --scanner-integration`, `--score`).
- `stage-plan-2026-09-22.md` §6 (population decision).

---

## Prerequisites

- [ ] #1071 (Add Shader CPU) and #1069 (#1047) on main, so the score reflects tonight's node fixes.
- [ ] Blender 5.2 headless; staged addon matches the evidence build (`dist/astroray` SHA recorded).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `docs/blender_parity/coverage_input_v4.json` | Provisional frozen input (nine-scene population), `ratified: false`, scanner receipt for #823 |
| `docs/blender_parity/coverage_input_v4_candidate_v2.json` | Same for the corpus v2 + production candidate population (diagnostic; not gate-eligible) |
| `docs/blender_parity/evidence/gate_b/sidecars/` | Per-backend, per-variant evidence artifacts (PNG + result JSON) for every use claimed nonzero |
| `docs/blender_parity/corpus_coverage.md` | Scorer report (`coverage_report.py` output) |
| `.astroray_plan/docs/gate-b-provisional-score-2026-10.md` | S_CPU / S_GPU per population, b1–b6, weight-ranked zero-scoring backlog with issue links |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/reference_corpus/coverage_report.py` | Only if needed: a `--population` selector for the v2 + production candidate (the nine-scene default stays) |

### Key design decisions

- Never mark the input ratified, never write a ratification artifact, never edit a frozen file (new version only).
- A use is nonzero only with a linked per-backend, per-variant artifact; unproven claims score 0 (pkg278 rule (c)).
- Rank the backlog by lost weight `min(n_i, 3)` summed per root cause, mapped to existing issues; file a new
  issue only for an unowned root cause, one per cause.
- Matrix-stale rows found on the way go to the #872 / #1039 owners, not fixed here.

---

## Acceptance criteria

- [ ] `coverage_report.py --score --input-manifest docs/blender_parity/coverage_input_v4.json` exits 0 with
      `status: provisional`, separate S_CPU and S_GPU, and every b-subcheck reported (b1 false: unratified).
- [ ] Every nonzero use links an existing sidecar whose SHA-256 verifies.
- [ ] `coverage_report.py --self-test` and `tests/test_pkg278_*` green.
- [ ] Doc gives both populations' scores and the top-10 lost-weight root causes with issue numbers.

---

## Non-goals

- Do not ratify, choose the population, or sign b1.
- Do not change the scoring formula or the 0.95 thresholds.
- Do not fix engine gaps the backlog finds.

---

## Progress

- [x] Collect + freeze v4 (nine-scene) and the v2 + production candidate.
- [x] Evidence sidecars (the one registered case; both fail, 0 nonzero uses).
- [x] Score + ranked backlog doc.

---

## Lessons

*(Fill in after the package is done.)*
