# pkg219 — Per-texel shader-graph evaluator research note

**Date:** 2026-08-23
**Author:** architect planning pass (goal-capture).
**Policy:** [CLAUDE.md §6](../../CLAUDE.md) — architecture reference is Cycles SVM
(Apache-2.0); design borrow, not code mirror. `cite-algorithm` runs at dispatch.
**Builds on:** [`blender-shader-nodes-research.md`](blender-shader-nodes-research.md)
(custom-node UX — orthogonal; that note is about node *authoring*, this is about
node-tree *evaluation*).

---

## Problem restated (grounded)

The addon **constant-folds** the Blender node tree
(`blender_addon/__init__.py::convert_shader_node`, ~L2700+). Any node needing
per-shading-point evaluation *downstream of a texture* silently degrades to a
constant/grey (memory `addon-constant-folds-shader-graph`). Confirmed broken:
`VALTORGB`/Color-Ramp on a texture (L2772 — `evaluate(fac)` on a single constant
returns `None` → grey), MixRGB/Math/MapRange/HSV/Invert/Gamma/Separate-Combine on
a texture, full 3-D `MAPPING` (L2961, only Z-rotation kept), non-UV `TEX_COORD`
(L2993, Camera/Window/Reflection/Normal → UV fallback).

## Reference architecture: Cycles SVM

Cycles' default shader system is **SVM** (Shader Virtual Machine): the node tree is
compiled to a **bytecode stream of `uint4` instructions** stored in a 1-D texture;
`svm_eval_nodes` is a templated GPU kernel that walks the stream with a node
counter and a **float stack** holding intermediate socket values (GitHub
`blender/cycles/src/kernel/svm/svm.h`, Apache-2.0). OSL is the alternative (JIT,
CPU-strong, heavier). Two facts that drive the Astroray design:

- **The stack is the bottleneck, not the opcode count.** Cycles has repeated
  reports of "SVM stack full with relatively few nodes" (#117706, T46872) and the
  stack is what "breaks LLVM optimization in many ways." On a GPU wavefront pinned
  at REG:254 (memory `wavefront-shade-kernels-register-saturated`), an *unbounded*
  per-shading-point float stack is exactly the spill risk we cannot take inline.
- **Half-baked bytecode** (compile on build server, specialize per scene) is a
  Cycles perf trick we do **not** need — Astroray compiles the tree host-side per
  material at scene-upload, which is fine.

## The fork — decision

The spec's three options were (a) full SVM/OSL evaluator, (b) incremental
special-casing, (c) hybrid op-VM. **Decision: (c), staged, as the path to (a).**

Rationale:
- (b) is the "reinvent the wheel 100 times" anti-pattern the owner explicitly
  rejected. Off the table except as throwaway.
- (a) full-SVM is correct but XL and register-hostile if done as one inline GPU
  interpreter. Doing it in one shot risks the REG:254 spill with no incremental
  value delivered.
- (c) delivers most of (a)'s real-world coverage (the broken chains above are all
  **scalar/colour ops on ≤4-wide values**) with a **bounded** op-VM, and the same
  bytecode format extends to full (a) later. It is a strict prefix of (a).

**Concrete (c) design:**
1. **Bytecode format = a small `uint4` op stream per material**, Cycles-shaped, so
   it is forward-compatible with (a). ~20 opcodes cover the confirmed-broken set:
   `TEX_IMAGE`, `TEX_COORD` (UV/Generated/Object/Camera/Window), `MAPPING` (full
   3-D loc/rot/scale matrix), `COLOR_RAMP`, `MIX`/`MIX_COLOR`, `MATH`, `MAP_RANGE`,
   `HSV`, `INVERT`, `GAMMA`, `BRIGHT_CONTRAST`, `SEPARATE_COLOR`, `COMBINE_COLOR`,
   `BUMP`, `NORMAL_MAP`, plus load/store-constant.
2. **Bounded stack.** Cap the value stack at a compile-time small N (e.g. 8×float4)
   and *statically verify at compile time* that the compiled program fits — if a
   material overflows, emit a **visible degradation entry** (reuse the existing
   `_degradation_report` mechanism) and fall back to constant-fold for that
   material. This keeps the GPU register budget provable, unlike Cycles' dynamic
   stack. This is the single most important design constraint.
3. **One evaluator, two backends:** a CPU evaluator and a GPU device function that
   walk the same bytecode. Keep the GPU evaluator in a **separate device function**
   invoked from the shade stage only for materials with a non-trivial program;
   pure-constant materials keep the current fast path (no VM). Template
   `<bool HasProgram>` isolation so non-VM scenes see zero register change (memory
   `closure-graph-lobe-count-spills-the-fused-kernel`).
4. **Unify the coordinate path regardless of fork** (spec item 3): full 3-D
   Mapping incl. X/Y rotation, real Generated/Object/Camera/Window coords. This is
   needed even for constant-folded materials and is a clean first sub-package.

## Recommended staging (so value lands incrementally, register budget stays proven)

- **pkg219a — Coordinate + Mapping unification** (M, no VM yet): full 3-D Mapping
  matrix + real TexCoord outputs, wired into the existing texture special-case.
  Fixes the "mapping only partly applied" half of the repro. Deliverable on its own.
- **pkg219b — Bounded op-VM core** (L): the `uint4` bytecode compiler (Blender
  tree → op stream, host-side), the CPU evaluator, the GPU device evaluator with
  the static stack-bound check + degradation fallback. Ship with the Color-Ramp,
  Mix, Math, MapRange opcodes — the highest-frequency broken chains.
- **pkg219c — Opcode coverage fill-out** (M): HSV/Invert/Gamma/BrightContrast/
  Separate-Combine/Bump/NormalMap, each with a Cycles parity render.
- **(a) full-SVM** stays a *future* option; (c)'s bytecode is its on-ramp. Do not
  file (a) now.

## Effort / risk
- **Effort:** L–XL total, but **decomposable** — 219a alone is M and independently
  useful. That decomposition is the main win of this planning pass.
- **Top risk:** GPU register/stack budget. Mitigation = static compile-time stack
  bound + separate device function + `<bool HasProgram>` template + a REG probe
  gate identical to pkg198/pkg199. If a program can't be proven-bounded, it falls
  back to constant-fold with a visible degradation entry — never a silent grey.
- **Second risk:** Cycles parity of individual ops (Color Ramp interpolation
  modes, Mix blend types, Math operations). Mirror Cycles' `svm_*` semantics
  op-by-op; each opcode gets a parity render in the acceptance matrix.

## Citations to lock at dispatch
- Cycles SVM: `blender/cycles/src/kernel/svm/svm.h` + `svm/*` (Apache-2.0;
  architecture + per-op semantics reference, not mirrored).
- Cycles SVM stack-budget lessons: T46872 (stack optimization), #117706 (stack
  full with few nodes) — motivate the bounded-stack design.
- OSL (alternative, rejected for GPU-wavefront weight): documented for the record.
