# pkg141 — GPU near-delta Disney-metal over-brightness (GPU/CPU 2.7–4.0× at roughness→0; adjudicate pdf-convention asymmetry vs closure-graph twin)

**Pillar:** 3 (GPU/CPU parity / MIS-pdf consistency)
**Track:** A (GPU lane; RTX-gated — CI is blind to it)
**Codex-paste-ready:** no (diagnostic-first: two candidate mechanisms must be distinguished by instrumentation before the fix is chosen; the fix then needs parity + wavefront-diff re-validation)
**Status:** open — **blocked on pkg123 (PR #498) merging first** (the CPU is the canonical baseline only post-#498; the evidence xfail rows live on that branch)
**Estimated effort:** M (instrumentation + one localized fix + un-xfail; the risk is the fix touching the shared GPU sampling path used by both megakernel and wavefront)
**Depends on:** **pkg123 (PR #498)**. Related but distinct from **pkg124** (CPU VNDF swap for the opaque lobe — do not entangle; land order between pkg141 and pkg124 is free, but each must leave the other's gates green) and **pkg138** (dielectric eval — different lobe). This package OWNS the CPU/GPU mixture-pdf asymmetry that pkg138's Notes flagged as out-of-scope.

---

## Context — measured tonight (2026-07-20 overnight), pre-existing on main

GPU renders Disney **metal at roughness = 0.0** substantially brighter than the
CPU reference:

- **GPU/CPU mean ratio 2.70×** on PRE-#498 main (GPU 0.02387 vs CPU 0.00884).
- The GPU image is **byte-identical pre/post #498** (the #498 fixes are
  CPU-side) — so this is NOT a #498 regression; it is a pre-existing GPU
  defect exposed by tightening the CPU.
- Post-#498 the CPU is canonical (chi²-adjudicated), and the measured gap
  becomes **4.0×**.
- Evidence is **xfail'd** in
  `tests/test_pkg123_disney_metal_gpu_cpu_parity.py` (near-delta rows) on the
  #498 branch — this package un-xfails them.

## Candidate mechanisms (adjudicate FIRST — do not fix blind)

Instrument before fixing; the two suspects live in different code and imply
different fixes:

**S1 — sample-pdf convention asymmetry (flagged by the #498 Opus review,
recorded in pkg138 Notes).** The CPU opaque-specular `sample()` returns the
**full-mixture** density: `s.f = eval(...)`, `s.pdf = pdf(...)`
(`plugins/materials/disney.cpp:512-514`, post-#498 anchors). The GPU inline
sampler pairs the **full-mixture f** with a **selected-lobe-only pdf**:
`s.f = gpu_disney_eval(...)` (full mixture) but
`s.pdf = D·NdotH/(4·HdotV) · (specW/total)` — the specular-lobe density only
(`include/astroray/gpu_materials.h:849-857`). A full-mixture `f` over a
partial-mixture `pdf` is an inconsistent one-sample estimator (Veach 1997
§9.2 one-sample model: with lobe-selection probability folded in, either pair
full-f with full-mixture pdf, or lobe-f with lobe-pdf — never mixed). Whether
this quantitatively yields 2.7–4.0× at near-delta must be shown by the
instrumentation, not assumed: dump `(f, pdf, f/pdf)` per event CPU-vs-GPU for
identical `(wo, wi)` at roughness 0 and compare.

**S2 — the GPU closure-graph Disney twin.** Plain dielectric/Disney-glass
shades via `GMAT_CLOSURE_GRAPH` on the GPU, not the inline path (memory:
`gpu-dielectric-lowers-to-closure-graph`, PR #404 fixed an eta²-clamp there).
**Check whether Disney METAL also lowers to the closure graph** in the scene
used by the parity test — if it does, the defect may live in the closure-graph
metal lobe (its own F/D/G or pdf), and `gpu_materials.h:849-857` is not even
the executing code. Instrument: log which GPU material path
(`GMAT_*`/closure-graph node) actually shades the test sphere.

**Ruled out by architect pre-check:** the near-delta roughness clamp is
IDENTICAL on both sides — `max(roughness², 0.0064)` at
`disney.cpp:{99,178,208,346,501,530}` and `gpu_materials.h:{519,606,638,714,833}`
(verified 2026-07-20) — so an alpha-floor mismatch is not the mechanism.

## Fix plan (cite — no inventions, CLAUDE.md §6)

After adjudication, fix the guilty site so **CPU and GPU compute the same
estimator term-for-term**:

- If **S1**: make the GPU sampler's `(f, pdf)` pair consistent — either mirror
  the CPU's full-mixture convention (pdf of the whole mixture at the sampled
  direction, matching `disney.cpp:514`) or the selected-lobe convention on BOTH
  f and pdf. **Prefer mirroring the CPU** (it is the chi²-validated canonical
  side post-#498). Cite Veach 1997 §9.2 (one-sample mixture estimator) and the
  CPU implementation as the in-repo generator; Cycles
  `intern/cycles/kernel/closure/bsdf.h` (`bsdf_sample`/`bsdf_pdf` mixture
  handling) as the production cross-reference.
- If **S2**: fix the closure-graph metal lobe against the same references (and
  the #404 precedent for how closure-graph energy bugs get fixed + gated).
- Either way: the megakernel and wavefront share this code — run BOTH legs.

## Verification gates

- [ ] Instrumentation note recorded in the PR: which mechanism (S1/S2/other),
      with the per-event `(f, pdf)` dump or path-taken log as evidence.
- [ ] **Un-xfail the near-delta rows of
      `tests/test_pkg123_disney_metal_gpu_cpu_parity.py`** — GPU/CPU mean ratio
      within the test's parity band at roughness 0.0 (and the near-delta grid
      the test covers), on RTX.
- [ ] Rough-metal no-regression: mid/high-roughness metal parity rows stay
      green (the fix must not shift the already-agreeing regime).
- [ ] Wavefront-diff gate suite stays green (megakernel + wavefront legs both
      re-run — shared sampling code).
- [ ] White-furnace / energy gates on metal stay green.
- [ ] If S1: the CPU/GPU "mixture-pdf asymmetry" flag in pkg138's Notes is
      resolved by this package — update that spec's note to point here.

## Non-goals

- **Not the CPU sampler** — post-#498 CPU is canonical; this package changes
  the GPU side (or the closure graph) to match it.
- **Not pkg124's VNDF swap** — if pkg124 lands first, re-anchor and keep its
  gates green; do not fold the VNDF change in here.
- **Not the dielectric lobe** (pkg138).
- **Not a general GPU MIS audit** — only the metal near-delta defect and
  whichever single mechanism the instrumentation convicts.

## Provenance

Filed from the **2026-07-20 overnight hardware-verifier measurement**: GPU/CPU
2.70× at roughness 0.0 on pre-#498 main (GPU 0.02387 / CPU 0.00884), GPU
byte-identical pre/post #498, 4.0× vs the post-#498 canonical CPU; xfail
evidence in `tests/test_pkg123_disney_metal_gpu_cpu_parity.py` on
`origin/pkg123-disney-chi2`. S1 was first flagged by the #498 Opus review
(recorded in pkg138 Notes, now owned here). Clamp-parity pre-check
(`0.0064` floor identical both sides) done by the architect 2026-07-20.

## Progress

- [ ] Instrument: which GPU path shades the test scene (S2 check) + per-event
      `(f, pdf)` CPU-vs-GPU dump (S1 check).
- [ ] Fix the convicted mechanism with citations.
- [ ] Un-xfail near-delta parity rows; both-legs + furnace + wavefront-diff
      green on RTX.

## Lessons

*(Fill in after the package is done.)*
