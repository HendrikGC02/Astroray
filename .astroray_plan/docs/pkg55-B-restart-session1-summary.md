# pkg55 Phase B' — Restart Session 1 Summary

**Date:** 2026-05-14
**Branch:** `pkg55-B-restart`
**Output:** spec amendment only — no code.

---

## Why this session pivoted from implementation to spec amendment

The restart scope that the previous 8 sessions of fork-resolution had been
dispatching against lived only in dispatch briefs and the architect's
strategy doc. It was NOT in the on-disk `pkg55-wavefront-soa-refactor.md`
spec. Per `CLAUDE.md` §2 (simplicity first) and §3 (surgical changes), the
spec is authoritative; everything else is supporting material.

Continuing to resolve ambiguities against a non-authoritative source was
silently widening scope across multiple sessions. The productive output
from Session 1 is therefore to capture all of the work done across those
sessions into authoritative spec language, so the next implementer works
from the spec — not from a chain of dispatch briefs whose decisions only
exist in chat history.

The pivot was: **stop implementing, write down what we already decided.**

---

## The 8 ambiguities that surfaced and their resolutions

Each resolution is now authoritative spec text under Phase B' §"Design
decisions" in `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`.
The short form, with rationale:

### §1 — Spectral oracle, not RGB

**Question.** Should the CPU reference oracle and CPU wavefront carry
spectral state (`SampledWavelengths`, `SampledSpectrum`) end-to-end, or
should we build an RGB-only oracle first and add spectral later?

**Resolution.** Spectral end-to-end. RGB only at the final
XYZ→sRGB conversion.

**Rationale.** The eventual GPU wavefront is spectral (matching production
`SpectralPathTracer`). An RGB-only oracle would require a wholesale
transcription pass when adding spectral, which is exactly the kind of
"oracle drift" Phase B' is designed to avoid. Better to pay the spectral
cost on day one and have the oracle stay structurally aligned with the
production target.

### §2 — Per-path RNG keying for wavefront; tile-shared for production

**Question.** What RNG scheme does the CPU wavefront use? Match
production's tile-shared `mt19937(baseSeed + tileIdx)`, or match Phase
A.1's GPU per-path `mt19937(hash(pixel, sample, 0))`?

**Resolution.** The wavefront side uses per-path keying. The production
side keeps tile-shared. The two are byte-incompatible but statistically
equivalent.

**Rationale.** The wavefront pipeline must match what Phase A.1 already
established on the GPU — per-path keying is mandatory there because there
are no "tiles" in the wavefront sense. Forcing the production CPU path
tracer to also adopt per-path keying would change production output and
break unrelated SSIM gates. So we accept the two schemes and validate
their statistical equivalence (see §3).

### §3 — Two reference PTs (Option Z), not one

**Question.** One reference PT, or two? If one, which RNG scheme?

**Resolution.** Two. `reference_pt_production` uses tile-shared RNG
(matches production); `reference_pt_wavefront` uses per-path RNG (matches
wavefront). A trip-wire test asserts `reference_pt_production` ==
production at the byte level. An equivalence test asserts SSIM ≥ 0.99
between the two oracles at 64 spp.

**Rationale.** A single oracle can't simultaneously be byte-equal to
production (which needs tile-RNG) and byte-equal to the wavefront (which
needs per-path RNG). Two oracles, one for each comparison, is the only
way to get both bit-exact gates.

### §4 — Scoped oracles (Option C), not full-surface transcription

**Question.** Do the reference PTs cover the full production feature
surface from day one (Disney, dielectric, SMS, GR, spectral upsampling
etc.), or only what the current CPU wavefront actually supports?

**Resolution.** Scoped. Session 2 reference PTs cover lambertian +
area lights + Cornell only. The oracles grow alongside the wavefront,
session by session.

**Rationale.** A full-surface oracle would trip on noise from features
the wavefront doesn't yet implement, defeating the diff harness's
purpose. And building a 100% transcription of pkg64 SMS / pkg67 GR /
pkg54c spectral upsampling / Disney / dielectric on day one is the kind
of scope explosion that killed the original Phase B.

### §5 — Callable driver, not a registered plugin (yet)

**Question.** Should the CPU wavefront be exposed as a registered
integrator plugin (`wavefront_path_tracer`) from Session 2, or as a
callable driver behind a pybind11 entry point?

**Resolution.** Callable driver. Plugin registration is deferred to the
final phase of B'.

**Rationale.** Plugin registration brings Blender-dropdown wiring,
`integrator_capabilities` flags, and dropdown-state migration concerns
into every session. None of that helps the per-stage diff work. Keep the
surface tight; register the plugin once it actually works.

### §6 — Reference PT is a separate file (Option C2), not hooks on production

**Question.** Add instrumentation hooks to production
`Renderer::pathTraceSpectral` so that the same code can be run as oracle,
or write a separate transcription file?

**Resolution.** Separate file. Production is untouched.

**Rationale.** Instrumentation hooks bloat production with diff-harness
state and risk perturbing production output. A separate file with a
trip-wire that asserts bit-equality is cleaner: production stays clean,
drift is detected by the test rather than by branching in production
code.

### §7 — Snapshot data structures

**Question.** How does the diff harness compare wavefront vs reference
PT? At the pixel level (final image), at the path level (final
radiance), or at each stage boundary?

**Resolution.** Stage-boundary snapshots. Both reference PTs emit
`WavefrontSnapshot` records at each stage boundary (post-init,
post-intersect, post-shade, post-light-sample, post-RR). The diff
harness compares snapshots element-by-element to localize divergence.

**Rationale.** Final-pixel comparison localizes the bug to "somewhere in
the pipeline" — useless when the original Phase B had three cascading
bugs at different stages. Stage-boundary snapshots tell you "the bug is
in stage_shade_lambertian, slot 47, field path_throughput, after sample
2" — actionable.

### §8 — Growing-oracle lifecycle

**Question.** Once we have the lambertian-Cornell oracle in Session 2,
what happens to it in Session 3 (metal)? Does it stay frozen, get
deleted, or grow?

**Resolution.** Growing oracle. Reference PTs grow incrementally as the
CPU wavefront adds materials. When the wavefront adds metal, the
reference PTs add metal in the same PR. The oracles never lead the
wavefront and never lag it.

**Rationale.** "Frozen oracle" forces every new material to invent its
own diff strategy. "Deleted oracle" loses the per-stage gate the moment
we move past lambertian. "Growing oracle" keeps the gate alive forever
with O(material) effort per session, which is the same effort we'd spend
anyway on the wavefront side.

---

## Next-session pickup instructions

The next implementer (Session 2) should:

1. **Read the amended spec, not these dispatch briefs.** The
   authoritative scope lives in
   `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`, Phase B'
   subsection. The 8 design decisions there are authoritative — do not
   re-litigate them.
2. **Write the design doc first** at
   `.astroray_plan/docs/pkg55-B-cpu-reference-design.md`, expanding the
   8 decisions into code-level detail (field layouts, function
   signatures, snapshot record format).
3. **Implement Session 2 deliverables** as listed in the spec's
   Phase B' staged plan §2. The close gate is bit-identity of CPU
   wavefront vs `reference_pt_wavefront` on Lambertian-only Cornell at
   1 spp.
4. **Do not touch** the AoS megakernel or `origin/pkg55-phase-b`.
   Phase B's branch is held, not deleted; the historical work stays
   reachable.
5. **Do not widen scope.** If something feels under-specified, stop and
   ask — do not silently extend. The 8 forks above are what 8 sessions
   of silent scope-widening cost; don't add a 9th.

---

## Deliverables (this session)

- Spec amendment landed in
  `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` (Phase B
  status note + new Phase B' subsection inserted between Phase B and
  Phase C; acceptance summary table updated to include B').
- This summary doc.
- PR opened against `main` (do not merge — owner reviews).
