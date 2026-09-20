# pkg277 — Coordinate-side op-VM programs for procedural textures (#822)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 1–2 sessions (~5 h) + one CUDA build
**Depends on:** pkg190, pkg219, pkg230b

---

## Goal

Before: a non-affine chain on a procedural's Vector input (`Texture Coordinate ->
Separate XYZ -> Math(Sin) -> Combine XYZ -> Noise`) is warned and dropped on both
backends. After: the CPU evaluates the warped coordinate exactly per shade, and the
GPU renders it through the existing pkg190 bake, with no shade-kernel change.

---

## Context

Filed from #818 / PR #821 as #822. The batch R design note chose option B (CPU
coordinate-program wrapper + GPU bake) over native HD procedural ports: zero device
code, reuses the Cycles-cited CPU evaluators, fits the REG:254 shade-kernel budget
by construction. Serves Pillar 5 Blender shader-node coverage (integration-first
directive).

---

## Evidence

- 2026-09-20: `HasProgram=true` shade kernels REG 254, STACK 4512–8736 B on build 0f4f62d1; option B adds no device code (design note).
- 2026-09-20: 64³ bake of a sin-warped checker: pixel mismatch 4–26 % for warp frequency k = 2–24, region-mean error ≤ 0.6 % (design note table).

---

## Reference

- Design note: `.astroray_plan/docs/issue822-coordinate-side-opvm-design.md`
- op-VM evaluator + Cycles citations: `include/astroray/shader_vm.h` (`svm/math_util.h`, `svm/color_util.h`, Apache-2.0)
- Bake: `src/gpu/scene_upload.cu` `bakeProceduralTexId` (pkg190, pkg242)

---

## Prerequisites

- [ ] PR #844 (#825/#826 multi-input GPU program inputs) merged — the work pkg277 extends (tracked here, not in `Depends on`, which is a package-spec list).
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg277_coordinate_program.py` | compiler, CPU-exactness, GPU parity and degradation tests |

### Files to modify

| File | What changes |
|---|---|
| `include/advanced_features.h` | `CoordProgramTexture`: child Texture + coordinate `ShaderVMProgram`; `value(uv,p)`: `p' = svm_eval(prog, {p})`, return `child->value(p'.xy, p')` |
| `module/blender_module.cpp` | binding to create the wrapper (name, child, coord mode) and set its coordinate program |
| `blender_addon/shader_vm_compiler.py` | coordinate leaf (Texture Coordinate / UV Map output -> `OP_LOAD_TEX 0`); `SEPXYZ` -> `OP_SEP_COLOR` (RGB); `COMBXYZ` -> `OP_COMBINE_COLOR` (RGB); scalar Math `SINE/COSINE/TANGENT` -> `OP_VEC_MATH` on the broadcast scalar |
| `blender_addon/__init__.py` | when a procedural's Vector chain is non-affine, compile it and wrap the procedural in the new texture (direct base colour and op-VM input paths); affine chains keep `_resolve_affine_coordinates` |

### Key design decisions

- No device code. The wrapper is a `Texture`, so `bakeProceduralTexId` bakes `wrapper->value()` over UV / Generated exactly like any procedural; direct and op-VM-input uses both work unchanged.
- No `svm_eval` change: every opcode needed exists; the fleet and `HasProgram=true` kernels stay byte-identical (still measured).
- Base coordinate provenance: UV / Generated bake; Object / Camera / Window / Normal / Reflection stay CPU-exact with the existing "GPU skips the program" degradation.
- Bake resolution: default 64³ (pkg190 convention). 128³ halves pixel mismatch at 8× memory (25 MB per 128³ texture); leave as a follow-up unless owner asks.
- Mapping × warp ordering: when a Mapping node is combined with a non-affine warp, Mapping is applied to the base coordinate first (affine, via `_resolve_affine_coordinates`), then the coordinate program warps the mapped point. CPU and GPU must apply the same ordering — the CPU evaluates the mapped-then-warped point per shade, and the GPU bake must be of that same mapped-then-warped field so the wrapper's baked value agrees with `wrapper->value()`.

---

## Acceptance criteria

- [ ] CPU render of `Generated -> Separate XYZ -> Math(Sin) -> Combine XYZ -> Checker` matches a numpy reference of the same field (Cycles `svm/checker.h` formula) per pixel, excluding a 1-px band at cell edges.
- [ ] GPU/CPU per-channel region-mean ratio within 3 % at 256 spp for the same scene and for a warped Noise.
- [ ] Per-pixel gate (the 64³ bake is the limiting factor, so the region-mean ratio alone does not catch the 4–26 % edge mismatch): at the 64³ bake resolution, the fraction of pixels whose per-channel |Astroray_GPU − Astroray_CPU| exceeds 0.01 must be ≤ 26 % for the sin-warped Checker (worst case, k = 24) and ≤ the same bound for the warped Noise.
- [ ] Mapping + non-affine warp: CPU and GPU both apply Mapping before the warp; verified against a numpy reference with a Mapping node present.
- [ ] `cuobjdump --dump-resource-usage`: 0 functions changed vs main.
- [ ] Non-affine chain with an Object base coordinate: CPU exact, degradation entry recorded.
- [ ] Addon path contact sheet (Cycles CPU | Astroray CPU | Astroray GPU) inspected.

---

## Non-goals

- Do not port procedural evaluators to HD / the shade kernel (option A).
- Do not add opcodes or change `svm_eval`.
- Do not change bake resolution or filtering (pkg190 parity coupling).
- Do not support arcsin/sinh/exp/log etc. scalar Math ops; warn and drop as today.

---

## Progress

- [ ] Wrapper class + binding
- [ ] Compiler leaf + nodes
- [ ] Addon wiring
- [ ] Tests + build + REG gate + GPU parity + contact sheet

---

## Lessons
