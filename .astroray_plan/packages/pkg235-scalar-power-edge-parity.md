# pkg235 — Scalar Math POWER edge-case parity

**Pillar:** 5 (Blender numerical shader behavior)
**Track:** A
**Status:** OPEN — detailed architect review required before dispatch
**Depends on:** pkg230 shared op-VM; no owner queue promotion

## Evidence and bounded goal

During pkg230 Phase 2 integration, a native host canary demonstrated that the
existing scalar `svm_safe_powf(0,-1)` returns infinity. Pinned Blender 5.1 Cycles
`util/math_base.h::compatible_powf` returns zero for zero base and nonzero
exponents, and one for any zero exponent, including 0^0. Cycles also guards
negative bases separately on GPU. Phase 2's Vector Math helper handles these
cases; the older scalar Math POWER helper was deliberately not changed.

Audit and correct only scalar Math POWER numerical edge semantics against that
pinned reference, including CPU/CUDA parity and Blender scalar-input conversion.
Before dispatch, determine the domain guarantees and compatibility impact of
replacing existing non-finite results. Preserve opcode encoding and clamp flags.

## Acceptance — all implementation gates UNRUN

- [ ] Cite licensed Cycles reference and define finite-input/exception behavior.
- [ ] Zero bases, zero/negative/integer/fractional exponents, and negative bases
      match explicit Cycles oracles on CPU and CUDA.
- [ ] Ordinary positive-domain results and use_clamp behavior remain correct.
- [ ] Real image-driven Blender Math POWER graphs exercise export and evaluation;
      saved representative outputs receive Astra/Claude qualitative review.
- [ ] Fresh native/import/architecture gates, caller/binding and resource review,
      documented regression tests, and independent Claude sign-off.

## Non-goals

No broader numerical-math rewrite, VM layout/limit changes, transport changes,
coordinate VM, new UI, or astrophysics work. Pillar 4 remains paused. This filing
records discovered parity debt; it does not claim implementation readiness or
outrank the owner's post-pkg230 package choice.

Independent Claude filing review: SIGN-OFF TO FILE ONLY, 2026-09-06.
Evidence: `test_results/pkg232-235/claude-filing-review.txt`.
