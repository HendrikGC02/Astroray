# pkg218 — Spectral colorimetry fidelity: accurate atomic-line lamp SPDs + configurable observer / camera response function

**Pillar:** 2
**Track:** A (architect to research + scope before implementation)
**Status:** open (filed 2026-08-22). **RESEARCH SPEC** — architect researches, splits,
and sizes before any implementation.
**Priority:** owner (2026-08-22): part of Pillar 4, **not the current main focus**.
Sequence behind the active work. Filed so it is tracked, not to dispatch now.

## Motivation

Two distinct spectral-colour issues surfaced while debugging preset lamps in Blender
(2026-08-22). They are related (both govern what colour a spectrum renders as) but have
different fixes, and the owner asked specifically whether the second one — the renderer's
"response function" — is the cause and whether it can be changed. It is NOT the cause of
the immediate bug, but it is a legitimate research-grade capability the owner wants.

---

## Thread A — atomic-line lamp SPDs are chromatically inaccurate (data bug)

**Evidence (measured, this session):** the stored `mercury_vapor` SPD in `profiles.bin`
integrates (against the engine's own CIE-1964-10° CMF) to chromaticity **xy = (0.314,
0.311)** — a magenta-white *below* the blackbody locus — and the CPU render reproduces
that colour **exactly** (normalized sRGB (1.00, 0.84, 1.00)). So the renderer is faithful;
the **stored SPD is wrong**. A real high-pressure mercury lamp is a **greenish-white ~xy
(0.33, 0.38)**, *above* the locus.

**Root cause:** `scripts/data/build_spectral_profiles.py` builds mercury from line weights
**436 nm (1000, blue) : 546 nm (500, green) : 405 nm (400, violet)** + a flat continuum.
That 2:1 blue:green ratio under-weights the 546 nm green line; in a real HPMV lamp the 546
green is comparable to or stronger than the 436 blue. Sensitivity check: boosting only the
green bins ~2–2.5× moves it to xy (0.315–0.316, 0.344–0.359) → green-dominant sRGB, i.e.
real-lamp-like. (Sodium is correct: xy (0.583, 0.417), deep amber.)

**Fork / cite requirement (CLAUDE.md §6):** do NOT blindly ×2 the green line. Pull real
relative line intensities for each atomic-line lamp from a cited source — **NIST Atomic
Spectra Database** line strengths and/or a measured HPMV emission spectrum — re-derive the
weights, and justify the chosen continuum model. Audit EVERY atomic-line lamp for
chromaticity vs its real counterpart, not just mercury.

**Acceptance (thread A):**
- [ ] Each atomic-line lamp's stored-SPD chromaticity is within a stated ΔE / Δxy of a
      cited real-lamp reference (mercury lands near (0.33, 0.38)).
- [ ] Regenerate `profiles.bin`; A/B-render **every** atomic-line lamp across SEPARATE
      processes (the `SpectralProfileDatabase::load()` process-wide-singleton footgun —
      memory `spectral-profile-edit-footguns`), visually inspected (salt-and-pepper guard).
- [ ] Research note under `.astroray_plan/docs/` citing the line-intensity source.

---

## Thread B — the spectral response function (observer) is hardcoded; make it configurable

**Owner question (2026-08-22):** *what response function does it use now, and can it be
changed to the human eye, or to different cameras?*

**Current state (audited):** the renderer's "response function" is a **CIE standard
observer** (the human-eye colour-matching functions), and it is **hardcoded / baked**:
- Primary spectral→XYZ: **CIE 1964 10° observer** — `cieCmf1964_10deg`
  (`include/astroray/spectrum.h:33`, `src/spectrum.cpp`), baked to GPU constant memory in
  `src/gpu/gpu_spectral_tables.cu` (`g_cmfX/Y/Z`, 360–830 @1 nm) via `uploadCmfTables()`.
- A white-balance constant `k = 1/∫D65·ȳ dλ` is derived from that same CMF (`g_d65SPD`).
- Inconsistency to resolve: `include/astroray/spectral.h` also carries a **CIE 1931 2°**
  CMF (380–780 @5 nm), and ReSTIR luminance (`include/astroray/restir/light_sample.h`)
  uses **1931 2°**. So two observers coexist in the codebase.
- There is **no runtime control** and **no camera-spectral-sensitivity path**.

**The feature:** make the response function a first-class, swappable input:
- Built-in observers: CIE 1931 2°, CIE 1964 10° (and unify the codebase on the selected
  one — kill the silent 1931/1964 split).
- Load a **measured camera spectral sensitivity** (R/G/B response curves) so a render can
  reproduce what a *specific* sensor sees — the research-grade case for astrophysics
  (matching a telescope/instrument passband) the owner is after.
- Re-derive the white-balance normalization per response function; upload the chosen table
  to the GPU constant-memory CMF slots; expose it in the addon (a scene setting + a way to
  load a CSV/`.spd` sensitivity file).

**Relationship to Thread A (important):** thread B is **not** the cause of the mercury
magenta. The mercury render already matches the SPD's analytic colour *under the current
observer*, and a real mercury lamp is greenish *under that same observer*. Swapping the
observer would shift ALL colours, not fix the specific green deficiency — that is a data
problem (thread A). Keep them separate; B is an additive capability, A is a correctness fix.

**Acceptance (thread B):**
- [ ] Observer is selectable (≥ CIE 1931 2° / 1964 10°) at scene level, CPU + GPU, with the
      white-balance constant re-derived per choice; the 1931/1964 codebase split is unified.
- [ ] A measured camera spectral sensitivity can be loaded and drives spectral→RGB; a known
      test spectrum reproduces the expected sensor RGB within a stated tolerance.
- [ ] Cite the observer data provenance (cvrl.ucl.ac.uk / colour-science) and any camera
      sensitivity dataset used.

## Reference
- Measured analysis this session (mercury xy, green-boost sweep, deviceReference note).
- `scripts/data/build_spectral_profiles.py` (line weights), `data/spectral_profiles/profiles.bin`.
- `src/spectrum.cpp`, `include/astroray/spectrum.h`, `include/astroray/spectral.h`,
  `src/gpu/gpu_spectral_tables.cu`, `include/astroray/restir/light_sample.h`.
- Memory: `spectral-profile-edit-footguns`, `astroray-native-nodes-need-astroray-output`.
- **Related but separate:** the GPU preset-lamp red-shift (a different bug — the CPU-side
  `emission_spectrum.cpp` `deviceReference` 4-sample MC RGB estimate — being fixed under its
  own chip; do NOT conflate with thread A/B).
