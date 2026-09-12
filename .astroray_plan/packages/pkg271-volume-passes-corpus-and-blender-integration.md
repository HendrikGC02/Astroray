# pkg271 — Heterogeneous volume passes/AOVs + corpus `volumes` family + Blender integration

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h)
**Depends on:** pkg269, pkg270

---

## Goal

Before: heterogeneous volumes render on CPU and GPU with emission (pkg268–270)
but there are no Volume Direct/Indirect passes for grids, `volume_bounces` is
DROPPED-SILENT in the addon, there is no corpus coverage, and no headless test
proves a Blender Volume object renders end-to-end. After: heterogeneous in-scatter
is split into `PASS_VOLUME_DIRECT` / `PASS_VOLUME_INDIRECT` (extending pkg204's
world-volume split), `volume_bounces` is honoured from the native panel, the
degradation report describes any drops, a `volumes` family is added to the pkg259
reference corpus, and a Blender headless test renders an imported Volume object
F12 on CPU+GPU with no exception.

---

## Context

This closes the volumes track: it makes the feature Cycles-parity-complete
(passes + native settings), measurable (corpus + Cycles A/B), and provably usable
from Blender. It depends on both the GPU stage (pkg269) and emission (pkg270) so
the passes and corpus exercise the full closure. Gate (c) of the north-star exit
checklist (three reference scenes) benefits from a real volume corpus scene.
Research: `docs/volumes-track-research-2026-09-12.md` §1d, §5.

---

## Reference

- Design doc: `.astroray_plan/docs/volumes-track-research-2026-09-12.md` §5
- External: Cycles `film/passes` Volume Direct/Indirect (Apache-2.0).
- Pattern to imitate: pkg204 (world-volume direct/indirect split), pkg198
  (`HasLightPassAOVs` fleet-isolation axis, `PASS_VOLUME_*` slots); pkg259 corpus
  (`benchmarks/reference_corpus/scenes/manifest.json`, families `lighting_studio`
  / `materials_hall` / `textures_mapping` / `world_sky`).

---

## Prerequisites

- [ ] pkg269 and pkg270 are done and green (GPU hetero + emission exist).
- [ ] A licence-clean `.vdb` asset (CC0 smoke/fire, or an engine-generated
      synthetic grid) is available for the corpus scene.
- [ ] pkg259 corpus manifest schema reviewed (family/scene/rows).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/scenes/volumes_smoke.py` | Corpus `volumes` family scene: a scattering smoke + an emissive blackbody fire, CPU+GPU |
| `tests/test_pkg271_volume_passes.py` | Volume Direct+Indirect sum = combined volume beauty (rel_L1 ~0), CPU+GPU |
| `tests/test_pkg271_blender_volume_headless.py` | Blender headless: import a Volume object, render F12 CPU+GPU, no exception, non-vacuous output |

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/wavefront/stage_volume_hetero.cu` | Route hetero in-scatter to `PASS_VOLUME_DIRECT` vs `PASS_VOLUME_INDIRECT` by the pkg204 direct/indirect category test |
| `include/raytracer.h` | CPU: split heterogeneous in-scatter into the volume direct/indirect pass accumulators |
| `blender_addon/settings_map.py` | Flip `volume_bounces` from DROPPED-SILENT to SUPPORTED (it is now wired through transport) |
| `blender_addon/exporter.py` | Honour `volume_bounces` for grid media; emit a degradation-report row for any unsupported Volume socket |
| `benchmarks/reference_corpus/scenes/manifest.json` | Register the `volumes` family + `volumes_smoke` scene rows |

### Key design decisions

- **Pass split** reuses the exact pkg204 direct-vs-indirect category test: the
  in-scatter lit directly by a light (NEE leg at the scatter vertex) is
  `PASS_VOLUME_DIRECT`; via a further bounce, `PASS_VOLUME_INDIRECT`. On GPU it
  extends `stage_volume_hetero.cu` behind the existing `HasLightPassAOVs` axis —
  no new shade-kernel state (REG:254 gate unchanged).
- **`volume_bounces`** is only flipped to SUPPORTED once transport actually
  consumes it (it does after pkg268–270); the flip must be backed by an
  output-effect test (bounces=0 vs N changes the image), not a reachability claim.
- **Corpus:** a `volumes` family with one scattering smoke and one emissive fire,
  both rendering CPU+GPU, added to the pkg259 manifest with parity rows. The
  Cycles A/B is recorded as a **cross-check band** (spectral σ + Planck emission
  diverge from Cycles' RGB by design per pkg270).
- **Non-vacuity:** the headless test asserts density variation and (for the fire)
  emission are actually present, so a black frame cannot pass (north-star gate (c)
  discipline).

---

## Acceptance criteria

- [ ] `test_pkg271_volume_passes.py` passes: Volume Direct + Indirect sum to the
      combined volume beauty (rel_L1 ~0) on CPU and GPU.
- [ ] `test_pkg271_blender_volume_headless.py` passes: an imported Volume object
      renders F12 on CPU and GPU with no addon exception and non-vacuous output.
- [ ] `volume_bounces` reads SUPPORTED in the coverage matrix and an
      output-effect test shows bounces changes the image.
- [ ] The `volumes` corpus family is registered; manifest tests green; Cycles A/B
      recorded as a cross-check band; contact sheet inspected by Astra or Claude.
- [ ] Full CPU + GPU suites green; grid-free scenes unchanged; RTX sweep at closeout.

---

## Non-goals

- Do not add velocity/motion blur or multi-scatter — pkg272.
- Do not change scattering/absorption/emission physics — pkg268–270 own those.
- Do not make the Cycles A/B the acceptance gate for the spectral divergences.
- Do not author the three north-star reference `.blend` assets here (that is the
  separate gate-(c) asset task).

---

## Progress

- [ ] CPU + GPU volume direct/indirect pass split for grids.
- [ ] `volume_bounces` honour + settings_map flip + output-effect test.
- [ ] `volumes_smoke` corpus scene + manifest rows.
- [ ] Blender headless import+render test.
- [ ] Pass all gates; Cycles A/B band; contact-sheet inspection; RTX sweep.

---

## Lessons

*(Fill in after the package is done.)*
</content>
