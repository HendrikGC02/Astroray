# Blender `.blend` Importer Research — Astroray pkg76

**Date:** 2026-05-10
**Scope:** External (non-`bpy`) reader for `.blend` files, sufficient
to drive the pkg71 Cycles-parity benchmark on Classroom, Junkshop,
BMW27 (and any future demo scene that ships only as `.blend`).
This is **parity scope** — not a general Blender compatibility layer.

---

## 1. Problem Statement (from pkg71 baseline)

The first pkg71 baseline run
(`benchmarks/cycles-parity/2026-05-10-hendrik-desktop-amd64-family-25-model-97-stepping-2-authenticamd-4fa95be.md`)
emitted clean Cycles rows for all five scenes but skipped
Astroray-CPU and Astroray-GPU on every `.blend` source with:

```
skip: astroray_blend_import_not_implemented
```

Cornell parity landed (Astroray-CPU SSIM 0.9536, Astroray-GPU SSIM
0.9548 vs Cycles-CPU EXR) because Cornell is built natively by both
engines from a Python scene description. Astroray today has no
external `.blend` reader; the in-Blender addon path translates
through the live `bpy` data API at viewport time, which is not
reachable from a CLI process. To fill the four missing rows the
benchmark needs an offline `.blend` → Astroray-scene importer.

Monster (`UDIM_monster/udim-monster.blend`) failed differently —
Cycles itself errored with `RuntimeError: Error: Cannot render, no
camera` for both CPU and CUDA rows. The file ships as a
texture-paint UDIM rig without a camera object. pkg76 must decide
whether to fix or drop it (see §5).

---

## 2. The `.blend` File Format — Summary

The file format is self-describing through a Structure DNA (SDNA)
block, which means a parser that reads the SDNA can walk every
typed block in the file without any hardcoded struct layouts. This
is the property that makes a parity-scope reader feasible in a few
hundred lines of Python rather than tens of thousands of lines of
C++.

**Canonical references (fetched 2026-05-10):**

| Source | Fetch result | Notes |
|---|---|---|
| `https://wiki.blender.org/wiki/Source/File_Format` | **HTTP 403** at fetch time | Implementer must retry or use an authenticated browser. Format described below from prior published descriptions. |
| `https://www.atmind.nl/blender/mystery_ot_blend.html` | **Reachable but body trimmed**; only title returned by harness | Implementer should re-fetch in a browser. Useful as a beginner walkthrough of block addressing and pointer resolution. |
| `https://github.com/blender/blender` (`source/blender/blenkernel/intern/`) | n/a (no fetch needed; license-fenced) | **GPL-2.0-or-later. Read for understanding, do NOT mirror code.** Authoritative reference for SDNA semantics. |
| `https://github.com/JTraversa/Blender-File-Reader` | License could not be auto-fetched (404 on raw paths tried) | Repo exists; the implementer **MUST visually confirm the LICENSE file at port time**. The brief instructed "BSD-3" — verify before mirroring. If no LICENSE is present, do not mirror. |
| `https://pypi.org/project/blend2json/` | Could not auto-confirm license | Same as above — **verify LICENSE at port time**. |

> **License-fence rule for pkg76:** No code is copied into Astroray
> until the implementer has the LICENSE file open in front of them
> and has confirmed it is one of: MIT, BSD-2/3, Apache-2.0, MPL-2.0,
> public-domain, or unlicense (CC0). Anything else — including
> "no LICENSE file present" — is treated as "all rights reserved"
> and the algorithm is re-implemented from the published format
> description, citing the format spec rather than the third-party
> code.

### 2.1 File header (12 bytes)

| Offset | Bytes | Field | Values |
|---|---|---|---|
| 0  | 7 | Magic | ASCII `BLENDER` |
| 7  | 1 | Pointer size | `_` = 4-byte pointers, `-` = 8-byte pointers |
| 8  | 1 | Endianness | `v` = little-endian, `V` = big-endian |
| 9  | 3 | Version | ASCII digits, e.g. `403` for Blender 4.3 |

Modern `.blend` files (Blender 3.0+) are wrapped in a Zstandard
stream; pre-3.0 files used gzip. The first 4 bytes of the raw file
distinguish them: `0x28 0xB5 0x2F 0xFD` for zstd, `0x1F 0x8B` for
gzip, otherwise treat as uncompressed. The reader must transparently
decompress before applying the table above.

### 2.2 File-block header

Every block after the file header begins with a fixed-layout
header, then `size` bytes of payload:

| Field | Type | Notes |
|---|---|---|
| `code` | char[4] | Block code, see §2.4 |
| `size` | uint32 | Payload size |
| `old`  | pointer | Original in-memory address, used as the pointer key |
| `SDNAnr` | uint32 | Index into the SDNA struct table |
| `count` | uint32 | Number of struct instances in payload |

`old` is the lookup key: every pointer in the file is the address
the data had when Blender wrote it, so resolving a pointer means
finding the block whose `old == ptr`. Build an `old → block` dict
during the first pass and the rest of parsing is straight
struct-decode.

### 2.3 SDNA1 block

Exactly one block has code `DNA1`. Its payload is a fixed sequence
of sub-records:

| Magic | Contents |
|---|---|
| `SDNA` | header magic |
| `NAME` | field-name list. Names embed type modifiers: `*foo`, `**bar`, `verts[3]`, `(*func)()`. Parse them — they are how arrays and pointer levels are recovered. |
| `TYPE` | type-name list (e.g. `Camera`, `Mesh`, `MPoly`, `float`). |
| `TLEN` | uint16 size of each type. |
| `STRC` | struct descriptors: `(type_index, n_fields, [(type_index, name_index)] * n_fields)`. |

`SDNAnr` from a block header indexes `STRC`. Combined with `TLEN`
and `NAME` parsing, every typed block is fully decodable without
hardcoding any C struct definitions. **This is the key invariant
that keeps the parser version-portable.**

### 2.4 Block codes touched by parity scope

| Code | Struct (typical) | Why pkg76 cares |
|---|---|---|
| `GLOB` | FileGlobal | points to the active scene |
| `SC`   | Scene | points to camera, world, master collection |
| `OB`   | Object | transform + pointer to data block (mesh / camera / lamp) |
| `ME`   | Mesh | vertices, faces, per-face material index |
| `CA`   | Camera | focal length, sensor size |
| `LA`   | Lamp / Light | type, color, energy |
| `MA`   | Material | (legacy r,g,b OR pointer to nodetree) |
| `WO`   | World | (legacy horr,horg,horb OR pointer to nodetree) |
| `NT`   | bNodeTree | shader graph; only walked far enough to find Principled/Diffuse base color and Background color/strength |
| `DATA` | inline child arrays (MVert, MPoly, MLoop, position attribute, corner_verts, custom-data layers) — addressed via parent pointers |
| `ENDB` | (none) | end-of-file sentinel |

### 2.5 Mesh-storage compatibility note

Mesh storage rewrote in Blender 3.6+: the legacy `MVert.co` /
`MPoly` / `MLoop` arrays were deprecated in favour of
attribute-based storage on a generic `CustomData` layer system
(`position` attribute for verts, `face_offset_indices` +
`corner_verts` for faces, `material_index` as a face-domain
attribute). pkg71's target scenes (Classroom 2017, Junkshop 2020,
BMW27 2014) were authored against the legacy layout and re-saved
with current Blender. The importer must read **both layouts**, but
should prefer the attribute-based one when both are present (the
legacy fields are no longer updated on save in 4.x).

### 2.6 Camera, Light, Material fields

- **Camera** (`bCamera`): `lens` (mm focal length, only when
  `type == CAM_PERSP`), `sensor_x`, `sensor_y`, `sensor_fit`,
  `clipsta`, `clipend`, `type` (`CAM_PERSP`=0, `CAM_ORTHO`=1,
  `CAM_PANO`=2). Panoramic is out of scope; reject and skip.
- **Light** (`Light` / `Lamp`): `type` (`LA_LOCAL`=0 point,
  `LA_SUN`=1, `LA_SPOT`=2, `LA_AREA`=4 — area lights are out of
  parity scope unless the harness already supports them; check
  before importing), `r`, `g`, `b`, `energy`.
- **Material** (`Material`): `use_nodes` flag — if false, fall back
  to legacy `r`/`g`/`b`/`metallic`/`roughness`. If true, walk
  `nodetree` for the active output's surface input, expect
  `ShaderNodeBsdfPrincipled` (read `Base Color` socket default) or
  `ShaderNodeBsdfDiffuse` (read `Color` socket default). Anything
  else: emit a warning, fall back to mid-grey, **continue** (parity
  scope, not perfection).
- **World** (`World`): same pattern — `use_nodes` false →
  `horr`/`horg`/`horb`; true → walk for `ShaderNodeBackground`'s
  Color and Strength defaults. HDRI image textures are out of
  scope (see §5 of the spec).

---

## 3. Reference Implementations Survey

| Repo | License (verify at port time) | Mirror? | Use |
|---|---|---|---|
| `blender/blender` `source/blender/blenkernel/intern/` | GPL-2.0-or-later | **No** | Authoritative for SDNA + struct semantics; read for understanding. |
| `JTraversa/Blender-File-Reader` | brief said BSD-3 — **unverified at fetch time** | If LICENSE confirmed BSD-3 at port time: yes, with attribution in source headers | Reference Python reader; mine for SDNA-walk pattern. |
| `blend2json` (PyPI) | brief said BSD-3 — **unverified at fetch time** | If LICENSE confirmed BSD-3 at port time: yes, with attribution | Reference for which fields matter for an offline render-spec dump. |
| `mont29/blendfile` (older Python reader, sometimes vendored elsewhere) | check at port time | maybe | Backup if the two above are unsuitable. |

If neither mirrorable reader is available, the parser is small
enough — header + block walk + SDNA decoder + a handful of typed
field reads — to be re-implemented from the format spec alone in
under ~600 LOC. Cite the format spec URL in the source header.

---

## 4. Validation Strategy

The reader is data-driven; the test that proves it works is a
roundtrip on a synthetic `.blend` we author with `bpy` at
test-collection time:

1. With `bpy` available (`pytest.importorskip("bpy")`), build a
   trivial scene: one Cube mesh, one Sun light, one Camera, a
   Principled BSDF with a known base colour, and a known World
   background colour.
2. Save to a temp `.blend`.
3. Run the new importer on that file.
4. Assert: vert count, face count, material count, light count,
   camera focal length, base colour RGB, world colour RGB all
   match the values used to author the scene.

This is the only acceptance test that does not depend on the full
pkg71 harness. The integration test is "the next pkg71 baseline
emits non-skip Astroray rows for the four `.blend` scenes."

---

## 5. Monster Scene Decision

The pkg71 baseline shows `udim-monster.blend` failing inside
**Cycles itself** with "no camera." This is a property of the
asset, not a bug in our harness. Three options:

1. **Drop Monster from pkg71's manifest.** Smallest change.
   Justification: Monster as shipped is a paint/texturing rig, not
   a render scene. Replacement coverage (many materials, hero
   render) is already provided by Junkshop.
2. Find a different "Monster"-class CC-0 scene (e.g. one of the
   Blender Studio short-film stills). Adds work to pkg76 and
   delays the parity baseline.
3. Inject a camera into the file at fetch time. Brittle and breaks
   the SHA-256 manifest gate.

**pkg76 chooses option 1.** Per CLAUDE.md §2 ("Simplicity First")
the four-scene set (Cornell + Classroom + Junkshop + BMW27)
already covers indoor-lighting, dense-prop, and HDRI cases.
Replacement Monster is a future package if anyone asks for it.

---

## 6. What this Document Does NOT Cover

- Animation (`Action`, `FCurve`), modifiers (`Modifier`), particle
  systems, hair, volumes, fluid sims. All out of pkg76 scope.
- Image textures and HDRIs (`Image`, `ImBuf`, packed pixel data).
  The `.blend` may embed images; the parity-scope importer reads
  the path string only and emits a warning if a node references
  one.
- The full shader graph. pkg57 already gives Astroray a node-based
  shader stack on the engine side; that is the place to extend
  shader fidelity, not in `.blend` import.
- Library linking (`Library` blocks pointing at other `.blend`s).
  The four target scenes are self-contained; the importer can fail
  loudly on a non-empty `LI` block.
