# pkg184 — `template<bool HasPhotons>` isolation of the photon-caustic KNN gather in the bucketed shade kernel

**Pillar:** 5 (GPU performance)
**Track:** A (register-pressure work; requires cuobjdump + perf gates)
**Status:** done (PR #597, 2026-08-12 — every HasPhotons=false shade variant strictly below baseline: STACK −256/−256/−128/−128 B across `<F,F>/<F,T>/<T,F>/<T,T>`; all HasPhotons=true variants byte-identical to baseline; REG:254 unchanged; non-photon glass-sphere shade kernel −2.76% wall vs +0.50% byte-identical control; base = current main e6b9f24 incl. pkg187 dispersion)
**Estimated effort:** M
**Depends on:** pkg157 `template<bool Deferred>` and pkg178 Stage-3b
`template<bool HasPrincipled>` — this is the third application of the same
isolation lever in `src/gpu/wavefront/stage_advance.cu`.

## Problem

`src/gpu/wavefront/stage_advance.cu` inlines the photon-map caustic KNN
gather (`photonGridGatherKnn(photonGrid, rec.point, 50, 1.1f, found)`) into
the shade half that `stageShadeBucketedKernel` compiles — behind a **runtime**
guard (`bounce == 0 && hasPhotonGrid && …`). ptxas must therefore allocate
registers/stack for the 50-neighbour gather's live set in every instantiation
of the REG:254-pinned shade kernel, for a feature that (a) only ever fires at
bounce 0 and (b) is inactive in the large majority of scenes.

## Why it's plausible-value

The identical pattern paid off twice in this file: pkg178 Stage-3b's
`HasPrincipled` isolation recovered a +52% regression on non-Principled
scenes. The shade kernel is register-saturated (see
`wavefront-shade-kernels-register-saturated` memory / pkg174 ledger), so any
live-state reduction either lowers spills or buys headroom for future lobes.

## Work

1. Add `template<bool HasPhotons>` (composing with the existing
   `<bool Deferred, bool HasPrincipled>`) with `if constexpr` around the
   gather; dispatch on `hasPhotonGrid` at launch.
2. Measure per-variant REG/STACK via `cuobjdump` post-link (NOT `ptxas -v`)
   and wall-clock on the standard gate scenes (min-of-N with GPU burn-in per
   `gpu-perf-ab-clock-drift` memory), photon and non-photon scenes.
3. Gates: photon-caustic parity tests unchanged
   (`tests/test_pkg55_c5_photon_wavefront.py`, `tests/test_gpu_caustic_parity.py`);
   no regression on non-photon scenes; cubin variant count doubles — confirm
   compile time stays acceptable.

Note: instantiation count doubles (2→4 kernel variants per templated axis
product). If compile time or cubin size becomes a concern, gate the
`HasPhotons=true` variants behind the same launch-side selection the
Principled split uses.

---

## Hardware verification 2026-08-12 (PR #597, independent verifier pass)

**Hardware:** RTX 5070 Ti (sm_120 / Blackwell), Windows 11 Enterprise
10.0.26200, NVIDIA driver 610.47 (CUDA UMD 13.3), CUDA Toolkit 12.8.61
(nvcc), OptiX SDK 9.1.0 (as configured; not exercised by this GPU-wavefront
gate). Build: MSVC 19.44.35207 (VS2022 BuildTools), VS-generator
`build_cuda` (root wrapper, `-DASTRORAY_CUDA_ARCHS=120
-DCMAKE_CUDA_ARCHITECTURES=120`).

**Arch discipline:** the PR worktree (`e14efed58...`) and an independent
merge-base baseline (`e6b9f24`, checked out fresh into a dedicated baseline
worktree) were both rebuilt from scratch via `build_cuda_worktree.bat`.
pkg183's post-link `cuobjdump --list-elf` gate confirmed `sm_120` (not a
stale/shadowed arch) on both `.pyd`s before any number below was trusted.

**Contamination guard:** worktree HEAD verified against the PR's
`headRefOid` (`e14efed580114341052fd798058d6ff15706153e`) before building.
**Anomaly (not caused by this session):** an untracked, pre-existing stray
file `stage_advance.cu` (containing pkg184's diff content) was found sitting
at the **main repo root** (`Astroray/stage_advance.cu`, mtime predating this
session). It is not referenced by `CMakeLists.txt` (which points at the real
`src/gpu/wavefront/stage_advance.cu`) so it did not contaminate any build in
this session, but it is worktree-contamination residue from some other
agent/process and should be cleaned up by whoever owns that checkout.

### Gate table (measured vs claimed)

| # | Gate | Claimed | Measured | Verdict |
|---|------|---------|----------|---------|
| 1 | cuobjdump post-link resource matrix, all 8 `stageShadeBucketedKernel<HasPrincipled,HasTexture,HasPhotons>` instantiations (native sm_120, `cuobjdump --dump-resource-usage`) vs an independently-rebuilt merge-base (`e6b9f24`) baseline | `<F,F,false>` 3608→3352 (−256); `<F,F,true>` 3608→3608 (byte-identical); `<F,T,false>` 3608→3352 (−256); `<F,T,true>` 3608→3608; `<T,F,false>` 6616→6488 (−128); `<T,F,true>` 6616→6616; `<T,T,false>` 6616→6488 (−128); `<T,T,true>` 6616→6616; REG:254 everywhere | Independently-rebuilt baseline (fresh worktree at `e6b9f24`): `<F,F>`=STACK 3608, `<F,T>`=3608, `<T,F>`=6616 (CONSTANT[2]:368), `<T,T>`=6616 (CONSTANT[2]:368) — matches the claimed baseline table exactly. PR tree measured: `<F,F,false>`=3352, `<F,F,true>`=3608, `<F,T,false>`=3352, `<F,T,true>`=3608, `<T,F,false>`=6488, `<T,F,true>`=6616, `<T,T,false>`=6488, `<T,T,true>`=6616. **All 8 deltas match the claimed table exactly**; REG:254 on every one of the 8 instantiations. | **PASS** |
| 2 | Perf A/B, glass-sphere caustic scene, wavefront route, 256 spp, min-of-7 with GPU burn-in, `wavefront_stage_shade_bucketed_n7` `sum_ms` (`ASTRORAY_PROFILE`) | Photons OFF: 93.623 ms → 91.039 ms (−2.76%). Photons ON (noise-floor control): 1045.40 ms → 1050.62 ms (+0.50%) | Photons OFF: baseline median 93.107 ms (min 92.985 ms, n=7) → pkg184 median 90.933 ms (min 90.863 ms, n=7) = **−2.34%** (median) / **−2.28%** (min-of-min). Photons ON: baseline median 985.579 ms (min 980.329 ms) → pkg184 median 986.539 ms (min 981.131 ms) = **+0.10%** (median) / **+0.08%** (min-of-min). Both directions confirmed: non-photon variant faster, photon-ON variant flat within noise (smaller than the PR's own reported control band). Launch count 572/render on both sides, both builds — matches the PR's methodology description. | **PASS** |
| 3 | Photon-caustic parity — `tests/test_gpu_caustic_parity.py` + `tests/test_pkg55_c5_photon_wavefront.py`, plus mandatory visual inspection | "2 passed, 1 xpassed (pre-existing prism xfail, unrelated)" | `2 passed, 1 xpassed in 2.39s` — exact match. `test_gpu_glass_sphere_caustic_parity`: caustic-ROI energy GPU=45.0501 CPU=41.1944 ratio=1.094x, SSIM=0.9606, GPU peak luminance=0.406. Visual: `pkg113_gpu_glass_sphere.png` / `pkg113_cpu_glass_sphere.png` both show a coherent, focused warm-toned caustic blob at the expected floor location with sparse MC noise pixels around it — no fireflies, no magenta/black NaN patches, no banding, no mode regression (still monochrome-warm, not spectral/rainbow). The HasPhotons=true gather path is visibly still firing correctly. `test_gpu_prism_rainbow_parity` XPASS (documented out-of-scope xfail; render is scattered noise as expected, unrelated to this PR). `test_wavefront_photons_off_identity` PASSED. | **PASS** |
| 4 | Broad regression slice (implementer claims 49 pass: photon emission/store, pkg157 firefly, pkg159 crypto, pkg178 principled+thinfilm parity, pkg186 texture parity, pkg187 dispersion) | "49 passed" | Ran a superset covering every named area plus additional pkg178 sub-suites (alpha, aniso, GPU/CPU parity, furnace, stage5 native routing, thin-film parity) and pkg186's features guard: **85 passed, 0 failed** (15.42s) — includes `test_gpu_photon_emission.py` (3), `test_gpu_photon_store.py` (4), `test_pkg157_wavefront_firefly_clamp_port.py` (7), `test_pkg159_wavefront_cryptomatte.py` (4), `test_pkg178_alpha.py` (11), `test_pkg178_aniso.py` (9), `test_pkg178_principled_gpu_cpu_parity.py`, `test_pkg178_principled_gpu_furnace.py`, `test_pkg178_stage5_native_routing.py`, `test_pkg178_thinfilm_gpu_cpu_parity.py` (all GPU/CPU ratio bands 0.95–1.05, all within), `test_pkg186_gpu_features_guard.py` (7), `test_pkg186_gpu_texture_parity.py` (2), `test_pkg187_addon_dispersion_probe.py` (3), `test_pkg187_principled_dispersion.py` (4), `test_pkg187_principled_dispersion_gpu_parity.py` (2). Zero failures. | **PASS (exceeds claim)** |

**Overall verdict: mergeable on HW evidence.** All 4 gates PASS, independently
re-measured (not just re-run against the PR's self-reported numbers) — the
cuobjdump matrix was cross-checked against a from-scratch baseline rebuild at
the exact claimed merge-base `e6b9f24`, and the perf A/B used a genuinely
separate baseline `.pyd` rather than trusting the PR body's own numbers. No
gate was relaxed; nothing needed escalation. The Blender-addon layer was not
touched by this change (`launchStageShadeBucketed` signature unchanged) and
was out of scope for this verification.

**Anomaly log:** the stray root-level `stage_advance.cu` noted above under
"Contamination guard" — advisory only, did not affect this session's build
correctness (confirmed via `CMakeLists.txt` source-list grep), but should be
triaged/deleted by its owner to avoid a future false-positive diff or stale
include.
