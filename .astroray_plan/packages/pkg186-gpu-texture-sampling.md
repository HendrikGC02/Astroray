# pkg186 — GPU texture sampling (the GPU path has zero texture support)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** done — image-texture slice (PR #590, 2026-08-12). Backend-aware
`__features__` guard landed + GPU image textures render with CPU parity
(per-channel mean-ratio 1.003 / 0.998 / 1.000). Untextured fleet kernel
BYTE-IDENTICAL (cuobjdump `stageShadeBucketedKernel<false,false>` REG:254
STACK:2640 == pre-pkg186 `<false>` STACK:2640). Procedural-node textures +
pkg119-B procedural reclassification deferred to a follow-up (out-of-slice; see
Lessons). (found 2026-08-12 during the post-pkg178/pkg182 spectral-
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

## Lessons (implementation, 2026-08-12)

### Decision 1 — IMAGE textures first (procedural deferred)
Register pressure is the #1 hard constraint. A procedural node evaluated in the
shade kernel means porting Perlin/Musgrave/Voronoi/wave/… noise evaluators into
the register-saturated `stageShadeBucketed` — heavy per-hit live state that spills
(exactly the pkg178 lobe-array class). An IMAGE texture is a single cheap fetch.
Image is also the more common real asset and the self-contained upload. So: image
first; procedural (which carries the pkg119-B payoff) is the filed follow-up.

### Decision 2 — baked device buffer + nearest fetch (NOT `cudaTextureObject_t`)
The CPU `ImageTexture::value` sampler is NEAREST-neighbour (clamp uv to [0,1], flip
v, floor to texel). Hardware bilinear via a texture object would DIVERGE from the
CPU reference and fail the parity gate. A baked buffer replicates the CPU sampler
bit-for-bit (`gpu_sampleImageTexture`) and needs no cudaArray/format/lifetime
machinery. All texels concatenate into one flat device buffer; each texture is an
`{offset,width,height}` slice (index addressing — no device-pointer-in-descriptor,
maps onto the wavefront's grow-only `wfUpload`).

### Register-safety architecture (the load-bearing part)
`GMaterial` is exactly 640 B (`alignas(64)`, zero slack) and is stack-copied by
value in `gpu_closure_as_material`, so a texture id CANNOT go in it (would round to
704 B and spill the shared `<false>` kernel — the pkg178 regression). The
per-material texture id lives in a PARALLEL device array `d_materialTextureId`.
Texture work is gated behind a NEW template bool `HasTexture` on `shadePathSlot` /
`stageShadeBucketedKernel`; untextured scenes instantiate `<HasPrincipled,false>`
which `if constexpr`-compiles out all texture codegen. The substitution itself is
ONE multiply: for a lambertian the whole bounce is linear in
`albedo_spec = upsample(baseColor)`, so `throughput *= upsample(texColor) /
upsample(baseColor)` before NEE+BSDF converts base→texture albedo exactly for both
the NEE eval and the BSDF continuation, with no per-hit `GMaterial` copy. UV is
barycentric-interpolated in-kernel from the hit triangle's uploaded active-layer
texcoords (Ericson RTCD §3.4), mirroring pkg178's recompute (no new per-path SoA
field; non-instanced only — instanced-texture UV is a follow-up).

### Measured gates (RTX 5070 Ti, sm_89 SASS)
- cuobjdump `--dump-resource-usage`, `stageShadeBucketedKernel<false,false>`
  (untextured non-principled fleet kernel): **REG:254 STACK:2640**, byte-identical
  to the pre-pkg186 single-bool `<false>` (pkg185 build, commit 24106ca):
  **REG:254 STACK:2640**. Zero regression — the `if constexpr` isolation held.
  Textured/principled instantiations are separate: `<false,true>`=STACK 4128,
  `<true,false>`=5952, `<true,true>`=5040 (paid only by scenes that use them).
  This byte-identity is stronger evidence than a clock-drift-confounded perf A/B.
- CPU/GPU per-channel mean-ratio on a lit UV-mapped textured quad (64², 96 spp,
  linear): **[1.003, 0.998, 1.000]** — essentially exact (substitution is exact
  for lambertian). GPU textured vs GPU flat-0.5 mean|diff| = **0.206** (texture is
  genuinely sampled, not dropped). Gate: `tests/test_pkg186_gpu_texture_parity.py`.
- `__features__` guard: `tests/test_pkg186_gpu_features_guard.py` (7 legs, CI-run).

### pkg119-B — deferred (out-of-slice), with a caveat on the premise
The 5 residual pkg119-B "TRANSLATION-BUG" entries are PROCEDURAL nodes; this slice
does IMAGE textures, so their GPU classification is unchanged (they still flatten
to base albedo — procedural eval is the follow-up). Per acceptance criterion 4 they
are explicitly explained as out-of-slice rather than re-run. NOTE: memory
`pkg119b-harness-runbook` (2026-08-08) DISPROVED the earlier TRANSLATION-BUG
convictions (`BSDF_TRANSPARENT`, `world:World`) as SSIM false-positives on
noise-dominated scenes — NOT flat-albedo texture drops — so the spec's "shared root
cause = flat-albedo" premise is at least partly contradicted by that analysis. The
procedural follow-up should re-baseline pkg119-B with the noise/under-converged
triage fix in place, not assume texture support alone reclassifies those entries.

### Deferred to follow-up
- Procedural texture nodes on GPU (the pkg119-B payoff).
- `cudaTextureObject_t` bilinear path (if a filtered CPU sampler ever lands).
- Instanced-mesh texture UV (object-local barycentrics; same cut pkg178 took for
  instanced anisotropy).
- Textured materials other than lambertian base color (metal/principled base-color
  texture slots — the addon TODO at exporter `_create_material` also notes this).
- Photon-caustic receiver on a textured lambertian still uses base albedo in the
  primary-hit gather (rare combo; documented in `stage_advance.cu`).
