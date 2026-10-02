# Gate (e) triage, all open issues, 2026-10-03

Lane at-e. Snapshot: 78 open issues (`docs/blender_parity/evidence/e/issues-baseline.json`, captured 2026-10-02T14:53:08.182666+00:00), main f06f3564. Rubric: `KNOWN_ISSUES.md` (high = wrong image, crash, or native setting silently ignored; medium = degraded but flagged; low = cosmetic; tooling, tests, unimplemented features and perf-only count as low or medium). Rated from issue bodies, recent comments and cheap code checks, not labels.

Independence: first pass by Claude (this lane), second by Codex Terra (`gpt-5.6-terra`, read-only, high effort) blind to the first. Final column keeps the higher rating on a high-vs-not split unless evidence is cited in the reconciliation column. Terra rated more liberally (any unflagged mean offset = high); the evidence-backed downgrades are listed below and are the review items for the lead.

## Summary (final)

| rating | count |
|---|---|
| high | 21 |
| medium | 29 |
| low | 25 |
| not-a-bug | 1 |
| already-fixed | 2 |
| total | 78 |

First-pass counts (Claude): low 25, medium 32, high 18, already-fixed 2, not-a-bug 1. Terra counts: low 27, high 34, already-fixed 7, medium 9, not-a-bug 1.

## Gate (e) blocker set: HIGH not covered by any lane (14)

- #866 Native adaptive-sampling toggle remains custom-only: gate (d) baseline gap
- #867 Expose requested native Debug Sample Count pass for CPU/GPU F12
- #881 Noise Texture pattern differs from Cycles (correlation 0.73 unrotated)
- #884 Indirect clamp removes far more energy on Astroray than Cycles in multi-scatter media (cabinet 9-10 % vs 2 %)
- #895 GR: black_hole shape plugin ignores spin and r_obs_M
- #946 Nishita sky at 4 deg sun elevation: sun disc 1.24x and glow 0.91x Cycles, disc colour too neutral (v2_sky_sun)
- #947 Motion-blurred rotating vane: Astroray reads 0.84x (perspective) / 0.40x (ortho) of Cycles (v2_camera_geometry)
- #955 Add Shader(BSDF, BSDF) lowers to the first BSDF; Mix Shader 'dominant shader' fallback for unsupported pairs is silent
- #959 GPU vs CPU photon caustics disagree in v2_dispersion_caustics (prism sun floor 6.8x, spot floor 1.17x, sphere limb r 1.13x)
- #961 Spot-lamp shaft through fog reads 0.70 (CPU) / 0.75 (GPU) of Cycles (corpus v2_media)
- #963 GPU renders the hair tuft in corpus v2_camera_geometry as a bare scalp: no strands
- #1006 Object texture coordinates ignore the object transform (world point used, Blender uses object-local)
- #1019 Media: heavy-tailed variance (fireflies) in the smoke plume; relMSE falls slower than 1/N (equal-time efficiency 0.052 -> 0.006 vs Cycles OptiX)
- #1025 CPU prism sun caustic reads 0.74 of Mitsuba (GPU 0.92) once the film stops adding white

## HIGH and in flight tonight (7)

- #879 Viewport: live ASTRORAY_VIEWPORT_WORKER flip + shading toggle crashes Blender in nvcuda64.dll (100k scene) (viewport)
- #990 Object Info Random, Attribute and Color Attribute are unsupported (chain flattened to grey; Color Attribute drop is unreported) (N1)
- #991 Light Path node unsupported: Mix Shader with Is Camera Ray / Is Shadow Ray Fac is a silent drop; Ray Length flat (N1)
- #992 Float Curve and RGB Curves unsupported by the op-VM (RGB Curves drop is unreported) (N2)
- #1017 CPU op-VM: an input's own Mapping node is dropped (ProgramTexture evaluates inputs at the parent program's point) (#1023)
- #1020 Narrow-band lamp: rendered R/G 14 % below the CIE integral of the lamp's own stored SPD (as-arb)
- #1021 Sun-lit floor ROI (floor_far) 12-16 % brighter than both Cycles and Mitsuba (as-arb)

In-flight lanes: N1 #990/#991, N2 #993/#992, N3 #996, viewport #875/#721/#879, as-arb #1020/#1021, #1023 = #1007/#1017. Fix commit for #1020/#1021 (0d697932) is on `lane/as-arb`, not yet on main. #1025 and #1024 are as-arb follow-ups, not themselves in a lane.

## Already fixed on main (comment posted, not closed; lead to close)

- #868 fixed by 9a0286b0 (live GPU-lock holders never expire by age; atomic acquire).
- #988 fixed by #1009 / 150fad17 (textured Principled keeps all lobes; marble highlight 0.58 -> 0.97 CPU). Residual errors on those materials belong to #1006/#881/#993.

## Per-issue table

| # | Title | Claude | Terra | Final | In flight | Justification / evidence | Reconciliation |
|---|---|---|---|---|---|---|---|
| 36 | feat: Holdout and indirect-only objects | low | low | **low** | no | Holdout landed (#830, e55288ca); remaining indirect-only objects is a feature gap, no wrong image on a supported path. | agree |
| 38 | feat: Tiled rendering for memory efficiency | low | low | **low** | no | Feature request (tiling); only matters for >GPU-memory frames; no wrong output. | agree |
| 39 | feat: Persistent data for animation rendering | low | low | **low** | no | Feature request (persistent data); perf only. | agree |
| 141 | feat(material): diffraction grating / spectral mirror BSDF | low | low | **low** | no | New-feature request (grating BSDF); no code, no regression. | agree |
| 144 | feat(volume): spectral nebula emission and reflection media | low | low | **low** | no | New-feature request (nebula media); Pillar 4 paused. | agree |
| 398 | Future/architecture: engine-agnostic core â€” standalone + USD/Hydra render delegate (deco | low | low | **low** | no | Long-horizon architecture tracker (pkg177). | agree |
| 721 | Viewport: camera events block ~155 ms each; progressive refinement idles at ~1.3 Hz | medium | low | **medium** | viewport | Viewport latency (~155 ms/camera event); no wrong image, worker opt-in; improving (#831/#850), in flight. | Terra low (perf-only); kept medium (higher). Not high either way. |
| 763 | Corpus scenes: Astroray CPU at 128 spp is far noisier than Cycles CPU at 128 spp (material | medium | high | **medium** | no | Equal-spp noise vs Cycles, means match (geometry/colour agree); variance tracker (Batch O, #941). | Terra high; kept medium. Evidence: issue body states geometry/colour match, 'not a colour/shape divergence'; variance not bias; #941 root cause. |
| 773 | Rough/smooth glass limb 0.84x Cycles under clamp_indirect=10: Astroray under-produces diff | medium | high | **medium** | no | Limb 0.84x under clamp_indirect=10 is Cycles-only speckle caustic (diffuse->glass->lamp); addon export verified faithful (2026-09-29 comment); physics-vs-Cycles look. | Terra high; kept medium. Evidence: 2026-09-29 comment: addon export faithful (addon/engine 1.00); remaining gap is Cycles-only speckle caustic transport, documented limitation. |
| 783 | Thin-film-aware multiple-scattering microfacet glass walk (pkg265 follow-up) | low | already-fixed | **low** | no | Thin-film rough glass is gated out of the walk (falls to single-scatter); niche follow-up. | Terra already-fixed (b09e2713); kept low. Evidence: #778 only gated thin-film OUT of the walk; the issue's subject (thin-film-aware walk) is unimplemented. |
| 789 | Rough-glass multiple-scattering walk is achromatic: dispersion unmodelled on the pkg265 CP | low | low | **low** | no | Rough-glass walk achromatic; not a regression, smooth-glass dispersion works; niche. | agree |
| 853 | GPU principled_hair ~11 % brighter than CPU on unpigmented hair, darker in blue when pigme | medium | high | **medium** | no | GPU hair +11% flat vs CPU (-13% blue when pigmented); inside the pkg225 +-15% gate; strict xfail row (comment 2). | Terra high; kept medium. Evidence: inside the documented pkg225 +-15% gate, strict-xfail row filed (comment 2). |
| 855 | Viewport storm row: re-measure after #850 (full re-sync ~125 ms/edit is the floor until #8 | low | low | **low** | no | Re-measurement task for viewport storm row; no defect claim. | agree |
| 858 | Owner try-out checklist: viewport worker default (ASTRORAY_VIEWPORT_WORKER=1) | low | low | **low** | no | Owner try-out checklist, not a defect. | agree |
| 864 | test: resolve actual modules in pkg258 byte-identity baseline comparison | low | low | **low** | no | Test-harness module-path bug (pkg258 byte-identity test). | agree |
| 865 | tooling: investigate bounded delegate critic non-completion | low | low | **low** | no | Delegate tooling investigation. | agree |
| 866 | Native adaptive-sampling toggle remains custom-only: gate (d) baseline gap | high | high | **high** | no | Native scene.cycles.use_adaptive_sampling=False still resolves adaptive=True on CPU+GPU (settings_map.py L81-93 reads only the custom prop; _gpu_adaptive_ignored_reason covers only the GPU progressive case). Native setting silently ignored. | agree |
| 867 | Expose requested native Debug Sample Count pass for CPU/GPU F12 | high | high | **high** | no | Native view_layer.cycles.pass_debug_sample_count requested, RenderResult lacks the pass on CPU+GPU, no report. Native pass silently ignored (borderline: debug pass). | agree |
| 868 | fix(lock): prevent live GPU jobs losing ownership after 90 minutes | already-fixed | low | **already-fixed** | no | Live GPU-lock holders no longer expire by age, atomic acquire: 9a0286b0 'fix(lock) ... (#868)' on main. | Terra low (tooling); kept already-fixed. Evidence: 9a0286b0 on main. |
| 869 | build: avoid long CUDA compile failures in the default worktree cache launcher | low | low | **low** | no | Build tooling: scripts/build/build_cuda_worktree.bat L119 still sets the CUDA launcher to sccache; developer-only. | agree |
| 872 | Coverage matrix generator drifted from the committed matrix (full regen reverts 9 rows) | low | low | **low** | no | Coverage-matrix generator drift (dev tooling); committed matrix is the authority. | agree |
| 875 | Viewport: in-place transform update for non-instanced meshes | medium | low | **medium** | viewport | Object moves full re-sync (~130 ms); correct but slow, no wrong image; in flight (viewport). | Terra low; kept medium (higher). |
| 879 | Viewport: live ASTRORAY_VIEWPORT_WORKER flip + shading toggle crashes Blender in nvcuda64. | high | high | **high** | viewport | Blender crash in nvcuda64.dll on live worker flip + shading toggle (100k GPU scene); env-var-before-launch workaround. Crash. | agree |
| 881 | Noise Texture pattern differs from Cycles (correlation 0.73 unrotated) | high | high | **high** | no | Default Noise Texture correlates 0.73 vs Cycles (hash/octave/normalisation differ): wrong pattern on a ubiquitous node, no report. No landed commit on main references it. | agree |
| 884 | Indirect clamp removes far more energy on Astroray than Cycles in multi-scatter media (cab | medium | high | **high** | no | Indirect-clamp removes 9-10% vs 2% in media at default clamp: cabinet reads 0.92x Cycles; <10%, clamp is biased by design; metric-mismatch candidate. | Terra high accepted: unflagged clamp energy loss (9-10% vs 2% Cycles, up to 21% scatter cube), no documentation of the gap. |
| 890 | GPU procedural bake (pkg190) 64^3 nearest-voxel loses high-frequency detail (warped checke | medium | medium | **medium** | no | GPU 64^3 procedural bake loses high-frequency detail; reported as DEGRADED/approximated (#1009); per-hit eval (#1007) in flight. | agree |
| 894 | GR: Kerr accretion disk (Page-Thorne) - disk still uses the Schwarzschild model when spin  | medium | high | **medium** | no | Kerr disk stays on Schwarzschild model when spin != 0: Pillar 4 (paused) documented limitation; not a Blender-native setting. | Terra high; kept medium. Evidence: issue states the disk is deliberately kept on the documented a=0 model; Pillar 4 paused. |
| 895 | GR: black_hole shape plugin ignores spin and r_obs_M | medium | high | **high** | no | black_hole shape plugin ignores spin/r_obs_M (plugins/shapes/black_hole.cpp has neither); binding path honours both; Pillar 4 paused, not a Blender-native setting. | Terra high accepted: spin/r_obs_M silently ignored on the plugin path (wrong image for spin != 0). |
| 898 | Reference bank: re-bless all scenes on the corrected pixel mapping (pkg280 Phase 4) | low | low | **low** | no | Reference-bank re-bless (stale references); test infrastructure. | agree |
| 920 | GPU SMS device port weight diverges from the CPU pkg226 MNEE weight (dead code today) | low | low | **low** | no | Dead code (runSMSAttemptDevice has no callers); nothing renders wrong. | agree |
| 924 | Lamp pass-through capped at 4 lamps per segment (pkg288); 5th+ dropped | medium | high | **medium** | no | 5th+ lamp on one segment dropped (kMaxLampPassthrough=4, raytracer.h L3778); rare, small energy loss. | Terra high; kept medium. Evidence: needs >=5 lamps intersected by one ray segment; cap is a code-documented limit (raytracer.h L3775-3778). |
| 926 | Coplanar fog-box/floor face: Cycles darkens the floor 1.9x, Astroray does not | not-a-bug | not-a-bug | **not-a-bug** | no | Issue itself shows Astroray is physically consistent; Cycles coincident-face volume-stack artifact. Docs/corpus action only. | agree |
| 941 | CPU sampler is std::mt19937 (no QMC): variance x spp stays flat while Cycles' falls 4.5x f | medium | high | **medium** | no | CPU white-noise sampler (no QMC): variance, not bias; means unchanged. | Terra high; kept medium. Evidence: issue body: 'means unchanged in MC band'; variance only (converges). |
| 942 | Disney half-metal reads 0.91-0.93x Cycles under a sun (single blended specular lobe vs Cyc | medium | high | **medium** | no | Disney half-metal 0.91-0.93x Cycles under a sun: single blended lobe; <10%, Disney (Blender export uses Principled). | Terra high; kept medium. Evidence: 7-9% on Disney (custom material; Blender export maps Principled to the Principled plugin, #940/#1009). |
| 946 | Nishita sky at 4 deg sun elevation: sun disc 1.24x and glow 0.91x Cycles, disc colour too  | high | high | **high** | no | Nishita low-sun (4 deg): sun disc 1.24x (b 1.58x), glow 0.91x, disc not reddened: wrong image on the native Nishita sky at sunset; strict-xfail rows, no report. | agree |
| 947 | Motion-blurred rotating vane: Astroray reads 0.84x (perspective) / 0.40x (ortho) of Cycles | high | high | **high** | no | Motion blur: vane reads 0.84x/0.40x of Cycles, near-sharp vs wide blur, while matrix lists use_motion_blur SUPPORTED: native setting effectively wrong, unreported. | agree |
| 950 | test_blender_parity_harness _pyd_dir prefers build_blender_addon over build_cuda; an OpenM | low | low | **low** | no | Test-infra only (_pyd_dir ordering). | agree |
| 954 | GPU scalar op-VM programs sample only one texture input: Mix Shader programs with textured | medium | medium | **medium** | no | GPU scalar op-VM multi-input programs constant; reported as a DEGRADED entry (CPU exact). | agree |
| 955 | Add Shader(BSDF, BSDF) lowers to the first BSDF; Mix Shader 'dominant shader' fallback for | high | high | **high** | no | Add Shader keeps first BSDF (reported DEGRADED by pkg293) but the Mix Shader 'dominant shader' fallback is silent (shader_blending.py L111-112 returns with no report): silent wrong shader for unsupported pairs. | agree |
| 956 | Disney metallic>0 with transmission>0: CPU transmission roulette ignores metallic, GPU/CPU | medium | high | **medium** | no | Disney metallic+transmission roulette: GPU/CPU 2-4x at m=1, strict xfails; Disney custom material (Blender export uses Principled), odd corner. | Terra high; kept medium. Evidence: Disney-only, strict xfails in tests/test_pkg293_gpu_lobe_programs.py (documented), metallic=1+transmission corner. |
| 957 | Principled rough glass GPU/CPU 1.03-1.07 with constant parameters | medium | high | **medium** | no | GPU rough glass 1.03-1.07x CPU (single-scatter vs walk); pre-existing, strict xfails. | Terra high; kept medium. Evidence: 3-7% GPU/CPU, strict xfails, single-scatter-vs-walk is a known engine difference. |
| 959 | GPU vs CPU photon caustics disagree in v2_dispersion_caustics (prism sun floor 6.8x, spot  | high | high | **high** | no | GPU vs CPU photon caustics disagree up to 6.8x (prism sun floor) in v2_dispersion_caustics: wrong image on one backend, no report; strict-xfail rows (related #1025). | agree |
| 960 | Thin-film titanium spheres: single channels outside the MC band on CPU and GPU (v2_thin_fi | medium | high | **medium** | no | Thin-film Ti single channels 1.05-1.18x, luminance 1.02-1.05, marginal outside band; maybe noise-underestimated bands. | Terra high; kept medium. Evidence: luminance 1.02-1.05; single channels 0.03-0.04 outside the 3-sigma band, strict-xfail rows (project's documented-limitation mechanism). |
| 961 | Spot-lamp shaft through fog reads 0.70 (CPU) / 0.75 (GPU) of Cycles (corpus v2_media) | high | high | **high** | no | Spot-lamp shaft through fog 0.70x (CPU)/0.75x (GPU) of Cycles with 5-seed sigma 0.054: real mean bug on a common scene type, unreported. | agree |
| 963 | GPU renders the hair tuft in corpus v2_camera_geometry as a bare scalp: no strands | high | high | **high** | no | GPU renders corpus hair tuft with no strands (CPU matches Cycles): wrong image, no hair-drop report; distinct from #853. | agree |
| 965 | ReSTIR-DI renders textured Emission Color as its texture mean (GPU) | medium | already-fixed | **medium** | no | ReSTIR-DI textured emission = texture mean; prints a DEGRADED line. | Terra already-fixed (073e50ff); kept medium. Evidence: 073e50ff is #962 (wavefront); #965 is the ReSTIR-DI follow-up filed after it, and prints DEGRADED. |
| 966 | GPU: per-hit textured emission on instanced meshes (needs instance transform or local bary | medium | medium | **medium** | no | GPU instanced textured emission = texture mean; DEGRADED report. | agree |
| 967 | Volume multiple scattering: red channel low at volume_bounces 4 (box control 0.955 of Cycl | medium | high | **medium** | no | Homogeneous media red 0.955x Cycles at volume_bounces 4 (4.5%); pre-existing. | Terra high; kept medium. Evidence: 4.5% single channel, inside corpus bands (4-9%). |
| 968 | Glass rim reads +7.5 % vs Cycles with no volume (pkg296 glass-shell control) | medium | high | **medium** | no | Glass rim +7.5% vs Cycles, no volume; pre-existing Fresnel/TIR energy difference (<10%). | Terra high; kept medium. Evidence: 7.5% rim ROI, inside corpus bands (4-9%). |
| 969 | CPU render not bit-stable across unrelated refactors (FMA contraction / inlining moves up  | low | low | **low** | no | Bit-stability of CPU renders across refactors (<=2e-7 per pixel); gate-tolerance question. | agree |
| 975 | Voronoi Texture 2D/4D dimensions evaluated as 3D (DEGRADED); implement Cycles voronoi.h 2D | medium | medium | **medium** | no | Voronoi 2D/4D evaluated as 3D; reported DEGRADED. | agree |
| 977 | test_results conventions follow-ups (after #976) | low | low | **low** | no | test_results housekeeping follow-ups. | agree |
| 983 | Corpus v2: firefly in v2_media smoke_plume ROI at seed 278 (CPU leg, MSVC build) reads 1.3 | low | high | **low** | no | Single seed-278 firefly on the MSVC CPU leg, not a bias (MinGW reads 1.000); tracked strict row. | Terra high; kept low. Evidence: issue body: not a bias, one firefly at one seed, MinGW builds read 1.000; strict provisional row. |
| 986 | Corpus v2 bands: CPU sigma from correlated seeds 278-282 is underestimated (mt19937 seed+t | low | low | **low** | no | Corpus band sigma underestimated from correlated seeds; test-band methodology. | agree |
| 988 | Principled with a per-texel Base Color exports as textured Lambertian: specular, coat, met | already-fixed | already-fixed | **already-fixed** | no | Textured Principled keeps all lobes: #1009 (150fad17) body: marble highlight 0.58 -> 0.97 CPU; tests/test_issue988_textured_principled.py. PR left it open; remaining errors are other root causes (#1006/#881/#993). | agree |
| 989 | op-VM has no per-hit shading inputs: Layer Weight, Fresnel, Geometry (Backfacing, Pointine | medium | already-fixed | **medium** | no | Layer Weight/Fresnel/Backfacing landed in #1009 (OP_SHADING; car-paint lit_front G 4.64 -> 0.87); remaining Pointiness/other Geometry outputs are reported (DEGRADED), not silent. | Terra already-fixed (150fad17); kept medium. Evidence: #1009 body lists Pointiness/other Geometry outputs still reported DEGRADED; issue left open by the PR. |
| 990 | Object Info Random, Attribute and Color Attribute are unsupported (chain flattened to grey | high | high | **high** | N1 | Color Attribute drop is unreported; Object Info Random/Attribute flatten to grey (prod_attributes G 2.20x). In flight (N1). | agree |
| 991 | Light Path node unsupported: Mix Shader with Is Camera Ray / Is Shadow Ray Fac is a silent | high | high | **high** | N1 | Mix Shader with Light Path Is Camera/Shadow Ray Fac dropped silently (emitter ring visible, hidden-emitter L 0.07 vs 2.2). In flight (N1). | agree |
| 992 | Float Curve and RGB Curves unsupported by the op-VM (RGB Curves drop is unreported) | high | high | **high** | N2 | RGB Curves dropped with no report; Float Curve flattens chain (reported); prod_curves_geometry outer_front R 0.36. In flight (N2). | agree |
| 993 | op-VM VM_MAX_SLOTS bound exceeded by an ordinary wood Roughness chain (Wave + Noise -> Mat | medium | medium | **medium** | N2 | VM_MAX_SLOTS exceeded: chain flattened to grey but reported ('not representable ... flattened to grey'). In flight (N2). | agree |
| 994 | GPU skips OBJECT-coordinate procedural programs (flat value): marble GPU 0.38-0.72x, wood  | medium | already-fixed | **medium** | no | GPU Object-coordinate programs now baked (64^3, #1009) and reported approximated; marble GPU 0.99-1.08 after; per-hit eval (#1007) in flight. | Terra already-fixed; kept medium. Evidence: #1009 body: GPU bake is lossy and reported approximated; per-hit eval is #1007. |
| 995 | Nested Mix Shader with textured Fac and a Glass branch collapses to a constant mix (prod_s | medium | medium | **medium** | no | Nested Mix with textured Fac + Glass collapses to constant mix, reported ('approximated MIX_SHADER ...'); prod_shader_stack 0.28-0.45x. Large error but flagged. | agree |
| 996 | coverage_matrix classifies op-VM-compiled sockets DROPPED-SILENT; pkg310 audit counts ~32  | low | low | **low** | N3 | Coverage-matrix/audit classification (stale rows): instrumentation, not render output. In flight (N3). | agree |
| 997 | test_spatial_reduces_mse is a coin flip: spatial/no-reuse MSE ratio 0.98-1.02 across seeds | low | low | **low** | no | Flaky test (spatial-reuse MSE coin flip). | agree |
| 998 | pkg287 sun photon caustic reads 1.07-1.10x the path-traced reference on main (gate 0.10) | medium | low | **medium** | no | Photon sun caustic 1.07-1.10x PT reference vs 0.10 gate; either 9% bright or noisy reference; undecided. | Terra low; kept medium (higher). |
| 1001 | pkg299 follow-ups: TTFS (CPU BVH off the GPU path), IAS refit, shared OptiX context, OptiX | low | low | **low** | no | pkg299 perf follow-ups (TTFS, refit, shared context). | agree |
| 1002 | pkg277 warped checker: GPU bake error 0.61 exceeds the 0.486 model once the CPU noise floo | medium | medium | **medium** | no | GPU warped-checker bake error 0.61 > 0.486 model; lossy bake reported approximated; strict xfail; addressed by #1007. | agree |
| 1004 | Mapping Scale driven by a node-group input (via Combine XYZ) is silently ignored: prod_pbr | medium | already-fixed | **medium** | no | Cause fixed in #1011 (ff7e1438: image REPEAT + Normal/Bump Mapping); tile layout matches; residual centre ~0.91x. No longer silent. | Terra already-fixed (ff7e1438); kept medium. Evidence: lane comment: residual centre ~0.91x, issue deliberately left open. |
| 1005 | Bump node with a procedural Height (Voronoi/Noise) is silently dropped | medium | medium | **medium** | no | Procedural Bump Height is now a DegradationReport entry (#1011); CPU overshoots ~2x on car_paint but flagged. | agree |
| 1006 | Object texture coordinates ignore the object transform (world point used, Blender uses obj | high | high | **high** | no | CoordMode::Object returns the world point (advanced_features.h L165-166); every Object-coordinate procedural on a non-identity object is shifted/rotated/scaled vs Blender, unreported. Not in any lane. | agree |
| 1007 | GPU: evaluate procedural textures per hit instead of the 64^3 voxel bake (Object-coordinat | medium | medium | **medium** | #1023 | GPU procedurals via lossy 64^3 bake, reported approximated; per-hit eval in flight (#1023). | agree |
| 1015 | test_pkg224_progressive_sobol_gpu::test_progressive_lowers_noise fails on main: progressiv | low | low | **low** | no | Failing test (progressive Sobol GPU assertion); test issue, check sampler engagement. | agree |
| 1017 | CPU op-VM: an input's own Mapping node is dropped (ProgramTexture evaluates inputs at the  | high | high | **high** | #1023 | CPU op-VM drops an input's own Mapping node (prod_wood rotate/scale lost) silently, both backends. In flight (#1023). | agree |
| 1019 | Media: heavy-tailed variance (fireflies) in the smoke plume; relMSE falls slower than 1/N  | medium | high | **high** | no | Heavy-tailed variance (fireflies) in media; noise not bias. | Terra high accepted: fireflies persist at 1024 spp, variance falls slower than 1/N (heavy tail); unflagged visible artifact. |
| 1020 | Narrow-band lamp: rendered R/G 14 % below the CIE integral of the lamp's own stored SPD | high | already-fixed | **high** | as-arb | Narrow-band lamp R/G 14% below CIE integral of its own SPD: colour-accuracy bug. In flight (as-arb). | Terra already-fixed (0d697932); kept high/in flight. Evidence: 0d697932 is on lane/as-arb only (git branch --contains), not on main. |
| 1021 | Sun-lit floor ROI (floor_far) 12-16 % brighter than both Cycles and Mitsuba | high | high | **high** | as-arb | Sun-lit floor 12-16% brighter than both Cycles and Mitsuba: wrong image. In flight (as-arb). | agree |
| 1024 | Film: out-of-gamut channels clipped to 0 per pass/beauty; decide whether scene-linear outp | medium | high | **medium** | no | Design decision: negative out-of-gamut channels clipped to 0 per pass; follow-up of #1020. | Terra high; kept medium. Evidence: deliberate documented design choice (clip at 0) awaiting an owner decision; follow-up of #1020. |
| 1025 | CPU prism sun caustic reads 0.74 of Mitsuba (GPU 0.92) once the film stops adding white | high | high | **high** | no | CPU prism sun caustic 0.74x of Mitsuba (z -7.4): real CPU transport deficit exposed by the #1020 fix (follow-up of as-arb, not itself in a lane). | agree |
