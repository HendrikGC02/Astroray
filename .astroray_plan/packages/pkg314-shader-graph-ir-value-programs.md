# pkg314 — Shader-graph IR and dynamic value programs (architecture Phases 1–2, #993, #992)

**Pillar:** 1
**Track:** A
**Status:** done — PR #1030, 2026-10-03: shader-graph IR + CPU/GPU graph interpreter + curves (#992); prod_wood CPU 4->7/16, GPU 3->7/16; curves GPU 2->3/16; production 16 pass / 22 xfail / 0 XPASS; corpus v2 604 pass / 94 xfail
**Estimated effort:** 3–5 sessions; one lead CUDA build per batch
**Depends on:** pkg219, pkg230, pkg277, pkg310

---

## Goal

Before: per-texel node chains compile to the bounded op-VM (`include/astroray/shader_vm.h`: 32 instructions,
8 slots, 2 pre-sampled textures, 2 ramps). The wood Roughness chain overflows the slot bound (#993), Float
Curve / RGB Curves are not represented (#992), and the GPU scalar path broadcasts one fetched input to every
program input.

After: the addon compiler emits a versioned, typed graph IR (CSE, last-use slot reuse, per-program resource
stats). Programs that do not fit the op-VM run as dynamic value programs: global arenas (instructions,
constants, tables, texture references) addressed by 32-bit per-program descriptors, executed by one shared
interpreter (CPU: per hit; GPU: a dedicated graph-evaluation kernel in its own translation unit with batched
global scratch). Texture instructions sample in-program, from computed coordinates where the coordinate chain
is compiled. Budgets are checked and fail with a DEGRADED report, never truncation.

---

## Context

Plan of record: `.astroray_plan/docs/shader-graph-architecture-2026-10-03.md` (option B, lead-approved
2026-10-03), Phases 1 and 2. Phases 3–4 (#990 #991 #995 #1005 #1006 services, closure contract) belong to
other lanes; lane N1 adds Light Path / Attribute / Object Info semantics, which must be re-hostable as IR
services. Fleet shade SASS must stay unchanged; the interpreter never inlines into `shadePathSlot`.

---

## Reference

- Design: `.astroray_plan/docs/shader-graph-architecture-2026-10-03.md`
- Curves: `.astroray_plan/docs/pkg314-curves-research.md` (Cycles `kernel/svm/ramp.h`, `blender/util.h`,
  `blender/shader.cpp`, Apache-2.0)
- Corpus: `.astroray_plan/docs/pkg310-production-corpus-burndown.md`

---

## Prerequisites

- [x] Architecture memo adopted (main f06f3564).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/shader_graph_ir.py` | IR builder (reuses the op-VM node handlers), CSE/DCE, last-use slot allocation, stats, v1 serialisation |
| `include/astroray/shader_graph.h` | Graph program format, budgets, shared HD interpreter over the op-VM opcode functions |
| `src/gpu/wavefront/stage_graph_eval.cu` | Dedicated graph-evaluation kernel + device binding (own TU) |
| `scripts/dev/shader_graph_ir_stats.py` | IR stats table over production + corpus v2 graphs (run in Blender) |
| `tests/test_pkg314_shader_graph_ir.py` | IR, allocator, CSE, budgets, curves, CPU value equivalence |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/shader_vm_compiler.py` | Curve handlers, depth limit from the builder |
| `blender_addon/__init__.py` | Route chains the op-VM rejects to graph programs |
| `include/astroray/shader_vm.h` | Table lookup (Cycles ramp/curve), binding fields for graph outputs |
| `include/advanced_features.h` | `GraphProgramTexture` (CPU twin) |
| `module/blender_module.cpp` | Bindings to create/inspect graph programs |
| `src/gpu/scene_upload.cu` | Upload graph arenas and per-material graph slots |
| `src/gpu/wavefront/stage_advance_device.cuh` | `HasProgram=true` shade reads graph outputs |
| `src/gpu/wavefront/stage_advance.cu` | Launch the graph kernel before shade when programs exist |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | Device buffers, scratch and output allocation |

### Key design decisions

See the architecture memo; lane-level choices are recorded in the PR body (STATE note) as they are made.

---

## Acceptance criteria

- [ ] IR stats table for every production + corpus v2 graph committed.
- [ ] Old-vs-new CPU/GPU value equivalence for op-VM-representable chains.
- [ ] Unit tests: >32 instructions, >2 textures, multiple mappings, repeated consumers, #993, curves.
- [ ] #993 wood Roughness compiles (no `VM_MAX_SLOTS` report); #992 curves on CPU and GPU.
- [ ] Fleet p0 REG 128 / STACK 432, fleet p1 198 unchanged; generic shade <= 255; build <= 1.3x.
- [ ] Production + corpus v2 suites run; passing strict xfails removed; contact sheets inspected.

---

## Non-goals

- Closure composition, Light Path, attributes, object info, bump footprints (Phases 3–4).
- NVRTC JIT.
- Per-hit GPU procedural evaluators (#1007 / PR #1023).

---

## Progress

- [ ] Phase 1: IR, passes, stats, equivalence.
- [ ] Phase 2: arenas, interpreter, CPU twin, GPU kernel, routing, #993, #992.

---

## Lessons

*(Fill in after the package is done.)*
