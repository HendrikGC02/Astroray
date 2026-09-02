# pkg180 — systemic Cycles-vs-Astroray dim: diagnosis note

**Owner:** Claude (last-line). **Charter:** diagnosis-first — localize the
~12–20% Astroray-dimmer-than-Cycles offset to a mechanism before ANY fix; a
uniform brightness multiply is forbidden (CLAUDE.md §6).

**Build under test:** engine `.pyd` in `build_blender_addon_cuda` (OpenMP-OFF,
addon build — required so MinGW libgomp doesn't deadlock headless Blender,
memory `mingw_openmp_blender_deadlock`). Diffuse/world transport is unchanged
since the 08-31 addon build (subsequent merges pkg131/208/209/212/218/225 do
not touch the diffuse-albedo or world-emission energy path), so it is
representative for a uniform-ratio diagnosis. Oracle: Blender 5.2 Cycles.

---

## Phase 1 — comparison-methodology audit (leg-by-leg)

### 1. View transform / color management — **RULED OUT (clean)**

The prime suspect (memory `gamma-vs-linear-comparison-artifact`) is that the
harness compares Cycles' *view-transformed* output against Astroray's *linear*
output. Audited the pkg119-B differential harness leg
(`benchmarks/blender_parity/render_leg.py`):

- `_configure_render` (`render_leg.py:76-81`) sets, for **both** engine legs:
  `view_settings.view_transform = "Standard"` (NOT Filmic/AgX),
  `exposure = 0.0`, `gamma = 1.0`, and writes **32-bit OpenEXR** (`color_depth
  = "32"`, `exr_codec = "NONE"`).
- Both legs are read back identically via `bpy.data.images.load(exr).pixels`
  (`render_leg.py:112-114`) → **scene-linear** float32 (EXR is linear; the view
  transform is a display-only op that does not bake into a 32-bit EXR).
- The Astroray leg goes through the same `bpy.ops.render.render` → EXR pipeline;
  the addon's final-render call passes `applyGamma = False` (the 4th positional
  arg of `renderer.render(...)`, `blender_addon/__init__.py:1265-1270`), so
  Astroray also emits **linear**.

**Verdict:** the comparison is in a common scene-linear space with matched
exposure/gamma. The view-transform/gamma artifact is **not** the cause of the
offset in the pkg119-B harness. (The PNG sidecar at `render_leg.py:127-130` is
cosmetic sRGB for the human report and is NOT the compared array — the compared
array is the linear `.npy`.)

### 2. Exposure / film — clean

`view_settings.exposure = 0.0` on both legs; Cycles adaptive sampling and
denoising off (`render_leg.py:85-87`). No per-leg tonemap.

### 3. World / normalization / per-BSDF — **RE-MEASURED: the offset is GONE**

Ran a targeted A/B on the current build (Blender 5.2 Cycles vs Astroray addon,
common linear EXR, 200², 128 spp, seed-pinned, per-channel mean ratio) on the
exact scenes that produced the baseline's dim readings:

| Scene | Baseline (2026-08-08) | Now (A/C mean) | Per-channel A/C |
|-------|-----------------------|----------------|-----------------|
| `backdrop_probe` (plain solid-diffuse backdrop + world + light) | **~0.79–0.82** (largest reading) | **1.0195** | [1.022, 1.020, 1.017] |
| `world` (lit coloured world) | (world:World cell) | **1.0085** | [0.982, 1.052, 0.991] |
| `shader_node:BSDF_DIFFUSE` (lit diffuse sphere) | **~0.88** (passing-cell cluster) | **0.9974** | [0.990, 1.011, 0.991] |
| `shader_node:BSDF_GLOSSY` (lit glossy sphere) | **~0.93** (metal r0.9 datapoint) | **1.0160** | [1.008, 1.031, 1.009] |

Every reading is now inside the `[0.90, 1.10]` parity band — three of the four
within ±2%. Astroray is, if anything, marginally *brighter* on the backdrop and
glossy scenes (the opposite sign to the reported dim). The only residual is a
small green-channel wobble (1.02–1.05) at the level of MC noise / minor
chromatic differences, NOT a systemic achromatic scale.

**The uniform ~12–20% Astroray-vs-Cycles dim that this package was filed to own
does not exist on the current build.** It was resolved by the intervening
parity work between 2026-08-08 and 2026-09-02 (the pkg138–151 dielectric series,
pkg178 Principled true-parity, the pkg129/163/165 metal work, the honour-matrix
pkg200/201 sweep, etc.) and/or the pkg119-B harness's own comparison protocol
being corrected to the clean `view_transform="Standard"` + linear-EXR path
audited in §1 (a Filmic/AgX-contaminated 2026-08-08 comparison would have
produced exactly the reported uniform dim).

---

## Disposition — CLOSED, no engine change (diagnosis-first outcome)

Per the Phase-1 exit criterion ("if the offset collapses into band once the
comparison is put in a common linear space … → methodology artifact, close this
package with no engine change"): **pkg180 is closed.** The offset is not
reproducible; there is no mechanism left to localize and explicitly no fix to
make (a uniform brightness multiply was forbidden anyway).

Note for pkg178's true-parity baseline: the current diffuse/glossy/world parity
floor is ~±2% (green channel up to ~+5% on the saturated-world scene) at 128 spp
— that is the honest starting band for any future per-lobe parity delta, not a
~15% offset. If a future harness run re-reports a large uniform dim, **check the
Cycles leg's `view_settings.view_transform` FIRST** (memory
`gamma-vs-linear-comparison-artifact`) before re-opening an engine investigation.
