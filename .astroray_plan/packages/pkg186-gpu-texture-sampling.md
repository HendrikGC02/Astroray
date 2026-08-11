# pkg186 — GPU texture sampling (the GPU path has zero texture support)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** open (found 2026-08-12 during the post-pkg178/pkg182 spectral-
integration + CPU/GPU-parity audit; owner asked "what still lacks GPU parity")
**Estimated effort:** L (scoped down by the two open decisions below)
**Depends on:** pkg115 (Blender shader-node texture adoption, CPU); pkg135
(demand-loaded sparse textures, CPU); pkg119-B (Blender differential parity
harness — used as the acceptance signal here).

---

## Symptom

The GPU render path has **no texture support at all**. It uploads exactly one
flat RGB per material:

- `src/gpu/scene_upload.cu` (lines 114, 202, 220, 239, 247) uploads
  `mat->getAlbedo()` — a single constant `Vec3` — per material. There is no
  per-texel data, no UV-indexed sampling.
- `include/astroray/gpu_types.h` has **no texture struct** (it carries the
  Stage-3b active-UV-layer coordinates at ~line 274, but nothing consumes them
  as a texture lookup — they are dead weight on the GPU side today).
- There is **no device-side texture sampling code anywhere** in `src/gpu/**`.

Consequence: any textured Blender material silently renders as **flat albedo**
on GPU, with **no warning and no addon guard**. The user sees a plausible-but-
wrong image and has no signal that a texture was dropped.

---

## Likely payoff — the pkg119-B TRANSLATION-BUGs

The 5 residual `TRANSLATION-BUG` entries in the pkg119-B differential-parity
baseline ([[pkg119b-harness-runbook]], 2026-08-08 baseline 26/12/1) are **all
procedural texture nodes**. Flat-albedo-on-GPU is the plausible **shared root
cause**: the CPU reference evaluates the procedural node; the GPU collapses it
to `getAlbedo()`. This spec therefore requires **re-running pkg119-B as an
acceptance signal** — if GPU texture support lands correctly, some or all of
those 5 should reclassify from TRANSLATION-BUG to parity-pass (or at least stop
being flat-albedo). Record the before/after classification counts.

---

## Required sub-item — backend-aware `__features__` dict

`module/blender_module.cpp` (~line 4491) advertises the capability dict:

```cpp
m.attr("__features__") = py::dict(
    "nee"_a=true, "mis"_a=true, "disney_brdf"_a=true, "sah_bvh"_a=true,
    "adaptive_sampling"_a=true, "volumes"_a=true, "textures"_a=true, "subsurface"_a=true,
    "gr_black_holes"_a=true,
    ...
```

`textures`, `volumes`, `adaptive_sampling`, and `gr_black_holes` are advertised
`true` **unconditionally**, though on the GPU path all four are CPU-only or
absent. The addon **Diagnostics panel displays this dict verbatim**, so it tells
the user "textures: yes" while the active GPU backend silently drops them.

Make the dict **backend-aware**: report per-capability truth for the *active*
backend (CPU vs CUDA/wavefront). Follow the pattern pkg171 established for the
CPU-only-integrator guard at `module/blender_module.cpp:1697` — the truth source
is the capabilities query the addon's `configure_backend` already reads, not a
hardcoded name. The Diagnostics panel must then show `textures: CPU only` (or
equivalent) when the GPU backend is selected, until this package closes the gap.

This sub-item is **required** and can land first (it is a small, honest guard
that stops the silent lie immediately, independent of the larger texture work).

---

## Open decisions (leave these for the implementer, record the choice)

These are genuine forks, not a manufactured menu — decide by scope/payoff:

1. **Image textures vs procedural nodes first.** The pkg119-B residuals are
   *procedural* nodes, so procedural-first maximizes the parity payoff. But
   image textures are the more common real-world asset and the simpler upload
   (a buffer + UV lookup) — a smaller, self-contained first slice. Pick one for
   this package; the other is a follow-up. State the choice and the reasoning.

2. **CUDA texture objects vs baked buffers.** `cudaTextureObject_t` gives free
   hardware bilinear + wrap modes but constrains formats/layout; a plain device
   buffer + manual UV fetch is simpler to wire and easier to make bit-parity
   with the CPU sampler. Decide per the slice chosen in (1) — procedural nodes
   have no image to bind and likely want evaluated-in-kernel or a baked buffer;
   image textures are the natural fit for texture objects.

---

## Work

1. Land the backend-aware `__features__` guard first (required sub-item);
   verify the Diagnostics panel reflects it in headless Blender.
2. Add the texture struct to `include/astroray/gpu_types.h` and the device-side
   sampler in `src/gpu/**` for the slice chosen in decision (1).
3. Wire the upload in `src/gpu/scene_upload.cu` — the per-material path must
   carry texture handles/data, not just `getAlbedo()`. Preserve the flat-albedo
   fast path for untextured materials (no per-texel cost when there is no
   texture).
4. Verify CPU/GPU parity on a textured scene (a per-channel mean-ratio gate, not
   SSIM — independent RNG streams; see [[ssim-wrong-gate-for-independent-rng]]).
5. **Re-run pkg119-B** ([[pkg119b-harness-runbook]]) and record the
   TRANSLATION-BUG reclassification for the 5 procedural-texture entries.

## Acceptance criteria

- [ ] `__features__` is backend-aware; Diagnostics panel no longer claims GPU
      texture support when the GPU backend drops textures.
- [ ] A textured material renders with its texture (not flat albedo) on the GPU
      path for the chosen slice, gated by a new test.
- [ ] CPU/GPU per-channel mean-ratio parity within band on a textured scene.
- [ ] pkg119-B re-run: before/after TRANSLATION-BUG counts recorded in Lessons;
      any procedural-texture entry that was flat-albedo is either fixed or
      explicitly explained as out-of-slice.
- [ ] Untextured materials show no measurable perf regression (flat-albedo fast
      path preserved).

## Hard non-goals

- **No attempt to cover both image and procedural textures in one package.**
  Pick one slice (decision 1); file the other as a follow-up.
- **No demand-loaded/sparse texture streaming** (that is pkg135's CPU scope; the
  GPU equivalent is a separate, larger package).
- **No `volumes`/`gr_black_holes` GPU implementation** — this package only makes
  the `__features__` dict *honest* about them, it does not implement them.
