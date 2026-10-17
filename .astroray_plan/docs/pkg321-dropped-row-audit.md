# pkg321 -- DROPPED-SILENT row audit (#1089)

Probe-backed verdict for every row of the #1089 families. CPU, Blender 5.2 headless, F12 through the addon, 80x80, 64 spp, seed pinned. Engine build: `build_cuda` HEAD 3bb710b8 (00:49, includes #1116 / #1123 / #1105), copied to `build_lane\`.

## Result

**17 stale rows credited, 29 real-drop rows (all now reported, each with an issue; 31 probes), 2 partial, 1 unproven.** Gate (b) population (`silent_drop_audit.py coverage`): matrix-silent uses 47 -> 33, matrix-only ceiling 0.6388 -> 0.6938; production corpus unchanged (1 silent, 0.8882). Of the 33 left, 26 are the real drops below (reported at runtime, so the audit reads them as `reported`, and the matrix label stays DROPPED because they are dropped) and 7 are outside #1089 (MapRange `clamp`, Material Output `Thickness`, World Output `Surface` / `is_active_output`, Brick `Mortar`, Environment / IES `Vector`; #1088).

Verdict classes: **stale** = the input moves the render, the row was never credited (the scanner cannot see the read); **REAL** = the render is bit-identical when the input changes; **partial** = consumed or approximated, with a stated gap; **unproven** = neither. `d_ab` = mean |A - B| over the image (the factor is the larger of the pixel and 8x8-block ratios to the seed-noise floor `d_aa` = A vs A under another seed).

## Method

`tests/pkg321_probe_blender.py` builds one scene per family (UV sphere + sun, hair tuft, VDB / mesh volume, Sky world), renders variant A, A under a second seed, and variant B that changes ONE input (or links one socket). The CPU engine is deterministic per seed, so an inert input gives `d_ab == 0` exactly. `tests/test_pkg321_dropped_row_probes.py` pins the verdict of every probe, the DegradationReport text for each drop, and that the matrix credits / annotations match the probes. Controls: `n_principled_control`, `s_sun_elevation_control`.

## Per-row verdicts

| Family | Node | Row | Verdict | Probe | d_ab | Note |
|---|---|---|---|---|---|---|
| Hair | Principled Hair | Color | stale | `hair_color` | 0.0576 (19x floor) | credited SUPPORTED |
| Hair | Principled Hair | Roughness | stale | `hair_roughness` | 0.00933 (11x floor) | credited SUPPORTED |
| Hair | Principled Hair | Radial Roughness | stale | `hair_radial_roughness` | 0.0052 (4x floor) | credited SUPPORTED |
| Hair | Principled Hair | Coat | stale | `hair_coat` | 0.0107 (24x floor) | credited SUPPORTED |
| Hair | Principled Hair | IOR | stale | `hair_ior` | 0.0173 (50x floor) | credited SUPPORTED |
| Hair | Principled Hair | Offset | stale | `hair_offset` | 0.00427 (6x floor) | credited SUPPORTED |
| Hair | Principled Hair | Melanin | stale | `hair_melanin` | 0.0696 (17x floor) | credited SUPPORTED (not in a corpus scene) |
| Hair | Principled Hair | Melanin Redness | stale | `hair_melanin_redness` | 0.0031 (6x floor) | credited SUPPORTED (not in a corpus scene) |
| Hair | Principled Hair | Absorption Coefficient | stale | `hair_absorption` | 0.0388 (14x floor) | credited SUPPORTED (not in a corpus scene) |
| Hair | Principled Hair | prop:parametrization | stale | `hair_parametrization` | 0.00328 (7x floor) | credited SUPPORTED |
| Hair | Principled Hair | Tint | unproven | `hair_tint` | 0.0296 (1x floor) | not credited, not called a drop: <1% change at Melanin 0 and not bit-identical; `principled_hair.cpp` keeps Tint only in the RGB fallback sigma, the spectral melanin path reads eu/ph. Noted on #1128 |
| Hair | Principled Hair | prop:model | partial | `hair_model` | 0 (bit-identical) | pixels identical (Huang is rendered as Chiang); already reported; row APPROXIMATED |
| Hair | Principled Hair | Random | REAL | `hair_random` | 0 (bit-identical) | #1128, now reported |
| Hair | Principled Hair | Random Roughness | REAL | `hair_random_roughness` | 0 (bit-identical) | #1128, now reported |
| Hair | Principled Hair | Random Color | REAL | `hair_random_color` | 0 (bit-identical) | #1128, now reported |
| Normal / Tangent | Diffuse | Normal | REAL | `n_diffuse` | 0 (bit-identical) | #1129; Normal Map, now reported |
| Normal / Tangent | Diffuse | Normal (Bump path) | REAL | `n_diffuse_bump` | 0 (bit-identical) | #1129; the Bump path is not honoured either, so there is no path to credit |
| Normal / Tangent | Glass | Normal | REAL | `n_glass` | 0 (bit-identical) | #1129, now reported |
| Normal / Tangent | Refraction | Normal | REAL | `n_refraction` | 0 (bit-identical) | #1129, now reported |
| Normal / Tangent | Sheen | Normal | REAL | `n_sheen` | 0 (bit-identical) | #1129, now reported |
| Normal / Tangent | Translucent | Normal | REAL | `n_translucent` | 0 (bit-identical) | #1129, now reported |
| Normal / Tangent | Anisotropic | Normal | REAL | `n_anisotropic` | 0 (bit-identical) | #1129, now reported |
| Normal / Tangent | Metallic | Normal | REAL | `n_metallic` | 0 (bit-identical) | #1129; was already reported (unconditional) |
| Normal / Tangent | Displacement | Normal | REAL | `disp_normal` | 0 (bit-identical) | #1129; was already reported when linked |
| Normal / Tangent | Principled | Normal (control) | control | `n_principled_control` | 0.406 (621x floor) | the same Normal Map moves the Principled sphere: the probe is not vacuous |
| Normal / Tangent | Principled | Tangent | REAL | `t_principled` | 0 (bit-identical) | #1130; was already reported when linked |
| Normal / Tangent | Principled | Coat Normal | REAL | `n_principled_coat` | 0 (bit-identical) | #1130; was already reported when linked |
| Normal / Tangent | Metallic | Tangent | REAL | `t_metallic` | 0 (bit-identical) | #1130; was already reported (unconditional) |
| Normal / Tangent | Anisotropic | Tangent | REAL | `t_anisotropic` | 0 (bit-identical) | #1130, now reported |
| Enums / Anisotropic | Anisotropic | Anisotropy | REAL | `a_anisotropy` | 0 (bit-identical) | #1131: node.type is BSDF_GLOSSY on 5.2, the BSDF_ANISOTROPIC branch never runs; now reported |
| Enums / Anisotropic | Anisotropic | Rotation | REAL | `a_rotation` | 0 (bit-identical) | #1131, now reported |
| Enums / Anisotropic | Principled | prop:distribution | REAL | `e_principled_distribution` | 0 (bit-identical) | #1132, now reported |
| Enums / Anisotropic | Glass | prop:distribution | REAL | `e_glass_distribution` | 0 (bit-identical) | #1132, now reported |
| Enums / Anisotropic | Refraction | prop:distribution | REAL | `e_refraction_distribution` | 0 (bit-identical) | #1132, now reported |
| Enums / Anisotropic | Sheen | prop:distribution | REAL | `e_sheen_distribution` | 0 (bit-identical) | #1132, now reported |
| Enums / Anisotropic | Anisotropic | prop:distribution | REAL | `e_anisotropic_distribution` | 0 (bit-identical) | #1132, now reported |
| Enums / Anisotropic | Glossy | prop:distribution | REAL | `e_glossy_distribution` | 0 (bit-identical) | #1132, now reported (same code path; not a #1089 row) |
| Enums / Anisotropic | Principled | prop:subsurface_method | REAL | `e_principled_subsurface_method` | 0 (bit-identical) | #1133; a generic SSS line existed but did not name it |
| Enums / Anisotropic | Principled | Subsurface IOR | REAL | `e_principled_subsurface_ior` | 0 (bit-identical) | #1133, now reported when non-default |
| Principled Volume | Principled Volume | Absorption Color | stale | `v_absorption_color` | 0.108 (39x floor) | credited SUPPORTED; the 'mapped to glass IOR=1.0' note was stale (#833 / pkg296 / pkg270) |
| Principled Volume | Principled Volume | Blackbody Tint | stale | `v_blackbody_tint` | 0.453 (77x floor) | credited SUPPORTED |
| Principled Volume | Principled Volume | Density Attribute | stale | `v_density_attribute` | 0.0556 (50x floor) | credited SUPPORTED (VDB grid chosen by name) |
| Principled Volume | Principled Volume | Temperature Attribute | stale | `v_temperature_attribute` | 0.0231 (13x floor) | credited SUPPORTED |
| Principled Volume | Principled Volume | Color Attribute | REAL | `v_color_attribute` | 0 (bit-identical) | #1134; was a stdout-only line, now in the DegradationReport |
| Sky | Sky Texture | prop:altitude | stale | `s_altitude` | 35.1 (4x floor) | credited APPROXIMATED (Nishita model, reported on every render) |
| Sky | Sky Texture | prop:sun_intensity | stale | `s_sun_intensity` | 122 (14x floor) | credited APPROXIMATED |
| Sky | Sky Texture | prop:sun_size | stale | `s_sun_size` | 72.3 (7x floor) | credited APPROXIMATED |
| Sky | Sky Texture | prop:sun_elevation (control) | control | `s_sun_elevation_control` | 95.3 (10x floor) | moves: the probe is not vacuous |
| Sky | Sky Texture | prop:ground_albedo | REAL | `s_ground_albedo` | 0 (bit-identical) | #1135; was already named in the warning |
| Sky | Sky Texture | prop:sun_direction | partial | `s_sun_direction` | 0 (bit-identical) | inert in Cycles too for the Nishita types (`cycles_sundir.py`: identical); Cycles reads it for PREETHAM / HOSEK_WILKIE (moves). Astroray renders those as Nishita; the warning now names it (`s_sun_direction_preetham`). Row APPROXIMATED; #1135 |
| Glass thin film / misc | Glass | Thin Film Thickness | REAL | `g_thin_film_thickness` | 0 (bit-identical) | #1136, now reported (re-run on the 00:49 build with #1116/#1123) |
| Glass thin film / misc | Glass | Thin Film IOR | REAL | `g_thin_film_ior` | 0 (bit-identical) | #1136, now reported |
| Glass thin film / misc | Geometry | output:Normal | REAL | `m_geometry_normal` | 0.158 (434x floor) | op-VM refuses it and flattens to grey; reported by the compiler already; gap = #989 |

Already fine since pkg320: Mix / Add Shader `Shader` (APPROXIMATED in the committed matrix, no longer silent).

## What changed

- `blender_addon/__init__.py`: named DegradationReport entries (only when the input is linked / non-default): hair Random*, standalone-BSDF linked Normal, Anisotropic Anisotropy / Rotation / Tangent, `distribution` (Principled, Glass, Refraction, Sheen, Glossy), Principled `subsurface_method` / `Subsurface IOR`, Glass thin film, Sky `sun_direction` for the legacy types; the volume export's degradations now reach the DegradationReport (they were stdout-only). No export behaviour changed.
- `blender_addon/volume_export.py`: `label` on the volume info, so the report feature name matches the node.
- `scripts/generate_blender_parity_matrix.py`: `PKG321_PROBE_CREDITS`, `PKG321_REPORTED_APPROXIMATIONS`, `PKG321_REPORTED_DROPS` (keyed by bl_idname; a row is touched only while DROPPED-SILENT); `coverage_matrix.json` and `report.md` regenerated in Blender 5.2, no drift outside these rows.
- Renders: CPU output of `prod_curves_geometry` and `materials_hall` (128x72, 16 spp) is byte-identical to the pre-change addon (`byteident.py`).

## Limits

- A moving probe proves the input is consumed, not that it matches Cycles; the gate (b) witnesses decide that.
- GPU legs are not run here (CPU is the oracle); the lead can run the same table on the GPU build.
- Enum probes compare two items of the enum (first vs second, or the node default vs one other); the remaining items are not probed.
