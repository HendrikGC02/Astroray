# Production node-tree corpus (pkg310)

Eight realistic production materials, each on a neutral stage (CC0 Poly Haven HDRI + sun + area lamp + grey floor),
320x240, Cycles 5.2 LTS reference at 1024 spp, Astroray gate at 64 spp, seed 278, adaptive off, denoise off,
Standard view transform. The point is to measure, before fixing anything, what a real node tree does to
Astroray: in band or not per backend, which (node, socket) pairs are exercised, and which are silently dropped.
Results and the ranked backlog: `.astroray_plan/docs/pkg310-production-corpus-burndown.md`.

| Scene | Object | Nodes exercised |
|---|---|---|
| `prod_car_paint` | sphere | Principled (Coat, Coat Roughness/IOR), Voronoi (Object coords) -> Bump -> Normal, Layer Weight Facing -> Mix (RGBA) base/flake tint, Fresnel -> Math -> Metallic |
| `prod_wood` | sphere | Object coords -> Mapping (rotation) -> Wave RINGS (distortion, detail) + Noise -> Math -> Color Ramp -> Base Color and Roughness; the same chain -> Bump |
| `prod_marble` | sphere | Noise -> Vector Math (Scale, Add) warp -> Mapping AFTER the warp -> Wave BANDS/SAW -> 4-stop Color Ramp |
| `prod_pbr_group` | sphere | Node group (Tiling input -> Combine XYZ -> Mapping Scale) with 4 packed images (base sRGB; roughness, metallic, tangent normal Non-Color), Normal Map -> Bump chained, Principled |
| `prod_shader_stack` | sphere | Add Shader( Mix( Mix(Principled metal, Principled paint, Noise), Glass, Noise -> Color Ramp ), Emission ): three shader levels |
| `prod_attributes` | 3 linked-mesh spheres | Color Attribute -> Base Color, custom float Attribute -> Roughness, Object Info Random -> Map Range -> Hue/Saturation |
| `prod_light_path` | glass ball, hidden emitter, post, floor | Is Camera Ray hides an emitter from the camera; Is Shadow Ray makes glass shadow-transparent; Ray Length -> Color Ramp tints the floor |
| `prod_curves_geometry` | bumpy open bowl | Noise -> Float Curve -> Map Range -> Math POWER -> Roughness; Noise Color -> RGB Curves; Geometry Backfacing and Pointiness -> Mix (RGBA) |

Each scene has 4-5 ROIs (`manifest.json` `crops`, projected from world points through the scene camera).

## Assets and licences

* HDRI: `benchmarks/reference_corpus/assets/syferfontein_18d_clear_1k.hdr`, Poly Haven, CC0 1.0,
  <https://polyhaven.com/a/syferfontein_18d_clear> (recorded per scene in `manifest.json` `assets`, SHA-256 pinned).
* Textures (`prod_pbr_group`, and the vertex colour / float attributes of `prod_attributes`): generated procedurally by
  `build_corpus.py` (numpy, no third-party data) and packed into the `.blend`; CC0 (synthetic).

## Rebuild and measure

```powershell
# one Blender process per scene; writes production/prod_<name>.blend + production/manifest.json
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python benchmarks/reference_corpus/build_corpus.py -- --families prod_wood
# Cycles references (production/refs/*.exr) + Astroray CPU (+GPU under the GPU lock) MC bands -> ../gates_production.toml
python benchmarks/reference_corpus/mc_tolerance.py --suite production --seeds 278 1301 2711 4177 6113 --legs cycles cpu --reference --work-dir <dir>
python scripts/build/gpu_locked_run.py <lane> -- python benchmarks/reference_corpus/mc_tolerance.py --suite production --seeds 278 1301 2711 4177 6113 --legs gpu --work-dir <dir>
# exercised (node, socket) pairs, silent-drop audit, contact sheets
blender -b --factory-startup --python benchmarks/reference_corpus/silent_drop_audit.py -- collect
python benchmarks/reference_corpus/silent_drop_audit.py audit --work-dir <dir>
python benchmarks/reference_corpus/report_tools.py production --work-dir <dir> --out-dir test_results/_runs/textures-nodes/production-corpus
```

Both Astroray legs need an addon build that loads inside Blender (`ASTRORAY_PYD_DIR`).

**Rebuilds are structurally identical, not byte-identical.** Blender 5.2 writes zstd-compressed `.blend` files whose
bytes change between two builds of the same script (checked on `v2_textures_opvm` and `prod_car_paint`), so the
manifest SHA-256 pins the committed file (`scene_library.load_corpus_manifest` fails closed on a mismatch) and
`tests/test_production_corpus.py::test_rebuild_is_structurally_identical` compares a fresh build's ROIs, node ids
and object census with the manifest.

## Bands and gate

`../gates_production.toml` is generated (never hand-typed). Rows that fail are strict xfails in
`../provisional_production.toml`, each tied to a GitHub issue; the fixing PR removes the row. A material PASSES on a
backend when every non-excluded ROI channel is inside its band AND the silent-drop list is empty
(`silent_drop_audit.py`, rules in its docstring).
