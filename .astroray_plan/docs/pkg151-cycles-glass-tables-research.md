# pkg151 — Cycles glass energy-preservation tables: symbols CONFIRMED (2026-07-24)

Architect pre-dispatch verification for pkg151 (rough-transmission multi-scatter
energy compensation). The pkg151 spec's "confirm the exact table
symbols/dimensions against the live source at port time" item is **done** — this
note is the record; the implementer ports against these, no re-research needed.

**Method:** direct fetch of `blender/blender` `main` raw sources, 2026-07-24.
Pinned last-touch commits:

- `intern/cycles/kernel/closure/bsdf_microfacet.h` — last touched
  `a738579cf5844886ad2d2752f452f58894814149` (2026-07-17).
- `intern/cycles/scene/shader.tables` — last touched
  `eaa5f63ba20e64a439af48a1600cb9ed7bf9bdf0` (2025-07-09; the glass tables are
  stable since the 888bdc1 / PR blender/blender#107958 multiscatter rework).

## Licenses (verified from SPDX headers, 2026-07-24)

| File | SPDX |
|------|------|
| `intern/cycles/kernel/closure/bsdf_microfacet.h` | **BSD-3-Clause** (the pkg151 spec previously said Apache-2.0 — corrected; matches the pkg124/#501 correction) |
| `intern/cycles/scene/shader.tables` (the table data) | **Apache-2.0**, `SPDX-FileCopyrightText: 2011-2022 Blender Foundation` |
| `intern/cycles/scene/shader.cpp` (table registration) | **Apache-2.0** |

Both allow-listed. The in-repo `data/disney_compensation/README.md` already
records this exact provenance split for the reflection tables — extend it, same
format.

## The function to mirror

`bsdf_microfacet.h`:

```c
ccl_device_inline void microfacet_ggx_preserve_energy(KernelGlobals kg,
                                                      ccl_private MicrofacetBsdf *bsdf,
                                                      const float3 wi,
                                                      const Spectrum Fss)
```

Core: look up single-scatter directional albedo `E` (and `E_avg`), then
`energy_scale = 1.0f + (1.0f - E) / E` (i.e. `1/E` albedo scaling, Turquin 2019
form), applied to the closure weight, with a Fresnel multi-bounce compensation
term using `Fss`/`E_avg`.

## Glass (dielectric transmission) case — exact symbols

For `CLOSURE_BSDF_MICROFACET_GGX_GLASS_ID` (reflection+transmission combined —
note Cycles compensates the **combined** glass closure, not a transmission-only
lobe):

- Table offsets (`kernel_data.tables.*`): `ggx_glass_E` (3D),
  `ggx_glass_Eavg` (2D), and for `ior < 1.0f` the inverse-direction variants
  `ggx_glass_inv_E` / `ggx_glass_inv_Eavg`.
- Lookups: `lookup_table_read_3D(kg, rough, mu, z, ofs, 16, 16, 16)` and
  `lookup_table_read_2D(kg, rough, z, avg_ofs, 16, 16)`.
- **The ior axis** (the `z` coordinate — this is the parameterization pkg151's
  spec flagged as unconfirmed):

  ```c
  const float z = sqrtf(fabsf((ior - 1.0f) / (ior + 1.0f)));
  ```

  with the table-offset swap to the `inv` tables when `ior < 1.0f` handling the
  exit direction (both eta and 1/eta covered, as the spec requires).

## Table data (`intern/cycles/scene/shader.tables`, Apache-2.0)

- `static const float table_ggx_glass_E[4096]` — 16×16×16 (rough × mu × z)
- `static const float table_ggx_glass_Eavg[256]` — 16×16 (rough × z)
- `static const float table_ggx_glass_inv_E[4096]` — 16×16×16
- `table_ggx_glass_inv_Eavg[256]` — registered in `shader.cpp`
  (`ensure_bsdf_table(dscene, scene, table_ggx_glass_inv_Eavg)`); the raw-fetch
  page truncated before its declaration — sanity-check the 256-float size when
  extracting, do not re-derive.
- Registration site: `scene/shader.cpp` `device_update_common` →
  `ktables->ggx_glass_E = ensure_bsdf_table(...)` etc.
- Generator (if regeneration is ever needed; prefer extracting the shipped
  arrays): Cycles `src/app/cycles_precompute.cpp` (Apache-2.0) — same tool
  recorded in `data/disney_compensation/README.md` for the reflection tables.

## In-repo substrate (what the port extends)

- `data/disney_compensation/ggx_E.bin` + `ggx_Eavg.bin` are already the Cycles
  `table_ggx_E[1024]` (32×32) / `table_ggx_Eavg[32]` — the pkg60/pkg145
  precedent. Add `ggx_glass_E.bin` / `ggx_glass_Eavg.bin` /
  `ggx_glass_inv_E.bin` / `ggx_glass_inv_Eavg.bin` beside them; update the
  README provenance lines.
- Loader: `DisneyEnergyCompensationTables`
  (`include/astroray/energy_compensation.h`, `src/energy_compensation.cpp`).
  It has `sample2D`/`sample1D` only — the glass tables need a **`sample3D`**
  (trilinear, 16³) plus the `z(ior)` remap and the `ior<1 → inv` table swap.
  Note the glass tables are 16-resolution vs the existing kGgxSize=32 — do not
  reuse the 32 constant.
- GPU mirror: the closure-graph dielectric path
  (`gpu_material_sample_spectral`, memory `gpu-dielectric-lowers-to-closure-graph`)
  — same tables uploaded, same index math; RTX parity gate per the spec.

## Caveats for the implementer

1. Cycles' tables are baked for its **combined** glass closure (Fresnel-weighted
   reflection+transmission single-scatter albedo, per-direction via the
   E(rough, mu, z) axis). Astroray's Disney transmission path splits R/T at
   lobe-selection time — apply the compensation consistently with how Cycles
   applies it (to the glass closure throughput, not per-sub-lobe re-tuning), and
   validate against the estimator identity in the pkg149 research doc
   (single-scatter median ≈ `G1(wi)/ior²` → compensated furnace ≈ 1.0).
2. Re-measure the pkg118 Part-B "multi-scatter rejected" claim on the corrected
   sampler (`670e583`) — it is confounded (measured on the azimuth-swapped
   sampler); recorded in both pkg149 and pkg151 specs.
