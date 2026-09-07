You are being consulted as a creative collaborator (one read-only session,
no code execution expected) on a render-engine test-asset design problem for
Astroray, a from-scratch Cycles-compatible path tracer with a Blender addon.
Reply in plain text/Markdown; this is a design brainstorm, not a coding task.

## North star (owner-approved, verbatim excerpt)

Astroray's near-term mission is a production-capable Blender/DCC renderer
with Cycles-compatible behavior where applicable and a fast interactive GPU
viewport. Correctness and visual fidelity outrank performance, while
viewport performance is a co-equal product goal. The eventual destination is
research-grade astrophysical simulation and science visualization, but that
pillar is currently paused — this task is pure Blender/Cycles parity work.

Pillar-4 exit gate (b) — shader-socket coverage: frequency-weighted coverage
over a frozen corpus of ~50 Blender scenes, target >=95% weighted coverage
and zero silent drops in corpus scenes. Gate (c): exactly three pinned
`.blend` scenes must render CPU+GPU with no addon exception and pass a
parity check (mean-ratio +-5%, SSIM >=0.95, scene-specific non-vacuity
checks so a black/missing feature cannot silently pass).

## The problem

Today Astroray silently drops many Cycles shader-node sockets and render
settings (translates them as no-ops with no warning) rather than refusing or
warning. Nobody has a systematic way to see this, because every existing
benchmark/parity/smoke scene was hand-picked ad hoc (a "metal_sweep" scene,
three placeholder-quality parity scenes, a single-sphere-per-feature debug
library). We are designing (not yet building) a small, deliberately
*attractive* corpus of Blender reference scenes — the kind the project owner
would put in the project's README — organized into seven families, each one
required to exercise a specific slice of Blender's feature surface so that
EVERY Cycles feature Astroray is meant to support lives in at least one
scene, and every feature it silently drops gets a "gap card" (and, where
cheap, a visible tell in the render itself — e.g. a broken Sky texture
should show as flat black sky, not just an absent warning).

## Owner's composition rules (apply to every scene)

- Don't put a glass sphere flush on a plane — it obscures the caustic; lift
  it slightly, or move the light, and zoom the camera onto the interesting
  part of the frame.
- Reflection/caustic scenes: shade smooth (jagged low-poly meshes read as a
  mess), camera looking down toward the object, light placed further away
  rather than sitting directly on top of the subject.
- Renders that felt "flat and boring" (an old material contact sheet) were
  explicitly criticized; scenes should have real depth/story, not a flat
  grid of spheres on a grey background.
- A 2x2 AOV-passes contact sheet was explicitly praised ("I really like this
  one") — the owner likes multi-panel comparison shots showing different
  passes/settings of the same subject, and asked for MORE passes (depth,
  sample-count heatmap) next time.
- A denoiser before/after comparison was praised but criticized for being
  low-resolution and using a boring scene — reuse a more interesting hero
  shot next time.
- A convergence-vs-spp graph was criticized because its "reference" was also
  the last sample point in the series, making the curve implausibly smooth
  right up to the point it flattens; use an independent, higher-spp
  reference next time.
- A big HDRI 3-sphere "sunset" render was explicitly loved and should not be
  changed.

## The seven scene families and current feature-row allocation

(Row counts are (category, node-socket-or-prop) triples from Astroray's
generated Cycles coverage matrix, 527 total: 114 SUPPORTED / 50 APPROXIMATED
/ 363 DROPPED-SILENT. "DROPPED-SILENT" = Astroray reads the .blend, does not
error, and silently ignores that socket/prop.)

1. **materials_hall** (166 rows: 10 SUPPORTED / 38 APPROXIMATED / 118
   DROPPED-SILENT) — every BSDF/closure Cycles ships (Diffuse, Glossy,
   Glass, Refraction, Principled incl. 21 advanced sub-inputs like coat/
   sheen/subsurface radius, Metallic, Sheen, Toon, Translucent, Transparent,
   Hair BSDF x2, Subsurface Scattering, Ray Portal, Emission, Holdout,
   Add/Mix Shader, spectral Blackbody/Wavelength, OSL Script). Current plan:
   a single continuous corridor/gallery with one alcove per closure family,
   shot as one wide establishing shot plus per-alcove crops, consistent
   studio lighting so BSDF differences read clearly.

2. **textures_mapping** (222 rows: 69 SUPPORTED / 0 APPROXIMATED / 153
   DROPPED-SILENT, the largest family) — procedural textures (Noise,
   Voronoi, Wave, Magic, Gabor, Checker, Brick, Gradient, White Noise),
   coordinate/mapping nodes (Mapping, TexCoord, UVMap), the converter/utility
   node graph (Math, Vector Math, Map Range, Clamp, Mix, ColorRamp, Curves,
   Combine/Separate), and bump/normal-map/true-displacement. Current plan:
   a "sample wall" of illuminated tiles grouped by sub-family under raking
   light, plus one hero object receiving a composite of several textures for
   the README shot.

3. **lighting_studio** (35 rows: 24 SUPPORTED / 0 APPROXIMATED / 11
   DROPPED-SILENT) — Point/Sun/Spot/Area lights and their props (temperature,
   soft-shadow size, spread, spot cone/blend, area shape), IES photometric
   profiles, light-group output. Current plan: a photography-studio still
   life shot four ways (one per light type), 2x2 contact sheet, one light
   fitted with an IES gobo profile so a dropped IES shows as a plain cone
   instead of the intended pattern.

4. **world_sky** (25 rows: 1 SUPPORTED / 0 APPROXIMATED / 24 DROPPED-SILENT)
   — Sky texture (Nishita/Hosek-Wilkie procedural sky, sun disc, turbidity),
   HDRI environment texture, world Background node, rotation/strength.
   Current plan: an open exterior "observation deck" with a reflective/
   refractive hero object, shown once under a working HDRI and once under
   the (currently unsupported) Sky texture so the drop is a literal black
   sky next to its working HDRI twin.

5. **geometry_zoo** (35 matrix rows here are only the volume-shader nodes —
   0 SUPPORTED / 12 APPROXIMATED / 23 DROPPED-SILENT; instancing, hair-as-
   geometry, modifiers, motion blur and smooth/flat/auto-smooth shading are
   NOT currently tracked by the coverage matrix at all, a scanner gap we're
   flagging separately). Current plan: a "cabinet of curiosities" turntable
   — instanced rock scatter, a hair/fur patch, small backlit volume boxes
   (scatter/absorption/coefficients), a smooth-vs-flat-vs-auto-smooth sphere
   trio, a modifier-applied-vs-not pair.

6. **camera_lens** (12 rows: 6 SUPPORTED / 0 APPROXIMATED / 6 DROPPED-SILENT)
   — focal length, sensor, shift, DoF aperture (fstop/blades/rotation/ratio),
   camera type (perspective/ortho/panoramic), clip start/end. Current plan:
   one room shot from four camera rigs (shallow-DoF portrait with bokeh
   shape, orthographic elevation, panoramic establishing shot, a near/far
   clip demonstration), 2x2 grid.

7. **render_settings** (32 rows: 4 SUPPORTED / 0 APPROXIMATED / 28
   DROPPED-SILENT) — samples, adaptive sampling, seed, film exposure/
   transparency, filter width, per-bounce-type depth limits, caustics
   toggles, denoiser, AOV/Cryptomatte/Freestyle output nodes. Current plan:
   not a geometric scene but a settings matrix over one fixed hero shot —
   convergence strip (independent high-spp reference this time), adaptive
   on/off, denoise before/after, film-transparent alpha checker, per-bounce-
   type isolation, a sample-count-heatmap AOV panel, a blank AOV pass next
   to a working depth pass to make the AOV-node drop visible.

## What we want from you

1. **Creative scene concepts per family** that are simultaneously beautiful
   (README-worthy, a story or a place, not a grid of spheres) and rigorous
   (every listed feature genuinely gets exercised, not just implied). Feel
   free to propose a materially different concept for a family if ours is
   weak — we will weigh it, not rubber-stamp it.
2. **Features we may have overlooked** — re-read the family feature lists
   above; is anything mis-scoped, missing an obvious sub-case, or would be
   much better demonstrated in a different family than we put it in?
3. **Ways to make silent drops visible in the rendered image itself** beyond
   the two examples above (black sky, plain cone instead of IES gobo) — the
   goal is a viewer glancing at the render can spot a regression without
   reading a manifest.
4. **A critique of our family-to-feature allocation** — anything that should
   move families, be merged, or split into a phase-2 addition.

Keep it concrete and scene-specific; we have limited render budget so please
bias toward ideas that reuse geometry/lighting across a family's tiles
rather than proposing N unrelated one-off scenes. This is Phase 0 design
only — no scenes will be built from this conversation directly.
