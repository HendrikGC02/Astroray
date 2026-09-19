# GitHub issue audit — 2026-09-15 (owner request 2026-09-14)

Facts: `issue-audit-facts-2026-09-15-A.md` / `-B.md` (assembled by opencode-go/deepseek-v4-flash
and deepseek-v4.1-flash, grunt tier; the lead spot-checked every close decision against the
spec Status line or the merged PR). Decisions: lead (Claude Fable 5.1). Issue closes/comments
are executed by the owner from the command block at the end (the lead session's permission
mode blocks `gh issue close`).

| issue | decision | evidence / owner | action |
|---|---|---|---|
| #818 | tracked | Batch N lane (in flight, 2026-09-15) | comment: owning lane |
| #817 | tracked | Batch M lane, PR #819 (in flight) | PR closes it |
| #814 | tracked | Batch L lane (in flight) | lane posts |
| #807 | tracked | pkg270 (Batch K lane, in flight) | already noted on the issue |
| #799 | **close** | Phase 1 #808 + Phase 2 #813 landed; direction residual → #814; spectral sky = future item (pkg273 note) | close |
| #795 | open, spec needed | #809: deficit is the env-map reflection lookup, not the conductor lobe | pkg275 (filed today, draft) |
| #789 | tracked | pkg265 follow-up (achromatic walk), no lane | comment: pkg265 |
| #783 | tracked | pkg265 follow-up (thin-film walk) | comment: pkg265 |
| #779 | tracked | Batch O (#779 option b addon-driven leg) in the handoff | comment: Batch O |
| #773 | tracked | root-caused to `principled.cpp` grazing dead-sample discard (pkg264/pkg150) | comment: pkg264 |
| #767 | tracked | Batch O recipe (three distinguishing tests) | comment: Batch O |
| #763 | tracked | Batch O four-way variance table | comment: Batch O |
| #755 | open, spec needed | systematic CPU-vs-GPU env-lookup/spectral gap; pkg237 did not own it | pkg275 (with #795) |
| #741 | **close** | pkg258 done: CPU #747 + GPU wavefront #751 | close |
| #724 | open, spec needed | clip planes ignored (documented degradation) | pkg274 addon gaps (draft) |
| #723 | open, spec needed | missing texture silently dropped, no code | pkg274 |
| #722 | open, spec needed | `scene.cycles.device` mapped `astroray_only` with a recorded semantic mismatch | pkg274 |
| #721 | tracked | Batch M storm row | comment: Batch M |
| #398 | keep (horizon) | pkg177 decision ratified 2026-08-08, no Hydra code | comment: pkg177 |
| #392 | **close (superseded)** | pkg106 DONE 2026-05-29 — the prism rainbow ships via the forward light-tracer path; MNEE Chunk D-radiance/E stayed on `wip/pkg106-chunk-d-radiance` and is not pursued | close |
| #168 | **close (superseded)** | May 2026 CPU/GPU spectral divergence; the current systematic gap is #755 (pkg237 mean-ratio gate) | close, point to #755 |
| #144 | keep (horizon) | pkg270/pkg271 give emission + passes; nebula media = Pillar 4 (paused) | comment: pkg270/271 |
| #143 | **close** | pkg178 native Principled (coat layer over a metallic base) + pkg145 layering energy | close |
| #141 | keep (owner decision) | no code, no spec; Pillar-4-adjacent | comment: needs an owner call |
| #140 | **close** | pkg178 per-λ Belcour–Barla thin-film Fresnel (pkg128 superseded) | close |
| #137 | **close** | pkg38 spectral profiles + `MeasuredSPD`; sensor SRFs = pkg133 (paused) | close |
| #39 | keep (no spec) | animation persistent data absent (pkg52 is viewport-only) | comment: unowned, low priority |
| #38 | keep (no spec) | tile bookkeeping only, no memory-bounded path | comment: unowned |
| #36 | open, spec needed | holdout / indirect-only absent | pkg274 |
| #30 | **close** | pkg225 hair rendering COMPLETE (CPU + GPU curves) | close |
| #29 | **close** | pkg88 motion blur + pkg103b camera motion blur done | close |

Filed today: **pkg274** (addon gaps: #722 device mapping, #723 missing-texture warning, #724 clip
planes, #36 holdout/indirect-only) and **pkg275** (env-map reflection lookup gap: #795 chrome
−23 %, #755 CPU-vs-GPU systematic gap). Both drafted by the grunt tier, lead-reviewed, lint-clean.

## Owner command block (run from the repo; each line is independent)

```bash
gh issue close 741 --comment "Issue audit 2026-09-15: pkg258 is done — CPU environment NEE + fixed continuous CDF sampler in #747, GPU wavefront environment NEE in #751. Residuals tracked in #767 and #755."
gh issue close 799 --comment "Issue audit 2026-09-15: Phase 1 in #808, Phase 2 (engine-side Nishita sky, model-consistent sun disc, absolute IES) in #813. Sun direction + irradiance re-measure continue in #814; the per-wavelength sky is a future item recorded in the pkg273 research note."
gh issue close 392 --comment "Issue audit 2026-09-15: superseded — pkg106 is DONE (2026-05-29): the prism rainbow ships through the forward light-tracer path. MNEE Chunk D-radiance/E remain on wip/pkg106-chunk-d-radiance and are not pursued."
gh issue close 168 --comment "Issue audit 2026-09-15: superseded by #755 — the CPU/GPU HDRI gap is now measured with the pkg237 converged per-channel mean-ratio gate; the May 2026 accumulation-divergence framing is obsolete."
gh issue close 143 --comment "Issue audit 2026-09-15: delivered by pkg178 (native Cycles Principled BSDF incl. the coat layer over a metallic base, PRs #566–#581) and pkg145 (layering energy compensation, #513)."
gh issue close 140 --comment "Issue audit 2026-09-15: delivered by pkg178 Stage 4 — per-wavelength Belcour–Barla thin-film Fresnel (include/astroray/thin_film_fresnel.h), Cycles 5.2 parity-verified; pkg128 superseded."
gh issue close 137 --comment "Issue audit 2026-09-15: delivered by pkg38 (spectral profile database, profiles.bin) + MeasuredSPD in include/astroray/emission_spectrum.h. Sensor spectral response functions are pkg133 (paused with Pillar 4)."
gh issue close 30 --comment "Issue audit 2026-09-15: delivered by pkg225 hair rendering (all six stages: CPU + GPU curve geometry and shading)."
gh issue close 29 --comment "Issue audit 2026-09-15: delivered by pkg88 (object motion blur, phases A/B/C.0: #284 #525 #437) + pkg103b (camera motion blur wiring, #372)."
gh issue comment 795 --body "Issue audit 2026-09-15: owning spec is pkg275 (env-map reflection lookup gap; with #755)."
gh issue comment 755 --body "Issue audit 2026-09-15: owning spec is pkg275 (with #795)."
gh issue comment 722 --body "Issue audit 2026-09-15: owning spec is pkg274 (addon gaps, with #723 #724 #36)."
gh issue comment 723 --body "Issue audit 2026-09-15: owning spec is pkg274 (addon gaps, with #722 #724 #36)."
gh issue comment 724 --body "Issue audit 2026-09-15: owning spec is pkg274 (addon gaps, with #722 #723 #36)."
gh issue comment 36 --body "Issue audit 2026-09-15: owning spec is pkg274 (addon gaps, with #722 #723 #724)."
gh issue comment 789 --body "Issue audit 2026-09-15: pkg265 follow-up; no active lane. Will be batched with #783 when the pkg265 Phase 3 GPU walk resumes."
gh issue comment 783 --body "Issue audit 2026-09-15: pkg265 follow-up; batched with #789 after the Phase 3 GPU walk."
gh issue comment 779 --body "Issue audit 2026-09-15: tracked as Batch O (option b: addon-driven Astroray leg for .blend scenes) in the session handoff."
gh issue comment 773 --body "Issue audit 2026-09-15: root cause is the principled.cpp grazing dead-sample discard (pkg264/pkg150 owner); no lane yet."
gh issue comment 767 --body "Issue audit 2026-09-15: tracked as Batch O (three distinguishing tests, recipe on this issue)."
gh issue comment 763 --body "Issue audit 2026-09-15: tracked as Batch O (four-way variance table)."
gh issue comment 721 --body "Issue audit 2026-09-15: storm row owned by the Batch M lane (PR #819)."
gh issue comment 818 --body "Issue audit 2026-09-15: owned by the Batch N lane (op-VM procedural inputs + coordinate math), in flight."
gh issue comment 398 --body "Issue audit 2026-09-15: long-horizon tracker; the architecture decision is pkg177 (owner-ratified 2026-08-08). No Hydra/USD code exists yet."
gh issue comment 144 --body "Issue audit 2026-09-15: emission + spectral σ land with pkg270, passes with pkg271; nebula-specific media remain Pillar 4 (paused)."
gh issue comment 141 --body "Issue audit 2026-09-15: no code and no spec; needs an owner call on whether a spectral grating BSDF belongs before or inside Pillar 4."
gh issue comment 39 --body "Issue audit 2026-09-15: unowned (pkg52 covers the viewport session only); low priority until animation rendering is a target."
gh issue comment 38 --body "Issue audit 2026-09-15: unowned; only tile bookkeeping exists. Revisit when memory pressure is measured on a real scene."
```

## Addendum — 2026-09-19 (after the session's merges)

Auto-closed by PR #830: #722 #723 #724. Still open although resolved (the PR bodies carried no closing keyword) — run these as well:

```bash
gh issue close 817 --comment "Fixed by #819 (2026-09-19): the viewport worker presents a reduced preview during a real region-view orbit and hands off to full resolution; orbit row added to the §9 driver. The worker default stays opt-in (metal-scene orbit row + 1-spp chroma noise), tracked on #721."
gh issue close 818 --comment "Primary case fixed by #821 (2026-09-19): procedural textures are op-VM inputs on both backends. Residuals: #822 (coordinate-side non-affine math), #823 (coverage scanner blind spot), #826 (multi-input programs on GPU), #825 (texIdx mapping aliasing)."
gh issue close 814 --comment "Sun direction fixed by #824 (2026-09-19): same-.blend addon-path A/B matches Cycles at sun_rotation 0/90/225 within 4 deg; sunlit radiance ratio 0.97/0.96/0.95, sunlit:shadow 2.06 vs 1.87 - the 1.48x number was invalid. IES x spot composition + GPU IES moved to pkg276."
gh issue close 807 --comment "Resolved by #810 + #820 (2026-09-19): per-wavelength extinction and Principled Volume emission - the cabinet's Principled cube shows the emission patch where Cycles does (ROI 0.809/0.801/0.773 vs Cycles 0.826/0.809/0.796). GPU blackbody emission is tracked in #828."
gh issue close 755 --comment "Not reproducible (pkg275, #829): GPU/CPU chrome-under-HDRI ratio [1.0003, 0.9998, 1.0010] at 4096 spp with adaptive sampling off and a shared exposure; texel-exact probes show the lookup and spectral upsample are byte-faithful across backends. The original gap was the pkg237 stopping-metric artefact."
gh issue close 795 --comment "Not a reflection deficit (pkg275, #829): the 0.77 sphere-masked MEAN is dominated by the reflected-sun highlight; the per-pixel median Astroray/Cycles ratio is R 0.96 / G 1.11 / B 1.02 and the luminance ratio map is uniform ~1.0. F82 Fresnel and ground illumination were both ruled out. The residual green skew is a spectral-upsampling effect (see #767)."
gh issue comment 36 --body "Holdout objects landed in #830 (pkg274, CPU path). Indirect-only objects are still open."
gh issue comment 721 --body "Storm row: #831 makes material-only edits take the incremental upload_materials() replay (commit p95 218.6->73.0 ms metal, 117.9->23.4 ms big; full re-syncs 48->2). The remaining ~80 ms tick gap is render/present, and the worker default stays opt-in."
```

New issues filed by lanes this session: #822 #823 #825 #826 #827 #828 #832. New specs: pkg273 (paused), pkg274 (done), pkg275 (done), pkg276 (open).
