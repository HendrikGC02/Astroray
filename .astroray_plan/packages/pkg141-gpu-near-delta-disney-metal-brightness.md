# pkg141 — GPU near-delta Disney-metal over-brightness (GPU/CPU 2.7–4.0× at roughness→0; adjudicate pdf-convention asymmetry vs closure-graph twin)

**Pillar:** 3 (GPU/CPU parity / MIS-pdf consistency)
**Track:** A (GPU lane; RTX-gated — CI is blind to it)
**Codex-paste-ready:** no (diagnostic-first: two candidate mechanisms must be distinguished by instrumentation before the fix is chosen; the fix then needs parity + wavefront-diff re-validation)
**Status:** implemented, PR #518 — **✅ ADJUDICATED MERGEABLE 2026-07-25 (architect): merge on the PR's own green gates, conditional on the checklist in the ADJUDICATION block at the end of this spec.** The HW verdict is formally FAIL bound to `f1fd7b8` (verifier hard rule: never relax a gate), but every failing gate reproduces bit-deterministically on unmodified main @ `8c49bbb` and contains no Disney metal — ownership of those failures transfers to **pkg153**; residual GPU dimness (0.60–0.77 near-delta) → follow-up **pkg152**. The four promotion-ready xfail rows are removed IN THIS PR (memory `xfail-gated-features-must-unxfail`). **Merge-conflict note for the pr-merger:** this spec file is edited on BOTH main (this Status + the two appended sections below) and the PR branch (gates/Progress/Lessons) — resolve by taking main's Status line and UNION-ing the appended sections with the PR's sections; state the resolution in the merge commit per CLAUDE.md.
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

## Hardware verification 2026-07-25 (verifier notes, folded in from the `Astroray-pkg141` worktree by the architect — the freeze rule kept them uncommitted there)

**Hardware:** RTX 5070 Ti, CUDA 12.8, OptiX 9.1.0. **Bound SHA:** `f1fd7b89447fdb8dce992fdbe81ee2c014470654`. Fresh worktree build via `configure_and_build.bat` (Release); `astroray.__file__` resolved to the worktree's own `build_cuda/Release` `.pyd`.

| Gate | Result |
|---|---|
| `tests/test_pkg123_disney_metal_gpu_cpu_parity.py -v --runxfail` | **7 passed** (all 4 formerly-xfail near-delta rows pass for real) |
| `tests/test_disney_rough_glass_furnace.py` | **5 passed** |
| `tests/test_disney_energy_conservation.py` | **271 passed** |
| `tests/wavefront_diff -q` | 4 failed / 22 passed / 1 xfailed — **all 4 reproduce near-identically on unmodified main @ `8c49bbb`** (env-scene mean-ratio R-channel ~12–15% over the 0.12 tol ×3; perf floor 0.90x vs required 1.30x); no Disney metal in any failing scene |
| `test_wavefront_photon_caustic_parity` (isolated) | 1 failed — exact known pre-existing main-branch flake signature (SSIM=-0.0000, peak WF=1.208 MW=1.591) |

Near-delta parity ratios (R/G/B), down from the pre-fix 2.7–4.0× over-brightness, all inside the [0.4, 2.5] band: roughness 0.00/0.03/0.05 → 0.6034/0.6892/0.7565; 0.10 → 0.6215/0.7066/0.7675. No-regression rows: 0.30 → 0.8583/0.9110/0.9358; 0.60 → 0.8570/0.9132/0.9422; 0.90 → 0.6392/0.7948/0.8857. Visuals: GPU sphere no longer a full-albedo mirror, highlight/Fresnel falloff matches CPU shape, no fireflies/NaN/banding; Disney contact sheet (roughness 0.4 — outside the affected band) unchanged within MC noise vs the `9ffccd4` before-image. **Verifier verdict: FAIL bound to `f1fd7b8`** per the never-relax-a-gate hard rule, with disposition of the pre-existing failures explicitly deferred to the architect.

## ✅ ADJUDICATION (2026-07-25, architect) — PR #518 MERGEABLE on its own green gates

**Decision 1 — merge.** The FAIL verdict is respected as recorded, but attribution is verified at the strongest available standard: the verifier re-ran every failing gate on unmodified main @ `8c49bbb` with a fresh `.pyd` and got near-identical, bit-deterministic numbers, and none of the failing scenes contain Disney metal. The PR's own contract — near-delta parity (THE gate), furnace, energy, visuals — is unanimously green. Holding #518 hostage to a pre-existing main-branch defect would invert attribution (pkg138/#517 partial-scope precedent). **Merge is conditional on:** (a) the xfail-removal commit below; (b) CI green on the final head; (c) pkg153 existing on main as the formal owner of the wavefront_diff/perf failures (done, this commit).

**Decision 2 — the 4 xfail rows are removed IN THIS PR** (hard rule, memory `xfail-gated-features-must-unxfail`; the spec's own un-xfail gate says the same). Small implementer commit. **HW carry-over:** the verifier's evidence was gathered with `--runxfail`, which is behaviorally identical to marker removal, so the `f1fd7b8`-bound measurements carry to the new head **provided** the pr-merger verifies by diff that the `f1fd7b8`→head delta is strictly (i) the four xfail markers in `tests/test_pkg123_disney_metal_gpu_cpu_parity.py` and (ii) doc-only files. Any other delta → full HW re-verify before merge. (The freeze rule is not violated: the HW run is complete and its verdict returned; this is the test-marker analog of the doc-only-delta carry-over check.)

**Decision 3 — residual dimness: accepted for pkg141 closure, NOT accepted as the final parity state.** 0.60–0.77 near-delta (and 0.64 R at roughness 0.9) is inside the deliberately wide [0.4, 2.5] band, so this package closes on its own contract; but the GPU now sits a stable, deterministic 1.3–1.7× DIM vs the canonical CPU — the opposite sign of the original defect and exactly the stable-per-channel-ratio signature that memory `mc-noise-vs-deterministic` classifies as structural. Follow-up spec **pkg152** filed (measure-first; the implementer's own Lessons hypothesis — CPU-side energy fixes of the pkg60/118/138/145 series never mirrored into the `gpu_materials.h` twin — is its leading candidate). Not dispatched tonight.

**Decision 4 — wavefront_diff ownership.** The 4 wavefront_diff failures + the perf-floor miss + the photon-caustic flake are formally logged as a pre-existing main-branch defect owned by **pkg153** (filed this commit), fed by the already-dispatched gate-failure-reviewer. **Interim protocol for every remaining HW verdict this run:** re-run failing gates on unmodified main @ a pinned SHA; PR-attributable failures block; main-attributable failures log to pkg153 with the repro numbers — do not re-adjudicate from scratch per PR.
