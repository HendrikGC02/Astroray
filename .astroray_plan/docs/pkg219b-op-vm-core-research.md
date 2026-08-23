# pkg219b — Bounded op-VM core: design + algorithm sourcing

Status: implementation reference (Claude, 2026-08-23)

## Algorithm sourcing (CLAUDE.md §6)

All per-texel node math is ported from the **Cycles SVM kernel**
(`intern/cycles/kernel/svm/*`, Apache-2.0), as enumerated and cross-checked in
`pkg219c-blender-node-opcode-semantics.md`. The VM *architecture* (flat
bytecode, per-node stack effect, baked Color-Ramp table) follows Cycles SVM
(`src/kernel/svm/svm.h`, `types.h`). Divergence from Cycles that is deliberate
and load-bearing:

- **Static stack bound.** Cycles' `SVM_STACK_SIZE = 255` float stack is
  dynamically sized and "overflows with relatively few nodes". On the REG:254
  wavefront shade kernel a 255-float local array spills catastrophically
  (memory `wavefront-shade-kernels-register-saturated`). pkg219b uses a
  **compile-time-bounded register file** of `VM_MAX_SLOTS` `GVec3` slots; the
  host compiler refuses (falls back to constant-fold + a visible degradation
  entry) any graph that exceeds the bound. Never a silent grey.

- **Opcodes carry pre-sampled inputs, the VM does not fetch textures.** The
  caller (CPU `ProgramTexture::value` / GPU shade path) samples the material's
  input textures into `inputs[]` and hands them to `svm_eval`. This keeps the
  evaluator pure and **byte-identical between CPU and GPU** (same HD function),
  so parity holds by construction rather than by re-derivation.

## Opcode set (pkg219b slice)

Cited to Cycles source in `shader_vm.h` inline. The 4 chains the coordinator
named map to:

| Opcode        | Cycles ref                              | Chain unblocked |
|---------------|------------------------------------------|-----------------|
| `OP_LOAD_TEX` | (input plumbing)                         | all             |
| `OP_LOAD_CONST`| `svm/value.h` NODE_VALUE_F/_V           | all             |
| `OP_MATH`     | `svm/math_util.h` `svm_math`             | Math→roughness  |
| `OP_MIX`      | `svm/color_util.h` `svm_mix`             | MixRGB          |
| `OP_RAMP`     | `svm/ramp.h` `rgb_ramp_lookup` (baked)   | Color Ramp      |
| `OP_MAP_RANGE`| `svm/map_range.h` `svm_node_map_range`   | Map Range       |

`OP_MATH` / `OP_MIX` / `OP_MAP_RANGE` carry an enum immediate; pkg219b ships the
common enum subset from the opcode-semantics doc §Summary-A, pkg219c fills the
rest.

## Design decisions (documented, bounded scope)

1. **`ProgramTexture` wraps the chain.** A new `Texture` subclass holds up to
   `VM_MAX_TEX` child textures + a `ShaderVMProgram`. `TexturedLambertian` holds
   it as its texture, so the existing one-texture-per-material CPU/GPU binding is
   reused unchanged for CPU. CPU supports N child textures (Mix of two textures
   works fully on CPU).

2. **GPU scope = single ImageTexture child.** `scene_upload.cu` detects a
   `ProgramTexture` whose inputs are a single `ImageTexture` (the literal repro:
   Color Ramp / Math / Map Range / Mix-with-constant on one image) and uploads
   the image + the program. Multi-image-child programs on GPU fall back to the
   pkg190 bake (resolution-limited) with a degradation entry — deferred to a
   follow-up. This keeps the GPU register probe focused on the highest-value,
   most-broken chain and the binding a single `texId`.

3. **GPU VM output = per-texel BASE COLOR.** The VM's final slot is an RGB that
   replaces `texColor` in the existing shade-path albedo fold
   (`throughput *= texUp/baseUp`). Scalar-to-non-color-socket chains
   (Math→Roughness) are fully supported on CPU; on GPU they are deferred (the
   closure params are evaluated deeper in the register-saturated kernel).

4. **`template<bool HasProgram>` 6th shade axis, program in GLOBAL memory.**
   Following pkg186/197/198/199: a `__constant__` binding carries the pointer to
   a device global `ShaderVMProgram[]` + a per-material program-index array. The
   `<false>` specialization (every fleet material) compiles the VM out entirely →
   byte-identical. Selected at runtime alongside `HasLightPassAOVs` (pkg198
   pattern) so the P/T/Ph/D switch stays legible.

## Static limits (shader_vm.h)

`VM_MAX_INSTR=32`, `VM_MAX_SLOTS=8`, `VM_MAX_CONST=16`, `VM_MAX_TEX=2`,
`RAMP_TABLE_SIZE=256`, `VM_MAX_RAMPS=2`. Program is a POD (trivially copyable to
a device buffer).
</content>
</invoke>
