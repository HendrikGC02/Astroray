# pkg201 — GPU wavefront settings-honour: flip the pkg200 HONEST-FAIL rows to PASS

**Pillar:** Integration Milestone (Blender/DCC integration — the steering wheel must actually steer)
**Track:** A (engine/kernel work on the GPU wavefront + a small addon-side exporter fix; gated on real Blender 5.1/5.2 F12 renders on RTX)
**Status:** Stage 1 done (PR pending, 2026-08-14 — `world_max_bounces` HONEST-FAIL→PASS ratio 5.24 on 5.1/5.2; `use_light_tree` KNOWN-GAP→NEEDS-VISUAL-confirmed honoured; also fixed a latent set_light_sampler crash). Stages 2 and 3 open. Direct follow-up to pkg200 (PR #616): closes the GPU-plumbing gaps that pkg200's honour matrix recorded as HONEST-FAIL.
**Estimated effort:** L, staged by risk (Stage 1 = S addon-only; Stage 2 = M GPU host/splat plumbing; Stage 3 = probe-first, register-hostile, may-park).
**Depends on:** pkg200 (`.astroray_plan/docs/pkg200-honour-matrix-results.md` — the findings this package closes, referenced by letter; `scripts/verify_pkg200_honour_matrix_run.py` — the verbatim re-run gate). pkg176 (native-settings plumbing; `blender_addon/settings_map.py`, `__init__.py::convert_scene`). pkg55 wavefront (`module/blender_module.cpp` GPU dispatch, `src/gpu/wavefront/gpu_wavefront_snapshot.cu::cuda_wavefront_render`).

**Ordering (hard):** the Stage 3 per-ray-state work touches the SAME wavefront serialization / shade-kernel register budget as **pkg199 Stage 2 (Step 2b register gate)** and the **pkg198 Stage 2 probe**. Do NOT start Stage 3 until BOTH of those land/settle — three packages contending for the REG-254-pinned shade kernel simultaneously will produce non-attributable register spills. Stages 1 and 2 are independent of that contention and may proceed anytime.

## Goal

pkg200 proved the GPU wavefront F12 path honours only `maxDepth`, seed, `filmExposure`, the pkg157 clamps, and the pkg197 denoise pass — and **silently drops the rest of the plumbed steering-wheel controls**. Every dropped control is a lie in the steering wheel: the exporter reads the native prop, the setter stores it, and `src/gpu/` never looks at it. This package closes the specific gaps pkg200 enumerated (findings A–F + the `use_light_tree` known-gap), one honour-matrix row at a time.

**This package flips rows, it does not add settings.** Success for every item = the corresponding pkg200 row flips **HONEST-FAIL → PASS** when the pkg200 driver is re-run *verbatim*. The matrix is the gate; that is the entire reason pkg200 built it. No new honour surface, no parity chasing (pkg119-B/pkg180 own absolute Cycles agreement — a row that moves the pixel in the promised direction PASSES here even at the known ~3× light-energy factor).

## Confirmed root causes (verified against code 2026-08-14, not just quoted from the findings doc)

- **A** — `module/blender_module.cpp:1863` calls `cuda_wavefront_render(..., maxDepth, ...)`; the five per-type bounce args (`diffuseBounces/glossyBounces/transmissionBounces/volumeBounces/transparentBounces`) are passed to the CPU `renderer.render(...)` at L1906 but **never to the GPU call**. `cuda_wavefront_render`'s signature (`gpu_wavefront_snapshot.cu:1294`) has no per-type-bounce params at all.
- **B** — `blender_addon/__init__.py:4773` reads `world.light_settings.max_bounces`; `light_settings` is the AO datablock and has **no** `max_bounces` member, so `getattr(..., 1024)` always wins and the control is inert. The real Cycles prop is `world.cycles.max_bounces`.
- **C** — `filterGlossy` stored (`include/raytracer.h:2123`, setter :2259); **zero references in `src/gpu/`**.
- **D** — `pixelFilterType`/`pixelFilterWidth` stored (`include/raytracer.h:2132-2133`, setter :2291); **zero references in `src/gpu/`** (the wavefront does no reconstruction filtering at splat).
- **E** — `useReflectiveCaustics`/`useRefractiveCaustics` stored (`include/raytracer.h:2124-2125`, setters :2260-2261); **never read in `src/gpu/`**. GPU photon caustics gate on a *separate* `usePhotonCaustics` opt-in (pkg113); the native toggles are unwired.
- **F** — no `transparentFilm`/background-alpha handling anywhere in `src/gpu/`; the GPU alpha buffer stays opaque (background alpha 1.0).
- **use_light_tree** — `blender_addon/settings_map.py:101` maps `scene.cycles.use_light_tree` to the custom `light_sampler` tri-state (`renderer.set_light_sampler`); the exporter reads the tri-state, never the native bool. Toggling the native prop changes nothing (a semantic mismatch, not a kernel gap).

## Specification (staged by risk)

### Stage 1 — cheap exporter-side fixes (addon-only, NO kernel, NO GPU register cost)

Closes **B** and the **use_light_tree** known-gap. Pure Python, in `blender_addon/`.

1. **Finding B:** change the world-bounce read path in `__init__.py::convert_scene` (~L4772-4775) to read `world.cycles.max_bounces` (the real Cycles world prop), keeping a `getattr` default for worlds without a cycles block. One-line-ish fix; do NOT touch the AO `light_settings` read used elsewhere.
2. **use_light_tree:** reconcile the tri-state-vs-bool mismatch in `settings_map.py`/`convert_scene` so toggling the native `scene.cycles.use_light_tree` actually reaches `renderer.set_light_sampler` (native `True` → light-tree sampler, `False` → the uniform/other sampler; preserve the custom tri-state's third state if it still has a distinct meaning, else collapse to the native bool per the pkg176 Stage-1 rule). Decide the mapping explicitly in the PR body — do not silently pick.

**Stage 1 acceptance:** the pkg200 `world_max_bounces` row (currently `1.0971 = 1.0971`) flips to PASS (strictly-monotone energy vs depth) re-running the driver verbatim; the `use_light_tree` known-gap row now shows a pixel change when the native prop toggles. Both are addon-only — no `.pyd` rebuild required beyond a register/liveness smoke.

**Stage 1 DONE (2026-08-14, `.astroray_plan/docs/pkg201-stage1-results.md`).** `world_max_bounces`: HONEST-FAIL→**PASS** (A(0)=0.209 → B(12)=1.097, ratio 5.24, 5.1≡5.2) — Finding B fixed (`world.cycles.max_bounces`); the pkg200 driver's Row override (which encoded the AO-datablock bug) was repointed in-place to the corrected attr. `use_light_tree`: KNOWN-GAP→**NEEDS-VISUAL, confirmed honoured** (|dLum| mean 0.028/0.037; both A/B valid lit frames differing in sampler noise) — promoted from `KNOWN_GAPS` to a real matrix row (`many_lights` Emission-emitter scene). Also fixed a **latent crash** the reconciliation exposed: `set_light_sampler` accepts only `'power'`/`'tree'` but the UI enum shipped `'uniform'`/`'light_tree'`; `resolve_light_sampler` now translates to a valid engine token (uniform→power; engine has no uniform sampler). Two changes beyond the spec's literal Stage-1 text, both justified in the PR: (1) the pkg200 driver correction is required because the Row encoded the very bug Finding B fixes; (2) the enum→token translation is required or the fix crashes on Blender's default scene.

### Stage 2 — GPU plumbing, LOW register risk (host/splat/pre-pass, not the shade kernel's per-ray live state)

Closes **D**, **E**, **F**. These do NOT add per-ray live state to the REG-254-pinned shade kernel, so they are not blocked by the pkg198/pkg199 register contention.

3. **Finding F (transparent film):** honour `transparentFilm` background alpha on the wavefront path — write background-miss alpha 0 (and the `transparent_glass` behaviour) into the GPU alpha buffer / copy-back, mirroring the CPU path. Touches the miss/background write and copy-back, not the shade closure.
4. **Finding E (caustic toggles):** map the native `useReflectiveCaustics`/`useRefractiveCaustics` onto the GPU photon-caustic pre-pass gate (pkg113). Host-side wiring in `blender_module.cpp` / `cuda_renderer.cu` — when a native toggle is off, suppress the corresponding photon-caustic contribution; when on, run the existing pre-pass. No new kernel. (Clarify in the PR the relationship to the separate `usePhotonCaustics` opt-in — the native toggles should not silently force the whole pkg113 pre-pass on if it was globally disabled; scope to "gate what the pre-pass already does".)
5. **Finding D (pixel reconstruction filter):** apply `pixelFilterType`/`pixelFilterWidth` in the wavefront splat/accumulate (the film-write stage), not the shade kernel. BOX/GAUSSIAN/BLACKMAN_HARRIS weight at accumulate time. This is a film-stage change; register-neutral for shade.

**Stage 2 acceptance:** pkg200 rows `film_transparent`, `film_transparent_glass`, `caustics_reflective`, `caustics_refractive`, `pixel_filter_type`, `filter_width` each flip HONEST-FAIL → PASS/NEEDS-VISUAL→PASS re-running the driver verbatim (caustic + film-transparent-glass rows are the visual ones — record a multimodal `Read` verdict). Non-caustic GPU renders show no perf regression (min-of-N burn-in, memory `gpu-perf-ab-clock-drift`).

### Stage 3 — per-ray bounce counters + filter-glossy, REGISTER-HOSTILE (probe-first, may-park per item)

Closes **A** and **C**. Both add per-ray live state that the REG-254-saturated shade kernel must carry — this is the register-budget-hostile half and MUST clear an up-front probe before any feature code, exactly like the pkg198 Stage 2 / pkg199 Step 2b discipline.

6. **MANDATORY FIRST STEP — register probe before building (per item):**
   - **A (per-type bounce counters):** threading `diffuse/glossy/transmission/volume/transparent` depth limits requires per-ray *per-type depth counters* in the wavefront path state, read+compared in the shade kernel's continuation logic. Carry the counters as SoA global-memory path state (like the existing depth/throughput fields), so the shade kernel holds the comparison, not a widened live struct. Isolate any shade-kernel-reaching branch behind a compile-time axis (pkg184/pkg189 if-constexpr) so the fleet default specialization stays byte-identical.
   - **C (filter_glossy):** Cycles' filter-glossy widens a bounce's sampled roughness based on the *prior* bounce's roughness — a per-ray "roughness carried so far" accumulator, also shade-kernel live state.
   - **HARD gate:** the pass-less / feature-off specialization of `stageShadeBucketedKernel` stays at the verified fleet baseline **REG 254 / STACK 3352 / CONSTANT[0] 1700**, confirmed on the FINAL linked `.pyd` via `cuobjdump` (sm_120 via `--list-elf` first; never `ptxas -v`). Memories `wavefront-shade-kernels-register-saturated`, `closure-graph-lobe-count-spills-fused-kernel`, `worktree-cmake-cuda-arch-stale-cache`.
   - **If even the SoA-global form spills the feature-off specialization or regresses non-feature perf: STOP and park THAT item with the cuobjdump evidence.** A clean park is a valid outcome (pkg194/pkg198 discipline). Per-type bounces and filter-glossy are evaluated independently — one may land while the other parks.
7. **Only if the probe clears (per item):** thread the per-type bounce limits into `cuda_wavefront_render` (extend the signature — sweep every call site: `blender_module.cpp:1863`, `cuda_wavefront_render_restir`, any test harness) and the wavefront continuation logic; and/or apply filter-glossy roughness widening in the shade stage. `volume_bounces` is additionally KNOWN-PARTIAL (volume transport itself is incomplete — pkg199); wire the counter, and if it still doesn't respond because of the transport gap, record that as expected and cross-ref pkg199, do not chase volume transport here.

**Stage 3 acceptance (per item that clears the probe):** the corresponding pkg200 rows flip HONEST-FAIL → PASS — `diffuse_bounces`, `glossy_bounces`, `transmission_bounces`, `transparent_max_bounces` (strictly-monotone indirect energy vs per-type depth), and `blur_glossy` (glossy-highlight max drops / spread rises) — re-running the driver verbatim. `volume_bounces` flips to PASS only if pkg199 volume transport is present; else remains an enumerated cross-ref. Any parked item ships a one-paragraph park note + cuobjdump evidence instead of a flip.

## Acceptance (whole package)

- [ ] Every item's gate is the **verbatim** re-run of `scripts/verify_pkg200_honour_matrix_run.py` on real Blender 5.1 AND 5.2, RTX 5070 Ti, LINEAR EXRs (`apply_gamma=False`), per-channel mean-ratio (never SSIM), nonzero pinned seeds, sentinel-gated (not Blender exit code). The pkg200 results table row moves from HONEST-FAIL to PASS. `.pyd` mtime stated next to every render leg (memory `stale_pyd_locations`; rebuild if older than HEAD).
- [ ] Stage 3 items each show the up-front cuobjdump register probe (feature-off specialization at REG 254 / STACK 3352 / CONSTANT[0] 1700 on the FINAL linked `.pyd`) BEFORE feature code; a parked item ships the evidence, not a flip.
- [ ] Call-site sweep recorded for any changed signature (`cuda_wavefront_render` especially) — every caller, test, and mock updated (memory `cpu-only-carveout-misses-gpu-headers`, CLAUDE.md pre-push rule).
- [ ] Visual rows (`caustics_*`, `film_transparent_glass`) have a multimodal `Read` verdict recorded.
- [ ] An updated copy of the pkg200 results table (or a pkg201 delta table) checked in showing the before/after verdict per closed row.

## Non-goals (hard)

- **No new settings.** Only the rows pkg200 recorded as HONEST-FAIL / native-gap. Nothing beyond flipping found rows.
- **No parity chasing.** Absolute Cycles numeric agreement is pkg119-B/pkg180's job (the ~3× light-energy factor stays). Honour = promised directional/quantitative effect only.
- **No shade-kernel live-state widening or lobe-array shrink to buy registers** (pkg178/pkg184). If it doesn't fit as SoA-global behind an if-constexpr axis, it parks.
- **No volume transport work** (pkg199 owns it) — `volume_bounces` wires the counter only.
- **No heterogeneous concerns.** Findings G (denoiser-backend selector) and I (`sample_clamp_indirect` inconclusive) from pkg200 are NOT in scope — G is a verification question, I is almost-certainly-honoured; both are separate follow-ups if the owner wants them.
- **No forking the pkg200 driver** — re-run it verbatim; extend only if a new scene is genuinely needed and register it in `scripts/README.md` (CLAUDE.md §5b).
