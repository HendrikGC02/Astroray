# pkg178 Stage 0 — Cycles Principled BSDF → Astroray closure/parameter map

**Owner-review artifact (pkg176 Stage-0 discipline).** Human-readable mirror of
the machine-readable twin `docs/blender_parity/pkg178_stage0_closure_map.json`
(single source of truth for tooling). No silent mapping decisions: every Cycles
Principled input and every closure in the stack has a row here with an explicit
realization tag and, where lossy, the delta + the gate band it implies.

Reference pin: Cycles `main` (Blender 5.2-era) —
`src/kernel/svm/closure.h` (`CLOSURE_BSDF_PRINCIPLED_ID`) +
`src/kernel/closure/{bsdf_util,bsdf_microfacet,bsdf_oren_nayar,bsdf_sheen,
bssrdf}.h`. Math citations: `.astroray_plan/docs/pkg178-stage1-closure-math-research.md`
and the architect's package note `cycles-principled-port-research-2026-08.md`.

## Realization vocabulary

| tag | meaning |
|---|---|
| `DIRECT` | existing Astroray closure / energy-comp table reused unchanged. |
| `NEW-CLOSURE` | exact Cycles port written for this package. |
| `APPROXIMATED` | nearest behaviour; the delta + gate band it implies is stated. |
| `DEFERRED` | not this stage; the owning follow-up stage/agent is named. |

## Owner decisions encoded (D1–D3, ratified 2026-08-08)

- **D1 (Blender 5.2 oracle):** yes — installed before Stage 4. Stage 0/1 verify
  against 5.1; Thin Wall (5.2) / conductor thin-film parity legs wait for 5.2.
- **D2 (subsurface):** APPROXIMATE-first. Stage 1 does NOT implement subsurface.
  A SEPARATE parallel agent builds random-walk BSSRDF. Subsurface rows below are
  `DEFERRED (owner: parallel random-walk BSSRDF agent)`; Stage 1 leaves the
  documented lobe-contract seam (`diffuse_weight = base_color·(1-subsurface_weight)·weight`).
- **D3 (addon rollout):** flag-first, default OFF until the Stage-5 parity matrix
  is green; default flip is a separate owner sign-off. Stage 5 concern, noted here.
- **D4 (Stage-2 register budget):** conditional; only surfaces at Stage 2. N/A here.

## Stage ownership of this package

| stage | scope | this PR |
|---|---|---|
| Stage 0 | this table + JSON twin | **DONE (this PR)** |
| Stage 1 | CPU core lobes (`plugins/materials/principled.cpp`) | **DONE (this PR)** |
| Stage 2 | GPU closure-graph twin | DEFERRED (lead builds/verifies; subagents can't build CUDA) |
| Stage 3 | coat / sheen LTC / anisotropy / emission+alpha / subsurface(D2) | DEFERRED (parallel lobe agents) |
| Stage 4 | Thin Film (Belcour-Barla, pkg128 utility) + Thin Wall (5.2) | DEFERRED |
| Stage 5 | addon flag-first switch (D3) | DEFERRED |

## Parameter map (Cycles Principled inputs)

Astroray param names accept the Cycles socket name; `base_color` also accepts the
legacy `albedo` alias (the addon/`create_material` `base_color` positional).

| Cycles input | Astroray param | realization | delta / band / note |
|---|---|---|---|
| `base_color` (RGB) | `base_color` / `albedo` | DIRECT | reflectance colour upsampled per-λ (JH); never albedo·cos (pkg168). |
| `metallic` | `metallic` | DIRECT | layer weight + F82 f0 driver. |
| `roughness` | `roughness` | DIRECT | GGX α = roughness² (floored 0.0064). |
| `ior` | `ior` | DIRECT | specular F0 + transmission Fresnel; `exponent=-ior` reparam. |
| `alpha` | `alpha` | APPROXIMATED | Stage 1: parsed, clamped [0,1]; a real Transparent lobe is DEFERRED (Stage 5, retiring the `transmission=max(t,1-alpha)` conflation). Band: opacity untested until Stage 5; default 1.0 (opaque). |
| `normal` | (shading normal via HitRecord) | DIRECT | uses `rec.normal`; per-lobe normal offsets (coat) DEFERRED. |
| `diffuse_roughness` | `diffuse_roughness` | NEW-CLOSURE | drives EON (Fujii + OpenPBR multiscatter); 0 → Lambert. |
| `specular_ior_level` | `specular_ior_level` | NEW-CLOSURE | `f0 = F0_from_ior(ior)·2·level`; default 0.5 → plain dielectric F0. |
| `specular_tint` (RGB) | `specular_tint` | NEW-CLOSURE | generalized-Schlick reflection tint + F82 edge tint. |
| `transmission_weight` | `transmission_weight` / `transmission` | DIRECT | rough-glass lobe weight; layered `weight*=(1-t)`. |
| `subsurface_weight` | `subsurface_weight` | DEFERRED (owner: parallel random-walk BSSRDF agent) | seam only: reduces diffuse by `(1-subsurface_weight)`. Not sampled in Stage 1. |
| `subsurface_radius` (RGB) | — | DEFERRED (BSSRDF agent) | — |
| `subsurface_scale` | — | DEFERRED (BSSRDF agent) | — |
| `subsurface_ior` | — | DEFERRED (BSSRDF agent) | — |
| `subsurface_anisotropy` | — | DEFERRED (BSSRDF agent) | negative anisotropy (5.2) included in that scope. |
| `subsurface_method` | — | DEFERRED (BSSRDF agent) | — |
| `anisotropic` | — | DEFERRED (Stage 3) | isotropic GGX only in Stage 1. |
| `anisotropic_rotation` | — | DEFERRED (Stage 3) | — |
| `tangent` | — | DEFERRED (Stage 3) | — |
| `coat_weight` | — | DEFERRED (Stage 3) | — |
| `coat_roughness` | — | DEFERRED (Stage 3) | — |
| `coat_ior` | — | DEFERRED (Stage 3) | — |
| `coat_tint` (RGB) | — | DEFERRED (Stage 3) | Beer absorption `tint^(1/cosθ_r)`. |
| `coat_normal` | — | DEFERRED (Stage 3) | — |
| `sheen_weight` | — | DEFERRED (Stage 3) | LTC microfiber (Zeltner 2022). |
| `sheen_roughness` | — | DEFERRED (Stage 3) | — |
| `sheen_tint` (RGB) | — | DEFERRED (Stage 3) | — |
| `emission_color` (RGB) | — | DEFERRED (Stage 3) | node emission (retiring addon promote-to-light). |
| `emission_strength` | — | DEFERRED (Stage 3) | — |
| `thin_film_thickness` (nm) | — | DEFERRED (Stage 4) | Belcour-Barla per-λ Airy; rides pkg128 utility. |
| `thin_film_ior` | — | DEFERRED (Stage 4) | — |
| `thin_wall` (bool) | `thin_wall` | DEFERRED (Stage 4) | parsed/ignored in Stage 1; combined-R+T thin glass + thin subsurface. |

## Closure-stack map (Cycles `CLOSURE_BSDF_PRINCIPLED_ID`, top-down)

| # | Cycles closure | Fresnel model | Astroray realization | tag |
|---|---|---|---|---|
| 1 | Emission | — | DEFERRED (Stage 3) | DEFERRED |
| 2 | Sheen (LTC) | — | DEFERRED (Stage 3) | DEFERRED |
| 3 | Coat (GGX dielectric) | `fresnel_dielectric` | DEFERRED (Stage 3) | DEFERRED |
| 4 | Metallic (GGX) | F82-tint | `Metallic` lobe: GGX + F82 (`fresnel_f82{tint_B,}`) + `ggxDarkeningChannel` comp | NEW-CLOSURE |
| 5 | Transmission (GGX glass / thin) | generalized-Schlick | `Transmission` lobe: Walter 2007 rough glass + `ggxGlassCompensationFactor`, `sqrt(base_color)` tint (thick only; thin_wall Stage 4) | DIRECT (estimator) + APPROXIMATED (tinting: reflection uses dielectric F, not full generalized-Schlick reflection_tint yet — band ±0.03 vs Cycles on tinted transmission at high roughness) |
| 6 | Specular dielectric (GGX) | generalized-Schlick `exp=-ior` | `Specular` lobe: GGX + generalized-Schlick real-reparam + `ggxCompensationFactor` | NEW-CLOSURE |
| 7 | Subsurface (Bssrdf / thin) | — | DEFERRED (owner: parallel random-walk BSSRDF agent, D2) | DEFERRED |
| 8 | Diffuse (Lambert / Oren-Nayar) | — | `Diffuse` lobe: Lambert, or EON (Fujii + OpenPBR multiscatter) at `diffuse_roughness>0` | NEW-CLOSURE |
| — | Transparent (`1-alpha`) | — | DEFERRED (Stage 5) | DEFERRED |
| — | layering `closure_layering_weight` | — | ported (bsdf_util.h) + `ggxDirectionalAlbedo` spec-albedo (pkg145) | NEW-CLOSURE |
| — | multiscatter GGX comp | — | `astroray::ggxDarkeningChannel` + `DisneyEnergyCompensationTables` | DIRECT |
| — | VNDF sampling | — | Heitz 2018 / pbrt-v4 (shared with disney.cpp) | DIRECT |

### Stage-0 realization counts (Stage-1 rows only)

- **DIRECT:** 7 (base_color, metallic, roughness, ior, transmission_weight, normal; + multiscatter/VNDF/glass-estimator infra)
- **NEW-CLOSURE:** 5 (diffuse_roughness/EON, specular_ior_level, specular_tint, specular lobe, metallic F82 lobe, layering chain)
- **APPROXIMATED:** 2 (alpha; transmission reflection tinting)
- **DEFERRED:** 21 (all Stage 3/4/5 inputs + subsurface D2)

## Lobe-interface contract (the seam parallel lobe agents code against)

Defined in `plugins/materials/principled.cpp`. The scaffold assembles a small
ordered set of `PrincipledLobe` values per shade point (view-dependent layering),
then recombines them with one-sample MIS. A new lobe (coat/sheen/aniso/thin-film/
SSS) is added by: (a) an enum value in `LobeKind`, (b) an arm in each of the four
free evaluators, (c) a row in `assembleLobes` slotting it into the Cycles layering
order with its `closure_layering_weight` attenuation. NO change to the MIS
recombination is needed — that is the invariant the contract protects.

```
enum class LobeKind { Diffuse, Specular, Metallic, Transmission,   // Stage 1
                      /* seam: */ Coat, Sheen, Subsurface };        // Stage 3+

struct PrincipledLobe {
    LobeKind kind;
    Vec3  weight;      // spectral layering weight (RGB; upsampled per-λ in the spectral path)
    Vec3  color;       // lobe reflectance colour (base_color, specular f0, or sqrt(base_color))
    float roughness;   // GGX α source (0 for Lambert)
    float ior;
    float sel;         // scalar selection weight = luminance(weight·approx_albedo); Σsel = W
    bool  isDelta;     // smooth glass → true (excluded from continuous eval/pdf sums)
};

// The four evaluators each lobe kind must implement an arm in:
SampledSpectrum evalLobeSpectral(const PrincipledLobe&, rec, wo, wi, lambdas);  // BSDF·cos, per-λ native
Vec3            evalLobeRGB     (const PrincipledLobe&, rec, wo, wi);           // RGB twin
float           pdfLobe         (const PrincipledLobe&, rec, wo, wi);           // solid-angle pdf
bool            sampleLobe      (const PrincipledLobe&, rec, wo, gen, &wi, &isDelta);
```

**MIS recombination invariant (do not re-derive per lobe — pkg170):**
`eval_total = Σ wᵢ·fᵢ`; `W = Σ selᵢ`; `pdf_total = Σ_{continuous} (selᵢ/W)·pdfᵢ`;
sample picks lobe `j` with prob `selⱼ/W`. `eval` and the selection use the SAME
`wᵢ`/`selᵢ` (matched). Layering keeps `Σ wᵢ·albedoᵢ ≤ 1`, so no `1/W` on eval.

**Spectral-nativeness contract:** every lobe's `evalLobeSpectral` upsamples
reflectance COLOURS via `RGBAlbedoSpectrum` and applies achromatic scalars per-λ.
Copying the Disney RGB-upsample shortcut (`disney.cpp:700-706`) is a contract
violation (pkg118/163/168 bug class).

## Per-lobe acceptance-gate matrix

Every lobe lands (this stage or a later one) with these gates. Stage-1 gates are
CPU-only (GPU + on-hardware Cycles parity DEFERRED to the lead at Stage 2).
Conventions: linear (`apply_gamma=False`), floor AND ceiling (pkg166), per-channel
mean-ratio not SSIM (independent RNG, pkg121/ssim-wrong-gate).

| lobe | Stage-1 CPU gate | later-stage gate (deferred) |
|---|---|---|
| Diffuse (Lambert) | white furnace ratio ∈ [0.85, 1.05]; chi² sampler accept (α=0.01) | Cycles diffuse-sweep per-channel ratio [0.95,1.05] |
| Diffuse (EON, `diffuse_roughness>0`) | furnace ∈ [0.80, 1.05] (multiscatter-boosted floor); chi² accept | Cycles EON roughness sweep [0.95,1.05] |
| Specular dielectric | furnace ∈ [0.90, 1.05] (plastic: spec+diffuse conserving); chi² accept | Cycles IOR / specular-level sweep [0.95,1.05] |
| Metallic (F82) | furnace ∈ [0.90, 1.05] at metallic=1; chi² accept (roughness ≥ 0.4) | pkg129 live-Cycles rough-metal A/B; F82 edge-tint hue |
| Transmission (rough glass) | furnace ∈ [0.85, 1.05]; peak-alignment (reuses disney glass gate) | Cycles transmission sweep; thin-film (Stage 4) |
| Coat / Sheen / Aniso / Thin-film / Thin-wall / SSS | — (deferred) | each: CPU+GPU furnace + Cycles single-feature parity on landing |

## Verification status of THIS PR (Stage 0 + Stage 1)

- CPU only. GPU (Stage 2) and on-RTX Cycles image-plane parity are DEFERRED to
  the building/verifying lead — NOT claimed here.
- Measured CPU furnace + chi² numbers are in the PR body.
