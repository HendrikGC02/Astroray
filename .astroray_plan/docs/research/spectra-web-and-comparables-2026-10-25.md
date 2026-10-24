# Spectra Render: web coverage beyond site/thread, plus comparables (2026-10-25)

Method: WebSearch (standard + extended, ~14 queries) and WebFetch. Results are secondary summaries by a small model; treat as unverified where marked. Site and Blender Artists thread are covered by other agents and not repeated.

## 1. Headline finding: Spectra has almost no independent web footprint

Nothing found outside the vendor's own pages. No YouTube video, Reddit thread, X/Mastodon/Bluesky post, BlenderNation article, Superhive/Gumroad listing, GitHub repo, Discord invite or press piece could be located by any query ("Spectra Render", "Valor Cat Studios", "Ben Reicher Spectra", "double slit", beta + platform names). Absence in a search index is weak evidence (US-only index, fresh pages indexed thinly). INFERRED: very early closed beta (site says "Join the beta"), no public marketing push yet.

| Channel | Result | Source |
|---|---|---|
| spectra-render.com | Only outbound link is blender.org demo files; no GitHub/YouTube/Discord/X/Reddit/store; beta buttons have no URL | https://spectra-render.com/ |
| YouTube (studio channel) | Linked from studio site; fetch returned only page chrome, so videos/views unknown; not Spectra-specific | https://www.youtube.com/c/valorcatstudiosinc |
| Reddit / X / Bluesky / Mastodon | No hits | (search) |
| BlenderNation / CGChannel / press | No hits | (search) |
| Superhive / Gumroad / Extensions | No Spectra listing ("Spectre Quick Suite" is an unrelated product) | https://superhivemarket.com/products/spectre-quick-suite |
| GitHub | No repo. Site states addon shell is GPL-3.0, native core proprietary | https://spectra-render.com/ |
| LinkedIn | Search snippet: a post about 54 days old announces beta (promotional; post not fetched; person profile URL 404'd) | https://www.valorcatstudios.com/ |

Facts from the studio page (vendor-authored) https://www.valorcatstudios.com/ : "realtime wave optics addon for Blender"; spectral, polarized, unbiased; viewport on any ray-tracing GPU; zip into stock Blender (addon, not fork); reads Principled-based materials, lights, cameras, colour management; (c) 2026; trademark Spectra Render; no release date. Per a search summary of the same page: four wavelengths and full polarization state per path, interference/diffraction "computed per beam". The ReSTIR/Rust/Vulkan claims did not appear on the studio page or in any result I reached (they come from the covered site/thread). Wave optics + polarization is a stronger claim than "spectral + ReSTIR caustics".

## 2. Developer (public info only)

- Vendor: Valor Cat Studios, inc., animation studio (Los Angeles / Glendale / West Hollywood; sources disagree), makers of the series Valor Cat and CG film Feline Paradox. https://www.valorcatstudios.com/ , https://www.bark.com/en/us/company/valor-cat-studios/lpXpN/
- Person: Ben Reicher, Founder and CEO; studio owner since July 2018; Head of CG at Mulholland; taught a Blender course at Bento Box (search snippets of https://www.linkedin.com/in/ben-reicher-439b6b57/ and https://voyagela.com/interview/meet-ben-reicher-valor-cat-studios-glendale/ ; not fully fetched). IMDb: https://www.imdb.com/name/nm6005405/ . Contact listed on studio page: ben@valorcatstudios.com.
- INFERRED: a CG-animation professional; no public prior renderer, papers or talks found. Product page names no individual, only the studio.
- Licence model (site): perpetual, 1 year updates, one licence per machine, free headless nodes for indie, per-node for studios, licensing gates installs/updates not renders; price not listed. https://spectra-render.com/

## 3. Comparables (2026 state as found)

| Engine | Spectral? | ReSTIR / caustics tech | Realtime viewport? | Blender integration | Licence / price | Source |
|---|---|---|---|---|---|---|
| Spectra Render | Claimed: 4 wavelengths/path + polarization | Claimed ReSTIR caustics (not independently seen) | Claimed, any RT GPU | Addon zip, stock Blender | Proprietary core, GPL shell; perpetual + 1 yr; price unlisted; closed beta | https://spectra-render.com/ , https://www.valorcatstudios.com/ |
| Cycles (5.2 LTS, Jul 2026) | No (RGB); only 2022 refactor groundwork; dispersion listed as open topic Apr 2026 | ReSTIR draft PR #164970 in Oct 2026 meeting, viewport-oriented debate; older #121023 on hold; path guiding CPU only (OpenPGL, now ASWF); HIP shadow caustics need HW RT | Yes (not realtime quality) | Native | GPL, free | https://developer.blender.org/docs/release_notes/5.2/cycles/ , https://devtalk.blender.org/t/2026-10-13-render-cycles-meeting/45974 , https://projects.blender.org/blender/blender/pulls/121023 , https://devtalk.blender.org/t/2025-02-04-render-cycles-meeting/38862 |
| LuxCoreRender 2.10 (May 2025) | No: RGB plus dispersion trick when glass dispersion>0 | Photon/bidir caustic handling; no ReSTIR found | Limited | BlendLuxCore; Blender 4.x claimed | Apache-2.0, free | https://en.wikipedia.org/wiki/LuxCoreRender , https://github.com/luxcorerender/blendluxcore |
| OctaneRender 2026.4 | Not confirmed in results (INFERRED: verify) | Neural Radiance Cache (2026.4); no ReSTIR seen | Yes | OctaneBlender addon 2026.3 for Blender 5.1.x | Commercial subscription; price not found | https://render.otoy.com/forum/viewtopic.php?p=443775 , https://render.otoy.com/forum/viewtopic.php?p=443729 , https://docs.otoy.com/blender/OCTANE_BLENDER.html |
| Indigo | Spectral (long-standing; not re-verified 2026) | Unbiased bidir/MLT | No | Indigo for Blender bundled; Blendigo manual old | Commercial, ~GBP 525-630 reseller | https://indigorenderer.com/blender/ , https://www.cadsoftwaredirect.com/renderers/indigo-renderer.html |
| Maxwell | Spectral by reputation (INFERRED, unverified) | n/a | No | B-Maxwell exporter only, old | Commercial; price not found | https://forum.maxwellrender.com/viewtopic.php?p=392361 |
| Mitsuba 3 | Yes: spectral/RGB/mono and polarized variants | Research integrators; no ReSTIR in default list | No | Integration plugin page, appears dated | BSD, free | https://github.com/mitsuba-renderer/mitsuba3 , https://mitsuba-renderer.org/plugins.html , https://blender-addons.org/mitsuba/ |
| Radeon ProRender | "Full Spectrum" Vulkan mode, viewport only, beta 2019 | not seen | Yes | Official AMD addon | Free | https://radeon-pro.github.io/RadeonProRenderDocs/en/plugins/blender/full_spectrum_rendering.html , https://www.cgchannel.com/2019/12/radeon-prorender-for-blender-gets-full-spectrum-rendering/ |
| blRstr | Not stated | ReSTIR via NVIDIA RTXDI, up to 15 indirect bounces, ReLAX; no SSS/volume/hair | Yes | Blender 3.1+; core exe + open addon | Commercial core, addon to open (no ETA); public beta; undated | https://stkrake.net/blRstr/ |
| Ignis RT | Not stated | Vulkan ray-query path tracer, DLSS Ray Reconstruction; no ReSTIR evidence | Yes | Addon, Blender 5.0+, RTX only | GPL-3.0; 12 stars, 1 open issue | https://github.com/kalexis1994/ignis-rt |
| Astroray (us) | Spectral | ReSTIR DI (CPU integrator; GPU CUDA wavefront) | Yes (GPU) | Addon, Blender 5.2 | Open | https://github.com/HendrikGC02/Astroray |
| Malt, pbrt-v4 exporters | Not researched; no results reached | - | - | - | - | - |

Cycles notes: no spectral or ReSTIR line in 5.2 Cycles release notes. A community thread on spectral Cycles exists https://devtalk.blender.org/t/thoughts-on-making-cycles-into-a-spectral-renderer/2192 ; snippets there say ReSTIR+SVGF is "almost always slower" at equal quality and that Cycles is "not cut out for caustics" (search snippet, page not verified).

## 4. Images

No demo renders or screenshots found outside the two covered sources (the site's `assets/gallery/double-slit.webp` belongs to the site agent). Evidence dir `C:\Users\hgcom\AppData\Local\astroray-evidence\2026-10-24\spectra\web\` was created and is empty.

## 5. Positioning read (INFERRED)

- Spectra's verifiable surface is one landing page plus a studio page; all technical claims are vendor-only and unbenchmarked. Treat "ReSTIR caustics" as unproven.
- Distinct angle: wave optics and polarization; Mitsuba 3 is the only comparable with polarization, and it is not realtime.
- Closed core + GPL shell + per-machine perpetual licence contrasts with Astroray's open licence; blRstr is the nearest precedent.
- Cycles ReSTIR is active (Oct 2026) but viewport-scoped and unmerged, and spectral Cycles has no landed work; spectral + ReSTIR in Blender remains an open niche.

## 6. Follow-ups

1. View the YouTube Videos tab and the LinkedIn beta post in a real browser (WebFetch got only chrome / 404).
2. Re-search in 2-4 weeks; a launch typically produces BlenderNation/Reddit hits.
3. Verify Octane/Maxwell/Indigo spectral status from vendor docs before publishing the table.
