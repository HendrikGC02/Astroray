# pkg251 — Spectral band parameter reachability across callers

**Pillar:** 5
**Track:** A
**Status:** open — contract audit and architect review before implementation
**Estimated effort:** S/M, confirm after audit
**Depends on:** pkg250

---

## Goal

Before: wavelength-band defaults and parameter parsing differ across the
standalone CLI, the production Python GPU caller, and CPU and GPU dispatch, so
decimal and integer wavelength arguments may not reach the same band and output
mode may be inferred inconsistently. After: an audited, documented band and
output_mode contract — covering explicit/default wavelength bounds and
output_mode from CLI, Python and Blender to CPU and GPU dispatch — that
preserves visible-color workflows and deliberate infrared/band-aware outputs,
separates a parameter representation bug from an intentional spectral
integration domain, and is proven by runtime tests that parameter values reach
the intended backend.

---

## Context

Pillar 5 covers renderer interoperability and spectral foundations. The package
depends on pkg250, the standalone dispatch repair, and on the existing spectral
core. The differing band and parameter behaviors predate pkg250; that repair
mirrors the current GPU binding and does not establish complete band parity, so
a contract audit and detailed architect review are required before
implementation.

---

## Evidence

- 2026-09-06: The full-rebuild investigation found differing default band
  contracts: CPU SpectralPathTracer uses 360–830 nm; the production Python GPU
  caller uses 380–780 nm and derives output mode from its band.
- 2026-09-06: The standalone CLI parses an integer literal as an integer
  ParamDict value, while getFloat accepts a float; decimal wavelength arguments
  and integer-looking arguments may not reach the same band.
- 2026-09-06: Additional gate investigation — the existing GPU luma path
  accumulates equal XYZ components and then converts XYZ to linear sRGB; equal
  XYZ (E-white) is not D65-neutral sRGB: matrix row sums produce
  (1.2048, 0.9484, 0.9087) times the scalar signal.
- 2026-09-06: Pkg250's first exact-gray PNG assertion therefore failed; Terra
  confirmed the caller was correct.

---

## Reference

- `tests/test_integrator_float_param.py` — existing ParamDict::getNumber
  contract to reuse where compatible (see Key design decisions).
- `gpu-focused.log` — the initial failed log, remains in the rebuild artifacts.

---

## Prerequisites

- [ ] pkg250 standalone dispatch repair is complete.

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

The bounded phases below are UNRUN.

- Audit explicit/default wavelength bounds and output_mode from CLI, Python and
  Blender to CPU and GPU dispatch; establish a documented contract that
  preserves visible-color workflows and deliberate infrared/band-aware outputs.
- Separate a parameter representation bug from an intentional spectral
  integration domain.
- Reuse the existing ParamDict::getNumber and
  `tests/test_integrator_float_param.py` contract where compatible; do not add
  a parallel numeric parameter API.
- The replacement reachability test compares explicit RGB (zero CMF signal
  beyond 830nm) with positive band-radiance output in the same 900–910nm scene.
- Decide scalar-output units and display/metadata semantics in this audit; do
  not enshrine the tint as the desired scientific API.

#### Phase 1 — Trace callers and defaults

Trace all callers and defaults with the project index. Record a contract matrix
for omitted, integer, decimal and invalid bounds; visible/IR bands; explicit
and inferred output mode. Reuse existing spectral test/harness tools.

#### Phase 2 — Architecture and review gate

Astra architecture plus independent high-tier review decides compatibility,
validation and any migration before implementation. Cite the established
spectral method for numerical changes; no new transport algorithm is implied.

#### Phase 3 — Implement the accepted contract

Implement only the accepted parameter/default contract. Add runtime tests
proving values reach the intended backend, including invalid-input behavior.

#### Phase 4 — Measurement and visual evidence

Save matched CPU/GPU raw outputs and metadata; inspect visible renders and
appropriate band-output visualizations. Measure effects with declared units,
sampling uncertainty and existing physical gates, not a blanket RGB metric.

#### Phase 5 — Delivery gates

Caller/binding review, focused regressions, GPU lock, actual imported-module
identity, independent sign-off and evidence-backed docs are delivery gates.

---

## Acceptance criteria

- [ ] A contract matrix is recorded for omitted, integer, decimal and invalid
      bounds; visible/IR bands; explicit and inferred output mode, traced
      across all callers and defaults with the project index.
- [ ] Astra architecture plus independent high-tier review has decided
      compatibility, validation and any migration before implementation;
      numerical changes cite the established spectral method.
- [ ] Runtime tests prove values reach the intended backend, including
      invalid-input behavior, implementing only the accepted
      parameter/default contract.
- [ ] Matched CPU/GPU raw outputs and metadata are saved; visible renders and
      appropriate band-output visualizations are inspected.
- [ ] Effects are measured with declared units, sampling uncertainty and
      existing physical gates, not a blanket RGB metric.
- [ ] Delivery gates pass: caller/binding review, focused regressions, GPU
      lock, actual imported-module identity, independent sign-off and
      evidence-backed docs.

---

## Non-goals

- No astrophysics activation.
- No spectral-core replacement.
- No new arbitrary band default.
- No claim that current output is scientific instrument calibration.
- Do not choose new defaults merely to make a reference image pass.
- Filing does not preempt pkg241/240 or the mapped-texture sequence.
- Pkg251 preserves later research foundations while Pillar 4 stays PAUSED.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
