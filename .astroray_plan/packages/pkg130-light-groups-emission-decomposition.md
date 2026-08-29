# pkg130 — Light groups + emission-mechanism decomposition (LuxCore radiance-group model)

**Pillar:** 5 (production polish / AOV output — journal-figure production)
**Track:** A (per-group framebuffers + post-render rebalancing gate runs CPU-side; wavefront write-out verified on RTX)
**Codex-paste-ready:** no (new per-group framebuffer plumbing across CPU + wavefront + EXR write + addon UI; emitter-group tagging is a scene-convention decision)
**Status:** still-open — never implemented; no light-group/emission-decomposition code in the repo, only the spec-filing PR #492.
**Estimated effort:** M (~1 session per the research doc — emitter id plumbing + per-group buffers + EXR layers + addon UI)
**Depends on:** none hard. Composes cleanly after pkg55 Phase C (single spectral pipeline → per-group buffers land in one CPU + one GPU path, not four). The **emission-mechanism** alphabet defined here is the label source pkg134 (LPE) extends — file/land pkg130 first so pkg134 has the group ids to consume.

---

## Goal

**Before:** Astroray renders one combined radiance buffer. There is no way to
separate a frame's contributions by which emitter produced them, so publication
figures that need "disk thermal vs. jet synchrotron vs. lensed starfield vs.
envmap" as independent, re-balanceable layers cannot be produced without
re-rendering the scene once per emitter set.

**After:** Port LuxCoreRender's **radiance-group** model (Apache-2.0): every
emitter / emissive material carries a small group id; the integrator writes each
path's contribution into the framebuffer for its originating group; the film keeps
one radiance buffer per group (8 groups, matching LuxCore's GPU cap) and exports
them as separate EXR layers. Groups can be re-scaled / re-tinted **in post without
re-rendering**. The Astroray-unique deliverable is that the group axis is
**physical emission mechanism** — `disk_thermal`, `jet_synchrotron`, `starfield`,
`envmap` — which no other open engine labels; that is the journal-figure win.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §2
(LuxCore radiance groups, "tier 1"). Two-part change:

1. **Emitter group id.** Add a per-emitter / per-emissive-material `group_id`
   (uint8, 0–7). Mirror LuxCore's `.id` (materials `.emission.id`) semantics: the
   id selects which radiance buffer receives that emitter's contribution. Default
   all emitters to group 0 (a scene with no group tags renders bit-identically to
   today, into a single layer).
2. **Per-group framebuffers.** The film holds `N_groups` radiance accumulators of
   length `numPixels`. At the point where a path's emission is accumulated, index
   by the originating emitter's `group_id`. On the wavefront this is one extra SoA
   index at accumulation — the path already carries its light selection, so the
   group id rides alongside it into `stageAccumulateXYZKernel`
   (`src/gpu/wavefront/stage_advance.cu` accumulation). CPU mirrors in
   `pathTraceSpectral`. EXR write (`src/io/exr_writer.{h,cpp}`) gains one named
   layer per non-empty group.

**Emission-mechanism mapping (the Astroray-unique part).** Provide a scene-side
convention that tags the four canonical mechanisms to fixed group ids so figures
are reproducible across scenes: `disk_thermal`, `jet_synchrotron`, `starfield`,
`envmap`. This is a labeling convention over the generic group id, not new
machinery.

---

## Implementation plan

- **A. Emitter group id + scene plumbing.** Add `group_id` to the emitter /
  emissive-material representation and the exporter; addon UI exposes it (8-way
  enum with the four named mechanisms + generic groups). Default 0.
- **B. Per-group framebuffers (CPU + wavefront).** Allocate `N_groups` accumulators;
  route emission accumulation by `group_id`; sum-of-groups must equal the single
  combined buffer bit-for-bit when every emitter is in one group.
- **C. Multi-layer EXR export + post rebalancing.** Write one EXR layer per
  non-empty group; add a post-render per-group scale/tint pass. Gate: re-scaling a
  group in post equals re-rendering with that emitter scaled (within tolerance).

---

## Acceptance criteria

- [ ] Emitter/emissive-material `group_id` (0–7) plumbed CPU → exporter → wavefront
      → EXR; default-0 render is identical to today's single-buffer output.
- [ ] Per-group framebuffers on CPU and wavefront; **Σ groups == combined buffer**
      bit-identically for the single-group case, within noise for multi-group.
- [ ] Multi-layer EXR export (one named layer per active group).
- [ ] Post-render per-group rescale matches a re-render with the emitter scaled
      (tolerance gate).
- [ ] Emission-mechanism convention (`disk_thermal` / `jet_synchrotron` /
      `starfield` / `envmap`) documented and produces the 4-layer decomposition on
      a black-hole + envmap reference scene.
- [ ] CPU↔GPU wavefront-diff parity holds per group.

---

## Non-goals

- **Not full LPE.** Path-grammar routing (Heckbert `L(S|D)*E`) is pkg134; pkg130 is
  membership-based group ids only (LuxCore "tier 1"). pkg134 extends this group
  alphabet.
- **Not >8 groups.** 8 matches LuxCore's GPU cap and the four mechanisms + spares;
  no dynamic group count.
- **Not a denoiser/AOV rework.** Existing Cryptomatte (Pillar 5) and other AOVs are
  untouched.

---

## Algorithm sourcing (CLAUDE.md §6)

- **LuxCoreRender** `github.com/LuxCoreRender/LuxCore` — **Apache-2.0 (verified —
  `COPYING.txt`)**. Radiance groups: per-light `.id` / `.emission.id`, one film
  radiance buffer per group, 8 groups on GPU engines, per-group post rescale/tint
  and per-group pass export. Wiki: "LuxCoreRender Light Groups".
- **Cycles** `github.com/blender/cycles` — Apache-2.0 (verified). Limited
  membership-based `lightgroup` passes (no path grammar) — secondary reference.
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §2
  (tier 1) + adoption table rank 2.
- **Emission-mechanism decomposition** is Astroray-original (no external source);
  it is a labeling convention over the ported group-id machinery, not a new algorithm.

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §2, adoption rank 2:
"Light groups by emission mechanism … before journal-figure production"). Owner
goal: publication-quality figures that separate the black-hole emission mechanisms
into independently re-balanceable layers — a decomposition no other open renderer
offers.

---

## Progress

- [ ] A — emitter `group_id` + scene/exporter/addon plumbing.
- [ ] B — per-group framebuffers (CPU + wavefront); Σ-groups identity verified.
- [ ] C — multi-layer EXR + post rescale gate; 4-mechanism decomposition on a BH scene.

---

## Lessons

*(Fill in after the package is done.)*
