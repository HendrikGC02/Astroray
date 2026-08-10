# Research note — pkg178 Stage 4: Thin Film (Belcour-Barla) + Thin Wall

**Date:** 2026-08-10. **Author:** architect (cite-algorithm discipline, CLAUDE.md §6).
**Scope:** the canonical paper + the exact Cycles reference implementation to port for
pkg178 Stage 4 (Thin Film iridescence on Principled specular/transmission/conductor
lobes + Thin Wall translucency) and the shared thin-film Fresnel utility pkg128 rides.
**All code excerpts below were verified VERBATIM against blender/blender `main`
(fetched 2026-08-10, raw.githubusercontent.com), not paraphrased from summaries.**

---

## 1. Canonical paper

Laurent Belcour, Pascal Barla. **"A Practical Extension to Microfacet Theory for the
Modeling of Varying Iridescence."** ACM Transactions on Graphics 36(4), Article 65,
SIGGRAPH 2017. DOI: 10.1145/3072959.3073620.
Project page (paper + supplemental code):
https://belcour.github.io/blog/research/publication/2017/05/01/brdf-thin-film.html

Model summary (the parts Cycles implements):

- A thin dielectric film (thickness `d` nm, IOR `n1`) sits on a substrate (dielectric
  `n2` or conductor `n2 + i·k2`). Light reflecting off the film interferes with light
  that bounced inside the film, producing wavelength-dependent (iridescent)
  reflectance. The film replaces the microfacet Fresnel term `F(cosθ)`; the microfacet
  distribution/sampling machinery is untouched.
- **Airy summation (paper Eq. 10, series form):** total reflectance is a geometric
  series over internal-bounce order `m`; each term carries a phase
  `m·(2π·OPD/λ + φ)` where the **optical path difference** is
  `OPD = 2·n1·d·cosθ2` (θ2 = in-film refraction angle) and `φ` is the phase shift on
  reflection at the two interfaces (polarization-dependent). Evaluated separately for
  S- and P-polarization, then averaged.
- **Spectral→RGB integration (paper §4):** an RGB renderer must integrate
  `R(λ)·CMF(λ)` over the visible range. The paper's trick: in the Fourier domain this
  becomes a rapidly-converging series against the **Fourier transform of the CMFs**
  ("sensitivity functions") — one lookup per bounce order `m` at `m·OPD`.
- **Truncation:** Cycles truncates the series after `m = 3` ("higher differences have
  barely any impact" — the residual is O(r123⁴)).

**Key spectral-core observation (pkg128's design, confirmed):** for a SINGLE
wavelength λ, the sensitivity function degenerates to the exact complex exponential
`S(m·OPD) = exp(i·2π·m·OPD/λ)` (a delta-function CMF; DC-normalized to 1). So the
spectral legs evaluate the SAME truncated Airy series with an analytic `S` and need
**no LUT at all** — simpler than Cycles' own path, and exact per sampled λ. The RGB
legs mirror Cycles' CIE-sensitivity LUT for like-for-like parity.

Note: pkg128's spec line "do not copy GPL Cycles source" is **stale** — the relevant
Cycles files are BSD-3-Clause / Apache-2.0 (verified below, and pkg128 §B itself says
Apache-2.0). Verbatim porting with per-function citation is license-clean and is the
established pkg178 pattern (`principled.cpp`, `energy_compensation.h`).

---

## 2. Cycles reference implementation (blender/blender `main`, 2026-08-10)

### 2.1 Files, functions, licenses (pin these in code citations)

| File | License | Functions (line @ main 2026-08-10) |
|---|---|---|
| `intern/cycles/kernel/closure/bsdf_util.h` | **BSD-3-Clause** | `FresnelThinFilm` :20 (`{float thickness; float ior;}`), `complex<T>` :25, `fresnel_dielectric_polarized` :47, `fresnel_dielectric` :94, `fresnel_dielectric_Fss` :131, `fresnel_f82_Fss` :140, `fresnel_f82tint_B` :146, `fresnel_f82_B` :161/:169, `fresnel_f82` :178/:186, `fresnel_conductor_polarized` :200, `fresnel_conductor` :262, `closure_layering_weight` :440, `iridescence_lookup_sensitivity_channel` :456, `iridescence_airy_summation_channel` :468, `fresnel_iridescence_channel` :499 |
| `intern/cycles/kernel/closure/bsdf_microfacet.h` | **BSD-3-Clause** | `adjust_thin_film_ior_at_backface` :86, `generalized_schlick_setup` :110, `generalized_schlick_fresnel` :264 (thin-film branch :274–298), `microfacet_fresnel` :335 (CONDUCTOR film :361–375, F82_TINT film :388–404), `microfacet_ggx_preserve_energy` :432, `bsdf_microfacet_estimate_albedo` :498 (film fallback :513/:540), `bsdf_microfacet_setup_fresnel_generalized_schlick` :941, `bsdf_microfacet_setup_fresnel_f82_tint` :980, **thin glass block :1218–1428**: `bsdf_thin_glass_fresnel` :1236, `bsdf_thin_glass_reflection_setup` :1284, `bsdf_thin_glass_transmission_roughness` :1307, `bsdf_thin_glass_transmission_setup` :1312, `bsdf_thin_glass_transmission_eval` :1348, `bsdf_thin_glass_transmission_sample` :1357, `bsdf_thin_glass_setup` :1392 |
| `intern/cycles/kernel/svm/closure.h` | **Apache-2.0** | Principled assembly: thin-film stack loads :301–304, metallic F82 + film :320–352, `thin_wall` load :360, transmission thick/thin fork :362–423 (backface adjust :400–403), specular + film :437–472, thin subsurface fork :480–484, diffuse :514–521 |
| `intern/cycles/kernel/svm/types.h` | Apache-2.0 | `#define THINFILM_THICKNESS_CUTOFF 0.1f` :577 |
| `intern/cycles/kernel/types.h` | Apache-2.0 | `#define THIN_FILM_TABLE_SIZE 512` :37 |
| `intern/cycles/kernel/closure/bsdf_oren_nayar.h` | BSD-3-Clause | `bsdf_thin_subsurface_setup` :169 |
| `intern/cycles/scene/shader.cpp` | **Apache-2.0** | `ShaderManager::compute_thin_film_table` :932 (XYZ→scene-RGB transform + DC normalization of the CMF FFT) |
| `intern/cycles/scene/shader.tables` | **Apache-2.0** | `table_thin_film_cmf[512][6]` :1287 — precomputed resampled+FFT'd CIE XYZ CMFs (re/im × XYZ) |
| `intern/cycles/doc/precompute/thin_film_table.py` | Apache-2.0 | generator for the table above (CIE 1931 2° CMFs → frequency reparametrization → FFT) |

History pins: dielectric thin film Blender PR #118477 (4.2); conductor thin film 5.0;
Thin Wall PR #157469 (5.2). Oracle: **Blender 5.2** (D1 — satisfied, installed).

### 2.2 The exact math to port (verified verbatim)

**Polarized dielectric Fresnel** (`bsdf_util.h:47`): returns `(r_s², r_p²)` per
polarization; outputs `cos_theta_t` (negative, relative to the normal:
`cos_theta_t = -sqrt(η² − (1 − cos²θi))/η`) and the reflection phase as
`r_cos_phi = (sign(r_s), sign(r_p))` — for a dielectric the phase shift is 0 or π, so
the phasor is real ±1. Amplitudes:
```
r_s = (cosθi + η·cosθt) / (cosθi − η·cosθt)
r_p = (cosθt + η·cosθi) / (η·cosθi − cosθt)
```
TIR ⇒ returns `(1,1)` (and the film reflectance is exactly 1 — both TIR early-outs in
`fresnel_iridescence_channel` return 1.0).

**Polarized conductor Fresnel** (`bsdf_util.h:200`): Born & Wolf §14.4.1 form with
`n + ik` convention; computes `u, v` from `t1 = η2²−k2²−η1²(1−cos²θ)`,
`t2 = sqrt(t1² + (2η2k2)²)`, `u² = max(½(t2+t1),0)`, `v² = max(½(t2−t1),0)`. Returns
R_s, R_p and, when requested, unit phasors `exp(i·φ_s)`, `exp(i·φ_p)`:
```
phasor_s ∝ (−u²−v² + (η1·cosθ)²,  −2·η1·cosθ·v)                      (re, im; normalized)
phasor_p ∝ ((η2²+k2²)²cos²θ − η1²(u²+v²),  2η1cosθ(2η2k2·u − (η2²−k2²)v))
```
**F82 branch inside it** (`F82 >= 0`): reflectance magnitude comes from the F82 model
(`F0` recomputed from film-relative `n = η2/η1`, `k² = (k2/η1)²`), while the PHASE
still comes from the physical n,k — this is how Cycles keeps the artist-facing F82
metal model consistent under a film.

**Airy summation** (`bsdf_util.h:468`, paper Eq. 10):
```
T121 = 1 − R12;  R123 = R12·R23;  r123 = sqrt(R123);  Rs = T121²·R23/(1 − R123)
R = Rs + R12                             /* C0 term */
Cm = Rs − T121
for m = 1..3:
    Cm *= r123
    S = sensitivity(channel, m·OPD)      /* complex */
    R += Cm · 2·(phasor^m).Re⋅S.Re + (phasor^m).Im⋅S.Im   /* i.e. 2·Re(phasor^m · conj-free dot) */
```
(`accumulator = phasor^m` built incrementally by complex multiply.)

**Top-level per-channel driver** (`fresnel_iridescence_channel`, `bsdf_util.h:499`,
`template<bool conductive>`):
1. Sub-1nm blend: `film_ior = mix(ambient_ior, film_ior, smoothstep(0,1,thickness))`
   when `thickness < 1.0f` (wave-optics regime cutoff; keeps the limit continuous).
2. Top interface: `R12 = fresnel_dielectric_polarized(cosθ1, film_ior/ambient_ior,
   &cosθ2, &phasor12_real)`; TIR ⇒ return 1.
3. Bottom interface: conductor ⇒ `fresnel_conductor_polarized(−cosθ2, film_ior,
   {n,k}, F82, …)` with complex phasors; dielectric ⇒
   `fresnel_dielectric_polarized(−cosθ2, substrate_n/film_ior, r_cos_theta_3, …)`
   with real ±1 phasors; TIR ⇒ return 1. **`r_cos_theta_3` is the substrate
   refraction cosine the glass lobe uses for the refracted direction** — the film is
   optically thin and does not displace the ray.
4. `OPD = −2·film_ior·thickness·cosθ2` (positive: cosθ2 is negative).
5. Full phase per polarization: `phasor = phasor23 · (−phasor12_real)`; run the Airy
   summation per polarization; result `saturatef(0.5·(R_s + R_p))`.

**RGB sensitivity LUT** (`bsdf_util.h:456` + `scene/shader.cpp:932`): LUT domain
`x = 2π·OPD/60000` (OPD in nm; covers 0–60µm), 512 entries × 6 (re/im × RGB). Host
side: precomputed **FFT of the frequency-resampled CIE XYZ CMFs**
(`shader.tables:1287`) is multiplied by the working-space XYZ→RGB matrix (linear ops
commute with the FFT) and normalized so the DC term is 1 (`i==0` row). Astroray's
working space is fixed (Rec.709-linear), so the XYZ→RGB multiply can be **baked at
table-generation time** — no runtime transform needed.

**Per-λ spectral legs (Astroray simplification):** replace step "S = LUT lookup" with
`S = {cos(2π·m·OPD/λ), sin(2π·m·OPD/λ)}` — exact, no table, structurally identical
code. Document at the call site that Belcour §4's RGB projection is intentionally
omitted on the spectral path (pkg128 rationale; the RGB and spectral legs will differ
slightly in hue BY CONSTRUCTION — record, don't gate-fail).

### 2.3 How the film slots into the Principled closures (svm/closure.h)

Common: `thinfilm_thickness` is read once; `thinfilm_ior` is forced to 0 when
`thickness ≤ THINFILM_THICKNESS_CUTOFF` (0.1nm) (:301–304). Film active ⇔
`thickness > 0.1f`.

- **Metallic (F82_TINT)** (:320–352 + `bsdf_microfacet.h:388–404`): the F82 fresnel
  struct carries the film. At eval time, per channel: estimate physical `n,k` from
  `(F0=f0, g=F82(1/7-angle value))` via **Gulbrandsen, "Artist Friendly Metallic
  Fresnel"** (JCGT 2014) reinterpretation:
  ```
  r = min(f0, 0.999);  g = fresnel_f82(1/7, f0, b_channel)
  n = mix((1+√r)/(1−√r), (1−r)/(1+r), g);  k = safe_sqrt((r(n+1)² − (n−1)²)/(1−r))
  ```
  then `fresnel_iridescence_channel<true>(…, n, k, F82=g, cosθ1, …)`.
  **Astroray optimization (safe):** f0/f82 are per-material constants ⇒ the n,k
  inversion can be host-precomputed at upload/ctor time (Cycles recomputes per shade
  only because its fresnel structs are per-hit allocations).
- **Transmission thick glass (GENERALIZED_SCHLICK)** (:386–419 +
  `bsdf_microfacet.h:274–298`): film lives in `FresnelGeneralizedSchlick`; at eval,
  per channel `F = fresnel_iridescence_channel<false>(…, ior, 0, −1, cosθ, &cosθt)`
  then the **F0-rescale block** (artistic control; port verbatim):
  ```
  F0_real = F0_from_ior(ior)
  if F0_real > 1e-5 and F != 1:
      s = saturate(inverse_lerp(1.0, F0_real, F_channel))
      F_channel *= mix(1.0, f0_channel/F0_real, s)
  ```
  Transmittance = `(1−F)·transmission_tint` (tint = `sqrt(base_color)`).
  `kernel_assert(exponent < 0 && f90 == 1)` — film only supported on the
  real-Fresnel-remap variant (exactly Principled's configuration).
  **Backface** (:395–403): `bsdf->ior = 1/ior` and
  `adjust_thin_film_ior_at_backface(thinfilm.ior, bsdf->ior)` — i.e.
  `film_ior *= 1/bulk_ior` (the stack `bulk | film | air` is optically equivalent to
  `air | film/bulk | 1/bulk`; comment at `bsdf_microfacet.h:86–108`).
- **Specular dielectric** (:437–472): same GENERALIZED_SCHLICK path (reflection-only,
  `f0 = F0·specular_tint`, `f90 = 1`, `exponent = −eta`). **Lobe activation condition
  becomes `eta != 1.0f || thinfilm_thickness > 0.1f`** — the film forces a specular
  lobe even at IOR 1. Layering weight still via `bsdf_albedo` +
  `closure_layering_weight`.
- **Energy compensation — the no-double-counting rule:** `microfacet_ggx_preserve_energy`
  is fed the FILM-FREE Fss estimate (`fresnel_f82_Fss`, generalized-Schlick Fss —
  `bsdf_microfacet.h:941–1001`), and `bsdf_microfacet_estimate_albedo` explicitly
  falls back to the film-free approximation ("Precomputing LUTs for thin-film
  iridescence isn't viable", :513/:540). **The film replaces only the single-scatter
  F; multiscatter compensation stays on the base-Fresnel tables.** Mirror this
  exactly: reuse `energy_compensation.h` unchanged; do NOT invent a film-aware Fss.
- **Register-pressure precedent:** Cycles' own comment (three sites): *"One channel at
  a time to reduce GPU register pressure"* — the per-channel loop is the reference
  implementation's own mitigation; adopt it on the GPU leg.

### 2.4 Thin Wall (Blender 5.2, PR #157469)

Reference: OpenPBR thin-walled case
(https://academysoftwarefoundation.github.io/OpenPBR/#model/thin-walledcase) as
implemented in `bsdf_microfacet.h:1218–1428` + `bsdf_oren_nayar.h:169`.

- `thin_wall` bool socket (:360). Two closures change meaning:
- **Transmission ⇒ `bsdf_thin_glass_setup`** (:368–385): ONE analytic R+T split, two
  lobes:
  - `bsdf_thin_glass_fresnel` (:1236): front-side `(r1, t1)` from
    `generalized_schlick_fresnel` (film included if active); back side `(r2, t2)`
    from a second generalized-Schlick evaluated at `(−cosθt, inv_ior=1/ior)` with the
    film IOR backface-adjusted — or `(r2,t2)=(r1,t1)` when no film. Beer-Lambert
    through the sheet: `c = transmission_tint^(−1/cosθt)` (tint = clamped base_color
    = the normal-incidence transmittance). Infinite internal-bounce geometric series,
    closed form:
    ```
    T' = c·t1·t2 / (1 − (r2·c)²)
    R' = r1 + T'·r2·c
    ```
  - **Reflection lobe** (:1284): standard GGX reflection, `ior=1`, constant Fresnel
    `R'` (weight), roughness = α.
  - **Transmission lobe** (:1312): the double refraction through a thin sheet does
    not bend the ray; modeled as a MIRRORED reflection (`N → −N`, eval/sample against
    `reflect(wi, N)`, `bsdf_microfacet.h:1348–1390`) with **roughened alpha**
    (Kulla & Conty, "Revisiting Physically Based Shading at Imageworks", p.40 — the
    3.7 in the slides is a typo for 1.7·2 = 3.4):
    ```
    α_T = saturate(α · sqrt(3.4·(η−1)·(η−0.5)² / η³))
    ```
    Near-specular α_T ⇒ pure transparent passthrough (`wo = −wi`, delta). Closure
    type `CLOSURE_BSDF_THIN_GLASS_TRANSMISSION_ID`; its energy-preservation lookup
    uses the REFLECTION `ggx_E/Eavg` tables (`:442–447`), NOT the glass tables — it
    is geometrically a reflection lobe.
- **Subsurface ⇒ `bsdf_thin_subsurface_setup`** (:480–484, `bsdf_oren_nayar.h:169`):
  diffuse + translucent split by `subsurface_anisotropy` g:
  ```
  reflection_weight   = saturate(0.5·(1−g)) · weight   (diffuse,     front hemisphere)
  transmission_weight = saturate(0.5·(1+g)) · weight   (translucent, back hemisphere)
  ```
  with Oren-Nayar variants of both when `diffuse_roughness > 0`. Note: this consumes
  the `subsurface_anisotropy` socket, which Astroray's Principled does not yet parse
  (Stage-3 D2=a approximation didn't need it) — Stage 4 adds it.
- **Astroray note:** the existing `plugins/materials/thin_glass.cpp` is an ad-hoc
  cone-sampling plugin — reuse its NAME/registry precedent only; the math above is
  the port target. `MaterialClosureType::ThinGlass` (GPU standalone closure) is
  untouched by Stage 4; the Principled monolithic closure carries its own thin-wall
  params. Re-pointing `thin_glass.cpp` at the new utility is pkg128-residual/follow-up
  territory, not Stage 4.

### 2.5 Conductor vs dielectric differences (summary table)

| Aspect | Dielectric substrate (`<false>`) | Conductor substrate (`<true>`) |
|---|---|---|
| Bottom Fresnel | `fresnel_dielectric_polarized(−cosθ2, n2/n1)` | `fresnel_conductor_polarized(−cosθ2, n1, {n,k}, F82)` |
| Bottom phasor | real ±1 (phase 0 or π) | full complex `exp(iφ)` from Born-Wolf |
| TIR at bottom | possible ⇒ R=1 | impossible |
| `r_cos_theta_3` | returned (glass refraction dir) | unused (no transmission) |
| n,k source | `ior` socket | Gulbrandsen inversion of (F0, F82) per channel |
| Used by lobes | specular, transmission glass, thin-glass | metallic (F82_TINT) |
| Backface | film IOR ÷ bulk IOR (transmission only) | n/a |

---

## 3. Sources

- Belcour & Barla 2017, ACM TOG 36(4):65, DOI 10.1145/3072959.3073620 (+ project page).
- Gulbrandsen 2014, "Artist Friendly Metallic Fresnel", JCGT 3(4) (n,k from r,g).
- Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks" (thin-glass
  transmission roughening p.40; multiscatter Fms).
- Born & Wolf, *Principles of Optics* 7th ed., §14.4.1 (conductor phase shifts).
- OpenPBR spec, thin-walled case (Apache-2.0).
- blender/blender `main` files/lines/licenses as tabled in §2.1 (fetched 2026-08-10).
- Blender PRs #118477 (film, 4.2), #157469 (thin wall, 5.2); 5.0 release notes
  (conductor film).
- Prior in-repo research: `.astroray_plan/docs/cycles-principled-port-research-2026-08.md`
  §1.3; pkg128 spec (per-λ design).
