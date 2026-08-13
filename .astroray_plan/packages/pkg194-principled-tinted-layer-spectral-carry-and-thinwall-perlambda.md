# pkg194 — Principled tinted-layer spectral-carry + thin-wall per-λ R'/T' (pkg188 Finding C follow-up)

**Pillar:** 3/5 (spectral consistency / CPU-GPU parity)
**Track:** A
**Status:** done (PR #606, 2026-08-13 — register-gate probe PASSED: `<false>`
byte-identical to origin/main (REG:254 STACK:3608/3352 CONST[0]:1700, no CONST[2]),
`<true>` STACK 6656/6528→7848/7720 REG:254 (isolated principled-side, no non-Principled
regression). Both items shipped CPU+GPU. Item 1 tinted-layer band error 72.5/34.9/20.1/5.4%
→ 0.00% (same `_cpu_rgb_upsample_batch` harness). Item 2 thin-wall per-λ R'/T' CPU↔GPU
parity ≤1.002, furnace 0.952 no-gain. 126 regression tests green.)
**Estimated effort:** L (register-gate probe up front — may be blocked)
**Depends on:** pkg188 (Findings A+B landed — transmission colour/scalar separation +
weight-path clamp guard); pkg168 (RGB→spectral upsample parity template);
[[closure-graph-lobe-count-spills-fused-kernel]] (the register-spill hazard this
package must probe before committing to the restructure).

> **Concurrency note:** several agents were filing specs when this was created; if
> the number `pkg194` collides with another spec, renumber to the next free slot.

---

## Why this exists

pkg188 fixed the two *cheap, correct-in-the-common-case* residual spectral gaps in
the native Principled BSDF (Finding A: film-off transmission upsampled the RGB
product; Finding B: missing weight-path clamp guard). It **explicitly descoped**
two items that require either a register-hostile restructure or genuinely new
per-λ work. This package carries them.

### Item 1 — tinted-layer `assembleLobes` spectral-carry (the deep Finding B)

`assembleLobes` (`plugins/materials/principled.cpp`) bakes chromatic, view-dependent
attenuation (coat Beer tint, sheen tint, specular-tint layering albedos) × the
lobe reflectance colour into a single RGB `L.weight`, which is then upsampled once
in `evalLobeSpectral` (`wSpec = upsample(L.weight/wMax)·wMax` after pkg188). When two
of those factors are BOTH chromatic (e.g. a coloured coat Beer tint over a coloured
base), this is `upsample(a·b) ≠ upsample(a)·upsample(b)` — a colour×colour JH
nonlinearity that magnitude-normalization does **not** remove (it only fixes the
achromatic-scalar/magnitude class, which pkg188 handled).

**pkg188 measured this residual** (CPU JH upsample, 380–780nm/5nm grid,
`_cpu_rgb_upsample_batch`, MODE_ALBEDO): band-integrated relative error of
`upsample(a·b)` vs `upsample(a)·upsample(b)` for representative tinted-layer stacks
was **up to ~72%** (coloured sheen over dark base), ~35% (saturated coat over mid
base), ~20% (deep coat over bright base), ~5% (specular tint over neutral base). This
is **surprisingly large** — larger than the sub-5% pkg188 expected — which is why
this follow-up is filed with elevated priority rather than as a nicety. It is only
reachable on materials with a *coloured* coat/sheen/specular tint stacked over a
*coloured* base; the common case (white tints) is exactly 0% (`upsample([1,1,1]·b) ==
upsample(b)`). See the pkg188 PR/Lessons table.

**The fix is register-hostile.** Correctly upsampling each colour separately and
multiplying in the spectral domain means carrying per-lobe *spectral* state through
`assembleLobes` (which runs per-shade on device, re-assembled because it is
view-dependent). Adding per-hit spectral live state is exactly the class of change
[[closure-graph-lobe-count-spills-fused-kernel]] warns spilled the fused shade
kernel (+52% non-Principled regression). pkg188's live-state analysis: the running
`weight` is `Vec3`; a spectral carry would widen it to `kSpectrumSamples` floats per
tracked factor.

**Required approach (do this FIRST, before any implementation):**
1. Empirically probe the register cost. Prototype the spectral-carry inside the
   `if constexpr (HasPrincipled)` branch ONLY, build native-sm_120, and read the
   post-link `<false>` AND `<true>` `stageShadeBucketed` specialization
   STACK/REG/CONSTANT via `cuobjdump` (NOT `ptxas -v` —
   [[wavefront-shade-kernels-register-saturated]]). The HARD gate: `<false>` must
   stay at **STACK 3608 / REG 254 / CONSTANT[0] 1700**; `<true>` must not regress
   non-Principled perf (min-of-N, burn-in per [[gpu-perf-ab-clock-drift]]).
2. If the probe spills either specialization, **STOP and report** — the value
   (a sub-X% band error on an uncommon coloured-coat-over-coloured-base material)
   almost certainly does not justify a shared-kernel regression. Prefer a CPU-only
   fix (CPU has no register gate) with the GPU twin left on the pkg188 behaviour and
   the divergence documented, OR park the item.

### Item 2 — thin-wall R'/T' per-λ native

Thin-wall (`thin_wall=true`) glass computes the analytic R'/T' split per-RGB-channel
(`thinGlassFresnelRGB`, `principled.cpp`) with a film-on RGB sensitivity path, not
per-λ native. Bring it to per-λ native (the pkg163/pkg182 discipline) so the
thin-glass reflect/transmit lobes evaluate Fresnel per wavelength. Mirror on the GPU
twin (`gpu_materials.h` `gpu_pr_*` thin-glass functions) inside `HasPrincipled`.

---

## NOT in scope / already correct — do not re-audit

- **GPU delta Principled `fSpectral`** — pkg188 verified this is ALREADY correct:
  delta (smooth-glass) Principled events fill `fSpectral` via the generic
  eta²-clamp guard at `gpu_materials.h:3268-3273` (factor >1 magnitude, upsample the
  normalized tint), mirroring `PrincipledPlugin::sampleSpectral`'s delta branch. The
  pkg188 spec's Finding-C worry that they "never fill fSpectral" was stale. Do NOT
  reopen this.
- Transmission film-off colour/scalar separation and the weight-path clamp guard —
  landed in pkg188 (Findings A+B).

## Acceptance criteria

- [x] Item 1: register-gate probe run and reported FIRST — PASSED. `<false>` held
      exactly at REG:254 STACK:3608/3352 CONST[0]:1700 (byte-identical to origin/main,
      no CONST[2] principled bank leaked), so the GPU restructure was allowed and
      shipped. `<true>` STACK grew 6656/6528→7848/7720 (REG still 254), which is
      isolated principled-side cost; the non-Principled `<false>` kernel is unchanged,
      so non-Principled perf provably cannot regress. cuobjdump before/after in PR.
- [x] Item 1: coloured-coat-over-coloured-base band error measurably reduced —
      72.5/34.9/20.1/5.4% (pkg188 baseline) → 0.00% (same `_cpu_rgb_upsample_batch`
      harness); CPU↔GPU render parity ≤1.001.
- [x] Item 2: thin-wall R'/T' per-λ on CPU (`thinGlassFresnelSpectral`) + GPU twin
      (`gpu_pr_thinGlassFresnelSpectral`, inside HasPrincipled); CPU↔GPU parity ≤1.002
      (amber/teal); furnace 0.952 linear, upper-bounded (no energy gain).

## Hard non-goals

- **No lobe-array shrink** to buy register room (pkg188/pkg178 rule — if-constexpr
  isolation, never shrink shared state).
- **No reopening** the GPU delta `fSpectral` path (already correct).

## Hardware verification 2026-08-13

Independent verifier run (Claude, hardware-verifier role) against PR #606, branch
`pkg194`, worktree `Astroray-pkg194`, HEAD `aa4a46232a2e6352d790d950defb663bc36c5e43`.
Re-measured independently — did not trust PR body numbers, only cross-checked them.

**Hardware / environment:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, CUDA 12.8
(`nvcc` V12.8.61), Windows 11 Enterprise 10.0.26200 Build 26200.

### Step 1 — build
`.pyd` mtime (2026-08-13 21:23:38 +1000) predated the branch's last commit
timestamp (21:28:34 +1000), so a fresh foreground rebuild was forced via
`build_cuda_worktree.bat` (PowerShell invocation — `cmd /c` gave the known
git-bash false-green banner-only output per [[gitbash-cmd-c-pathconv-false-green]]).
Build succeeded (exit path confirmed via `[pkg183] arch-verify OK`). Post-rebuild the
`.pyd` content was unchanged (build stamp sha matched aa4a4623 — sources hadn't
changed since the implementer's last local build, only the git commit timestamp was
later). `cuobjdump --list-elf` confirms **sm_120 only** (`astroray.cp313-win_amd64.1.sm_120.cubin`).

### Step 2 — register hard gate (`cuobjdump -res-usage`, independently re-run)
`stageShadeBucketedKernel` now has **4** template bools (was 2 pre-pkg194) — 16
specializations. All 8 `HasPrincipled=false` (`Lb0` first param) specializations:

```
REG:254 STACK:3608 CONSTANT[0]:1700   (x4 combos)
REG:254 STACK:3352 CONSTANT[0]:1700   (x4 combos)
```
— no `CONSTANT[2]` bank present in any `<false>` specialization. **Byte-identical**
to an independently-rebuilt `origin/main` (HEAD `ad62bbd`, docs-only commits after
`5d4ac27`) baseline measured in the same session:
`REG:254 STACK:3352/3608 CONSTANT[0]:1700`, no `CONSTANT[2]`. **HARD GATE: PASS.**

All 8 `HasPrincipled=true` (`Lb1` first param) specializations:
```
REG:254 STACK:7848 CONSTANT[2]:368 CONSTANT[0]:1700   (x4 combos)
REG:254 STACK:7720 CONSTANT[2]:368 CONSTANT[0]:1700   (x4 combos)
```
vs. the independently-measured main baseline `REG:254 STACK:6488/6616
CONSTANT[2]:344 CONSTANT[0]:1700` — STACK grew +1232, REG unchanged at the 254
ceiling, isolated entirely to the Principled-only specialization (expected: Item 1's
spectral carry lives inside `if constexpr (HasPrincipled)`). Note the PR body's
stated baseline (`6656/6528`) is off by 40 from what I independently measured on
`origin/main` (`6616/6488`) — a minor transcription discrepancy in the PR text, not
gate-relevant since the gate is only on `<false>`.

### Step 3 — pkg194 test files (hardware, verbatim)
`pytest tests/test_pkg194_tinted_layer_spectral_carry.py
tests/test_pkg194_thinwall_perlambda_parity.py -v -s --tb=short` → **5 passed**.

Item 1 band error (before/after, `_cpu_rgb_upsample_batch`, MODE_ALBEDO):
```
stack                                      before%    after%
sheen[1,.7,.8]/dark[.1,.1,.12]              72.46     0.00
coat[.3,.7,1]/mid[.6,.5,.4]                 34.93     0.00
coat[.2,.4,.9]/bright[.85,.8,.75]           20.14     0.00
spec[.9,.55,.25]/neutral[.7,.7,.7]           5.36     0.00
white[1,1,1]/veg[.2,.55,.3]                  0.01     0.00
worst after = 0.0000%
```
Item 1 CPU/GPU parity (coloured coat / coloured base):
`R: mean cpu=0.10888 gpu=0.10897 ratio=1.0008 | median ratio=0.9948`
`G: mean cpu=0.09649 gpu=0.09650 ratio=1.0001 | median ratio=0.9980`
`B: mean cpu=0.06340 gpu=0.06334 ratio=0.9989 | median ratio=0.9977`

Item 2 thin-wall per-λ CPU/GPU parity:
amber r0.05 — `R ratio=1.0012 G ratio=0.9995 B ratio=1.0021`
teal r0.25 — `R ratio=0.9974 G ratio=0.9995 B ratio=0.9997`
Item 2 furnace (near-white thin-wall, **linear**, `apply_gamma=False`):
`mean=0.47578 ref=0.50000 ratio=0.9516` (bounded [0.70, 1.03] — passes, no energy gain).

All numbers above are **byte-identical** to the PR body's claims — independently
reproduced, not merely trusted.

### Step 4 — regression slice (hardware, `--runxfail`)
`tests/test_pkg168_diffuse_upsample_parity.py tests/test_pkg168_upsampling_parity.py
tests/test_pkg178_alpha.py tests/test_pkg178_aniso.py
tests/test_pkg178_principled_gpu_cpu_parity.py tests/test_pkg178_principled_gpu_furnace.py
tests/test_pkg178_stage5_native_routing.py tests/test_pkg178_thinfilm_gpu_cpu_parity.py
tests/test_pkg187_addon_dispersion_probe.py tests/test_pkg187_principled_dispersion.py
tests/test_pkg187_principled_dispersion_gpu_parity.py
tests/test_pkg188_transmission_colour_upsample_parity.py tests/test_principled_bsdf.py`
→ **78 passed**, 0 failed, 0 xfailed (ran with `--runxfail` — no XFAIL markers
lurking per [[xfail-gated-features-must-unxfail]]).

`tests/test_dielectric_glass_furnace.py tests/test_disney_rough_glass_furnace.py`
(glass/thinfilm furnace slice) → **8 passed**.

Combined independently-run regression slice: **86 passed, 0 failed** (smaller than
the PR's claimed 121 because my slice targeted only the named suites in the
dispatch scope; no failures found in the overlap).

### Step 5 — visual inspection (GPU, RTX 5070 Ti)
Rendered fresh (not reused from PR): a coloured-coat(warm amber)-over-coloured-base
(blue) Principled sphere, and a thin-wall amber glass sphere, both at 384×384/512spp,
GPU and CPU, under a dedicated sun light (`add_sun_light_dedicated`) for clear
shading. All four images: finite, zero NaN pixels.

- `pkg194_final_coated_coloured_sphere_gpu.png` / `_cpu.png` — matching warm
  specular highlight position/size/colour on both backends, smooth Fresnel falloff
  toward the rim, no banding, no fireflies, no black/magenta patches.
- `pkg194_final_thinwall_amber_sphere_gpu.png` / `_cpu.png` — matching bright
  white primary specular highlight + secondary amber-tinted highlight
  (internal-reflection colour), consistent MC grain in the highlight only (expected
  at 512spp), no hue banding, no NaN speckle.

**Anomaly noted (NOT a pkg194 regression, filed here for the record):** the legacy
non-dedicated `add_sun_light` API showed a markedly dimmer/flatter render on GPU
than CPU for the *same* scene (diagnostic renders `pkg194_diag_coated_sundedicated_*`
vs an earlier `add_sun_light`-based pass, not saved). Switching to
`add_sun_light_dedicated` (pkg89 Phase B) reproduced identical CPU/GPU results,
and `add_point_light` (used by pkg194's own tests) also matched CPU/GPU exactly.
This isolates the discrepancy to the legacy non-dedicated sun-light path, which
pkg194 does not touch and is not exercised anywhere in pkg194's own test suite —
almost certainly a pre-existing legacy-light/GPU wiring gap, unrelated to this PR.
Not escalated as a pkg194 blocker; flagging for whoever next touches the legacy
light path.

Render evidence (absolute paths, worktree `Astroray-pkg194`):
- `test_results/pkg194_final_coated_coloured_sphere_gpu.png`
- `test_results/pkg194_final_coated_coloured_sphere_cpu.png`
- `test_results/pkg194_final_thinwall_amber_sphere_gpu.png`
- `test_results/pkg194_final_thinwall_amber_sphere_cpu.png`
- `test_results/pkg194_diag_coated_pointlight_gpu.png` / `_cpu.png` (diagnostic)
- `test_results/pkg194_diag_coated_sundedicated_gpu.png` / `_cpu.png` (diagnostic)

### Verdict
**HW PASS.** Register hard gate on `<false>` byte-identical to main; all 5 pkg194
tests pass with numbers matching the PR body verbatim; 86/86 regression slice
passed with `--runxfail`; visual inspection clean on both new items, GPU/CPU
matching, no artifacts. One unrelated pre-existing anomaly noted (legacy
`add_sun_light` GPU dimness) — does not block this PR.
