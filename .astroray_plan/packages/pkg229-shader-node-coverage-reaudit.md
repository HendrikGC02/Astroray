# pkg229 — Shader-node / socket coverage re-audit + next-wave ranking

**Pillar:** 5
**Track:** A
**Status:** done — report .astroray_plan/docs/blender-coverage-reaudit-2026-09.md, 2026-09-05
**Estimated effort:** 1 session (~3–4 h)
**Depends on:** pkg119, pkg195, pkg219, pkg219d, pkg223, pkg223b

---

## Goal

Before: the last authoritative Blender socket-coverage numbers are stale.
pkg119-A (2026-07-19) measured **131 SUPPORTED / 23 APPROXIMATED / 370
DROPPED-SILENT / 20 stale of 524** socket-level features; the owner's
2026-08-29 assessment cited **117 / 22 / 385** and explicitly asked to
"re-audit the coverage numbers next pass." Since then a large amount of
shader-node infrastructure has landed — **pkg195** (spectral node system, all
3 stages), **pkg219a/b/c** (coordinate/Mapping unification + per-texel op-VM
evaluator + opcode fill-out), **pkg219d** (scalar parameter textures →
roughness/metallic/transmission/IOR), **pkg223** (tangent-space normal maps),
**pkg223b** (Bump node) — none of which is reflected in a re-run of the
coverage matrix. After: the coverage matrix is regenerated against current
`main`, the deltas since 2026-07-19 are attributed to the packages that closed
them, and a **frequency-weighted, ranked list of the top remaining
DROPPED-SILENT sockets** is produced to drive the next integration-first
feature wave. This is the honest "where is Blender integration actually at"
measurement the owner requested — the precursor that tells us whether
integration is close or still far, and what to build next.

---

## Context

We are steering integration priorities off a 6-week-stale measurement. This
package re-measures mechanically (no hand-classification), so the next wave of
feature specs is grounded in current, frequency-ranked evidence rather than
guesswork. It is cheap, CI-verifiable, GPU-free, and its output is directly a
ranked backlog. At filing, all dependency inputs had already landed: the
pkg119-A generator, pkg195, pkg219a/b/c, pkg219d, pkg223, and pkg223b.

---

## Evidence

- Memory `integration-first-directive-2026-08`: the integration-first
  directive puts rigorous Blender/DCC integration ahead of new engine
  features, and the owner judges the Pillar 4 gate NOT MET partly on socket
  coverage.
- The last authoritative matrix is pkg119-A (2026-07-19, PR #487): **131
  SUPPORTED / 23 APPROXIMATED / 370 DROPPED-SILENT / 20 stale of 524**
  socket-level features; the owner's 2026-08-29 assessment cited **117 / 22 /
  385** and explicitly asked to "re-audit the coverage numbers next pass."
- The coverage number driving that Pillar-4-gate judgment predates the entire
  pkg195/pkg219*/pkg223* shader-node wave — pkg195, pkg219a/b/c, pkg219d,
  pkg223, and pkg223b have landed since and are not reflected in a re-run of
  the coverage matrix.

---

## Reference

- Generator (already exists, AST-scanned, no hand-typed tables):
  `scripts/generate_blender_parity_matrix.py` — emits `coverage_matrix.json`
  + `report.md`; runs headless in Blender
  (`blender --background --factory-startup --python … -- --out docs/blender_parity`).
- Prior authoritative matrix: pkg119-A (PR #487), numbers in
  `ROADMAP.md` (2026-07-19 round closeout) and STATUS/owner-assessment
  2026-08-29.
- Differential harness (for spot-verifying reclassified rows renders-correct,
  not just AST-present): pkg119 Phase B, `scripts/run_parity.py` /
  `summarize_parity.py`.
- Blender is installed locally (memory `blender-5-1-installed-locally`) — run
  the generator yourself headless; do not defer to the owner.

---

## Prerequisites

- [ ] Build passes on main; addon `.pyd` staged and current w.r.t. HEAD
      (the generator bootstraps the real addon + `.pyd`; a stale addon build
      under-reports SUPPORTED — memory `staged-addon-pyd-stale-vs-head`).
      Rebuild the addon (`build_blender_addon.py --backend cuda`) before the
      run and confirm the canary.
- [ ] Blender 5.1/5.2 headless launch works (pkg119-B runbook).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md` | The re-audit report: new SUPPORTED/APPROX/DROPPED-SILENT counts, delta table vs 2026-07-19 attributed to closing packages, and the ranked top-N DROPPED-SILENT sockets with usage-frequency rationale |
| `docs/blender_parity/coverage_matrix.json` | Regenerated machine-readable matrix (generator output; commit the refreshed artifact) |

### Files to modify

| File | What changes |
|---|---|
| `scripts/generate_blender_parity_matrix.py` | ONLY if the AST scanner misses a genuinely-landed evidence pattern (e.g. the pkg219 op-VM `ProgramTexture` path, pkg219d scalar-param side-table, pkg223 normal/bump consumption) and therefore mis-reports a SUPPORTED socket as DROPPED-SILENT. Any scanner change must be justified in the report with the specific node/socket it corrects and cross-checked against a real headless render via pkg119-B. Do NOT add hand-typed classification tables. |

### Key design decisions

- **Mechanical re-measure first, interpret second.** Run the generator
  unchanged, diff against the last matrix, and only touch the scanner if a
  concrete false-DROPPED-SILENT is proven (AST evidence exists in the addon
  but the scanner's pattern-matcher misses it). The whole value of pkg119-A
  is that classification is evidence-extracted, not asserted — preserve that.
- **Rank by real usage frequency, not raw count.** 385 dropped sockets are
  not equal. Weight the ranking by how often each node/socket appears in
  practice (Principled inputs, Color Ramp, Mix, Math, Mapping, common texture
  nodes rank far above exotic sockets). The deliverable is a *prioritized*
  backlog, not a flat list.
- **Attribute the delta.** For every socket that moved DROPPED-SILENT →
  SUPPORTED/APPROXIMATED since 2026-07-19, name the package that closed it
  (pkg195 / pkg219* / pkg223*). This validates the shader-node wave's ROI and
  is the evidence the owner's Pillar-4-gate re-assessment needs.
- **Spot-verify, don't trust AST alone.** For the top ~5 newly-SUPPORTED
  high-frequency sockets, confirm they actually render correctly via a
  pkg119-B differential render, not just that the AST scanner found a read
  (memory `PR-named-tests-insufficient`, `pkg119b-harness-runbook`). A socket
  that is "consumed" but renders wrong is not SUPPORTED.

---

## Acceptance criteria

- [ ] `coverage_matrix.json` regenerated against current `main` and committed;
      generator run is reproducible (documented command line).
- [ ] Report gives current SUPPORTED / APPROXIMATED / DROPPED-SILENT / stale
      counts and a delta table vs the 2026-07-19 baseline, each moved socket
      attributed to its closing package.
- [ ] Ranked top-N (N ≥ 15) remaining DROPPED-SILENT sockets, frequency-weighted,
      each with a one-line "what it would take to close" note sized S/M/L — this
      is the ready-to-spec next-wave backlog.
- [ ] Top ~5 newly-SUPPORTED high-frequency sockets spot-verified via a real
      headless-Blender differential render (not AST-only).
- [ ] If the scanner was changed, the specific corrected socket(s) are named
      and each is backed by a render, not just an AST match.

---

## Non-goals

- Do not implement any new socket support in this package — this is
  measurement + ranking only. The ranked list feeds *follow-up* feature specs.
- Do not hand-edit classification tables into the generator.
- Do not touch any GPU shade-kernel code.
- Do not re-open Pillar-4-paused work; coverage of astro-data sockets is out
  of scope.

---

## Progress

- [ ] Rebuild + stage addon `.pyd`; confirm canary (new pkg219d/pkg223 methods present)
- [ ] Run the generator headless; capture `coverage_matrix.json` + `report.md`
- [ ] Diff vs 2026-07-19 matrix; attribute deltas to closing packages
- [ ] Investigate any suspicious false-DROPPED-SILENT (op-VM / scalar-param / normal-bump paths); fix scanner only if a real miss is proven + render-verified
- [ ] Build the frequency-weighted ranked backlog with S/M/L close-effort notes
- [ ] Spot-verify top-5 newly-SUPPORTED sockets via pkg119-B differential render
- [ ] Write `blender-coverage-reaudit-2026-09.md`; open PR

---

## Lessons

- (none yet)
