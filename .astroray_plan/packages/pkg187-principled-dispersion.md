# pkg187 — Principled BSDF dispersion (achromatic caustics from Principled glass)

**Pillar:** 3/5 (spectral light transport / Blender parity)
**Track:** A
**Status:** done — CPU-complete + GPU-wired (PR #593, 2026-08-12 — CPU chromatic prism
red/blue spread 4.27→5.35px; zero-dispersion byte-identical; addon forward-probe
unit-tested; `<false>` shade kernel **REG:254/STACK:3608 byte-identical to main**
at TRUE sm_120 — see the register-gate note below. GPU-visible wavefront
dispersion deferred to the follow-up spec filed 2026-08-12 — it is a pre-existing
frozen no-op that the dielectric reference shares.)
**Estimated effort:** M

> **Register-gate note (corrected 2026-08-12).** The first measurement read
> `REG:254/STACK:2640` — that was the **fleet-wide stale-arch artifact**: every
> `build_cuda` tree carried a cached `CMAKE_CUDA_ARCHITECTURES=52`, so `cuobjdump`
> read Maxwell PTX, not the sm_120 SASS that runs (pkg183 is shipping an automatic
> guard). Rebuilt both worktree and a fresh merge-base baseline with
> `-DASTRORAY_CUDA_ARCHS=120 -DCMAKE_CUDA_ARCHITECTURES=120` (verified
> `compute_120,sm_120` in the generated project) and re-ran `cuobjdump
> --dump-resource-usage` on the FINAL LINKED `.pyd`: `stageShadeBucketedKernel<false>`
> is **REG:254 STACK:3608 CONSTANT[0]:1700 on BOTH** baseline and pkg187 —
> byte-identical, no register/stack increase (the if-constexpr HasPrincipled
> isolation holds at the true arch).
**Depends on:** pkg178 (native Principled BSDF); pkg31/pkg29 (Sellmeier
dielectric plugin); pkg64 (GPU Sellmeier / hero-λ upload); SMS/MNEE
(`include/astroray/mesh_attempt.h`).

> **Correction (2026-08-12, during implementation).** The original spec claimed
> "Blender 4.2+ exposes a Dispersion input on Principled BSDF; that value is
> dropped silently on import." **This is false.** A headless `bpy` probe of the
> installed builds — Blender **4.3.2, 4.5.0, 5.1.0, 5.2.0** — shows **no**
> Dispersion socket on `ShaderNodeBsdfPrincipled`, `ShaderNodeBsdfGlass`, or
> `ShaderNodeBsdfRefraction`. Principled dispersion is **unmerged upstream WIP**:
> Blender PR [#162041](https://projects.blender.org/blender/blender/pulls/162041).
> Per the coordinator-approved **Option A**, the engine core (Work 1/2/4) ships
> and is verified via engine-level dispersion params; the addon gets a
> forward-compatible socket **probe** (no-op today, live when #162041 ships) that
> is unit-tested against a synthetic node. Work 3 and the Blender-round-trip
> acceptance criterion are rewritten accordingly below.

---

## Symptom

`PrincipledPlugin` is **not dispersion-aware**, so a Blender Principled glass
prism produces **silently achromatic caustics** — no rainbow, no chromatic
split — even when the Blender material sets a nonzero Dispersion.

Concretely:

- `PrincipledPlugin` has **no `iorAt(λ)` override** — it inherits the flat
  `iorAt` at `include/astroray/raytracer.h:488`, returning the same IOR at every
  wavelength.
- **No `isDispersive()` override**, so `src/gpu/scene_upload.cu` never sets the
  dispersive flag, and the GPU wavelength-aware sampler
  (`include/astroray/gpu_materials.h:3121`, gated on `GMAT_DIELECTRIC`) is
  **unreachable** for a Principled material — which lowers to
  `GMAT_CLOSURE_GRAPH`, not `GMAT_DIELECTRIC` (see
  [[gpu-dielectric-lowers-to-closure-graph]]).
- **No `terminateSecondary()` / hero-wavelength collapse on refraction**, so
  even if the sampler were reached, the chromatic path would not collapse to a
  hero λ correctly.
- SMS/MNEE caster gathering (`include/astroray/mesh_attempt.h:45,64`) only
  requires `isTransmissive()`. A Principled glass prism therefore **enters the
  chromatic specular-manifold solver** but runs it with **identical IOR at every
  λ** — the solver does chromatic work and gets an achromatic answer.
- The Blender addon maps thin-film sockets but has **no Dispersion socket
  mapping at all** (`grep -rni "dispersion" blender_addon/` returns only the
  Astroray-native Sellmeier node, never the Principled socket). ~~Blender 4.2+
  exposes a Dispersion input on Principled BSDF; that value is dropped silently
  on import.~~ **CORRECTED:** no shipped Blender (4.3–5.2, probed) exposes such a
  socket — it is unmerged WIP (PR #162041). So nothing is being "dropped"; the
  addon simply has no forward-compatible probe for the socket the WIP will add.

Net: the audit's answer to "is native Principled spectrally consistent?" is
"no, for refraction" — dispersion is a real Blender socket that this engine
ignores end to end.

---

## Reference implementation — cite, don't invent

Invoke the `cite-algorithm` skill for the **Abbe-number → dispersion-curve**
mapping before writing code. Blender's Principled Dispersion input is an Abbe
number (Vd); the engine's existing dielectric uses Sellmeier coefficients. The
canonical bridge is the Cauchy or a reduced-Sellmeier fit from (Vd, IOR at
d-line). Do not hand-roll a wavelength dependence.

- `plugins/materials/dielectric.cpp:110-142` — the existing **Sellmeier**
  dielectric plugin, including the **pkg64 GPU hero-λ upload** path. This is the
  in-repo template for `iorAt(λ)`, `isDispersive()`, `terminateSecondary()`, and
  the scene-upload dispersive flag. Mirror its structure; do not re-derive it.
- **Cycles' Principled dispersion handling** — how Cycles converts the Abbe
  number to per-λ IOR for the Principled BSDF transmission lobe. Cite the exact
  Cycles source (Apache-2.0) in the code and save research notes to
  `.astroray_plan/docs/` per CLAUDE.md §6.
  **RESOLVED:** the canonical source is `bsdf_glass_ior` in
  `intern/cycles/kernel/closure/bsdf_microfacet.h` (Blender PR #162041), which
  implements the **OpenPBR Surface v1.1.1** two-term **Cauchy** fit
  `n(λ)=A+B/λ²`, `B=(n_d−1)·(dispersion_scale/Vd)·fac`, `A=n_d−B/λ_d²`, Fraunhofer
  lines λ_d=0.5876/λ_C=0.6563/λ_F=0.4861 μm. Full notes:
  `.astroray_plan/docs/pkg187-principled-dispersion-research.md`. Implemented in
  `principled.cpp::cauchyAB` (CPU) + `gpu_dispersion.cuh::gpu_cauchy_ior` (GPU).

---

## Work

1. Add `iorAt(λ)`, `isDispersive()`, and `terminateSecondary()` /
   hero-collapse-on-refraction overrides to `PrincipledPlugin`, driven by the
   Abbe→dispersion mapping (cited), following `dielectric.cpp:110-142`.
2. Ensure `src/gpu/scene_upload.cu` uploads the dispersive flag + hero-λ IOR
   data for a dispersive Principled material. Because Principled lowers to
   `GMAT_CLOSURE_GRAPH` (not `GMAT_DIELECTRIC`), verify the wavelength-aware
   refraction path at `gpu_materials.h:3121` is reachable from the closure-graph
   transmission lobe — if it is gated purely on `GMAT_DIELECTRIC`, that gate
   must widen or the closure-graph transmission must call the same per-λ IOR.
3. **(REWRITTEN — Option A.)** No shipped Blender exposes a Dispersion socket
   (see the correction note above), so add a **forward-compatible probe** beside
   the thin-film socket mapping: `put_float('dispersion_scale', 'Dispersion
   Scale', 'Dispersion')` + `put_float('dispersion_abbe', 'Dispersion Abbe
   Number')`. It is a no-op on every current build (socket absent → nothing
   written → engine non-dispersive) and round-trips automatically the day PR
   #162041 ships. Unit-test it against a synthetic node carrying those inputs.
   Do **not** add a new in-UI Dispersion socket to any Astroray-native node
   (out of scope).
4. Guard SMS/MNEE (`mesh_attempt.h`): a Principled caster with nonzero
   dispersion must feed per-λ IOR into the manifold solver; a zero-dispersion
   Principled must behave exactly as today (no regression).

## Acceptance criteria

- [x] A Principled glass prism with nonzero dispersion produces **chromatic**
      caustics (measurable hue spread) on **CPU** — verified visually (red/blue
      centroid spread 4.27px → 5.35px, max RGB diff 0.92; LOOKED at the render).
      **GPU: see the GPU-leg finding below** — GPU wavefront dispersion is a
      pre-existing frozen no-op (dielectric identical), so the GPU chromatic gate
      is deferred to the separately-filed follow-up; pkg187 gates the GPU leg on
      *faithful-mirror-of-the-dielectric-reference* + the register gate instead.
- [x] Zero-dispersion Principled glass is bit-unchanged from current behavior
      (regression guard — `np.array_equal` passes).
- [x] **(REWRITTEN — GPU-leg finding.)** ~~CPU/GPU per-λ parity on a dispersive
      Principled prism (per-channel mean-ratio, not SSIM).~~ Not achievable: the
      GPU **wavefront** spectral dispersion (hero-collapse) is a pre-existing,
      frozen no-op — it does not fire for the dielectric reference either
      (`test_pkg64_gpu_cpu_parity` xfail since 2026-06-08; pkg64 defers GPU
      per-wavelength multi-IOR to Session 2). **Measured (256spp, spectral srgb,
      glass sphere refracting a colored backdrop):**

      | material   | CPU flat | CPU disp | GPU flat | GPU disp |
      |------------|----------|----------|----------|----------|
      | Principled | 0.2053   | 0.1138   | 0.2041   | 0.2041   |
      | dielectric | 0.2144   | 0.1183   | 0.2131   | 0.2139   |

      CPU dispersion is live for BOTH; GPU dispersion is a no-op for BOTH. pkg187
      wires Principled into the identical infra (scene_upload Cauchy upload +
      `gpu_material_sample_spectral` hero-IOR + `terminateSecondary`), so the
      achievable GPU gate is *no new divergence vs the dielectric reference*
      (`test_pkg187_principled_dispersion_gpu_parity.py`) + the cuobjdump register
      gate. GPU-visible wavefront dispersion is a **separately-filed follow-up
      (2026-08-12)**; enabling it lights up dielectric AND Principled through this
      same wiring.
- [x] **(REWRITTEN — Option A.)** The forward-compatible addon probe is
      unit-tested against a synthetic Principled node carrying 'Dispersion Scale'
      / 'Dispersion Abbe Number' inputs (maps to `dispersion_scale` /
      `dispersion_abbe`); and the chromatic render is verified via the engine
      dispersion params. (The literal "set it in Blender's Principled node" path
      is unreachable until PR #162041 ships — no shipped Blender exposes it.)
- [x] Research notes for the Abbe→dispersion mapping saved under
      `.astroray_plan/docs/pkg187-principled-dispersion-research.md` with the
      Cycles source cited in-code (`principled.cpp::cauchyAB`,
      `gpu_dispersion.cuh::gpu_cauchy_ior`).

## Lessons / findings

- **Premise correction (Blender socket).** No shipped Blender (4.3.2–5.2.0,
  headless-probed) exposes a Dispersion socket on Principled/Glass/Refraction —
  it is unmerged WIP (PR #162041). Verify feature availability against the actual
  installed DCC before building integration around a socket.
- **GPU wavefront dispersion is a pre-existing frozen no-op.** The hero-collapse
  dispersion on the GPU wavefront leg (`stage_advance.cu` →
  `gpu_material_sample_spectral`) does not produce visible dispersion for the
  dielectric reference either (BK7 control: GPU flat 0.2131 ≈ bk7 0.2139). The
  working GPU dispersion is the *photon-caustic* path (pkg113/pkg185), a different
  mechanism. Enabling GPU wavefront dispersion (and wiring the photon path for
  closure-graph casters) is a **separately-filed follow-up (2026-08-12)**; pkg187
  correctly wires Principled into the frozen infra so it lights up for free when
  that lands.
- **`--runxfail` XPASS can be vacuous.** `test_gpu_prism_rainbow_parity` "passed"
  under `--runxfail` in 0.80s with no render output — the assert cleared without a
  real GPU render. The xfail marker is RETAINED; a real render-level check is
  needed once GPU dispersion is enabled. Do not report that XPASS as a feature.

## Hard non-goals

- **No new dispersion model.** Reuse Sellmeier/Cauchy via the cited Abbe mapping;
  the dielectric plugin already carries the machinery.
- **No thin-film re-work** — thin-film sockets already map (pkg178); this is only
  the Dispersion socket + per-λ refraction IOR.
- **No change to the non-dispersive Principled fast path** beyond adding the
  overrides; zero-dispersion cost must not move.

---

## Hardware verification 2026-08-12 (PR #593, independent verifier pass)

**Hardware:** RTX 5070 Ti (sm_120 / Blackwell), Windows 11 Enterprise
10.0.26200, NVIDIA driver 610.47 (CUDA UMD 13.3), CUDA Toolkit 12.8.61
(nvcc), OptiX 9.1.0, OIDN 2.4.1. Build: MSVC 19.44.35208 (VS2022 BuildTools),
VS-generator `build_cuda` (root wrapper) + Ninja for the Blender-addon leg.

**Arch discipline:** both the PR tree and the merge-base baseline were
rebuilt **from scratch** (`build_cuda/` deleted, reconfigured with
`-DASTRORAY_CUDA_ARCHS=120 -DCMAKE_CUDA_ARCHITECTURES=120`) after this
session hit the exact fleet-wide stale-arch failure mode independently: a
leftover baseline worktree cache read `CMAKE_CUDA_ARCHITECTURES:STRING=52`.
Post-link `cuobjdump --list-elf` confirmed `sm_120.cubin` (not PTX/Maxwell)
on every `.pyd` trusted below.

### Gate table (measured vs claimed)

| # | Gate | Claimed | Measured | Verdict |
|---|------|---------|----------|---------|
| 1 | Register gate — `stageShadeBucketedKernel<false>` (post-link `.pyd`, `cuobjdump --dump-resource-usage`, true sm_120) | REG:254 STACK:3608 CONSTANT[0]:1700 both sides, byte-identical | PR tree: `REG:254 STACK:3608 CONSTANT[0]:1700`. Baseline (merge-base `7b9cc1b`, independent from-scratch sm_120 rebuild in a separate worktree): `REG:254 STACK:3608 CONSTANT[0]:1700`. **Exact match, zero delta** (not even the allowed CONSTANT[2] delta — that field doesn't appear on `<false>` at all on either side; it only appears on `<true>`, which is out of scope for this gate). | **PASS** |
| 2 | CPU chromatic dispersion (prism red/blue centroid spread + visual) | 4.267px → 5.345px, max RGB diff ~0.92 | `test_principled_dispersion_is_chromatic`: flat 4.267px, dispersive 5.345px, max abs RGB diff 0.9165 (mean 0.0779). Visual: rendered `pkg187_principled_flat.png` / `pkg187_principled_dispersive.png` (96×96, 32spp) plus a computed diff image — the dispersive render shows a coherent magenta/purple mixing band exactly at the prism silhouette (red bleeding into the blue half and vice versa), matching the pkg29 dielectric reference's established visual signature. This is a structured, localized shift, not scattered noise. | **PASS** |
| 3 | Zero-dispersion bit-identity (regression guard) | `np.array_equal` | `test_zero_dispersion_is_bit_identical` PASSED (dispersion_scale=0 == no-params == baseline, exact). | **PASS** |
| 4 | GPU faithful-mirror parity + documented no-op control | Principled disp/flat ≈ dielectric disp/flat (both ≈1.0, no-op); Principled: [0.9986, 1.0026, 0.9998]; dielectric: [0.9997, 1.0136, 1.0025]; CPU disp/flat: principled 0.5541 vs dielectric 0.5518 | `test_gpu_dispersion_wired_mirrors_dielectric_reference`: GPU principled disp/flat = **[0.9986 1.0026 0.9998]**, GPU dielectric disp/flat = **[0.9997 1.0136 1.0025]** — exact match to claim. `test_cpu_dispersion_is_real_and_mirrors_dielectric`: principled disp/flat=**0.5541**, dielectric bk7/flat=**0.5518** — exact match. | **PASS** |
| 5 | 3 new test files + regression slice | "all pass (68)" | New: `test_pkg187_principled_dispersion.py` 4/4, `test_pkg187_addon_dispersion_probe.py` 3/3, `test_pkg187_principled_dispersion_gpu_parity.py` 2/2 — **9/9**. Regression sweep (pkg178 principled parity, spectral_prism, principled_bsdf, gpu_multiwavelength, gpu_sellmeier_ior, multiwavelength, metal parity pkg123/160/163, reflection_not_black ×2, prism_caustic_rainbow, sms_caustic_spectral, spectral_gpu_materials): **80/80**. Glass-caustic family (caustic_validation, glass_sphere_caustic, gpu_caustic_parity, sms_caustic_validation): **8 passed, 1 xpassed** (see gate 6). Grand total this session: **98 passed, 1 xpassed, 0 failed.** | **PASS** |
| 6 | `test_gpu_prism_rainbow_parity` stays xfail (not un-xfailed) | retained | Source confirms `@pytest.mark.xfail(strict=False, ...)` still present; run shows `XPASS` (not a hard PASS) in 0.90s. Marker retained as documented. | **PASS** |
| 7 | (Added mid-run, ABI-review addendum) Blender addon vtable-shift smoke — `getCauchyAB()` is a genuine mid-vtable insertion in `Material` (`raytracer.h`, right after `getSellmeierC()`, before `getTransmission()`), shifting every virtual slot declared after it | register + convert + render a trivial Principled scene without crash/garbage | Built `build_blender_addon_cuda` **from scratch** (`-DASTRORAY_DISABLE_OPENMP=ON`, Ninja, confirmed `sm_120.cubin` via `cuobjdump --list-elf`, no reused objects). Registered in headless Blender 5.1 (`blender_addon.register()` — "Astroray renderer addon registered"), converted a 1-mesh/960-triangle Principled-material sphere scene, rendered via `CUSTOM_RAYTRACER` on GPU (RTX 5070 Ti) in 1.65s. Output: 32×32, **0 NaN pixels**, mean 0.5621, max 1.0 — a plausible lit red sphere (visually confirmed), not a crash or garbage. | **PASS** |

### Build-tooling finding (not a pkg187 gate — flagging for the record)

`scripts/build/build_blender_addon.py`'s `_backend_config()` falls back to a
**hardcoded CUDA arch list `"75;86;89"`** (no sm_120) whenever
`ASTRORAY_CUDA_ARCHS` isn't passed on the CLI, and the script exposes no CLI
flag for it. Worse: re-invoking the script against an **already-correctly-configured**
`build_blender_addon_cuda` cache (manually set to `Release`/`120`) caused its
internal reconfigure to silently revert the cache to `CMAKE_BUILD_TYPE=Debug`
+ `CMAKE_CUDA_ARCHITECTURES=52`, which then hard-failed the build
(`/RTC1`+`/O2` incompatible). Gate 7 above was verified by configuring and
building the addon module **manually** with explicit
`-DASTRORAY_CUDA_ARCHS=120 -DCMAKE_CUDA_ARCHITECTURES=120
-DCMAKE_BUILD_TYPE=Release`, then pointing headless Blender at the resulting
`.pyd` via `ASTRORAY_PYD_DIR` (the same pattern `benchmarks/blender_parity/render_leg.py`
already uses) — bypassing the packaging script's buggy reconfigure/zip
pipeline entirely. The manually-built `.pyd` itself is confirmed sm_120 and
is what Gate 7 exercised; the packaging/zip/install pipeline itself was
**not** exercised and should not be assumed fixed by this pass. Recommend a
follow-up ticket for `build_blender_addon.py` (arch default + cache-revert-on-reconfigure).

### Overall verdict

**All 7 gates PASS on measured hardware evidence.** No visual regressions
found (chromatic fringe is real and localized, not noise; zero-dispersion
path untouched; GPU no-op control reads exactly as documented; addon
vtable-shift smoke is clean). The build-tooling gap above is out-of-scope for
pkg187 itself (pre-existing script limitation, not something this PR
introduced or worsened) and does not block merge.

Verifier does not adjudicate the merge decision — this is a numbers report
for the gate-review/merge process.
