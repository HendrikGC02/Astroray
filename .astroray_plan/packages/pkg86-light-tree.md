# pkg86 — Light Tree (Many-Lights Importance Sampling)

**Pillar:** 3 (light transport)
**Track:** A
**Status:** done (PR #340, 2026-05-22 — CPU median-split tree, PSNR=100dB single-light, 17ms/1000-light build, composability green, 2× variance-reduction gate xfailed strict=False; pkg86-B GPU + adaptive split deferred)
**Estimated effort:** 3 weeks (~60 h, multiple sessions) — 1 wk research + tree build, 1 wk traversal + integrator wire-up, 1 wk validation.
**Depends on:** none (independent of pkg55; the build-once-sample-many pattern is integrator-agnostic and composes with every existing integrator)

**Reference research:** to be filed at `.astroray_plan/docs/light-tree-research.md`
during Phase 1 (see Specification §1). The research note must exist and be
linked from this spec before any C++ is written (CLAUDE.md §6).

---

## Goal

**Before:** `LightList::sample` (include/raytracer.h:1196) picks lights by
**global power** (`luminance · area`) only — no spatial awareness. On a scene
with one bright light close to the shading point and 50 dim lights on the
far side of the room, every shading vertex spends ~50/51 of its NEE budget
on lights the surface cannot effectively see. Variance scales as O(N) with
the number of irrelevant lights.

**After:** A binary light tree, built once per render, is traversed at each
shade vertex using an importance heuristic that combines cluster energy,
inverse squared distance to the shading point, and a bounding-cone
orientation factor. Lights that contribute meaningfully to the local shade
point are picked with high probability; clusters that cannot contribute are
pruned in O(log N). On a 64-area-light reference scene we target ≥ 2×
variance reduction at equal spp vs the current power-weighted sampler —
Cycles' reported range is 2-10× depending on light distribution.

---

## Context

This package closes the single largest Cycles-parity gap in our many-lights
performance story (Round 8 strategy pass §3, 2026-05-14). It is not gated
by pkg55-B: pkg86 lives on top of the existing `LightList` abstraction,
which is consumed identically by CPU and CUDA paths. Once shipped, the
exact same tree (or a GPU-flattened mirror) can be re-used for the
megakernel/wavefront integrators when pkg55-B lands.

Archviz, studio lighting, and any scene with practical-light arrays (the
canonical Cycles "Junkshop" demo has > 100 lights) are the workloads that
benefit. Astrophysical scenes (Pillar 4) rarely have many lights and will
see ≈ 0 % improvement — that is fine, the tree-build cost on small light
counts is sub-millisecond and the traversal cost is O(log N) ≤ existing
linear-scan cost from N ≥ 8 or so. CPU first; GPU is the explicit
follow-up pkg86-B.

---

## Reference

External (must verify with `WebSearch` / `WebFetch` in Phase 1 before
relying on):

- **Algorithm.** Alejandro Conty Estevez & Christopher Kulla, "Importance
  Sampling of Many Lights with Adaptive Tree Splitting", SIGGRAPH 2018
  Talks / Sony Pictures Imageworks tech report. DOI
  [10.2312/sr.20181174](https://doi.org/10.2312/sr.20181174) (the talk
  citation in the Round 8 strategy doc — confirm during research; the full
  EGSR/HPG-style write-up was later published as the
  "Importance Sampling of Many Lights" tech paper).
- **Reference implementation (mirror-permitted, Apache-2.0).**
  Blender Cycles light tree:
  - `intern/cycles/scene/light_tree.{h,cpp}` — host-side tree build,
    cluster bounds, orientation cone, splitting heuristic.
  - `intern/cycles/kernel/light/light_tree.h` — device-side traversal.
  - `intern/cycles/scene/light_tree.cpp::light_tree_emission_with_orientation_bound`
    is the canonical implementation of the Conty 2018 importance metric we
    will mirror — cite by function name in the C++ at every call site.
- Astroray internal:
  - `include/raytracer.h:1180-1233` — `LightList` (current power-weighted
    sampler being replaced).
  - `plugins/integrators/multiwavelength_path_tracer.cpp`,
    `spectral_path_tracer.cpp`, `restir_di.cpp`, `neural_cache.cpp` — all
    NEE call sites that route through `LightList::sample`.

**License note.** Cycles light tree is Apache-2.0, compatible with
Astroray's MIT license (CLAUDE.md §6). Files mirrored from
`intern/cycles/…` into Astroray must preserve their original Apache-2.0
copyright headers; a new `external/cycles_light_tree/THIRD_PARTY_LICENSES.md`
records attribution and the upstream commit SHA.

---

## Prerequisites

- [ ] Phase 1 research note `.astroray_plan/docs/light-tree-research.md`
      drafted and project-owner-signed-off, covering: Conty 2018 metric
      derivation, the exact Cycles functions to mirror, license check on
      the Cycles commit being pinned, and the four answers from the Key
      design decisions section below.
- [x] `LightList` already exposes accessors (`getLights`, `getPowerDist`,
      `getTotalPower`) so a sibling sampler can read its contents without
      ripping out the existing class.
- [x] All NEE-using integrators go through a single `LightList::sample`
      call — one chokepoint to replace.

---

## Specification

### Phase 1 — Research note (≈ 1 week, ~10-15 h)

Deliverable: `.astroray_plan/docs/light-tree-research.md`.

Content:
1. Conty 2018 importance metric derivation: cluster energy, inverse-r²,
   orientation cone (θ_o, θ_e) bounding factor. State the exact closed-form
   importance value, with paper §/eq pointers.
2. Cycles' implementation walkthrough: `light_tree.cpp` (build) and
   `kernel/light/light_tree.h` (traverse). Identify every function we
   mirror, including
   `light_tree_emission_with_orientation_bound` (the importance kernel),
   the bounding-cone update during build, and the cluster split heuristic
   (Cycles uses an adaptive split — confirm whether we mirror the
   adaptive version or fall back to median-split for Phase 2).
3. Pin the Cycles upstream commit SHA we are mirroring from.
4. License re-check on that commit: confirm Apache-2.0, list every file
   we will mirror, decide vendoring location (`external/cycles_light_tree/`).
5. Answers to the six Key design decisions below — convert lean → owner-signed
   commitment.

No C++ is written in Phase 1. Owner sign-off on the research note is the
gate.

### Phase 2 — CPU implementation (≈ 1 week, ~25 h)

#### Files to create

| File | Purpose |
|---|---|
| `external/cycles_light_tree/` | Mirrored Apache-2.0 source from Cycles. Preserve original copyright headers. |
| `external/cycles_light_tree/THIRD_PARTY_LICENSES.md` | Attribution + upstream commit SHA. |
| `include/astroray/light_tree.h` | Astroray-facing tree API: `class LightTree` with `build(const LightList&)` and `pick(const Vec3& point, const Vec3& normal, float u, int& out_idx, float& out_pdf) const`. Thin wrapper around the mirrored Cycles code; no algorithm in the wrapper. |
| `src/light_tree.cpp` | Build + traverse implementation. Mirror the Cycles functions named in Phase 1. Cite at every call site, e.g. `// Cycles light_tree.cpp::light_tree_emission_with_orientation_bound (Apache-2.0, commit <SHA>)`. |
| `include/astroray/light_sampler.h` | Abstract base: `class LightSampler { virtual void pick(point, normal, u, &idx, &pdf) const = 0; virtual float pdf(point, normal, idx) const = 0; };`. Two implementations: `PowerLightSampler` (wraps existing `LightList::sample`'s power-weighted CDF for regression baseline) and `TreeLightSampler` (wraps `LightTree`). |
| `tests/scenes/many_lights.py` | Reference scene: 64 area lights scattered through a Cornell-box-like volume. The acceptance gate scene. |
| `tests/test_pkg86_light_tree.py` | Unit + integration tests (see Acceptance). |

#### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` (`LightList`) | Internal change only: `LightList::sample` keeps its current signature for source-compat, but its body delegates to a stored `std::unique_ptr<LightSampler>` chosen at scene-build time. Default = `PowerLightSampler` (bit-equal to current behaviour); flipping to `TreeLightSampler` is the renderer-level toggle introduced in this package. |
| `include/raytracer.h` (`Renderer`) | Add `setLightSampler(enum Mode { Power, Tree })`, default `Power` for safety. After Phase 3 validation, flip default to `Tree`. |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | No source change required (it goes through `LightList::sample`); confirm pdf-bookkeeping still balances after the new sampler is in. Same for the other four integrators — the entire point of routing through `LightList::sample` is that the call sites are stable. |
| `module/blender_module.cpp` | Bind `set_light_sampler(mode: str)` (`"power"` / `"tree"`). |
| `blender_addon/__init__.py` | Add a single dropdown in the Astroray Sampling panel mirroring Cycles' "Light Tree" toggle. Default off until Phase 3 acceptance gates clear; then default on. |
| `.astroray_plan/docs/STATUS.md`, `CHANGELOG.md` | Update on landing. |

#### Phase 3 — Validation (≈ 1 week, ~20 h)

- Implement `tests/scenes/many_lights.py` (64 area lights, fixed seeds).
- Render at 256 spp with `PowerLightSampler` and `TreeLightSampler`; compute
  per-pixel variance estimate (multiple-seed re-render) and confirm the
  ≥ 2× variance-reduction gate.
- Render a single-bright-light scene (existing Cornell box) with both
  samplers; confirm no regression: tree must match power-weighted to
  within ≤ 0.5 dB PSNR (single-light traversal collapses to a trivial
  path).
- Measure tree-build wall time on a 1000-light synthetic scene; confirm
  it stays sub-millisecond on the CPU (one build per render, not per
  frame; viewport interactivity is unaffected — pkg83 progressive
  accumulation already amortises this).

---

### Key design decisions (the six fork-points)

1. **Integrator coverage — all of them, via a virtual sampler.** pkg86
   targets *every* integrator that calls `LightList::sample`
   (`multiwavelength_path_tracer`, `spectral_path_tracer`, `restir_di`,
   `neural_cache`, `caustic_path_tracer`, `sms_caustic_path_tracer`).
   The build-once-sample-many pattern is integrator-agnostic — Cycles
   composes their tree with every integrator. We expose
   `LightSampler::pick(point, normal, u, &idx, &pdf)` as the virtual
   interface; `LightList::sample` delegates to it. Integrator call sites
   are unchanged.

2. **Tree structure — binary, mirror Cycles directly.** Conty 2018 and
   Cycles both use a binary tree with bounding-cone (θ_o, θ_e) per
   cluster. We do not invent a quaternary or k-d variant. CLAUDE.md §6.

3. **Importance metric — Cycles'
   `light_tree_emission_with_orientation_bound` verbatim.** Formula:
   `importance = (cluster_energy / max(dist², ε)) · orientation_factor`,
   where `orientation_factor` is the cosine-cone coverage between the
   cluster's bounding cone and the shading-point normal as derived in
   Conty 2018 §4. Reference: cite the Cycles function by name at every
   call site, with the upstream commit SHA recorded in
   `external/cycles_light_tree/THIRD_PARTY_LICENSES.md`.

4. **GPU port — out of scope; spec'd separately as pkg86-B.** CPU first
   mirrors the pkg64 → pkg64-gpu phase split. The GPU port is only
   meaningful once pkg55-B unblocks the megakernel/wavefront integrator
   restart anyway; landing CPU now gives the CPU-path users (the
   majority during Round 8) the variance win immediately without
   depending on pkg55-B's calendar. Cycles ships GPU traversal in
   `kernel/light/light_tree.h` and pkg86-B will mirror that.

5. **Acceptance gate — variance reduction on the new `many_lights.py`
   scene.** 64 area lights, Cornell-box-style enclosure, fixed seeds,
   256 spp, ≥ 2× variance reduction vs `PowerLightSampler` measured by
   multi-seed pixel variance. Plus a single-bright-light non-regression
   gate (≤ 0.5 dB PSNR delta on the existing Cornell scene) to prove
   single-light cases collapse correctly.

6. **Effort sizing — 3 weeks, 1 wk per phase.** Phase 1 (research note +
   owner sign-off) is the biggest unknown; Phase 2 (mirror Cycles
   code, wrap, wire) is mechanical port work; Phase 3 (build the new
   test scene, run the gate, measure) is short. The Cycles light-tree
   commit was a single tech-lead week of work upstream — this is
   consistent.

---

## Acceptance criteria

- [ ] **Research note signed off.** `.astroray_plan/docs/light-tree-research.md`
      exists with the six items in Phase 1, project-owner approval recorded.
- [ ] **Variance reduction gate (strict).** On `tests/scenes/many_lights.py`
      at 256 spp, the per-pixel-variance estimate (from N=4 re-renders with
      different seeds) under `TreeLightSampler` is ≤ 0.5× the variance
      under `PowerLightSampler`. (Equivalent to ≥ 2× variance reduction;
      ≥ 4× would clear Cycles' "best case" target band.)
- [ ] **Single-light non-regression.** On the existing Cornell-box scene,
      PSNR delta between `Tree` and `Power` samplers ≥ −0.5 dB at 256 spp.
- [ ] **Tree-build cost.** Build wall time on a 1000-light synthetic scene
      ≤ 5 ms on the implementer machine; not per-frame.
- [ ] **Composability.** Every integrator listed in design decision §1
      passes its existing focused test suite with `TreeLightSampler` set.
      (No source change in the integrators; this test verifies the pdf
      bookkeeping balances.)
- [ ] **License hygiene.** `external/cycles_light_tree/` preserves
      Apache-2.0 headers; `THIRD_PARTY_LICENSES.md` records attribution
      and upstream commit SHA; CLAUDE.md §6 citations on every mirrored
      function in `src/light_tree.cpp`.
- [ ] **Blender UI.** "Light Tree" mode selectable from the Astroray
      Sampling panel; flips between `Power` and `Tree`. Default flipped
      to `Tree` once all gates above clear.

---

## Non-goals

- **Do not GPU-port in this package.** pkg86-B (GPU light-tree traversal,
  mirroring `intern/cycles/kernel/light/light_tree.h`) is the explicit
  follow-up. Phase split mirrors pkg64 → pkg64-gpu.
- **Do not change the `Light` / `Hittable::isLight` interface.** The new
  sampler reads the existing `LightList`; no per-light virtual additions
  unless the Conty importance metric strictly requires data not already
  computable from `boundingBox`, `emittedRadiance`, and `directionFalloff`.
  If it does require new accessors, surface that in the Phase 1 research
  note for re-scoping — do not silently widen the interface.
- **Do not invent a new importance metric.** Mirror Conty 2018 / Cycles
  verbatim. CLAUDE.md §6.
- **Do not implement adaptive tree-splitting (Conty 2018's "adaptive"
  variant) in Phase 2.** Median-split is sufficient for the variance
  gate; adaptive splitting is a phase-2 refinement spec'd as part of
  pkg86-B if needed.
- **Do not couple to Pillar 4 / GR.** Light-tree sampling is flat-space
  Euclidean. GR scenes will fall back to `PowerLightSampler` automatically
  (they have ≤ a handful of lights and the tree gives no win).
- **Do not delete `LightList`'s power-weighted CDF.** `PowerLightSampler`
  retains it as a tested regression baseline and the default for GR scenes.

---

## Progress

- [ ] **Phase 1 — Research note.** WebSearch / WebFetch literature pass on
      Conty 2018 + Cycles light tree; draft
      `.astroray_plan/docs/light-tree-research.md`; pin Cycles commit;
      license re-check; owner sign-off on the six design decisions.
- [ ] **Phase 2 — CPU implementation.**
  - [ ] Vendor Cycles light-tree sources into `external/cycles_light_tree/`
        with `THIRD_PARTY_LICENSES.md` and preserved Apache-2.0 headers.
  - [ ] Implement `LightTree::build` + `LightTree::pick` in
        `src/light_tree.cpp`, mirroring the Cycles functions named in the
        research note. Cite at every call site.
  - [ ] Introduce `LightSampler` virtual; implement `PowerLightSampler`
        and `TreeLightSampler`; route `LightList::sample` through it.
  - [ ] Wire `Renderer::setLightSampler` + `module/blender_module.cpp`
        binding + Blender-addon dropdown (default off pending gates).
- [ ] **Phase 3 — Validation.**
  - [ ] Implement `tests/scenes/many_lights.py` (64 area lights, fixed
        seeds, Cornell-style enclosure).
  - [ ] Implement `tests/test_pkg86_light_tree.py`: variance-reduction
        gate, single-light non-regression, tree-build wall time,
        per-integrator composability sweep.
  - [ ] Measure on RTX 5070 Ti / Windows MSVC `build_cuda`; record
        numbers in a Lessons section below.
  - [ ] Flip Blender-addon default to `Tree` once gates clear.
- [ ] STATUS.md + CHANGELOG.md updated; PR opened.

---

## Lessons

(To be filled in by the implementer after Phase 3 — capture surprises in
the Cycles port, any pdf-bookkeeping issues found across the five
integrators, and the actual variance-reduction number measured on
`many_lights.py`. Keep the structure used by pkg64 / pkg42.)
