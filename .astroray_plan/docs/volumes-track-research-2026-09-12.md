# Volume-rendering (heterogeneous / VDB) track — research note, 2026-09-12

Architect goal-capture from the owner directive of 2026-09-11 evening (§7 item 5
of `north-star-and-integration-gate-2026-09-07.md`, verbatim):

> "Absolutely, volume rendering is not intended to be a Pillar 4 exclusive,
> since it is required to meet Cycles parity. It is a core part of any rendering
> engine and not some niche scientific addon."

So the heterogeneous-volume / VDB track opens **now** as **core Cycles parity**,
under Pillar 2/3 — it is NOT Pillar 4. The paused packages pkg45/46/48/49/50/51
and pkg107 are a *different thing* (science data loaders: SPH-to-volume, FITS/HDF5
ingest, accretion-flow emission models) and stay frozen. This track builds the
generic renderer capability that Cycles has; the paused science loaders can later
feed that capability, but nothing here unpauses them.

This note is the single research artifact for the track: (1) an audit of what
exists, (2) the algorithm map with citations, (3) the licence table, (4) the
Cycles-vs-physics divergences, (5) the package DAG with dependency order and a
per-package acceptance table. The package specs (pkg267–pkg272) are filed
alongside it.

---

## 1. Audit — what exists on `main` (9a7ef06c) and what is absent

### 1a. Homogeneous world volume — EXISTS, both backends

A global, uniform participating medium ("world volume" / global fog) is fully
implemented on CPU and GPU:

- **CPU** (`include/raytracer.h`):
  - `Renderer::setWorldVolume(density, color, anisotropy, scatter)` (~L2756),
    state `hasWorldVolume` / `worldVolumeDensity` / `worldVolumeColor` /
    `worldVolumeAnisotropy` / `worldVolumeScatter` (~L2415–2425).
  - `worldTransmittance(distance)` and a spectral per-wavelength variant
    (~L2522–2578): Beer–Lambert `exp(-σ_t·d)`, σ_t = color·density, spectral
    upsample of the reflectance-like tint.
  - Free-flight distance sampling + HG in-scatter + NEE-through-medium in the
    integrator (~L3039+), engaged only when `worldVolumeScatter > 0`
    (single-scattering albedo α); α=0 ⇒ pure absorption, byte-identical to
    Stage 1.
- **GPU wavefront** (`include/astroray/gpu_types.h` `struct GWorldVolume`;
  `src/gpu/wavefront/stage_advance.cu`, `stage_init.cu`): published once/frame
  into a `__constant__` symbol (`setWavefrontWorldVolume`), a dedicated
  `stageVolumeScatterKernel` isolated behind `template<bool HasWorldScatter>`
  so fog-free scenes stay byte-identical (`intersect<false>` REG 127 / STACK 616
  unchanged). HG in-scatter + Volume Direct/Indirect pass split.
- **Provenance:** pkg199 Stage 1 (#611) + Stage 2 (CPU #617, GPU #619);
  pkg204 (#625) volume-pass direct/indirect split. All HW-verified.
- **Key facts from pkg199:** there was NEVER any HG / in-scatter / distance
  sampling before pkg199 — the original spec's premise was false; the only prior
  volume code was Beer–Lambert absorption. `worldVolumeAnisotropy` had been
  stored and read by nothing.

### 1b. Legacy `ConstantMedium` — EXISTS, effectively dead

`include/astroray/shapes.h` L314 `class ConstantMedium : public Hittable` and
`plugins/shapes/constant_medium.cpp` (`ASTRORAY_REGISTER_SHAPE("constant_medium")`):
a Ray-Tracing-in-One-Weekend homogeneous bounded medium. It is **not** part of
the modern spectral path: it seeds a `std::mt19937` from `std::random_device`
inside `hit()` (non-deterministic, breaks seed pinning), scatters via a
`Lambertian` material (NOT the isotropic/HG phase function), and is RGB, not
spectral. Treat it as legacy to be superseded by a proper bounded grid/homogeneous
medium in the spectral integrator (pkg268), not extended.

### 1c. `isotropic` phase plugin — EXISTS, orphaned

`plugins/materials/isotropic.cpp` implements p = 1/4π with a spectral `eval`/
`sample`. It is registered but `ConstantMedium` uses `Lambertian` instead, so it
has no live caller. pkg268 should make it (and an HG phase) the actual medium
phase function.

### 1d. Blender addon volume wiring — MINIMAL

- `blender_addon/exporter.py`: `volume_bounces` is passed to `render(...)`
  (L1425, L2072) but there is **no `bpy.types.Volume` object export**, no VDB
  read, no `principled_volume` closure lowering.
- `blender_addon/settings_map.py` L141–143: `volume_bounces` is
  **DROPPED-SILENT** with the note "volume transport is itself only partially
  implemented."
- `blender_addon/native_settings.py` L69: default `volume_bounces = 0`.

### 1e. What is ABSENT (the whole task surface)

- **No OpenVDB / NanoVDB** anywhere in the tree (grep: zero `.vdb`, `openvdb`,
  `nanovdb` in source).
- **No heterogeneous media** — no density/temperature/color/velocity grids, no
  spatially-varying σ_t.
- **No delta tracking / ratio tracking / null-scattering**, no **majorant grid**.
  The homogeneous world volume uses analytic Beer–Lambert (correct only because
  σ_t is constant).
- **No Principled Volume** closure (Cycles `principled_volume`: density, color,
  anisotropy, absorption color, emission strength/color, blackbody intensity/
  tint, temperature, attribute names for density/temperature grids).
- **No bounded object media** in the spectral integrator (only global fog + the
  dead legacy Hittable).
- **No volume NEE with ratio-tracking transmittance** (homogeneous NEE uses the
  analytic exponential; heterogeneous shadow rays need ratio tracking).

**Conclusion:** the homogeneous machinery (HG phase, in-scatter, NEE-through-
medium, pass split, the `template<bool>` GPU fleet-isolation pattern) is a strong
scaffold to imitate, but every heterogeneous piece — grid representation, import,
majorant, delta/ratio tracking, Principled Volume, VDB — is greenfield.

---

## 2. Algorithm map with citations (cite-algorithm first)

Every non-trivial algorithm below names a canonical paper and a licence-
compatible reference implementation. Implementers MUST run the `cite-algorithm`
skill and save per-algorithm notes before coding; this table is the starting map,
not a substitute.

| Algorithm | Canonical paper | Reference impl (licence) | Where it lands |
|---|---|---|---|
| Delta / Woodcock tracking (free-flight in heterogeneous media) | Woodcock et al. 1965, "Techniques used in the GEM code…"; pbrt-v4 §14.1–14.2 | pbrt-v4 `media.h` `SampleT_maj`, `cpu/integrators.cpp` `VolPathIntegrator` (Apache-2.0) | pkg268 (CPU), pkg269 (GPU) |
| Majorant grid + DDA traversal (bounding σ_t for tracking) | pbrt-v4 §11.4.2 "DDA Majorant Iterator" | pbrt-v4 `media.h` `MajorantGrid`, `DDAMajorantIterator`, `RayMajorantIterator` (Apache-2.0) | pkg267 (build), pkg268/269 (consume) |
| Ratio tracking (unbiased transmittance for NEE shadow rays) | Novák, Selle, Jarosz 2014, "Residual Ratio Tracking for Estimating Attenuation in Participating Media", SIGGRAPH Asia | pbrt-v4 `SampleLd` transmittance loop; Cycles `shade_volume.h` `volume_integrate_step` (both Apache-2.0) | pkg268 (CPU), pkg269 (GPU) |
| Null-scattering path integral (spectral / colored media, unbiased) | Miller, Georgiev, Jarosz 2019, "A null-scattering path integral formulation of light transport" | pbrt-v4 `VolPathIntegrator` null-scatter handling (Apache-2.0) | pkg268 (design ref), pkg270 (spectral σ) |
| Spectral / decomposition tracking (chromatic σ_t) | Kutz, Habel, Li, Novák 2017, "Spectral and Decomposition Tracking for Rendering Heterogeneous Volumes", SIGGRAPH | pbrt-v4 spectral MIS majorant loop (Apache-2.0) | pkg270 (per-λ σ) |
| Henyey–Greenstein phase function | Henyey & Greenstein 1941 | already in `raytracer.h` (world-volume in-scatter); Cycles `kernel/closure/volume.h` `phase_hg` (Apache-2.0) | pkg268 (reuse/generalize) |
| Equiangular sampling (light NEE inside media) | Kulla & Fajardo 2012, "Importance Sampling Techniques for Path Tracing in Participating Media" | pbrt-v4 / Cycles `shade_volume.h` `volume_equiangular_sample` (Apache-2.0) | pkg268 (MIS with distance sampling) |
| Blackbody emission from a temperature grid | Planck's law; Cycles `svm_node_blackbody` | Cycles `kernel/svm/svm_blackbody.h`, `principled_volume` in `svm/closure.h` (Apache-2.0); engine already has a Blackbody node | pkg270 |
| NanoVDB sparse grid (shared CPU/GPU representation) | Museth 2021, "NanoVDB: A GPU-Friendly and Portable VDB Data Structure…" | `nanovdb/NanoVDB.h` single header (Apache-2.0 — verified 2026-09-12) | pkg267 |
| OpenVDB `.vdb` file read (CPU-side import) | Museth 2013, "VDB: High-Resolution Sparse Volumes with Dynamic Topology" | OpenVDB (MPL-2.0) OR Blender's own `bpy.types.Volume.grids` Python API | pkg267 |
| Principled Volume closure semantics | Blender manual "Principled Volume"; Cycles `blender/volume.cpp` grid attribute mapping | Cycles `scene/volume.cpp`, `kernel/svm/closure.h` `svm_node_closure_volume` (Apache-2.0) | pkg268 (basics), pkg270 (emission) |

---

## 3. Licence table

| Component | Licence | Vendoring verdict |
|---|---|---|
| pbrt-v4 (`media.h`, `integrators.cpp`) | Apache-2.0 | Reference for algorithm structure/math; clean-room the code, cite in comments. Do not paste verbatim without the Apache header. |
| Cycles (`shade_volume.h`, `volume_stack.h`, `svm/closure.h`, `scene/volume.cpp`, `blender/volume.cpp`) | Apache-2.0 | Same — reference + cite; our `external/cycles_light_tree/` precedent shows Apache Cycles code can be vendored with its header when a direct port is chosen. |
| **NanoVDB** `nanovdb/NanoVDB.h` | **Apache-2.0** (SPDX confirmed at the header top, 2026-09-12; "Copyright Contributors to the OpenVDB Project") | **Vendorable as a single header.** This is the preferred sparse-grid representation shared CPU↔GPU. Header-only, no build-system entanglement. |
| OpenVDB core (`.vdb` file reader) | MPL-2.0 (file-level copyleft) | Heavyweight C++ dependency (Boost/TBB/Blosc). **Prefer NOT to link it.** Two lighter import paths in pkg267 (see §5). If ever linked, MPL-2.0 is file-level and compatible, but the build cost is not worth it. |
| Blender `bpy.types.Volume.grids` | Blender GPL runtime, accessed via the addon's Python (already GPL-context) | The addon already runs inside Blender; reading grids through the Python API introduces no new licence obligation on the engine. |

**Licence recommendation:** vendor `NanoVDB.h` (Apache-2.0) as the engine grid
representation; do the `.vdb`→grid decode either through Blender's Python API
(addon path, no engine dependency) or by parsing the file with NanoVDB's own
`.nvdb` tooling / a minimal reader — explicitly avoid linking full OpenVDB. This
keeps the engine dependency-free and Apache/MPL-clean.

---

## 4. Cycles-vs-physics divergences (apply the §7 2026-09-08 "physics first" rule)

Where Cycles is physically approximate and Astroray is spectral, Astroray
implements the physically correct model (cited), records the divergence with
oracle evidence, and the Cycles A/B becomes a **cross-check band**, not the
acceptance criterion. Where Cycles is physically right or an artist look must
match, Cycles parity stays the target.

1. **Chromatic extinction.** Cycles path-traces volume σ with RGB coefficients
   and uses hero-wavelength / RGB tracking. Astroray is spectral: σ_a(λ), σ_s(λ)
   per wavelength are a real feature (spectral/decomposition tracking, Kutz 2017).
   → physics-first; Cycles A/B is a cross-check band on integrated RGB.
2. **Blackbody emission.** Cycles converts temperature→RGB via a blackbody LUT
   (RGB-approximate; compounds the memory note `gpu-emission-is-rgb-approximated`).
   Astroray evaluates Planck spectrally through the existing Blackbody path.
   → physics-first; cross-check the integrated RGB against Cycles.
3. **Homogeneous vs heterogeneous NEE.** Cycles and Astroray's current world
   volume use analytic Beer–Lambert transmittance for NEE (valid: constant σ_t).
   Heterogeneous NEE needs unbiased **ratio tracking** (Novák 2014). This is a
   new estimator, not a divergence — match Cycles' result in expectation.
4. **Equiangular + distance-sampling MIS.** Cycles combines equiangular light
   sampling with distance sampling via MIS inside media (crucial for spotlights
   in fog / god-rays). Astroray's homogeneous path already does phase/light MIS;
   pkg268 must add equiangular for heterogeneous. → parity target (Cycles right).
5. **Emission "step size" ray march.** Legacy Cycles used a fixed step-size ray
   march for absorption/emission; modern Cycles uses null-scattering. Astroray
   should use null-scattering / tracking throughout — do not reintroduce a
   biased fixed-step march. → physics-first.

---

## 5. Package DAG, dependency order, and acceptance table

Six packages, pkg267–pkg272. Pillars: representation/import = Pillar 2 (spectral
core / data foundation); transport, GPU, emission, passes = Pillar 3 (light
transport upgrades). Track A (route to `package-implementer`); the physics- and
CUDA-heavy packages (pkg268/269/270) are **Opus-tier implementation** work per
memory `delegate-tier-stalls-on-hard-packages` — the dispatcher should not send
them to open-weight lanes despite Track A. All GPU packages must state the
REG:254 shade-kernel constraint and the pkg199/pkg204 `template<bool>` wavefront-
stage isolation pattern.

```
pkg267 (grid repr + Blender/VDB import + majorant)   [Pillar 2, no volume deps]
   │
   ├──► pkg268 (CPU delta/ratio tracking + Principled Volume basics + NEE)  [Pillar 3]
   │        │
   │        ├──► pkg269 (GPU wavefront heterogeneous stage, NanoVDB)        [Pillar 3]
   │        │        │
   │        ├──► pkg270 (Principled Volume emission: blackbody/temp/spectral) [Pillar 3]
   │        │        │
   │        │        └──► pkg271 (passes/AOVs + corpus `volumes` family +    [Pillar 3]
   │        │                     viewport/degradation + Blender headless)
   │        │        ┌────────────┘  (pkg271 depends on pkg269 AND pkg270)
   │        └──► pkg272 (OPTIONAL: velocity/motion-blur grids OR             [Pillar 3]
   │                     multi-scatter approx — only if justified)
```

Dependency order (topological): **pkg267 → pkg268 → {pkg269, pkg270} → pkg271**;
pkg272 optional, off pkg268.

### Per-package acceptance table

| pkg | Deliverable | Key gates |
|---|---|---|
| pkg267 | Engine `GridMedium` (NanoVDB-backed) + majorant grid; Blender `bpy.types.Volume`/`.vdb` import → engine grid | Load a synthetic + a real `.vdb`; assert grid dims/bbox/world-transform; majorant ≥ max σ_t per supervoxel (numpy check); Blender headless exports a Volume object to an engine grid handle |
| pkg268 | CPU delta-tracking free-flight + ratio-tracking transmittance NEE + HG/isotropic phase + Principled Volume basics (density/color/absorption/anisotropy); bounded object media in the spectral integrator | Homogeneous slab furnace vs analytic Beer–Lambert (linear, floor+ceiling, `apply_gamma=False`); heterogeneous transmittance + single-scatter vs a brute-force numpy ray-march reference within tolerance; ratio-tracking NEE unbiased (mean converges to the numpy reference); seed-deterministic (no `random_device`) |
| pkg269 | GPU wavefront heterogeneous volume stage (NanoVDB device grid); delta/ratio tracking on device; `template<bool>` fleet isolation | GPU↔CPU per-channel ROI mean ratio ±5 % on a heterogeneous scene; fog-free/grid-free fleet **byte-identical**; REG:254 shade-kernel HARD gate unchanged; `cuobjdump` REG report on the new stage |
| pkg270 | Principled Volume emission: emission strength/color, blackbody intensity/tint from a temperature grid → Planck spectral; per-λ σ_a/σ_s (spectral/decomposition tracking) | Emission-only furnace: blackbody radiance vs analytic Planck at a known T (linear, floor+ceiling); temperature-grid → color matches Cycles cross-check band; per-λ σ produces measurable chromatic extinction vs an RGB run |
| pkg271 | Volume Direct/Indirect passes for heterogeneous media (extend pkg204); `volume_bounces` un-DROPPED in `settings_map`; degradation-report rows; `volumes` corpus family; Blender headless F12 | Pass sum = beauty (rel_L1 ~0); manifest tests green for the new `volumes` family; Blender headless imports a Volume object and renders F12 CPU+GPU with no exception; Cycles A/B recorded as a cross-check band |
| pkg272 | OPTIONAL velocity-grid motion blur OR a multi-scatter diffusion approximation | Only filed to `in-progress` if a corpus scene demonstrably needs it; motion-blur A/B vs Cycles, or multi-scatter energy vs a reference |

### First two to dispatch

**pkg267 and pkg268.**

- **pkg267** unblocks the entire track: both the CPU transport (pkg268) and the
  GPU stage (pkg269) need the grid representation, the majorant grid, and the
  NanoVDB decision. It is also the only package with no volume dependency, so it
  can start immediately, and its Blender-import half is CPU-only (parallelizable
  against a GPU-locked lane).
- **pkg268** delivers the first *correct, visually verifiable* heterogeneous
  volume on the CPU oracle — the correctness foundation before any GPU work — and
  unblocks pkg269 (GPU), pkg270 (emission), and pkg272 (optional). Per the north
  star (correctness > fidelity > speed) the CPU oracle must be right before the
  GPU stage is even attempted.

Together pkg267 + pkg268 get a real smoke/cloud VDB rendering correctly on the
CPU, gated against Beer–Lambert and a numpy reference — the milestone that proves
the track before the GPU and emission investment.

---

## 6. Open questions for the owner (max 3, real forks)

1. **VDB import path:** decode `.vdb` grids through **Blender's Python API**
   (`bpy.types.Volume.grids`, addon-only, zero engine dependency, but F12/addon-
   only — a standalone `.vdb` on the CLI would not load) **or** a **minimal
   engine-side `.nvdb`/`.vdb` reader** (works headless and standalone, more code)?
   The architect leans Blender-API-first (matches "Blender is the steering
   wheel") with an engine `.nvdb` reader deferred to pkg272-scope if standalone
   ever matters.
2. **Emission colour model:** Astroray evaluates blackbody emission **spectrally
   (Planck)** while Cycles is RGB-LUT-approximate. Confirm the physics-first rule
   applies here too (spectral Planck, Cycles as cross-check band) — the architect
   assumes yes per §7 2026-09-08, but blackbody fire is exactly the kind of
   artist-facing look where an owner might want Cycles-match instead.
3. **pkg272 scope:** is velocity-grid **motion blur** a near-term parity need, or
   should the optional slot instead hold a **multi-scatter approximation** for
   dense clouds (Cycles' `multiple_scattering`-like behaviour)? The architect
   would file neither until pkg271's corpus shows which one a real scene needs.
</content>
</invoke>
