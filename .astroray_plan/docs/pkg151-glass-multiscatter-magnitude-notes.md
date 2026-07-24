# pkg151 — numeric probe of the Cycles glass-table compensation magnitude

**Purpose:** before wiring the Cycles `table_ggx_glass_E`/`table_ggx_glass_Eavg`
port into `roughTransmissionEval`, the extracted table data was probed
standalone (Python, trilinear/bilinear interpolation matching the planned
`sample3D`/`sample2D` C++) to estimate how large the resulting compensation
factor actually is at `ior=1.5` (the furnace test's material), across the
exact roughness grid the pkg151 gate uses. This is reported here in full,
including the finding that the effect is **much smaller** than the furnace
deficit pkg149 measured, so a reviewer isn't surprised by the PR body's
combined-branch numbers.

## Method

`z(ior=1.5) = sqrt(|0.5/2.5|) = 0.4472`, `Fss = fresnel_dielectric_Fss(1.5)
= 0.0895` (Kulla & Conty 2017 average-Fresnel fit, `bsdf_util.h`). For each
`(roughness, mu)` in the furnace gate's grid, sampled `E = sample3D(table_ggx_
glass_E, roughness, mu, z)`, `Eavg = sample2D(table_ggx_glass_Eavg, roughness,
z)`, then `factor = 1 + Fms*(1-E)/E` (the exact Cycles
`microfacet_ggx_preserve_energy` glass-branch formula, `Fms = Fss*Eavg/(1-Fss*
(1-Eavg))`).

## Result

| roughness | mu=0.1 | mu=0.3 | mu=0.5 | mu=0.707 | mu=0.9 | mu=1.0 |
|---|---|---|---|---|---|---|
| 0.05 | 1.0001 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 0.10 | 1.0009 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 0.30 | 1.0069 | 1.0020 | 1.0006 | 1.0003 | 1.0001 | 1.0001 |
| 0.60 | 1.0101 | 1.0096 | 1.0062 | 1.0035 | 1.0020 | 1.0015 |
| 1.00 | 1.0247 | 1.0306 | 1.0254 | 1.0180 | 1.0114 | 1.0087 |

**The compensation factor tops out at ~1.03 (3%) even at roughness=1.0**,
compared to the ~1.2x-11x (roughness-dependent) that would be needed to raise
the pkg149-measured post-fix furnace values (0.217 at R=0.1, 0.357 at R=0.3,
0.596 at R=0.6, 0.817 at R=1.0) into the [0.92, 1.03] gate band.

## Interpretation

This is expected, not a bug in the port: Cycles' glass tables model the
single-scatter deficit of the **combined reflection+transmission GGX glass
closure** — i.e. energy that would otherwise vanish because a ray bounces
between multiple microfacets of the *same* rough interface before either
reflecting back out or transmitting through. For a low-Fresnel dielectric
(`Fss=0.09` at ior=1.5) with transmission enabled as an "escape channel",
very little energy is genuinely lost this way at moderate roughness — most
of a ray's energy either reflects or transmits in the first microfacet
interaction. The effect only becomes large (>10%) at extreme corners
(roughness=1.0, near-grazing, high-ior `z`) that are far from this material's
operating point.

This means the Cycles Turquin/Kulla-Conty glass-closure LUT compensation, by
itself, is very unlikely to be the dominant fix for the ~10-90% furnace
deficit pkg149 exposed. It is still the textbook, cite-able mechanism named
by the pkg151 spec and is implemented faithfully (see the spec's own
"non-goals" — this package does not re-open the sampler or invent a new
mechanism), but the measured combined-branch furnace numbers in the PR body
should be read with this ceiling in mind: if they remain outside
[0.92, 1.03], that is evidence the pkg149-exposed deficit's dominant cause is
something other than (or in addition to) microfacet-level multiple
scattering — worth flagging back to the architect rather than silently
declared fixed.
