# pkg55-B-prime-cuda-gate-derivation — Two-tier CPU↔CPU / CPU↔GPU gate + decision #9 + A.1 checklist

**Pillar:** 5
**Track:** A / E (doc-only spec derivation; informs the wavefront CUDA-port methodology)
**Status:** done (PR #320, 2026-05-17) — two-tier CPU↔CPU / CPU↔GPU gate definition now authoritative in the pkg55 spec; design decision #9 added; A.1 ray-normalization checklist item added to Session-2c design doc; STATUS.md known-issues note resolved. **Unblocks pkg55-B' CUDA-port Sessions N+2..M.**
**Estimated effort:** ~½ day; doc-only (no code, no tests)
**Depends on:** PR #296 (pkg55-B' Session-2c technique review — the source of the §4.4 actions). pkg55-B' Session 2c done (PR #297).

---

## Goal

**Before:** The pkg55 spec's program-wide Phase B' staged-plan item 5
says *"Bit-identity gates each port"* for the CUDA-port sessions
(Sessions N+2..M). PR #296 §4.1 proves CPU↔GPU exact bit-identity is
**physically unachievable** (nvcc FMA fusion differs from host; CUDA
`sinf`/`expf`/`__fdividef` are not host libm and not IEEE-correctly-
rounded; SSE2 vs PTX intermediate rounding differs; host
`-ffast-math`/`/fp:fast` reassociation has no PTX equivalent). Shipping
the CUDA sessions against an impossible target re-triggers exactly the
Session-2c whack-a-mole one layer out, in vendor libm where it is worse.
The Session-2c NOTE in the spec flags this as advisory prose only; the
new 9th design decision ("shared-kernel, never re-transcribe") and the
A.1 ray-normalization checklist item are not yet captured anywhere
authoritative.

**After:** The pkg55 spec carries the §4.2 **two-tier gate**: the word
"bit-identity" appears **only** for CPU↔CPU; CPU↔GPU is a
ULP-bounded + relative-error-distribution + SSIM gate. Phase B' design
decisions include a 9th, authoritative decision — *"Wavefront is a
re-scheduling of one shared per-bounce kernel, never a
re-transcription"* — with the §3-verify structural CI checks as its
enforcement. The Session-2c design doc carries the A.1 ray-normalization
subtlety as an explicit checklist item (it has now regressed twice — once
on GPU in A.1, once on CPU in 2c). The advisory Session-2c NOTE is
converted into a hard pre-CUDA gate that points at this package as the
blocking action.

---

## Context

PR #296 (the pkg55-B' Session-2c first-principles technique review) §4.4
explicitly lists "Concrete spec actions (for the architect to file, not
done here)." The prior architect pass recommended (recommendation (ii))
filing these as **their own tracked package** that produces the in-place
pkg55 spec edits, rather than doing them silently — so the methodological
re-derivation has an acceptance gate and an audit trail. This package is
that filing.

The re-derivation is **forced before any CUDA-port session** but is
**not** a blocker for Sessions 3..N (growing-oracle expansion on CPU,
which keep the existing exact-0.0 CPU↔CPU gate, which PR #296 confirms is
correct and must stay). This dependency shape (blocks N+2..M only) is the
whole reason it is a small standalone doc package and not folded into the
Session-3 work.

PR #296 §4.4 verbatim actions:

1. Rewrite Phase B' staged-plan item 5 ("Bit-identity gates each port")
   to the §4.2 two-tier definition. The word "bit-identity" must appear
   *only* for CPU↔CPU.
2. Add to Phase B' design decisions a 9th decision: **"Wavefront is a
   re-scheduling of one shared per-bounce kernel, never a
   re-transcription"** — with the §3-verify structural CI checks as the
   enforcement. PR #296 calls this "the single most important invariant
   for sessions 3..N and currently *implicit and violated*."
3. Add the A.1 ray-normalization subtlety (pkg55 spec lines 156–157) to
   the Session 2c design doc as an explicit checklist item, because it
   has regressed twice (GPU in A.1, CPU in 2c).

The §4.2 two-tier gate (from PR #296):

| Layer | What is provable | Correct gate |
|---|---|---|
| CPU oracle ↔ CPU wavefront | Same code, same bytes, same order → byte-identical | **Exact 0.0 snapshot diff** (structural guarantee + witness). Keep as-is. |
| CPU production ↔ CPU `reference_pt_production` | Same RNG scheme, independent transcription tracking production | Bit-exact RGB at 1 spp (existing trip-wire). Keep as-is. |
| CPU wavefront ↔ CUDA wavefront | *Not* the same operations (different hardware) — only the same *algorithm* | **ULP-bounded per-stage agreement on PostInit/PostIntersect (geometry only, no transcendentals — ≤ a small fixed ULP bound, measured and pinned, not invented, e.g. ≤ 4 ULP), per-stage relative-error distribution with a hard p99.9 bound for Post-Shade/LightSample/RR, plus SSIM ≥ 0.985 image gate.** Harness's job is *localization*, not exact equality. |
| Whole program (final) | Algorithm parity, not bit parity | Original Phase B/C SSIM (≥0.985 vis / ≥0.97 NIR) + perf gates. Unchanged. |

The §3-verify structural CI checks (decision #9 enforcement, from
PR #296 §3 "How to verify" step 1): grep the wavefront stage TUs — there
must be **zero** `bvh->hit` in `stage_shade_*`, **zero** re-keyed
`WavefrontRNG` constructions in any stage (RNG comes from SoA), **zero**
`Ray(o,d)` constructions from SoA scalars. This is a static proof the
shared-kernel structural guarantee holds and should be a CI assertion.

The A.1 ray-normalization checklist item (pkg55 spec lines 156–157):
never `Ray ray(origin,direction)` from SoA scalars in a stage (the
constructor re-normalizes → the A.1 1-ulp drift). Serialize/restore the
`Ray`'s already-normalized fields directly (default-construct,
field-assign). Add a one-line comment citing the A.1 subtlety so
session 3+ does not regress it a third time.

## Reference

- PR #296: `.astroray_plan/docs/pkg55-B-session2c-technique-review.md`
  — §0 bottom-line (three structural divergences), §1.3 the gate framing
  (structural guarantee + empirical witness), §3 the shared-kernel
  technique + "How to verify" structural CI checks, §4.1 why CPU↔GPU
  exact equality is impossible, §4.2 the two-tier table, §4.3 why this
  preserves the methodology's localization value, §4.4 the three
  concrete spec actions this package executes.
- pkg55 spec: `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`
  — Phase B' staged-plan item 5 (line ~280, "Bit-identity gates each
  port"); Phase B' design decisions (lines ~283–292, currently 8 — add
  #9); the Session-2c NOTE (line ~277, advisory — convert to a hard
  pre-CUDA gate pointer); A.1 ray-normalization subtlety (lines
  ~156–157).
- Session-2c design doc:
  `.astroray_plan/docs/pkg55-B-cpu-reference-design.md` (the 8
  design decisions in code-level detail; the A.1 checklist item is
  appended here).
- First-principles addon plan: `.astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md`
  (PR #300) §7 item 4 — the recommendation that the §4.4 reword is folded
  into the same amendment as the BUG-02/10/11/12 named gates (those
  named-gate cross-refs are a *separate* pkg55 spec edit filed alongside
  this package; this package owns only the §4.4 reword).

## Prerequisites

- [ ] PR #296 reviewed (it is an open doc PR; its §4.4 is the
      authoritative source for this package's edits).
- [ ] pkg55-B' Session 2c done (PR #297) — the exact-0.0 CPU↔CPU gate it
      demonstrated is the thing the two-tier split preserves.

## Specification

### Key design decisions

1. **Doc-only; the deliverable is the in-place pkg55 spec edits.** This
   package produces no code and no tests. Its output is a doc-only PR
   amending `pkg55-wavefront-soa-refactor.md` and the Session-2c design
   doc. *Rationale:* prior architect pass recommendation (ii) — a tracked
   package with an acceptance gate, not a silent edit.
2. **The word "bit-identity" appears only for CPU↔CPU.** Every CPU↔GPU
   reference in the spec becomes the §4.2 bounded+SSIM gate. *Rationale:*
   PR #296 §4.1 — exact host↔device equality is physically impossible;
   leaving the word forces the CUDA sessions into the Session-2c crisis.
3. **Decision #9 is authoritative, not advisory.** "Wavefront is a
   re-scheduling of one shared per-bounce kernel, never a
   re-transcription," enforced by the §3-verify structural CI checks
   (zero `bvh->hit` in `stage_shade_*`; zero re-keyed `WavefrontRNG`;
   zero `Ray(o,d)` from SoA scalars). *Rationale:* PR #296 §3 — this is
   the single most important invariant for Sessions 3..N and is currently
   implicit and was violated pre-2c.
4. **Convert the Session-2c NOTE from prose to a hard pre-CUDA gate.**
   The advisory NOTE becomes "BLOCKING: before any CUDA-port session
   (N+2..M), `pkg55-B-prime-cuda-gate-derivation` must be done." This
   package is the blocking action it points at.
5. **Scope discipline.** This package owns *only* the §4.4 three actions.
   The BUG-02/10/11/12 named-gate cross-refs and the Session-2c-NOTE
   blocking pointer are a *separate* pkg55 spec edit filed alongside (in
   the same Round-10 doc PR) — recorded here for traceability but not
   this package's deliverable text.
6. **GATE-THRESHOLDS-PINNED (named gate, not prose).** The CPU↔GPU gate
   *form* is fixed here, but the *numbers* are not closed until measured.
   The named gate is: **the first CUDA-port session (pkg55-B' Session
   N+2) MUST pin the numeric ULP bound (PostInit/PostIntersect geometry),
   the p99.9 relative-error percentile bound (Post-Shade/LightSample/RR),
   and the SSIM floor *before* any CUDA code change in that session.**
   The gate is **not "closed"** until these three numbers are written
   into this spec (replacing the `≤ 4 ULP` / `p99.9` / `SSIM ≥ 0.985`
   placeholders, which are explicitly flagged "measured-and-pinned, not
   invented"). **Sessions N+2..M are blocked until GATE-THRESHOLDS-PINNED
   is satisfied** — measurement-then-pin is the first action of Session
   N+2, gating any kernel edit in that and every subsequent CUDA session.
   *Rationale:* PR #296 §4.2 — pinning the form without forcing the
   numbers to be measured-first would let the CUDA sessions drift the
   thresholds to whatever the current code happens to produce, defeating
   the gate.

### Files to modify (the deliverable)

| File | What changes |
|---|---|
| `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` | (1) Phase B' staged-plan item 5 rewritten to the §4.2 two-tier definition; "bit-identity" used **only** for CPU↔CPU. (2) New Phase B' design decision #9: "Wavefront is a re-scheduling of one shared per-bounce kernel, never a re-transcription" + the §3-verify structural CI checks as enforcement. |
| `.astroray_plan/docs/pkg55-B-cpu-reference-design.md` | Append the A.1 ray-normalization subtlety (spec lines 156–157) as an explicit checklist item — it has regressed twice (GPU A.1, CPU 2c). |

### Files to create

| File | Purpose |
|---|---|
| *(none)* | Doc-only package; no new files, no tests. The acceptance gate is a textual assertion over the two edited docs. |

## Acceptance criteria

- [ ] In `pkg55-wavefront-soa-refactor.md`, Phase B' staged-plan item 5
      no longer says "bit-identity" for CPU↔GPU; it states the §4.2
      two-tier gate (CPU↔CPU exact-0.0; CPU↔GPU ULP-bounded +
      relative-error p99.9 + SSIM ≥ 0.985). The word "bit-identity"
      appears in the spec only in a CPU↔CPU context.
- [ ] Phase B' design decision **#9** is present and authoritative:
      "Wavefront is a re-scheduling of one shared per-bounce kernel,
      never a re-transcription," with the §3-verify structural CI checks
      (zero `bvh->hit` in `stage_shade_*`; zero re-keyed `WavefrontRNG`;
      zero `Ray(o,d)` from SoA scalars) named as the enforcement.
- [ ] The Session-2c design doc
      (`pkg55-B-cpu-reference-design.md`) carries the A.1
      ray-normalization checklist item.
- [ ] The Session-2c NOTE is converted from advisory prose into a hard
      pre-CUDA gate pointing at `pkg55-B-prime-cuda-gate-derivation` as
      the blocking action for Sessions N+2..M (note: the literal
      conversion is the companion pkg55 edit filed in the same Round-10
      doc PR; this criterion verifies the pointer exists and names this
      package).
- [ ] **GATE-THRESHOLDS-PINNED** is recorded in the spec as a named gate:
      it explicitly states that pkg55-B' Session N+2 must pin the numeric
      ULP bound, the p99.9 percentile bound, and the SSIM floor **before**
      any CUDA code change, that the gate is not "closed" until those
      three numbers are written into the spec, and that Sessions N+2..M
      are blocked until it is satisfied.
- [ ] No code, no test, no behavior change anywhere.

## Non-goals

- Do **not** weaken the CPU↔CPU gate. Exact 0.0 by shared-kernel
  construction (Session 2c) is correct and stays — PR #296 §4.2 row 1.
- Do **not** start, design, or scope any CUDA-port session. This package
  only re-derives the *gate*; it does not begin the work it gates.
- Do **not** add the BUG-02/10/11/12 named gates here — that is a
  separate pkg55 spec edit (filed alongside in the same doc PR).
- Do **not** edit STATUS / ROADMAP / NEXT_STAGE_REPORT from this package
  — those Round-10 doc updates are filed alongside but are not this
  package's deliverable.
- Do **not** invent ULP/relative-error numbers. The CPU↔GPU bound is
  *measured and pinned* during the first CUDA-port session, not chosen
  here; this package fixes the gate *form* (PR #296 §4.2), with the
  example ≤ 4 ULP / p99.9 / SSIM ≥ 0.985 placeholders flagged as
  "measured-and-pinned, not invented."

## Progress

- [ ] Phase B' staged-plan item 5 rewritten to the two-tier gate.
- [ ] Phase B' design decision #9 added with the structural CI checks.
- [ ] A.1 ray-normalization checklist item appended to the Session-2c
      design doc.
- [ ] Companion pkg55 edit (NOTE → hard pre-CUDA gate pointer) confirmed
      present in the same doc PR.
- [ ] Doc-only PR opened; no code touched.

## Lessons

*(Fill in after the package is done.)*

This package exists because PR #296 proved the program-wide
"bit-identity gates each port" line is physically unsound for CPU↔GPU and
would re-trigger the Session-2c whack-a-mole in vendor libm. Filing the
§4.4 actions as a tracked package — rather than a silent spec edit —
gives the methodological re-derivation an acceptance gate and makes the
"blocks only N+2..M" dependency explicit so Sessions 3..N proceed
unblocked.

---

## Track routing / acceptance gate

- **Track A / E.** Doc-only spec derivation; no GPU, no
  hardware-verifier, no tests. The acceptance gate is the textual
  assertion over the two edited docs (below).
- **Round-10 sequencing:** depends on PR #296. **Blocks ONLY pkg55-B'
  CUDA-port Sessions N+2..M.** **Does NOT block Sessions 3..N** — those
  keep the existing exact-0.0 CPU↔CPU gate and proceed in parallel.
  Independent of the addon track (pkg94/95/96) and concurrent with it.
- **Acceptance gate (one line):** the pkg55 spec no longer says
  "bit-identity" for CPU↔GPU; Phase B' design decision #9
  ("shared-kernel, never re-transcribe") is present with its structural
  CI checks; the A.1 ray-normalization checklist item is present in the
  Session-2c design doc; and the **GATE-THRESHOLDS-PINNED** named gate is
  recorded (Session N+2 pins ULP / p99.9 / SSIM numbers before any CUDA
  code change; Sessions N+2..M blocked until pinned).
