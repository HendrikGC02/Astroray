# #763 materials_hall variance table (batch T, 2026-09-20)

Status: measured (PR #837). Owner of the gap: CPU light tree, follow-up #851.

## Verdict (CPU)

The **CPU light tree** owns the gap. Turning it off (the power sampler) cuts the
Astroray/Cycles variance ratio **8–14×** on the lit ROIs: wall 83 → 7.7, floor
200 → 14, D 145 → 10. Removing the practical bulb changes nothing (wall 83 →
122, within two-seed noise). Owner: pkg86 CPU light tree, which pkg262 made the
default via the native `use_light_tree = True`. Follow-up: #851.
Prime suspect, a cited divergence: `LightTree::importance` uses
`max(distance - bboxRadius, 1e-6)`, which blows importance up ×1e12 whenever the
shading point lies inside a cluster's bounding sphere. Cycles `kernel/light/tree.h`
clamps `distance >= 0.5·|centroid − bbox.max|` and blends min- and max-distance
importance.

The residual after the tree is off is 4–9× in luminance and 50–120× in chroma.
Spectral rendering plausibly explains it: 4 wavelengths per path give colour
speckle that RGB Cycles lacks. The pixel filter is a second suspect, not measured.

## Method

- Scene: `benchmarks/reference_corpus/scenes/materials_hall.blend`, 960×176.
- Settings: 32 spp for both engines, adaptive and denoise off, clamp 0/10 (the
  scene's own, identical for both engines), filter 1.5 px, linear EXR.
- Engines: headless Blender 5.2 with main's staged addon (916907b). Cycles CPU
  against Astroray CPU (`cycles.device=CPU`).
- Variance: two seeds (11, 23) per leg. Per-pixel var = (I₁−I₂)²/2, then
  mean over the ROI, / mean(I)². Ratio = Astroray / Cycles, same variant.
  - `rgb` = all channels.
  - `lum` = Rec.709 luminance.
  - `chroma` = variance of I/lum (colour speckle).
- ROIs: manifest crops A–I plus `wall` (0.30–0.70 × 0.10–0.40) and `floor`
  (0.22–0.78 × 0.72–0.86), top-down fractions. Boxes are drawn on the first row of
  the sheet.
- Variants: (a) light tree off = `cycles.use_light_tree False` (addon → `'power'`).
  (b)/(c) progressive Sobol is GPU-only (pkg224). The addon enables it only with
  GPU adaptive sampling, so the GPU legs force it on by patching
  `set_use_progressive_sampler`. (d) removes the `Practical` point light, with
  Cycles re-rendered the same way.

## CPU table (variance ratio Astroray/Cycles)

| variant | metric | A | B | C | D | E | H | I | wall | floor |
|---|---|---|---|---|---|---|---|---|---|---|
| base (tree on) | rgb | 57 | 16 | 37 | 145 | 11 | 19 | 65 | 83 | 200 |
| | lum | 45 | 12 | 28 | 110 | 7.6 | 4.4 | 56 | 59 | 149 |
| | chroma | 77 | 318 | 315 | 74 | 41 | 20 | 466 | 255 | 279 |
| (a) tree off | rgb | 47 | 9.9 | 7.1 | 10 | 3.4 | 19 | 14 | 7.7 | 14 |
| | lum | 33 | 6.1 | 4.8 | 5.6 | 2.0 | 3.7 | 11 | 4.4 | 8.9 |
| | chroma | 78 | 248 | 89 | 15 | 21 | 17 | 410 | 48 | 118 |
| (d) bulb removed | rgb | 40 | 17 | 32 | 179 | 9.9 | 19 | 41 | 122 | 196 |
| | lum | 29 | 13 | 25 | 139 | 6.4 | 4.5 | 36 | 87 | 146 |

The wall's median per-pixel relative variance is 0.14 against Cycles' 0.00068
(200×), and the top 1 % of pixels hold 12 % of it (Cycles 37 %). The grain is
uniform, not fireflies. The sheet shows the same:
`test_results/batchT/issue763_materials_hall_cpu_variants.png`.

A and I are mostly the dark world seen directly. Cycles returns it noise-free;
Astroray's 4-λ estimate adds chroma noise. Read those two columns as the
spectral floor.

## GPU table

(pending: GPU-lock slot)
