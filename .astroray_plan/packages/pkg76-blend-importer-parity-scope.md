# pkg76 — Astroray `.blend` Importer (Parity Scope)

**Pillar:** 5
**Track:** A
**Status:** done (PR #240, 2026-05-10 — SDNA-walking offline reader, no `bpy` runtime; CSV row population on Classroom/Junkshop/BMW27 deferred as a separate ½-day RTX session under §3 of NEXT_STAGE_REPORT.md)
**Estimated effort:** 1–2 weeks (~30–45 h, multi-session)
**Depends on:** pkg71 (the harness consumer; landed in PR #218)

---

## Goal

**Before:** pkg71's first canonical baseline (PR #218) lands clean
Cornell parity numbers — Astroray-CPU SSIM 0.9536, Astroray-GPU
SSIM 0.9548 vs Cycles-CPU EXR — but every non-Cornell row in
`benchmarks/cycles-parity/2026-05-10-hendrik-desktop-amd64-family-25-model-97-stepping-2-authenticamd-4fa95be.md`
reads `skip: astroray_blend_import_not_implemented`. Astroray has
no offline `.blend` reader, so the harness can only compare on
scenes both engines build natively from a Python scene-spec.
"Astroray matches Cycles" is therefore an unfounded claim outside
Cornell.

**After:** A small Python `.blend` reader that walks the SDNA
self-description, extracts a parity-scope subset (camera, mesh,
material base colour, light, world colour) and emits an Astroray
scene via the existing Renderer Python API. The pkg71 harness
calls it for every Astroray-engine row whose source is a `.blend`,
and the next baseline run produces real, non-skip Astroray-CPU and
Astroray-GPU rows for **Classroom, Junkshop, and BMW27**, with
SSIM ≥ 0.85 vs the Cycles-CPU EXR reference. (See §4 for the
Monster decision.)

The scope is *parity for pkg71*, not a Blender compatibility
layer. Future packages can extend.

---

## Context

pkg71 is the only thing standing between Astroray and a publishable
parity number on more than a single Cornell box. Without offline
`.blend` import, every CC-0/CC-BY demo scene in the manifest
remains a one-engine row. The blocker is small, well-bounded, and
solvable by reading a self-describing format — no rendering
research, no GPU work. This package belongs in track A only because
it unblocks the parity story; the work itself is unglamorous file
parsing.

The Blender source (`source/blender/blenkernel/intern/`) is the
authoritative reference but is GPL-2.0-or-later and cannot be
mirrored into MIT-licensed Astroray. The `.blend` format is
self-describing through its embedded SDNA (Structure DNA), which
means a parser written from the published format spec — not from
Blender source — stays small (a few hundred lines) and license-clean.

---

## Reference

- Research notes: [`.astroray_plan/docs/blend-importer-research.md`](.astroray_plan/docs/blend-importer-research.md)
  (created in this commit, contains format-summary tables, license
  verdicts, and the Monster decision rationale).
- Format spec (re-fetch in browser if 403 from `WebFetch`):
  - `https://wiki.blender.org/wiki/Source/File_Format` — official.
  - `https://www.atmind.nl/blender/mystery_ot_blend.html` —
    community walkthrough of block addressing.
- Authoritative reader (read-only, GPL-2.0-or-later, **do not
  mirror**): `blender/blender` `source/blender/blenkernel/intern/`,
  in particular `readfile.c` for the SDNA + block-walk semantics.
- Candidate mirrorable readers (license **must be confirmed at
  port time**, brief described both as BSD-3 but auto-fetch failed):
  - `https://github.com/JTraversa/Blender-File-Reader`
  - `https://pypi.org/project/blend2json/`
- pkg71 baseline that motivates this package:
  `benchmarks/cycles-parity/2026-05-10-hendrik-desktop-amd64-family-25-model-97-stepping-2-authenticamd-4fa95be.md`.
- pkg71 manifest: `benchmarks/cycles-parity/scenes/manifest.toml`.

---

## Reference Implementations

Per CLAUDE.md §6 and the pkg71 precedent ("Cite, Borrow, Verify"),
the table below records what we may and may not draw from. License
fields are the authors' claims as of 2026-05-10; **the implementer
re-confirms each LICENSE file before pasting any line of code**.

| Repo | Commit/version | License | Mirror? | Files to study | What to mirror | What NOT to mirror |
|---|---|---|---|---|---|---|
| `blender/blender` (`source/blender/blenkernel/intern/readfile.c`, `dna_genfile.c`) | record SHA in source header at port time | **GPL-2.0-or-later** | **No** | SDNA decoder, block-walk loop, pointer-resolve dictionary | nothing (algorithm understanding only) | any code lines, comments, struct names that came from the file verbatim |
| `JTraversa/Blender-File-Reader` | record SHA at port time | brief: BSD-3 — **VERIFY before mirroring** | conditional: yes if BSD-3 confirmed, with attribution | overall reader entry point, SDNA struct table walk | small helpers (header decode, name parser, block iterator) cited per-function | engine-specific render code if present (none expected; this is a reader-only repo) |
| `blend2json` (PyPI) | record version at port time | brief: BSD-3 — **VERIFY before mirroring** | conditional: yes if BSD-3 confirmed, with attribution | which fields it surfaces for camera/mesh/material/light/world | the field-selection list (use as a checklist for our parity subset) | any code we cannot license-clear |
| Blender format spec (wiki + atmind) | URL + fetch date | docs (no code license) | n/a | header layout, block header, SDNA1 sub-records | our parser is written *from* this spec | n/a |
| `BlendLuxCore` `export/` (Python) | n/a | **GPL-3.0** — incompatible with MIT | **No** | how a third-party engine consumes `bpy` data structurally | nothing | anything |

If both candidate Python readers turn out to be unsuitable (no
LICENSE, GPL, or otherwise restrictive), the parser is written
from the format spec alone in ~600 LOC. The format spec is the
canonical reference and is licence-neutral as documentation.

Cite the source in the file header of every adapted module:
```python
# Adapted from JTraversa/Blender-File-Reader@<SHA> — BSD-3, see THIRD_PARTY/Blender-File-Reader-LICENSE
# .blend format reference: https://wiki.blender.org/wiki/Source/File_Format
```

---

## Specification

### Strategy — Python, not C++

The reader is **Python**, not C++. Cycles uses C++ because it lives
inside the Blender process and needs to consume `bpy` struct
pointers in-memory. Astroray reads the file offline; there is
nothing about the parsing work that benefits from being native, and
the existing addon-shaped Python scene builder is already the path
that constructs Astroray scenes from a `.blend` (via `bpy`). pkg76
mirrors that builder's output API, but driven from raw file bytes.

This avoids: ABI churn against `bpy`, MinGW C++ struct-by-value
issues (per `mingw_large_struct_byval` memory), and the need for a
new build target.

### File parser

A four-pass design:

1. **Decompress** if needed (Zstd for Blender 3.0+, gzip for
   pre-3.0). Detect by magic bytes; fall through to raw if
   neither.
2. **Header decode** — read the 12-byte header, latch
   pointer-size and endianness for the rest of the read.
3. **First block-pass** — scan every block header (code, size,
   `old`, SDNA index, count), build a dict `old → (offset, code,
   sdna_index, count)`. When we hit `DNA1`, decode SDNA into
   `(name_table, type_table, type_size_table, struct_table)`.
   Stop at `ENDB`.
4. **Typed read pass** — starting from `GLOB`, follow pointers
   through `Scene → camera`, `Scene → master_collection →
   children → objects` (or legacy `Scene → base → object` chain
   on older files), and per-`Object` follow `Object.data` to
   `Mesh` / `Camera` / `Light`. Each typed read is driven by the
   SDNA struct descriptor — there are **zero hardcoded C struct
   layouts** in our code.

### Minimum field set (parity scope only)

| Datablock | Field | Purpose | Out of scope |
|---|---|---|---|
| `bCamera` | `lens`, `sensor_x`, `sensor_y`, `sensor_fit`, `clipsta`, `clipend`, `type` | perspective camera | `CAM_PANO` (skip with warning), DOF, shift |
| `Object` | `loc[3]`, `rot[3]` (or `obmat[4][4]` if present), `size[3]`, `data` ptr, `type` | transform + datablock dispatch | constraints, parents, drivers, modifiers |
| `Mesh` (legacy ≤3.5) | `mvert[].co`, `mpoly[].loopstart`+`totloop`+`mat_nr`, `mloop[].v` | tris/quads + per-face material index | UVs (pkg59 territory), normals (pkg61) |
| `Mesh` (≥3.6 attribute layout) | `position` attribute, `face_offset_indices`, `corner_verts`, `material_index` attribute | same as above on the new layout | same |
| `Material` | `use_nodes`; if false: `r,g,b,metallic,roughness`; if true: walk `nodetree` for active output → `ShaderNodeBsdfPrincipled.Base Color` (default value only) **or** `ShaderNodeBsdfDiffuse.Color` | base colour for parity SSIM | full shader graph (use pkg57 nodes manually for full fidelity) |
| `Light` (Lamp) | `type` (LA_LOCAL/LA_SUN/LA_SPOT — area lights conditional on Astroray support), `r,g,b`, `energy` | point/sun/spot lights | LA_AREA shape parameters, IES files, light linking |
| `World` | `use_nodes`; if false: `horr,horg,horb`; if true: walk `nodetree` for `ShaderNodeBackground` Color + Strength defaults | background colour | HDRI / image-texture-driven worlds (out of scope; document) |

Anything else encountered emits a one-line warning to the import
log and is silently skipped — the reader **never aborts** an
import on an unrecognised feature; it degrades to "rendered with
parity-scope fidelity."

### Output — Python builder script

`tools/blend_import/blend_to_astroray.py` (or wherever the existing
Astroray Python API conventionally lives — confirm at implement
time). Public surface:

```python
def import_blend(path: pathlib.Path,
                 *,
                 strict: bool = False) -> astroray.Scene:
    """Build an Astroray scene from a .blend file at *path*.

    Parameters
    ----------
    path
        Path to a .blend file (compressed or uncompressed).
    strict
        If True, raise on any parity-scope-unsupported feature
        instead of warning. The pkg71 harness passes False.
    """
```

The output is the same `astroray.Scene` object the Cornell scenes
already construct, so the renderer pipeline downstream is unchanged.

### Wiring into pkg71

The harness gains one branch in its scene-prep step: if
`scene.source.endswith(".blend")` and `engine.startswith("astroray")`,
call `import_blend(path)` and feed the result to the existing
Astroray run path. The `astroray_blend_import_not_implemented`
skip reason is removed; replaced (where parity-scope import does
emit warnings) with a per-row warning count column in the CSV.

The harness change is intentionally tiny — 5–10 lines, no
restructuring of pkg71's runner.

### Files to create / modify

| File | What |
|---|---|
| `tools/blend_import/__init__.py` | package marker |
| `tools/blend_import/sdna.py` | SDNA decoder (header, type/name/struct tables) |
| `tools/blend_import/reader.py` | block walk + pointer resolution |
| `tools/blend_import/scene_builder.py` | typed reads → `astroray.Scene` |
| `tools/blend_import/blend_to_astroray.py` | public `import_blend()` entry point |
| `tests/test_blend_import_roundtrip.py` | bpy-authored synthetic `.blend` roundtrip (skip-if-no-bpy) |
| `tests/test_blend_import_format.py` | unit tests for SDNA decode + header decode against a tiny checked-in `.blend` blob |
| `tests/fixtures/synthetic_min.blend` | 1 cube + 1 sun + 1 camera + 1 Principled BSDF, authored by `bpy` once and committed (≪10 KB) |
| `THIRD_PARTY/Blender-File-Reader-LICENSE` | iff we mirror from JTraversa repo and confirm BSD-3 |
| `THIRD_PARTY/blend2json-LICENSE` | iff we mirror from blend2json and confirm BSD-3 |
| `benchmarks/cycles-parity/runner.py` (or harness equivalent) | replace skip stub with `import_blend()` call for `astroray-*` engines on `.blend` sources |
| `benchmarks/cycles-parity/scenes/manifest.toml` | drop `[[scene]] id="monster"` entry (see §4) |
| `.astroray_plan/docs/blend-importer-research.md` | already created in this PR; updated as port-time discoveries land |

Test note: `tests/fixtures/synthetic_min.blend` is generated by a
small `bpy` script (`tests/fixtures/build_synthetic_min.py`) that
the test author runs once outside CI. The script is committed; the
output `.blend` is committed (binary, but ≪10 KB and stable across
re-runs because we set deterministic IDs). CI does not require
`bpy`.

---

## Acceptance

- [ ] Unit tests in `tests/test_blend_import_format.py` decode the
      header, SDNA, and three known struct fields from
      `synthetic_min.blend` with no `bpy` dependency. Green on
      all three platforms in CI.
- [ ] `tests/test_blend_import_roundtrip.py`
      (`pytest.importorskip("bpy")`) builds a fresh scene
      programmatically, saves it to a temp `.blend`, imports it
      with `import_blend()`, and asserts: vert count, face count,
      material count == 1, light count == 1, camera focal length
      within 1e-3, base colour RGB within 1e-3, world colour RGB
      within 1e-3.
- [ ] `pytest -q tests/test_blend_import_*` passes locally on
      Windows MinGW + Linux GCC. (Per `mingw_large_struct_byval`
      memory the parser is pure Python so the toolchain risk is
      nil; this row is a sanity check.)
- [ ] The next pkg71 baseline run on Hendrik's reference machine
      emits **non-skip** Astroray-CPU and Astroray-GPU rows for
      Classroom, Junkshop, and BMW27 (Monster row absent — see §4).
      Each Astroray row records timing, peak RSS, peak VRAM, and
      SSIM ≥ 0.85 vs the Cycles-CPU EXR reference at the manifest
      `reference_spp`. The 0.85 threshold (relaxed from Cornell's
      0.95 gate) accounts for shader-graph and procedural-texture
      fidelity loss in parity-scope import.
- [ ] The pkg71 baseline `.md` summary now contains attribution
      lines for any scene we successfully imported under CC-BY
      (Junkshop, BMW27).
- [ ] Every adapted file has a header citation pointing to either
      the format spec or the third-party repo + commit + license,
      per CLAUDE.md §6.
- [ ] No GPL-licensed code from `blender/blender` or
      `BlendLuxCore` appears anywhere in the diff. Verified by
      visual diff review.

---

## Non-goals

- **Full shader graph import.** Parity scope reads only the Base
  Color of a Principled or Diffuse BSDF, plus the World
  Background colour. Anything else (Mix shaders, ColorRamp,
  procedural textures, Voronoi, Musgrave) is silently degraded to
  the base colour with a warning. Astroray-side complexity is
  pkg57 territory; manual shader authoring on the engine side
  remains the path for full fidelity.
- **Image textures and HDRIs.** Parity scope is procedural only.
  Image paths are read but not loaded; HDRI worlds degrade to the
  Background node's colour default. Future package: `pkgNN-blend-image-import`.
- **Animation, modifiers, particles, hair, volumes.** All out of
  parity scope. The reader does not even visit these blocks.
- **Library-linked `.blend`s.** A non-empty `LI` block fails
  loudly. The four target scenes are self-contained.
- **Round-trip writing.** This is a one-way reader; we never
  write `.blend` files.
- **Camera panoramic / fisheye / equirectangular projections.**
  `CAM_PANO` is skipped with a warning.
- **Area lights** unless Astroray's existing light infrastructure
  already supports them at parity-scope geometry; the importer
  decides at port time and documents the choice.

---

## Monster Scene Decision

Per the pkg71 baseline, `udim-monster.blend` fails inside Cycles
itself with `RuntimeError: Error: Cannot render, no camera`. The
file ships as a paint/UDIM rig, not a render scene.

**pkg76 drops `[[scene]] id = "monster"` from
`benchmarks/cycles-parity/scenes/manifest.toml`.** Justification
(per CLAUDE.md §2 "Simplicity First"): the four-scene set
(Cornell + Classroom + Junkshop + BMW27) already covers
sanity-light-transport, indoor-mixed-lighting, dense-prop, and
HDRI-studio. A "many-materials hero render" replacement scene is
not on the critical path; if anyone wants one, it's a future
package, not a pkg76 sub-task. The pkg71 README is updated in this
PR with a one-line note explaining the drop.

---

## Progress

- [x] Author `tests/fixtures/build_synthetic_min.py`, generate
      `synthetic_min.blend`, commit both.
- [x] Implement `sdna.py` + `reader.py`; pass
      `test_blend_import_format.py` (6/6 green).
- [x] Implement `scene_builder.py` + `blend_to_astroray.py`;
      `test_blend_import_roundtrip.py` exists (skip-if-no-bpy).
- [x] Wire into pkg71 runner; drop monster from manifest.
- [ ] Rerun baseline on reference machine and commit the new
      baseline `.md` — **deferred to a separate run on Hendrik's
      reference machine**; this implementation PR ships only the
      code path. Three new rows (Classroom / Junkshop / BMW27 ×
      astroray-cpu+astroray-gpu) will land via that follow-up.
- [ ] Verify SSIM ≥ 0.85 — same: depends on the reference-machine
      run.

---

## Lessons

- The merged spec was written assuming Blender's legacy 12-byte
  file header and 24-byte block header. Files authored by Blender
  4.0+ use a 17-byte file header (`"BLENDER17-01v0501"`) and a
  32-byte block header with widened `old`/`size` fields and the
  layout `code(4) + sdna_index(u32) + old(u64) + size(u64) +
  count(u32) + _pad(u32)`. The reader detects both variants from
  the file-header bytes. (Verified by computing TEST thumbnail
  payload boundaries land on GLOB exactly.)
- Mesh data in 4.0+ files lives in the new
  `Mesh.attribute_storage` (`AttributeStorage` → `Attribute[]` →
  `AttributeArray.data`), not in the legacy
  `vdata`/`pdata`/`ldata` `CustomData` layers (those persist as
  empty stubs for compat). The importer queries
  `attribute_storage` first and falls back to `CustomData` and
  pre-3.6 `mvert`/`mloop`/`mpoly` arrays.
- The spec's referenced public API is `astroray.Scene`; the actual
  class on this codebase is `astroray.Renderer` (used by the
  addon and the cornell parity script). `import_blend()` returns
  a populated `Renderer` and stashes camera intrinsics on it for
  the harness to call `setup_camera` once it knows the render
  resolution.

### pkg76 CSV Population (2026-05-24, RTX hardware)

Three-scene parity run on astroray-gpu (300 SPP classroom, 240 SPP junkshop, 1024 SPP bmw27):

- **Junkshop: SSIM = 0.972** ✅ (gate: ≥0.85) — full parity-scope import success, 1.44s @ 1085 MB peak.
- **Classroom: SSIM = 0.470** ❌ (gate: ≥0.85) — render completes (0.90s @ 951 MB) but structural divergence vs Cycles-CPU reference suggests material/lighting fidelity loss beyond parity-scope shader-graph limitations. Requires visual diff + importer audit.
- **BMW27: crash** ❌ — all meshes skipped with "no 'poly_offset_indices'" (Blender 4.x attribute-storage variant not fully handled by importer), then `uploadScene()` fails with 0 prims. Requires mesh-attribute fallback path or BMW27-specific format handling.

**Parity script bug fixed:** `scripts/run_parity.py` _ssim() function runs in parent process, not subprocess, so it didn't inherit `OPENCV_IO_ENABLE_OPENEXR=1` from _subprocess_env(). Added `os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')` at top of _ssim() to fix silent EXR read failures.

**CSV:** `benchmarks/cycles-parity/2026-05-24-pkg76-csv-astroray-gpu.csv`

**Acceptance verdict:** 1/3 scenes pass the ≥0.85 gate. Classroom and BMW27 failures are implementation gaps (not environment/toolchain issues), deferred to follow-up pkg76-followup or blend-importer-audit packages.
