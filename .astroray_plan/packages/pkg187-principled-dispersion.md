# pkg187 — Principled BSDF dispersion (achromatic caustics from Principled glass)

**Pillar:** 3/5 (spectral light transport / Blender parity)
**Track:** A
**Status:** open (found 2026-08-12 during the post-pkg178/pkg182 spectral-
integration + CPU/GPU-parity audit; production-relevant since
`use_native_principled` defaulted **ON** 2026-08-11)
**Estimated effort:** M
**Depends on:** pkg178 (native Principled BSDF); pkg31/pkg29 (Sellmeier
dielectric plugin); pkg64 (GPU Sellmeier / hero-λ upload); SMS/MNEE
(`include/astroray/mesh_attempt.h`).

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
  Astroray-native Sellmeier node, never the Principled socket). Blender 4.2+
  exposes a Dispersion input on Principled BSDF; that value is **dropped
  silently** on import.

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
3. Add the **Dispersion socket mapping** to the Blender addon Principled import
   (grep target: the thin-film socket mapping, add Dispersion beside it).
4. Guard SMS/MNEE (`mesh_attempt.h`): a Principled caster with nonzero
   dispersion must feed per-λ IOR into the manifold solver; a zero-dispersion
   Principled must behave exactly as today (no regression).

## Acceptance criteria

- [ ] A Principled glass prism with nonzero Blender Dispersion produces
      **chromatic** caustics (measurable hue spread), CPU and GPU. Verify
      **visually** — hue_spread + bright_coverage both pass on noise
      ([[general-photon-loop-needs-solid-glass]]); LOOK at the render.
- [ ] Zero-dispersion Principled glass is bit-unchanged from current behavior
      (regression guard).
- [ ] CPU/GPU per-λ parity on a dispersive Principled prism (per-channel
      mean-ratio, not SSIM).
- [ ] The Blender Dispersion socket round-trips: set it in Blender → engine
      renders chromatic. Verify headlessly (Blender 5.1 is installed locally;
      [[blender-5-1-installed-locally]]).
- [ ] Research notes for the Abbe→dispersion mapping saved under
      `.astroray_plan/docs/` with the Cycles source cited in-code.

## Hard non-goals

- **No new dispersion model.** Reuse Sellmeier/Cauchy via the cited Abbe mapping;
  the dielectric plugin already carries the machinery.
- **No thin-film re-work** — thin-film sockets already map (pkg178); this is only
  the Dispersion socket + per-λ refraction IOR.
- **No change to the non-dispersive Principled fast path** beyond adding the
  overrides; zero-dispersion cost must not move.
