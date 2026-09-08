# pkg259 — Cycles feature-coverage reference scene corpus

**Pillar:** 5
**Track:** B
**Status:** in-progress — Phase 1 PR #761 open (materials_hall + textures_mapping builders, manifest, build_corpus.py CLI, tests, README, both-engine renders)
**Estimated effort:** 1 week (~20 h across sessions; Phase 0 one session, then one scene family per session)
**Depends on:** pkg229, pkg249, pkg253

---

## Goal

Before: parity, benchmark and addon-smoke work each pick their own tiny
scene (`metal_sweep`, three #729 corpus scenes, the pkg119b per-feature
single-sphere library, `benchmarks/showcase`), so coverage is accidental and
a Cycles feature that Astroray silently drops is only noticed when someone
happens to wire it. After: a standard, version-pinned corpus of
representative, deliberately attractive Blender scenes that together exercise
every Cycles feature Astroray is meant to support (materials, textures and
mapping, lights, world, geometry, camera, render settings, passes), each
scene carrying a manifest of the features it covers, with a generated
coverage-and-parity report that makes any Cycles/Astroray inconsistency
visible per feature. Benchmarks, parity gates, viewport measurements and
addon smoke tests all draw from this corpus instead of ad-hoc scenes.

---

## Context

Owner directive (2026-09-07 evening): constructing representative scenes
that cover "pretty much all features and materials and things that work in
Cycles that we would want to work in Astroray too" is too tedious to do by
hand and needs the rigour an agent can apply so no feature is overlooked;
the scenes should also be interesting and pretty, and their design may be a
creative brainstorm with GPT-6 Astra. This package is the Pillar-4 exit-gate
(c) instrument (three pinned scenes become the corpus) and the substrate for
gate (b)'s frequency-weighted coverage measurement. It serves Pillar 5.

---

## Evidence

- 2026-09-07: coverage matrix after the pkg253 scanner fix: SUPPORTED 114 /
  APPROXIMATED 50 / DROPPED-SILENT 363 of 527 enumerable features
  (`docs/blender_parity/coverage_matrix.json`).
- 2026-09-07: #729 corpus: `cornell_interior` (36 tri), `material_zoo`
  (8 450 tri), `hdri_exterior_hair` (1 922 tri + 2 400 strands); node ids
  per scene in `benchmarks/blender_parity/scenes/manifest.json`; only eight
  distinct shader node types across all three.
- 2026-09-07: pkg241 viewport measurements use `metal_sweep.blend` and a
  procedural 100k-triangle grid; the weekly bench uses `cornell` and
  `textured_plane`; none of these share a manifest or feature tags.

---

## Reference

- `benchmarks/blender_parity/README.md` (pkg119b harness),
  `scene_library.py::REFERENCE_SCENES`, `render_leg.py --export-blend /
  --load-blend / --report-only`, `manifest.json` schema (#729).
- `docs/blender_parity/coverage_matrix.json` and
  `scripts/generate_blender_parity_matrix.py` (pkg119 Phase A, pkg229
  re-audit) — the feature universe the corpus must cover.
- `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` §2
  gates (b) and (c).
- Cycles regression scene conventions: Blender's `tests/render/` layout
  (one feature per small scene, reference PNG per engine) — the structure to
  borrow, not the assets.
- `readme-showcase-render-feedback` memory (owner's composition rules:
  lift glass spheres, zoom, sample-heatmap AOV).

---

## Prerequisites

- [ ] pkg253 socket groups landed or at least enumerated, so the Principled
      scene knows which sockets are expected to render vs warn.
- [ ] Blender 5.2 reachable headless (`scripts/dev/launch_blender_mcp.ps1`
      for the GUI bridge; `blender -b` for exports); isolated profile per
      pkg236.
- [ ] Astra (gpt-6-astra) available through the Codex CLI for the Phase 0
      brainstorm, or the owner waives it.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/README.md` | Corpus charter: scene families, naming, manifest schema, how a new Cycles feature gets a home, how to regenerate references. |
| `benchmarks/reference_corpus/build_corpus.py` | Runs inside Blender: deterministic builders for every scene (procedural where possible, packed assets otherwise), writes `.blend` + manifest with feature tags, node ids, object/light/world inventory, sha256. |
| `benchmarks/reference_corpus/scenes/<family>_<name>.blend` | The scenes. Families: `materials_hall` (every BSDF + Principled socket groups), `textures_mapping` (image/procedural textures, Mapping/TexCoord/UV/generated/object, bump/normal/displacement), `lighting_studio` (point/spot/sun/area incl. spread/shape, mesh emitters, IES, light groups), `world_sky` (HDRI incl. sun disc, Sky texture, colour world, rotation/strength), `geometry_zoo` (instances, hair/curves, volumes, motion blur, smooth/flat/auto-smooth, modifiers applied), `camera_lens` (DoF, clip, orthographic/panoramic, exposure/view transform), `render_settings` (passes, cryptomatte, adaptive, denoise on/off, film transparent). |
| `benchmarks/reference_corpus/coverage_report.py` | Joins the manifests against `coverage_matrix.json`: features covered by ≥1 scene, uncovered features, and per-feature Cycles-vs-Astroray verdict from the parity harness; emits `docs/blender_parity/corpus_coverage.md` + JSON. |
| `tests/test_reference_corpus_manifest.py` | Every `.blend` reopens, sha256 matches, manifest node ids match the file, each family covers its declared feature list, no feature in the matrix's SUPPORTED/APPROXIMATED set is uncovered (DROPPED-SILENT features may be uncovered but must be listed). |
| `.astroray_plan/docs/reference-corpus-design-2026-09.md` | Phase 0 output: brainstorm record (with Astra), per-scene concept, camera/composition notes, asset licences, which existing scenes are absorbed or retired. |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/blender_parity/scene_library.py` | `REFERENCE_SCENES` reads the corpus directory instead of the hard-coded three. |
| `benchmarks/blender_parity/render_leg.py` | `--load-blend` works for every corpus scene; non-vacuity checks come from the manifest, not code. |
| `benchmarks/blender_parity/harness.py` | Manifest loader + per-feature verdict export consumed by `coverage_report.py`. |
| `benchmarks/blender_parity/scenes/manifest.json` | The three #729 scenes are absorbed into the corpus (kept byte-identical or regenerated by `build_corpus.py`, recorded either way); this manifest becomes a pointer or is retired. |
| `scripts/benchmarks/weekly_local_bench.ps1` | Parity and showcase legs iterate the corpus families instead of `cornell`/`textured_plane`. |
| `scripts/run_parity.py` | Accepts corpus scene ids. |
| `benchmarks/viewport_parity/blender_driver.py` | Accepts corpus scenes as workloads (pkg241 keeps `metal_sweep` as its historical baseline). |
| `scripts/dev/known_issues_report.py` | Optional: link each open `addon-gap` issue to the corpus scene that reproduces it. |
| `scripts/README.md` | Register `build_corpus.py` and `coverage_report.py`. |

### Key design decisions

- **Rigour first, beauty second, but both required.** Coverage is proven
  by the manifest-vs-matrix test, not by eyeballing. Composition follows
  the owner's showcase rules; each scene must be something the owner would
  put in the README.
- **Deterministic builders over hand-authored files** wherever the feature
  allows it (procedural geometry, node trees built in code), so a scene can
  be regenerated when the schema changes; packed external assets only for
  image textures, IES profiles and HDRIs, each with a recorded licence.
- **One feature can live in several scenes; every SUPPORTED/APPROXIMATED
  feature must live in at least one.** DROPPED-SILENT features are
  represented by a "gap card" in the report, and where cheap, by a scene
  element so the drop is visible in the render (a missing Sky texture
  should show as black sky, not as an absent object).
- **Verdicts come from the existing harness** (pkg104 metrics, pkg119b
  triage buckets, per-channel mean ratio); this package adds scenes and a
  report, not a metric stack (§5b).
- **Phase 0 brainstorm with Astra** (owner request): one Codex session,
  read-only, producing scene concepts and a feature-to-scene allocation;
  the lead keeps final say and records disagreements.
- **Phases:** 0 design doc + allocation table → 1 `materials_hall` +
  `textures_mapping` (largest matrix share) → 2 `lighting_studio` +
  `world_sky` → 3 `geometry_zoo` + `camera_lens` + `render_settings` →
  4 harness/bench integration + coverage report + absorb #729 scenes.

---

## Acceptance criteria

- [ ] `tests/test_reference_corpus_manifest.py` green: every corpus scene
      reopens with matching sha256 and node inventory; zero uncovered
      SUPPORTED/APPROXIMATED features; DROPPED-SILENT features listed.
- [ ] `coverage_report.py` produces `docs/blender_parity/corpus_coverage.md`
      with a per-feature Cycles/Astroray verdict for every covered feature;
      the report is regenerable from a clean checkout with Blender 5.2.
- [ ] Each scene renders in both engines headless (CPU; GPU where the addon
      supports it) without an addon exception; renders saved under
      `benchmarks/reference_corpus/refs/` and inspected by the lead.
- [ ] Weekly bench and the pkg119b harness run on the corpus; the three
      #729 scenes are absorbed with their existing gates still passing.
- [ ] Design doc records the Astra brainstorm, the feature allocation, and
      asset licences.

---

## Non-goals

- Do not fix engine or addon defects the corpus exposes; file issues
  (`addon-bug` / `addon-gap`) and let the owning package fix them.
- No new comparison metrics or a new render driver.
- No Pillar 4 (astrophysics) scenes; a science corpus is a later package.
- No animation sequences; single frames only (motion blur uses
  sub-frame motion inside one frame).

---

## Progress

- [x] 2026-09-09 — **Phase 1 polish MERGED (#781):** `materials_hall` reframed to a 960×176 frieze (alcoves fill the frame at report size), 14 per-alcove crops cut from the same establishing render by `benchmarks/reference_corpus/report_tools.py` (crop rects in the manifest, both engines), contact sheets committed with `git add -f`; manifest tests 10/10; Phase-2 HDRI `assets/syferfontein_18d_clear_1k.hdr` (Poly Haven CC0, sha256 in the README) carried forward. Lead inspection: reframe reads well; Astroray still far noisier at 128 spp (#763, and the addon CPU leg is single-threaded → #780: the 960×176 render took ~2 h 20 min); alcove E Translucent pane renders black (registered gap card). Phase 2 (`lighting_studio` + `world_sky`) not started.
- [x] 2026-09-08 — **Phase 1 MERGED (#761):** `materials_hall.blend` + `textures_mapping.blend`, `build_corpus.py`, manifest (§4.1 schema), corpus README + gap registry, `tests/test_reference_corpus_manifest.py` 7/7; 56/56 and 72/72 allocated rows tagged; both scenes render in both engines headless (CPU). Lead inspection of the contact sheets: layout/colours match Cycles; the hall establishing shot is too wide to read at report size (alcoves are a thin strip) — **Phase 1 polish (next builder session): reframe the hall camera and render the per-alcove crops the design doc §1.1 calls for**; Astroray leg far noisier than Cycles at equal 128 spp (#763); procedural textures feeding Emission render blank (#762). Phase 2 (`lighting_studio` + `world_sky`) next.
- [x] 2026-09-08 evening — continuation lane closed out PR #761: restored
      `textures_mapping_astroray_cpu.png` (regenerated from the render's
      linear `.npy` with `render_leg.py`'s own sRGB tonemap after the prior
      lane's working tree had it deleted) and rebuilt its contact sheet;
      merged `origin/main` (5dea6e37, incl. pkg260 #758) — one conflict
      (`allocation_table.md`) resolved by taking main's script then
      regenerating against the merged 586-row `coverage_matrix.json`.
      pkg260 added 42 rows to `textures_mapping` (`image_property`,
      `input_node`: NEW_GEOMETRY/OBJECT_INFO/ATTRIBUTE/VERTEX_COLOR/
      LIGHT_PATH), all DROPPED-SILENT; 10 already covered by existing
      README text, the other 32 added to the README gap registry +
      `gap_registry.json` (`textures_mapping` now 263 rows owned / 181 gap
      registry, `materials_hall` unaffected). `test_reference_corpus_manifest.py`
      (7/7) and `test_reference_scene_corpus.py` (19/19) re-run clean
      post-merge. Visually inspected both contact sheets: `materials_hall`
      alcove content/positions match Cycles but the Astroray leg is much
      noisier at the same declared 128spp (1915.8s vs Cycles' ~1.2s,
      reading as Cycles' adaptive sampling stopping early) with one addon
      degradation notice (9 approximated BSDF paths, incl. `BSDF_METALLIC`
      dropping Normal/Tangent/Weight and `MULTI_GGX`); `textures_mapping`
      confirms the earlier-flagged defect — all 5 procedural-pattern-node
      `-> Emission -> Output` proof cards render flat white/blank on
      Astroray (Cycles shows each pattern), silently (no addon warning),
      while the same nodes into Principled Base Color elsewhere are known
      to work. Findings written into the PR body for the lead to triage;
      no engine/addon fix attempted (spec non-goal). PR #761 mergeable:
      MERGEABLE (mergeStateStatus UNSTABLE = CI pending re-run post-merge).
- [x] 2026-09-08 afternoon — Phase 1 built: `build_materials_hall_scene` +
      `build_textures_mapping_scene` added to `scene_library.py` (corridor
      gallery / printmaker's workshop per the design doc, both reusing
      existing helpers); `build_corpus.py` CLI (runs inside Blender, cross-
      checks each builder's actively-wired sockets against
      `coverage_matrix.json` via the Phase-0 allocation table, fails loudly
      on a gap); `materials_hall.blend` (57 feature_tags incl. 1 gap card,
      13734 tri) and `textures_mapping.blend` (72 feature_tags, 2926 tri)
      committed with `manifest.json` + `gap_registry.json`; corpus
      `README.md` (charter, gap registry, regenerate instructions);
      `tests/test_reference_corpus_manifest.py` (7 tests, all green: 2
      Blender-dependent skip cleanly without it). Both scenes render in both
      engines (Cycles 128spp CPU; Astroray CPU via the staged OpenMP-off
      `dist/astroray` module) without an addon exception. Along the way,
      found and worked around a real Blender quirk: past a few hundred
      node-trees created in one session, `bpy_prop_collection` string-keyed
      socket lookup starts spuriously raising `KeyError` for sockets plainly
      present under iteration (worked around via an identifier-match
      helper, `scene_library._sock`).
- [x] 2026-09-08 morning — owner answered the design doc §7: scanner extension filed as
      pkg260 (Phase 1 proceeds in parallel); gate (c) switches to the corpus trio when built;
      gate (b) weight = distinct scenes per socket capped at 3; `test_env.hdr` provenance
      waits for the corpus HDRI (Phase 2); duplicate rows folded into pkg260; light/shadow
      linking out of scope; pkg253 landed (#728) so Alcove D tags are final.

- [ ] 2026-09-07 evening — filed by the lead from the owner's directive;
      Phase 0 not started.
- [x] 2026-09-08 — Phase 0 design doc drafted:
      `.astroray_plan/docs/reference-corpus-design-2026-09.md`. Covers all
      seven families, a generated feature-to-scene allocation (527/527
      matrix rows assigned, 114 SUPPORTED + 50 APPROXIMATED with a family
      home, 363 DROPPED-SILENT as gap cards), asset-licence inventory and
      proposals, manifest/tool-interface design, the one-call Astra
      brainstorm (succeeded, folded in with an explicit accept/reject
      record), and a concrete Phase 1 (`materials_hall` +
      `textures_mapping`) build checklist. No scenes built; Phase 1 is the
      next session.

---

## Lessons

- A session that builds hundreds of distinct node-trees (a materials/
  textures corpus scene does exactly this) can hit a real Blender quirk:
  `node.inputs["Name"]` / `"Name" in node.inputs` starts spuriously raising
  `KeyError` / returning `False` for a socket that is plainly present in
  `[s.name for s in node.inputs]`, once enough prior node-trees exist in the
  session (reproduced in isolation with 400 dummy Principled materials
  created first). Iterating and matching by `identifier` (falling back to
  `name`) sidesteps it -- see `scene_library._sock`. Not yet root-caused
  inside Blender itself; flag if another corpus-scale scene hits it.
- `coverage_matrix.json` scanner enumerates node PROPERTIES and INPUT
  sockets, not OUTPUT sockets or (category, feature) pairs with no property
  at all -- several nodes allocated to a family in Phase 0's design doc
  (TEX_COORD, UVMAP, MAPPING, VALTORGB/ColorRamp, MATH, VECT_MATH, MAP_RANGE,
  CLAMP, Combine/Separate Color/XYZ, Curves) turned out to have ZERO
  SUPPORTED/APPROXIMATED rows in the current (post-pkg253) matrix, so Phase 1
  did not need to build dedicated proofs for them -- only the README gap
  registry. Worth knowing before over-building Phase 2/3 content for a node
  the matrix doesn't actually credit yet.
