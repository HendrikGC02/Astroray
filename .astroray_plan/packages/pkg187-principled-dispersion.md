# pkg187 — Principled BSDF dispersion (achromatic caustics from Principled glass)

**Pillar:** 3/5 (spectral light transport / Blender parity)
**Track:** A
**Status:** CPU-complete + GPU-wired (PR #593, 2026-08-12 — CPU chromatic prism
red/blue spread 4.27→5.35px; zero-dispersion byte-identical; addon forward-probe
unit-tested; `<false>` shade kernel REG:254/STACK:2640 unchanged. GPU-visible
wavefront dispersion deferred to the follow-up spec filed 2026-08-12 — it is a
pre-existing frozen no-op that the dielectric reference shares.)
**Estimated effort:** M
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
