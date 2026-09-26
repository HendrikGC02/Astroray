# pkg293 — GPU Disney/Principled: per-hit lobe weights from Metallic/Roughness/Transmission programs, incl. inside Mix/Add shaders (#889)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h) + register audit
**Depends on:** pkg230, pkg219d

---

## Goal

Before: on the GPU a Metallic op-VM program (image or procedural) renders
byte-identical to the constant because closure-graph lobe weights are baked
from the constant at upload (pkg219d); Roughness/Metallic/IOR/Transmission
programs are dropped when the Principled BSDF sits inside a Mix/Add Shader;
the compiler ignores which procedural output (Fac vs Color) is wired.
`test_issue846` carries a strict xfail. After: lobe weights are recomputed
per hit from the evaluated scalar programs (via the pkg230 side-table
`GVec3`/scalar slots, `template<bool HasProgram>` gated), blend lowering
carries program slots, the Fac/Color output choice is honoured, the xfail
flips, and the shade kernel stays at REG 254 with STACK delta reported.

---

## Context

A textured Metallic map is the most common PBR asset pattern; on GPU it is
silently a constant. pkg284's `v2_textures_opvm` scene gates it. Register
pressure is the known risk (memory `closure-graph-lobe-count-spills-fused-kernel`,
`shade-axis-side-table-avoids-spill`), which is why this is an Opus lane
with a ptxas audit in the acceptance criteria.

---

## Evidence

- 2026-09-25 (#889): Metallic program → byte-identical to constant; degradation entry reported; `test_issue846` strict xfail.
- `include/astroray/gpu_materials.h:3009` comment: lobe weighting corrected for single-lobe graphs only.
- pkg230 (memory `op-VM utility opcodes`): shared HD `svm_eval`, `GVec3` slots, gated `<HasProgram=true>` — the mechanism to reuse.

---

## Reference

- Cycles `kernel/svm/closure.h` `svm_node_closure_bsdf` (Apache-2.0): metallic/roughness/transmission are read per hit from the stack and lobe weights computed there (`principled` mix of diffuse/metal/glass/clearcoat by `metallic`, `transmission`).
- Burley 2012/2015 lobe mixing: `(1−metallic)·(1−transmission)·diffuse + metallic·metal + (1−metallic)·transmission·glass`.
- `blender_addon/shader_vm_compiler.py` (`_compile_socket_value`, blend lowering), `include/astroray/gpu_materials.h` (closure-graph lowering), `src/gpu/wavefront/stage_advance.cu` shade kernels.
- Memory: `wavefront-shade-kernels-register-saturated`, `noinline-runtime-flag-avoids-shade-spill`, `pkg201-filter-glossy-alpha-site-sprawl`.

---

## Prerequisites

- [ ] Batch Y (#846 scalar programs) merged — yes (853d13b9).
- [ ] ptxas register report from the current main build saved for the A/B.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg293_gpu_lobe_programs.py` | Checker-driven Metallic (0/1 squares), Roughness gradient, Transmission mask, each alone and inside a Mix Shader with a Diffuse: GPU/CPU per-square mean within ±5 %; Fac vs Color output wiring gives different (and CPU-matching) results. Flips `test_issue846` xfail. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_materials.h` | `<HasProgram=true>` path: evaluate scalar programs for metallic/roughness/transmission/IOR at the hit, recompute lobe weights per Burley/Cycles before sampling/eval/pdf; constant path untouched (byte-identical kernels for `HasProgram=false`). |
| `src/gpu/scene_upload.cu` | Blend (Mix/Add) lowering carries per-branch program slots; upload the extra slots in the pkg230 side table. |
| `blender_addon/shader_vm_compiler.py` | Emit program slots for Principled sockets inside Mix/Add shader branches; honour the wired procedural output (Fac → scalar program, Color → `GVec3`). |
| `blender_addon/degradation.py` | Remove the Metallic-program degradation entry once fixed. |
| `tests/test_issue846_scalar_program_procedural.py` | xfail removed. |

### Key design decisions

- **Gated template, not a runtime branch**, so scenes without programs keep byte-identical shade kernels (pkg230 precedent).
- **Per-hit recompute only of the weights**, not of the closure graph topology: the lobes exist already; their mix factors become per-hit scalars.
- **Register budget rule:** if the `HasProgram=true` kernel spills (STACK > 0 beyond current), move the weight recompute behind the `__noinline__` runtime flag (memory `noinline-runtime-flag-avoids-shade-spill`) rather than shrinking scope.
- **Fac vs Color:** follow Cycles socket semantics — Fac is the scalar output (noise value / checker fac), Color is the RGB output; the compiler currently picks by node type.

---

## Acceptance criteria

- [ ] `test_pkg293_gpu_lobe_programs.py` green on the RTX 5070 Ti; `test_issue846` xfail removed and passing.
- [ ] ptxas: `HasProgram=false` shade kernels byte-identical (cuobjdump SASS hash); `HasProgram=true` REG ≤ 254, STACK delta reported in the PR.
- [ ] Corpus `v2_textures_opvm` Metallic/Roughness proof cards GPU/CPU within ±5 % (when pkg284 landed).
- [ ] Degradation report no longer lists Metallic programs.

---

## Non-goals

- No new op-VM opcodes; no procedural bake resolution changes (#890 is separate).
- No CPU changes (CPU already evaluates per hit).

---

## Progress

- [ ] Compiler slots + upload.
- [ ] Per-hit weights + register audit.
- [ ] Tests + xfail flip.

---

## Lessons

*(Fill in after the package is done.)*
