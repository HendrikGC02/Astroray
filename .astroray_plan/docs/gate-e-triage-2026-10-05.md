# Gate (e) triage, all open issues, 2026-10-05

Snapshot: 79 open issues (`docs/blender_parity/evidence/e/issues-baseline.json`, captured 2026-10-04T12:49:44.142109+00:00), main b0564cb4 + #1059. Rubric: `KNOWN_ISSUES.md`. Two independent passes: Claude (Sonnet 5.5, blind to the 2026-10-03 ratings) and Codex Terra (`gpt-5.6-terra`, read-only, high effort, blind to the Claude pass). Lead (Opus 5.5) reconciliation: keep the higher rating on a high-vs-not split unless evidence supports the lower; the 2026-10-03 evidence-backed downgrades are reused for unchanged issues. Reducer: `scripts/dev/known_issues_report.py --finalize-gate-e`.

## Summary

| rating | count |
|---|---|
| high | 10 |
| medium | 32 |
| low | 26 |
| not-applicable | 11 |
| total | 79 |

Gate (e): **RED**, high_count 10 (was 21 on 2026-10-03). First passes: Claude 5 high, Terra 21 high. `not-applicable` = already fixed on main or not a bug (close these: they are the lead's to verify).

## High (gate (e) blockers)

- #36 feat: Holdout and indirect-only objects
- #895 GR: black_hole shape plugin ignores spin and r_obs_M
- #946 Nishita sky at 4 deg sun elevation: sun disc 1.24x and glow 0.91x Cycles, disc colour too neutral (v2_sky_sun)
- #947 Motion-blurred rotating vane: Astroray reads 0.84x (perspective) / 0.40x (ortho) of Cycles (v2_camera_geometry)
- #955 Add Shader(BSDF, BSDF) lowers to the first BSDF; Mix Shader 'dominant shader' fallback for unsupported pairs is silent
- #1033 Transparent pass-throughs count as bounces (clamp class, max_bounces budget) unlike Cycles transparent_bounce
- #1042 GPU ReSTIR integrator ignores curves (primary + shadow)
- #1045 Photon caustic gather assumes a Lambertian receiver (albedo/pi) on glossy/metal surfaces
- #1047 Light Path / Attribute follow-ups: GPU late switch-child attribute slices, missing Attribute Alpha default, counter saturation
- #1051 Hair: residual g/b/L dimness vs Cycles after #1037 (tuft ROI 0.91-0.96; melanin test scene ~22% dimmer)

## Per-issue table

| # | Title | Claude | Terra | Final | Reconciliation |
|---|---|---|---|---|---|
| 36 | feat: Holdout and indirect-only objects | high | high | **high** | agree |
| 38 | feat: Tiled rendering for memory efficiency | low | low | **low** | agree |
| 39 | feat: Persistent data for animation rendering | low | low | **low** | agree |
| 141 | feat(material): diffraction grating / spectral mirror BSDF | low | low | **low** | agree |
| 144 | feat(volume): spectral nebula emission and reflection media | low | low | **low** | agree |
| 398 | Future/architecture: engine-agnostic core — standalone + USD/Hydra render delega | low | low | **low** | agree |
| 721 | Viewport: camera events block ~155 ms each; progressive refinement idles at ~1.3 | low | low | **low** | agree |
| 763 | Corpus scenes: Astroray CPU at 128 spp is far noisier than Cycles CPU at 128 spp | medium | medium | **medium** | agree |
| 773 | Rough/smooth glass limb 0.84x Cycles under clamp_indirect=10: Astroray under-pro | medium | high | **medium** | kept medium as 2026-10-03: addon export faithful (2026-09-29 comment); residual is Cycles-only diffuse->glass->lamp speckle caustic. |
| 783 | Thin-film-aware multiple-scattering microfacet glass walk (pkg265 follow-up) | low | low | **low** | agree |
| 789 | Rough-glass multiple-scattering walk is achromatic: dispersion unmodelled on the | low | medium | **medium** | kept higher (medium) |
| 855 | Viewport storm row: re-measure after #850 (full re-sync ~125 ms/edit is the floo | low | low | **low** | agree |
| 858 | Owner try-out checklist: viewport worker default (ASTRORAY_VIEWPORT_WORKER=1) | low | not-a-bug | **low** | kept higher (low) |
| 864 | test: resolve actual modules in pkg258 byte-identity baseline comparison | low | low | **low** | agree |
| 865 | tooling: investigate bounded delegate critic non-completion | low | low | **low** | agree |
| 867 | Expose requested native Debug Sample Count pass for CPU/GPU F12 | already-fixed | already-fixed | **not-applicable** | agree |
| 869 | build: avoid long CUDA compile failures in the default worktree cache launcher | low | low | **low** | agree |
| 872 | Coverage matrix generator drifted from the committed matrix (full regen reverts  | low | low | **low** | agree |
| 875 | Viewport: in-place transform update for non-instanced meshes | already-fixed | already-fixed | **not-applicable** | agree |
| 879 | Viewport: live ASTRORAY_VIEWPORT_WORKER flip + shading toggle crashes Blender in | already-fixed | already-fixed | **not-applicable** | agree |
| 881 | Noise Texture pattern differs from Cycles (correlation 0.73 unrotated) | already-fixed | already-fixed | **not-applicable** | agree |
| 884 | Indirect clamp removes far more energy on Astroray than Cycles in multi-scatter  | already-fixed | already-fixed | **not-applicable** | agree |
| 890 | GPU procedural bake (pkg190) 64^3 nearest-voxel loses high-frequency detail (war | medium | medium | **medium** | agree |
| 894 | GR: Kerr accretion disk (Page-Thorne) - disk still uses the Schwarzschild model  | medium | high | **medium** | kept medium as 2026-10-03: Pillar 4 (paused) documented interim (black_hole.h:100-102); not a Blender-native setting. |
| 895 | GR: black_hole shape plugin ignores spin and r_obs_M | medium | high | **high** | kept high as 2026-10-03: shape-plugin path silently ignores spin/r_obs_M (wrong GR image on a reachable Python path). |
| 898 | Reference bank: re-bless all scenes on the corrected pixel mapping (pkg280 Phase | low | low | **low** | agree |
| 920 | GPU SMS device port weight diverges from the CPU pkg226 MNEE weight (dead code t | low | low | **low** | agree |
| 924 | Lamp pass-through capped at 4 lamps per segment (pkg288); 5th+ dropped | medium | high | **medium** | kept medium as 2026-10-03: 5th+ lamp on one segment (kMaxLampPassthrough=4); rare, small energy loss. |
| 926 | Coplanar fog-box/floor face: Cycles darkens the floor 1.9x, Astroray does not | not-a-bug | not-a-bug | **not-applicable** | agree |
| 941 | CPU sampler is std::mt19937 (no QMC): variance x spp stays flat while Cycles' fa | medium | medium | **medium** | agree |
| 942 | Disney half-metal reads 0.91-0.93x Cycles under a sun (single blended specular l | medium | high | **medium** | kept medium as 2026-10-03: Disney custom material only (Blender export uses native Principled); <10%. |
| 946 | Nishita sky at 4 deg sun elevation: sun disc 1.24x and glow 0.91x Cycles, disc c | medium | high | **high** | kept high as 2026-10-03: native Nishita sky at low sun, disc 1.24x and unreddened; wrong image. |
| 947 | Motion-blurred rotating vane: Astroray reads 0.84x (perspective) / 0.40x (ortho) | high | high | **high** | agree |
| 950 | test_blender_parity_harness _pyd_dir prefers build_blender_addon over build_cuda | low | low | **low** | agree |
| 954 | GPU scalar op-VM programs sample only one texture input: Mix Shader programs wit | already-fixed | medium | **medium** | Claude fixed (80f39ec5) / Terra medium; kept medium until the issue is verified and closed. |
| 955 | Add Shader(BSDF, BSDF) lowers to the first BSDF; Mix Shader 'dominant shader' fa | high | high | **high** | agree |
| 956 | Disney metallic>0 with transmission>0: CPU transmission roulette ignores metalli | medium | high | **medium** | kept medium as 2026-10-03: Disney custom material only (use_native_principled off), strict xfails. |
| 957 | Principled rough glass GPU/CPU 1.03-1.07 with constant parameters | medium | high | **medium** | kept medium as 2026-10-03: GPU rough glass 1.03-1.07x CPU, strict xfails, bounded. |
| 960 | Thin-film titanium spheres: single channels outside the MC band on CPU and GPU ( | low | medium | **medium** | kept higher (medium) |
| 965 | ReSTIR-DI renders textured Emission Color as its texture mean (GPU) | medium | medium | **medium** | agree |
| 966 | GPU: per-hit textured emission on instanced meshes (needs instance transform or  | medium | medium | **medium** | agree |
| 967 | Volume multiple scattering: red channel low at volume_bounces 4 (box control 0.9 | medium | high | **medium** | kept medium as 2026-10-03: 4.5% single-channel media bias, bounded. |
| 968 | Glass rim reads +7.5 % vs Cycles with no volume (pkg296 glass-shell control) | medium | high | **medium** | kept medium as 2026-10-03: 7.5% rim ROI, bounded Fresnel/TIR difference. |
| 969 | CPU render not bit-stable across unrelated refactors (FMA contraction / inlining | low | low | **low** | agree |
| 975 | Voronoi Texture 2D/4D dimensions evaluated as 3D (DEGRADED); implement Cycles vo | medium | medium | **medium** | agree |
| 977 | test_results conventions follow-ups (after #976) | low | low | **low** | agree |
| 983 | Corpus v2: firefly in v2_media smoke_plume ROI at seed 278 (CPU leg, MSVC build) | low | medium | **medium** | kept higher (medium) |
| 986 | Corpus v2 bands: CPU sigma from correlated seeds 278-282 is underestimated (mt19 | low | low | **low** | agree |
| 989 | op-VM has no per-hit shading inputs: Layer Weight, Fresnel, Geometry (Backfacing | already-fixed | medium | **medium** | Claude fixed (150fad17) / Terra medium; Pointiness residual reported; kept medium. |
| 990 | Object Info Random, Attribute and Color Attribute are unsupported (chain flatten | already-fixed | already-fixed | **not-applicable** | agree |
| 992 | Float Curve and RGB Curves unsupported by the op-VM (RGB Curves drop is unreport | already-fixed | already-fixed | **not-applicable** | agree |
| 993 | op-VM VM_MAX_SLOTS bound exceeded by an ordinary wood Roughness chain (Wave + No | already-fixed | already-fixed | **not-applicable** | agree |
| 994 | GPU skips OBJECT-coordinate procedural programs (flat value): marble GPU 0.38-0. | already-fixed | already-fixed | **not-applicable** | agree |
| 995 | Nested Mix Shader with textured Fac and a Glass branch collapses to a constant m | medium | high | **medium** | kept medium as 2026-10-03: collapse is reported (approximated MIX_SHADER warning), so flagged. |
| 997 | test_spatial_reduces_mse is a coin flip: spatial/no-reuse MSE ratio 0.98-1.02 ac | low | low | **low** | agree |
| 998 | pkg287 sun photon caustic reads 1.07-1.10x the path-traced reference on main (ga | low | medium | **medium** | kept higher (medium) |
| 1001 | pkg299 follow-ups: TTFS (CPU BVH off the GPU path), IAS refit, shared OptiX cont | low | low | **low** | agree |
| 1002 | pkg277 warped checker: GPU bake error 0.61 exceeds the 0.486 model once the CPU  | medium | medium | **medium** | agree |
| 1004 | Mapping Scale driven by a node-group input (via Combine XYZ) is silently ignored | medium | already-fixed | **medium** | Terra fixed / Claude medium: residual centre ~0.91x after #1011; kept medium. |
| 1005 | Bump node with a procedural Height (Voronoi/Noise) is silently dropped | medium | medium | **medium** | agree |
| 1015 | test_pkg224_progressive_sobol_gpu::test_progressive_lowers_noise fails on main:  | low | low | **low** | agree |
| 1019 | Media: heavy-tailed variance (fireflies) in the smoke plume; relMSE falls slower | already-fixed | medium | **medium** | Terra medium / Claude fixed: #1054 removed the tail mechanism; residual variance tracked (#1032); kept open as medium. |
| 1024 | Film: out-of-gamut channels clipped to 0 per pass/beauty; decide whether scene-l | medium | low | **medium** | kept higher (medium) |
| 1031 | GPU skips a texture-less (per-hit only) op-VM program on a lambertian base colou | low | high | **medium** | Terra high; medium: Blender export routes Diffuse BSDF to principled (blender_addon/__init__.py:5355-5376), so the GPU lambertian op-VM skip is Python-API-only and strict-xfailed. |
| 1032 | Media: heterogeneous segment-NEE distance strategy uses the hull's global majora | medium | medium | **medium** | agree |
| 1033 | Transparent pass-throughs count as bounces (clamp class, max_bounces budget) unl | high | high | **high** | agree |
| 1034 | Object / Generated texture coordinates slide under motion blur (shutter-open bar | medium | medium | **medium** | agree |
| 1035 | gate (d): tighten adaptive allocation bound (flat/detail sample ratio 0.9 vs ref | low | low | **low** | agree |
| 1038 | Glass BSDF sphere: centre 6-9 % brighter than Cycles (R/B) and its sun shadow ~2 | medium | high | **medium** | Terra high; medium: shadow fill is physical caustic light Cycles omits (owner physics-over-look 2026-09-29); centre 6-9% R/B is a bounded <10% gap, same class as #968. |
| 1039 | Coverage-matrix generator: no output-socket evidence (Light Path / Attribute / O | low | low | **low** | agree |
| 1042 | GPU ReSTIR integrator ignores curves (primary + shadow) | high | high | **high** | agree |
| 1044 | CPU photon caustics: one 3M-photon map per render freezes gather speckle (GPU tr | medium | medium | **medium** | agree |
| 1045 | Photon caustic gather assumes a Lambertian receiver (albedo/pi) on glossy/metal  | medium | high | **high** | Claude medium; high: glossy/metal receivers gather albedo/pi, a biased non-view-dependent image with no warning when caustics are on. |
| 1046 | CPU photon-map seeding is fixed when renderSeed == 0 (random sentinel) | low | medium | **medium** | kept higher (medium) |
| 1047 | Light Path / Attribute follow-ups: GPU late switch-child attribute slices, missi | medium | high | **high** | Claude medium; high: missing Attribute alpha returns 0 vs Cycles 1, silent wrong value on reachable attribute materials. |
| 1050 | gate (a) worker-OFF capture: persist POST_PIXEL raw events and validate the pres | low | low | **low** | agree |
| 1051 | Hair: residual g/b/L dimness vs Cycles after #1037 (tuft ROI 0.91-0.96; melanin  | medium | high | **high** | Claude medium; high: hair 22% dimmer in the melanin scene, no warning; >10% wrong image. |
| 1052 | reference-bank phash gate (sms-refractive-glass-sphere) sits at the MC noise flo | low | low | **low** | agree |
| 1057 | pkg291 GPU in-place patch refused in long GPU runs: triIndexOf map keyed on raw  | already-fixed | already-fixed | **not-applicable** | fixed by 132c9749 on PR #1059 (not yet on main at capture); refused patch falls back to a full re-flatten. |
