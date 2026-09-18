# Issue audit facts — 2026-09-15 (set B)

Read-only audit. Evidence gathered with `git log`, `gh pr list`, `gh issue view`,
`git grep` over `.astroray_plan/packages/` and `.astroray_plan/docs/STATUS.md`.
All 15 issues are **OPEN** (verified with `gh issue view <n>`).

## #722 Native Cycles Device (scene.cycles.device) is ignored
- **Merged PRs mentioning it:** none (PR #725 references the range `#721–#724`, not `#722` literally)
- **Specs mentioning it:** `pkg37-blender-addon-backend-refresh` (Status: done); `pkg176-blender-native-steering-wheel` (Status: done (PRs #555/#556/#561/#568, 2026-08-08 - Stages 0-4 COMPLETE))
- **STATUS.md mentions:** `**Bug list started:** issues #721 viewport blocking (P1), #722 native Cycles Device`
- **Code evidence:** `blender_addon/settings_map.py:407: MappingEntry("astroray_only", "device_mode", "scene.cycles.device", "custom_raytracer.device_mode", ...)` and `:409: "SEMANTIC MISMATCH: native scene.cycles.device is CPU/GPU only; Astroray adds an 'auto' ..."`
- **Last issue comment:** no comments

## #721 Viewport: camera events block ~155 ms each; progressive refinement idles at ~1.3 Hz
- **Merged PRs mentioning it:** `#725 chore(fixtures): repair metal_sweep HDRI path, drop placeholder scenes, add KNOWN_ISSUES generator`; `#812 feat(batch-g): pkg266 P2.3 closeout — present-rate root cause, chunk-spp column, section 9 gate table, worker default`
- **Specs mentioning it:** `pkg241-render-cancellation-viewport-response` (Status: done - Triage 2026-09-12 (half-implemented audit, `half-implemented-triage-2026-09-12.md`): Phases 0-2.2 delivered (#733 #739 #748 #750 #768 #777)); `pkg266-viewport-phase2-3-bounded-cancel-and-commit` (Status: done - PR #812 merged 2026-09-13: present-rate=0 root-caused to two bugs (spurious view_update over-cancel; orphaned worker holding the global admis)
- **STATUS.md mentions:** `(UI event latency during a chunk, target p95 <= 33 ms); comment on #721.` and `**Bug list started:** issues #721 viewport blocking (P1), #722 native Cycles Device`
- **Code evidence:** `blender_addon/__init__.py:1256: # live viewport worker to idle, then own the ONE global admission token`; `blender_addon/__init__.py:1260: # finally below on every exit path. With the viewport worker off there are`
- **Last issue comment:** 2026-09-13 | `PR #812 (pkg266 P2.3 closeout) merged 2026-09-13: the present-rate=0 measurement failure had two root causes (spurious view_update re-fires cancelling the in-flight generation; an orphaned worker hold`

## #398 Future/architecture: engine-agnostic core - standalone + USD/Hydra render delegate
- **Merged PRs mentioning it:** `#399 fix(addon): instanced lights + camera frustum parity tests; Blender-integration parity specs (pkg112/114/115/116/117)`
- **Specs mentioning it:** `pkg177-dcc-integration-architecture-eval` (Status: CLOSED - decision document delivered + **owner-RATIFIED 2026-08-08** (`.astroray_plan/docs/dcc-integration-decision-2026-08.md`); parallel-safe, tou)
- **STATUS.md mentions:** none
- **Code evidence:** `git grep -il "hydra|render_delegate|\busd\b" -- include src plugins` `-> none` (no Hydra/USD/render-delegate source; only the pkg177 decision doc)
- **Last issue comment:** no comments

## #392 pkg106: finish the triangulated-prism rainbow (Chunk D-radiance + E)
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg106-sms-on-triangulated-prisms` (Status: DONE (2026-05-29) - prism rainbow ships via the forward)
- **STATUS.md mentions:** none
- **Code evidence:** `plugins/integrators/light_tracer_caustic.cpp`; `include/astroray/manifold/mesh_attempt.h:5: // chain (per-ray hero-wavelength IOR -> per-wavelength bend -> spatial rainbow),`
- **Last issue comment:** no comments

## #168 bug: CPU/GPU spectral accumulation parity divergence
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg55-wavefront-soa-refactor` (Status: done (PR #524, 2026-07-25 - Session C7 landed: both megakernels DELETED, wavefront is the only GPU render path)); `pkg64-gpu-sellmeier-session2-multi-ior` (Status: done (PR #385, 2026-05-28 - SSIM 0.928 >=0.85, energy 1.38x, PSNR +2.19 dB))
- **STATUS.md mentions:** none
- **Code evidence:** `include/astroray/gpu_materials.h:72: // Hero layout must match CPU sampleUniform (src/spectrum.cpp:82): hero spans`
- **Last issue comment:** no comments

## #144 feat(volume): spectral nebula emission and reflection media
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg270-principled-volume-emission-blackbody-spectral` (Status: open); `pkg268-cpu-heterogeneous-volume-transport` (Status: done - PR #810 merged 2026-09-13 (c231f27d): delta tracking + ratio tracking + HG/isotropic phase + Principled Volume basics + volume NEE); `pkg271-volume-passes-corpus-and-blender-integration` (Status: open); `pkg273-cloud-volume-material` (Status: paused - owner: horizon item until the cloud simulation is complete (filed 2026-09-15))
- **STATUS.md mentions:** none
- **Code evidence:** `include/astroray/volume/volume_transport.h:1: // pkg268 — CPU heterogeneous volume transport: delta-tracking free flight +`; `include/astroray/emission.h:6: // Volumetric emission base class for Pillar-4 astrophysical emitters.`
- **Last issue comment:** no comments

## #143 feat(material): coated conductor and car-paint layered material
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg143-disney-clearcoat-energy-recalibration` (Status: SUPERSEDED by pkg145 (2026-07-21, PR #510 ...)); `pkg145-disney-specular-energy-compensation-refit` (Status: done (PR #513 merged 2026-07-23) - diffuse-under-specular Cycles `closure_layering_weight`/OpenPBR coupling added); `pkg194-principled-tinted-layer-spectral-carry-and-thinwall-perlambda` (Status: done (PR #606, 2026-08-13))
- **STATUS.md mentions:** none
- **Code evidence:** `include/astroray/energy_compensation.h:50: static constexpr int kClearcoatSize = 32;`; `:68: float clearcoatE(float mu) const;`
- **Last issue comment:** no comments

## #141 feat(material): diffraction grating / spectral mirror BSDF
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none
- **STATUS.md mentions:** none
- **Code evidence:** `git grep -n -i -E "\bgrating\b|diffraction" -- include src plugins` `-> none`
- **Last issue comment:** no comments

## #140 feat(material): thin-film interference coating
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg128-thin-film-iridescence` (Status: superseded by pkg178 - the per-lambda Belcour-Barla thin-film Fresnel utility this spec designed landed and was Cycles-5.2 parity-verified under pkg178); `pkg178-native-cycles-principled-bsdf` (Status: done (PRs #566-#581, 2026-08-07 - 2026-08-10 - native Cycles-Principled BSDF COMPLETE, Stages 0-5, CPU+GPU byte-mirrored)
- **STATUS.md mentions:** none
- **Code evidence:** `include/astroray/gpu_materials.h:11: #include "thin_film_fresnel.h" // pkg178 Stage 4: shared Belcour-Barla iridescence core`; `include/astroray/gpu_thin_film_table.cuh`
- **Last issue comment:** no comments

## #137 feat(material): measured spectral material curves
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg38-spectral-profiles` (Status: done); `pkg133-srf-spectral-sensors` (Status: paused - Triage 2026-09-12 (half-implemented audit): Pillar-4-adjacent; resumes with pkg51)
- **STATUS.md mentions:** none
- **Code evidence:** `include/astroray/emission_spectrum.h:73: struct MeasuredSPD {`; `:15: // 3. MeasuredSPD { profile_name } — loads from pkg38 spectral-profile database.`; `include/astroray/spectral_profile.h`
- **Last issue comment:** no comments

## #39 feat: Persistent data for animation rendering
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg52-persistent-viewport-session` (Status: done) — viewport session, not animation-frame persistence
- **STATUS.md mentions:** none
- **Code evidence:** `blender_addon/__init__.py:1456: # pkg52: persistent viewport session (pkg116: delegated to Exporter)` (viewport session only; no animation persistent-data path found)
- **Last issue comment:** no comments

## #38 feat: Tiled rendering for memory efficiency
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none
- **STATUS.md mentions:** none
- **Code evidence:** `include/raytracer.h:2404: // cancelled=false and tilesCompleted==totalTiles.`; `include/astroray/integrator.h:30: // frame, before the tile loop). Default impl is a no-op` (tile bookkeeping only, no memory-bounded tiled render path)
- **Last issue comment:** no comments

## #36 feat: Holdout and indirect-only objects
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** none
- **STATUS.md mentions:** none
- **Code evidence:** `git grep -n -i holdout -- include src plugins blender_addon` `-> none`
- **Last issue comment:** no comments

## #30 feat: Hair/curves rendering
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg225-hair-rendering` (Status: COMPLETE - **all six stages landed (CPU + GPU curve geometry, CPU + ...)
- **STATUS.md mentions:** none
- **Code evidence:** `include/astroray/curves.h:2: // pkg225 Stage 1 — CPU ray-curve (swept-circle "thick" cross-section) intersection.`
- **Last issue comment:** no comments

## #29 feat: Motion blur (camera and object transform)
- **Merged PRs mentioning it:** none
- **Specs mentioning it:** `pkg88-motion-blur` (Status: done - Triage 2026-09-12: Phases A/B/C.0 landed (#284, #525, #437); C.1 stays perf); `pkg103b-camera-motion-blur-wiring` (Status: done (PR #372, 2026-05-24 - wired `set_camera_motion_blur` via depsgraph T/R/S decomposition; CENTER shutter window; 3/3 tests green)); `pkg72-motion-vectors` (Status: done)
- **STATUS.md mentions:** none
- **Code evidence:** `blender_addon/__init__.py:2079: if render_settings and getattr(render_settings, 'use_motion_blur', False):`; `:2080: shutter = float(getattr(render_settings, 'motion_blur_shutter', 0.5))`
- **Last issue comment:** no comments

## Summary

| issue | merged PRs | owning spec | last activity |
|-------|------------|-------------|---------------|
| #722 | none (#725 references range #721–#724) | pkg37 (done); pkg176 (done) | PR #725 merged 2026-09-06; no comments |
| #721 | #725, #812 | pkg241 (done); pkg266 (done) | 2026-09-13 comment; PR #812 merged 2026-09-13 |
| #398 | #399 | pkg177 (CLOSED) | PR #399 merged 2026-05-30; no comments |
| #392 | none | pkg106 (DONE) | no comments |
| #168 | none | pkg55 (done); pkg64-gpu-sellmeier-session2-multi-ior (done) | no comments |
| #144 | none | pkg270 (open); pkg268 (done); pkg271 (open); pkg273 (paused) | no comments |
| #143 | none | pkg143 (SUPERSEDED); pkg145 (done); pkg194 (done) | no comments |
| #141 | none | none | no comments |
| #140 | none | pkg128 (superseded); pkg178 (done) | no comments |
| #137 | none | pkg38 (done); pkg133 (paused) | no comments |
| #39 | none | pkg52 (done) | no comments |
| #38 | none | none | no comments |
| #36 | none | none | no comments |
| #30 | none | pkg225 (COMPLETE) | no comments |
| #29 | none | pkg88 (done); pkg103b (done); pkg72 (done) | no comments |
