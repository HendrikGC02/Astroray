# Product themes plan — 2026-09-29

Architect run (Claude Opus 5.5) on four owner themes. Inputs: main dbb7a382,
`stage-plan-2026-09-22.md`, `architect-plan-2026-09-29.md` (batches AK–AO),
`north-star-and-integration-gate-2026-09-07.md`, STATUS.md, four Sonnet
fact-gathering reports (UI, node coverage, spectral data, output/AOVs), spot
checks by the lead. First packages: **pkg310–pkg313** (all lint-clean).

## 0. Where the Fable+Astra long-term plan already stands

| Theme | In the 09-22 stage plan? |
|---|---|
| 1 complex node trees | Partly. Gate (b) measures socket **breadth** (frequency-weighted socket coverage, still UNMEASURED in `acceptance_manifest.json`). Nothing measures **composition**: realistic trees with per-hit inputs, >2 textures, deep shader stacks. |
| 2 dedicated UI | Only as a constraint: north star "no parallel ground-up UI" (pkg176 retired the custom UI). No UI package is scheduled. |
| 3 element/molecule spectra | Only pkg45 (CLOUDY H/He Case-B tables, paused) and the unfiled pkg195 Phase 2 (spectrum math nodes, SPD import). No general line library. |
| 4 data cubes | Only pkg51 Phase 1 "radiance microbins" (paused, Stage 3) and pkg243 (single raw band). No cube accumulator, writer or diagnostic AOV export. |

**Lead view.** Theme 1 is the most important of the four and belongs in the
Stage 0 exit gate. A renderer that drops Attribute or Layer Weight nodes, or
renders Light Path tricks wrong without saying so, is not "daily-usable"
whatever gate (b)'s socket score says. Theme 2 fits the north star as long as
"dedicated" means native Blender surfaces (Properties contexts, Add-menu
categories, presets, asset library, node badges), never a parallel app.
Themes 3 and 4 are science foundation. Each has a cheap product-now slice
(element emission spectra for lamps, flames and signage; diagnostic AOVs), and
it is worth building now only when shaped as the substrate pkg46, pkg51 and
pkg243 will consume. Otherwise it gets built twice.

## 1. Theme 1: complex shader node setups

**Exists.** The op-VM (`shader_vm.h`) runs per-texel scalar/vec3 programs on
CPU and GPU (pkg186, pkg190, pkg219, pkg230, pkg277, pkg293) for base colour,
roughness, metallic, transmission, IOR, normal and bump. Node groups are
inlined (`inline_shader_nodes`). Normal Map and Bump work (pkg223/223b).
Principled, Metallic and most BSDFs are supported. Mix Shader lerps Principled
specs. `DegradationReport` emits one WARNING line per render.

**Gap (measured by code reading, not yet by renders).**
- **Per-hit inputs are missing.** There is no handler anywhere in
  `blender_addon/` for Attribute, Color Attribute, Geometry, Layer
  Weight/Fresnel, Object Info or Light Path. A chain without a texture leaf is
  constant-folded, so these nodes cannot vary per hit even in principle.
- **Program bounds are tight.** 32 instructions, 8 registers, 2 textures and
  2 ramps per program; one coordinate mapping per program. A PBR set with
  more than 2 images in one chain falls back.
- **Closure composition is not general.** Add Shader of two BSDFs keeps only
  the first (#955), and the dominant-shader fallback is silent. On GPU,
  textured-Fac programs sample only one texture (#954). The metal+glass mix
  is off by 2–4× (#956).
- **Pattern fidelity.** Noise correlates 0.73 with Cycles (#881). The GPU bake
  is 64³ nearest (#890). Mapping after non-affine math is unsupported (#891).
  Image reads 2× too bright and Voronoi Color renders grey (#944). Affine
  Mapping into Checker is flat (#945).
- **GPU emission.** Textured Emission Color is flat on GPU (#962, #965, #966).
- Curves (RGB/Float/Vector), Vector Transform, Normal, Tangent, White Noise,
  Gabor, AO and Bevel are unsupported.

Predicted today on 8 representative production materials: about 2/8 inside
the Cycles band (wood, the grouped PBR set). The rest fail on per-hit inputs,
closure composition or pattern fidelity. pkg310 replaces this prediction with
a measurement.

**Theme gate:** *N/8 production materials within the per-ROI MC band of
Cycles on CPU and GPU, with zero silent degradations.* Targets: baseline
(pkg310) → 5/8 after P3 → 8/8 after P4.

| Phase | Content | Gate | Lane |
|---|---|---|---|
| P1 **pkg310** | 8-material production corpus (car paint, wood, marble, grouped PBR set, 3-deep Mix/Add stack, Color Attribute + Attribute, Light Path tricks, Object Info/Geometry/Curves) with Cycles refs; a node-tree walker that diffs exercised (node, socket) pairs against the DegradationReport; ranked burn-down backlog as issues | baseline N/8 table; silent-drop list; each backlog item names the materials it unblocks | Sonnet 5.5 + Terra review |
| P2 open issues | #944 #945 #954 #955 #956 #962 #965 #966 (unscheduled today) join #881 #890 #891 (AM-3/4/5) | each issue's named observable; materials re-scored | Sonnet 5.5 / Opus (#956, #954, #962: GPU shade) |
| P3 per-hit inputs | op-VM input opcodes: Geometry (N, I, backfacing, position), Layer Weight/Fresnel, Color Attribute/Attribute (vertex attribute upload), Object Info (random, location), Light Path (ray-type flags; GPU needs a per-lane ray-type bit, register-audited) | 5/8; `HasProgram=false` SASS identical; REG ≤ 254 | Opus |
| P4 architecture fork | Raise op-VM bounds (textures in-program, >32 instr) **or** move to a Cycles-SVM-shaped per-hit graph with closure accumulation (arbitrary Add/Mix of BSDFs). Decide on pkg310's counts of how many failures are bounds versus closures | 8/8 | Opus design note → owner |
| P5 long tail | Curves, Vector Transform, Normal/Tangent nodes, White Noise, Gabor; AO/Bevel only if a corpus material needs them | per-node Cycles tests | Sonnet 5.5 |

Ordering: pkg310 can start in any free CPU slot now. It is Blender-headless
heavy and must be serialised with the pkg284 reference renders. It reuses the
pkg284 harness and must not fork it. P2 is a new batch after AM. P3 follows
pkg293/pkg295 in `gpu_materials.h` and `shader_vm_compiler.py`. P4 waits for
P3's evidence. **Product-now: all of it.**

## 2. Theme 2: dedicated, Blender-native interfaces

**Exists.**
- Properties panels: render (Sampling, Performance, Wavelength, Diagnostics),
  world (Surface only), material (plus Spectral/Live preview sub-panels),
  object (Black Hole with about 35 flat properties; caustic caster) and light
  (Astroray Spectrum: power and profile).
- Cycles panels are reused selectively via COMPAT_ENGINES (4 Light Paths
  panels adopted).
- 8 custom nodes sit in one flat "Astroray" Add submenu. Native nodes now
  work behind the stock Material Output when wired directly as Surface, but
  still go grey behind Mix Shader or when unwired.
- Only 3 operators. No presets, no asset library, no View Layer passes panel.

**Gap (ranked).**
1. No View Layer passes UI for AOVs, cryptomatte or light-path passes; they
   are reachable only through Python.
2. World and Light panels are thin (no sky, strength or world-volume UI; no
   size, spread or shadow controls; GPU spectral exactness shown only as a
   label).
3. The Black Hole panel is one undifferentiated column with no units or
   presets.
4. The Add menu is flat and uncategorised.
5. Nodes that render grey carry no on-node status.
6. There are no preset menus or bundled assets.
7. Tooltips are uneven.
8. Un-honoured Cycles settings are not visibly marked.

**Lead position (push-back).** "Dedicated interface" must mean native Blender
surfaces only. That rules out an N-panel sidebar app, a custom workspace, or
widgets that duplicate Cycles controls. It is the pkg176 decision, and it is
also what "fits in with the rest of Blender" means.

| Phase | Content | Gate |
|---|---|---|
| P1 **pkg311** | UI conventions note + conformance pass: categorised Add menu, on-node status badges, Black Hole sub-panels + preset menu with units, render/quality presets, tooltip lint test, un-honoured Cycles controls labelled | headless UI test suite green; every Astroray RNA property has a description; screenshot evidence inspected |
| P2 passes UI | View Layer > Passes panel for existing AOVs + light-path + cryptomatte (joins theme 4 P2), World panel depth (sky, strength, world volume) | each toggled pass appears in the Render Result; F12 honour test per control |
| P3 spectral library UI | element/molecule picker with search, Spectrum Mix node UI, "Astroray Spectra" + "Astroray Materials" asset catalogues (with theme 3) | asset-browser drag-drop renders; library round-trips in a saved .blend |
| P4 astro objects | Add > Astroray (black hole, emission nebula, accretion disk) | science-later: waits for Pillar 4 thaw |

Ordering: pkg311 is addon-Python only (Flash/Sonnet 5.5 lane, Terra review).
It conflicts with `__init__.py` edits in AK-5 (#921/#773), AN-2 (#866) and
AN-3 (#867), so it runs after those. **Product-now: P1–P3. Science-later:
P4.**

## 3. Theme 3: element and molecule spectral library

**Exists.**
- `profiles.bin` (ASPR v1: 300–2500 nm on a 5 nm grid, 441 samples) with 47
  entries: 40 reflectance (USGS, ECOSTRESS, Rakic) and 7 emission (CIE
  F2/F3, three LEDs, Na and Hg synthesised from NIST ASD lines with
  area-normalised Gaussians at bake time).
- Runtime profiles via `register_spectral_profile`; the profile database is a
  process-wide singleton.
- `EmissionSpectrum` variants are Blackbody, RGB, MeasuredSPD and Composite
  (base × RGB filter only; no weighted sum).
- GPU dedicated lights use a baked spectral `emissionProfileTable` (pkg218).
  GPU emission shaders are still RGB-approximated (to verify).
- Chromatic volume σ(λ) exists in the pkg270 hero-wavelength path, but no
  profile feeds it.

**Gap.**
- No per-element or per-molecule data.
- No temperature- or pressure-dependent line shapes.
- No combine/scale authoring: pkg195 Phase 2 (spectrum math, gel filters, SPD
  import) was never filed.
- No absorption profiles for media.
- A 5 nm grid cannot resolve lines (Na D is 0.6 nm apart). That is fine for
  colour, but not for science.

**Semantics (adopted).**
- Emission: L(λ) = Σᵢ wᵢ·Pᵢ(λ; Tᵢ, Pᵢ), each Pᵢ unit-integral. wᵢ is a
  relative power fraction, and lamp Power or emission Strength supplies
  absolute scale.
- Absorption: σ_a(λ) = Σᵢ nᵢ·σᵢ(λ; T, P), with transmittance exp(−∫σ_a ds)
  through the pkg270 spectral volume path.
- Reflectance profiles are **never** summed (area-weighted mixing only).
- Element spectra are **LTE** (Boltzmann populations at T). That is right for
  lamps, flames and arcs, and **wrong for nebulae**. Nebular recombination
  (Case B) stays with pkg45/pkg46; the UI must not present LTE Balmer ratios
  as nebular.

**Data (licences as verified 2026-09-29).**
- Ship now:
  - NIST ASD (US-gov public domain, already used)
  - RefractiveIndex.info (CC0, n and k)
  - USGS splib07 and ECOSTRESS (public domain, already shipped)
- Needs an owner call:
  - ExoMol: **CC BY-SA 4.0**. Share-alike binds derived tables; OK if the
    data files carry their own licence.
  - HITRAN/HITEMP: registration; redistribution terms not published on
    hitran.org/about; derived tables only.
  - CHIANTI: "freely available… acknowledge"; no formal licence text.
  - Kurucz: no stated licence.
  - MPI-Mainz UV/VIS atlas: no licence; reference only.

| Phase | Content | Gate | Scope |
|---|---|---|---|
| P1 **pkg312** | NIST ASD line library for H–Zn plus selected heavy elements (neutral + singly ionised, 300–2500 nm); offline LTE bake with Voigt(T, P); addon **Element Emission** + **Spectrum Mix** nodes → runtime profile consumed by lights and emission shaders; no engine change | Na D / Hg / H lines at the NIST wavelengths (±1 bin); unit integral; Boltzmann ratio test vs analytic; mixture linearity; GPU leg spectral or DEGRADED-reported | product-now |
| P2 absorption media | σ(λ) profiles × number density into the volume absorption coefficient (CPU, then GPU twin); surface Spectral Filter (pkg195 P2 item) | Beer–Lambert slab vs analytic per λ ≤ 1 %; CPU/GPU ±2 % | product + science |
| P3 molecules | band cross-sections pre-binned on a T grid (O₂ A-band, H₂O, CO₂, CH₄, O₃, NO₂; C₂/CN Swan bands for flames and comets) from licence-cleared sources | Swan band heads at literature λ; T interpolation monotone | owner licence call first |
| P4 fine grid | ASPR v2 (windowed sub-nm grid) + line-aware λ sampling shared with pkg46's line-mixture MIS | resolved Na D doublet; noise vs line-width convergence | science-later (Pillar 4) |

Ordering: pkg312 is Python-only in `scripts/data/`, `data/` and
`blender_addon/nodes/` (Sonnet 5.5; `cite-algorithm` first for the Voigt and
Boltzmann formulas). It is CPU-cheap and can go in any free slot after
pkg311's Add-menu change (same file) or before it with a rebase. P2 touches
`volume_transport.h` and must be serialised after pkg296.

## 4. Theme 4: data-cube output

**Exists.**
- CPU `SampleResult` carries first-hit albedo, normal, position, depth, UV,
  alpha, IDs, bounce count, sample weight and 15 light-path passes.
- Spectral samples (4 hero λ) are folded to XYZ per sample. There is no
  per-bin storage on CPU or GPU; the GPU accumulates XYZ only.
- GPU adaptive sampling holds a per-pixel sample count that is never
  exported. The CPU bounce/sample-weight buffers are internal heatmaps.
- `exr_writer` writes multi-channel float32 EXR. FITS is **read-only**
  (cfitsio already linked). There is no HDF5 or Zarr.
- Blender registers Albedo/Normal/Depth/Mist/Position/UV/Index plus
  light-path and cryptomatte passes. There is no sample-count, variance,
  ray-count or path-depth pass (#867 is queued as AN-3).

**Gap.** A λ-bin accumulator, variance (sum of squares), ray and path
counters, a cube writer with a WCS spectral axis, and a Blender surface for
them.

**Cost.** 1920×1080 × 64 bins × float32 = 531 MB per cube (×2 with variance).
It fits the 16 GB card. Scalar AOVs are about 8 MB each.

**Lead position.** Separate the two halves.
- **Diagnostic AOVs** (sample count, variance, path depth, ray count,
  position, IDs) are product-now. They help noise and adaptive-sampling work
  and Cycles has equivalents.
- **The spectral cube** is science substrate. It must be exactly the
  accumulator pkg51 Phase 1 ("radiance microbins") needs, so pkg51 consumes
  it rather than re-implementing it.
- Recommended formats: **FITS** cube (CTYPE3 = 'WAVE', CUNIT3 = 'nm'; cfitsio
  already a dependency) for science, and **multi-layer EXR** for DCC.
  HDF5/Zarr only when a consumer asks.
- Values are **relative** radiance with pkg243 provenance headers. No
  absolute-units claim before the instrument model (north star "will NOT"
  #4).

| Phase | Content | Gate | Scope |
|---|---|---|---|
| P1 **pkg313** | CPU oracle: λ-bin cube (hero samples splatted with f/p), diagnostic AOVs (sample count, variance, mean path depth, ray count), FITS + EXR writer, Python API returning numpy arrays | CMF-integrated cube reproduces the RGB beauty within MC noise; sodium-lamp scene puts ≥ 95 % of emitted energy in the D-line bins; variance AOV matches the empirical 8-seed variance; beauty bit-identical when off | science-foundational + diagnostics |
| P2 GPU + Blender | wavefront bin accumulation (side table, runtime flag, REG ≤ 254), AOVs as View Layer passes (theme 2 P2), "Spectral cube" output setting | CPU/GPU cube ±2 % per bin (MC band); F12 writes the FITS | product-now (AOVs), science (cube) |
| P3 instrument | pkg51 Phase 1 consumes the cube: SRF/QE weighting, PSF before integration; pkg243 provenance in headers; celestial WCS once the camera→sky mapping exists | pkg51 gates | science-later (Stage 3) |

Ordering: pkg313 edits the CPU accumulation in `raytracer.h` (~5044–5190).
It must follow pkg297 P1a (the `Rng` retype) and AN-3 #867 (whose AOV
contract it adopts). Opus lane (accumulation estimator), with Terra review.
It touches no GPU code in P1.

## 5. Proposed placement against batches AK–AO

New **Batch AP** starts once AK has merged, at ≤ 3 implementing lanes in
total:

| # | Item | Lane | Conflict key / order |
|---|---|---|---|
| 1 | pkg310 production corpus + burn-down | Sonnet 5.5 + Terra | Blender headless, serialised with pkg284/pkg285 reference renders |
| 2 | pkg311 UI conformance P1 | Sonnet 5.5 (or Flash) + Terra | `blender_addon/__init__.py`, `nodes/__init__.py`, after AN-2/AN-3 |
| 3 | pkg312 element line library P1 | Sonnet 5.5 + Terra | `scripts/data/`, `nodes/__init__.py` (after pkg311's menu edit) |
| 4 | pkg313 data cube P1 | Opus 5.5 + Terra | `raytracer.h` accumulation, after pkg297 P1a and #867 |

After pkg310 reports, a theme-1 P2 batch picks up the 8 unscheduled issues,
and P3 gets its own spec.

## 6. Owner decisions (not made here)

1. **Theme 1 gate.** Make "N/8 production materials within band, zero silent
   drops" a Stage 0 exit-gate row next to gate (b)? (Lead: yes.)
2. **Theme 1 P4 fork** (bounded op-VM versus an SVM-shaped per-hit graph):
   decide after pkg310's counts.
3. **Theme 2 scope.** Native Blender surfaces only (lead recommendation)?
   Should an asset library (.blend catalogue, adds MB to the ZIP) ship?
4. **Theme 3 licences.** Accept ExoMol CC BY-SA 4.0 derived tables (licensed
   separately under `data/`)? Accept HITRAN-derived tables once the terms are
   verified? Kurucz and CHIANTI with acknowledgement only?
5. **Theme 3 grid.** Stay on the 5 nm ASPR v1 for P1–P3 and take ASPR v2
   (sub-nm windows) only with Pillar 4? (Lead: yes.)
6. **Theme 4 format.** FITS + multi-layer EXR (lead) versus adding HDF5/Zarr
   now. Default bin layout: 380–780 nm at 5 nm (81 bins) versus
   user-defined.
7. **Priority.** Themes 1–2 ahead of the Pillar 4 thaw (lead: yes, they are
   integration). Should themes 3–4 P1 run now as foundation, or wait for the
   Stage 0 exit?
