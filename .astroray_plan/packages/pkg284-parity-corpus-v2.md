# pkg284 — Cycles-parity corpus v2 (replaces the nine-scene corpus)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h): 1 scenes + manifests, 1 gates + references, 1 harness/bench/test wiring
**Depends on:** pkg259, pkg278

---

## Goal

Before: the pkg259 nine-scene corpus (`materials_hall`, `textures_mapping`,
`lighting_studio`, `world_sky_{hdri,sky}`, `geometry_zoo`, `camera_lens{,_ortho}`,
`render_settings`, `volumes_smoke`) predates the light-tree/MIS, dedicated-lamp,
media, dispersion, sky and thin-film fixes of 2026-09; its references were
rendered on that broken engine and its gates are SSIM/pHash-heavy, which
independent MC noise cannot meet. After: a small corpus of eight Cycles-parity
scenes (one per transport feature that now matters), each with a fixed seed,
adaptive sampling off, per-ROI per-channel mean-ratio gates whose tolerance is
derived from measured MC variance, a Cycles reference rendered headless from the
same `.blend`, and a written re-bless rule: any correctness fix that moves a
gate re-pins the reference in the same PR, never the other way round.

---

## Context

Owner 2026-09-25: the nine-scene corpus "served its purpose way back" and may
be scrapped and redone freely; no ratification. Owner 2026-09-26: tests
calibrated on a broken engine must be corrected, never kept. The showcase
scenes (PR #911) already render both engines from one `.blend` and carry
per-region ratios; fold them in. This package is the gate (b)/(c) population
and the regression net for Batches AD–AF (lamp-hit continuation, photon power,
clamp metric, GPU/CPU divergence). Without it every correctness lane re-invents
a fixture and the next re-bless is again "visually identical, gate red".

---

## Evidence

- 2026-09-22: bank on 604b03f0 — cornell-mini SSIM 0.38, gr-kerr SSIM 0.9345 < 0.96 "visually identical to reference"; SSIM is the wrong gate for independent RNG (memory `ssim-wrong-gate-for-independent-rng`).
- 2026-09-08 (#763): materials_hall Astroray CPU 128 spp far noisier than Cycles; the corpus never caught the light-tree bias (#851) or the sun starvation (#859) because its gates were image-level.
- 2026-09-26 (PR #911): showcase per-ROI ratios — sky disc 1.00, metals 0.96–1.00, volumes shaft 0.97–0.99, glass sphere 1.00/0.96/1.00; fire 0.68/0.56/0.42 caught #908 in one number.
- 2026-09-25 (#884): five-seed per-channel ratios 0.921/0.915/0.908 vs 0.991/0.990/0.994 clamp-off — the per-ROI ratio form isolates one mechanism per gate.

---

## Reference

- `benchmarks/reference_corpus/build_corpus.py`, `scenes/manifest.json` schema (`crops`, `gate_c`, `feature_tags`) — keep the schema, replace the scenes.
- `benchmarks/blender_parity/render_leg.py::_configure_render` (seed 278, adaptive off, denoise off) and `harness.py` (`per_channel_ratio`, `compute_channel_mean_ratio` per ROI) — the metric stack; §5b: extend, do not fork.
- `benchmarks/blender_showcase/showcase.py` (glass, volumes, sky, metals builders).
- Blender `tests/python/cycles_render_tests.py` (idiff fail 0.016 / failpercent 1 on tiny fixed-seed scenes): one feature per small scene, per-engine reference — the layout to borrow.
- pbrt-v4 `src/pbrt/cmd/imgtool.cpp` `diff` (`--metric ME/MRSE`) — mean-ratio over regions as the MC-robust metric.
- Memory: `readme-showcase-render-feedback` (composition), `fix-tests-calibrated-on-broken-engine`, `corpus-scenes-replaceable`, `seed-zero-is-random-sentinel`, `gamma-vs-linear-comparison-artifact`.
- `.astroray_plan/docs/reference-corpus-design-2026-09.md` (v1 design; superseded by this package's `reference-corpus-v2-design.md`).

---

## Prerequisites

- [ ] Batch AD (pkg288 lamp-hit continuation, pkg290 clamp) and Batch AE (pkg286/287 photons) merged, or the affected scenes' references are marked `provisional` in the manifest until they land.
- [ ] Blender 5.2 headless with the staged CUDA addon (`dist/astroray`) and Cycles OptiX/CPU.
- [ ] GPU lock free for the reference render session (each scene ≤ 60 s per engine at reference spp).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/scenes/v2_light_tree.blend` | Interior with 6 mesh emitters of unequal power + 1 point + 1 area(spread 45°) + 1 sun: light tree/MIS, dedicated lamps, #886 closed emitter (an emissive sphere). ROIs: floor under each light class, back wall, emitter faces. |
| `benchmarks/reference_corpus/scenes/v2_media.blend` | Fog box + smoke VDB + fire (Principled Volume blackbody) + two mesh emitters inside the medium + one lamp behind it: #912/#913/#884 territory. ROIs: shaft, smoke, fire core, fog floor. |
| `benchmarks/reference_corpus/scenes/v2_dispersion_caustics.blend` | Showcase glass (SF11 prism + Sellmeier sphere) under a sun AND a spot (pkg287): caustic ROIs on the floor, refracted beam, sphere limb, background firefly ROI. |
| `benchmarks/reference_corpus/scenes/v2_sky_sun.blend` | Showcase sky (Nishita, 4° sun) with a chrome ball and a diffuse ground: disc, glow, zenith, ground, reflection ROIs. |
| `benchmarks/reference_corpus/scenes/v2_thin_film_metals.blend` | Showcase metals: gold/copper/titanium films at three thicknesses, rough-glass thin film (#783). ROIs per sphere (channels < 0.01 excluded). |
| `benchmarks/reference_corpus/scenes/v2_textures_opvm.blend` | Print table: image + Noise/Voronoi/Wave/Checker (#881, #890), Mapping before AND after a non-affine warp (#891), Metallic/Roughness programs incl. inside Mix Shader (#889). ROIs per proof card. |
| `benchmarks/reference_corpus/scenes/v2_camera_geometry.blend` | Ortho + perspective clip markers (#873), instancing, hair tuft (#853), motion-blur vane, mesh volume (#833). ROIs per specimen. |
| `benchmarks/reference_corpus/scenes/v2_viewport.blend` | `metal_sweep` + a 100k-triangle grid in one file, two named cameras; the pkg291 gate (a) driver loads it. No render gate; manifest only. |
| `benchmarks/reference_corpus/gates_v2.toml` | Per scene: `seed`, `spp_gate`, `spp_reference`, ROI list, per-channel tolerance, `provisional` flag, `blessed_on` (commit + PR). |
| `benchmarks/reference_corpus/refs_v2/<scene>_{cycles,astroray_cpu,astroray_gpu}.exr` | Linear references (EXR, not PNG; `git add -f`, memory `evidence-png-gitignore-trap`). |
| `benchmarks/reference_corpus/mc_tolerance.py` | Renders a scene with N seeds at `spp_gate`, writes per-ROI per-channel σ/mean; tolerance = max(0.02, 3·σ_rel·√2) written into `gates_v2.toml`. |
| `tests/test_corpus_v2_parity.py` | One parametrised test per (scene, backend): render at `spp_gate`, compare per-ROI channel means to the Cycles reference within tolerance; `provisional` rows xfail(strict). Marked `gpu` for the GPU leg. |
| `.astroray_plan/docs/reference-corpus-v2-design.md` | Per-scene concept, ROI map (annotated PNG), what each ROI is meant to catch, which v1 scene it retires, asset licences. |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/reference_corpus/build_corpus.py` | Add the v2 builders (import the showcase builders from `blender_showcase/showcase.py`; do not copy them); `--family v2_*`. |
| `benchmarks/reference_corpus/scenes/manifest.json` | v2 entries with `crops`/`feature_tags`; v1 entries get `"retired_by": "pkg284"` (files deleted once gate (c) trio is remapped, see decisions). |
| `benchmarks/reference_corpus/README.md` | v2 charter, re-bless rule, `mc_tolerance.py` usage. |
| `benchmarks/blender_parity/scene_library.py` | `REFERENCE_SCENES` = v2 set. |
| `scripts/benchmarks/weekly_local_bench.ps1` | Iterates v2 families. |
| `tests/test_reference_corpus_manifest.py` | Accepts retired entries; coverage check runs over v2 + retained v1 rows. |
| `scripts/README.md` | Register `mc_tolerance.py`. |

### Key design decisions

- **Gate form is fixed: per-ROI, per-channel linear mean ratio Astroray/Cycles, fixed seed, adaptive off, denoise off.** No SSIM, no pHash on this corpus (those stay in the bank for Astroray-only scenes). Ratio bands come from `mc_tolerance.py`, never hand-typed; floor 2 % covers Cycles' own seed noise. Channels whose Cycles mean < 0.01 are excluded (showcase convention).
- **Three legs per scene:** Cycles CPU (reference), Astroray CPU, Astroray GPU. A GPU/CPU gate (±5 %, pkg271 convention) is derived from the same renders; it is what catches #876/#912-class bugs.
- **Re-bless rule (owner 2026-09-26):** a PR that moves a gate must either (a) show the gate encoded the old bug and re-pin `blessed_on` in the same PR with the reason in the commit, or (b) fix the engine. Never revert a fix or widen a band to keep green. Cycles references are re-rendered only when Blender is upgraded (record version in `gates_v2.toml`).
- **`provisional` rows** exist so scenes can land before their fix (e.g. fire before #908 landed): strict xfail, flipped in the fixing PR (memory `xfail-gated-features-must-unxfail`).
- **Gate (c) trio:** the owner chose gallery/workshop/terrace-with-hair from v1. Proposed remap: `v2_light_tree` / `v2_textures_opvm` / `v2_camera_geometry` (hair). This is an owner decision; until confirmed, v1 `materials_hall`, `textures_mapping` and `hdri_exterior_hair` stay on disk and `gate_c` keeps pointing at them.
- **Spp:** `spp_gate` 64 (test, ≤ 10 s CPU per scene at 320×180), `spp_reference` 1024 for Cycles. Resolution per scene in the manifest; the ROI map is in normalised coordinates so resolution can change without re-blessing.
- **Coverage report** (`coverage_report.py`) keeps working: v2 feature tags are a subset of the matrix; uncovered SUPPORTED rows are listed, not failed, until pkg278 decides gate (b)'s population.

---

## Acceptance criteria

- [ ] Eight v2 `.blend` files build deterministically from `build_corpus.py`, reopen with matching sha256, and `manifest.json` carries ROIs + feature tags for each.
- [ ] `gates_v2.toml` tolerances are produced by `mc_tolerance.py` (5 seeds) and committed with the σ table; no band below 2 % or above 15 % without a written reason.
- [ ] `tests/test_corpus_v2_parity.py`: every non-provisional (scene, backend) row passes on the merge build; provisional rows are strict xfails tied to an issue number.
- [ ] GPU/CPU ±5 % rows pass on the RTX 5070 Ti for every scene except those xfailed with an issue.
- [ ] Design doc has the annotated ROI map per scene and the lead's visual sign-off render for each (Astroray vs Cycles side by side).
- [ ] `weekly_local_bench.ps1` and `scene_library.py` run on v2; `python scripts/project_index.py lint` clean.

---

## Non-goals

- Do not fix engine defects the corpus exposes; file issues and mark rows provisional.
- No new metric implementations; reuse `harness.py`/`reference_bank.metrics`.
- No Pillar 4 scenes (GR/ADAF stay in the reference bank, pkg285).
- No animation; single frames.
- Do not delete v1 scenes until the gate (c) remap is owner-confirmed.

---

## Progress

- [ ] Phase 1: builders + manifests + design doc (Blender-side, no engine).
- [ ] Phase 2: `mc_tolerance.py`, references, `gates_v2.toml`, test.
- [ ] Phase 3: harness/bench wiring, v1 retirement entries, README.

---

## Lessons

*(Fill in after the package is done.)*
