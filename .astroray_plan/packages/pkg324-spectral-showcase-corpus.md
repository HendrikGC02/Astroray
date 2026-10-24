# pkg324 — Spectral showcase corpus v1 (the scenes the competition sells, rendered and measured)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h); scene building + CPU legs in-lane, GPU legs via the lead
**Depends on:** none

---

## Goal

Before: Astroray's public gallery is Cornell boxes and a material zoo; the spectral features that
distinguish it (dispersion, thin film, blackbody, spectral caustics) have no demo scenes and no
qualitative evidence. After: nine small Cycles-node `.blend` scenes under
`benchmarks/showcase/spectral/`, a runner that renders each on CPU, GPU and Cycles at a pinned seed/spp
and writes PNG contact sheets, analytic checks where they exist, and a one-page gallery doc the
README can link.

---

## Context

Two "Spectra" engines surfaced in October 2026 (`docs/research/spectra-*-2026-10-25.md`); their
whole pitch is images of dispersion fire, thin-film rings and coloured caustics. Astroray has the
physics but not the pictures, and the owner's product themes (2026-09-29) include showing spectral
strength. The corpus also doubles as a qualitative regression net for the spectral paths that the
numeric gates cover only indirectly. Scene recipes are inferred from published renders; no
competitor assets are used.

---

## Reference

- Recipes: `docs/research/spectra-website-2026-10-25.md §4`, `docs/research/spectra-blenderartists-thread-2026-10-25.md §6`
- Existing tooling to reuse (CLAUDE.md 5b): `benchmarks/showcase/runner.py` (presets), `benchmarks/reference_corpus/report_tools.py` (npy→PNG, contact sheets), `benchmarks/blender_parity/render_leg.py`
- Thin-film analytic: Airy reflectance of a single dielectric layer (Belcour & Barla 2017 as the model Cycles uses)
- Prism deviation: Snell with Cauchy/Sellmeier n(λ) at the pinned wavelengths

---

## Prerequisites

- [ ] Build passes on main; `dist/astroray` stamped at HEAD.
- [ ] Blender 5.2 LTS available headless.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/showcase/spectral/scenes/*.blend` | nine scenes: thin-film ladder, prism fan, brilliant diamond, soap bubble + glass block, absorbing glass cube caustic, iridescent bunny, tumbler bounce-cap A/B, shader-ball node bench, Classroom (CC0 demo file, linked not copied) |
| `benchmarks/showcase/spectral/build_scenes.py` | builds the eight procedural scenes in headless Blender from code (deterministic; the only hand-made asset is the CC0 Classroom) |
| `benchmarks/showcase/spectral/manifest.json` | scene id, seed, spp, resolution, ROI rects, analytic check kind |
| `benchmarks/showcase/spectral/checks.py` | Airy thin-film hue vs thickness; prism fan angular spread vs n(λ); energy (white furnace) for the bubble shell |
| `tests/test_pkg324_showcase_corpus.py` | manifest/scene hash tests (fast) + analytic checks (slow, marks serial/gpu) |
| `docs/showcase/spectral-gallery.md` | the gallery page with the sheets and the numbers |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/showcase/runner.py` | a `--preset spectral` that renders the manifest's scenes on cpu/gpu/cycles and writes sheets via `report_tools` |
| `scripts/README.md` | register the runner preset and `build_scenes.py` |

### Key design decisions

- Cycles-node materials only (Principled thin film, Glass/Principled dispersion sockets, Blackbody): the point is that
  stock Blender scenes look better in Astroray, not that Astroray needs custom nodes.
- Every scene has a Cycles leg so the sheet is three-way (CPU / GPU / Cycles); where Cycles cannot do the effect
  (true dispersion caustics) the sheet says so instead of hiding the column.
- The tumbler bounce-cap scene renders at transmission depth 4/8/12 and 64 as the reference; it is the acceptance
  scene for pkg325 and ships here first.
- First-pass visual inspection runs through the `vision` delegate tier; its verdicts on position/size are confirmed
  with numpy before they enter the doc (memory `vision-model-hallucinates-pixel-shifts`).

---

## Acceptance criteria

- [ ] `pytest tests/test_pkg324_showcase_corpus.py` passes (fast part in CI; slow part under the GPU lock).
- [ ] Thin-film ladder: measured sphere hue vs Airy prediction within 10 deg of hue angle at the three thicknesses.
- [ ] Prism fan: red-to-blue angular spread within 5 % of the analytic Cauchy deviation.
- [ ] Nine three-way contact sheets exist with the manifest's seed/spp stamped; `docs/showcase/spectral-gallery.md`
      shows them with the numbers; lead visual sign-off recorded.
- [ ] No new script duplicates an existing generator (`scripts/README.md` updated).

---

## Non-goals

- Do not add engine features here (pkg325/pkg326 carry the Glass thin film and bounce-cap work).
- Do not copy competitor assets or images; recipes only.
- Do not publish to the README in this package (owner question 2 in `architect-plan-2026-10-25.md`).

---

## Progress

- [ ] Scenes built and hashed
- [ ] Runner preset + sheets
- [ ] Analytic checks green
- [ ] Gallery doc + lead sign-off

---

## Lessons

*(Fill in after the package is done.)*
