# Reference corpus (pkg259)

A version-pinned corpus of representative, deliberately attractive Blender
scenes that together exercise every Cycles feature Astroray is meant to
support (materials, textures/mapping, lights, world, geometry, camera,
render settings, passes). Each scene carries a manifest of the matrix
features it demonstrates, so a Cycles feature Astroray silently drops is
found by a test, not by someone happening to wire it. Design record:
`.astroray_plan/docs/reference-corpus-design-2026-09.md`. Spec:
`.astroray_plan/packages/pkg259-cycles-feature-coverage-reference-scenes.md`.

**Phase 3 of 4** (this state): `materials_hall`, `textures_mapping`,
`lighting_studio`, `world_sky`, `geometry_zoo`, `camera_lens`, and
`render_settings` are all built. The harness/bench integration and
`coverage_report.py` are Phase 4 -- see the spec's Progress log.

**Phase 3** (this session): `geometry_zoo` realises the design doc's
"cabinet of curiosities" as ONE establishing shot with six specimen groups
(collection instancing incl. one negative-scale copy, a live modifier
stack, a flat/smooth/auto-smooth shading trio, a small Curves/hair object,
a blurred-vs-explicitly-disabled motion-blur vane pair, and a backlit
volume cabinet), same single-render+crop pattern as every earlier family.
`camera_lens` and `render_settings` scale the design doc's more elaborate
"2x2 camera contact sheet" / "six-panel pass sheet" concepts down to what
the allocation table actually requires (9 and 4 SUPPORTED rows
respectively): `camera_lens` is a single perspective hero shot (a Blender
render has exactly one active camera, so a genuinely different camera
`type` needs a second file the way `world_sky` needed one for its World --
not required here since `type`/`ortho_scale` are DROPPED-SILENT, not
required rows); `render_settings` authors its 4 SUPPORTED render-process
rows on a small hero shot (their effect is normalised away by
`render_leg.py`'s own engine-parity settings, exactly like every other
scene's `cycles.use_denoising`/`use_adaptive_sampling` already are) plus one
cheap, NOT-normalised-away `max_bounces` mirror-pair gap card.

**Phase-1 polish** (earlier session): `materials_hall`'s establishing camera
was reframed (owner feedback on PR #761's contact sheet: the alcove content
was a thin strip lost in a 16:9 frame) to a wide "frieze" aspect ratio sized
to the actual content height, and its per-alcove `crops` are now rendered as
first-class outputs (`report_tools.py`) rather than left as unrendered
manifest rectangles -- see "Naming and files" and "How to regenerate" below.

**Phase 2** (this session): `lighting_studio` realises the design doc's
"four booths, one per light type, 2x2 contact sheet" concept as ONE
establishing shot -- four physically walled booths side by side under a
single fixed camera (the same still life in each), rather than four
separately re-rendered quadrants -- so it reuses the exact single-render
+crop pattern Phase 1 established (cheaper, and the crops already visually
ARE the four-way comparison). `world_sky` is two `.blend` files sharing one
family tag (`world_sky_hdri`/`world_sky_sky`, see "Naming and files")
because a Blender scene has exactly one World, so "HDRI vs Sky, each
against its own Cycles reference" cannot be a single scene.

## Families

| Family | Concept | Status |
|---|---|---|
| `materials_hall` | Every BSDF/closure Cycles ships, staged as a gallery corridor: one alcove per closure family (Diffuse, Glossy/Metallic, Dielectric, the Principled wall, Sheen/Translucent, Emission & spectral, an OSL gap-card placard), one shared 3-point + practical light rig. | Phase 1 (built) |
| `textures_mapping` | A printmaker's workshop: a print table plus small independent proof cards (one `<node> -> Emission -> Output` per required node) for the procedural-texture, pattern, image/coordinate, bump/normal/displacement, and colour-grade/converter node families. | Phase 1 (built) |
| `lighting_studio` | Photography-studio still life in four walled booths (POINT/SUN/SPOT/AREA), one fixed camera, one establishing shot; the SPOT booth carries a synthetic asymmetric-wall-washer IES profile. | Phase 2 (built) |
| `world_sky` | HDRI vs Sky-texture exterior, "three independent opportunities" (background/reflection/indirect), two `.blend` files (`world_sky_hdri`/`world_sky_sky`) sharing the family tag. | Phase 2 (built) |
| `geometry_zoo` | A "cabinet of curiosities": collection instancing, a live modifier stack, a flat/smooth/auto-smooth shading trio, a small Curves (hair) object, a blurred-vs-disabled motion-blur pair, and a backlit volume cabinet (Principled Volume / Volume Absorption / Volume Scatter). | Phase 3 (built) |
| `camera_lens` | One perspective hero shot: DoF (aperture_fstop + focus_object/focus_distance), lens shift, explicit sensor_fit, plus in-scene aperture-blades/clip gap cards. | Phase 3 (built) |
| `render_settings` | A small hero shot proving samples/film_transparent/use_denoising/denoiser by scene authorship, plus an opposed-mirror `max_bounces` gap card. | Phase 3 (built) |

## Naming and files

- `scenes/<family>.blend` -- the built scene (one `.blend` per family for
  `materials_hall`/`textures_mapping`/`lighting_studio`). `world_sky` is the
  one Phase-2 exception: `scenes/world_sky_hdri.blend` and
  `scenes/world_sky_sky.blend` share the `world_sky` family tag (design doc
  Sec 6.2 item 8's "may later split" -- needed here because a Blender scene
  has exactly one World, not because a single frame is illegible).
- `scenes/manifest.json` -- one entry per scene id (`family`, `builder_fn`,
  `blend_path`, `sha256`, `settings` (res/spp/engine), `reopen_verified`,
  `triangle_count`, `curve_count`/`curve_point_count`, `object_counts`,
  `node_ids`, `feature_tags`, `assets`, `crops`. Schema design:
  `.astroray_plan/docs/reference-corpus-design-2026-09.md` Sec 4.1.
- `scenes/gap_registry.json` -- machine copy of every DROPPED-SILENT matrix
  row a family owns that is *not* given an in-scene gap card; the Markdown
  version is the "Gap registry" section below. Regenerated every
  `build_corpus.py` run (`--print-gap-registry` to reprint it to stdout).
- `refs/` -- rendered PNGs (`<family>_<engine>_cpu.png`), a side-by-side
  full-shot contact sheet (`<family>_contact_sheet.png`), and (Phase-1-polish)
  the per-alcove/per-proof crop outputs generated from `manifest.json`'s
  `crops` rects by `report_tools.py`: `<family>_crops/<name>_<engine>.png`
  per crop, plus a `<family>_crops_contact_sheet.png` grid (both engines
  stacked per crop). **Gitignored globally** (`*.png`); committed copies use
  `git add -f`.

## Manifest schema (`feature_tags` entries)

```jsonc
{
  "category": "shader_node", "feature": "BSDF_GLASS",
  "bl_idname": "ShaderNodeBsdfGlass", "socket_or_prop": "input:IOR",
  "classification": "SUPPORTED", "gap_card": false
}
```

Shape mirrors a `docs/blender_parity/coverage_matrix.json` row exactly, so
a future `coverage_report.py` (Phase 4) can join on the same tuple key.
`"gap_card": true` marks a DROPPED-SILENT feature the scene deliberately
makes visible (e.g. the OSL placard in `materials_hall`); every other
DROPPED-SILENT row for the family is *not* in `feature_tags` -- it is listed
in the Gap registry below instead.

## Coverage-claim rule (binding)

A `feature_tags` entry is only valid if the socket/prop is **connected or
set to a non-default, effect-producing value** *and* its effect falls inside
a documented crop region (`crops` in the manifest) -- not merely "the node
exists somewhere in the scene". `build_corpus.py` enforces the SUPPORTED/
APPROXIMATED half of this mechanically: each scene builder in
`benchmarks/blender_parity/scene_library.py` returns the exact
`(bl_idname, socket_or_prop)` pairs it actively wires, and `build_corpus.py`
cross-checks that list against every SUPPORTED/APPROXIMATED
`coverage_matrix.json` row assigned to the family (via the Phase-0
allocation table's `ASSIGN` map) -- it raises loudly (`SystemExit`) if a
required row is missing, or if a builder claims a row that isn't actually
assigned to that family. This is why building the corpus is called
"proving" coverage rather than "asserting" it.

## Coverage totals (Phase 1+2+3, post-pkg253/pkg260 matrix)

| Scene id | Family | Rows owned | SUPPORTED | APPROXIMATED | tagged (feature_tags) | gap-carded | gap registry |
|---|---|---|---|---|---|---|---|
| `materials_hall` | `materials_hall` | 166 | 10 | 46 | 56 | 1 (SCRIPT) | 109 |
| `textures_mapping` | `textures_mapping` | 263 | 69 | 3 | 72 | 0 | 181 |
| `lighting_studio` | `lighting_studio` | 36 | 24 | 0 | 24 | 4 | 8 |
| `world_sky_hdri` | `world_sky` | 25 | 1 | 0 | 1 | 5 | 19 |
| `world_sky_sky` | `world_sky` | 25 | 1 | 0 | 1 | 11 | 13 |
| `geometry_zoo` | `geometry_zoo` | 47 | 5 | 12 | 18 | 1 (`instance_collection`) | 29 |
| `camera_lens` | `camera_lens` | 16 | 9 | 0 | 12 | 3 (`aperture_blades`, `clip_start`, `clip_end`) | 4 |
| `render_settings` | `render_settings` | 33 | 4 | 0 | 5 | 1 (`max_bounces`) | 28 |

("Rows owned" = every matrix row the Phase-0 allocation table assigns to
that FAMILY as primary owner (`SOCKET_OVERRIDE`-resolved, e.g. World's
`light_linking_shadow_linking` gap card belongs to `lighting_studio`, not
`world_sky`, even though every other World row stays `world_sky`);
DROPPED-SILENT rows make up the remainder. Re-run
`.astroray_plan/docs/pkg259-phase0/build_allocation_table.py` if
`coverage_matrix.json` changes -- these totals will drift with it.
`world_sky_hdri`/`world_sky_sky` both own the SAME 25-row `world_sky` family
pool (a Blender scene has exactly one World, so the HDRI/Sky comparison is
two `.blend` files, not one) -- each independently covers the family's one
SUPPORTED row (`use_nodes`); across the pair, every one of the 24
DROPPED-SILENT rows is gap-carded by at least one half and/or listed in at
least one half's gap registry (10 rows are gap-carded by one half while
still appearing in the OTHER half's registry, e.g. `TEX_ENVIRONMENT` is
gap-carded in `world_sky_hdri` but has no environment-texture node to
gap-card in `world_sky_sky`, so it is `world_sky_sky`'s registry entry
instead) -- verified by `test_families_cover_their_allocated_rows`, which
unions both halves' `feature_tags`/gap-registry rows before checking.
pkg260's scanner extension (#758, merged 2026-09-08) landed 42 new rows for
`textures_mapping` (`image_property`/`input_node` categories: Image /
`ShaderNodeTexImage` colour-management properties, `NEW_GEOMETRY`,
`OBJECT_INFO`, `ATTRIBUTE`, `VERTEX_COLOR`, `LIGHT_PATH`), all
DROPPED-SILENT; 10 of them (`Image`/`ShaderNodeTexImage`/`ATTRIBUTE`) are
already documented under the same `bl_idname` elsewhere in this file, the
other 32 are newly listed in the gap registry below. `materials_hall` is
unaffected by the pkg260 merge -- no new rows were assigned to it.)

## How a new Cycles feature gets a home

1. Add/extend a row in `docs/blender_parity/coverage_matrix.json` (owned by
   pkg229/pkg119 Phase A's scanner, not this package).
2. Assign it to a family in `.astroray_plan/docs/pkg259-phase0/build_allocation_table.py`'s
   `ASSIGN` map, re-run the script, and check `allocation_table.md` picked it up.
3. Wire it into that family's builder in `benchmarks/blender_parity/scene_library.py`
   (`build_<family>_scene`), returning the new `(bl_idname, socket_or_prop)`
   pair in the builder's `tags` list, with a documented crop region.
4. Re-run `build_corpus.py --families <family>` -- it fails loudly if the row
   isn't actually wired, or if `tags` claims something the allocation table
   doesn't assign to this family.
5. Re-render both engines (`render_leg.py --load-blend`) and update `refs/`.

## How to regenerate

```
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --factory-startup \
    --python benchmarks/reference_corpus/build_corpus.py -- \
    --families materials_hall textures_mapping lighting_studio world_sky_hdri world_sky_sky \
               geometry_zoo camera_lens render_settings \
    --out-dir benchmarks/reference_corpus/scenes
```

(`world_sky_hdri`/`world_sky_sky` are the two `.blend` files for the
`world_sky` family -- there is no bare `world_sky` scene id. `geometry_zoo`/
`camera_lens`/`render_settings` are plain 1:1 scene ids like
`materials_hall`/`textures_mapping`/`lighting_studio`.)

Then render both engines per scene via `render_leg.py --load-blend` (absolute
paths for `--load-blend`/`--out` -- Blender's relative-path resolution after
`bpy.ops.wm.open_mainfile` does not reliably match the invoking shell's
working directory). Per-scene resolution/samples come from `manifest.json`'s
`settings` (`materials_hall` 960x176 @256spp, `textures_mapping` 960x540
@192spp, `lighting_studio` 640x160 @256spp, `world_sky_hdri`/`world_sky_sky`
480x270 @128spp, `geometry_zoo` 960x220 @96spp, `camera_lens` 640x400
@192spp, `render_settings` 640x360 @128spp -- all comfortably under the
addon's CPU render budget, see "Render times" below):

```
blender.exe -b --factory-startup --python benchmarks/blender_parity/render_leg.py -- \
    --load-blend <abs>/benchmarks/reference_corpus/scenes/<scene_id>.blend \
    --engine CYCLES --out <abs>/benchmarks/reference_corpus/refs/<scene_id>_cycles_cpu \
    --res 640 --res-y 160 --samples 256 --device cpu
```

(swap `--engine CUSTOM_RAYTRACER` and set `ASTRORAY_PYD_DIR` to the staged
OpenMP-off CPU addon module for the Astroray leg). `render_leg.py` writes a
linear `.npy`; convert to a display PNG with any sRGB-encode helper (Blender's
own Python often lacks Pillow -- the repo's normal Python environment does not).

Then turn the two `.npy` renders into the full contact sheet and per-alcove/
per-booth crops (`report_tools.py`, run in the repo's normal Python env, not
Blender; `--family` takes a scene id, e.g. `world_sky_hdri`, not the family
name):

```
python benchmarks/reference_corpus/report_tools.py \
    --family materials_hall \
    --cycles-npy <out>/materials_hall_cycles_cpu.npy \
    --astroray-npy <out>/materials_hall_astroray_cpu.npy \
    --manifest benchmarks/reference_corpus/scenes/manifest.json \
    --out-dir benchmarks/reference_corpus/refs
```

This writes `refs/<scene_id>_{cycles,astroray}_cpu.png`,
`refs/<scene_id>_contact_sheet.png`, `refs/<scene_id>_crops/<name>_<engine>.png`
per `manifest.json` `crops` entry, and `refs/<scene_id>_crops_contact_sheet.png`.

## Render times (measured, RTX 5070 Ti host, CPU-only legs)

| Scene id | Resolution | Samples | Cycles CPU | Astroray CPU |
|---|---|---|---|---|
| `lighting_studio` | 640x160 | 256 | ~4s | ~29-40s |
| `world_sky_hdri` | 480x270 | 128 | ~7s | ~37-42s |
| `world_sky_sky` | 480x270 | 128 | ~7s | ~17-19s |
| `geometry_zoo` | 960x220 | 96 | ~3s | ~22-23s |
| `camera_lens` | 640x400 | 192 | ~9-10s | ~123-126s |
| `render_settings` | 640x360 | 128 | ~4-7s | ~6s |

All stay far under the ~40 min/render budget the addon's CPU leg needs for
`materials_hall`-scale scenes (#780) -- most Phase 2/3 scenes are simple
enough (no thin-film/subsurface/hair closures) that per-sample cost is
roughly two orders of magnitude cheaper than `materials_hall`'s alcove
corridor at comparable sample counts. `camera_lens` is the one Phase-3
outlier (~126s, still 19x under budget): its shallow-DoF hero shot needs a
full 192spp for the bokeh disks to read cleanly rather than as noise, and
its 9-object scene (spheres + bokeh specks + clip props) costs more per
sample than the other Phase-3 scenes.

## Asset licences

Phase 1 itself uses only procedural geometry/textures (per the design doc's
"procedural builders over hand-authored files" decision) plus Blender's
bundled Suzanne monkey mesh (`materials_hall` Alcove D bust -- ships with
every Blender install, no licence needed). The one deferred item: a real
CC0 file-based image for the `TEX_IMAGE` file-loading proof (the Phase-1
`TEX_IMAGE` row is instead covered by a procedural stripe pixel buffer,
which proves the `Vector` input row but not file I/O) -- tracked as a
Phase 1 gap, see "Known Phase-1 gaps" below.

One asset was pulled forward from Phase 2 (`world_sky`) during the Phase-1
polish session and committed then; Phase 2 (this session) wires it into
`world_sky_hdri`'s World node tree (`ShaderNodeTexEnvironment`, via a
repo-relative `//../assets/...` path rewritten after the first save, same
pattern `hdri_exterior_hair` (#729) already uses) and records it in that
scene's manifest `assets` entry:

| File | Resolution | Source | Licence | sha256 |
|---|---|---|---|---|
| `assets/syferfontein_18d_clear_1k.hdr` | 1k | https://polyhaven.com/a/syferfontein_18d_clear | CC0 1.0 | `6f81c4b48dcb79555d7e8a8839e59e75d76fd34f1e07e070f6dd923df5c119a0` |

`lighting_studio`'s IES photometric profile (SPOT booth) is synthesized
in code, not downloaded -- a `bpy.types.Text` data-block (`ShaderNodeTexIES`
`INTERNAL` mode) generated by `scene_library._ies_wall_washer_lm63()`
(design doc Sec 3.2's "synthesize procedurally... sidesteps IES licensing
entirely"; format research: `.astroray_plan/docs/pkg259-phase2-ies-format-research.md`).
No external asset, no licence question, no relative-path bookkeeping.

## Known Phase-1 gaps (deliberate, not oversights)

- **`TEX_IMAGE` file-based loading** is deferred (spec's binding Phase-1
  scope: "no external downloads in this phase"); the procedural stripe
  buffer covers the `input:Vector` row honestly but not file-I/O behaviour.
- **`materials_hall` Alcoves F (Hair BSDFs) and G (shader-graph utility:
  Add/Mix Shader, Holdout, ShaderToRGB, Material Raycast)** are not built:
  every row those nodes own in the current matrix is DROPPED-SILENT (no
  SUPPORTED/APPROXIMATED row would go untagged by skipping them), so they
  are gap-registry entries only, not in-scene content. `BSDF_RAY_PORTAL`'s
  "impossible doorway" concept from the design doc is likewise gap-registry
  only for the same reason.
- **One `.blend` per family** (not split into sub-scenes) -- both Phase-1
  frames render legibly at the coverage-report's thumbnail size; see the
  design doc Sec 6.2 item 8's open decision, resolved here as "no split
  needed."
- **Crop rectangles** (`manifest.json`'s `crops`) are a linear pinhole
  approximation (`scene_library._crop_rect`), not a perspective-accurate
  projection -- adequate for Phase 4's coverage report; refine there if a
  crop render disagrees with the documented rectangle.

## Known Phase-2 gaps and findings (deliberate scope cuts, and one addon-gap)

- **World env-map indirect illumination does not reach diffuse surfaces in
  the Astroray addon leg (addon-gap candidate, NOT fixed here per spec
  non-goals).** `world_sky_hdri`'s "three independent opportunities" test
  (design doc Sec 1.4) cleanly separates the three: the HDRI background
  displays correctly and the chrome hero sphere reflects it correctly in
  BOTH engines, but the diffuse ground plane and shaded recess -- lit only
  by indirect/ambient environment light in Cycles -- render essentially
  unlit/black in the Astroray CPU leg (`refs/world_sky_hdri_crops/
  indirect_astroray_cpu.png` vs `indirect_cycles_cpu.png`). This is exactly
  the failure mode the design doc's "three opportunities" rule exists to
  catch (a world that displays but does not illuminate) -- the scene did its
  job. It is surprising given CPU env NEE landed engine-side (memory
  `env-nee-absent-cdf-sampler-unused`, #747/#751); the Blender addon's
  world-lighting wire-up may be a separate code path that was not updated,
  but that diagnosis is not confirmed here -- filed as a finding for the
  addon owner, not investigated further (non-goal: "do not fix engine or
  addon defects the corpus exposes").
- **`world_sky_sky`'s Sky Texture is a clean total drop, as expected.**
  Astroray logs `No recognised world shader: set background color to black`
  and renders solid black; Cycles renders the full Nishita/Multiple-
  Scattering sky. This is the spec's textbook "visible drop" example, not a
  finding -- `TEX_SKY` is 100% DROPPED-SILENT in the current matrix.
- **Sky Texture brightness is tuned down from a physically-scaled default**
  (`Background.Strength = 0.06`, not `1.0`) because this harness's
  `render_leg.py` uses a plain sRGB encode with no filmic tone-mapping
  (`Standard` view transform, `exposure=0.0`) -- Nishita sky radiance at
  Strength 1.0 blows the whole Cycles reference to white, which would make
  the "visible drop" comparison illegible on the ONE side that is supposed
  to look correct. This is an exposure choice for legibility, not a claim
  about default Sky Texture behaviour.
- **`lighting_studio`'s SPOT-booth IES intensity constant** (the Math node
  multiplying `ShaderNodeTexIES`'s `Factor` output before `Emission.Strength`)
  was tuned by eye (180.0) for a legible, non-blown wall-wash in both
  engines at 256spp -- an artistic exposure choice for the coverage demo,
  not a photometric calibration claim about the synthetic IES profile's
  absolute units.
- **Booth walls are not a perfect light seal** (`scene_library._studio_booth_walls`):
  each booth's back+side walls contain its own light well enough at the
  studio's scale for the four-booth comparison to read cleanly, but this is
  not a rigorously verified zero-bleed enclosure.
- **`world_sky`'s recess "no direct sky visibility" enclosure**
  (`scene_library._world_sky_geometry`'s `_recess_panel` roof+3-walls) is a
  reasonable approximation, not a raytraced occlusion proof -- Cycles'
  correctly-lit recess interior (see the addon-gap finding above) confirms
  the geometry receives SOME environment-derived light as intended; it does
  not confirm zero direct sky rays reach the interior.
- **`world_sky`'s design-doc extras are deferred**, to keep both Astroray
  renders comfortably inside the render-time budget: the "small strip of
  inset thumbnails" demonstrating world rotation/strength, and the paired
  low/high-turbidity Sky variant (design doc Sec 1.4: "a dropped Sky
  parameter may leave a plausible-looking default sky instead of a black
  one... pair a variant to expose a control that is silently ignored").
  `world_sky_sky`'s single black-frame result already demonstrates the
  simpler "total drop" case; the "silently-ignored-parameter" case is not
  demonstrated this phase.
- **Light-linking/shadow-linking** (`World.light_linking_shadow_linking`,
  the one `SOCKET_OVERRIDE` row) is a doc-only gap-registry entry, per the
  owner's 2026-09-08 decision (design doc Sec "Owner answers", Q7: "out of
  scope for the corpus").

## Known Phase-3 gaps and findings (deliberate scope cuts, and inspection notes)

- **`geometry_zoo`'s non-volume content (instancing, modifiers, shading,
  motion blur) is proven by the six Object-category matrix rows only, not by
  a per-node manifest join.** Design doc Sec 1.5's "known matrix gap": there
  is no `Modifier`/scene-graph scanner category beyond `object`'s six rows
  (all allocated here and all tagged), so the visual richness beyond those
  six rows is inspected, not mechanically proven -- an open owner question
  the design doc already recorded (Sec "Owner answers" Q1), not
  re-litigated in this phase.
- **`geometry_zoo`'s volume cabinet renders very differently between
  engines (finding, not fixed here per spec non-goals).** Cycles shows the
  striped backdrop attenuated/scattered through three visually distinct
  cubes (Principled Volume glowing warm, Absorption tinting red, Scatter
  softening to white); Astroray's leg (`refs/geometry_zoo_crops/
  volume_astroray_cpu.png` vs `volume_cycles_cpu.png`) shows a much brighter,
  more saturated result (a solid yellow-orange disk where Cycles shows a
  soft red patch) -- consistent with a coarser/differently-normalised
  homogeneous-volume implementation, not investigated further here.
- **`geometry_zoo`'s motion-blur pair is a weak visual tell at this crop
  scale/sample count.** The VaneBlur/VaneSharp vanes are both authored
  correctly (`cycles.use_motion_blur` True/False, keyframed rotation
  either side of the current frame, `scene.render.use_motion_blur = True`)
  and the addon does receive the property, but neither vane shows an
  obvious blur streak at 96spp/960x220 in either engine -- the ±25 degree
  in-plane rotation of a thin blade does not displace enough screen-space
  pixels at this scale to read clearly. The matrix row is proven by
  authorship (build_corpus.py's cross-check), not by this observation.
- **`camera_lens`'s "near" DoF sphere and near-clip prop both under-read.**
  `LensNear` (placed close to the camera and off-axis for the original
  three-sphere DoF trio) falls outside the rendered frame's field of view at
  this camera placement -- only the focus/far pair is visible, which is
  still enough to prove the DoF row (sharp focus subject vs. a visibly
  softer far sphere in both engines). `NearClipProp` (a tiny 0.08-unit cube
  just inside `clip_start`) is only a few pixels at this resolution and is
  not clearly distinguishable in the contact sheet; the row's actual
  DROPPED-SILENT status is instead confirmed by the addon's own console
  degradation message (`ignored camera clip_start/clip_end`), and the
  `clip_far` crop is a strong, clean visible-drop demonstration (Cycles
  shows only three bokeh discs on black; Astroray shows the same three
  discs in front of the magenta backdrop plane that should have been culled
  by `clip_end`).
- **`camera_lens` builds no orthographic/panoramic camera in-scene.** A
  Blender render has exactly one active camera, so demonstrating a second
  camera `type` needs either a second `.blend` (the `world_sky` pattern) or
  a second render pass; `type`/`ortho_scale` are DROPPED-SILENT, not
  required rows, so this is scope-cut to a gap-registry entry rather than
  built, the same simplification precedent as materials_hall's un-built
  Alcoves F/G (Known Phase-1 gaps above).
- **`render_settings`'s four SUPPORTED rows are proven by scene authorship,
  not by a visible pixel difference in this corpus's own contact sheet.**
  `render_leg.py`'s `_configure_render` normalises samples/denoising for a
  fair per-engine comparison across every scene in the corpus (it already
  force-disables `cycles.use_denoising`/`use_adaptive_sampling` for every
  OTHER family too) -- `film_transparent`/`use_denoising`/`denoiser`/
  `samples` are genuinely written to non-default values in the committed
  `.blend` (checked by `build_corpus.py`'s manifest-vs-matrix join) but are
  not expected to visibly differ in `render_settings_contact_sheet.png`.
  Building a bespoke renderer that respects them would be a new comparison
  driver, out of scope per the spec's non-goals.
- **`render_settings`'s `max_bounces` mirror gap card is a subtle tell at
  this exposure/scale.** Both opposed mirrors read mostly dark in both
  engines (a 2-bounce cap on a facing-mirror pair mostly resolves to black
  beyond the second reflection at this scene's modest lighting), so the
  Cycles-correct-vs-Astroray-ignores-the-cap difference is present in the
  render but not a dramatic visual -- a stronger version would need a
  brighter mirror-facing scene, deferred as a nice-to-have polish item
  rather than re-built now.

## Gap registry

Every DROPPED-SILENT `coverage_matrix.json` row a family owns that is *not*
given an in-scene gap card (machine copy: `scenes/gap_registry.json`,
regenerated by `build_corpus.py`). `world_sky_hdri`/`world_sky_sky` each
list only the rows THEY leave uncovered -- a row gap-carded by one half and
registered by the other appears in only one of the two lists below (see the
"Coverage totals" footnote for the union accounting).

### `materials_hall` (109 rows)

- `ADD_SHADER` (`ShaderNodeAddShader`): input:Shader, input:Shader
- `BSDF_DIFFUSE` (`ShaderNodeBsdfDiffuse`): input:Normal, input:Weight
- `BSDF_GLASS` (`ShaderNodeBsdfGlass`): input:Normal, input:Weight, input:Thin Film Thickness, input:Thin Film IOR, prop:distribution
- `BSDF_GLOSSY` (`ShaderNodeBsdfAnisotropic`): input:Anisotropy, input:Rotation, input:Normal, input:Tangent, input:Weight, prop:distribution
- `BSDF_HAIR` (`ShaderNodeBsdfHair`): input:Color, input:Offset, input:RoughnessU, input:RoughnessV, input:Tangent, input:Weight, prop:component
- `BSDF_HAIR_PRINCIPLED` (`ShaderNodeBsdfHairPrincipled`): input:Color, input:Melanin, input:Melanin Redness, input:Tint, input:Absorption Coefficient, input:Aspect Ratio, input:Roughness, input:Radial Roughness, input:Coat, input:IOR, input:Offset, input:Random Color, input:Random Roughness, input:Random, input:Weight, input:Reflection, input:Transmission, input:Secondary Reflection, prop:model, prop:parametrization
- `BSDF_METALLIC` (`ShaderNodeBsdfMetallic`): input:IOR, input:Extinction, input:Normal, input:Tangent, input:Weight
- `BSDF_PRINCIPLED` (`ShaderNodeBsdfPrincipled`): input:Weight, input:Subsurface IOR, input:Tangent, input:Coat Normal, prop:distribution, prop:subsurface_method
- `BSDF_RAY_PORTAL` (`ShaderNodeBsdfRayPortal`): input:Color, input:Position, input:Direction, input:Weight
- `BSDF_REFRACTION` (`ShaderNodeBsdfRefraction`): input:Normal, input:Weight, prop:distribution
- `BSDF_SHEEN` (`ShaderNodeBsdfSheen`): input:Normal, prop:distribution
- `BSDF_TOON` (`ShaderNodeBsdfToon`): input:Color, input:Size, input:Smooth, input:Normal, input:Weight, prop:component
- `BSDF_TRANSLUCENT` (`ShaderNodeBsdfTranslucent`): input:Normal, input:Weight
- `BSDF_TRANSPARENT` (`ShaderNodeBsdfTransparent`): input:Weight
- `EEVEE_SPECULAR` (`ShaderNodeEeveeSpecular`): input:Base Color, input:Specular, input:Roughness, input:Emissive Color, input:Transparency, input:Normal, input:Clear Coat, input:Clear Coat Roughness, input:Clear Coat Normal, input:Weight
- `EMISSION` (`ShaderNodeEmission`): input:Weight
- `HOLDOUT` (`ShaderNodeHoldout`): input:Weight
- `MATERIAL_RAYCAST` (`ShaderNodeRaycast`): input:Position, input:Direction, input:Length, input:, prop:active_index, prop:only_local
- `MIX_SHADER` (`ShaderNodeMixShader`): input:Factor, input:Shader, input:Shader
- `OUTPUT_MATERIAL` (`ShaderNodeOutputMaterial`): input:Surface, input:Volume, input:Displacement, input:Thickness, prop:is_active_output, prop:target
- `SCRIPT` (`ShaderNodeScript`): prop:use_auto_update (`prop:mode` is gap-carded in-scene, Alcove I placard)
- `SHADERTORGB` (`ShaderNodeShaderToRGB`): input:Shader
- `SUBSURFACE_SCATTERING` (`ShaderNodeSubsurfaceScattering`): input:Color, input:Scale, input:Radius, input:IOR, input:Roughness, input:Anisotropy, input:Normal, input:Weight, prop:falloff

### `textures_mapping` (181 rows)

- `AMBIENT_OCCLUSION` (`ShaderNodeAmbientOcclusion`): input:Color, input:Distance, input:Normal, prop:inside, prop:only_local, prop:samples
- `ATTRIBUTE` (`ShaderNodeAttribute`): prop:attribute_type
- `BEVEL` (`ShaderNodeBevel`): input:Radius, input:Normal, prop:samples
- `BUMP` (`ShaderNodeBump`): prop:invert
- `CLAMP` (`ShaderNodeClamp`): input:Value, input:Min, input:Max, prop:clamp_type
- `COMBINE_COLOR` (`ShaderNodeCombineColor`): input:Red, input:Green, input:Blue, prop:mode
- `COMBXYZ` (`ShaderNodeCombineXYZ`): input:X, input:Y, input:Z
- `CURVE_FLOAT` (`ShaderNodeFloatCurve`): input:Factor, input:Value
- `CURVE_RGB` (`ShaderNodeRGBCurve`): input:Factor, input:Color
- `CURVE_VEC` (`ShaderNodeVectorCurve`): input:Factor, input:Vector
- `DISPLACEMENT` (`ShaderNodeDisplacement`): input:Normal, prop:space
- `FRESNEL` (`ShaderNodeFresnel`): input:IOR, input:Normal
- `INVERT` (`ShaderNodeInvert`): input:Factor
- `LAYER_WEIGHT` (`ShaderNodeLayerWeight`): input:Blend, input:Normal
- `LIGHT_FALLOFF` (`ShaderNodeLightFalloff`): input:Strength, input:Smooth
- `LIGHT_PATH` (`ShaderNodeLightPath`, pkg260): output:Is Camera Ray, output:Is Shadow Ray, output:Is Diffuse Ray, output:Is Glossy Ray, output:Is Singular Ray, output:Is Reflection Ray, output:Is Transmission Ray, output:Is Volume Scatter Ray, output:Ray Length, output:Ray Depth, output:Diffuse Depth, output:Glossy Depth, output:Transparent Depth, output:Transmission Depth, output:Portal Depth
- `MAPPING` (`ShaderNodeMapping`): input:Vector, input:Location, input:Rotation, input:Scale, prop:vector_type
- `MAP_RANGE` (`ShaderNodeMapRange`): input:Value, input:From Min, input:From Max, input:To Min, input:To Max, input:Steps, input:Vector, input:From Min, input:From Max, input:To Min, input:To Max, input:Steps, prop:clamp, prop:data_type, prop:interpolation_type
- `MATH` (`ShaderNodeMath`): input:Value, input:Value, input:Value, prop:operation, prop:use_clamp
- `MIX` (`ShaderNodeMix`): input:Factor, input:Factor, input:A, input:B, input:A, input:B, input:A, input:B, input:A, input:B, prop:clamp_factor, prop:clamp_result, prop:data_type, prop:factor_mode
- `MIX_RGB` (`ShaderNodeMixRGB`): input:Factor, input:Color1, input:Color2, prop:use_alpha, prop:use_clamp
- `NEW_GEOMETRY` (`ShaderNodeNewGeometry`, pkg260): output:Position, output:Normal, output:Tangent, output:True Normal, output:Incoming, output:Parametric, output:Backfacing, output:Pointiness, output:Random Per Island
- `NORMAL` (`ShaderNodeNormal`): input:Normal
- `NORMAL_MAP` (`ShaderNodeNormalMap`): prop:base, prop:convention, prop:space
- `OBJECT_INFO` (`ShaderNodeObjectInfo`, pkg260): output:Location, output:Color, output:Alpha, output:Object Index, output:Material Index, output:Random
- `SEPARATE_COLOR` (`ShaderNodeSeparateColor`): input:Color, prop:mode
- `SEPXYZ` (`ShaderNodeSeparateXYZ`): input:Vector
- `SQUEEZE` (`ShaderNodeSqueeze`): input:Value, input:Width, input:Center
- `ShaderNodeRadialTiling` (`ShaderNodeRadialTiling`): input:Vector, input:Sides, input:Roundness, prop:normalize
- `TANGENT` (`ShaderNodeTangent`): prop:axis, prop:direction_type
- `TEX_BRICK` (`ShaderNodeTexBrick`): input:Vector, input:Mortar, prop:offset
- `TEX_CHECKER` (`ShaderNodeTexChecker`): input:Vector
- `TEX_COORD` (`ShaderNodeTexCoord`): prop:from_instancer
- `TEX_GABOR` (`ShaderNodeTexGabor`): input:Vector, input:Scale, input:Frequency, input:Anisotropy, input:Orientation, input:Orientation, prop:gabor_type
- `TEX_GRADIENT` (`ShaderNodeTexGradient`): input:Vector
- `TEX_IMAGE` (`ShaderNodeTexImage`): prop:extension, prop:interpolation, prop:projection, prop:projection_blend
- `TEX_MAGIC` (`ShaderNodeTexMagic`): input:Vector
- `TEX_NOISE` (`ShaderNodeTexNoise`): input:Vector, input:W, prop:noise_dimensions
- `TEX_VORONOI` (`ShaderNodeTexVoronoi`): input:Vector, input:W, prop:voronoi_dimensions
- `TEX_WAVE` (`ShaderNodeTexWave`): input:Vector
- `TEX_WHITE_NOISE` (`ShaderNodeTexWhiteNoise`): input:Vector, input:W, prop:noise_dimensions
- `UVMAP` (`ShaderNodeUVMap`): prop:from_instancer
- `VALTORGB` (`ShaderNodeValToRGB`): input:Factor
- `VECTOR_DISPLACEMENT` (`ShaderNodeVectorDisplacement`): input:Vector, input:Midlevel, input:Scale, prop:space
- `VECTOR_ROTATE` (`ShaderNodeVectorRotate`): input:Vector, input:Center, input:Axis, input:Angle, input:Rotation, prop:invert, prop:rotation_type
- `VECT_MATH` (`ShaderNodeVectorMath`): input:Vector, input:Vector, input:Vector, input:Scale, prop:operation
- `VECT_TRANSFORM` (`ShaderNodeVectorTransform`): input:Vector, prop:convert_from, prop:convert_to, prop:vector_type
- `VERTEX_COLOR` (`ShaderNodeVertexColor`, pkg260): output:Color, output:Alpha
- `WIREFRAME` (`ShaderNodeWireframe`): input:Size, prop:use_pixel_size

### `lighting_studio` (8 rows)

- `AREA` (``): specular_factor
- `OUTPUT_LIGHT` (`ShaderNodeOutputLight`): prop:is_active_output, prop:target
- `POINT` (``): specular_factor
- `SPOT` (``): specular_factor, show_cone
- `SUN` (``): specular_factor
- `World` (``): light_linking_shadow_linking

(`specular_factor`'s empty `bl_idname` is a Light datablock property, not a
shader node -- see the design doc's `light`/`world` category rows. `show_cone`
is a viewport-only gizmo toggle with no rendered effect, hence no gap card.)

### `world_sky_hdri` (19 rows)

- `BACKGROUND` (`ShaderNodeBackground`): input:Weight
- `OUTPUT_WORLD` (`ShaderNodeOutputWorld`): input:Volume, prop:is_active_output, prop:target
- `TEX_ENVIRONMENT` (`ShaderNodeTexEnvironment`): prop:projection
- `TEX_SKY` (`ShaderNodeTexSky`): input:Vector, prop:aerosol_density, prop:air_density, prop:altitude, prop:ground_albedo, prop:ozone_density, prop:sky_type, prop:sun_direction, prop:sun_disc, prop:sun_elevation, prop:sun_intensity, prop:sun_rotation, prop:sun_size, prop:turbidity

(`TEX_SKY` has no node to gap-card in this half -- `world_sky_hdri` has no
Sky Texture node at all; see `world_sky_sky` below for its gap-carded rows.)

### `world_sky_sky` (13 rows)

- `BACKGROUND` (`ShaderNodeBackground`): input:Weight
- `OUTPUT_WORLD` (`ShaderNodeOutputWorld`): input:Volume, prop:is_active_output, prop:target
- `TEX_ENVIRONMENT` (`ShaderNodeTexEnvironment`): input:Vector, prop:interpolation, prop:projection
- `TEX_SKY` (`ShaderNodeTexSky`): input:Vector, prop:aerosol_density, prop:air_density, prop:altitude, prop:ozone_density, prop:sun_direction

(`TEX_ENVIRONMENT` has no node to gap-card in this half -- `world_sky_sky`
has no Environment Texture node at all; see `world_sky_hdri` above.)

### `geometry_zoo` (29 rows)

- `HAIR_INFO` (`ShaderNodeHairInfo`): output:Is Strand, output:Intercept, output:Length, output:Thickness, output:Tangent Normal, output:Random
- `PRINCIPLED_VOLUME` (`ShaderNodeVolumePrincipled`): input:Color Attribute, input:Density Attribute, input:Absorption Color, input:Blackbody Tint, input:Temperature Attribute, input:Weight
- `VOLUME_ABSORPTION` (`ShaderNodeVolumeAbsorption`): input:Weight
- `VOLUME_COEFFICIENTS` (`ShaderNodeVolumeCoefficients`): input:Weight, input:Absorption Coefficients, input:Scatter Coefficients, input:Anisotropy, input:IOR, input:Backscatter, input:Alpha, input:Diameter, input:Emission Coefficients, prop:phase
- `VOLUME_SCATTER` (`ShaderNodeVolumeScatter`): input:IOR, input:Backscatter, input:Alpha, input:Diameter, input:Weight, prop:phase

(`Object.instance_collection` is gap-carded in-scene instead -- the RockProto
collection-instancing content demonstrates it directly at no extra cost.)

### `camera_lens` (4 rows)

- `Camera` (``): aperture_rotation, aperture_ratio, type, ortho_scale

(`aperture_blades`, `clip_start`, and `clip_end` are gap-carded in-scene
instead -- see "Known Phase-3 gaps and findings" above.)

### `render_settings` (28 rows)

- `OUTPUT_AOV` (`ShaderNodeOutputAOV`): input:Color, input:Value
- `OUTPUT_LINESTYLE` (`ShaderNodeOutputLineStyle`): input:Color, input:Color Fac, input:Alpha, input:Alpha Fac, prop:blend_type, prop:is_active_output, prop:target, prop:use_alpha, prop:use_clamp
- `RenderSettings` (``): use_adaptive_sampling, adaptive_threshold, adaptive_min_samples, seed, sample_offset, film_exposure, filter_width, diffuse_bounces, glossy_bounces, transparent_max_bounces, transmission_bounces, volume_bounces, caustics_reflective, caustics_refractive, use_fast_gi, denoising_input_passes
- `UVALONGSTROKE` (`ShaderNodeUVAlongStroke`): prop:use_tips

(`max_bounces` is gap-carded in-scene instead -- the opposed-mirror pair,
see "Known Phase-3 gaps and findings" above.)
