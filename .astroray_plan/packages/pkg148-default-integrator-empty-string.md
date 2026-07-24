# pkg148 — `integratorName_` default-constructs empty: GPU dedicated-light scenes silently render black

**Pillar:** 3 (light transport plumbing / API footgun)
**Track:** A
**Codex-paste-ready:** no (small, but the fix choice is a convention decision + needs an RTX-verified render gate)
**Status:** done (PR #516, 2026-07-24 — Option A: `integratorName_` defaults to
`"path_tracer"` at construction and at both reset sites (`clear()`,
`set_integrator("auto"|"default"|"")`); binding-level `get_integrator()`
added; GPU dedicated-light non-black gate measured locally on RTX 5070 Ti
(gpu_mean > 0.05, CPU/GPU ratio in [0.9, 1.1]) — official `/verify` RTX sweep
still pending per protocol, this was opportunistic since the dev box has a
CUDA build)
**Estimated effort:** S
**Depends on:** none

**Origin:** HW-verifier finding during PR #515 verification. **Pre-existing behavior,
not a regression.** Same class as the silent-black-render bugs in the
`gr-emission-model-wiring-checklist` memory: green CI, black render, only the HW
visual gate catches it.

---

## Repro (measured)

1. Fresh `Renderer` + GPU device + a dedicated light (e.g. AREA lamp) + `render()`
   **without** calling `set_integrator` → **solid black**.
2. Same scene with an explicit `set_integrator("path_tracer")` → correct render.
3. The CPU path has no such gate at default construction, so **CPU and GPU disagree
   on a default-constructed renderer** — the worst kind of parity trap for test authors.

## Mechanism (anchors on `main`)

`module/blender_module.cpp:361` — `std::string integratorName_;` default-constructs
**empty**. The render dispatch gates named-integrator behavior on
`!integratorName_.empty()` (`blender_module.cpp:2177/2190/2200`), and the GPU
dedicated-light NEE wiring only engages inside the named-integrator branches
(`:1745-1766` — e.g. `enableNEE = (integratorName_ == "path_tracer")`). Empty name →
legacy fallback path → dedicated lights never sampled on GPU → black.

## Fix direction (pick per existing engine conventions; note both in the PR)

- **Option A — default to `"path_tracer"` at construction.** Matches CPU behavior and
  the principle of least surprise; `set_integrator` remains the override. Check the
  `clear()`/reset sites (`:2233`, `:2499`) — they must reset to the default, not to
  empty, or the footgun returns after a scene reset.
- **Option B — fail loudly on empty** (throw/assert when `render()` runs with no
  integrator set on GPU). Safer if the empty-name legacy path is load-bearing for
  some caller; grep for deliberate empty-name uses before choosing A.

Decide by call-site sweep: if nothing depends on the empty-name legacy branch,
prefer A (and consider deleting the branch as a follow-up note, not in this package).

## Acceptance gate

- GPU dedicated-light scene renders **non-black at default construction** (per-channel
  mean well above black floor), RTX-verified; CPU==GPU on the same default-constructed
  scene within the usual parity band.
- A binding-level test pinning the default (`get_integrator`/capabilities reflect
  `path_tracer`, or the loud-failure behavior if Option B) so the default cannot
  silently regress to empty.
- Existing integrator-selection tests (`test_integrator_capabilities.py` etc.)
  unchanged.

## Non-goals

- No integrator behavior changes — this is purely the default/failure-mode plumbing.

## Hardware verification 2026-07-24

**Hardware:** RTX 5070 Ti · Windows 11 Enterprise 10.0.26200 · CUDA 12.8 (nvcc; 12.6 also present) · OptiX 9.1.0 · OIDN 2.4.1
**Worktree:** `Astroray-pkg148` @ `56ebbc91c334df89bc87cbc24c2c7051c46fb3d5` (PR #516)
**Build:** clean rebuild via `configure_and_build.bat` (VS 2022 generator, Release config) after MSVC bootstrap via `vcvars64.bat` — `build_cuda_worktree.bat` was not used because its `cmake --build build_cuda --target astroray` omits `--config Release`, which defaults to Debug on this multi-config generator (see memory `build-cuda-worktree-debug-config`). Build succeeded; `astroray.__file__` confirmed loading from the worktree's own `build_cuda/Release/astroray.cp313-win_amd64.pyd`.
**Smoke-check:** `get_integrator()` binding present, returns `"path_tracer"` on a fresh `Renderer()` — matches spec.

### Pass/fail table

| Gate | Result |
|---|---|
| `tests/test_pkg148_default_integrator.py` (7 tests) | 7 passed in 0.56s |
| ↳ `test_gpu_dedicated_light_nonblack_at_default_construction` | PASSED — gpu_mean=1.1248067617416382, cpu_mean=1.1272635459899902, ratio=0.9978205768676797, all finite |
| `tests/test_pkg89_gpu_dedicated_lights.py` + `tests/test_pkg89_phase_b_dedicated_lights.py` (dedicated-light parity suite) | 6 passed, 1 skipped (IES profile, unrelated) in 1.54s — AREA gpu_mean=1.1254 cpu_mean=1.1277 ratio=0.998 corr8x8=0.971; POINT gpu_mean=0.9479 cpu_mean=0.9509 ratio=0.997 corr8x8=0.983 |
| Integrator selection suite (`test_integrator_capabilities.py`, `test_integrator_plugin.py`, `test_integrator_float_param.py`, `test_blender_auto_integrator.py`, `test_pkg64_phase3_default_integrator.py`, `test_pkg64_gpu_phase3_default_integrator.py`, `test_pkg91_integrator_param_lifecycle.py`) | 23 passed, 1 skipped, 1 xfailed in 6.50s — the xfail (`test_pkg64_gpu_phase3_prism_psnr_floor`) is a pre-existing, documented (2026-06-08) retired legacy gate, unrelated to this change |
| Megakernel GPU smoke (default-constructed `Renderer`, GPU, simple lit-sphere scene, 256×256, 64 spp) | No crash, all pixels finite, mean=0.0040799775160849094 |
| Visual gate (default-constructed `Renderer`, GPU, POINT dedicated light + shadow sphere, 256×256, 256 spp) | Non-black, correctly shaded, no fireflies/NaN/banding — PNG saved |
| Full suite spot-check (`pytest tests/ --ignore=tests/wavefront_diff`) | 7 failed, 1453 passed, 68 skipped, 24 xfailed, 6 xpassed in 331.20s — all 7 failures pre-existing/environmental (SSIM flake + missing `astroray_test_helpers` CMake target in this worktree's build scope), none touch integrator naming/defaulting |

### Visual inspection

Rendered a DEFAULT-constructed `Renderer` (no `set_integrator()` call) on GPU with a POINT dedicated light and a shadow-casting sphere on a ground plane (256×256, 256 spp, seed 7). Image is non-black, shows correctly Lambertian-shaded sphere with smooth illumination gradient; no fireflies, no NaN/magenta pixels, no banding/quantization artifacts. This is the direct visual confirmation of the fix: this exact scenario (default construction, no explicit integrator, GPU) rendered solid black before pkg148. PNG: `test_results/overnight_report_2026-07-23/pkg148_default_gpu_light_after.png`.

### Anomalies / discrepancies worth watching

- The PR body reported "8 failed" in the full-suite run including a `test_kerr_validation.py::FileNotFoundError`. The verifier's run measured **7 failed**, and all 39 tests in `test_kerr_validation.py` passed on this worktree (`scripts/generate_gyoto_references.py` exists and imports fine). This specific failure claim did not reproduce — flagged as a PR-body reporting discrepancy, not a gate concern (fewer failures than claimed, and the discrepant one wasn't integrator-related either way).
- Spot-checked one of the 7 failures (`test_wavefront_photon_caustic_parity`, the SSIM flake) against unmodified `main` (using main's existing build): reproduces byte-for-byte identically (`SSIM=-0.0000 < 0.80, peak WF=1.208 MW=1.591`) — confirmed genuinely pre-existing, unrelated to pkg148.
- The 6 `ModuleNotFoundError: astroray_test_helpers` failures are specific to this worktree's build only having compiled the `astroray` CMake target (not the separate `astroray_test_helpers` target) — main's existing build already has that target compiled, so those 6 do not reproduce there. This is a worktree build-scope artifact, not a main-branch code defect, and is unrelated to pkg148's diff (`module/blender_module.cpp` only).

**Verdict: PASS**, bound to `56ebbc91c334df89bc87cbc24c2c7051c46fb3d5`.
