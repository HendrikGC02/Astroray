# pkg310 — Production node-tree corpus + silent-degradation audit + gap burn-down backlog

**Pillar:** 5
**Track:** A
**Status:** done (PR #999, 2026-09-30 - baseline CPU 0/8, GPU 0/8, 39 strict silent pairs (~7 real), 9 issues filed #988-#996; acceptance item "contact sheet inspected (Opus)" still OPEN: lane-inspected only, Opus sign-off pending)
**Estimated effort:** 2–3 sessions (~8 h): scenes + Cycles refs ~4 h, walker + audit ~2 h, runs + backlog ~2 h
**Depends on:** pkg278, pkg284

---

## Goal

Before: shader-node support is measured only as socket breadth (gate (b),
still UNMEASURED). Nobody has rendered a realistic production node tree
against Cycles, and a node with no handler can vanish without a warning.
After: eight representative production materials exist as `.blend` scenes
with Cycles references and MC bands. One command reports, per material and
backend (CPU, GPU): in band or not, every exercised (node, socket) pair, and
every **silent** degradation. The result is a ranked backlog of GitHub
issues, each naming the materials it unblocks. That backlog is the theme-1
burn-down (`product-themes-plan-2026-09-29.md` §1).

---

## Context

Owner 2026-09-29: "Astroray is still not equipped to handle complex shader
node setups — one of the larger hurdles to something actually practical."
Code reading finds no addon handler for Attribute, Color Attribute, Geometry,
Layer Weight, Fresnel, Object Info or Light Path. The op-VM is capped at 32
instructions and 2 textures, Add Shader(BSDF, BSDF) keeps only the first, and
13 issues are open (#881 #890 #891 #944 #945 #954–#957 #962 #965 #966). This
package measures before anything is fixed, so that the P3/P4 architecture
decision (bounded op-VM versus an SVM-shaped per-hit graph) rests on counts.
Sonnet 5.5 lane, Terra review, Opus visual sign-off on the contact sheet.

---

## Evidence

- 2026-09-29: `grep ATTRIBUTE|VERTEX_COLOR|LIGHT_PATH|LAYER_WEIGHT|FRESNEL blender_addon/shader_vm_compiler.py blender_addon/__init__.py` → no matches.
- 2026-09-29: `include/astroray/shader_vm.h:31-36` `VM_MAX_INSTR=32`, `VM_MAX_SLOTS=8`, `VM_MAX_TEX=2`, `VM_MAX_RAMPS=2`.
- 2026-09-29: `docs/blender_parity/acceptance_manifest.json` row b `status: unmeasured`.

---

## Reference

- Plan: `.astroray_plan/docs/product-themes-plan-2026-09-29.md` §1.
- Harness to extend (do not fork): `benchmarks/reference_corpus/build_corpus.py`, `mc_tolerance.py`, `gates_v2.toml`, `provisional_v2.toml`, `tests/test_corpus_v2_parity.py` (pkg284); `benchmarks/reference_corpus/coverage_report.py --collect` (pkg278 scene-used reachability); `blender_addon/degradation.py` (`DegradationReport`).
- Coverage history: `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md` (pkg229).
- Textures: procedurally generated images, or Poly Haven CC0 image sets (record the source URL and licence in the manifest).
- Memory notes: `ssim-wrong-gate-for-independent-rng`, `roi-mean-over-specular-highlight-artefact`, `mc-noise-vs-deterministic`, `corpus-scenes-replaceable`.

---

## Prerequisites

- [x] pkg284 Phase 2 on main (`test_corpus_v2_parity.py`, MC-band tooling).
- [x] Blender 5.2 headless available (`blender-5-1-installed-locally`); a current `build_cuda` + staged addon for the GPU leg.
- [x] `python scripts/project_index.py query "corpus"` and `scripts/README.md` read; no new harness script where a flag suffices.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/production/README.md` | The eight materials, what each exercises, the texture sources and licences |
| `benchmarks/reference_corpus/gates_production.toml` | Per (scene, backend, ROI, channel) MC bands, same schema as `gates_v2.toml` |
| `benchmarks/reference_corpus/silent_drop_audit.py` | Diffs exercised (node, socket) pairs from `coverage_report.py --collect` against the export's `DegradationReport`; lists silent drops |
| `tests/test_production_corpus.py` | Parametrised CPU/GPU parity + silent-drop assertions; failures `xfail(strict=True)` tied to an issue number |
| `.astroray_plan/docs/pkg310-production-corpus-burndown.md` | Baseline N/8 table, silent-drop list, ranked backlog with issue links |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/reference_corpus/build_corpus.py` | Builders for the eight `prod_*` scenes (one family entry each) |
| `benchmarks/reference_corpus/mc_tolerance.py` | Accept `--gates gates_production.toml` if it does not already take a gates path |
| `scripts/README.md` | Register `silent_drop_audit.py` |

### Key design decisions

**The eight materials.** Each is one object on a neutral stage with a
sun + area lamp + HDRI, and each has 2–4 ROIs on the textured regions:

1. `prod_car_paint`: Principled with coat; Voronoi-driven flake normal; Layer Weight/Fresnel mixing base and flake tint.
2. `prod_wood`: Wave + Noise → Color Ramp → base colour and roughness; the same chain → Bump.
3. `prod_marble`: Noise → Vector Math warp → Wave → Color Ramp; Mapping after the warp.
4. `prod_pbr_group`: 4 images (base, roughness, metallic, normal) inside a node group; Mapping; Normal Map chained with Bump.
5. `prod_shader_stack`: Mix(Mix(Principled metal, Principled paint, Noise mask), Glass, Fac) + Add Emission; at least 3 levels deep.
6. `prod_attributes`: Color Attribute → base colour; Attribute (custom float) → roughness; Object Info Random → hue on 3 instances.
7. `prod_light_path`: Is Camera Ray hides an emitter from camera; Is Shadow Ray makes glass shadow-transparent (the classic trick); Ray Length tint.
8. `prod_curves_geometry`: RGB Curves + Float Curve + Map Range + Math chain; Geometry Backfacing and Pointiness → Mix.

**Scoring.**
- Per material and backend, PASS means every non-provisional ROI channel sits
  inside the pkg284-style MC band (5 seeds, adaptive off, seed ≠ 0) **and**
  the silent-drop list is empty.
- Report N/8 per backend.
- Do not use SSIM for independent RNG (memory note); use ROI means with the
  bands, plus a visual contact sheet (Astroray CPU | GPU | Cycles) inspected
  by Opus.

**Silent-drop definition.** An exercised (node type, socket) pair that is not
SUPPORTED in the frozen coverage manifest and does not appear in the render's
`DegradationReport`. Exercised means reachable from the active output with a
non-default value or a link, per pkg278's reachability rules.

**Backlog.**
- One issue per root cause, not per material.
- Each issue records: materials unblocked, category (per-hit input /
  op-VM bound / closure composition / pattern fidelity / GPU-only / addon
  export), backend, and a named observable with a threshold.
- Existing issues are linked, not duplicated.
- Rank by materials unblocked, then by P-phase (plan §1).
- The count of "op-VM bound" versus "closure composition" failures is the
  input to the P4 fork note.

**Failures are data.** Tests for failing materials are
`xfail(strict=True, reason="#NNN")` so the future fix PR must un-xfail them
(memory `xfail-gated-features-must-unxfail`). Treat a surprising number as
possibly a scene or reference defect first (CLAUDE.md §5c).

---

## Acceptance criteria

- [x] 8 `prod_*.blend` scenes + Cycles references + `gates_production.toml`, rebuilt from `build_corpus.py` (structurally identical; Blender 5.2 `.blend` bytes are not reproducible, manifest SHAs pin the committed files).
- [x] `pytest tests/test_production_corpus.py` runs both backends (GPU legs under the GPU lock); every non-passing material is a strict xfail with an issue number.
- [x] `silent_drop_audit.py` lists silent drops per material. It is proven non-vacuous by a fixture material with a deliberately unhandled node that it flags.
- [x] Burn-down doc: baseline N/8 on CPU and on GPU, the silent-drop list, a ranked backlog of issues, and the bound-versus-closure failure count.
- [ ] Contact sheet saved (as `test_results/textures-nodes/production-corpus/`, layout guard forbids `pkg310/`) and inspected (Opus), with the verdict in the burn-down doc. Saved and lane-inspected; **Opus sign-off pending**.
- [x] `scripts/README.md` updated; `python scripts/project_index.py lint` clean.

---

## Non-goals

- Do not fix any rendering gap here; file it.
- Do not change the op-VM, the compiler, or GPU code.
- Do not alter gate (b) scoring or the pkg278 frozen manifest.
- Do not fork the pkg284 harness.

---

## Progress

- [x] Scene builders + Cycles references
- [x] Silent-drop audit + fixture
- [x] CPU/GPU runs, bands, contact sheet
- [x] Backlog issues + burn-down doc

---

## Lessons

* Blender 5.2 `.blend` files are zstd-compressed and not byte-reproducible (true of every corpus scene), so "bit-identical rebuild" became "manifest SHA pins the committed file + structural-identity test".
* `test_results/pkg310/` is not a valid layout path (banned token); evidence lives in `test_results/textures-nodes/production-corpus/`.
* The frozen coverage matrix is too coarse for a strict silent-drop gate (#996): 32 of the 39 strict hits are stale rows. Fix the matrix before promoting the audit to a merge gate.
* Bands: use decorrelated seeds (#986), not 278-282.
