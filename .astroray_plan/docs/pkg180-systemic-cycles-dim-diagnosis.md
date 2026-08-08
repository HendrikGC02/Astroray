# pkg180 — systemic ~12–20% Astroray-vs-Cycles dim: diagnosis note

**Status:** Phase 1 + Phase 2 COMPLETE (2026-08-09). Phase-1 verdict: **NOT a
comparison-methodology artifact** (honest linear comparison). Phase-2 verdict:
**REAL ENGINE-CORE DEFECT, LOCALIZED AND NAMED** — dedicated (non-hittable)
lights are invisible to BSDF-sampled rays while NEE still pays the MIS power-
heuristic complement, so the BSDF-share of every non-delta lamp's direct
lighting is silently discarded and lamp reflections in specular surfaces are
near-black (the owner's 2026-08-09 observation, reproduced at 58× too dark).
See §Phase 2 below for the measurement table, the named mechanism, the fix
charter, and the sequencing recommendation (pkg172(A) re-pin WAITS).

---

## Baseline being explained (from the filing, do not re-derive)

Three independent readings on main (RTX 5070 Ti + Blender 5.1, linear ratio
Astroray/Cycles):

| Measurement | Ratio | Scene |
| --- | --- | --- |
| pkg119-B differential harness (passing cells) | ~0.88 | shader-node sphere + backdrop + area light + world 0.6 |
| pkg129 metal A/B, neutral r0.9 | ~0.93 | Disney metal sphere, roughness-dependent on top of a baseline offset |
| plain solid-diffuse backdrop probe | ~0.79–0.82 | backdrop-only (area light + world 0.6), the simplest scene, the LARGEST dim |

Signature: a uniform, chromatically-uniform ~12–20% energy-scale offset. A
uniform achromatic scale across unrelated materials/scenes is the fingerprint of
a global-exposure / comparison difference OR a global light/world energy
translation factor — not a per-feature BSDF bug.

## Phase 1 — comparison-methodology audit (blocking; cheapest first)

Audited leg-by-leg against the actual harness code on main (`570477b`).

### 1. View transform / color management — MATCHED (ruled out)
Both `benchmarks/blender_parity/render_leg.py` and
`benchmarks/cycles-parity/metal_ab/render_leg.py`, in `_configure_render`, set on
BOTH legs (Cycles and CUSTOM_RAYTRACER):
```
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure       = 0.0
scene.view_settings.gamma          = 1.0
scene.render.image_settings.file_format = "OPEN_EXR"   # 32-bit, codec NONE
```
Output is a 32-bit linear scene-referred EXR; `_render_to_npy` reads it back via
`bpy.data.images.load(...).pixels[:]` (no colorspace override → linear buffer for
an EXR). **Both engines are written and read in the same scene-linear space.**
This is the pkg180 prime suspect (the `gamma-vs-linear-comparison-artifact`
family that has burned the project before) and it is NOT present here — the
harnesses were already hardened (pkg166 "linear: Standard view transform"
comment in the metal leg). Ruled out.

### 2. Exposure / film settings — MATCHED (ruled out)
`view_settings.exposure = 0.0` and `gamma = 1.0` on both legs; no tonemap is
applied to one leg only; `film_transparent = False` both. No stray exposure.

### 3. Sample / normalization + world contribution — MATCHED (ruled out as a
*comparison* asymmetry; see caveat)
`scene_library.build_scene(bpy, ..., engine=args.engine)` builds ONE scene body
per feature and both engine legs run the SAME builder. World strength/color and
light energies are literals shared by both legs:
- `_add_world` sets the same `strength`/`color` for both engines.
- `_add_area_light(energy=200)`, `LIGHT_CONFIGS` energies, etc. are identical per
  leg.
- The ONLY engine-specific scene difference is a documented 180° area-light flip
  for the Astroray leg (`engine == "CUSTOM_RAYTRACER"` in `build_light_scene`,
  the pkg122 +Z-area-normal convention) — an orientation fix, not an energy
  change.

Both engines therefore receive identical *input* energy and are compared in
identical *output* space. **The comparison protocol is honest.**

## Phase 1 verdict

The ~0.88 / ~0.93 / ~0.79–0.82 dim is **not** a view-transform, exposure, or
normalization artifact — it survives an apples-to-apples linear comparison of
identically-energised scenes. Therefore it is one of:

- **(H1) A scene-translation energy factor** — the Astroray addon converts
  Blender light `energy` (watts) and world `strength` into its own radiometric
  units; if that conversion is ~15–20% low vs Cycles' convention, every lit scene
  is uniformly dim. The backdrop probe being the LARGEST dim (~0.80, area-light +
  world only, no complex BSDF) points here.
- **(H2) A real engine transport offset** — a direct-lighting solid-angle /
  light-normalization factor, or an indirect-throughput difference.

These are distinguished by an **analytic scene** (Phase 2): a single diffuse
surface (ρ known) under a single known-irradiance light, no world, where the
expected outgoing radiance `L = ρ·E/π` is computable and tells us WHICH engine is
off the analytic truth — and, by running the Astroray leg BOTH via the addon
(in-Blender translation path) AND via the standalone `astroray.Renderer()` API
(engine only, no addon translation), whether the offset lives in the translator
(H1) or the engine core (H2).

## Consequence for sequencing (owner-facing)

Because the dim is real (not a display artifact), **the pkg172(A) supervised
gate re-pin must wait for Phase 2 localization.** pkg172(A) is a
+0.628%/bounce diffuse brightening — small next to a 15–20% dim. Re-pinning the
whole repo's parity/energy gates now would bake the unlocalized dim into the new
baselines and mask whatever Phase 2 finds. Order: pkg180 Phase 2 → localize →
(if the dim is a defect, its own fix spec with architect sign-off) → THEN the
pkg172(A) coordinated re-pin on a clean baseline.

Also: pkg178's per-lobe Cycles-parity gates inherit this offset. Until Phase 2
lands, pkg178 parity numbers should be read as *relative* (lobe-to-lobe), with
the systemic offset annotated, not as absolute Cycles parity.

## Phase 2 — localization (COMPLETE 2026-08-09; no fix shipped, CLAUDE.md §6)

Measurement setup: RTX 5070 Ti machine, all Astroray legs **CPU device**
(pkg129: GPU≈CPU), linear EXR/linear buffers throughout, pinned nonzero seeds.
Cycles oracle: Blender 5.1 headless, CPU, view transform Standard, exposure 0,
gamma 1, 512 spp. Standalone legs: `build_cuda/astroray.cp313-win_amd64.pyd`
(mtime 2026-08-08 20:36, newer than HEAD `570477b`). Addon legs:
`build_blender_addon_cuda` OpenMP-off pyd (same-day, 5 h pre-HEAD — the missing
commits are pkg178 closure-map work that does not touch light/NEE code).
Probe scripts archived at `.astroray_plan/docs/pkg180-phase2-probes/`
(`standalone_probe*.py` — run with repo python; `blender_leg.py` — run per
engine via `blender --background --factory-startup --python ... -- --scene
<s> --engine <e> --out <stem>`); scenes mirror the pkg122 oracle configs.

### Localization table (luminance, linear; ratios are Astroray/Cycles)

| Probe | Analytic | Cycles | Astroray standalone (engine core) | Astroray addon | Reading |
| --- | --- | --- | --- | --- | --- |
| SUN E=π, diffuse ρ=0.5 floor (expected L=ρE/π=0.5) | 0.5 | 0.50000 | **0.50008** | 0.626 † | Engine core EXACT for (near-)delta lights; no global units/exposure error anywhere in the chain |
| 3×3 AREA lamp 300 W @ h=3, floor center (pkg122 config) | 1.2704 (point value) | 1.2494 | **1.1616 (0.930×)** | **1.1510 (0.921×)** | The systemic dim, reproduced on the simplest scene; addon/standalone = 0.991 → **translator (H1) exonerated; engine core (H2) convicted** |
| Same, `max_depth=1` vs `8` (standalone) | — | — | identical (1.1616 both) | — | **Direct-lighting mechanism**, not indirect throughput / RR / clamp |
| Same geometry, radiance-matched HITTABLE emissive mesh quad (standalone, off-axis probe) | 0.6312 | — | 0.972× analytic | — | Hittable emitters ≈ unbiased; deficit is **dedicated-lamp-specific** (dedicated/mesh differential 0.978 vs 0.975 predicted) |
| Mirror (glossy r=0.05) — reflection of a 100 W 2×2 AREA lamp | ≈7.16 | 7.155 | **0.013** | **0.123 (0.017×)** | **Owner's observation, quantified: the reflected lamp is ~58× too dark** |
| Mirror — reflection of a radiance-matched emissive MESH plane | ≈7.16 | 7.151 | 7.215 | 6.902 (0.965×) | Reflection is correct when the emitter is hittable — convicts lamp non-hittability, not the glossy BSDF |

† Addon SUN excess (+25%) is the KNOWN pkg122 verifier finding (translated
Diffuse BSDF carries a baseline Fresnel-specular lobe; vanishes with pure
`lambertian`). Opposite sign to the dim; separate pre-existing issue.

Numeric cross-check: integrating the NEE power-heuristic weight over the 3×3
lamp predicts a kept fraction of **0.9415** at the floor center (0.975 at the
off-axis probe point); measured kept fractions are 0.915–0.930 (0.978
differential off-axis). The mechanism quantitatively accounts for the deficit
(the 1–2% residual is patch-averaging over the irradiance falloff plus MC
noise).

### The named mechanism

**Dedicated lights are invisible to BSDF-sampled rays, but NEE still pays the
MIS complement as if they weren't.**

- `astroray::Light` is by design "first-class light interface (sibling to
  Hittable, not derived from it)" (`include/astroray/light.h:3`). Every lamp
  the Blender addon translates — POINT/SUN/AREA/SPOT via
  `add_*_dedicated` (`blender_addon/__init__.py:4150–4217`) — is a dedicated
  light: never in the BVH, and there is no lamp-intersection pass. A
  BSDF-sampled continuation ray aimed at a lamp hits nothing.
- The NEE leg (`include/raytracer.h:2457–2487`) weights every non-delta light
  sample by the power heuristic `wt = a²/(a²+b²)` (`a` = solid-angle light pdf
  × selection, `b` = BSDF pdf), budgeting for the complementary BSDF-sampled
  leg. That complement (`raytracer.h:2416–2447`, the pkg120 two-sided MIS
  term) only fires when a ray *hits an emissive Hittable* — structurally
  impossible for dedicated lights. Exactly the BSDF-share of every dedicated
  lamp's direct lighting is therefore discarded at every diffuse/glossy
  vertex, and lamp reflections in specular/low-roughness surfaces are
  near-black (NEE is skipped on delta lobes entirely; `wt→0` as roughness→0).
- The loss scales with the lamp's subtended solid angle (ratio `b/a`): large,
  close area lamps lose the most; a 0.526° sun loses ~nothing (measured
  0.50008 vs 0.5). This explains the whole baseline pattern: backdrop probe
  worst (~0.79–0.82: big close area lamp, grazing geometry), pkg119-B sphere
  cells ~0.88, metal r0.9 ~0.93 (spikier `b`), sun/delta scenes clean.
- **GPU wavefront is structurally identical** (`src/gpu/gpu_nee.cuh:438`
  `wt = isDeltaLight ? 1 : powerHeuristic(lightPdf, bsdfPdf)`; no lamp
  intersect in `stage_advance.cu`) — consistent with pkg129's GPU≈CPU on the
  dim.
- Cycles reference behavior (what parity requires): `lights_intersect`
  (`intern/cycles/kernel/light/light.h`, Apache-2.0) intersects lamp objects
  along BSDF-sampled rays and `light_sample_from_intersection` adds the
  MIS-weighted emission — the half Astroray never collects. (Cycles lamps stay
  invisible to camera rays; only indirect/BSDF rays see them.)

### Side findings (flag, do not fix here)

1. **Stale 180° AREA-lamp flip in the harnesses (post-pkg139).**
   `benchmarks/blender_parity/scene_library.py::build_light_scene` and
   `scripts/verify_pkg122_cycles_oracle.py` still flip the AREA lamp for the
   Astroray leg. pkg139 already fixed the addon axis convention (identity
   rotation measured 0.921× here, i.e. correct orientation + the systemic
   dim); the flipped leg now renders **black** (measured 0.00000). The
   pkg119-B `light:AREA` cell is currently comparing a black frame — remove
   the flips and re-baseline when the fix lands.
2. Addon-translated Diffuse BSDF ≠ pure Lambertian under SUN (0.626 vs 0.500)
   — the known pkg122 baseline-Fresnel-lobe finding, separate follow-up.
3. GPU NEE still divides by `(lightPdf + 0.001)` (`gpu_nee.cuh:440`) — the
   additive-epsilon family pkg172(A) removed on CPU. Small; fold into the
   pkg172(A) GPU twin.

### Disposition

**(a) Is the dim a real defect?** Yes. Engine core (H2), both devices,
direct-lighting MIS accounting for dedicated lights. Not the translator
(addon/standalone = 0.991), not view-transform/exposure (Phase 1), not
indirect transport (depth-1 invariant), not a units error (sun exact vs
analytic). The same mechanism produces both the uniform 7–20% scene dim and
the owner's dark-lamp-reflection observation — one defect, two symptoms.

**(b) File a fix spec?** Yes — charter below (implementation NOT started, per
this package's diagnosis-only mandate). Proposed id **pkg181, Track A**:

> **pkg181 — Dedicated-light visibility to BSDF rays (Cycles
> `lights_intersect` parity).** Add a lamp-intersection pass for dedicated
> lights: `Light::intersect(ray, tMin, tMax)` for Area, Point(radius>0),
> Spot(radius>0), Distant(angle>0); in `pathTraceSpectral` (and the GPU
> wavefront advance/shade stages) test dedicated lights against the BVH-hit
> distance for **non-camera rays only** (Cycles semantics: lamps invisible to
> camera rays), and feed hits into the EXISTING pkg120 two-sided MIS term —
> `LightList::pdfValue` already sums dedicated lights
> (`PowerLightSampler::pdfValue`), so the weight machinery is complete; only
> the intersection is missing. Cite Cycles `kernel/light/light.h`
> `lights_intersect` + `light_sample_from_intersection` (Apache-2.0) in code
> (CLAUDE.md §6). Respect spot cone / area spread / one-sidedness via the
> existing per-type falloff so a back-face hit stays dark.
> **Gates (all linear, floor+ceiling):** (1) mirror-lamp A/B ≥0.95× Cycles
> (was 0.017×); (2) pkg122 AREA floor A/B in [0.97,1.03] (was 0.921×);
> (3) SUN analytic 0.5 within ±1% (regression guard); (4) furnace suites
> unchanged; (5) render-level suites (`reflection_not_black`,
> `material_properties`) re-run, not just new gates; (6) CPU/GPU agreement on
> probes (1)–(3); (7) remove the stale harness AREA flips (side-finding 1)
> and re-baseline pkg119-B + pkg129 ratio bands.
> **Risks:** wavefront shade stages are register-saturated (REG:254) — lamp
> intersect belongs in the advance/intersection stage, not shade; pin the
> wavefront snapshot capture moment at spec time; light-tree (`Tree` sampler)
> `pdfValue` path must be exercised too. **Rejected alternative:** setting
> `wt=1` for dedicated lights (NEE-only estimator) — unbiased for diffuse and
> would close the uniform dim, but lamp reflections stay black on delta lobes
> and near-black at low roughness, i.e. it does NOT fix the owner's
> observation and diverges from Cycles' estimator; parity requires the
> intersect.

**(c) pkg172(A) re-pin sequencing?** **Wait.** Firm recommendation: the dim is
a localized, mechanism-named defect 10–25× larger than pkg172(A)'s
+0.628%/bounce correction, concentrated exactly in the area-lit scenes the
supervised gates are pinned on. Re-pinning now bakes a known defect into every
baseline and forces a second coordinated re-pin weeks later. Order:
pkg181 fix → RTX hardware sweep → ONE coordinated re-pin (pkg172(A) +
pkg119-B bands + pkg129 metal bands + pkg178 lobe gates) on the clean
baseline. Until then pkg178 parity numbers stay relative (lobe-to-lobe) with
the offset annotated, unchanged from the Phase-1 note.
