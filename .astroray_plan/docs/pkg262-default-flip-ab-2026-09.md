# pkg262 A/B — default-on progressive sampler / light tree / GPU adaptive (2026-09-09)

Hardware: RTX 5070 Ti, `build_cuda` (Ninja, sm_120 embedded, arch-verify +
canary green). The fork (b) numbers in §1.4 were measured against a build
compiled from the on-disk fork (b) sources before that state was committed
(build stamp `sha=67f3c62c…` — the fork (a) commit — `header_hash=5a3a3b20…`
reflects the actual fork (b) file contents on disk at build time, per
`incremental-build-signature-staleness`; re-verified green again after
committing fork (b) as b5273c02, see the PR's build-log/test evidence). All
numbers measured on this machine 2026-09-09; per `gpu-perf-ab-clock-drift`,
frame-time numbers are min-of-3.

---

## 1. Fork decision: progressive sampler + GPU adaptive sampling (issue #759)

### 1.1 What was tried first (fork (a)) and why it was reverted

The spec's stated preference was the ENGINE DEFAULT (`include/raytracer.h`
`useProgressiveSampler = true`, "one behaviour everywhere"). This was
implemented, built, and measured — and it broke two hard gates:

| Gate | Before (flag off) | Fork (a): engine default = true | Ceiling |
|---|---|---|---|
| `tests/wavefront_diff/test_pkg55_perf_gate.py::test_wavefront_contact_sheet_ceiling` (median-of-3, 1024spp 8x8) | 0.570–0.711s (2026-07-25 pin) | **1.629s** | 1.5s |
| `tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py::test_cpu_to_gpu_threshold_gate` (PostInit ULP, CPU PCG32 vs GPU) | ULP ≤ 4 | **2,147,475,505** | 4 |

Six further GPU tests pinned to byte-identical/near-identical default-render
baselines also broke the same way (`test_pkg64_gpu_phase{2,3}_no_regression`,
`test_pkg198_gpu_lightpath_passes::test_gpu_fleet_inert_beauty`,
`test_pkg258_env_nee_gpu_byte_identity`, `test_gpu_caustic_parity`,
`test_pkg189_gpu_wavefront_dispersion::test_gpu_dielectric_rainbow_visual`).
Root cause: making Sobol'+Owen-scramble sampling the ENGINE default means
every GPU render — not just adaptive ones — pays its per-draw cost and
diverges from the CPU's PCG32 reference stream, which is exactly the risk
pkg224's own spec flagged ("GPU-only divergence must be an explicit
decision, not a silent gap" for the CPU/GPU snapshot-parity harness).

**Per the spec's own rule ("a flip that fails its row stays off"), fork (a)
is REVERTED.** `include/raytracer.h` `useProgressiveSampler` stays `false`.

### 1.2 Fork (b) shipped instead (the spec's documented fallback)

`blender_addon/__init__.py` `render()` and `blender_addon/exporter.py`
`sync_viewport_scene()` now call, right after the device is resolved:

```python
renderer.set_use_progressive_sampler(
    active_device == "gpu" and bool(settings.use_adaptive_sampling))
```

The engine-level raw-`Renderer()` default is untouched (byte-identical,
fast PCG32) — every test/script that never touches these two flags keeps
today's exact behaviour. The addon enables the progressive sampler ONLY
when GPU adaptive sampling is actually requested — and since the addon's
own `use_adaptive_sampling` custom property already defaults to `True`
(matching the engine's `useAdaptiveSampling = true` default), this means
adaptive sampling — the feature issue #759 is about — now genuinely
activates by default on real Blender GPU renders, while every raw-engine
test harness (which never goes through `blender_addon`) is unaffected.

### 1.3 Root-cause bug found and fixed independently of the fork choice

`gpu_wavefront_snapshot.cu`'s `adaptiveOn` gate additionally required
`alphaOut == nullptr`. Every real call site (`module/blender_module.cpp`'s
default GPU route, pkg201 Stage 2 Finding F, PR #623 — which PREDATES
pkg131's PR #665 that added this condition) passes
`camera->alphaBuffer.data()` unconditionally (never null). So `adaptiveOn`
was **permanently false regardless of every flag**, on top of #759's addon
plumbing gap. Confirmed empirically before the fix: `adaptive=True` vs
`adaptive=False` with BOTH progressive and adaptive explicitly enabled via
the raw Python binding differed only within the ~3e-7 GPU atomic-noise
floor (i.e., not at all). Fixed to `!renderer.getUseTransparentFilm()`,
mirroring the semantically-identical `coverageOn` check two lines above in
the same function. This fix is independent of the fork (a)/(b) choice and
is required either way for adaptive sampling to ever engage.

### 1.4 Measured evidence for fork (b)

**Frame time** — `benchmarks/viewport_parity/run.py --gpu-only --tris 100000
--frames 60 --no-h3`, min-of-3 runs, camera-only pan/zoom/orbit,
chunk_spp=1, depth=4, 96×96→ actually 512×512 default res:

| Config | frame mean (min-of-3) | frame p99 (min-of-3) | render mean (min-of-3) |
|---|---|---|---|
| OFF (`--adaptive-sampling off --progressive-sampler off`) | 113.03 ms | 122.03 ms | 93.86 ms |
| ON (`--adaptive-sampling on --progressive-sampler on`) | 115.47 ms | 122.94 ms | 96.10 ms |
| Δ | **+2.16%** | **+0.75%** | **+2.39%** |

Ceiling: +5%. **PASS.** (At chunk_spp=1 the adaptive round loop cannot early-stop
within a single-sample chunk — this measures the pure per-launch progressive-
sampler overhead, the realistic viewport-interactivity cost.)

**Noise at equal spp** — in-process GPU render, 96×96, diffuse floor + one
rect area light (real soft-shadow noise source), max_depth=4, RMSE against a
4096-spp (adaptive/progressive off) reference, same seed:

| spp | ON time | ON RMSE vs ref | OFF time | OFF RMSE vs ref | RMSE ratio (OFF/ON) |
|---|---|---|---|---|---|
| 128 | 0.020 s | 0.0013037 | 0.020 s | 0.0036555 | **2.80×** |
| 256 | 0.045 s | 0.0008208 | 0.038 s | 0.0025461 | **3.10×** |

Noise: **equal-or-better — strictly better (~3×) at matched spp.** PASS.
(The 256-spp wall-time gap, 0.045s vs 0.038s, is dominated by launch/JIT
overhead at this tiny scale — see the pkg81 bench above for the
representative, larger-scene cost.)

**Parity suites** — full `pytest tests/ -m gpu` after the fork (b) + alphaOut
fix: **766 passed, 26 skipped, 10 xfailed, 1 xpassed, 0 failed** (was 758
passed / 9 failed under fork (a)). The 9 previously-broken tests individually
re-run: 27 passed, 1 pre-existing xfail (`test_gpu_prism_rainbow_parity`,
unrelated). `tests/test_pkg262_gpu_adaptive_effect.py` (the #759 red/green
gate): 2 passed. `tests/test_pkg131_adaptive_gpu.py` +
`tests/test_pkg224_progressive_sobol_gpu.py` + `tests/test_pkg86_B_gpu_parity.py`:
12 passed.

**Verdict: SHIP fork (b).** Row passes on every axis (frame time, noise,
parity). Fork (a) stays reverted, documented above for provenance.

---

## 2. Light tree default (`custom_raytracer.light_sampler`: `'power'` → `'light_tree'`)

This only affects the **non-Cycles-scene fallback** in
`native_settings.resolve_light_sampler` — any real Blender scene reads the
native `cycles.use_light_tree` bool as authoritative, which this package does
not touch. The blast radius is unit-test stubs / non-Cycles callers only.

Evidence (established by pkg86-B, PRs #434/#436/#438, re-verified green here
post-fix — **not re-derived**, per the Non-goal "do not change the sampler or
light-tree algorithms; defaults and wiring only"):

| Gate | Result | Note |
|---|---|---|
| Single-light non-regression (GPU) | 100 dB PSNR tree vs power | zero visible cost for the common few-light case |
| GPU↔CPU pick parity (10k queries) | ≥99.5% identical, pdf rel-err <1e-4 | re-verified green here: `test_pkg86_B_gpu_parity.py::test_pick_parity_10k_queries` PASSED |
| GPU tree upload cost (10k lights) | 0.09–0.5 ms (≤10ms gate) | re-verified green here: `test_tree_upload_cost_10k_lights` PASSED |
| 64-light variance reduction | 1.11–1.14× (CPU/GPU) vs 2.0× target | pre-existing `xfail(strict=False)`, Phase-1 scene-structure limitation, NOT this package's scope |
| SAOH two-cluster routing | >95% both backends | re-verified green here: `test_saoh_split_routes_to_near_cluster` PASSED |

**Verdict: SHIP.** No regression identified on any measured axis; a net
improvement (or PSNR-identical) in every case pkg86-B measured. Cycles
scenes are unaffected since the native bool is authoritative.

---

## 3. Degradation report correctness (pkg200 rule)

`blender_addon/__init__.py::_gpu_adaptive_ignored_reason` now mirrors the
wavefront's real `adaptiveOn` gate (`!passesOn && !cryptoOn &&
!getUseTransparentFilm()`) and reports through `DegradationReport.ignore(...)`
whenever GPU adaptive sampling is requested but one of those three conditions
would make the wavefront ignore it. No performance/quality tradeoff; pure
honesty fix. `blender_addon/settings_map.py`'s `use_adaptive_sampling` /
`adaptive_threshold` / `light_sampling` rows were also corrected — they were
stale (`DROPPED-SILENT`/"not plumbed") even though pkg131 had already wired
`renderer.set_adaptive_sampling`.

---

## 4. #763 (Astroray/Cycles equal-spp RMSE ratio, pkg259 corpus) — tracked, no gate

Not re-measured in this pass. The pkg259 reference corpus
(`benchmarks/reference_corpus/scenes/{materials_hall,textures_mapping}.blend`)
has committed Cycles-CPU and Astroray-CPU references but no Astroray-GPU
leg yet; producing one requires a full headless-Blender render pass through
the addon exporter, which is out of proportion for a criterion the owner
explicitly marked "no gate" (2026-09-08). Left for a follow-up pass; the
corpus and Cycles references already exist and do not need to be re-rendered
per the owner's #763 note ("do not re-render Cycles if references exist").

---

## Summary — what shipped vs what stayed off

| Change | Shipped? | Where |
|---|---|---|
| GPU adaptive sampling actually engages (alphaOut bug) | **Yes** | `src/gpu/wavefront/gpu_wavefront_snapshot.cu` |
| Progressive sampler auto-enabled when GPU adaptive requested (fork b) | **Yes** | `blender_addon/__init__.py`, `blender_addon/exporter.py` |
| Progressive sampler as the ENGINE default (fork a) | **No — reverted** | measured regression, §1.1 |
| Light tree as the addon fallback default | **Yes** | `blender_addon/__init__.py` |
| Degradation report flags ignored-adaptive cases | **Yes** | `blender_addon/__init__.py`, `blender_addon/settings_map.py` |
| #763 Astroray/Cycles GPU corpus RMSE ratio | **Deferred** | tracked, no gate (owner 2026-09-08) |
