# pkg202 — Legacy sun GPU zero-contribution fix: upload-time conversion to the dedicated distant light

**Pillar:** Integration Milestone (Blender/DCC integration — imported `.blend` files must render the same light on GPU as CPU)
**Track:** A (GPU scene-upload host code; gated on a real RTX render A/B, not CI green)
**Status:** done (PR #TBD, 2026-08-14 — legacy sun renders on GPU: finite-angle GPU/CPU parity ratio 1.000, delta sun GPU 0.6333 == analytic ρ·S/π 0.6366 and == CPU dedicated delta 0.6345; .blend-importer sun non-black on GPU; no-CDF-theft linearity ratio 1.000; dedicated control unchanged 1.000; RTX 5070 Ti, sm_120, .pyd @ HEAD).
**Estimated effort:** S–M. One upload-time conversion in `src/gpu/scene_upload.cu`, plus three self-contained tests. No new device/kernel code.
**Depends on:** pkg89-GPU (the dedicated distant-light device path this reuses — `src/gpu/scene_upload.cu:897-938`, `gpu_nee.cuh` `gpu_dedicated_sample`, `astroray::DistantLight` in `include/astroray/lights/distant_light.h`). Independent of the pkg198/199/201 wavefront-register work — this is upload-side host code and touches no shade-kernel live state.

## Goal

The **legacy** `add_sun_light` API contributes **exactly zero** on GPU. Fix it by converting the legacy `DistantLight` hittable to the already-verified pkg89 dedicated distant-light representation **at scene-upload time**, so every legacy caller — most importantly the `.blend` importer — renders the sun on GPU, byte-identically to CPU. No new device sampler; reuse the dedicated path pkg89 already proved.

## Evidence base (diagnosis session, verified on RTX 5070 Ti, fresh `.pyd` at HEAD 9d6eb98, sm_120, GPU lock held; each code citation re-verified against live code 2026-08-14)

- **Legacy `add_sun_light` contributes EXACTLY ZERO on GPU** (not "dimmer" — the pkg194-review "residual" was scene background). A/B repro: gray Lambertian floor, straight-down sun, black background, linear (`apply_gamma=False`):
  - CPU mean ≈ **0.632–0.640** — matches the analytic `albedo·S/π = 0.5·(4)/π = 0.6366` for the repro's intensity.
  - GPU mean **0.0 / 0.0 / 0.0** at BOTH 64 and 512 SPP.
  - Dedicated-sun control (the pkg89 dedicated API) ≈ **1.00 on GPU and CPU**, both SPP — the dedicated path is correct; only the legacy path is dark.
- **Root cause (two coupled failures):**
  1. The legacy sun is a **hittable** `DistantLight` (`include/raytracer.h:774`), created by `Renderer::addSunLight` → `renderer.addObject(sun)` (`module/blender_module.cpp:710-717`). On upload, `scene_upload.cu:361-364` maps any non-Sphere/non-Triangle prim to **`GPRIM_SKIP`** (`gp.index = -1`). The sun is still gathered as a hittable **emitter** — it keeps a full-power `GLight` entry in the unified light CDF — but when NEE selects it, `gpu_nee.cuh:424-427` hits `if (primIdx < 0) return s;` / `if (lp.type == GPRIM_SKIP) return s;` and returns an **invalid (empty) sample**. Net: zero contribution AND the wasted selection probability adds variance to every *other* light (the CDF slot is dead but still consumes selection mass).
  2. The sun is **not in the GPU BVH**, and the wavefront miss/background shader (`src/gpu/wavefront/stage_advance.cu:307` — the env-map miss branch) evaluates only env/background plus the dedicated lamps. So there is no BSDF-hit path to the sun either.
- **Impact scope:** the Blender addon is UNAFFECTED (it uses the dedicated lamp API). The failure hits the **`.blend` importer**, which emits legacy suns at `tools/blend_import/scene_builder.py:915` (`ctx.renderer.add_sun_light(fwd, 0.0, mat_id, 0, 0)`) → **imported `.blend` files lose all sun light on GPU**. Pre-existing since pkg85-C (GPRIM_SKIP placeholder); never a regression.

## Prescribed fix (coordinator decision — implement this; alternatives recorded as rejected below)

**Upload-time conversion:** in scene upload, detect the legacy `DistantLight` hittable and emit it as a **dedicated** `GDedicatedLight` (the pkg89 distant kind) instead of a hittable `GLight` + `GPRIM_SKIP` pair.

Why this is the right call:
- **Units are EXACT — the conversion is lossless.** The diagnosis established that the legacy `DistantLight` delivers irradiance = its material intensity via the `1/Ω` falloff, and the dedicated `astroray::DistantLight` treats its `intensity` argument as irradiance `S` directly (constructor `include/astroray/lights/distant_light.h:22-25`). No radiometric fudge factor; the CPU A/B already lands on the analytic `S/π` answer. **The implementer must re-derive and record this equivalence in the PR** (show the two intensity→irradiance paths produce the same `S` for the repro scene) before trusting it — do not take it on faith from this spec.
- **Reuses the pkg89-GPU dedicated path verbatim** (`scene_upload.cu:897-938` dedicated-light upload; `gpu_dedicated_sample` in `gpu_nee.cuh`; `DeviceLightParams`/`fillDeviceParams`). **No new device code, no new sampler, no kernel touch, no register cost.**
- **Fixes ALL legacy callers at once**, including the `.blend` importer — because the conversion is at the upload boundary, not at any one call site.

### Rejected alternatives (record in the PR)
- **A new `GPRIM_DISTANT` device sampler** — adds device code and a new sampler path for zero benefit over the existing dedicated distant kind; more surface, more register/verification risk.
- **Importer migration to the dedicated API + deprecating the legacy GPU path** — leaves *other* legacy `add_sun_light` callers dark, and churns the importer for a problem that belongs at the upload boundary.

## Specification

Work is confined to `src/gpu/scene_upload.cu` (host upload) plus tests. Do NOT touch any `.cu` kernel, `gpu_nee.cuh`, or CPU render code.

1. **Detect the legacy sun at upload.** Where hittable emitters are gathered into `r.lights`/the unified CDF, identify the legacy `DistantLight` (`include/raytracer.h:774`) — e.g. via `dynamic_cast` on the hittable, mirroring however sphere/triangle emitters are already discriminated in this file. Extract its direction, angular diameter, and material intensity/emission.
2. **Emit it as a dedicated distant light instead.** Construct the equivalent `GDedicatedLight` (distant kind) using the same `DeviceLightParams` fields the pkg89 block populates (`scene_upload.cu:912-936`), with the intensity mapped per the verified units equivalence. Push it into `r.dedicatedLights` so `gpu_dedicated_sample` handles it.
3. **REMOVE the legacy sun's hittable `GLight`/CDF entry.** The converted sun must NOT also occupy a hittable `GLight` slot with a `GPRIM_SKIP` prim — that is the dead CDF slot that wastes selection probability and adds variance to every other light. Either skip creating the hittable emitter entry for a converted sun, or excise it before the CDF is built, so the final unified CDF contains the sun **once**, as a dedicated light, with correct cumulative power. This is an explicit acceptance item, not incidental.
4. **CPU behavior stays byte-identical.** The conversion is GPU-upload-side ONLY. The CPU render path (which handles the legacy hittable `DistantLight` correctly today) must be untouched — no change to `raytracer.h`, `light_sampler.cpp`, or the CPU integrator. Verify a legacy-sun CPU render is bit-for-bit unchanged pre/post.

## Acceptance gates

All GPU legs: RTX 5070 Ti, `.pyd` mtime stated next to each render and rebuilt if older than HEAD (memory `stale_pyd_locations`), sm_120 confirmed via `cuobjdump --list-elf` (memory `worktree-cmake-cuda-arch-stale-cache`), linear EXR/`apply_gamma=False` (memory `gamma-furnace-cannot-detect-energy-gain`), nonzero pinned seed (memory `seed-zero-is-random-sentinel`), per-channel **mean-ratio** never SSIM (memory `ssim-wrong-gate-for-independent-rng`).

- [ ] **Legacy-sun parity test (permanent, self-contained in `tests/`).** Port the diagnosis session's `scratchpad/legacy_sun_ab.py` pattern into a self-contained test: gray Lambertian floor, straight-down legacy `add_sun_light`, black background. Assert **GPU/CPU per-channel mean-ratio ≈ 1.0** (MC convention) for the legacy-sun scene at a modest SPP, and assert GPU mean is **non-zero and matches the analytic `albedo·S/π`** (upper AND lower bound — a furnace/analytic bracket, per memory `gamma-furnace-cannot-detect-energy-gain`). The test must build its own scene via the public bindings — no dependency on the scratchpad script.
- [ ] **`.blend`-importer-path test.** A `.blend` (or the importer code path `tools/blend_import/scene_builder.py:913-916`) with a SUN lamp imports and **renders non-black on GPU** (mean above a black-frame threshold). This is the real-world regression the fix exists for.
- [ ] **Dedicated-sun control unchanged.** The pkg89 dedicated-sun scene still renders ≈ 1.00 on GPU/CPU (no regression from the upload changes) — assert its mean is within tolerance of the pre-change baseline.
- [ ] **No dead-CDF-entry / variance check.** Assert the final GPU light-selection CDF **excludes** the converted legacy sun as a hittable entry (it appears once, as a dedicated light). Demonstrate via the upload-side light counts (hittable-emitter count does not include the converted sun; dedicated count does) and/or a variance check that a legacy-sun-plus-second-light scene shows no excess variance on the second light vs the equivalent dedicated-sun scene at matched SPP.
- [ ] **CPU byte-identical.** A legacy-sun CPU render is bit-for-bit identical pre/post the change.
- [ ] **Call-site sweep.** If any upload-side signature changes, grep the repo for every caller/test/mock and update them (CLAUDE.md pre-push rule; memory `cpu-only-carveout-misses-gpu-headers` — check CUDA-reachable `.h` too). CI green alone is insufficient — the RTX A/B is the gate (memory `ci_has_no_gpu_runtime_blindspot`).
- [ ] **PR records the units derivation.** The lossless intensity→irradiance equivalence (legacy `1/Ω` falloff vs dedicated `S`) is re-derived and shown, not asserted from this spec.

## Non-goals (hard)

- **No new device code / no new sampler / no kernel touch.** The whole point is reusing the pkg89 dedicated path. If the fix seems to need a new `GPRIM_DISTANT` sampler, stop — that is the rejected alternative.
- **No CPU render-path changes.** CPU already handles the legacy hittable sun correctly; keep it byte-identical.
- **No importer rewrite.** Do not migrate `scene_builder.py` off `add_sun_light` — the fix lives at the upload boundary so all legacy callers benefit. (Touching the importer only to add the test scene is fine.)
- **No parity chasing / new light features.** Absolute Cycles agreement and light-tree behaviour are other packages. This closes a zero-contribution hole; success is "GPU matches CPU for the legacy sun," nothing more.
- **No angular-disk / soft-shadow scope creep.** The repro uses a delta-ish sun; match whatever the dedicated distant path already does for angular diameter — do not extend it here.
