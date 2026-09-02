# pkg210 — Companion wavelengths retained on specular reflection (terminate only on refraction)

**Pillar:** 3 (spectral light transport correctness)
**Track:** A (CPU+GPU spectral transport change — register-sensitive, probe-first).
**Estimated effort:** S–M (small logic change, but touches the register-pinned
hero-collapse path — MUST clear a cuobjdump probe before feature code).
**Status:** SUPERSEDED — premise stale, no work needed (verified 2026-09-02).
The described bug ("collapses companions on specular reflection too") does **not
exist** in current code. All four runtime `terminateSecondary()` sites already
fire on *actual refraction only*, never on reflection:
- GPU dielectric `gpu_materials.h:524` — inside the refraction `else` branch
  (the reflect branch at :510-514 never collapses). The spec misread this as
  "unconditional-on-dispersive"; it is refraction-gated.
- GPU principled `gpu_materials.h:3284` — `if (refracted) wl.terminateSecondary()`.
- CPU dielectric `dielectric.cpp:214` — `bool reflected = ...; if (!reflected)`
  (present since **pkg31**, the original Sellmeier impl).
- CPU principled `principled.cpp:2038` — gated on a Transmission lobe whose `wi`
  crosses the hemisphere (added by **pkg187**, PR #593).
Both guards predate this spec's 2026-08-19 filing, so companions have always
been retained through reflection. The desired behaviour is already the shipped
behaviour; a reflective-dispersive A/B render is available if belt-and-suspenders
confirmation is wanted, but there is nothing to implement.

Original spec below (kept for the record).

**~~Status:~~** ~~open (filed 2026-08-19).~~
**Depends on:** nothing hard. Independent of pkg206 (that changes the hero
*proposal*; this changes *when* companions are terminated). CPU+GPU byte-mirrored
in the SAME PR.

## Goal

Astroray collapses to the hero wavelength (`terminateSecondary()`, zeroing the 3
companion pdfs) on dispersive events. Today it fires the collapse on **specular
reflection too**, not only on refraction — see the call sites:
`include/astroray/gpu_materials.h:524` (`if (mat.isDispersive)
lambdas.terminateSecondary();`) and `:3284` (`if (refracted)
wl.terminateSecondary();`), plus the CPU `SampledWavelengths::terminateSecondary`
(`src/spectrum.cpp:102`). Dispersion physically occurs only where the ray
**refracts** (crosses into a medium with wavelength-dependent IOR); a specular
**reflection** does not disperse (it is second-order at grazing angles at most).
Collapsing companions on reflection needlessly throws away 3/4 of the spectral
samples and adds chromatic noise on reflective spectral paths. PBRT v4 and Cycles
both have this gap; keeping the companions on reflection is strictly more correct
and currently unclaimed.

## Specification

1. **REGISTER PROBE FIRST — this is register-hostile territory** (the hero-collapse
   logic lives on/near the pinned `stageShadeBucketedKernel`, REG 254). Before any
   feature code, run the cuobjdump `-res-usage` probe (sm_120 confirmed via
   `--list-elf` first) and confirm the change site's baseline; the acceptance gate
   is that the fleet `<0,0,0,0,0>` shade kernel stays byte-identical
   (REG 254 / STACK 3352 / CONSTANT[0] 1700). If gating the collapse on
   refract-vs-reflect adds live state that spills the shade kernel, **PARK** and
   report — do not ship a regression (memory
   `wavefront-shade-kernels-register-saturated`,
   `closure-graph-lobe-count-spills-fused-kernel`). This package MAY park on the
   probe; that is an acceptable outcome.

2. **Invoke `cite-algorithm`.** Cite the hero-wavelength MIS framework
   (**Wilkie et al. 2014**, DOI 10.1111/cgf.12419) for the correctness of carrying
   companions through non-dispersive events, and the standard result that
   dispersion arises at refractive interfaces (wavelength-dependent Snell), not at
   reflection. Note in a research note under `.astroray_plan/docs/` why reflection
   is (to first order) non-dispersive and the second-order grazing effect is out
   of scope.

3. **Gate the collapse on ACTUAL refraction only.** `terminateSecondary()` must
   fire only when the sampled event is a transmission/refraction through a
   dispersive interface — NOT on the specular reflection lobe of a dispersive
   material. Fix both GPU sites (`gpu_materials.h:524` unconditional-on-dispersive
   → refraction-only; `:3284` already guards `if (refracted)` — verify the other
   site and any CPU twin match this condition). **Mirror the CONDITION, not just
   the term** (memory: CPU→GPU ports must mirror the guard). Keep byte-mirror
   between CPU (`spectrum.cpp` caller) and GPU in the same PR.

4. **Verify unbiasedness.** Carrying companions on reflection must not change the
   converged result of a purely-reflective dispersive scene (it only reduces
   variance); a dispersive refraction scene must be unchanged (companions still
   collapse there).

## Acceptance

- [ ] **Register HARD gate:** fleet `stageShadeBucketedKernel<0,0,0,0,0>`
  byte-identical to baseline (254/3352/1700) after the change, verified on the
  final linked `.pyd` via cuobjdump (sm_120 first), mtime stated. If it spills,
  the package PARKS with the probe table recorded — that is a valid closeout.
- [ ] A reflective dispersive scene (mirror-through-glass or a dispersive metal
  reflection) shows **lower chromatic noise** at fixed spp than before (companions
  retained) — report an A/B noise/variance metric, LINEAR EXRs, seed-pinned.
- [ ] A dispersive **refraction** scene (prism) is unchanged within MC noise
  (companions still collapse on refraction — per-channel mean-ratio band).
- [ ] CPU↔GPU parity preserved; the collapse condition is byte-identical between
  CPU and GPU sites (show both snippets). Furnace/unbiasedness gates pass (render
  LINEAR with an upper bound).
- [ ] CI green on all matrix jobs AND the RTX leg (memory
  `ci-has-no-gpu-runtime-blindspot`).

## Non-goals

- **No grazing-angle second-order reflection dispersion** — explicitly out of
  scope; reflection is treated as non-dispersive (companions carried, not
  wavelength-split).
- **No change to the hero proposal density** (that is pkg206) and **no per-bounce
  re-sampling** (that is pkg211).

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`...2026-08-19-cycles-dispersion-research.html` §6.6, ranked recommendation #6).
Grounded in live code: `gpu_materials.h:524,3284`, `spectrum.cpp:102`,
`spectrum.h:133`, `gpu_types.h:109`. **Claude/careful-tier, probe-first** — the
register-hostile collapse-site plus the unbiasedness judgment make this a
last-line-of-defense package, NOT unattended open-model work; route the probe +
verification to Claude even if the mechanical edit is small.
