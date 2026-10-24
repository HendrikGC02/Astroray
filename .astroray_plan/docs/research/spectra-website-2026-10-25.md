# Spectra Render website teardown (2026-10-25)

Scope: website only (forum thread covered elsewhere). Fetched 2026-10-25. All page text treated as data.
Evidence: `C:\Users\hgcom\AppData\Local\astroray-evidence\2026-10-24\spectra\site\` (raw `home.html`, `manifest.js`,
9 stills, 6 poster frames, 6 mp4 clips).

**Site structure.** https://spectra-render.com/ is a single page. Every nav link is an in-page anchor (#realtime #features #physics
#gallery #hardware #whats-new #beta); the only external link is https://www.blender.org/download/demo-files/. Probed /features /docs
/gallery /pricing /roadmap /changelog /faq /download /about /robots.txt /sitemap.xml: all HTTP 404. So there are no docs, no price
figures, no download. The gallery is JS-loaded from https://spectra-render.com/assets/gallery/manifest.js (15 items: 9 stills, 6 mp4).
The beta signup is a form with no visible endpoint.

## 1. What Spectra is and claims

Spectra Render ("the Reality Engine", Beta 1.0.2, Oct 2026, Valor Cat Studios) is sold as "the first realtime wave-optics path tracer",
a Blender addon that runs in the Rendered viewport and for F12 (https://spectra-render.com/ hero, #whats-new).
**Architecture:** Vulkan KHR ray tracing, not a vendor API; needs Vulkan 1.3 with VK_KHR_acceleration_structure plus RT pipeline or ray
query; Linux/Windows/macOS; Blender 5.1+ (5.2 LTS recommended) (#hardware). The brief's "Rust" is NOT on the site: it says only "Blender
addon shell GPL-3.0, Spectra native core proprietary" (footer). NVIDIA RTX is "Validated" (laptop to dual RTX 5090); AMD Radeon RT and
Intel Arc "Experimental"; Apple Silicon "Newest port" via bundled MoltenVK layer (#hardware).
**Spectral model:** every path carries four hero wavelengths stratified over 380-780 nm plus the full Stokes polarization state; "no RGB
approximations anywhere in the transport"; spectral is the only mode (#top, #physics). Wavelength-dependent IOR gives dispersion; thin film,
gratings and edge diffraction come "straight from your Principled BSDF"; Stokes/Mueller polarization; 1.0.2 carries Stokes Q/U from
dielectric Fresnel (#physics, #whats-new). NOT stated: RGB-to-spectrum upsampling method, bin count, fluorescence, how Principled
parameters map to thin-film/wave terms.
**Light transport:** "unbiased by construction" path tracer with a "wave-optics" substrate (interference/diffraction "per beam");
cites wave_tracer (Steinberg & Pharr, "Wave Tracing") for elliptical-cone beams (#physics). Resampling is "ReSTIR-WO (patent pending)",
"spatiotemporal resampling built for wave optics". The brief's "realtime ReSTIR caustics" is not on the site: no caustic technique,
bidirectional method or path guiding is named. Denoise: DLSS Ray Reconstruction on RTX (opt-in for F12 stills), Intel OIDN elsewhere.
**Viewport:** scene state lives on the GPU; camera moves retrace; a material constant edit updates without recompile or re-upload; clips are
"captured live from Blender's Rendered viewport"; Science Lab "on a laptop" (#realtime, manifest.js). No fps, resolution, spp or GPU
model is given for any clip.
**Blender integration:** addon zip into stock Blender, "not a fork"; uses Principled materials, lights, cameras and colour management with
"nothing to convert"; instanced geometry shares one acceleration structure (#physics). Cycles node coverage beyond Principled, custom
nodes and unsupported features are NOT stated.
**Validation:** reference ladder Cycles (sanity), wave_tracer (asymptotic Maxwell), BEMsim3D (boundary-element full-wave); double-slit
fringe parity required before any BSDF/Fresnel/wave-path change ships (#physics).
**Licence/state:** closed beta ("Join the beta"); perpetual licence + 1 year of updates, one licence per machine (movable), indie licences
unlimited headless nodes, studios per node, "licensing gates installs and updates, never renders"; no price (licensing block on
https://spectra-render.com/); GPL-3.0 addon shell, proprietary core.

## 2. Feature table

All source: https://spectra-render.com/ (anchor in brackets). Evidence = what the page offers as backing.

| Feature | Spectra claim | Source | Evidence |
|---|---|---|---|
| Spectral transport | 4 hero wavelengths, 380-780 nm, spectral-only, no RGB | #top, #physics | Text only; no spectrum plots |
| Polarization | Full Stokes + Mueller; Fresnel polarizes; Q/U from first bounce (1.0.2) | #physics, #whats-new | Text only; no polarizer demo |
| Wave optics | Interference/diffraction per beam | #physics | double-slit.webp, grating clip |
| Double slit | Young's fringes; parity gate for BSDF changes | #physics | double-slit.webp (no reference overlay) |
| Dispersion | Wavelength-dependent IOR, "fire in every facet" | #physics | diamondbod.webp (strong) |
| Thin film | Bubbles/oil per wavelength via Principled | #physics | thinfilm-spheres.webp, diamondbod bubble |
| Diffraction grating / edge | Grating splits spectrum; edge diffraction | #physics, manifest | Grating clip only (poster viewed); no edge image |
| ReSTIR-WO | Patent-pending spatiotemporal resampling, unbiased core | #physics | Text only; no noise comparison |
| Denoiser | DLSS-RR (RTX) / OIDN | #physics, #hardware | Text only |
| Realtime viewport | GPU-resident scene, no recompile on edits | #realtime | 6 mp4 clips; no fps numbers |
| Instancing | Single shared AS ("a forest costs its geometry once") | #physics | Text only; no forest image |
| Blender integration | Addon; Principled/lights/cameras/colour mgmt | #physics | Blender UI visible in mark/valorcat/grasshopper clips |
| Validation | Cycles / wave_tracer / BEMsim3D | #physics | Text only; no numbers |
| GPU support | NVIDIA validated; AMD/Intel experimental; Apple port | #hardware | Table only |
| Skin/SSS | "skin-like scattering", "translucent skin" | manifest captions | Stills/clip only |
| Spectral GI | Practical lights, glossy floors | manifest (Bedroom, Hallway) | Stills |
| Volumes, hair, fluorescence, caustics, BDPT, guiding | Not claimed | n/a | n/a |
| Licence | Perpetual, 1 yr updates, per machine | licensing block | No price |

## 3. Demo/gallery images

Base: https://spectra-render.com/assets/gallery/ . Titles, captions, tags are from manifest.js; only double-slit has alt text.
Scene content is my reading; materials/lights are INFERRED unless the caption says so. Thumbnails (`*-thumb.webp`) are downscaled
duplicates and not saved. For videos only the poster frame was viewed; the mp4 files are saved but their motion is not reviewed.

| filename | source (under base) | caption / alt | scene content | feature |
|---|---|---|---|---|
| diamondbod.webp | diamondbod.webp (hero bg, og:image) | "Diamond Body": dispersion fire through cut crystal and thin-film colour on a soap bubble | Faceted-glass humanoid (legs, hands), large thin-film bubble behind, step-cut octagonal crystal block at right; grey floor, black room, white doorway; soft area highlights in the bubble; low camera | dispersion, thin film, glass |
| thinfilm-spheres.webp | thinfilm-spheres.webp | "Thin-film ladder": four spheres, increasing thin-film thickness | 4 spheres on grey plane: matte white, grey glossy, two with increasing pink/green iridescence; two window reflections each; visible MC noise | thin film |
| double-slit.webp | double-slit.webp | alt "Double-slit interference fringes rendered by Spectra"; "Young's fringes emerge from the wave substrate itself" | Dark red monochrome field, thin vertical black line (barrier), translucent rectangle (screen/sensor) with central fringe and two side fringes, faint outer fringes | wave optics |
| diffraction-grating.mp4 + -poster.webp | diffraction-grating.mp4 | "Diffraction grating": grating splits light into its spectrum, sweeping across the armour as camera moves | Poster: low-angle black armour on pale-skinned figure, blue panels, big glossy highlights, faint rainbow streak on one plate | diffraction, metals |
| gauntlet-junkshop.webp | gauntlet-junkshop.webp | "Junk Shop": Blender demo, path traced live in viewport (CC-BY) | Stall with robot and girl in colander hat; wood, rusty metal, emissive pixel-LED panels; dark blue background, warm key; DoF, steam | interior, mixed materials, emission |
| gauntlet-classroom.webp | gauntlet-classroom.webp | "Classroom": warm sunlight through blinds, Blender demo (CC0) | 1920x1080 classroom: wood desks with chrome tube legs, blackboard, cork boards, opal pendant lamps, radiators, sun through blinds at right; visible fireflies | interior, sun GI |
| int-scilab.mp4 + -poster.webp | int-scilab.mp4 | "Live viewport: Science Lab": fly-through, laptop, no offline render | Wide-angle sci-fi lab: white pod, brass/copper pipes, red door, blue striped floor, bench, dome ceiling lights; 8 MB clip | interior, metals, realtime |
| mark.mp4 + -poster.webp | mark.mp4 | "Live viewport: Mark" | Blender UI; stylised man, white shirt, bright window with trees, brick wall; World node editor visible | skin/character, realtime |
| valorcat-vhs.mp4 + -poster.webp | valorcat-vhs.mp4 | "Live viewport: Valor Cat": hero scrubbed live | Blender UI; armoured hero, yellow visor and chest glyph, blue-grey glossy armour | metals, emission, realtime |
| grasshopper.mp4 + -poster.webp | grasshopper.mp4 | "Live viewport: Grasshopper": outdoor, interactive | Blender Pose Mode (yellow bones), blurred tree line, grass, overcast sky | exterior/sky, creature |
| mantis.webp | mantis.webp | "Mantis": macro creature under spectral GI | Front-on green mantis, DoF-blurred leaves, dark pitted ground; dim | creature, DoF |
| sprinkles.webp | sprinkles.webp | "Sprinkles": skin-like scattering, wet specular on a goldfish | Low-angle goldfish close-up, glossy wet lips/eye, pale lavender backdrop, white ceiling strip | SSS, glossy |
| int-bedroom.webp | int-bedroom.webp | "Bedroom": practical lights, glossy floors, spectral GI | Round-bed sci-fi bedroom, curved windows with foggy city, glossy dark floor; very under-exposed | interior, glossy |
| plyp-dancing.mp4 + -poster.webp | plyp-dancing.mp4 | "Plyp Dancing": soft translucent skin | Poster: tiny beige figure on green cutting mat at a desk, lavender wall, lamp, coffee cup, pen pot | SSS, interior |
| int-hallway.webp | int-hallway.webp | "Hallway": coves, sconces, polished metal | Corridor with blue LED cove ceiling, downlights, polished wood/metal panels, glass-ball newel, red sign; heavy DoF blur | interior, emission, metals |

Not images: animated spectrum canvas `#waves`, SVG favicon, Facebook tracking pixel.

## 4. Scenes we should rebuild

Common measurement: render on GPU and CPU at fixed non-zero seed and spp, save PNG for visual inspection, plus the per-scene gate.
Recipes are INFERRED from the images; Spectra publishes no scene files except the Blender demo files.

1. **Double-slit probe.** Monochrome ~650 nm point/collimated source, opaque barrier with two slits (e.g. 20 um wide, 100 um pitch), receiver plane.
   Astroray has no wave optics, so this is a negative control (no fringes expected) and a requirements marker for any diffraction module.
   Measure: fringe period vs lambda*L/d if ever implemented.
2. **Thin-film ladder.** 4 spheres r~1 on a grey floor; Principled: diffuse white, glossy metal, then thin-film at 300/600/900 nm if the
   node supports it; uniform grey world plus one soft area light; camera at sphere height, 35 mm. Measure: hue vs thickness against
   analytic Airy reflectance; low-spp noise; time.
3. **Dispersive crystal.** Step-cut octagonal block and faceted-glass figure on a dark grey floor, glass with Cauchy/Sellmeier dispersion
   (diamond n~2.41), dark room, 2 soft rectangular lights plus a bright panel, low close camera. Measure: spectral spread through a
   prism sub-test (known deviation per wavelength), firefly count, convergence.
4. **Soap bubble + glass.** Thin shell sphere (IOR 1.33, film 300-600 nm) next to a glass block, area-light reflections. Measure: colour vs
   viewing angle, white-furnace energy conservation with the shell.
5. **Classroom (CC0 Blender demo).** Directly reusable (no licence blocker). Sun through blinds, pendant opal lamps, wood and chrome.
   Measure: Astroray vs Cycles ROI parity (floor, blackboard, window), fireflies, time to 1% noise; NEE/ReSTIR-DI stress (several emissive
   pendants plus sun through slats).
6. **Junk Shop (CC-BY demo).** Emissive LED panels, many materials, DoF, steam. Measure: Cycles parity, GPU memory, viewport fps on camera
   orbit; keep CC-BY attribution if published.
7. **Glossy sci-fi interior proxy (hallway/bedroom).** Not public assets, so build a procedural proxy: corridor 3x3x20 m, polished wood floor
   (rough 0.05), emissive blue cove strips plus 6 downlights, chrome sphere, camera mid-corridor. Measure: glossy-floor light reflections,
   noise in dark regions (bedroom is under-exposed, so also check exposure and tonemap).
8. **Skin/SSS close-up (goldfish, Plyp).** Principled SSS head-like mesh with wet clearcoat, white/lavender backdrop, one overhead strip light,
   85-100 mm camera. Measure: SSS energy conservation, highlight shape, Cycles parity.
9. **Live-viewport capture protocol (Science Lab).** A protocol, not a scene: orbit a 150k-300k tri interior at about 1280x1140 on the
   RTX 5070 Ti, log frame time and noise 1 s after the camera stops. Spectra publishes no numbers, so we should publish our own.

## 5. Open questions / not stated on the site

- Engine language: "Rust" appears nowhere; only "native core proprietary".
- RGB-to-spectrum upsampling, bin count, wavelength sampling PDF and hero-wavelength MIS details.
- Fluorescence, volumes, hair, caustics, bidirectional/photon methods, path guiding: not claimed; "realtime ReSTIR caustics" is absent (ReSTIR-WO only).
- What "unbiased" means with ReSTIR plus DLSS-RR/OIDN; whether F12 finals are denoiser-free.
- What wave optics does geometrically in an ordinary scene: beam representation, coherence, when interference applies.
- Cycles node compatibility list, custom nodes, Geometry Nodes, volumes, light linking, AOVs, motion blur, CPU fallback.
- No benchmarks: no fps, spp, resolution or GPU model per clip (only "a laptop"), no Cycles/Astroray comparisons, no wave_tracer or BEMsim3D plots.
- Price, 1.0 release date, beta size, download, docs, changelog beyond 1.0.2; no privacy/terms page.
- ReSTIR-WO "patent pending": no filing number or paper.
- Several stills look unconverged or under-exposed (classroom fireflies, thin-film noise, dark bedroom); spp not stated.
