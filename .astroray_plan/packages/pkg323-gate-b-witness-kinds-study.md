# pkg323 — Gate (b) witness control kinds for the top SUPPORTED families, scored under both predicates (#1087, non-predicate part)

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** 1 session (~4 h); CPU legs in-lane, GPU legs via the lead (~10 min)
**Depends on:** pkg318, pkg320

---

## Goal

Before: `render_leg.py` has one control-mutation kind (`checker_flat`) and the witness registry one case, so 57 % of
the gate (b) weight cannot score even in principle, and the owner is asked to change the frozen predicate (ROI
rectangle -> feature mask) with a sample of one.
After: control kinds exist for Noise, Brick, Wave, Bump and Mapping (61 weight, the largest matrix-SUPPORTED
families), each with registered witnesses in a CANDIDATE case map, and a table shows every witness's verdict under
the frozen rectangle predicate and the proposed mask predicate, CPU and GPU. The owner decides #1087 with data.

---

## Context

Same pattern as pkg317 for gate (c): build the instrument, measure both options, change no frozen file. The control
kinds are needed whichever predicate the owner picks. Run after #1099 is diagnosed, so the table separates
predicate effects from a real scene bias.

---

## Evidence

- 2026-10-06: pkg318: one witness, fails on both backends (ssim 0.846 / 0.839) although the checker matches Cycles (masked mean 1.001); non-feature pixels 0.84/0.91/0.94 of Cycles (#1099).
- 2026-10-06: lost-weight cause 1 (SUPPORTED, no witness): Noise 20, Brick 12, Wave 11, Bump 10, Mapping 8.

---

## Reference

- Issue #1087; `benchmarks/reference_corpus/coverage_report.py` (`CASE_WITNESS_REGISTRY`, `witness_metrics`); `benchmarks/blender_parity/render_leg.py` (control kinds).
- pkg317 study shape: `.astroray_plan/docs/gate-c-metric-study-2026-10.md` (both options, controls, no gate change).
- Counterfactual design: feature present vs neutralised (Noise/Wave/Brick -> constant at the texture mean; Bump strength 0; Mapping identity), both engines, so `effect` is measured on Cycles too.

---

## Prerequisites

- [x] pkg320 merged (identities resolve for the witnesses).
- [x] #1099 diagnosed (textures_mapping wall bias), so a failing witness is attributable.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/witness_candidates_v5.json` | Candidate case map (not frozen, not read by `--score`) |
| `tests/test_pkg323_control_kinds.py` | Each control kind mutates only its target node; the counterfactual changes the masked region and not the rest |
| `.astroray_plan/docs/gate-b-witness-study-2026-10.md` | Verdict table: witness x {rectangle, mask} x {CPU, GPU}; owner question |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/blender_parity/render_leg.py` | Control kinds `noise_const`, `brick_const`, `wave_const`, `bump_zero`, `mapping_identity` |
| `benchmarks/reference_corpus/coverage_report.py` | `witness_metrics` gains a `region` argument (`rect` default = frozen behaviour, `mask` for the study); a `--study` path scores the candidate map under both |

### Key design decisions

- **The frozen path is byte-identical.** `--score` on `coverage_input_v4.json` must give the same JSON before and after.
- **Witness selection is mechanical:** for each family, every exercised use in the nine-scene and candidate populations whose
  node has a single screen-space region; the selection rule goes in the doc, so the owner can audit it.
- **Report, don't tune.** No threshold or mask dilation is tuned to make witnesses pass.

---

## Acceptance criteria

- [x] Control-kind tests pass; frozen `--score` output byte-identical.
- [x] At least 10 witnesses across the five families scored under both predicates on CPU and GPU, with sheets (Astroray | Cycles | diff | mask) inspected.
- [x] Study doc states, per predicate, the provisional S_CPU / S_GPU these witnesses would give and the owner question.
- [x] `python scripts/project_index.py lint` passes.

---

## Non-goals

- Do not change `coverage_input_v4*.json`, the predicate, or `acceptance_manifest.json`.
- Do not author witnesses for APPROXIMATED Principled sockets (they also need the warning rule (d) first).

---

## Progress

- [x] Control kinds + tests
- [x] Candidate map + selection rule
- [x] CPU legs, study doc (CPU)
- [x] GPU legs (lead), S_GPU filled

---

## Lessons

- The rectangle-vs-mask predicate changed no verdict on 27 witnesses (CPU and GPU); noise at 64 spp on hero objects and real engine gaps (Bump, Displacement, shader stack, Brick Mortar) are what block credit. Credit needs every scene variant of an identity, so the witness count binds. See the study doc.
