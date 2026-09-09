# pkg259 Phase 2 — IES LM-63 file-format research note

**Why this note exists (CLAUDE.md Sec 6):** `lighting_studio`'s spot fixture
needs a real IES photometric profile (design doc Sec 1.3: an asymmetric
wall-washer / multi-lobed distribution, "not an arbitrary projected image").
The design doc (Sec 3.2) already decided to *synthesize* the profile in code
rather than source an external file (no licence question, matches "procedural
builders over hand-authored files"). This is a file-FORMAT lookup (IESNA
LM-63-2002 is a public ANSI/IES standard, not a proprietary or patented
algorithm), not an invented physical/sampling algorithm — Blender's own Cycles
does the photometric-grid interpolation at render time. Documented here per
CLAUDE.md Sec 6's "when in doubt, treat as non-trivial" so the format's
provenance and the synthetic-data disclosure are on record before code lands.

## Format structure (IESNA LM-63-2002)

Sources: [rastro.ai — IES File Format: Every Line Explained (LM-63-2002)](https://www.rastro.ai/resources/glossary/ies-file-format-every-line-explained-lm-63-2002),
[ANSI Blog — IES Standard File Format for Photometric Data](https://blog.ansi.org/ansi/standard-file-photometric-data-ies-lm-63-19/),
[AGi32 — IESNA LM-63 Format](https://docs.agi32.com/PhotometricToolbox/Content/Open_Tool/iesna_lm-63_format.htm).

Plain-ASCII, CRLF or LF line-terminated, each line < 132 chars:

1. `IESNA:LM-63-2002` (version line).
2. Zero or more `[KEYWORD] value` metadata lines (`[TEST]`, `[MANUFAC]`, ...).
3. `TILT=NONE` (no tilt data — the synthetic fixture has none).
4. Photometric parameter line, 10 whitespace-separated fields:
   `num_lamps lumens_per_lamp multiplier num_vertical_angles
   num_horizontal_angles photometric_type units_type width length height`.
   `lumens_per_lamp = -1` means "absolute photometry" (candela values taken
   at face value, not lumen-normalized) — the convention this synthetic
   profile uses.
5. Ballast line, 3 fields: `ballast_factor ballast_lamp_factor input_watts`.
6. Vertical angles line: `num_vertical_angles` values, degrees, ascending.
7. Horizontal angles line: `num_horizontal_angles` values, degrees, ascending.
8. Candela matrix: `num_horizontal_angles` rows of `num_vertical_angles`
   values each (one row per horizontal/azimuth plane, values across the
   vertical angles in that plane) — this is the layout Blender's IES
   importer (`node_shader_tex_ies.cc` / `ies_file.cc` upstream) expects.

## Synthetic profile used by `build_corpus.py`

`_ies_wall_washer_lm63()` (pure string function, no `bpy`) generates:
- 19 vertical angles, 0-180 deg in 10 deg steps (a wall-washer throws light
  well past nadir, unlike a downlight's typical 0-90 range).
- 8 horizontal angles, 0-315 deg in 45 deg steps.
- Candela = `BASE * vertical_lobe(v) * azimuth_lobe(h)`, where
  `vertical_lobe` is a Gaussian bump centred off-nadir (peak ~65 deg, the
  "aimed sideways at a wall" shape) and `azimuth_lobe` is a two-term cosine
  series with unequal amplitude/phase so the horizontal distribution is
  visibly asymmetric and multi-lobed (a strong lobe one direction, a weaker
  secondary lobe elsewhere) rather than a symmetric cone.

**This is a synthetic distribution built for visual/coverage purposes, not a
measurement of any real fixture** — no photometric claim is made about it
matching a manufactured luminaire; it only needs to (a) parse as a valid
LM-63 file Blender's `ShaderNodeTexIES` accepts and (b) look visibly
asymmetric/multi-lobed on the studio backdrop so a dropped `TEX_IES` (plain
uniform cone) is an obvious, correctly-attributed visual tell next to its
three sibling lights.

## Delivery choice: internal Text data-block, not an external `.ies` file

`ShaderNodeTexIES.mode` defaults to `INTERNAL` (`.ies` points at a `bpy.types.Text`
data-block embedded in the `.blend`); `EXTERNAL` mode uses `.filepath` to an
on-disk file instead
([Blender Python API — bpy.types.ShaderNodeTexIES](https://docs.blender.org/api/current/bpy.types.ShaderNodeTexIES.html)).
This corpus uses `INTERNAL` mode: `build_corpus.py` creates the Text
data-block (`bpy.data.texts.new(...)`, `.write(_ies_wall_washer_lm63())`) and
hands it to `scene_library.build_lighting_studio_scene`, which assigns it to
the node's `.ies` property. This keeps the `.blend` fully self-contained (no
external asset file, no relative-path bookkeeping like the HDRI needs) and
matches the design doc's "no external downloads" preference even more
directly than an external `.ies` file would have.
