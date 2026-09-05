# Blender shader-node / socket coverage re-audit — 2026-09 (pkg229)

Mechanical re-measurement of Astroray's Blender socket-level coverage against
current `main`, the first since pkg119-A (2026-07-19). Regenerated with the
AST-scanning generator (no hand-typed classification tables) run headless in
Blender 5.2. The headline finding is twofold: (1) the shader-node wave
(pkg195 / pkg219* / pkg223*) measurably raised coverage, and (2) the generator's
scanner had a **blind spot** that made that wave invisible — it is fixed here and
the fix is render-verified.

## Reproduce

```powershell
# addon Python source is scanned from the repo (not the staged dist); only a
# loadable OpenMP-off .pyd is needed to import + register.
$env:ASTRORAY_PYD_DIR = "$PWD/dist/astroray"
& "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" `
    --background --factory-startup `
    --python scripts/generate_blender_parity_matrix.py -- --out docs/blender_parity
```

Outputs: `docs/blender_parity/coverage_matrix.json` (committed) + `report.md`.

## Headline numbers

| Metric | 2026-07-19 (pkg119-A) | 2026-09 (this re-audit) | Δ |
|---|---|---|---|
| SUPPORTED | 131 | **152** | **+21** |
| APPROXIMATED | 23 | **35** | +12 |
| DROPPED-SILENT | 370 | **340** | **−30** |
| stale sockets | 20 | **9** | −11 |
| TOTAL sockets | 524 | 527 | +3 (Blender 5.2 API) |

Net: **+33 sockets now SUPPORTED-or-APPROXIMATED (154 → 187)**, DROPPED-SILENT
down 30, and latent stale-socket bugs more than halved. Coverage moved the right
direction — the shader-node wave paid off. (The owner's 2026-08-29 figure of
117/22/385 was itself below pkg119-A because it predated no code change; it is
superseded by this mechanical re-measure.)

## The scanner blind spot (methodological finding — fixed)

A naive re-run of the *unmodified* generator reported **104 SUPPORTED / 388
DROPPED-SILENT** — i.e. coverage apparently *fell* after a wave that added
coverage. That was wrong, and diagnostic:

- The generator classifies a node by AST-scanning `convert_shader_node` (and a
  fixed list of sibling functions) in `blender_addon/__init__.py` for
  `ntype == 'X'` dispatch + the sockets read inside each block.
- The **pkg219 op-VM** moved most value/color/vector node translation out of that
  path into a data-driven compiler, `blender_addon/shader_vm_compiler.py`
  (`compile_socket`, invoked via `_maybe_build_program_texture` →
  `create_program_texture`). The scanner **never opened that file**, and the
  vector/normal/mapping resolvers (`_resolve_vector_input`,
  `_resolve_mapping_matrix`, `get_normal_inputs`, `get_color_or_texture`) are not
  in its function list. So the *entire* op-VM wave (Math, Mix, Color Ramp, Map
  Range, Mapping, Normal Map, Bump, coordinate/UV nodes, …) read as
  DROPPED-SILENT — a measurement artifact, not a regression.

**Fix** (`scripts/generate_blender_parity_matrix.py`, this PR): a second AST
evidence source, `scan_vm_and_vector_supported_types()`, extracts the same
`ntype == 'X'` / `type in (...)` literals from `compile_socket` and the four
resolver functions. These handlers compile the *whole* node (all value inputs),
so a matched type credits every live input socket. Still pure AST extraction — no
hand-typed tables. It credited **20 node types / +48 sockets**: BRIGHTCONTRAST,
BUMP, COMBINE_COLOR, GAMMA, HUE_SAT, INVERT, MAPPING, MAP_RANGE, MATH, MIX,
MIX_RGB, NORMAL_MAP, RGB, RGB_TO_BW, SEPARATE_COLOR, TEX_COORD, TEX_IMAGE, UVMAP,
VALTORGB, VALUE.

**Render-verified, not AST-only** (spec requirement): the op-VM / mapping /
scalar-param path is exercised end-to-end by the pkg219 render suites, re-run
green on current `main`: `test_pkg219a_mapping_render`,
`test_pkg219b_parity_render`, `test_pkg219c_parity_render`,
`test_pkg219d_scalar_param_textures` — **12/12 passed**. These render node chains
per-texel (Color Ramp / Math / Mix / Mapping driving base color & scalar params)
and diff against the constant-fold baseline, so the reclassified sockets
demonstrably render correctly.

## Delta attribution (what closed the gap since 2026-07-19)

| Nodes moved to SUPPORTED/APPROX | Closing package |
|---|---|
| MATH, MIX/MIX_RGB, VALTORGB (Color Ramp), MAP_RANGE, HUE_SAT, INVERT, GAMMA, BRIGHTCONTRAST, SEPARATE/COMBINE_COLOR, RGB_TO_BW, RGB, VALUE | pkg219a/b/c (per-texel op-VM evaluator + opcode fill-out) |
| MAPPING, TEX_COORD, UVMAP (coordinate/Mapping unification) | pkg219a/b |
| roughness / metallic / transmission / IOR scalar param textures | pkg219d |
| NORMAL_MAP (tangent-space normal maps) | pkg223 |
| BUMP | pkg223b |
| BLACKBODY, WAVELENGTH and the spectral node set | pkg195 |
| TEX_NOISE, TEX_VORONOI and procedural-texture inputs | pkg190 / pkg219 op-VM |

## Known residual under-report (documented, not hand-fixed)

`BSDF_HAIR_PRINCIPLED` (20 sockets) still reads DROPPED-SILENT but is actually
**APPROXIMATED**: the addon translates it to the native `principled_hair`
material (pkg225-S5/S6, PRs #682/#683, verified by pkg225's own gates). The
scanner misses it because `_standalone_bsdf_spec` dispatches the type but
delegates the socket reads to a `_hair_shader_spec` helper — a
dispatch-then-delegate pattern the per-socket extractor does not follow
inter-procedurally. Fixing it generically (crediting `_standalone_bsdf_spec`
wholesale) would over-credit the `Normal`/`Weight` sockets of ~10 other
standalone BSDFs, a net accuracy loss, so it is left mechanical and flagged here.
True counts are therefore ~152 SUPPORTED / ~36 APPROXIMATED / ~338 DROPPED once
hair is read as APPROXIMATED.

## Ranked next-wave backlog (frequency-weighted, genuine DROPPED-SILENT)

Ranked by real-world shader-graph usage, not raw socket count. S/M/L =
implementation effort (engine + addon + gate).

| # | Node / sockets | Freq | Dropped detail | Effort |
|---|---|---|---|---|
| 1 | **BSDF_PRINCIPLED** advanced inputs (21) | ★★★ | Subsurface Radius/Scale/IOR/Anisotropy, Coat IOR/Tint, Specular IOR Level/Tint, Anisotropic Rotation, Tangent, Alpha, Thin Wall, Weight, Diffuse Roughness | L (each sub-param needs engine closure support; Alpha/Specular Tint are M) |
| 2 | **VECT_MATH** (Vector Math, 4 inputs + op) | ★★★ | Vector×3, Scale, operation | M — add a vector opcode family to the op-VM alongside MATH |
| 3 | **CLAMP** (Value/Min/Max + type) | ★★★ | Value, Min, Max, clamp_type | S — a single op-VM opcode; trivial semantics |
| 4 | **MATH/MIX post-op props** | ★★★ | MATH.use_clamp, MIX.clamp_factor/clamp_result/factor_mode | S — clamp flag in the existing OP_MATH/OP_MIX |
| 5 | **TEX_SKY** (Nishita/Hosek sky, 14) | ★★ | sky_type, sun_*, turbidity, ozone/aerosol/air density, ground_albedo | L — physical sky model (world lighting; high value for outdoor scenes) |
| 6 | **BSDF_METALLIC** (13) | ★★ | Edge Tint, IOR, Extinction, Anisotropy, Thin Film Thickness/IOR, Normal, Tangent, fresnel_type, distribution | M–L — the new standard metal node; conductor Fresnel + thin film mostly exist in-engine |
| 7 | **VECTOR_ROTATE** (7) | ★★ | Vector, Center, Axis, Angle, Rotation, rotation_type | M — op-VM vector rotate opcode |
| 8 | **MAP_RANGE / TEX_IMAGE props** | ★★ | MAP_RANGE.clamp/interpolation_type; TEX_IMAGE.extension/interpolation/projection | M — mostly sampler/state flags on paths that already read the main input |
| 9 | **DISPLACEMENT** (5) | ★★ | Height, Midlevel, Scale, Normal, space | S if bump-approximated; L for true displacement |
| 10 | **AMBIENT_OCCLUSION** (6) | ★ | Color, Distance, Normal, samples, inside, only_local | L — needs in-shader occlusion ray queries |
| 11 | **SUBSURFACE_SCATTERING** node (9) | ★ | radius, scale, IOR, anisotropy, method | L — random-walk SSS closure |
| 12 | **PRINCIPLED_VOLUME / VOLUME_SCATTER / VOLUME_COEFFICIENTS** | ★ | density, anisotropy, absorption/scatter coeffs | L — volume shader graph (world/object volumes) |
| 13 | **TEX_GABOR** (7) | ★ | new Gabor-noise texture | M — op-VM procedural opcode |
| 14 | **RenderSettings** (17) | ★★ | assorted render-engine props | S–M each; audit which map to existing engine knobs |
| 15 | **VECTOR_DISPLACEMENT / BSDF_TOON / EEVEE_SPECULAR** | ★ | niche closures | M–L; lower priority |

**Recommended next feature wave** (best ROI, mostly op-VM extensions): items 2–4
+ 7 (Vector Math, Clamp, MATH/MIX clamp flags, Vector Rotate) are all small op-VM
opcode additions on an evaluator that already exists — a cluster of ★★★ utilities
for S/M effort. Item 1 (Principled advanced inputs) is the highest-value single
node but L effort spread across several engine closures; worth its own spec that
sequences the sub-params (Alpha and Specular Tint first — cheapest and most-used).

## Non-goals honored

No new socket support implemented (measurement + ranking only); no hand-typed
classification tables added (the scanner change is pure AST extraction of real
dispatch literals); no GPU shade-kernel code touched; Pillar-4 astro sockets out
of scope.
