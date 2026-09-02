# pkg225 Stage 2 — Principled Hair BSDF (Chiang 2016): algorithm research

CLAUDE.md §6 gate: no invented BSDFs. This note records the canonical sources for
the Stage-2 CPU `PrincipledHair` closure (`plugins/materials/principled_hair.cpp`
+ `include/astroray/hair_bsdf.h`) **before any engine code is written**, per the
`cite-algorithm` skill. It is the implementation contract for the parent agent.

Companion note (geometry, already landed): `pkg225-curve-intersect-research.md`.

---

## 1. Papers (cite these)

- **Chiang, Bitterli, Tappan, Burley 2016** — "A Practical and Controllable Hair
  and Fur Model for Production Path Tracing." *Computer Graphics Forum* 35(2)
  (EGSR 2016) / also presented SIGGRAPH 2015 talk.
  **DOI: 10.1145/2775280.2792559** (this is the exact DOI cited in Cycles'
  `bsdf_principled_hair_chiang.h` header). The target model for Stage 2.
- **Marschner, Jensen, Cammarano, Worley, Hanrahan 2003** — "Light Scattering
  from Human Hair Fibers." *ACM TOG* 22(3) (SIGGRAPH 2003). **DOI:
  10.1145/882262.882345.** The R/TT/TRT longitudinal-azimuthal decomposition
  Chiang builds on.
- **d'Eon, Francois, Hill, Letteri, Aubry 2011** — "An Energy-Conserving Hair
  Reflectance Model." *EGSR 2011 / CGF 30(4)*. **DOI: 10.1111/j.1467-8659.2011.01976.x.**
  Source of the Gaussian-detector longitudinal $M_p$ (Bessel-$I_0$ form) and the
  energy-conserving azimuthal treatment pbrt/Chiang use.
- **Huang, Wu, Meng, Yan 2022** — "A Microfacet-based Hair Scattering Model."
  *EGSR 2022 / CGF 41(4)*. **NOT Stage-2 scope** — see §7.

---

## 2. Reference implementations (license-compatible; mirror these)

Both are permissive and match the citation pattern already used across Astroray
(`principled.cpp`, `disney.cpp`, `curves.h`).

### 2a. pbrt-v3 `src/materials/hair.cpp` — BSD-2-Clause
- Repo: `mmp/pbrt-v3`,
  https://github.com/mmp/pbrt-v3/blob/master/src/materials/hair.cpp
- Copyright Matt Pharr / Wenzel Jakob; **BSD-2-Clause** — the *same* license
  Astroray already cites for `curves.h`. This is the textbook-canonical Chiang
  implementation (pbrt book §9.9 "Hair") and the cleanest to port a CPU BSDF
  from. Functions we mirror: `Mp`, `Np`, `Ap`, `Logistic`/`TrimmedLogistic`/
  `SampleTrimmedLogistic`, `I0`/`LogI0`, `Phi`, `SigmaAFromConcentration`,
  `SigmaAFromReflectance`, `HairBSDF::f`, `HairBSDF::Sample_f`, `HairBSDF::Pdf`,
  `HairBSDF::ApPdf`, and the `sin2kAlpha`/`cos2kAlpha` cuticle-tilt setup.

### 2b. Cycles `intern/cycles/kernel/closure/bsdf_principled_hair_chiang.h` — Apache-2.0
- Repo: `blender/blender` @ `main` (Blender 5.2-era), fetched 2026-09-02.
  Path confirmed live: `.../closure/bsdf_principled_hair_chiang.h` (481 lines).
  **Cycles split the old `bsdf_hair_principled.h` into two files**:
  `bsdf_principled_hair_chiang.h` (Chiang 2016) and
  `bsdf_principled_hair_huang.h` (Huang 2022). The node picks between them.
- Apache-2.0 (Blender Foundation) — compatible; same pattern as `principled.cpp`.
- The parameter *packing* (socket → closure) lives in
  `intern/cycles/kernel/svm/closure.h` (`CLOSURE_BSDF_HAIR_CHIANG_ID` case,
  ~line 836) and the σ_a mappings in
  `intern/cycles/kernel/closure/bsdf_util.h`
  (`bsdf_principled_hair_sigma_from_concentration` :427,
  `bsdf_principled_hair_sigma_from_reflectance` :419,
  `bsdf_principled_hair_albedo_roughness_scale` :412).

**Recommendation: port from Cycles' `bsdf_principled_hair_chiang.h` as the
primary (it *is* the "Principled Hair BSDF" the addon targets in Stage 6), and
use pbrt-v3 `hair.cpp` as the cross-check / secondary citation.** The two are
mathematically the same model; Cycles' parameter *plumbing* (melanin remap,
tint, coat→m0_roughness, radial roughness) is what the Blender node exposes, so
matching Cycles avoids a socket-remap layer.

### Code citation block for the Stage-2 files
```cpp
// Principled Hair BSDF — Chiang et al. 2016, "A Practical and Controllable Hair
// and Fur Model for Production Path Tracing", CGF 35(2). DOI:10.1145/2775280.2792559.
// Built on Marschner 2003 (DOI:10.1145/882262.882345) + d'Eon 2011
// (DOI:10.1111/j.1467-8659.2011.01976.x).
// Reference impl (primary): Blender Cycles @main —
//   intern/cycles/kernel/closure/bsdf_principled_hair_chiang.h  (Mp/Np/Ap, eval/sample)
//   intern/cycles/kernel/closure/bsdf_util.h                    (sigma_from_{concentration,reflectance})
//   intern/cycles/kernel/svm/closure.h  CLOSURE_BSDF_HAIR_CHIANG_ID  (socket packing)
//   License: Apache-2.0 (Blender Foundation) — compatible with Astroray's MIT LICENSE.
// Cross-check (secondary): pbrt-v3 src/materials/hair.cpp, BSD-2-Clause
//   (Pharr/Jakob) — same math, textbook form (pbrt §9.9).
// Per-function math notes: .astroray_plan/docs/pkg225-hair-bsdf-research.md
```

---

## 3. The model — what we reproduce

Far-field azimuthal, near-field longitudinal fiber-scattering model. BSDF is a
sum over scattering orders $p$: **R** ($p{=}0$, surface reflection), **TT**
($p{=}1$, transmission through the fiber), **TRT** ($p{=}2$, one internal
bounce), plus a **residual TRRT+** term ($p{=}3$, geometric-series tail of all
higher orders). Each order factorizes:

$$ f = \sum_{p} M_p(\theta_o,\theta_i)\; A_p(\omega_o)\; N_p(\phi) $$

Longitudinal $M_p$, azimuthal $N_p$, absorption/attenuation $A_p$. Astroray's
frame convention makes $\theta$ the angle off the normal plane (measured from the
strand tangent) and $\phi$ the azimuth in that plane.

### 3a. Longitudinal $M_p$ (roughness $\beta_m$)
d'Eon 2011 Gaussian detector via a Bessel-$I_0$ form; Cycles
`longitudinal_scattering()` (chiang.h :136). Variance $v$ per lobe, from the UI
roughness $\beta_m \in (0,1]$ (chiang.h :168):

- $v_R = v = \big(0.726\,\beta_m + 0.812\,\beta_m^2 + 3.7\,\beta_m^{20}\big)^2$
- $v_{TT} = 0.25\,v$, $v_{TRT} = 4\,v$, $v_{TRRT+} = 4\,v$
- The **R lobe uses a separate `m0_roughness`** (Chiang "Primary Reflection
  Roughness"), set from the **Coat** socket: `m0_roughness = 1 − clamp(coat,0,1)`,
  then `m0_roughness *= v`, then squared through the same $0.726/0.812/3.7$
  polynomial (svm/closure.h :918, chiang.h :165/:170).
- Numeric-stability split at $v \le 0.1$ uses `log_bessel_I0` (chiang.h :99/:145).

### 3b. Azimuthal $N_p$ (roughness $\beta_n$, absorption $\sigma_a$)
Logistic-distribution azimuthal lobe (Chiang; replaces d'Eon's more expensive
Gaussian). Cycles `azimuthal_scattering()` (chiang.h :127) over
`trimmed_logistic` (:108) trimmed to $[-\pi,\pi]$. Scale $s$ from $\beta_n$
(chiang.h :169):

$$ s = \big(0.265\,\beta_n + 1.194\,\beta_n^2 + 5.372\,\beta_n^{22}\big)\cdot\sqrt{\pi/8} $$

For R/TT/TRT the lobe is centered at $\Delta\Phi(p,\gamma_o,\gamma_t)=2p\gamma_t-2\gamma_o+p\pi$
(chiang.h :46); the residual lobe is **isotropic** azimuthally, $N_3 = 1/2\pi$
(chiang.h :327).

### 3c. Attenuation $A_p$ (Fresnel + Beer-Lambert absorption)
`hair_attenuation()` (chiang.h :199). Fresnel $f = F_{\text{dielectric}}(\cos\theta_o\cos\gamma_o,\eta)$;
transmittance through the fiber $T = \exp\!\big(-\sigma_a\cdot 2\cos\gamma_t/\cos\theta_t\big)$
(chiang.h :290, Beer-Lambert over the chord length in the cross-section):

- $A_0 = f$ (R)
- $A_1 = (1-f)^2\,T$ (TT)
- $A_2 = (1-f)^2\,T^2 f$ (TRT)
- $A_3 = A_2 \cdot \dfrac{Tf}{1 - Tf}$ (TRRT+ geometric tail) (chiang.h :220)

The per-lobe $A_p$ energies are normalized to a discrete pmf for lobe selection
in `Sample_f` (chiang.h :225). **This normalization is what keeps the model
energy-conserving** — the residual term captures the tail so no energy is
dropped.

### 3d. Geometry: $h$, $\gamma_o$, $\gamma_t$, IOR
- **IOR** $\eta = 1.55$ (keratin) — Blender node default, Cycles default,
  pbrt default all agree.
- $h \in [-1,1]$ is the ray's offset across the fiber's circular cross-section
  ($h{=}0$ dead-center, $h{=}\pm1$ grazing the silhouette). $\sin\gamma_o = h$,
  $\gamma_o = \arcsin h$ (chiang.h :282). Refracted: modified-index
  $\eta' $ handling gives $\sin\gamma_t = h\cos\theta_o/\sqrt{\eta^2-\sin^2\theta_o}$
  (chiang.h :286).
- **Cuticle tilt** $\alpha$ (Offset socket, default $2° = 2\pi/180$ rad,
  node :117). Cycles negates it in setup (`bsdf->alpha = -alpha`, chiang.h :192)
  and applies scaled tilts per lobe via `hair_alpha_angles()` (chiang.h :235):
  R uses $2\alpha$, TT uses $1\alpha$, TRT uses $4\alpha$ (the `angles[0..5]`
  pairs). pbrt uses the equivalent `sin2kAlpha`/`cos2kAlpha` with the same 1/2/4
  pattern (Marschner tilt). **Port Cycles `hair_alpha_angles` verbatim** for
  parity — the sign/scale conventions are fiddly and differ subtly from pbrt.

### 3e. σ_a parameterization (three modes — the Blender node's `parametrization`)
All three must work (spec Stage-2 decision). σ_a is naturally **spectral** — this
is the Stage-5 hook. From `bsdf_util.h` + `svm/closure.h`:

1. **Direct Absorption** (`NODE_PRINCIPLED_HAIR_DIRECT_ABSORPTION`): σ_a = the
   RGB `Absorption Coefficient` socket directly (default `(0.245531, 0.52, 1.365)`).
2. **Melanin / Pigment Concentration** (`..._PIGMENT_CONCENTRATION`):
   `melanin = -log(max(1-melanin, 1e-4))` (perceptual 0..1 → 0..∞ remap,
   svm :882); Bitterli redness split `eumelanin = melanin·(1-redness)`,
   `pheomelanin = melanin·redness` (svm :885); then
   $\sigma_a = c_e\cdot\text{eumelanin} + c_p\cdot\text{pheomelanin} + \sigma_{\text{tint}}$
   where (bsdf_util.h :430) **Cycles coefficients**:
   - $c_e$ (eumelanin) $= (0.506,\,0.841,\,1.653)$
   - $c_p$ (pheomelanin) $= (0.343,\,0.733,\,1.924)$
   - optional Tint → σ via the reflectance map below (radial roughness $\beta_n$).
3. **Direct Coloring / Reflectance** (`..._REFLECTANCE`, the node **default**):
   $\sigma_a = \big(\ln(\max(color,0)) / D(\beta_n)\big)^2$ with
   $D(\beta_n) = 5.969 - 0.215\beta_n + 2.532\beta_n^2 - 10.73\beta_n^3
   + 5.574\beta_n^4 + 0.245\beta_n^5$ (bsdf_util.h :416/:422). Inverts a target
   surface color into the absorption that produces it.

---

## 4. pbrt-v3 vs Cycles — divergences Astroray must pick between

| # | Item | pbrt-v3 `hair.cpp` | Cycles `..._chiang.h` | **Astroray pick** |
|---|------|--------------------|-----------------------|-------------------|
| 1 | **Melanin coefficients** | $c_e{=}(0.419,0.697,1.37)$, $c_p{=}(0.187,0.4,1.05)$ | $c_e{=}(0.506,0.841,1.653)$, $c_p{=}(0.343,0.733,1.924)$ | **Cycles** — addon wires Blender's node; parity is the goal |
| 2 | **Melanin input remap** | takes $c_e,c_p$ directly | perceptual `-log(1-melanin)` + Bitterli redness split + optional Tint | **Cycles** (node socket semantics) |
| 3 | **Color→σ_a poly** | identical 5.969… quintic in $\beta_n$ | identical | either (same); use $\beta_n$=radial roughness |
| 4 | **Roughness remap** | identical $0.726/0.812/3.7$ ($v$), $0.265/1.194/5.372$ ($s$) | identical | either (same) |
| 5 | **Primary-reflection roughness / Coat** | absent | `m0_roughness = (1-coat)·v` on R lobe only | **Cycles** (Coat is a Blender socket) |
| 6 | **Residual lobe** | `ApMax` geometric tail, $N=1/2\pi$ | identical `Ap[3]`, $N_3=1/2\pi$ | either (same) |
| 7 | **$h$ source** | `h = -1 + 2·uv.v` from the intersector | geometric `dot(cross(Ng,X),Z)` for thick curves | **pbrt form** — self-consistent with our pbrt-ported intersector (see §5) |
| 8 | **Cuticle-tilt application** | `sin2kAlpha/cos2kAlpha`, R:2α TT:−α TRT:−4α | `hair_alpha_angles`, R:2α TT:1α TRT:4α, `alpha=-alpha` | **Cycles `hair_alpha_angles` verbatim** (parity) |
| 9 | **Model family** | Chiang only | Chiang **and** Huang 2022 (node selectable, Chiang default) | **Chiang** (spec Stage-2; Huang deferred §7) |

Net: **port the math skeleton from Cycles `bsdf_principled_hair_chiang.h`, keep
$h$ from the pbrt intersector, cite both.** The only place pbrt wins is $h$,
because Astroray's geometry is the pbrt intersector.

---

## 5. Frame + `hair_v` → `h` — the load-bearing integration detail

The hair BSDF frame is built from the **curve tangent, not a surface normal**,
and it is **view-dependent**. Cycles (chiang.h :174/:267):
```
X = normalize(dPdu)          // longitudinal axis = strand tangent
Y = normalize(cross(X, wi))  // wi = VIEW/outgoing dir (Astroray `wo`)
Z = normalize(cross(X, Y))
local = to_local(dir, X, Y, Z); sin_theta = local.x; phi = atan2(local.z, local.y)
```
Stage 1 already hands us **`rec.uvTangent = dpdu.normalized()`** (curves.h :275)
— that is exactly $X$. So `HairBSDF` builds $X = $ `rec.uvTangent`, then
$Y,Z$ from `wo`. Because `Material::eval(rec, wo, wi)` and `sample(rec, wo, …)`
both receive `wo`, the same frame is reconstructed in eval/sample/pdf — do **not**
try to cache a fixed tangent frame on the HitRecord; rebuild it from `wo` each
call (the frame genuinely depends on the view).

**`h` from `rec.hair_v` — and a comment/code discrepancy to be aware of.** The
Stage-1 leaf sets (curves.h :243)
```
v = (edgeFunc>0) ? 0.5 + dist/(2r) : 0.5 - dist/(2r)
```
so `hair_v = 0.5` when `dist = 0` (ray through the fiber **axis** / center) and
`hair_v → 0 or 1` at `dist → r` (grazing the **silhouette edges**). This is
exactly pbrt's convention, where `hair.cpp` then does `h = -1 + 2·uv.v`. **So the
Stage-2 mapping is `h = 2·rec.hair_v − 1`** (→ `h=0` at center, `h=±1` at the
edges), matching `sin_gamma_o = h`.

> ⚠️ The prose comment on `HitRecord::hair_v` (raytracer.h :353-358) reads
> "0.5 = grazing edge facing the ray, 0/1 = the visible-hemisphere extremes,"
> which is **inverted** relative to the code above (0.5 is the center/axis hit,
> not a grazing edge). Trust the code + pbrt formula `h = 2v−1`, not the prose.
> Worth a one-line comment fix in the Stage-2 PR, but do **not** change the
> intersection math — the numeric `hair_v` is pbrt-correct.

Cycles derives `h` geometrically instead (thick curves) or from `-sd->v` (ribbon);
we don't need either — the pbrt intersector already produced the pbrt `v`.

---

## 6. Design — how `PrincipledHair` slots into Astroray

**Files (per the spec):**
- `include/astroray/hair_bsdf.h` — shared, backend-agnostic math: `logistic`,
  `trimmedLogistic`, `sampleTrimmedLogistic`, `besselI0`/`logBesselI0`,
  `Mp` (`longitudinalScattering`), `Np` (`azimuthalScattering`), `deltaPhi`,
  `hairAttenuation` (Ap + normalized pmf), `hairAlphaAngles`, and the σ_a helpers
  `sigmaAFromConcentration` / `sigmaAFromReflectance` (both an **RGB `Vec3`** and
  a **`SampledSpectrum`** overload — the Stage-5 seam). Header-only so Stage 3/4
  GPU can `#include` the same functions (mark them so they compile under
  `__device__` later — plain `static inline`, no STL in the hot path).
- `plugins/materials/principled_hair.cpp` — `class PrincipledHair : public Material`.

**Material interface mapping** (`include/raytracer.h` :458):
- `evalSpectral(rec, wo, wi, lambdas)` is **pure-virtual → must implement**, and
  is the *natural primary* here: σ_a is spectral, so the spectral path is
  first-class (no Jakob-Hanika round-trip needed even in Stage 2 — sigma is a
  per-λ absorption). Implement the full Mp·Ap·Np sum with a `SampledSpectrum`
  σ_a and `T = exp(-σ_a · …)`.
- `eval(rec, wo, wi)` / `pdf` / `sample(rec, wo, gen)` (RGB): implement with a
  `Vec3` σ_a (the RGB mode) so RGB renders and NEE MIS work. `pdf` returns the
  energy-weighted `F_energy` sum (chiang.h :333) — the model's own pdf; this
  makes `f/pdf ≈ weight` directly testable.
- `sampleSpectral` default wraps `sample` (raytracer.h :550) — but that default
  routes through the RGBAlbedo-LUT eta² clamp, which is wrong for hair. **Override
  `sampleSpectral`** to select a lobe from the spectral $A_p$ pmf, sample the
  tilted-$M_p$ longitudinal angle + trimmed-logistic azimuth (chiang.h :382-451),
  and return `f_spectral` directly. Do not reuse the dielectric-glass wrapper.
- Flags: `isGlossy()→true`, `isTransmissive()→true` (TT lobe crosses the fiber),
  `getIOR()→1.55`. `getAlbedo()` can use `bsdf_principled_hair_albedo` (chiang.h
  :467) for the denoiser albedo AOV.
- Registration: `ASTRORAY_REGISTER_MATERIAL("principled_hair", PrincipledHair)`
  (mirror `disney.cpp` :948); add to `MaterialRegistry` per spec.

**σ_a behind a function boundary (Stage-5 readiness).** Compute σ_a in
`sigmaARGB(...)` and `sigmaASpectral(..., lambdas)` only — never inline the
melanin/color math into the lobe loop. Stage 5 then swaps `sigmaASpectral` for a
per-wavelength melanin cross-section (`hair_melanin_spectral.h`) with **zero**
change to the lobe code. The three parametrization modes (direct / melanin /
reflectance) are a switch inside those two helpers, decided at ctor from the
addon params.

**Ctor params (match the Blender node so Stage 6 needs no remap):** `roughness`
$\beta_m$, `radial_roughness` $\beta_n$, `coat` (→ m0_roughness), `ior` (1.55),
`offset` $\alpha$ (2°), `parametrization` enum, and the mode-specific inputs
(`color`; `melanin`+`melanin_redness`+`tint`; `absorption_coefficient`), plus
`random`/`random_color`/`random_roughness` (per-strand variation — Stage 2 can
accept a single `random` float; the per-strand attribute wiring is Stage 6).
Do the roughness→(v,s) and melanin remaps **once in the ctor** (like
`principled.cpp` precomputes), not per hit.

**GPU / register implications (flag now, keep Stage 2 CPU-only):**
- Mp uses `bessel_I0` / `sinh` / `log`; the sampler adds `atan2`/`log`/trig.
  This is transcendental-heavy → on the GPU shade fleet (REG:254-pinned,
  see MEMORY `wavefront-shade-kernels-register-saturated`) it **will** spill.
  Stage 4 **must** isolate behind `template<bool HasHair>` (the `HasPrincipled`
  D4 pattern, MEMORY `closure-graph-lobe-count-spills-fused-kernel`) so non-hair
  scenes pay zero registers. Acceptance gate: `cuobjdump` REG unchanged for
  non-hair materials.
- The hair BSDF is **not** a sum of GGX/diffuse closures → it does **not** fit
  the pkg36 closure-graph lowering. Make it a standalone `GMAT_HAIR_PRINCIPLED`
  branch (spec Stage-4 already says this is allowed), not a closure-graph node.
- Per-strand `random` rides the geometry side data (`GCurveSegment` extra float
  / the `c_wfTexBinding` side-table pattern, MEMORY `shade-axis-side-table-avoids-spill`),
  read from the hit, **not** stored in `GMaterial` (keeps GMaterial at 640 B).
- Keep `hair_bsdf.h` STL-free in the hot path so Stage 3/4 can `#include` it into
  `.cuh` unchanged.

---

## 7. Deliberately NOT in Stage 2

- **Huang 2022 near-field model** (`bsdf_principled_hair_huang.h`, EGSR 2022).
  Cycles ships it as the **other** selectable model (node `model` enum), but the
  Blender node **defaults to Chiang** and pkg225's spec explicitly targets Chiang
  2016. Huang adds an `Aspect Ratio` socket (elliptical cross-section) and R/TT/TRT
  lobe-weight sockets. **File as a follow-up** if the owner wants elliptical fur;
  not Stage-2 scope. (Node sockets that only appear under Huang: `Aspect Ratio`,
  `R lobe`, `TT lobe`, `TRT lobe` — the addon should hide these when the material
  uses the Chiang path.)
- **Volumetric fiber scattering** (Zinke & Weber 2007) — spec non-goal.
- **GPU** (Stages 3-4), **spectral melanin cross-sections** (Stage 5), **addon
  wiring** (Stage 6).

---

## 8. Blender 5.2 node `ShaderNodeBsdfHairPrincipled` — socket set (Stage-6 target)

Confirmed from `source/blender/nodes/shader/nodes/node_shader_bsdf_hair_principled.cc`
(fetched 2026-09-02). Two dropdowns in the node header: **`model`** (default
`CHIANG`) and **`parametrization`** (default `REFLECTANCE` / Direct Coloring).
Input sockets + defaults:

| Socket | Default | Shown when |
|--------|---------|-----------|
| Color | (0.017513, 0.005763, 0.002059) | parametrization = Reflectance |
| Melanin | 0.8 | parametrization = Pigment Concentration |
| Melanin Redness | 1.0 | Pigment Concentration |
| Tint | (1,1,1) | Pigment Concentration |
| Absorption Coefficient | (0.245531, 0.52, 1.365) | Direct Absorption |
| Aspect Ratio | 0.85 | **model = Huang only** |
| Roughness ($\beta_m$) | 0.3 | always |
| Radial Roughness ($\beta_n$) | 0.3 | **model = Chiang only** |
| Coat | 0.0 | **model = Chiang only** |
| IOR | 1.55 (keratin) | always |
| Offset ($\alpha$ tilt) | 2° = 2π/180 rad | always |
| Random Color | 0.0 | Pigment Concentration |
| Random Roughness | 0.0 | always |
| Random | (hidden attribute input) | always |
| R lobe / TT lobe / TRT lobe | 1.0 each | **model = Huang only** |
| **output** BSDF | — | — |

Stage-2 CPU material should accept the **Chiang + all-three-parametrization**
subset (everything except the Huang-only sockets). This is a clean 1:1 socket
mapping — the reason the spec chose Cycles-parameterization parity.

---

## 9. Acceptance-gate ideas (Stage-2 `tests/test_pkg225_hair_bsdf.py`)

1. **White-furnace / energy conservation.** Integrate the BSDF (importance-sampled,
   or hemisphere-swept over $\theta_i,\phi_i$) for a set of
   $\{\beta_m,\beta_n,\eta,\sigma_a{=}0\}$; directional albedo must be **≤ 1.0**
   (energy-conserving). With $\sigma_a{=}0$ (no absorption) and white illumination
   it should approach 1.0 minus the residual tail. Assert an **upper bound** (a
   gamma-free linear integral — MEMORY `gamma-furnace-hides-energy-gain`).
2. **f/pdf consistency.** Since `pdf` returns the model's `F_energy`, verify
   `eval(wo,wi)/pdf(wo,wi)` matches the `sample()` returned weight within MC
   tolerance across many random $(wo,wi)$. Cheaper and stricter than a full χ².
3. **Reciprocity (approximate).** The frame is view-dependent, so treat
   reciprocity as approximate — assert `f(wo,wi) ≈ f(wi,wo)` within a loose
   tolerance and document that the far-field Chiang model is only near-reciprocal.
4. **Melanin → color cross-check.** Assert `sigmaAFromConcentration` at the Cycles
   coefficients reproduces published brown/black (eumelanin) vs red (pheomelanin)
   trends; e.g. pure eumelanin → σ_a rising toward blue (absorbs blue least → red
   passes → brown), pure pheomelanin → the redder $(0.343,0.733,1.924)$ profile.
   Numeric check against the exact coefficient triples.
5. **Azimuthal-roughness sweep vs Cycles.** Render a hair swatch (sphere-of-strands
   or a curved tuft) at $\beta_n \in \{0.1, 0.3, 0.6, 1.0\}$ and compare to a
   Cycles reference render **per-channel mean-ratio in [0.95,1.05]** (independent
   RNG → mean-ratio, **not** SSIM — MEMORY `ssim-wrong-gate-for-independent-rng`).
   This is the visual parity gate; keep it out of the fast unit suite.
6. **Regression guard.** Non-hair scenes byte-identical (the material only
   activates on curve hits where `hair_u/hair_v ≠ -1`).

---

## Open questions for the parent / owner

- **Coat socket semantics:** Cycles maps Coat→`m0_roughness = (1-coat)·v` (a
  primary-reflection-roughness knob), *not* a separate clearcoat lobe. Confirm we
  replicate that (recommended) rather than adding a real coat lobe.
- **`random` in Stage 2:** accept a single scalar now; defer the per-strand
  geometry-attribute plumbing to Stage 6 (matches how Cycles reads it from a curve
  attribute). OK?
- Fix the inverted `HitRecord::hair_v` prose comment (raytracer.h :353-358) in the
  Stage-2 PR? (code is correct; only the comment misleads.)
