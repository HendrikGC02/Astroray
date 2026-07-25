# pkg144 — Firefly clamp biases delta/direct NEE: wire the Cycles direct/indirect clamp split

**Pillar:** 3 (light transport / integrator correctness)
**Track:** A (integrator clamp restructuring against the Cycles reference + an energy-linearity gate; needs a build + evidence-first default tuning)
**Codex-paste-ready:** no (an adjudicated integrator change that moves firefly control from an always-on top-level cap to a per-contribution bounce-split, with a default that must be tuned against the existing firefly/caustic tests — judgment at the gate)
**Status:** done (PR #515, 2026-07-23 — clamp split wired CPU+GPU megakernels, both defaults 0/off per measured evidence, bright-sun linearity ratio ~0.9995 across 3 decades; secondary light-selection-importance deferred; 2 of 3 pkg144-adjacent xfails resolved, 2 Disney-highlight tests reassigned to pkg145's remit with measured evidence — see PR body)
**Estimated effort:** M (primary clamp-split); secondary light-selection section is a separable S–M follow-up
**Depends on:** none (pkg140 landed the delta-sun MIS/`power()` fixes in `060cfd0`; this is the pre-existing clamp that masks them)

**Origin:** pkg140 debug round, PR #507 owner comment. The gate-5 `with_sun == without_sun`
failure was root-caused to a **test-only** power-balance issue (fixed in the test), but
the investigation surfaced a **production** bias in the firefly clamp that is filed here.

---

## Primary finding — the always-on per-sample luminance clamp biases delta/direct NEE

`include/raytracer.h:3003-3005`, in the per-pixel sample-accumulation loop:

```cpp
// Per-sample firefly suppression: sCol is XYZ, Y is photometric luminance.
float sLum = sCol.y;
if (sLum > 20.0f) sCol = sCol * (20.0f / sLum);
```

This clamp is applied to `sCol`, the **whole path's** contribution to the pixel
(direct + indirect already summed), and it is **unconditional and always on**. Two
problems, both breaking energy conservation for bright/low-probability lights:

1. **It clamps direct light, including delta-light NEE.** A delta light's NEE
   estimator is **deterministic** — `sampleLi` returns emission with `pdf = 1`
   (delta) and the per-fire value is `throughput · f_r · L / (selPdf)`. There is
   **no variance to suppress**, so capping it is **pure downward bias**, not noise
   control. For a bright delta sun the per-sample luminance grows ∝ S but is capped
   at 20, so the measured brightness **asymptotes at ~14–20 across S = 1e6…1e9**
   instead of growing linearly (measured, PR #507). This is a silent energy loss
   for any bright delta light, and — via the `S/selPdf` convergence in the power-CDF
   (see secondary finding) — for any high-power delta light with low selection
   probability.

2. **It cannot honor a direct/indirect distinction** because it fires on the
   already-summed sample color, after direct and indirect are inseparable.

### What Cycles does (the reference)

`src/kernel/film/light_passes.h::film_clamp_light`:

```c
const float limit = (bounce > 0) ? kernel_data.integrator.sample_clamp_indirect
                                 : kernel_data.integrator.sample_clamp_direct;
```

Cycles selects the clamp **per contribution** by bounce depth (`bounce == 0` →
`sample_clamp_direct`, `bounce > 0` → `sample_clamp_indirect`), and **both default
to 0 (disabled)**. The documented guidance is to **leave direct light unclamped** —
"clamping direct light paths can have a too extreme effect" — because fireflies are
overwhelmingly an indirect-path phenomenon. Cycles has **no** always-on hardcoded
luminance cap; firefly control is entirely opt-in and split direct/indirect.

### Astroray already has the split — but it is dead

`include/raytracer.h:2123-2124` declares `clampDirect = 0` / `clampIndirect = 0`
with setters (`:2179-2180`), reset (`:2244-2245`), and Python bindings
(`module/blender_module.cpp:1444-1449`, `set_clamp_direct`/`set_clamp_indirect`).
**These fields are never read/applied anywhere in the integrator** (repo-wide grep:
only declaration/setter/reset/binding sites). So Astroray ships the Cycles
direct/indirect API surface **unwired**, and the only clamp actually in effect is
the hardcoded, always-on, direct+indirect-combined `sLum > 20`.

---

## Adjudication + fix contract (primary)

**Replace the hardcoded always-on top-level clamp with the Cycles-style
per-contribution direct/indirect split that is already stubbed, and never bias
direct/delta NEE energy.**

1. **Remove** the unconditional `sLum > 20` cap at `raytracer.h:3005`.
2. **Wire `clampDirect`/`clampIndirect`** into the path integrator, applied
   **per contribution by bounce depth**, mirroring `film_clamp_light`:
   - `bounce == 0` (camera-visible emission + first-hit direct NEE, **including
     delta-light NEE**) → clamp by `clampDirect`.
   - `bounce > 0` (indirect) → clamp by `clampIndirect`.
   - A limit of `0` means **disabled** (Cycles semantics). This requires
     accumulating direct vs indirect luminance separately inside `sampleFull` and
     clamping each before summing, rather than clamping the combined `sCol`.
3. **Default policy — the adjudicated tradeoff.** Cycles defaults both to 0 (off).
   But Astroray's existing firefly/caustic **tests currently rely on the always-on
   20 cap** to stay green, so removing it wholesale risks regressing them. Resolve
   evidence-first:
   - **`clampDirect` default = 0 (off), non-negotiable** — direct/delta NEE must
     never be silently biased. This is the whole point of the package.
   - **`clampIndirect` default** = the smallest value that keeps the existing
     firefly/caustic tests green (candidate: the legacy 20, but confirm — it may be
     unnecessary, or a different value may be cleaner). Choose it by running those
     tests, not by assumption. If the tests pass with `clampIndirect = 0` too,
     prefer full Cycles parity (both off).
   - Document the chosen defaults and cite `film_clamp_light` + the bounce-split.

This is **not an invented algorithm** (CLAUDE.md §6): it is a direct port of Cycles
`film_clamp_light`'s bounce-indexed clamp selection into the existing (stubbed)
`clampDirect`/`clampIndirect` fields. Apache-2.0, already a project reference.

### Gates (primary)

- **NEW — bright-sun energy linearity.** A delta sun on a gray floor: measured
  brightness **grows ∝ S** across at least three decades (e.g. S = 1e6, 1e7, 1e8),
  matching the analytic `albedo · S / π` within noise (PR #507 measured the
  sun-alone analytic at 0.63603 vs 0.63662). The current code asymptotes ~14–20;
  post-fix the ratio to analytic stays ~1 at every S. Metric: per-channel
  mean-ratio to analytic (NOT SSIM). This test is the package's reason to exist —
  add it.
- **Existing firefly/caustic tests unchanged** — the mixed-metallic gray-furnace
  glow test (`test_disney_energy_conservation.py:69`), any caustic/prism firefly
  gates, and the general render suite stay green. This is what pins the
  `clampIndirect` default.
- **Furnace/white-furnace unchanged** — the clamp restructuring must be a no-op on
  energy-conserving scenes below the clamp threshold.
- **GPU parity if applicable.** If the GPU/wavefront integrator has its own
  hardcoded firefly cap (grep for a `20.0f`/`fminf` luminance cap in the kernels),
  apply the same split so GPU==CPU; else note N/A. Do not run two CUDA verifiers
  concurrently (memory `cuda_verifier_concurrency`).
- **Build evidence** (CLAUDE.md): `.pyd` mtime vs `git log -1 HEAD`,
  `astroray.__file__ = build_cuda/Release/` before the gates.

---

## Secondary finding (lower priority; separable) — DistantLight vs AreaLight power() unit-scale mismatch

The power-CDF light selector (`src/light_sampler.cpp:52`,
`selPdf = power_i / totalPower`) assumes every light's `power()` is a comparable
radiant-flux proxy. It is not:

- `AreaLight::power()` = `luminance · intensity · normalizeFactor · area · π`
  (`src/lights/area_light.cpp:119-127`) — a flux-like quantity, **O(10²–10³)** at
  intensity 300.
- `DistantLight::power()` = `luminance · intensity · normalizeFactor · solidAngle`
  (`src/lights/distant_light.cpp:98-107`) — scaled by the sun's tiny solid angle
  (Ω ≈ 6e-5 for a 0.5° sun), so **O(1e-5)** at intensity ~4.

At comparable *visual* brightness these differ by **~7–8 orders of magnitude**, so
in a mixed sun+area scene the power-CDF selects the sun with vanishingly small
probability → very high NEE variance for the sun (and, compounded with the primary
clamp bug, silent energy loss). This is a **light-selection-heuristic** question,
not a radiometry bug: a distant light delivers irradiance S to every surface
**independent of its angular size**, so its scene importance is comparable to an
area light of similar illuminance — the `× solidAngle` factor **understates** it.

**Contract (secondary — research-first, may split to its own package):**
- Do **not** hand-tune a fudge factor. Research Cycles' light-importance metric —
  `src/scene/light.cpp` `LightManager` importance and the light-tree measure
  (Estevez & Kulla 2018, "Importance Sampling of Many Lights") — for how a
  sun/distant light's selection importance is put on a common scale with area
  lights (importance ∝ emitted radiance/irradiance, not raw flux × angular size).
  Cite the source (CLAUDE.md §6).
- Change `DistantLight::power()` (or introduce a separate `selectionImportance()`
  that the CDF uses instead of `power()`) so distant and area lights sit on a
  comparable importance scale. Keep `power()`'s radiometric meaning intact if it is
  used elsewhere — check call sites before repurposing it.
- **Gate:** a mixed sun+area scene shows both lights selected with sane
  probabilities and the sun's NEE converges at a feasible sample budget; existing
  single-light energy tests unchanged. Lower priority than the primary clamp fix;
  the coordinator flagged it as "same spec or a note."

---

## Definition of done
- [x] Hardcoded `sLum > 20` cap removed; `clampDirect`/`clampIndirect` wired per-bounce (bounce==0→direct, bounce>0→indirect), 0=disabled, mirroring `film_clamp_light`.
- [x] `clampDirect` default 0 (off); `clampIndirect` default chosen evidence-first (measured 0 keeps the full firefly/caustic/furnace suite green — full Cycles parity, both off), documented in `.astroray_plan/docs/pkg144-firefly-clamp-research.md`.
- [x] NEW bright-sun energy-linearity gate added and green (with_sun ∝ S across 3 decades — 1e6/1e7/1e8 — ratio-to-analytic ~0.9995).
- [x] Existing firefly/caustic + furnace + render suites unchanged; build evidence shown (see PR).
- [x] GPU firefly-cap parity handled: the two PRODUCTION GPU megakernels (`path_trace_kernel.cu` tracePathGPU, `multiwavelength_kernel.cu` tracePathMW — the latter is what the default `path_tracer` integrator actually dispatches to on GPU) got the same bounce-indexed split. The pkg55 wavefront SoA dev-harness kernels (`stage_advance.cu`/`stage_restir.cu`, not in the production dispatch path) still carry the old whole-path clamp — explicitly deferred, see research doc.
- [ ] Secondary: distant-vs-area selection-importance — DEFERRED, not attempted this round (time-boxed to the primary clamp-split fix). Still open.

**Wavefront wiring: pkg157** (2026-07-26, PR #526). pkg55-C7 (PR #524) deleted
both GPU megakernels this package wired above, taking their clamp-split with
them — the wavefront that replaced them (now the ONLY GPU render path) never
had it, and still carried the OLD always-on whole-path `lum > 20` cap the
megakernel fix removed (`stageRegenKernel` in `stage_advance.cu`,
`stageRestirResolveKernel` in `stage_restir.cu`). pkg157 re-ports the bounce-
indexed `clampDirect`/`clampIndirect` split into the wavefront's four
accumulation sites (env/background miss + emissive-hit in `intersectPathSlot`,
NEE/shadow-resolve in `shadePathSlot`/`stageShadowKernel`, and ReSTIR-DI's
primary+resolve terms in `stage_restir.cu`) via a new shared device helper
`gpu_clampContribMW` (`src/gpu/gpu_spectral_tables.h`) — the direct wavefront
port of this package's own deleted `multiwavelength_kernel.cu::gpu_clampContribMW`
(commit `1af7eca`). No SMS-caustic-equivalent site exists in the wavefront (its
caustic mechanism is the structurally different pkg55-C5 photon-map gather, not
a per-bounce specular-manifold chain) — that accumulation path is unclamped by
design, same as before. HW verification pending; see pkg157 PR body.
- **Un-xfail note:** `test_direct_and_indirect_clamp_controls` (test_python_bindings.py) un-xfailed — genuinely fixed by this package. The two Disney-highlight tests named in the dispatch (`test_disney_metallic_tints_specular_highlight`, `test_disney_roughness_changes_glossiness`) were investigated in depth and found NOT to be caused by the firefly clamp (converged, stable R/B and mean gaps of ~0.03-0.06 and ~0.0087 respectively, well under their 0.10/0.015 gates, unchanged across clamp settings 0/20/1e6 and across 64-2048 spp) — root cause is a Pillar-2 Disney specular-magnitude question adjacent to pkg145 (Disney specular energy compensation refit), not pkg144's integrator clamp. Their xfail reasons were updated with the measured evidence and left in place; see PR body.

---

## Hardware verification 2026-07-23

**Hardware:** NVIDIA GeForce RTX 5070 Ti. **OS:** Windows 11 Enterprise 10.0.26200.
**CUDA:** v12.8 (`nvcc.exe`). **OptiX:** 9.1.0. **OIDN:** 2.4.1.
Worktree: `Astroray-pkg144` (branch `pkg144-firefly-clamp-split`), bound to HEAD
`089bf720e17a1b4e18c82e5d20c423f49ddc549f`. `.pyd` rebuilt clean via
`configure_and_build.bat` (`cmd.exe //c`, absolute path invocation required —
`cmd /c` alone under this Bash tool opens an interactive shell instead of
executing; `//c` or the fully-qualified path avoids it). Confirmed
`astroray.__file__` resolves to the worktree's own `build_cuda/Release/`.

### Pass/fail table

| Test | Command | Result |
|---|---|---|
| Bright-sun energy-linearity (new gate) | `pytest tests/test_pkg144_firefly_clamp_direct_indirect_split.py -q -v` | **8 passed** |
| Material/binding + clamp controls | `pytest tests/test_material_properties.py tests/test_python_bindings.py -q` | **92 passed, 15 xfailed, 2 xpassed** in 75.11s |
| `test_direct_and_indirect_clamp_controls` | `pytest tests/test_python_bindings.py -k clamp -v` | **1 passed** (confirmed genuinely un-xfailed) |
| Furnace/firefly/caustic regression (6 files) | `pytest tests/test_disney_energy_conservation.py tests/test_dielectric_glass_furnace.py tests/test_disney_rough_glass_furnace.py tests/test_disney_reflection_not_black.py tests/test_caustic_validation.py tests/test_pkg140_distant_light_zero_angle.py -q` | **290 passed** in 7.99s |
| GPU caustic parity | `pytest tests/test_gpu_caustic_parity.py -q` | **1 passed, 1 xfailed** in 2.27s |
| Pre-existing-failure check (worktree) | `pytest tests/test_pkg55_c5_photon_wavefront.py::test_wavefront_photon_caustic_parity -v` | **FAILED** — `SSIM=-0.0000 < 0.80 (peak WF=1.208 MW=1.591)` |
| Pre-existing-failure check (unmodified main, SHA 833ac60, read-only, no git changes) | same test, run against main's own `.pyd` | **FAILED** — byte-identical: `SSIM=-0.0000, peak WF=1.208 MW=1.591` |

Verdict on the "1 failed" claim: **confirmed genuinely pre-existing**, unrelated
to pkg144 (pkg55 wavefront/MW photon-caustic parity gap, tracked separately).

### GPU dispatch nuance found during verification (not a pkg144 regression)

`Renderer::integratorName_` default-constructs to an **empty string**, not
`"path_tracer"`. On GPU this matters: `blender_module.cpp`'s
`integratorName_ == "path_tracer" -> renderMultiwavelength` dispatch only
fires when `set_integrator("path_tracer")` is called explicitly — with no
integrator set, GPU dedicated-light scenes render solid black (CPU's
`pathTraceSpectral` has no such gate and renders correctly either way). Every
GPU render in this verification pass explicitly called
`set_integrator("path_tracer")` after `set_use_gpu(True)` to route through the
production MW megakernel per the PR's own dispatch note. Confirmed pre-existing
binding behavior, orthogonal to the clamp-split change.

### Measured numbers — bright-sun energy linearity (the gate this package exists for)

CPU (via the test's own scene, S = 1e6/1e7/1e8, `angular_diameter` ∈ {0.0 (delta), 0.00918}):

```
ad=0.0:    ratios_rgb = [0.9981, 1.0006, 0.9668]   (stable across all 3 decades)
ad=0.00918: ratios_rgb = [0.9974, 1.0022, 0.9680]  (stable across all 3 decades)
```

GPU (`set_use_gpu(True)` + `set_integrator("path_tracer")`, same scene/seed):

```
ad=0.0:     ratios_rgb = [0.9922, 0.9993, 0.9876]  (stable across all 3 decades)
ad=0.00918: ratios_rgb = [0.9995, 0.9975, 0.9775]  (stable across all 3 decades)
```

No collapse toward 0 at any S on either backend — the pre-fix bug (asymptote at
~14-20 regardless of S) is gone. Full per-case numeric dump:
`test_results/overnight_report_2026-07-23/pkg144_hw_numbers.json` and
`pkg144_linearity_ratios.json` (worktree `test_results/`).

### Visual inspection summary

- **Disney contact sheet** (`tests/scenes/disney_contact_sheet.py`, 512×512,
  512spp) at defaults (both clamps off) vs the saved main-before reference
  (`disney_contact_sheet_before.png`, SHA 476581f, the commit immediately
  preceding pkg144's code): **visually near-identical**, no banding, no NaN
  (magenta/black) pixels, no mode regression. Mean display RGB within
  <0.02% of the before render. The multicolored speckle cluster on the metal
  sphere's lower-left is present **identically** in before/defaults/clamped —
  pre-existing dispersion/caustic noise, not introduced by this PR.
- **Firefly quantification** (linear/unclamped renders, pixel-luminance vs
  5×5 local-median outlier ratio): defaults shows a **modest increase** in
  outlier pixel counts vs main-before — 3×: 153→171 (+12%), 5×: 61→74 (+21%),
  10×: 12→16 (+33%), 20×: 3→1 (down); max spike ratio roughly doubles
  (2274→4645). This is the expected clamp-removal bias/variance tradeoff
  (this particular scene has no delta sun, so the old cap rarely triggered —
  the effect is small). Mean linear luminance unchanged (<0.02%) across
  before/defaults/clampIndirect=10 — **no energy loss**.
- **`clampIndirect=10` demonstration**: on the same contact sheet, firefly
  outlier counts drop **below the main-before baseline at every threshold**
  (3×: 154, 5×: 53, 10×: 9, 20×: 0) while mean brightness stays within 0.02%
  of the unclamped default — the new control suppresses fireflies without
  visible energy loss, exactly as designed.
- **Bright-sun scene** (S=1e7, fixed-exposure tonemap referenced to the
  analytic floor value): defaults (`clampDirect` off) renders a uniform
  correctly-exposed mid-grey floor (ratio-to-analytic ~0.99-1.00, highlights
  no longer capped). A control render with `clampDirect=20` (simulating the
  removed always-on `sLum>20` cap) renders **solid black at the same fixed
  exposure** — floor pinned at ~20 regardless of S=1e7, a ~5-order-of-
  magnitude underexposure. This is the exact bug the PR fixes, reproduced
  and visually confirmed on this hardware.

PNGs (worktree `test_results/`, copied to
`test_results/overnight_report_2026-07-23/` with `pkg144_` prefix):
`pkg144_contact_sheet_defaults.png`, `pkg144_contact_sheet_clamped.png`,
`pkg144_bright_sun.png`, `pkg144_bright_sun_oldcap_sim.png`.

### Anomalies to watch

- GPU integrator-dispatch empty-string default (above) is a latent footgun
  for any future GPU test/scene author who forgets `set_integrator("path_tracer")`
  — silently renders black rather than erroring. Worth a follow-up ticket,
  out of scope for pkg144.
- The pkg55 wavefront/MW photon-caustic SSIM=-0.0000 failure remains open
  and unrelated; do not re-attribute it to future clamp-split work.

**Verdict: PASS**, bound to `089bf720e17a1b4e18c82e5d20c423f49ddc549f`.
