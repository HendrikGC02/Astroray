# Disney Energy Compensation Research

**Package:** pkg60 — Disney v2 Energy Compensation (No-Glow Materials)  
**Date:** 2026-05-09  
**Branch:** `codex/pkg60-disney-energy-compensation`  
**Status:** research note only; no implementation started.

---

## Sources Fetched

### Kulla & Conty 2017

- **Title:** "Revisiting Physically Based Shading at Imageworks"
- **Authors:** Christopher Kulla and Alejandro Conty
- **Venue:** ACM SIGGRAPH 2017 Courses, *Physically Based Shading in Theory
  and Practice*
- **DOI:** `10.1145/3084873.3084893`
- **Fetched URL:** https://blog.selfshadow.com/publications/s2017-shading-course/imageworks/s2017_pbs_imageworks_slides_v2.pdf
- **Relevant sections:** "Microfacet Energy Compensation" slides/notes,
  pages 9-19 in the extracted PDF text; "Sheen" pages 104-109.

### Cycles Reference Implementation

- **Repository:** https://github.com/blender/cycles and Blender mirror
  https://github.com/blender/blender
- **Overall Cycles repo license:** Apache-2.0 (`LICENSE` in `blender/cycles`).
- **Files fetched:**
  - `src/kernel/closure/bsdf_microfacet.h`
    https://raw.githubusercontent.com/blender/cycles/main/src/kernel/closure/bsdf_microfacet.h
  - `src/kernel/closure/bsdf_sheen.h`
    https://raw.githubusercontent.com/blender/cycles/main/src/kernel/closure/bsdf_sheen.h
  - `src/scene/shader.tables`
    https://raw.githubusercontent.com/blender/cycles/main/src/scene/shader.tables
  - `src/app/cycles_precompute.cpp`
    https://raw.githubusercontent.com/blender/cycles/main/src/app/cycles_precompute.cpp
  - `src/scene/shader.cpp`
    https://raw.githubusercontent.com/blender/cycles/main/src/scene/shader.cpp
  - `src/kernel/svm/closure.h`
    https://raw.githubusercontent.com/blender/cycles/main/src/kernel/svm/closure.h

### Burley 2015

- **Title:** "Extending the Disney BRDF to a BSDF with Integrated Subsurface
  Scattering"
- **Author:** Brent Burley
- **Venue:** SIGGRAPH 2015 course notes, *Physically Based Shading in Theory
  and Practice*
- **DOI/arXiv:** no paper-specific DOI or arXiv ID found in the primary PDF.
  Secondary references cite it as ACM SIGGRAPH 2015 Courses with ISBN
  `9781450336345`. The DOI `10.1145/2775280.2792555` found in searches refers
  to a related SIGGRAPH 2015 talk by Christensen, not this Burley note.
- **Fetched URL:** https://blog.selfshadow.com/publications/s2015-shading-course/burley/s2015_pbs_disney_bsdf_notes.pdf

---

## License Findings

The spec expectation "Apache-2.0 / CC0" is close but not exact for the
specific Cycles files:

| File | SPDX header observed | Compatibility note |
|---|---|---|
| `src/kernel/closure/bsdf_microfacet.h` | `SPDX-License-Identifier: BSD-3-Clause`; copyright Sony Pictures Imageworks and Blender Foundation | BSD-3-Clause is permissive and compatible with Astroray's MIT license, but any port must preserve attribution/notice. |
| `src/kernel/closure/bsdf_sheen.h` | `SPDX-License-Identifier: Apache-2.0`; copyright Blender Foundation | Compatible with MIT, with Apache notice obligations. |
| `src/scene/shader.tables` | `SPDX-License-Identifier: Apache-2.0`; copyright Blender Foundation | Compatible with MIT, with Apache notice obligations. |
| `src/app/cycles_precompute.cpp` | `SPDX-License-Identifier: Apache-2.0`; copyright Blender Foundation | Compatible with MIT, with Apache notice obligations. |
| `src/scene/shader.cpp` | `SPDX-License-Identifier: Apache-2.0`; copyright Blender Foundation | Compatible with MIT, with Apache notice obligations. |

No CC0 LUT source was found in current Cycles. The LUT data is generated into
`src/scene/shader.tables` as Apache-2.0 static float arrays.

---

## Math To Reproduce

Kulla & Conty define directional albedo for the single-scatter microfacet BRDF:

```text
E(mu_o) = integral_over_hemisphere f_ss(mu_o, mu_i, phi) * mu_i dmu_i dphi
```

For a perfectly reflective microfacet model, the target furnace-test albedo is
1. Missing energy is:

```text
1 - E(mu_o)
```

Their added multiple-scattering lobe is:

```text
f_ms(mu_o, mu_i) =
    (1 - E(mu_o)) * (1 - E(mu_i))
    / (pi * (1 - E_avg))

E_avg = 2 * integral_0^1 E(mu) * mu dmu
```

The paper notes that a 32x32 table over `(roughness, mu)` is sufficient for GGX,
with an additional 32-entry 1D table for `E_avg`.

For Fresnel/tinted cases, the Kulla & Conty notes add the average-Fresnel
multiple-bounce factor:

```text
F_ms = F_avg * E_avg / (1 - F_avg * (1 - E_avg))
```

Cycles' current implementation applies this through `microfacet_ggx_preserve_energy(...)`:

```text
missing_factor = (1 - E) / E
energy_scale = 1 + missing_factor = 1 / E
Fms = Fss * E_avg / (1 - Fss * (1 - E_avg))
darkening = (1 + Fms * missing_factor) / energy_scale
```

The closure weight is multiplied by `darkening`, and GGX eval/sample paths are
multiplied by `energy_scale`. This means the simple scalar factor quoted in the
pkg60 spec, `1 + (1 - E) / E`, is correct only for the white/no-Fresnel
energy-preservation part. For colored Fresnel lobes, the Cycles port must also
carry the `Fms`/`darkening` adjustment or it will over-brighten saturated
materials.

---

## Cycles Implementation Facts

### Function Names

The spec names `microfacet_ggx_E`; current Cycles does **not** expose a function
with that name. The relevant current function is:

- `src/kernel/closure/bsdf_microfacet.h:microfacet_ggx_preserve_energy(...)`

Important line findings from fetched current Cycles:

- `bsdf_microfacet.h:389` defines `microfacet_ggx_preserve_energy`.
- `bsdf_microfacet.h:400-401` samples reflection `ggx_E` as 32x32 and
  `ggx_Eavg` as 32.
- `bsdf_microfacet.h:414-415` samples glass `ggx_glass_E` as 16x16x16 and
  `ggx_glass_Eavg` as 16x16.
- `bsdf_microfacet.h:423-436` implements `missing_factor`, `energy_scale`,
  `Fms`, and `darkening`.
- `bsdf_microfacet.h:1048` multiplies GGX eval by `energy_scale`.
- `bsdf_microfacet.h:1065` multiplies sampled GGX eval by `energy_scale`.

### LUT Dimensions

From `src/scene/shader.tables` and `src/app/cycles_precompute.cpp`:

| Table | Cycles symbol | Dimensions | Float count |
|---|---|---:|---:|
| GGX reflection directional albedo | `table_ggx_E` | 32 x 32 | 1024 |
| GGX reflection average albedo | `table_ggx_Eavg` | 32 | 32 |
| GGX glass directional albedo | `table_ggx_glass_E` | 16 x 16 x 16 | 4096 |
| GGX glass average albedo | `table_ggx_glass_Eavg` | 16 x 16 | 256 |
| GGX inverse-ior glass directional albedo | `table_ggx_glass_inv_E` | 16 x 16 x 16 | 4096 |
| GGX inverse-ior glass average albedo | `table_ggx_glass_inv_Eavg` | 16 x 16 | 256 |
| Sheen LTC | `table_sheen_ltc` | 3 planes x 32 x 32 | 3072 |
| Generalized Schlick lookup | `table_ggx_gen_schlick_ior_s` | 16 x 16 x 16 | 4096 |
| Generalized Schlick lookup | `table_ggx_gen_schlick_s` | 16 x 16 x 16 | 4096 |

### Sheen Discrepancy

The pkg60 spec says to inspect `bsdf_sheen.h` for "Conty & Kulla 2017 sheen".
Current Cycles `bsdf_sheen.h` instead cites:

```text
"Practical Multiple-Scattering Sheen Using Linearly Transformed Cosines" (2022)
Tizian Zeltner, Brent Burley, Matt Jen-Yuan Chiang
```

Current Cycles sheen setup:

- samples `table_sheen_ltc` transform A at `offset + 0 * 32 * 32`;
- samples transform B at `offset + 1 * 32 * 32`;
- samples albedo at `offset + 2 * 32 * 32`;
- multiplies closure weight and sample weight by that albedo;
- uses the LTC transform in eval/sample.

Kulla & Conty 2017 pages 104-105 describe Imageworks' "Charlie" sheen and say
they store sheen albedo in a 16x16 table indexed by roughness and incident
angle, using `min(1 - E(mu_o), 1 - E(mu_i))` scaling to avoid energy gain.
That is **not** the same as current Cycles' 32x32 LTC sheen.

### Clearcoat Discrepancy

No `clearcoat_E` or clearcoat-specific table was found in current Cycles. In
current Cycles Principled setup (`src/kernel/svm/closure.h`):

- coat allocates a `MicrofacetBsdf`;
- coat uses `bsdf_microfacet_ggx_setup(bsdf)`;
- coat calls `bsdf_microfacet_setup_fresnel_dielectric(...)`;
- that path invokes `microfacet_ggx_preserve_energy(...)` for GGX dielectric
  reflection.

So a Cycles-faithful port should likely use the GGX `E` / `E_avg` path for coat
rather than inventing a separate `clearcoat_E.bin`, unless the project owner
explicitly wants an Astroray-specific clearcoat table.

---

## Astroray-Specific Findings Before Code

Astroray already contains an inline `GGXEnergyCompensationLUT` and
`ggxMultiScatterCompensation(...)` in `include/raytracer.h`, and
`plugins/materials/disney.cpp` adds an ad-hoc multi-scatter term:

```text
Fms = ggxMultiScatterCompensation(NdotV, NdotL, roughness_)
msWeight = roughness_ * (2 - roughness_)
dielectricMs = F0 * (Fms * msWeight * 0.5) * NdotL
conductorMs = F0 * (Fms * msWeight * 1.3)
```

This is not the current Cycles formula. It also lives in `include/raytracer.h`,
which pkg60's prompt did not list as an implementation target. During the code
phase we should either:

1. replace this ad-hoc path with the Cycles/Kulla path, or
2. measure whether any existing lobe is already energy-conserving and remove
   only the over-bright contribution.

Do not stack the Cycles compensation on top of this existing ad-hoc term
without first measuring; that would likely double-compensate high-roughness
metal/Disney lobes.

---

## Proposed Implementation Direction After Owner Sign-Off

1. Port the Cycles Apache-2.0 `table_ggx_E` and `table_ggx_Eavg` data into
   Astroray data files, preserving attribution.
2. For Astroray Disney reflection lobes, use:
   - `E = sample_ggx_E(roughness, abs(NdotV))`;
   - `Eavg = sample_ggx_Eavg(roughness)`;
   - white/no-Fresnel scale `1 / max(E, eps)`;
   - colored-Fresnel correction equivalent to Cycles'
     `Fms` / `darkening` when the lobe has non-white Fresnel.
3. For clearcoat, use the same GGX dielectric preservation path unless owner
   signs off on a separate clearcoat-specific table.
4. For sheen, choose one of:
   - **Cycles-current path:** port `table_sheen_ltc` and the Zeltner/Burley/
     Chiang 2022 LTC sheen implementation; or
   - **Kulla/Conty Imageworks path:** implement the 16x16 Charlie-sheen albedo
     compensation described in the 2017 course notes.
5. Remove or gate the existing Astroray ad-hoc `ggxMultiScatterCompensation`
   term in Disney/Metal after numerical integration confirms the new path.

---

## Open Questions For Project Owner

1. **License sign-off:** Cycles data is Apache-2.0 and microfacet source is
   BSD-3-Clause, not CC0. Both are MIT-compatible, but the port must preserve
   notices. Is that acceptable for Astroray?
2. **Sheen target:** Should pkg60 follow current Cycles and port the 2022 LTC
   multiple-scattering sheen, or follow the Kulla/Conty 2017 Charlie-sheen
   16x16 albedo compensation described in the Imageworks course?
3. **Clearcoat table:** Current Cycles has no `clearcoat_E` LUT; it uses the
   GGX energy-preservation path for coat. Should Astroray drop the planned
   `clearcoat_E.bin` and use GGX `E`, or do we still want an Astroray-specific
   clearcoat LUT?
4. **Scope correction:** Because Astroray already has an inline, generated
   `GGXEnergyCompensationLUT` in `include/raytracer.h`, is pkg60 allowed to
   modify/remove that header despite the implementation spec only naming
   `plugins/materials/disney.cpp`?
5. **LUT source format:** Cycles current source ships static arrays in
   `shader.tables`, not `.bin` files. Should the implementation phase convert
   those arrays into Astroray `.bin` files as planned, or keep generated C++
   arrays with license headers?

---

## Implementation Follow-Up (2026-05-09)

Owner sign-off allowed the code phase to proceed. The implementation converted
Cycles `shader.tables` into Astroray `.bin` assets, preserved Cycles attribution
in `data/disney_compensation/README.md`, and used the Cycles/Kulla-Conty net
GGX factor `1 + Fms * ((1 - E) / E)` at the Disney GGX call site.

The numerical gate also exposed two Astroray-local issues outside the original
research note:

- Disney specular/clearcoat eval was using the Disney Smith-G helper and then
  dividing by `4*NdotL*NdotV` again, causing grazing-angle glow. The code phase
  corrected those lobe formulas before applying LUT compensation.
- Burley diffuse retro-reflection in the existing Disney plugin exceeded the
  white-furnace bound at roughness=0.9, grazing view. A small directional
  furnace normalization was added to keep the existing diffuse lobe within the
  package's 1.02 hard gate.
- Follow-up visual review found that eval-only integration was not enough to
  catch renderer bias: mixed diffuse/specular Disney samples returned only the
  selected lobe PDF while carrying the full Disney eval in `f`. The code phase
  now uses the combined material PDF for non-transmission Disney mixtures and
  adds a gray-furnace render regression for metallic=0.7, roughness=0.05.

Measured final gate: 90 listed roughness/metallic/sheen/clearcoat combinations
× 3 outgoing cosines × 4096 Halton samples, worst-case reflectance **1.015891**
at roughness=0.9, metallic=0, sheen=0, clearcoat=0, cosThetaO=0.1.
