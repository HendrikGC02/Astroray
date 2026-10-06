<!-- Owner route 2026-10-06: one blind Claude (Sonnet 5.5) rater + opencode GLM-5.3 critic (AGREE 12/12). Lead reconciliation: #1070 (high) is resolved by PR #1094 (reference firefly); #1075 is fixed by PR #1098. -->
# Gate (e) blind rating, Claude (Sonnet 5.5), 2026-10-06

Scope: 12 open issues created on or after 2026-10-05, plus #1060 (created 2026-10-04, absent from the 2026-10-05 table). Rubric (`KNOWN_ISSUES.md`): high = wrong image, crash, or a native setting silently ignored; medium = degraded but flagged; low = cosmetic. Rated from issue bodies, comments and spot code checks on main beda1881. Impact = size of the visible/numerical effect; likelihood = how reachable it is from the Blender addon.

| # | Title | Impact | Likelihood | Severity | Blocks Stage 0 | Rationale |
|---|---|---|---|---|---|---|
| 1060 | run_parity SSIM gates red: cornell 0.932, world_sky_hdri 0.807 | low | low | **low** | no | Cornell half was a harness setup mismatch plus an SSIM reader change, fixed on main by a52f0e07 (#1074, SSIM 0.9994); the world_sky_hdri half is noise-limited SSIM at 128 spp, no engine defect shown. Close candidate once the hdri row is reclassified. |
| 1070 | v2_sky_sun: chrome_reflection ROI (stone pillar base) r 0.81 / g 0.91 of Cycles at low sun | high | medium | **high** | yes | Unflagged 19% red / 9% green deficit on a native Nishita-sky corpus scene, unchanged at 512 spp, disc and rim match so it is transport or material, not noise. Unattributed: it may be harness-side (cf. #1060), in which case it drops to medium/low. |
| 1072 | GPU: Add Shader sums closures (renders first shader only) | medium | medium | **medium** | no | Real GPU wrong image for Add Shader, but the addon emits an ADD_SHADER degradation warning (`blender_addon/__init__.py:5643`) and the CPU is exact after #1071, so it is flagged. |
| 1073 | Shadow-ray transparent walks ignore transparent_max_bounces (maxHops 8 CPU / 31 GPU) | low | low | **medium** | no | Native setting honoured on camera paths (#1033) but not on shadow rays; only differs with more than 8 stacked transparent sheets or a limit below 8. Rare, small, no warning, same class as #924. |
| 1075 | AOV first-hit passes (albedo/normal/depth) ignore indirect-only objects | medium | low | **medium** | no | Confirmed still open: `spectral_path_tracer.cpp:223,309` use `bvh->hit` not `hitCameraRay`. Beauty is correct (#1076); only data passes (and denoiser guides) wrongly include a hidden object, and only for the new indirect-only feature. Strictly unflagged, so a stricter rater may call it high. |
| 1081 | GR: surfaces hit inside the black-hole region are lit by straight NEE/bounce rays | medium | low | **medium** | no | Diffuse surfaces inside r_max render dark and lamps are blocked by the influence sphere; wrong image but Pillar 4 (paused), not a Blender-native setting, and a known limitation of #1063 (emissive spheres render correctly). Same class as #894. |
| 1082 | GR: reflected light at an in-region scene hit has no gravitational shift | low | low | **low** | no | Second-order correction (inverse shift on incident light) deliberately not half-applied; depends on #1081 first. Pillar 4, paused. |
| 1087 | gate (b): witness registry holds one checker case that fails (patch SSIM over ROI rectangle) | low | low | **low** | no | Scoring tooling and frozen-predicate design for gate (b); no user-visible rendering defect (checker itself matches Cycles). Gate (b) is separate from gate (e). |
| 1088 | coverage matrix: Output/Background/Environment/IES rows read DROPPED-SILENT; collector ids mismatch | low | low | **low** | no | Scanner/collector bookkeeping: working features read as drops. Tooling only, affects b4 scoring not renders. |
| 1089 | gate (b) audit: Hair, BSDF Normal/Tangent, distribution/subsurface_method, Principled Volume, Sky rows DROPPED-SILENT | medium | medium | **medium** | no | Unverified audit; at least some are real drops but already warned (BSDF_METALLIC Tangent warning at `__init__.py:5505`, Coat Normal/Tangent listed as approximated at 5109-5112), others look stale (hair #1037, volume #833). Any confirmed silent drop would escalate to high individually. |
| 1092 | Curves: whole-strand self-intersection skip (Cycles), not just the leaving segment | low | medium | **low** | no | Measured effect about 1% on the hair_tuft ROI; the tuft is still about 2.5% low after pkg316. Fidelity refinement, below the MC band. |
| 1099 | textures_mapping: wall around checker swatch reads r/g/b 0.84/0.91/0.94 of Cycles (CPU and GPU) | medium | medium | **medium** | no | Unflagged 6-16% wall bias, CPU and GPU agree. The #1060 precedent (harness setup mismatch) makes a setup cause likely, so medium pending diagnosis; if the engine is at fault (raking area light on a diffuse wall) it becomes high. Also blocks the only gate (b) witness. |

## Counts

| severity | count |
|---|---|
| high | 1 |
| medium | 6 |
| low | 5 |
| not-applicable | 0 |
| total | 12 |

(medium: 1072, 1073, 1075, 1081, 1089, 1099; low: 1060, 1082, 1087, 1088, 1092; high: 1070.)

## Already fixed or not a bug

- #1060: cornell half fixed by a52f0e07 (#1074). World_sky_hdri half remains and is not an engine bug (noise-limited SSIM).
- No other issue looks fixed on main. #1075 is confirmed still open in code; #1072 and #1073 are open follow-ups to #1071/#1033 (de-dup note: #1072 is the GPU leg of #955, whose CPU leg landed in 2f9f1519).

