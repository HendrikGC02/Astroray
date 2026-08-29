# pkg128 — Thin-film iridescence (Belcour-Barla), evaluated per-wavelength on the spectral core

**Pillar:** 2 (materials / BSDF) + 5 (spectral showcase)
**Track:** A (CPU-first spectral BSDF layer with numerical + visual gates; GPU spectral-closure mirror RTX-verified; Blender addon parity cells closed)
**Codex-paste-ready:** no (a physically-based interference model re-derived from the paper, applied across three closures + the GPU mirror, plus a spectral-showcase visual bar and addon socket wiring — needs judgment, not a mechanical patch)
**Status:** superseded by pkg178 — the per-λ Belcour-Barla thin-film Fresnel utility this spec designed landed and was Cycles-5.2 parity-verified under pkg178 Stage 4 (PR #584; `include/astroray/thin_film_fresnel.h`, `src/gpu/gpu_thin_film_table.cu`, wired in `plugins/materials/principled.cpp`). Residual charter (standalone Glass/Metallic node cells + spectral showcase) remains unactioned. Was: open — self-contained material feature; the recommended "good medium package after Phase C" in the research adoption plan. **Cross-ref 2026-08-08:** pkg178 (native Cycles Principled BSDF) Stage 4 adopts this spec's per-λ Belcour-Barla design and builds the shared thin-film Fresnel utility; this package's residual charter is the standalone Glass/Metallic node cells + the spectral showcase, riding that utility — coordinate at dispatch time.
**Estimated effort:** M–L (a self-contained interference term is moderate, but it attaches to metal/dielectric/Disney Fresnel on both CPU and GPU, needs a spectral-native evaluation the RGB references don't, and closes three DROPPED-SILENT addon parity cells with a visual showcase gate)
**Depends on:** none hard. Composes with the spectral material path (pkg30/pkg35 spectral BSDF interface) and the Fresnel evaluation in `plugins/materials/{metal,dielectric,disney}.cpp` + `include/astroray/gpu_materials.h`. Best sequenced after pkg55 Phase C so the GPU mirror lands in the single surviving wavefront closure rather than the doomed megakernel.

---

## Goal

**Before:** Astroray has no thin-film interference. A microfacet surface's Fresnel
term (`metal.cpp`/`dielectric.cpp`/`disney.cpp` and the GPU spectral closure in
`gpu_materials.h`) is the bare conductor/dielectric Fresnel — no wavelength-dependent
phase interference, so soap bubbles, oil slicks, anodised metal, and coated glass
render as flat, non-iridescent surfaces. The Blender Principled/Glass/Metallic nodes
expose **Thin Film Thickness** and **Thin Film IOR** sockets, and the addon parity
audit records all six of them as **DROPPED-SILENT**: a user who wires thin-film in
Blender gets a silently non-iridescent render
(`docs/blender_parity/report.md:570-571` glass, `:610-611` metallic, `:643-644`
principled; same rows in `docs/blender_parity/coverage_matrix.json`).

**After:** A thin-film interference layer modulates the specular Fresnel term of the
microfacet closures per the Belcour-Barla 2017 model, controlled by a film thickness
and film IOR. Because Astroray's core is **spectral**, the interference is evaluated
**per wavelength directly** — the airy/phase term is computed at each sampled
wavelength with no RGB spectral-sensitivity fit (the step that dominates the RGB
references' complexity is simply absent for us). Soap bubbles and oil slicks show
physically-correct, view- and thickness-dependent iridescence in the spectral
showcase. The Blender **Thin Film Thickness** / **Thin Film IOR** sockets on
Principled, Glass, and Metallic are honoured end-to-end, flipping those six parity
cells from DROPPED-SILENT to SUPPORTED.

---

## Context — the spectral renderer's showpiece material

The 2026-07 PBR sweep flagged thin-film as *"a self-contained, showcase-friendly
material feature — good medium package after Phase C"*
(`.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 6 + adoption plan),
and the follow-up pass confirmed **OpenPBR's recommended thin-film model is
Belcour-Barla** (`2026-07-pbr-advances-research-pass2.md` Axis C).

The differentiator worth foregrounding: iridescence **is** a spectral phenomenon —
the colour comes from wavelength-dependent constructive/destructive interference in
a film a few hundred nanometres thick. Every RGB renderer (Belcour-Barla's own
reference, Cycles) must approximate the spectral integral by fitting the interference
response to three RGB spectral-sensitivity curves — the paper's central engineering
compromise. Astroray already carries a bundle of real wavelengths through each path
(the spectral core), so it evaluates the interference term at the **actual sampled
wavelengths** and needs no RGB fit. That makes soap bubbles and oil slicks the
natural hero images for the spectral showcase and the journal article's
"why spectral" argument — a genuine capability the RGB engines only approximate.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### A. Port the Belcour-Barla interference term (CPU first, spectral-native)

- Implement the thin-film Fresnel modulation from **Belcour & Barla 2017,
  "A Practical Extension to Microfacet Theory for the Modeling of Varying
  Iridescence", ACM ToG / SIGGRAPH 2017** (project page + supplemental code, and the
  OpenPBR reference). The model replaces the interface Fresnel `F(cosθ)` with an
  interference-modulated reflectance that depends on film thickness `d`, film IOR
  `η₁`, the bounding media IORs, and wavelength `λ` via the optical path difference
  and the polarised phase shifts.
- **Evaluate per wavelength, not via the RGB sensitivity fit.** For each wavelength
  in the current `SampledWavelengths` bundle, compute the airy-summation reflectance
  at that `λ` directly. This is the spectral simplification: skip Belcour §4's
  projection onto RGB sensitivity curves entirely. Document at the call site that the
  RGB-fit step is intentionally omitted because the renderer is spectral.
- Attach as a **layer on the existing microfacet Fresnel**, not a new closure: in the
  specular-reflection Fresnel of `plugins/materials/metal.cpp` (conductor),
  `plugins/materials/dielectric.cpp` (dielectric), and `plugins/materials/disney.cpp`
  (the metallic/specular lobe `F0` path near `disney.cpp:381-385`). Two new material
  params `thinFilmThickness` (nm) and `thinFilmIOR`, default thickness 0 ⇒ term is a
  no-op (bit-equal to today).
- **Cite:** Belcour & Barla 2017 (DOI / project page in the research note); the
  OpenPBR specification's thin-film section, **Apache-2.0**, arXiv:2512.23696, as the
  parameterisation reference; and Cycles' implementation as the production
  cross-check (see B). Re-derive the polarised Fresnel phase math from the paper — do
  not copy GPL Cycles source (mirror the pkg64 SMS discipline).

### B. Cross-check against Cycles' thin-film kernel

- Cycles implements the same Belcour-Barla model in
  **`src/kernel/closure/bsdf_microfacet.h`** — a `FresnelThinFilm` struct feeding
  `fresnel_dielectric_polarized` / `fresnel_conductor_polarized` with phase shifts
  matched to the paper's figures (Blender PR **#118477**, Principled dielectric
  thin-film; PR **#141131**, thin-film for metals). Cycles is **Apache-2.0**, so it
  is a license-clean *reference for behaviour and the RGB cross-check*, but Astroray's
  evaluation stays spectral-native per A. Use a Cycles A/B on a soap-bubble scene as a
  qualitative parity check, accepting that Cycles' RGB fit and Astroray's spectral
  evaluation will differ slightly in hue by construction (record the expected
  divergence).

### C. GPU spectral-closure mirror

- Mirror the per-wavelength interference term into the GPU spectral closure
  (`include/astroray/gpu_materials.h` and the wavefront metal/dielectric shade,
  `src/gpu/wavefront/stage_shade_metal.cu`). Keep CPU and GPU in lockstep (same phase
  math, same per-λ evaluation); RTX-verify against the CPU render. Sequence after
  pkg55 Phase C so this lands in the single surviving wavefront closure, not the
  megakernel that Phase C deletes.

### D. Blender addon wiring — close the DROPPED-SILENT parity cells

- Read the **Thin Film Thickness** and **Thin Film IOR** sockets in the addon
  material conversion (`blender_addon/__init__.py::convert_materials`, the
  `BSDF_PRINCIPLED` / `BSDF_GLASS` / `BSDF_METALLIC` branches — the Principled path is
  around `__init__.py:3054` and `:3387`) and pass them to the renderer material as the
  new `thinFilmThickness` / `thinFilmIOR` params.
- Regenerate `docs/blender_parity/report.md` + `coverage_matrix.json` and confirm the
  six cells now read **SUPPORTED**: `BSDF_GLASS`/`BSDF_METALLIC`/`BSDF_PRINCIPLED` ×
  {Thin Film Thickness, Thin Film IOR}.

### E. Showcase + gates

- **Numerical gate:** an energy/furnace check that the thin-film term does not add
  energy — at thickness 0 the closure is bit-equal to today; at non-zero thickness the
  directional-hemispherical reflectance stays ≤ 1 (interference redistributes energy
  across wavelengths, it does not create it). Reuse the pkg60/pkg118 furnace
  harness pattern.
- **Spectral-showcase visual gate:** a soap-bubble and an oil-slick scene rendered on
  the spectral path showing thickness- and view-angle-dependent iridescent banding;
  saved as reference PNGs with an SSIM floor, in the spirit of the pkg64 caustic
  visual gate. These are the journal-article / showcase hero images.

---

## Acceptance criteria

- [ ] Thin-film interference term implemented in `metal.cpp` (conductor),
      `dielectric.cpp`, and the `disney.cpp` specular lobe, evaluated **per
      wavelength** on the spectral path with **no RGB sensitivity fit**; `thickness=0`
      is bit-equal to the pre-pkg128 closures.
- [ ] GPU spectral closure mirrors the CPU term; CPU↔GPU lockstep RTX-verified on a
      thin-film scene.
- [ ] Blender **Thin Film Thickness** + **Thin Film IOR** sockets honoured for
      Principled, Glass, and Metallic; the six `docs/blender_parity` cells flip
      DROPPED-SILENT → SUPPORTED (report + coverage_matrix regenerated).
- [ ] Energy gate: directional-hemispherical reflectance ≤ 1 across a
      (thickness, film-IOR, roughness, view-angle) grid — no glow.
- [ ] Spectral-showcase visual gate: soap-bubble + oil-slick reference renders show
      physically-correct thickness/view-angle iridescence; SSIM floor vs saved
      references; qualitative Cycles A/B recorded (expected hue divergence from
      Cycles' RGB fit documented, not treated as a failure).
- [ ] Research note `.astroray_plan/docs/thin-film-iridescence-research.md`: Belcour-
      Barla 2017 citation + DOI, OpenPBR (Apache-2.0) parameterisation, Cycles
      `bsdf_microfacet.h::FresnelThinFilm` (PR #118477/#141131) as the cross-check
      reference, the polarised-phase math reproduced, and the spectral-vs-RGB-fit
      rationale.
- [ ] CLAUDE.md §6 citations at every thin-film call site.

---

## Non-goals

- **Not a general layered-BSDF framework.** This is the single thin-film interference
  layer on the microfacet Fresnel — not position-free Monte Carlo layered BSDFs
  (research finding 5, a separate horizon package).
- **Not coat or fuzz.** OpenPBR documents coat (with darkening) and fuzz as distinct
  layers (finding 6); those are separate packages. This is thin-film only.
- **Not the RGB sensitivity-curve fit.** Deliberately omitted — the spectral core
  evaluates interference at real wavelengths. We do **not** port Belcour §4's RGB
  projection.
- **Not multiscatter energy compensation.** Reflection multiscatter is pkg129;
  thin-film redistributes energy spectrally but this package does not add the
  Turquin/Kulla-Conty compensation term.
- **No new procedural thickness textures beyond the socket value.** Honour the
  Blender socket (constant or texture-driven if the addon already resolves it); do
  not invent new thickness authoring UX.

---

## Provenance

Filed from the **2026-07-17 PBR-advances research sweep** (finding 6, verified 3-0,
`.astroray_plan/docs/2026-07-pbr-advances-research.md`) and its **follow-up pass**
(`2026-07-pbr-advances-research-pass2.md` Axis C, which confirmed OpenPBR's
recommended thin-film model is Belcour-Barla). The research adoption plan named
thin-film the showcase-friendly medium package after Phase C. The DROPPED-SILENT
parity cells are from the live addon parity audit (`docs/blender_parity/report.md`).
Owner context: iridescent soap bubbles / oil slicks are the spectral renderer's
showpiece — a capability RGB engines can only approximate via an RGB fit, and a
"why spectral" figure for the journal article.

---

## Progress

- [ ] A — Belcour-Barla per-wavelength interference term in metal/dielectric/disney
      Fresnel (CPU); thickness-0 no-op verified.
- [ ] B — Cycles `bsdf_microfacet.h` cross-check A/B recorded.
- [ ] C — GPU spectral-closure mirror; CPU↔GPU lockstep RTX-verified.
- [ ] D — addon socket wiring; six parity cells → SUPPORTED.
- [ ] E — energy gate + soap-bubble/oil-slick showcase visual gate.
- [ ] Research note written.

---

## Lessons

*(Fill in after the package is done.)*
