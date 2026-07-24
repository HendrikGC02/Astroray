Disney compensation tables in this directory are derived from Blender Cycles src/scene/shader.tables (Apache-2.0) and associated closure code:
- src/kernel/closure/bsdf_microfacet.h (BSD-3-Clause)
- src/kernel/closure/bsdf_sheen.h (Apache-2.0)
- src/app/cycles_precompute.cpp (Apache-2.0)

See .astroray_plan/docs/disney-energy-compensation-research.md for file paths, table dimensions, and the compensation equations used by Astroray.

## pkg151 — glass (rough dielectric transmission) tables

`ggx_glass_E.bin`, `ggx_glass_Eavg.bin`, `ggx_glass_inv_E.bin`, `ggx_glass_inv_Eavg.bin`
extend the above with the Cycles **glass** multi-scatter energy-compensation
tables — these are ior-dimensioned (16x16x16 / 16x16, NOT the 32x32 reflection
tables above) and back the rough-transmission compensation in
`DisneyEnergyCompensationTables::ggxGlassE`/`ggxGlassEavg`.

- Source: `intern/cycles/scene/shader.tables` (Blender/blender, commit
  `eaa5f63ba20e64a439af48a1600cb9ed7bf9bdf0`), symbols `table_ggx_glass_E[4096]`,
  `table_ggx_glass_Eavg[256]`, `table_ggx_glass_inv_E[4096]`,
  `table_ggx_glass_inv_Eavg[256]`. **License: Apache-2.0**
  (`SPDX-FileCopyrightText: 2011-2022 Blender Foundation`).
- Consuming closure code:
  `intern/cycles/kernel/closure/bsdf_microfacet.h` `microfacet_ggx_preserve_energy`
  (glass branch) and `intern/cycles/kernel/closure/bsdf_util.h`
  `fresnel_dielectric_Fss` (Kulla & Conty 2017 average-Fresnel fit). **License:
  BSD-3-Clause** (`SPDX-FileCopyrightText: 2009-2010 Sony Pictures Imageworks
  Inc., et al.` / `2011-2022 Blender Foundation`).
- Layout: row-major with roughness as the fastest-varying axis (`x`), matching
  Cycles' `lookup_table_read_3D(kg, rough, mu, z, ofs, 16, 16, 16)` /
  `lookup_table_read_2D(kg, rough, z, avg_ofs, 16, 16)` convention (X fastest,
  then Y, then Z) — extracted byte-for-byte from the C initializer order in
  `shader.tables`, no transpose applied.
- The `z` axis is `z = sqrt(|ior - 1| / (ior + 1))`; the `_inv_` tables are used
  when `ior < 1` (looked up with `ior' = 1/ior`), covering the exit-refraction
  direction — both handled internally by `ggxGlassE`/`ggxGlassEavg`.
- Extraction method: raw-fetched `shader.tables` at the pinned commit above,
  parsed the three `static const float table_ggx_glass_*[...]` C array literals
  with a small Python script (float-per-token regex, verified exact expected
  element counts before writing), wrote IEEE-754 float32 little-endian
  binaries — same method as the existing `ggx_E.bin`/`ggx_Eavg.bin` extraction.
- See `.astroray_plan/docs/pkg151-cycles-glass-tables-research.md` and
  `.astroray_plan/docs/pkg151-glass-multiscatter-magnitude-notes.md` for the
  full citation trail and a numeric probe of the resulting compensation
  magnitude across the furnace test's roughness grid.
