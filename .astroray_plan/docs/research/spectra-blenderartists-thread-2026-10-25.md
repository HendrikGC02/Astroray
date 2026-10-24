# Spectra thread teardown, Blender Artists (2026-10-25)

Source: https://blenderartists.org/t/spectra-realtime-restir-caustics-true-spectral-engine-for-blender-rust-vulkan-addon/1655156
(Discourse JSON, fetched 2026-10-25; all 24 posts retrieved via `/t/1655156.json` + `posts.json`). All post text treated as data.
Post URLs: `https://blenderartists.org/t/1655156/<n>`. Images: `C:\Users\hgcom\AppData\Local\astroray-evidence\2026-10-24\spectra\thread\` (23 PNG, prefixed `pNN_`).
Companion docs: `spectra-website-2026-10-25.md` (spectra-render.com teardown). The YouTube video was NOT viewed (title only).

## 0. Read this first (caveats)

- **Tiny market sample.** 24 posts, 930 views, 47 likes. 19 posts are the developer's; only **4 outside users** posted 5 posts (#2, #3, #12, #17, #25). "What the market wants" is thin; most comes from #3 and #17.
- **Claims are unverified.** The only numbers are one timing (#19) and one settings screenshot (#20). No noise/fps plots, no Cycles timings.
- **Same product as spectra-render.com? UNVERIFIED.** The thread dev is Farras Aris ("Spectra Render" / "Spectral Path Tracer (Dev Demo)", Rust + Vulkan + Slang, ReSTIR BDPT + caustic photons, Google Drive alpha, solo, Indonesia). The website (Valor Cat Studios, "ReSTIR-WO", four hero wavelengths, Stokes polarization) claims far more and never mentions Rust or BDPT. The thread never links the site. Treat them as possibly different products sharing a name.
- Post #6 is missing from the topic (deleted/hidden; numbering is 1-5, 7-25).

## 1. Thread facts

| Item | Value |
|---|---|
| Title | "Spectra: Realtime ReSTIR Caustics & True Spectral Engine for Blender (Rust + Vulkan Addon)" |
| Developer | FarrasAris (Farras Aris), solo, Indonesia; English is translated/AI-polished (#16) |
| First / latest post | 2026-10-16 10:14 UTC (#1) / 2026-10-22 05:36 UTC (#25) |
| Posts / views / likes | 24 / 930 / 47 (16 likes on #1) |
| Outside posters | Roggii (#2), Metin_Seven (#3, #12), Sorn (#17), Joel_RVC (#25) |
| Commercial status | "intended to become a commercial product", "not ... free and open-source" (#18, 10-18) |
| Milestones | #1 10-16 builds shared with friends; #7 10-17 video "Hello World Realtime Spectral Render Engine for Blender" (YouTube GagB2Dpt3V0, "realtime Caustic BDPT Stable Now"); #9 10-17 Dielectric Graceful Exit; #11 10-18 Phase 1 node suite on Blender 5.2 LTS, "zero-stall IPC", "standalone Rust + Vulkan daemon"; #13 10-18 **first public Alpha** `spectral_blender_addon_demo.zip` via Google Drive (watermarked); #19 10-19 showcase; #21 10-19 Cycles parity suite (4 sheets); #22 10-19 "new dev build" (same Drive link, no changelog); #25 10-22 first outsider shading critique |
| Version | UI shows "Spectra Dev Demo" on Blender 5.2.1 LTS (#19/#20 images). No version number stated. |

## 2. Developer claims (post, date)

**Architecture / platform**
- Rust + Vulkan + Slang, "from the ground up" (#13, 10-18; #1, 10-16). Vulkan **RT** (hardware) engine; GPU: "Vulkan Ray Tracing compatible (NVIDIA RTX recommended)" (#13).
- **Out-of-process daemon + Python addon + "high-speed IPC"**: Blender's main thread never freezes on material tweaks or orbit (#13; "zero-stall IPC" #11).
- Windows 10/11 only; Blender 4.0 to 5.2 LTS; OIDN and TBB DLLs bundled (#13).
- Solo dev, uses AI as "24/7 pair-programmer" (#16, 10-18, answering the vibe-coding question #12).

**Spectral pipeline**
- "Continuous wavelength spectrums" (#13). Dispersion via **Cauchy** formula, no fake colour-split (#13). Custom "Spectral Cauchy Glass" node: Base IOR, Dispersion, Roughness, Absorption colour, Thin-Walled, Dielectric Priority for nested glass (#13; #19 image: IOR 1.517, dispersion 0.008).
- Thin-film interference (soap/oil/coatings) via "Spectral Thin-Film Iridescence" node; **Spectral Blackbody Emitter** (Kelvin); **Spectral Metallic Car Paint Flakes** node (#13). Blender 5.2's native Principled "Thin Film" panel is visible in #10/#21 screenshots.
- Blender Wavelength node honoured: 532 nm gives a green sphere (#10 image p10_06).
- Render panel "Spectral Optics & Physics" has **Mode: "RGB Fast Tracing"** (a dropdown, so an RGB mode coexists with spectral) and colour pipeline "AgX / Linear Scene-Referred" (#20 image).
- NOT stated in the thread: wavelengths per sample, hero-wavelength use, RGB-to-spectrum upsampling, Abbe model, fluorescence, polarization. (The website claims 4 hero wavelengths and Stokes; the thread does not.)

**Light transport / ReSTIR / caustics**
- "ReSTIR BDPT" is "one of the main techniques" (#1, 10-16); video "realtime Caustic BDPT stable" (#7).
- Settings panel (#20 image): **ReSTIR BDPT** checkbox; sub-panel "Caustic Photons & ReSTIR BDPT": Photon budget **4M Photons (Max)**, Caustic Intensity 10.00, Caustic Firefly Clamp 1.00, Caustic Bounces 8, **Sun Emitter Radius 5.50**; also "Spatial Path Guiding" (unchecked) and Max Light Bounces 12. So caustics = photon map + ReSTIR BDPT hybrid (INFERRED from UI labels; no text explains it).
- **Dielectric Graceful Exit** (#9, 10-17): after the exit-bounce limit (8) glass turns into transparent passthrough and the ray is "released" to find lights, instead of black dead spots; "similar to Redshift's refraction limit". UI: checkbox plus "Exit Bounce Depth 8" (#20 image).
- Nothing on spatiotemporal reuse details, MNEE/SMS, GI/PT naming or unbiasedness.

**Denoising / viewport / speed**
- OIDN in viewport and F12 (#13). Banner "Spectral | Done: 64 Samples (Denoised)" (#20 image). Progressive, instant camera/transform updates (#13).
- **Only speed number:** 1000x1000, "under 8 seconds", **RTX 3080 Mobile laptop** (#19, 10-19); spp/scene settings not given (parity suite used 64 spp, #21).
- No fps, VRAM or scene-size figures anywhere.

**Blender integration / node support**
- Native Blender shader trees translated "on the fly": Principled (Base Color, Roughness, Metallic, Transmission, IOR, Emission), Color Ramp, Mix, Math, textures (#13, #16); OpenPBR-aligned Principled "1:1" (#5, 10-16).
- Candid limits (#21, 10-19): "not every Blender node is 100% compatible"; gaps in procedural textures, vector-math edge cases, curve evaluation, "translation and baking pipelines" (implies procedurals are **baked**). Section 3 shows what the sheets show.
- HDRI equirect was rotated 90 deg vs Blender; fixed (#21).
- Alpha puts a watermark on viewport and F12 (#13).

**Roadmap promises**
- Material library/presets (#5); post-processing (bloom, chromatic aberration) "in progress" (#5, requested in #3); remaining node coverage (#21); "Phase 1" node tests imply later phases (#11); commercial release, price/licence unstated (#18). Physical lights and easy environment lighting claimed "Done" (#5).

## 3. Benchmarks and comparisons

One benchmark only: **Spectra vs Cycles GPU (OptiX)**, #21 (10-19). Conditions: glTF/USD Shader Ball, HDRI studio lighting only, AgX, 64 spp, 12 bounces, OIDN on both. Hardware not stated (INFERRED: the 3080 Mobile laptop of #19). Metrics: none; visual side-by-side plus Blender node screenshot. No LuxCore/Octane/Corona comparisons (Corona/Octane only named as design targets, #5). No timings.

My reading of the sheets (**INFERRED visual judgement**, not dev claims):

| Test (sheet) | Cycles vs Spectra |
|---|---|
| G1 Principled (blue, metallic 0.8, rough 0.2) | close, Spectra slightly darker |
| G1 Metallic (gold) | close |
| G1 Glass (rough 0.02) | Spectra greyer/duller inside |
| G1 Diffuse (pink) | close |
| G1 Sheen (magenta) | **mismatch**: Cycles near-black velvet, Spectra bright magenta (matches Joel_RVC #25) |
| G1 Emission, Mix shader | close |
| G2 Mapping scale / offset+rot | close |
| G2 Normal map (strength 1.6) | pattern matches, Spectra much glossier |
| G2 Bump | **fail**: bump ignored, smooth sphere, colour differs |
| G3 Checker / Noise fBm / Wave / Gradient+ColorRamp | pattern scale and colours differ (saturated, different ramps) |
| G3 Voronoi + bump | **fail**: flat blue, pattern missing |
| G4 Separate/Combine Color | close |
| G4 Separate/Combine XYZ; Vector Math dot/normalize | **fail**: plain white |
| G4 Bright/Contrast + Gamma | close |
| G4 RGB Curves | **hue mismatch** (teal vs pink) |

My count: about 9 of 21 rows close, 12 differing or failing. The dev publishes this openly, so these are known gaps.

## 4. User feedback ("what the market wants")

Only 5 outside posts. Grouped (count of distinct asks, posts):

| Group | Count | Posts | Detail |
|---|---|---|---|
| Ease of use, not "a gazillion functions" | 1 | #3 (3 likes) | simple controls, no study required |
| Correct, easy materials (Fresnel, refraction) | 1 | #3 | physically correct by default |
| Ready-made material presets | 1 | #3 | plastic, skin, cloth, hair, metals; dev agrees (#5) |
| Easy, controllable SSS | 1 | #3 | dev: spectral makes it "easy and convincing" (#5, not shown) |
| Light falloff near edge (avoid harsh reflections/refractions) | 1 | #3 | controllable lamp border falloff |
| Easy environment lighting with separate visible background | 1 | #3 | dev: "Done" (#5) |
| Post-processing: bloom, chromatic aberration | 1 | #3 | dev: in progress (#5) |
| Wants a test build | 1 | #2 (3 likes) | Roggii; dev promises link by chat (#4) |
| Authorship transparency (native nodes? vibe-coded? team?) | 3 questions | #12 | answered #16 |
| Commercial vs open-source intent before investing time | 1 | #17 (1 like) | answered #18: closed commercial |
| Shading critique: diffuse and sheen should not have specular | 1 | #25 | matches the Sheen sheet mismatch |

Praise: no explicit praise beyond "Looks promising!" (#2). Likes are the signal: #1 16, #9 4, #19 2, #21 3, #23 3; render and caustic posts draw likes, text updates do not.
Bugs: outsiders 1 (#25). Dev-disclosed: bump, XYZ/vector math, voronoi, RGB curves, sheen (#21 sheets); glass black dead-spots (#9, fixed by Graceful Exit); HDRI rotation (#21, fixed).
Not requested by anyone: GR/astro, volumes, hair, headless/cluster, AMD, Linux, animation.
Trust friction: vibe-coding suspicion (#12), licence opacity (#17), Google Drive distribution plus watermark (#13, #17).

## 5. Images (23 files, all downloaded; all viewed except p10_02-p10_05, p10_07 single frames, covered by the p10_01 contact sheet)

Dir: `C:\Users\hgcom\AppData\Local\astroray-evidence\2026-10-24\spectra\thread\`. All posted by FarrasAris. Original URL = `https://blenderartists.org/uploads/default/<hash>` (in the post HTML).

| filename | post | caption/context | scene contents | feature shown |
|---|---|---|---|---|
| p01_01_image.png (677x513) | #1 | hero image | dark room; glass Suzanne, glass diamond/sphere on glossy floor; light streaks | caustics, dispersion fringes, noisy glass |
| p01_02_image.png (777x617) | #1 | hero image | glass prism, spectrum fans across a dark floor; grain | dispersion rainbow |
| p01_03_12.png (1920x1080) | #1 | car, credit "2024 Nilu 27 Concept" (Ddiaz Design, Sketchfab) | extreme-DoF suspension spring, gold damper, chrome, red body | metals, DoF, soft HDRI |
| p01_04_spectral_render.png (1440x1080) | #1 | "spectral_render" | large brilliant-cut diamond, blue-grey backdrop | dispersion fire |
| p01_05_5.png (1920x1080) | #1 | same car | red/black coupe, top-down, chrome wheels, hard shadow, light streaks on floor | car paint, glossy |
| p09_01_image.png (1213x646) | #9 | "Dielectric Graceful Exit OFF / ON, 8 Bounce" | thick glass tumbler in front of HDRI city street | bounce-cap glass |
| p10_01_p1_all_nodes_contact_sheet.png | #10 | Phase 1 nodes | six sphere renders: colour ramp, mix, wavelength, invert, math, RGB to BW | node coverage |
| p10_02_p1_01_color_ramp, p10_03_p1_06_rgb_to_bw, p10_04_p1_05_math, p10_05_p1_04_invert, p10_06_p1_03_wavelength, p10_07_p1_02_mix_color (1413x556) | #10 | render left, Blender 5.2 node graph right | single sphere on studio backdrop | each node |
| p19_01_3.png (1000x1000) | #19 | "Spectra Dev Demo" watermark; "under 8 s, RTX 3080 Mobile" | orange absorbing glass cube, glass objects, caustic streaks on plane | absorption + caustics |
| p19_02_4.png (1920x1042) | #19 | Blender screenshot, Test.blend | Camera, Cube, Light, Plane; Spectral Cauchy node (IOR 1.517, disp 0.008, rough 0, peach absorption, priority 1) | node parameters |
| p19_03_1.png (1000x1000) | #19 | showcase | cube inside large petal-shaped caustic rings with radial rays | caustic focus patterns |
| p19_04_2.png (1000x1000) | #19 | showcase | orange cube, light plane, faint spiky caustics | caustics |
| p20_01_image.png (1920x1012) | #20 | Blender UI, Porsche 911 (free model), "Spectral \| Done: 64 Samples (Denoised)" | Principled paint metallic 0.7, rough 0.1, coat 0.03; render panel (section 2 settings) | settings, car paint |
| p21_01 core_bsdf_closures (1937x3988), p21_04 textures_and_uv_mapping (x2272), p21_03 procedural_patterns_and_colorramp (x2844), p21_02 math_vector_and_color_grading (x2844) | #21 | Cycles GPU vs Spectra vs node graph | shader ball (sphere with cutaway, base ring) on checker floor, HDRI | parity: 7 closures, 4 texture/UV, 5 procedurals, 5 math/colour |
| p23_01_Untitled.png (1920x1080) | #23 | no text | Stanford bunny with iridescent surface, black void, rainbow caustic floor | thin-film, dispersion caustics |

Google Drive link-preview icons in #13/#22 skipped. Google Drive archive NOT downloaded (untrusted binary).

## 6. Scenes we should rebuild

Common: Cycles-node materials only; run CPU and GPU, compare to a Cycles reference where applicable; save PNGs for qualitative inspection (CLAUDE.md 5c).

1. **Prism spectrum fan** (p01_02). Triangular prism IOR 1.52 with Abbe ~58 (Cycles 5.3 dispersion sockets); narrow slit area/spot light; matte grey floor; black world; camera low. Measure: fan angular spread vs analytic Cauchy/Sellmeier, colour order, noise per spp.
2. **Brilliant diamond** (p01_04). Faceted diamond mesh IOR 2.42 with dispersion; studio HDRI plus floor. Measure: fire colour spread, firefly count, spp to clean, time.
3. **Tumbler on HDRI street, bounce cap** (p09). Thick glass (IOR 1.5) on plinth, city HDRI; render at max bounces 4/8/12 plus a high-bounce reference. Measure: dark dead-spot fraction vs bounces, energy vs reference.
4. **Absorbing glass cube + caustic plane** (p19). Glass cube IOR 1.517, dispersion 0.008, orange absorption; glass sphere nearby; one small bright light above; white plane; 3/4 low camera, 1000x1000. Measure: caustic shape/brightness vs long path-traced reference, convergence time, wall time.
5. **Dark caustic lineup** (p01_01). Glass Suzanne, diamond-like sphere, small spheres on a glossy dark floor; single hard light; black world. Measure: caustic quality, fireflies, spectral banding.
6. **Iridescent bunny** (p23). Stanford bunny with Principled thin film (thickness 400-900 nm) on a glossy floor; black world; small bright sun. Measure: thin-film hue vs analytic, caustic colours.
7. **Shader-ball node parity bench** (p21). glTF/USD shader ball on checker floor, HDRI studio, AgX, 64 spp, 12 bounces, OIDN; the 21 materials of the four sheets (see section 3 table). Measure: per-tile luminance/chroma ratio vs Cycles and SSIM with attribution. Cheapest, highest market signal: the rival fails ~12 of them.
8. **Car paint + ground** (p20, p01_05). Free Porsche 911 or Nilu-class coupe; paint metallic 0.7, rough 0.1, coat 0.03; grey ground; sun + sky. Measure: clearcoat look, soft shadow, reflection noise, viewport fps.
9. **Wavelength-node sphere** (p10_06). Sphere with Wavelength node 532 nm into base colour; studio backdrop. Measure: sRGB chroma vs analytic spectral-to-sRGB (Astroray: JH upsampling + CIE 1931 2 deg, STATUS #837).
10. **Macro mechanical close-up** (p01_03). Spring/damper/chrome assets, shallow DoF, HDRI. Measure: DoF noise, glossy convergence.

## 7. Astroray vs the thread (matches / lags / leads)

Astroray facts from `STATUS.md` and memory; INFERRED where noted.

| Area | Thread says | Astroray | Verdict |
|---|---|---|---|
| Spectral transport / hero wavelength | continuous spectrum (#13); per-sample count unstated | hero-lambda stratified camera group (pkg305), hero-lambda proposal (#848), CIE 1931 + JH upsampling (#837) | Matches/leads (INFERRED, nothing to compare in thread) |
| Dispersion | Cauchy node (#13/#19) | Cycles 5.3 dispersion sockets (pkg207), dispersion energy fix (#901) | Matches; Spectra adds a custom node with glass priority nesting |
| Thin film | node + Principled panel | Principled thin-film, metal thin-film sign fix (#902) | Matches |
| Blackbody emission | node (#13) | spectral Planck lamps (pkg218), volume blackbody (pkg270) | Matches/leads |
| Polarization / fluorescence | absent in thread (website: Stokes) | not found in STATUS (INFERRED absent) | Lags vs the website claim only |
| Caustics | photons + ReSTIR BDPT, 4M photons (#20) | photon caustic (pkg286/287, 1.00-1.07x path traced), SMS (off by default in Blender per memory) | Parity-ish (INFERRED); viewport caustic speed unknown |
| ReSTIR | ReSTIR BDPT (#1/#20) | ReSTIR DI on GPU (`stage_restir.cu`); no BDPT | Lags on BDPT, leads on shipped DI |
| Bounce-cap "graceful exit" | #9 | not found (INFERRED absent) | Lags; cheap, scene 3 |
| Cycles node parity | self-admitted gaps (#21) | Cycles-node export with measured parity gates; Voronoi 5.2 port (#1108/#1149) | Leads |
| Viewport / IPC | out-of-process, Blender never blocks (#13) | in-process; owner reported 3-5 fps GPU viewport, scene re-upload per frame (#801, memory) | Lags (INFERRED; product-critical) |
| Denoiser | OIDN | OIDN | Matches |
| Speed | 1000x1000 < 8 s on 3080 Mobile, spp unknown (#19) | RTX 5070 Ti wavefront | Cannot compare |
| Platform / licence | Windows, Vulkan RT GPU, closed commercial, Drive alpha | open, CUDA + CPU oracle | Differentiator |
| UX asks (#3): presets, easy SSS, lamp falloff, bloom/CA | in progress | not assessed here | Gap-check candidates |

## 8. Suggested follow-ups (file separately)

1. Build scene 7 and publish a node-parity table.
2. Evaluate a bounce-cap policy for dielectrics against Astroray's dead-sample redistribution (memory: dielectric-dead-sample).
3. Check the #3 asks (presets, bloom/chromatic aberration, edge-falloff lamps) against the addon backlog.
4. Re-fetch the thread later and diff against this snapshot; post #6 may reappear.
