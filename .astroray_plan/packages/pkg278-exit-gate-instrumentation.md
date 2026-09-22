# pkg278 — Exit-gate instrumentation (acceptance manifest, weighted coverage, corpus-trio parity, native-panel smoke, clean install, severity triage)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg259, pkg260

---

## Goal

Before: each row (a)–(f) of the Pillar-4 exit gate is measured, if at all, by a
different ad-hoc artifact in a different format, and the gate can be called green
by narrative. After: every row is produced by its own scripted instrument, and
`docs/blender_parity/acceptance_manifest.json` records scene SHA-256s, build id,
backend, settings, metric, threshold and evidence path per row — re-measurable and auditable from one file.

pkg278's exit permits measured RED rows: its deliverable is the validated
instruments + reproducible commands + evidence for every row. A row without an instrument stays UNMEASURED (`value: null`, `status: unmeasured`); a red measurement is a valid result, not a failure of this package.

---

## Context

`north-star-and-integration-gate-2026-09-07.md` §2 defines gate rows (a)–(f);
Stage 0a of `stage-plan-2026-09-22.md` says instrument them first, because a gate
measured by narrative can be relabeled green. pkg260 landed the matrix extension
(527 → 586 rows), but pkg259's Phase 4 — `coverage_report.py`, the gate (b)
scorer — was never built. Gate (c) has no consolidated CPU+GPU report, gate (e)
no published rubric, and gate (f) is unverified on a clean machine. This package
builds the instruments only; fixing what they measure is the Stage 0b–0d batches.
pkg259 is superseded; its Phase 4 obligations live here in full (2026-09-22).

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: Astra turn-2 review amendments applied (planning session).
- 2026-09-22: Codex Terra review defects applied (planning session).
- 2026-09-22: Astra turn-4 sign-off discrepancies closed (planning session).

---

## Reference

- Gate rows: `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md §2 (a)–(f)`
- Instrument design: `.astroray_plan/docs/reference-corpus-design-2026-09.md §4.3`
- Sequencing and the open corpus decision: `.astroray_plan/docs/stage-plan-2026-09-22.md §3 Stage 0a, §6`
- Gate (a) harness: `pkg241` (present/cancel contract) and `pkg266` (viewport worker)
- Metrics reused, not rebuilt: `pkg104` (reference bank) and the pkg119b triage output

---

## Prerequisites

- [ ] pkg259 is done (corpus assets + `benchmarks/reference_corpus/scenes/manifest.json`).
- [ ] pkg260 is done (matrix rows cover object / image-property / input-node).
- [ ] #823 (scanner blind to `_compile_socket_value`) has landed BEFORE the
      coverage measurement — gate (b) is not scored until it does.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/coverage_report.py` | pkg259 Phase 4 gap: joins corpus manifests to `docs/blender_parity/coverage_matrix.json`, counts exercised sockets from the scene node trees, and writes `corpus_coverage.md` + a JSON twin. |
| `scripts/gate_manifest.py` | Assembles `docs/blender_parity/acceptance_manifest.json` from the per-row instruments. |
| `docs/blender_parity/acceptance_manifest.schema.json` | JSON schema the manifest rows must validate against; `gate_manifest.py` rejects a hand-edited status. |
| `tests/test_gate_native_panels.py` | Gate (d) output-effect smoke: adaptive sampling and denoise driven only by native panels, CPU and GPU. |
| `docs/install-clean-machine.md` | Gate (f) documented ZIP install through Blender's extension installer, no build toolchain. |
| `docs/blender_parity/evidence/install-clean-machine/` | Gate (f) evidence: install log, installed-file list, F12 PNG, fresh-profile settings. |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/blender_parity/harness.py` | Export a per-feature verdict JSON for the manifest; reuse the existing pkg119b triage output, add no new metric. |
| `benchmarks/reference_bank/runner.py` | Add a per-channel mean-ratio gate type; SSIM stays a diagnostic print for the reference bank and the HDRI CPU/GPU parity gate only (owner 2026-09-08) — NOT for exit-gate (c), which gates on SSIM. |
| `scripts/README.md` | Register `coverage_report.py` and `scripts/gate_manifest.py`. |
| `.astroray_plan/docs/KNOWN_ISSUES.md` | Publish the severity rubric: high = wrong image, crash, or a native setting silently ignored; medium = degraded but flagged; low = cosmetic. |
| `benchmarks/blender_parity/scene_library.py` | `REFERENCE_SCENES` reads the corpus directory instead of the hard-coded three. |
| `benchmarks/blender_parity/render_leg.py` | `--load-blend` works for every corpus scene; non-vacuity checks come from the manifest. |
| `benchmarks/blender_parity/scenes/manifest.json` | The three #729 scenes absorbed into the corpus, recorded byte-identical or regenerated. |
| `scripts/benchmarks/weekly_local_bench.ps1` | Parity and showcase legs iterate the corpus families. |
| `scripts/run_parity.py` | Accepts corpus scene ids. |
| `benchmarks/viewport_parity/blender_driver.py` | Accepts corpus scenes as workloads; pkg241 keeps metal_sweep as its historical baseline. |
| `scripts/dev/known_issues_report.py` | Optional: link each open addon-gap issue to the corpus scene that reproduces it. |

### Key design decisions

One manifest is the gate's only source of truth; every instrument reuses an
existing metric rather than adding a comparison stack (pkg104 + pkg119b).

#### Acceptance manifest

- Single file `docs/blender_parity/acceptance_manifest.json`, one object per row
  (a)–(f): `scene_sha256[]`, `build_id`, `backend`, `settings`, `metric`,
  `value`, `threshold`, `evidence_path`, `instrument`, `date`.
- `scripts/gate_manifest.py` runs each instrument and merges the results. A row
  with no instrument writes `value: null` and `status: unmeasured` — never
  omitted.
- Re-runs overwrite atomically; git history is the audit record.

#### GREEN predicate (schema-enforced, universal)

- Every row's status is COMPUTED by `scripts/gate_manifest.py` from a
  JSON-schema-validated row (`docs/blender_parity/acceptance_manifest.schema.json`):
  required fields present; every `evidence_path` exists and its recorded SHA-256
  matches; `build_id` and `backend` present; all mandatory measurements for that
  row present — (a) 3×100 repetitions on both pinned scenes, GPU-only latency,
  denoise excluded, p95/p99 and cancel-ack limits; (c) separate CPU and GPU F12
  exit status plus SHA-pinned images and metrics; `value` inside `threshold`.
- Any missing or dangling item makes the row RED or UNMEASURED — never GREEN by
  narrative. A hand-edited status is rejected by the validator.

#### Gate (b) weighted coverage

- `coverage_report.py` joins corpus manifests to `coverage_matrix.json` on the
  key `(category, feature, bl_idname, socket_or_prop)`.
- Score per BACKEND `b ∈ {CPU, GPU}`:
  `S_b = Σ_i min(n_i, 3)·s_{i,b} / Σ_i min(n_i, 3)`, where `i` is a canonical
  socket identity (`bl_idname` + socket identifier), `n_i` the number of distinct
  corpus scenes exercising it, and `s_{i,b} ∈ {1 SUPPORTED, 0.5 bounded
  approximation, 0}`. A classification is only nonzero when it links a
  per-backend, per-variant evidence artifact (rendered PNG or test result) in
  the manifest; an unproven claim defaults to `s_{i,b} = 0` — it can never raise
  the score. EACH backend must pass 95 % separately; never average
  backends into a single score.
- Scoring rules:
  - (a) scene hashes, exercised uses, socket identities, weights and exclusions
    are FROZEN in a committed input manifest before scoring; the manifest's
    SHA-256 is recorded in the report, every exclusion carries a written
    rationale, and any change is a new manifest version, never an edit.
  - (b) exercised uses are derived from the scene node trees and Blender/Cycles
    reachability — a use Astroray drops stays in the denominator.
  - (c) a SUPPORTED claim must cover the frozen exercised variants of the socket
    and link per-backend, per-variant rendered/test evidence; a working constant
    input does not validate linked programs. No linked artifact ⇒ 0.
  - (d) 0.5 is awarded only for a functioning bounded approximation with a
    user-visible attributable warning and a linked evidence artifact; "ignored
    but warned" scores 0.
  - (e) missing evidence is not SUPPORTED; a missing corpus asset invalidates the
    run.
  - (f) zero silent drops in corpus scenes is a separate Boolean requirement, not
    a diagnostic.
  - (g) the mandatory Principled-advanced, Metallic BSDF, Sky texture and Displacement checks are their own rows even if corpus weighting hides them.
- Count EXERCISED sockets by reopening each `.blend` and reading its node tree,
  not from manifest labels.
- Report silent drops and CPU/GPU differences as separate lists.
- Emit `docs/blender_parity/corpus_coverage.md` plus the JSON twin.
- The nine-scene score is published as PROVISIONAL until the owner ratifies the
  population (`stage-plan-2026-09-22.md` §6); the original "~50 scenes"
  population was never frozen, so its score is reported as UNDEFINED, not
  computed. An unratified population is categorically ineligible for GREEN
  regardless of score: the report carries `status: provisional`, and the GREEN
  evaluator rejects any row whose population has no recorded owner ratification.
- Validate the scorer on a synthetic 3-scene fixture with a hand-computed
  weighted score.

#### Gate (a) table

- Warm session, both pinned scenes (10k and 100k triangles), 3×100 camera edits and 3×100 material edits each; instrument emits one row per scene × edit-kind.
- event → first *correct* Blender-presented frame: GPU p95 ≤ 100 ms, p99 ≤ 150 ms; cancel-ack p95 ≤ 200 ms, p99 ≤ 300 ms; no stale frame presented after the ack.
  Latency is a GPU-only oracle (CPU is the image oracle, not a latency oracle), and denoise is excluded from the interactive loop (owner-ratified 2026-09-07).
  The GREEN evaluator requires every one of these fields.
- Extends the pkg241/pkg266 viewport harness; measured in a real Blender session, not the in-process harness.

#### Gate (c) trio

- materials_hall gallery / textures_mapping workshop / world_sky terrace-with-hair (owner 2026-09-08), pinned SHAs.
- Each scene is rendered through F12 under CPU and GPU separately; the report records both render exit statuses, SHA-256-pinned output images and the per-channel
  metrics. GREEN requires successful CPU **and** GPU renders with paired artifacts — a CPU-only report cannot be represented as complete.
- ±5 % ROI mean ratio per channel, SSIM ≥ 0.95 on the GPU-vs-CPU pair as a gating metric (north-star §2(c)), and non-vacuity checks (checker contrast
  present, HDRI contribution present, hair-pixel coverage > 0) so a black or missing feature cannot pass.

#### Gate (d) native panels

- `tests/test_gate_native_panels.py`: adaptive on/off changes the sample-count AOV and lowers flat-region noise at a declared budget;
  denoise on/off lowers residual noise after settle; CPU and GPU.
- Driven only by native panel properties, never a custom property. Output-effect test, not a reachability test.
- Accuracy safeguard: compare adaptive-on and denoise-on outputs against a converged reference at a fixed budget, and require mean-error and
  detail-preservation (edge/texture) checks, so lower variance purchased by blurring or bias cannot pass. Numeric limits are predeclared in the test
  and the manifest: mean relative luminance error ≤ 2 % over the declared reference-comparison regions, and detail preservation (edge/texture gradient
  energy) ≥ 0.95 of the reference (frozen 2026-09-22, lead may adjust). Regions are declared in the manifest, not chosen after the fact.

#### Gate (e) triage

- Publish the severity rubric in `.astroray_plan/docs/KNOWN_ISSUES.md`: high = wrong image, crash, or a native setting silently ignored;
  medium = degraded but flagged; low = cosmetic.
- The LIVE open-issue population is captured at acceptance time — not a frozen count carried from the planning session — by an exact `gh issue list`
  query whose command, timestamp and full issue-ID snapshot are stored in the manifest. Reconciliation rule: every issue in the snapshot must have an
  independent signed rating; the snapshot is re-run and the query repeated until the delta is empty, and any unrated or newly-appeared issue blocks GREEN.
- Every open issue is rated under the rubric by an independent pass (Codex Terra), not by label — the gate cannot be met by relabeling.

#### Gate (f) clean install

- Fresh Blender profile; install the ZIP through Blender's own extension installer
  (distinct from `scripts/dev_addon.ps1`); machine without the build toolchain; one F12 render.
- Evidence in `docs/blender_parity/evidence/install-clean-machine/`, procedure in `docs/install-clean-machine.md`.

---

## Acceptance criteria

- [ ] `docs/blender_parity/acceptance_manifest.json` exists and every row's
      status is produced by the schema-enforced predicate; a hand-edited status
      is rejected by the validator.
- [ ] `coverage_report.py` runs headless in Blender and emits
      `docs/blender_parity/corpus_coverage.md` + JSON, with silent drops and
      CPU/GPU differences reported separately.
- [ ] The weighted scorer is validated on a synthetic 3-scene fixture against a
      hand-computed weighted score.
- [ ] The nine-scene coverage score is printed as PROVISIONAL, and the unfrozen
      original population is reported UNDEFINED (not computed).
- [ ] `tests/test_gate_native_panels.py` passes on CPU and GPU.
- [ ] The clean-machine install is documented and committed with its evidence.
- [ ] The severity rubric is published in `KNOWN_ISSUES.md` and every open issue
      has an independent rating.
- [ ] Both scripts are registered in `scripts/README.md`.
- [ ] GPU parity rows, the real-Blender viewport table and the clean-machine
      install each have their own execution slot recorded in the manifest
      (CPU-only lanes cannot produce them). Gate (c) GREEN additionally requires
      separate successful CPU and GPU render exit statuses, SHA-256-pinned
      images and metrics for every trio scene.
- [ ] Gate (b) GREEN requires a hash-locked, owner-ratified input manifest and
      linked evidence for every nonzero classification; a PROVISIONAL
      population is ineligible for GREEN.

---

## Non-goals

- Do not fix the failures the instruments measure (Stage 0b–0d batches).
- Do not introduce a new comparison metric stack (reuse pkg104 + pkg119b).
- Do not add engine code, registries, or a new UI.
- Do not relax any threshold to make a row green.
- Do not ratify the corpus population — the owner decides.

---

## Progress

- [ ] `coverage_report.py` + synthetic-fixture scorer validation.
- [ ] `harness.py` per-feature verdict export.
- [ ] `gate_manifest.py` + the manifest schema.
- [ ] Gate (c) trio parity report.
- [ ] Gate (d) native-panel smoke (CPU + GPU).
- [ ] Gate (e) rubric + independent triage.
- [ ] Gate (f) clean-machine evidence.
- [ ] Register both scripts in `scripts/README.md`.
- [ ] Absorb pkg259 Phase 4 residuals.

---

## Lessons

*(Fill in after the package is done.)*
