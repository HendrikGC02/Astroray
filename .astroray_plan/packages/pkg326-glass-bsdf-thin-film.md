# pkg326 — Glass BSDF Thin Film sockets (#1136)

**Pillar:** 1
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h) + GPU legs via the lead
**Depends on:** none

---

## Goal

Before: the Glass BSDF's `Thin Film Thickness` and `Thin Film IOR` sockets are a reported drop
(#1136, pkg321): the addon warns and renders plain glass. After: the Glass BSDF routes those sockets
through the same thin-film path the Principled BSDF already uses (APPROXIMATED rows), on CPU and GPU;
the matrix rows flip to APPROXIMATED/SUPPORTED, the DegradationReport entry goes away, and a soap
bubble built from the Glass node shows interference colours that match the Principled build within
the MC band.

---

## Context

Cycles added thin film to the Glass BSDF alongside the Principled BSDF; Astroray ported only the
Principled side (pkg182 conductor path, pkg178). The spectral showcase (pkg324) wants bubbles and
coated glass from the plain Glass node, and the competitor galleries lead with exactly that image.
Small, well-bounded, one node.

---

## Evidence

- 2026-10-18: pkg321 probes `g_thin_film_thickness` / `g_thin_film_ior` leave the CPU render identical (reported drop, #1136).

---

## Reference

- Cycles 5.2 `kernel/closure/bsdf_microfacet.h` thin-film Fresnel (F82 / dielectric thin layer) and `shader/nodes/glass_bsdf` socket plumbing
- Astroray Principled thin film: `src/materials/principled*.cpp`, GPU closure lowering (`gpu_dielectric_lowers_to_closure_graph` memory)
- Belcour & Barla 2017 (the model); cite file:line in code per CLAUDE.md §6

---

## Prerequisites

- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg326_glass_thin_film.py` | Glass vs Principled bubble within band (CPU, GPU); zero-thickness Glass equals plain glass to 1e-6; report entry gone |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | export the two sockets for `ShaderNodeBsdfGlass` into the glass material; drop the DegradationReport entry |
| `include/astroray/material_closure.h` | CPU glass closure: apply `thin_film_fresnel.h` (the Principled path) when thickness > 0 |
| `src/gpu/scene_upload.cu` | GPU: upload the glass material's thin-film thickness/IOR into the same closure parameters the Principled closure uses (`gpu_thin_film_table.cu` stays shared) |
| `docs/blender_parity/coverage_matrix.json` | regenerate on Blender 5.2 (with `report.md`) |
| `benchmarks/reference_corpus/scenes/proof_pending.json` | if the frozen corpus still gap-cards the rows, register them proof-pending (pkg320 pattern, with the test baseline) |

### Key design decisions

- Reuse, do not re-derive: the Principled thin-film code path is the implementation; Glass only plumbs sockets into it.
- The GPU side must not add a template axis; if the glass closure needs a flag, use the existing closure-graph parameters.

---

## Acceptance criteria

- [ ] `tests/test_pkg326_glass_thin_film.py` green on CPU and GPU.
- [ ] Matrix rows `ShaderNodeBsdfGlass|input:Thin Film Thickness/IOR` no longer DROPPED-SILENT; #1136 closed by the PR.
- [ ] cuobjdump: no shade-kernel REG/STACK regression beyond ±16 B.

---

## Non-goals

- Do not touch the Principled thin-film model itself.
- Do not add dispersion to thin film.

---

## Progress

- [ ] Addon export + CPU
- [ ] GPU lowering + BUILD REQUEST
- [ ] Matrix regen + tests

---

## Lessons

*(Fill in after the package is done.)*
