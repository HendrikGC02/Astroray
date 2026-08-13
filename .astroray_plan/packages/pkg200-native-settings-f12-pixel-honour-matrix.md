# pkg200 — Native-settings F12 pixel-honour matrix: prove each adopted Blender/Cycles control actually changes the render

**Pillar:** Integration Milestone (Blender/DCC integration — verification layer)
**Track:** A (addon-heavy Python driver + real-host Blender 5.1/5.2 legs; render legs RTX)
**Status:** open (filed 2026-08-14). Deferred from pkg176 Stage 4 closeout ("deep per-setting F12 pixel-honour matrix — a later addon HW session"); NEXT_STAGE_REPORT §2 item 5.
**Estimated effort:** L, staged (Stage 0 harness + honour-surface enumeration; Stages 1–4 batched render legs; each stage is a 1-session pickup).
**Depends on:** pkg176 (native-settings plumbing — the surface under test; `blender_addon/settings_map.py`, `native_settings.py`, `__init__.py::convert_scene`, `ADOPTED_NATIVE_PANELS`), pkg175 (`scripts/dev_addon.ps1 -Smoke` dev loop — the headless real-host mechanism). Cross-links: **pkg119-B** (differential Cycles-parity harness — orthogonal: pkg119 asks "does it match Cycles numerically"; this package asks "does the setting change the pixel at all, in the promised direction"), **pkg180** (systemic dim, the absolute-parity axis this package deliberately does NOT chase).

## Goal

pkg176 retired the custom UI: native Blender/Cycles panels are now the only steering wheel. Stage 1–4 verified that the exporter *reads* the 14 direct-mapped native props (unit tests + register/headless smoke). What was NEVER verified: that each adopted setting **honours its promise at F12 render time, pixel-level, on real hardware** — that `max_bounces 0` vs `8` actually changes indirect energy, that `sample_clamp_indirect` actually clips fireflies, that `film_exposure 2.0` actually doubles linear pixel energy. A setting the exporter reads but the engine ignores is a silent lie in the steering wheel.

**This package tests HONOUR, not PARITY.** Honour = the setting produces its promised *directional/quantitative* effect at F12 (monotone energy response, firefly clip, linear exposure scale). Absolute numeric agreement with Cycles is pkg119-B / pkg180's job and is explicitly out of scope — that keeps this package tractable and orthogonal. A row that changes the pixel in the right direction PASSES here even if it disagrees with Cycles by the known ~3× light-energy factor (pkg89/pkg180).

**Scope of the honour surface** (enumerated from `settings_map.py`, not prose — see Stage 0): the `direct` render/sampling/light-path/film/denoise rows actually plumbed to a `renderer.*` setter or `render()` arg at F12. Confirmed plumbed in current code:

- Sampling/render: `samples` (render spp), `preview_samples` (viewport), `seed` (`set_seed`; **seed 0 = engine random sentinel**, pin nonzero), `pixel_filter_type`+`filter_width` (`set_pixel_filter`), `resolution_x/y`.
- Light paths: `max_bounces`, `diffuse_bounces`, `glossy_bounces`, `transmission_bounces`, `volume_bounces`, `transparent_max_bounces`, `sample_clamp_direct`/`sample_clamp_indirect` (`set_clamp_*`), `blur_glossy` (`set_filter_glossy`), `caustics_reflective`/`caustics_refractive`, `world_max_bounces` (`set_world_max_bounces`).
- Film: `film_exposure` (`set_film_exposure`), `film_transparent` (`set_use_transparent_film`), `film_transparent_glass` (`set_transparent_glass`).
- Denoise: `use_denoising` (`render_denoise_pass`), `denoiser` backend + `use_preview_denoising` (approximated).

**Explicitly out of the honour matrix** (documented, not tested here): the Principled BSDF socket rows (pkg119-B owns the socket-level matrix); the `dropped` rows (adaptive sampling, fast GI, camera clip/type/bokeh, per-light specular) — those have no engine target and are covered by a separate honesty leg (below) that only checks they *warn*; the `approximated` native `use_light_tree` which is NOT honoured natively today (`convert_scene` reads the custom `light_sampler`, not the native prop) — record as a known gap, do not test as honoured.

## Specification (staged)

**Stage 0 — honour-surface enumeration + A/B render driver (blocking, no HW):**
- Enumerate the honour surface *programmatically* from `settings_map.py` (`by_status("direct")` filtered to rows whose `neutral_param` is a real setter/`render()` arg, plus the plumbed `approximated` denoise rows). The matrix must be generated from the contract so it cannot silently drift from what pkg176 actually plumbed — hard-fail if a `direct` row has no test row assigned.
- Build ONE reusable A/B driver (extend an existing render harness per CLAUDE.md §5b — check `scripts/README.md` first; do NOT fork a sixth contact-sheet script): given a `.blend`, a native-prop override pair (A, B), and a metric, it runs two headless F12 renders through the `dev_addon.ps1 -Smoke` real-host path, writes **LINEAR EXRs** (`apply_gamma=False` — memory `gamma-furnace-cannot-detect-energy-gain`), and emits per-channel mean / max / variance + the pass/fail sentinel. Gate on the printed sentinel, not the Blender exit code (pkg175 rule).
- All MC comparisons use **per-channel mean-ratio** with a tolerance band, never SSIM (memory `ssim-wrong-gate-for-independent-rng`). Pin nonzero seeds on every leg.
- Verify: driver runs on real Blender 5.1 AND 5.2, produces a LINEAR EXR pair + metric JSON for one smoke row (e.g. `film_exposure`).

**Stage 1 — Batch A: light-path depth energy monotonicity (automatable):**
`max_bounces`, `diffuse_bounces`, `glossy_bounces`, `transmission_bounces`, `transparent_max_bounces`, `world_max_bounces`. A/B = low depth (0 or 1) vs high (8–12). Assertion: closed-box indirect-energy mean is **strictly monotone** in the depth (high > low, LINEAR). Scenes: Cornell-style closed box (diffuse/glossy — smooth-shaded per memory `cycles-caustics-need-smooth-shading` where glossy interreflection matters); a glass slab (transmission); a stacked alpha-transparent quad tower (transparent_max); HDRI-lit box (world_max_bounces). `volume_bounces` is a KNOWN-PARTIAL honest-failure candidate (volume transport only partly implemented — settings_map note) — test it, and if it does not respond, file a finding, do not fix here.

**Stage 2 — Batch B: clamps + filter-glossy firefly clipping (automatable):**
`sample_clamp_direct`, `sample_clamp_indirect`, `blur_glossy`. Scene: small bright emitter + glossy floor (firefly generator). A/B = clamp off (0) vs a small clamp. Assertion: per-channel **max** pixel value drops to ≈ the clamp bound and high-percentile variance falls, while low-energy regions are unchanged (LINEAR, seed-pinned). `blur_glossy`: sharp glossy highlight A/B (0 vs 1) — highlight max drops / spatial spread rises.

**Stage 3 — Batch C: film + sampling + seed (automatable):**
`film_exposure` (linear: exposure 2.0 → per-channel mean-ratio ≈ 2.0 within band — the cleanest quantitative honour test), `film_transparent`/`film_transparent_glass` (background alpha 0 vs opaque; glass-alpha behaviour), `samples` (mean stable, variance falls ~1/√N across a 4×-apart spp pair — memory `mc-noise-vs-deterministic`), `preview_samples` (viewport spp responds), `seed` (two DISTINCT nonzero seeds → different noise, equal mean within MC band; and a repeated fixed nonzero seed → reproducible within the 1e-5 GPU atomic floor, memory `ci_has_no_gpu_runtime_blindspot`).

**Stage 4 — Batch D: caustics + pixel filter + denoise (metric + visual inspection):**
`caustics_reflective`/`caustics_refractive` (caustic scene, smooth-shaded caster per memory — on vs off changes caustic-region energy; visual confirm the caustic appears/vanishes), `pixel_filter_type` (BOX vs GAUSSIAN vs BLACKMAN_HARRIS — edge-gradient sharpness differs) + `filter_width` (wider → softer edges), `use_denoising` (post-denoise variance collapses; **visual inspection** the output is not garbage), `denoiser` backend (optix vs oidn both yield a denoised frame) + `use_preview_denoising`. Mark denoise-quality and caustic-appearance rows as **needs-visual** (multimodal `Read` on the PNG), the rest automatable-metric.

**Degradation-honesty leg (folds into Stage 0 harness, cheap, automatable):**
For a sample of `dropped` controls (camera `type`/`clip_end`/bokeh, per-light `specular_factor`), set them off-default and assert `report_unsupported_native_controls` emits the consolidated WARNING naming them — closes pkg176's "zero silently-ignored controls on adopted panels" acceptance. This is a warning-presence check, not a render leg.

**Design rule:** the driver stays a bpy-facing verification harness — it must not reach below the pybind session boundary (Route-2 discipline, pkg176). No new engine/kernel code in this package.

## Acceptance

- [ ] Honour surface is ENUMERATED from `settings_map.py` at test time; every `direct`-plumbed row maps to exactly one matrix row (hard-fail on an unassigned row) — the matrix cannot drift from the pkg176 contract.
- [ ] Every automatable row (Batches A–C, filter/denoise-variance in D, degradation-honesty leg) has a green LINEAR, seed-pinned, per-channel-mean-ratio assertion, run on real Blender 5.1 AND 5.2 via the `dev_addon.ps1 -Smoke` path with the sentinel gated (not exit code), on RTX hardware. `.pyd` mtime stated next to every render leg (memory `stale_pyd_locations`).
- [ ] Every needs-visual row (caustic appear/vanish, denoise-not-garbage) has a multimodal `Read` inspection recorded with a verdict.
- [ ] A checked-in results table: per row → {A/B override, scene, metric, measured A/B numbers, PASS / HONEST-FAIL, automatable|visual}. HONEST-FAIL rows (e.g. `volume_bounces` if non-responsive, `use_light_tree` native gap) are enumerated as **follow-up findings with a proposed spec stub**, NOT fixed inside this package.
- [ ] `scripts/README.md` updated with the new A/B honour driver (or the extended existing harness) in the same PR (CLAUDE.md §5b).

## Non-goals

- **No settings plumbing and no UI changes.** This is verification + bug-filing only. If a row is not honoured, it becomes a follow-up finding — no silent fixes inside this package (owner directive).
- **No absolute Cycles parity.** Directional/quantitative honour only; numeric agreement with Cycles is pkg119-B / pkg180. The known ~3× light-energy divergence does NOT fail an honour row.
- **No Principled-socket matrix** (pkg119-B owns it), **no engine/kernel feature work** (a `dropped` control that needs new capability is a follow-up per pkg176's non-goal), **no denoiser-quality benchmarking** beyond "variance drops and the frame is not garbage".

## Provenance

Filed by the architect 2026-08-14 from the pkg176 Stage 4 deferral (NEXT_STAGE_REPORT §2 item 5). Grounded in the current addon code (`blender_addon/settings_map.py` MAPPING, `native_settings.py`, `__init__.py::convert_scene` F12 setter block ~L1804–1916, `ADOPTED_NATIVE_PANELS` ~L5824), not report prose. Splits the honour axis (this package) cleanly from the parity axis (pkg119-B/pkg180).
