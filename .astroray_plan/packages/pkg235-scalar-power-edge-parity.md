# pkg235 — Scalar Math POWER edge-case parity

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** pkg230

---

## Goal

Before: the existing scalar `svm_safe_powf(0,-1)` returns infinity, diverging
from the pinned Blender 5.1 Cycles reference. After: scalar Math POWER
numerical edge semantics are audited and corrected against that pinned
reference, including CPU/CUDA parity and Blender scalar-input conversion, and
only that bounded scope.

---

## Context

This package serves Pillar 5 (Blender numerical shader behavior). It depends on
the pkg230 shared op-VM, with no owner queue promotion. Estimated effort was
left TBD. This filing records discovered parity debt; it does not claim
implementation readiness or outrank the owner's post-pkg230 package choice.

---

## Evidence

- During pkg230 Phase 2 integration, a native host canary demonstrated that the
  existing scalar `svm_safe_powf(0,-1)` returns infinity.
- Pinned Blender 5.1 Cycles `util/math_base.h::compatible_powf` returns zero
  for zero base and nonzero exponents, and one for any zero exponent, including
  0^0. Cycles also guards negative bases separately on GPU.
- Phase 2's Vector Math helper handles these cases; the older scalar Math POWER
  helper was deliberately not changed.
- 2026-09-06: Independent Claude filing review: SIGN-OFF TO FILE ONLY.
  Evidence: `test_results/pkg232-235/claude-filing-review.txt`.

---

## Reference

- Pinned reference: Blender 5.1 Cycles `util/math_base.h::compatible_powf`.
- Filing-review evidence: `test_results/pkg232-235/claude-filing-review.txt`.

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

- Before dispatch, determine the domain guarantees and compatibility impact of
  replacing existing non-finite results.
- Preserve opcode encoding and clamp flags.

---

## Acceptance criteria

All implementation gates are UNRUN.

- [ ] Cite licensed Cycles reference and define finite-input/exception behavior.
- [ ] Zero bases, zero/negative/integer/fractional exponents, and negative
      bases match explicit Cycles oracles on CPU and CUDA.
- [ ] Ordinary positive-domain results and use_clamp behavior remain correct.
- [ ] Real image-driven Blender Math POWER graphs exercise export and
      evaluation; saved representative outputs receive Astra/Claude qualitative
      review.
- [ ] Fresh native/import/architecture gates, caller/binding and resource
      review, documented regression tests, and independent Claude sign-off.

---

## Non-goals

- No broader numerical-math rewrite, VM layout/limit changes, transport
  changes, coordinate VM, new UI, or astrophysics work.
- Pillar 4 remains paused.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
