# Research note — Native Cycles Principled BSDF port (pkg178)

**Date:** 2026-08-08. **Author:** architect (goal-capture). **Owner request:**
a faithful native copy of Cycles' Principled BSDF — the LATEST version,
including the thin translucent / thin-film material — replacing the current
Principled→Disney approximation for true parity. This note records the
external reference pin, the Astroray extension-point analysis, and the
swarm-decomposition assessment behind pkg178.

---

## 1. Reference pin: Cycles main (Blender 5.2-era Principled BSDF)

The post-4.0 rewrite timeline (what "latest" means):

| Version | Feature | Reference |
|---|---|---|
| 4.0 (2023) | Full rewrite: Coat (GGX, `coat_ior`+`coat_tint` Beer absorption, sits above emission), Sheen (Zeltner/Burley/Chiang LTC "microfiber"), multiscatter GGX by default, IOR-driven specular (`specular_ior_level` remaps F0), emission inside the node | [4.0 release notes](https://developer.blender.org/docs/release_notes/4.0/shading/) |
| 4.2 | **Thin Film** iridescence (Belcour-Barla 2017), dielectric specular + transmission | [PR #118477](https://projects.blender.org/blender/blender/pulls/118477) |
| 4.3 | Diffuse Roughness (energy-preserving multiscatter Oren-Nayar, OpenPBR/EON behaviour); Physical Conductor (complex-IOR) + F82-tint metal Fresnel | [PR #123345](https://projects.blender.org/blender/blender/pulls/123345), [PR #123616](https://projects.blender.org/blender/blender/pulls/123616) |
| 5.0 | Thin Film extended to **conductors** (metallic lobe) | [5.0 Cycles notes](https://developer.blender.org/docs/release_notes/5.0/cycles/) |
| 5.2 | **Thin Wall** mode (bool): thin sheet — combined reflection+transmission thin glass, diffuse+translucent thin subsurface ("paper, leaves, window sheets"); also negative SSS anisotropy | [PR #157469](https://projects.blender.org/blender/blender/pulls/157469) |

The owner's "thin translucent / thin-film material" is BOTH features: Thin
Film (interference iridescence, 4.2/5.0) and Thin Wall translucency (5.2).

**Oracle implication:** the local Blender is 5.1 — it has dielectric+conductor
thin film but NOT Thin Wall. Stage-4 thin-wall parity legs need a Blender
5.2 LTS install as the Cycles oracle (owner decision D1 in pkg178).

### 1.1 Full parameter list (SVM stack reads, `svm_node_closure_bsdf`,
`CLOSURE_BSDF_PRINCIPLED_ID`, cycles `src/kernel/svm/closure.h`)

`base_color, metallic, roughness, ior, alpha, normal; diffuse_roughness;
subsurface_weight, subsurface_radius (RGB), subsurface_scale, subsurface_ior,
subsurface_anisotropy, subsurface_method; specular_ior_level, specular_tint,
anisotropic, anisotropic_rotation, tangent_offset; transmission_weight;
coat_weight, coat_roughness, coat_ior, coat_tint, coat_normal_offset;
sheen_weight, sheen_roughness, sheen_tint; emission_color, emission_strength;
thin_film_thickness (nm), thin_film_ior; thin_wall (bool)`.

### 1.2 Closure stack and layering (the structure to replicate)

Weight flow: `weight = mix_weight`; `weight *= alpha` (a Transparent closure
takes `1-alpha`); then top-down:

1. **Emission** — attenuated by the layers stacked above it.
2. **Sheen** (LTC microfiber): `weight = closure_layering_weight(sheen_albedo, weight)`.
3. **Coat**: GGX dielectric microfacet, `fresnel_dielectric`; layer albedo
   attenuates below; underlying weight further
   `*= mix(1, coat_tint^optical_depth, coat_weight)` with
   `optical_depth = 1/cos(theta_refracted)` (Beer's law).
4. **Metallic**: GGX + `FresnelF82Tint` or `FresnelConductor`; thin-film
   params forwarded (5.0). Afterwards `weight *= (1-metallic)`.
5. **Transmission**: thick → GGX glass closure +
   `FresnelGeneralizedSchlick(ior, tint=specular_tint, sqrt(base_color),
   thin_film)`; thin_wall → `bsdf_thin_glass_setup` (single closure,
   combined R+T, no refraction offset). Afterwards
   `weight *= (1-transmission_weight)`.
6. **Specular dielectric** (if `eta != 1` or thin film): GGX +
   `FresnelGeneralizedSchlick` (`f0` from `specular_ior_level`, `f90 = 1`,
   `exponent = -eta`); layering weight via GGX directional albedo (E lookup).
7. **Subsurface**: thick → `Bssrdf` (random-walk); thin_wall →
   `bsdf_thin_subsurface_setup` (diffuse + translucent);
   `diffuse_weight = base_color * (1-subsurface_weight) * weight`.
8. **Diffuse**: `bsdf_diffuse_setup`, or `bsdf_oren_nayar_setup` when
   `diffuse_roughness > 0` (energy-preserving multiscatter Oren-Nayar / EON,
   OpenPBR behaviour).

Multiscatter GGX energy compensation rides the fresnel-setup variants
(`is_multiggx`). Backface handling adjusts the film IOR:
`adjust_thin_film_ior_at_backface(thinfilm.ior, bsdf->ior)`.

### 1.3 Thin-film model (cycles `src/kernel/closure/bsdf_util.h`)

Belcour & Barla, *A Practical Extension to Microfacet Theory for the
Modeling of Varying Iridescence*, ACM TOG 36(4), SIGGRAPH 2017. Cycles
implements the Airy-reflectance summation truncated at m=3 with complex
phasors; `OPD = -2 * film_ior * thickness * cos_theta_2`; evaluated
**per RGB channel** through a CIE sensitivity LUT
(`iridescence_lookup_sensitivity_channel`); `template<bool conductive>
fresnel_iridescence_channel(kg, channel, ambient_ior, thin_film{thickness,
ior}, substrate_n, substrate_k, F82, cos_theta_1, *r_cos_theta_3)` covers
dielectric AND conductor substrates. Thickness in nm (LUT range 0–60 µm).
Astroray note: our spectral integrator can evaluate the Airy reflectance
directly per sampled wavelength (potentially *more* faithful than Cycles'
3-channel sensitivity-LUT approach); the RGB legs should mirror Cycles'
per-channel LUT for parity. Keep both in mind at Stage-4 spec time.

### 1.4 Reference files and licenses

Cycles standalone mirror `github.com/blender/cycles` (Apache-2.0; several
closure headers carry BSD-3-Clause — both compatible, follow the existing
in-repo citation pattern used by `disney.cpp`/`energy_compensation.h`):
`src/kernel/svm/closure.h` (closure assembly + layering — the canonical
structure), `src/kernel/closure/bsdf_microfacet.h` (GGX + fresnel setups +
energy preservation), `bsdf_util.h` (fresnel + iridescence), `bsdf_sheen.h`
(LTC tables + fetch), `bsdf_oren_nayar.h` (EON), `bsdf_transparent.h`,
`bssrdf.h` (random-walk profiles). Papers: Belcour-Barla 2017; Zeltner,
Burley, Chiang, *Practical Multiple-Scattering Sheen Using Linearly
Transformed Cosines* (SIGGRAPH 2022 talk); Kulla & Conty 2017; Kutz/Hoffman
F82-tint; OpenPBR spec (EON diffuse).

---

## 2. Astroray extension-point analysis (grep-verified on main `736cd75`)

### 2.1 CPU — genuinely pluggable, low friction

- Registry: `include/astroray/register.h:26` —
  `ASTRORAY_REGISTER_MATERIAL(name, T)` installs a `ParamDict` factory in a
  string-keyed `MaterialRegistry`. `disney.cpp:918` registers `"disney"`.
- Build: `CMakeLists.txt:303` `file(GLOB_RECURSE ASTRORAY_PLUGIN_SOURCES
  CONFIGURE_DEPENDS ...)` — a new `plugins/materials/principled.cpp` needs
  **zero CMake edits** (plugins build as an OBJECT library so the
  registration static-initializers survive).
- Interface (`include/raytracer.h:424`): `sample/eval/pdf/emitted` +
  spectral — **`evalSpectral` (`:485`) is the one PURE-VIRTUAL hard
  requirement**; `sampleSpectral:494` has an upsampling default with the
  eta²-clamp guard; `Ext` variants for pkg39 profiles — +
  `closureGraph():437` (the GPU lowering) + `backendCapabilities():438`
  (validates the graph for GPU reachability) + ~14 scalar getters that form
  the `scene_upload.cu` upload ABI.
- Binding gotchas (`module/blender_module.cpp:477-505`
  `PyRenderer::createMaterial`): NO prefixed-key map or `enable_*` branch
  for materials (blanket ParamDict pass-through — the GR-emission wiring
  checklist does not apply here), BUT (a) a ctor exception is swallowed and
  silently falls back to a legacy material — test the registry name
  explicitly; (b) `params.contains("texture")` bypasses the registry
  entirely (the root cause of the addon's textured-basecolor→lambertian
  downgrade); (c) `ParamDict` float/int stores are type-segregated — use
  `getFloat` only.
- Reusable subsystems already in place: `energy_compensation.h` (Cycles
  `table_ggx_E`/`Eavg` + glass tables, Kulla-Conty layering — pkg60/151/
  160/163 lineage), VNDF sampling (pkg149), `RGBAlbedoSpectrum`
  Jakob-Hanika upsampling (beware the nonlinearity: upsample reflectance
  colour only — memory `spectral-upsample-nonlinearity-scaled-bsdf`),
  `thin_glass.cpp` (a 122-line thin-glass plugin — a starting precedent for
  Thin Wall), `oren_nayar.cpp` (qualitative O-N; EON is new),
  `subsurface.cpp` (64-line approximation — NOT a random-walk BSSRDF).

Verdict: the owner's hope holds on the CPU side — a new material is a new
file + registration, no core edits.

### 2.2 GPU — closure-graph, NOT pluggable; core edits required

- `gpu_types.h:364` `GMaterialType` enum; modern materials lower to
  `GMAT_CLOSURE_GRAPH` (dielectric and Disney already do — memory
  `gpu-dielectric-lowers-to-closure-graph`).
- `material_closure.h:15` `MaterialClosureType`: today `Diffuse,
  GGXConductor, DielectricTransmission, Clearcoat, Sheen, Emission,
  ThinGlass`. `GMaterialClosure closures[G_MAX_MATERIAL_CLOSURES]` with
  `G_MAX_MATERIAL_CLOSURES = 8` (`gpu_types.h:391,468`).
- Evaluation: `gpu_materials.h` (1769 lines) — `gpu_closure_graph_eval/
  pdf/sample/eval_spectral` (`:1379–1568`) with one-sample-MIS lobe
  recombination (pkg170's `wᵢ/W` fix lives here). Upload:
  `src/gpu/scene_upload.cu`.
- Required core edits for a faithful Principled: new/extended closure types
  (EON diffuse, F82-tint conductor, generalized-Schlick specular, coat with
  ior+tint absorption, LTC sheen, thin-film fresnel params on conductor +
  dielectric closures, thin-subsurface/translucent), per-closure param
  fields, possibly `G_MAX_MATERIAL_CLOSURES` 8→10 (the full stack can
  allocate up to 9 closures incl. transparent+emission; CPU-side cap
  `material_closure.h:40` moves in lockstep), upload plumbing
  (`scene_upload.cu:108-148` closure path preferred over a new
  `GMAT_PRINCIPLED` string arm), and eval/sample/pdf/spectral switch arms.
- **Known traps if a new `GMaterialType` is added instead of riding
  `GMAT_CLOSURE_GRAPH`:** `stage_advance.cu:109` `G_WF_NUM_MAT_TYPES = 7`
  with a SILENT clamp at `:1034-1036` (an out-of-range type shades in the
  wrong bucket, no error), duplicated as `kNumMatTypes = 7` at
  `gpu_wavefront_snapshot.cu:1412`; and `photon_caustic.cu:116-124`
  `isTransmissive` must learn any new transmissive type or caustics
  silently skip it. The closure-graph route avoids the first two entirely
  — a strong argument for it.
- LTC sheen and thin-film sensitivity data need table uploads — precedent
  exists (Cycles `shader.tables` GGX E/Eavg already ship on both legs,
  `gpu_ggx_tables.cu`, `gpu_glass_tables.cu`).
- **Extensibility unlock (design-only today):**
  `.astroray_plan/docs/pkg174-per-material-kernel-dispatch-design.md` —
  `template<int MatType>` per-bucket shade kernels off the already-sorted
  shade queues. Measured perf-neutral; its justification is exactly this
  package's problem (adding materials without growing one shared kernel's
  spill). Stage 2 should decide whether to land it as its vehicle.

### 2.3 Register-pressure risk (the known ceiling)

`stageAdvance`/`stageShadeBucketed` are pinned at 254 regs; any extra
per-hit live state spills ~2KB and tanks wavefront perf (memory
`wavefront-shade-kernels-register-saturated`; pkg168/pkg174 history; pkg174
just recovered the ceiling to owner-accepted levels). Measured attribution
(pkg174 design doc, `cuobjdump`): NEE and BSDF legs are two independent
~160-reg consumers on a ~95-reg base — new material arms inlined into
`gpu_material_sample_spectral` grow STACK spill, not REG, so the damage is
invisible to a REG-only check; watch STACK. The thin-film Airy
summation (complex phasors, per-channel loop) and LTC sheen fetch are
exactly the kind of code that spills. Mitigations, in preference order:
1. Evaluate new closures in a **dedicated shade bucket/kernel** for
   closure-graph materials carrying the new closure types, so register cost
   is isolated from the existing hot kernels (bucketing machinery exists).
2. `__noinline__` boundaries around thin-film fresnel (pkg174 measured this
   lever; mind the clock-drift protocol, memory `gpu-perf-ab-clock-drift`).
3. Precompute what is angle-independent per material (film OPD prefactor).
Protocol: `cuobjdump` per-kernel reg/spill counts before/after at every GPU
stage, and the wavefront perf gate must stay green on **non-principled**
scenes unconditionally; principled-scene perf gets its own measured budget.

### 2.4 Blender addon seam

**Two parallel Principled translation paths — both must switch together:**
the live spec-based path (`_principled_shader_spec:3055` →
`_create_material_from_shader_spec:3189`, `'disney'` literal at `:3237`
plus the `'transparent'`-kind lowering at `:3241`) and the semi-orphaned
`convert_principled_bsdf_v2:3358` (`'disney'` at `:3437`). Three literals →
one flag-aware helper. Today's mapping drops/approximates: coat
ior/tint/normal, sheen tint/roughness, specular_ior_level/tint, diffuse
roughness, SSS radius/scale/anisotropy/method, anisotropic rotation/tangent,
thin film + thin wall (entirely); **alpha is folded into
`transmission = max(transmission, 1-alpha)`** (opacity/refraction
conflation — same family as the convicted BSDF_TRANSPARENT
TRANSLATION-BUG, SSIM 0.44, which lowers transparent to a Disney ior=1.0
dielectric at `:3239-3241`); emission is heuristically promoted to a
`'light'` material; **textured base color downgrades the whole material to
textured-lambertian** (`:3227-3235` — root cause is the
`params.contains("texture")` registry bypass in `createMaterial`).
The manual-override dropdown (`CustomRaytracerMaterialSettings:705`)
enumerates `material_registry_names()` — a new registered material appears
there automatically. `shader_blending.py` normalizes principled specs and
must learn the new params too. `dist/astroray/__init__.py` is a build
artifact — never edit.

### 2.5 Verification infrastructure (exists, reusable)

- pkg119-B differential harness (Cycles-vs-Astroray, PR #550,
  `benchmarks/blender_parity/{harness,render_leg,scene_library,triage}.py`;
  runbook in memory `pkg119b-harness-runbook`) — per-feature scene pairs;
  current gates SSIM≥0.90 / mean ΔE2000≤8.0, per-channel ratio for triage
  only. A native Principled needs NO harness code change: flip the flag,
  re-run, diff `triage_report.json` flag-off vs flag-on; new rows (thin
  film, thin wall) enter by reclassifying their `coverage_matrix.json`
  cells from DROPPED-SILENT. Note these package-level gates are looser
  than pkg178's per-feature parity bands — the harness locates
  divergence, the per-lobe gates convict it.
- `benchmarks/reference_bank/` (pkg104) Cycles-as-oracle blessing + metrics;
  `benchmarks/cycles-parity/` (pkg71) paired render legs.
- pkg166 conventions: linear rendering (`apply_gamma=False`), floor AND
  ceiling bands (gamma furnaces cannot detect energy gain).
- pkg129 (narrowed) live-Cycles rough-metal A/B — composes with Stage-1
  metal-lobe acceptance (spec only, no code shipped yet; the closest
  substrate is `benchmarks/cycles-parity/` from pkg71).
- **pkg128 (thin-film iridescence) — pre-existing open spec, reconciled:**
  pkg128 already specifies Belcour-Barla thin film across
  metal/dielectric/disney + GPU + the six DROPPED-SILENT addon sockets,
  with the key design insight that **Astroray's spectral core can evaluate
  the Airy term per sampled wavelength directly** (no RGB
  sensitivity-curve fit — simpler than Cycles' own implementation).
  pkg178 Stage 4 adopts pkg128's per-λ design and implements the
  thin-film Fresnel layer ONCE as a shared utility; pkg128's residual
  charter narrows to the standalone Glass/Metallic node cells + the
  spectral showcase visuals, riding the same utility.
- Gate style: per-channel mean-ratio bands, not SSIM, for independent RNG
  streams (memory `ssim-wrong-gate-for-independent-rng`).

---

### 2.6 Highest-value design decision: spectrally native from day one

Disney's `evalSpectral` is the pkg13 shortcut — upsample the post-scale RGB
eval (`disney.cpp:700-706`). Jakob-Hanika upsampling is nonlinear in
magnitude (`upsample(k·c) != k·upsample(c)`), and this exact shortcut has
already produced three separate bug classes (pkg118/#404 eta² clamp, pkg163
metal colour-space seam, pkg168 diffuse upsample-shape). The new material
must be per-λ native in `evalSpectral`/`sampleSpectral` (upsample
reflectance COLOURS, apply scalars per-λ), matching the pattern
`gpu_metal_eval_spectral`/`MetalPlugin::evalSpectral` established. This is
the single largest correctness improvement over porting Disney's shape.

---

## 3. Swarm-decomposition assessment (honest)

The closure architecture does decompose by lobe, but NOT flat-parallel from
day one:

- **Serial spine (cannot be swarmed):** Stage 0 mapping table; the Stage-1
  scaffold — parameter dict, closure-stack assembly, the
  `closure_layering_weight` chain, lobe-selection/one-sample-MIS pdf
  recombination. This is the part where every historical Disney defect
  lived (pkg169/pkg170) and it defines the internal lobe interface.
- **Parallel-by-lobe (after the scaffold):** metal F82(+tint), transmission
  glass, coat, sheen LTC, EON diffuse, thin-film fresnel, thin-wall
  closures are separable implementation units against the scaffold's lobe
  interface, each with its own furnace + Cycles single-lobe parity gate.
  Realistic width: **3–4 lobe agents concurrently**, not a large swarm —
  beyond that they contend on shared headers and on review bandwidth.
- **Hard constraint:** delegated subagents cannot build CUDA on this
  machine (memory `delegated-agents-cant-build-cuda`) — lobe agents are
  implement-only; the lead builds, runs gates, and owns every GPU merge
  serially. GPU register budget is a global resource: one gatekeeper.
- **Bounded grunt (delegate-skill tier):** table conversion (LTC/CIE data →
  headers), scene-pair generation for the feature matrix, mapping-table
  transcription — all evidence-verified per the cost-routing policy.

Net: "a swarm of low-level agents" ≈ 1 scaffold implementer (serial), then
3–4 parallel lobe implementers + grunt delegation, converging through one
building/verifying lead. Coupling is real but the staged spec is shaped to
maximize the parallel window (Stages 3–4 lobes are independent of each
other).

---

## 4. Sources

- https://developer.blender.org/docs/release_notes/4.0/shading/
- https://developer.blender.org/docs/release_notes/5.0/cycles/
- https://projects.blender.org/blender/blender/pulls/118477 (thin film)
- https://projects.blender.org/blender/blender/pulls/157469 (thin wall, 5.2)
- https://projects.blender.org/blender/blender/pulls/123345, /123616 (EON)
- https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/principled.html
- https://github.com/blender/cycles — `src/kernel/svm/closure.h`,
  `src/kernel/closure/{bsdf_microfacet,bsdf_util,bsdf_sheen,bsdf_oren_nayar,bssrdf}.h`
- Belcour & Barla 2017 (TOG 36(4)); Zeltner/Burley/Chiang 2022; Kulla &
  Conty 2017; OpenPBR specification.
