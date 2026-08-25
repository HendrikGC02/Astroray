# pkg222 — Atomic-line lamp SPDs: cited, chromatically-correct line intensities (pkg218 Thread A, extracted)

**Pillar:** 3 (spectral rendering) — data-correctness fix. (This is the
*data-bug* half of pkg218; pkg218 Thread B — the swappable observer / camera
response function — stays a separate Pillar-4 research item and is NOT in scope.)
**Track:** A
**Status:** open (filed 2026-08-25, architect planning pass; extracts pkg218
Thread A into an independently dispatchable, cheap-model-friendly unit).
**Priority:** MEDIUM-HIGH — every preset atomic-line lamp renders the wrong color
(mercury is magenta, should be greenish-white). Cheap to fix once the reference
line intensities are cited. Synergistic with pkg221 (emission-line dispersion is
only *correct-colored* once the line SPDs are right).
**Estimated effort:** M (research + data regen + A/B render audit; no engine C++).
**Implementer tier:** deepseek-v4-pro (data + citation + gated A/B render). The
citation-and-audit discipline is the value here, not code volume.

**GATING — READ FIRST:** `build_spectral_profiles.py` / `profiles.bin` are ALSO
touched by **pkg214fix** (in-progress sodium/mercury energy-normalization refix on
branch `pkg214fix`; PR #629 was HW-FAIL). Do NOT start this until pkg214fix has
LANDED, or you will collide on the same generator and the same profiles. After
pkg214fix merges, rebase and re-audit sodium+mercury TOGETHER (the peak-vs-energy
normalization coupling that bit #629 — memory none, see STATUS 2026-08-19→21).

---

## Root cause (measured this session — from pkg218 Thread A)

The stored `mercury_vapor` SPD in `data/spectral_profiles/profiles.bin` integrates
(against the engine's own CIE-1964-10° CMF) to chromaticity **xy ≈ (0.314, 0.311)**
— a magenta-white *below* the blackbody locus — and the CPU render reproduces that
color exactly (normalized sRGB (1.00, 0.84, 1.00)). So the renderer is faithful;
**the stored SPD data is wrong.** A real high-pressure mercury lamp is a
**greenish-white ~xy (0.33, 0.38)**, *above* the locus.

The generator `scripts/data/build_spectral_profiles.py` builds mercury from line
weights **436 nm (1000, blue) : 546 nm (500, green) : 405 nm (400, violet)** plus a
flat continuum. That 2:1 blue:green ratio under-weights the 546 nm green line; in a
real HPMV lamp the 546 green is comparable to or stronger than the 436 blue. (A
sensitivity check boosting only the green bins ~2–2.5× moves it to xy
(0.315–0.316, 0.344–0.359) → green-dominant, real-lamp-like. Sodium is already
correct: xy (0.583, 0.417), deep amber.)

## Goal

Every preset atomic-line lamp's stored SPD renders a color within a stated ΔE / Δxy
of a **cited real-lamp reference**, with the chosen relative line intensities and
continuum model traceable to a source in code + a research note.

## Specification

1. **`cite-algorithm` / cite-data first (CLAUDE.md §6).** Do NOT eyeball-multiply
   the green line. Pull real relative line intensities for each atomic-line lamp
   from a **cited** source: **NIST Atomic Spectra Database** line strengths and/or a
   published measured emission spectrum (e.g. a measured HPMV spectrum for mercury).
   Save a research note to `.astroray_plan/docs/pkg222-atomic-line-intensities.md`
   citing every source and the derivation (which lines, relative intensities,
   continuum model + its justification).
2. **Audit EVERY atomic-line lamp** in `build_spectral_profiles.py`, not just
   mercury — enumerate them, compute each stored SPD's chromaticity against the
   engine CMF, compare to its cited real-lamp reference, and list Δxy per lamp
   BEFORE and AFTER. (Sodium is expected already-correct; confirm it, don't regress
   it — this is the pkg214fix coupling risk.)
3. **Re-derive the line weights + continuum** from the cited intensities, regenerate
   `profiles.bin`, and commit BOTH the generator change and the regenerated binary
   (or document the exact regen command if the binary is build-time).
4. **A/B render audit across SEPARATE PROCESSES.** `SpectralProfileDatabase::load()`
   is a process-wide singleton — an in-process A/B is a no-op (memory
   `spectral-profile-edit-footguns`). Render each atomic-line lamp before/after in
   separate processes and visually inspect (salt-and-pepper guard).

## Acceptance criteria

- [ ] Each atomic-line lamp's stored-SPD chromaticity is within a stated Δxy (e.g.
      ≤ 0.02) of its cited real-lamp reference. Mercury lands near xy (0.33, 0.38)
      (greenish-white, above the locus).
- [ ] Sodium stays correct (xy ≈ (0.583, 0.417)); no regression vs the pkg214fix
      baseline. Audit table (BEFORE/AFTER xy + Δxy) for EVERY atomic-line lamp in
      the research note.
- [ ] `profiles.bin` regenerated; every atomic-line lamp A/B-rendered across
      SEPARATE processes, visually inspected, no salt-and-pepper artifacts.
- [ ] Research note under `.astroray_plan/docs/` citing the NIST line-intensity /
      measured-spectrum sources per lamp.
- [ ] No engine C++ change (data + generator only); existing spectral tests green.
      If the render pipeline is CPU-only for this audit, hold the GPU lock or force
      true CPU-only (memory `cpu-suites-autouse-cuda`).

## Reference

- `scripts/data/build_spectral_profiles.py` (line weights + continuum),
  `data/spectral_profiles/profiles.bin`.
- `include/astroray/spectrum.h` / `src/spectrum.cpp` (`cieCmf1964_10deg`, the
  observer the audit integrates against — unchanged here; Thread B owns the
  observer swap).
- pkg218 (`pkg218-spectral-colorimetry-fidelity.md`, Thread A is the source of this
  spec), pkg38/pkg195 (spectral profile system), pkg214/pkg214fix (sodium/mercury
  normalization — GATING dependency).
- Memory: `spectral-profile-edit-footguns`, `cpu-suites-autouse-cuda`.
