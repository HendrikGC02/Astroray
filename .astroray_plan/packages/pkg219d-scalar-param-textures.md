# pkg219d — Scalar parameter textures (op-VM → roughness/metallic/etc.)

**Pillar:** 5 (Blender/DCC integration — shader-node compatibility)
**Track:** A (engine + addon; CPU + GPU BSDF eval)
**Status:** DONE 2026-09-03 — built + register-probed + HW-verified by the parent.
Fleet `stageShadeBucketedKernel<0,0,0,0,0,0,0>` measured **byte-identical** to
baseline (REG:254/STACK:3368/CONSTANT[0]:1716) from the linked `.pyd` — the
`<HasProgram=false>` fleet paid nothing (the `if constexpr` + empty
`GScalarOverride<false>` + collapsed pointer-indirection held). `tests/
test_pkg219d_scalar_param_textures.py` 3/3 on the RTX box (CPU + GPU roughness
per-half reproduction + CPU/GPU mean-ratio parity); 297 disney/material/hair
regression tests pass. Merged as PR #674 (CI green, cpp-abi-guard APPROVE).
**Addon path verified 2026-09-03:** clean-rebuilt `build_blender_addon_cuda`
(the mid-class vtable insertion needs `--clean`, per cpp-abi-guard +
`incremental-build-signature-staleness`) then a headless-Blender smoke — the
addon registers (vtable sound) and renders a `TexImage→MapRange→Roughness`
node-chain Principled material end-to-end. Known-bounded: metallic/transmission
GPU parity is approximate (closure lobe-MIX baked at upload); roughness/IOR
exact. — **fork DECIDED 2026-09-02 (architect), CPU-model pinned 2026-09-03
(parent).** Was "architect to detail before dispatch"; the design pass below resolves it. Route: dv4/deepseek implements to the decided design, HARD `cuobjdump` probe + `cpp-abi-guard` + Claude-last-line review before merge — same routing shape as pkg223 (PR #647). Filed 2026-08-31 — residual surfaced by the pkg219 completion audit, PR #661.
**Estimated effort:** M–L (extends a proven side-table pattern; the GPU register probe is the only Claude-last-line step).
**Depends on:** pkg219a/b/c (op-VM evaluator, all landed) — the machinery already exists; this only wires its output into non-base-color BSDF inputs.

## Finding (grounded, from the pkg219 audit)

The per-texel op-VM shader-graph evaluator (pkg219a/b/c) is functionally complete
and general, BUT the op-VM **program texture is attached only to Base Color**
(`get_base_color_texture` in the addon), and the engine material carries only
`base_color_texture` / `normal_map_texture` / `bump_map_texture`. There is **no
per-texel scalar parameter-texture input** for roughness / metallic / etc.:
`roughness` reads a constant-folded float via `get_float_input`. So a Blender graph
like `Image → Map Range → Roughness` cannot per-texel-drive roughness even though
the op-VM can already evaluate `image → MapRange → scalar`; there is simply nowhere
in the BSDF to plug the result. (This is the one unmet row of the original pkg219
acceptance matrix: "Math/MapRange driving roughness.")

## Architect design pass (2026-09-02) — fork resolved

The report framed this as an undecided fork: "new `GMaterial` scalar-param-texture
field vs a side-table." **It is not a real fork — the side-table wins by precedent,
and the base-color program already lives there.** Grounded in the live code:

- The op-VM already rides a `__constant__` side-table, NOT `GMaterial`:
  `GWavefrontProgramBinding { const ShaderVMProgram* programs; const int* matProgId; }`
  (`include/astroray/shader_vm.h:390-393`), published once per frame via
  `setWavefrontProgramBinding` and read only inside `if constexpr (HasProgram)`
  (`src/gpu/wavefront/stage_advance.cu:1249-1259`). `matProgId[mat] == -1` for every
  non-program material, so the entire `<HasProgram=false>` fleet compiles the VM out —
  byte-identical to main.
- A `GMaterial` field is the anti-pattern the fleet explicitly avoids (memory
  `shade-axis-side-table-avoids-spill`, `pkg114`-era 640 B struct is register-adjacent).
  **Decision: extend the existing `c_wfProgBinding` side-table. Do NOT touch `GMaterial`.**

**Decided representation (the one sub-fork that was real — N parallel arrays vs a
flattened slot table):** use a **flattened per-(material, slot) table**, fixed small
`K`. Start `K = 4`: `{ROUGHNESS, METALLIC, TRANSMISSION, IOR}` — the highest-value
scalar BSDF inputs; specular/sheen/clearcoat/etc. deferred (add slots later, same
shape, no re-architecture). Extend the binding to:

```
struct GWavefrontProgramBinding {
    const ShaderVMProgram* programs;          // unchanged: device global array
    const int*             matProgId;         // unchanged: base-color program (-1=none)
    const int*             matScalarProgId;   // NEW: [mat*K + slot] program idx (-1=none)
    const int*             matScalarTexId;    // NEW: [mat*K + slot] source-image id (-1=none)
};
```
Two new `const int*` in the constant binding (not per-launch args), one scene-upload
pair, one eval loop. `matScalarTexId` is required because a roughness program's input
texel is a *different* image than the base-color map (the current single program feeds
`vmIn[0] = texColor`, the base-color texel — a scalar program must fetch its OWN map).

**GPU eval (inside the existing `if constexpr (HasProgram)` block, after the base-color
swap, `stage_advance.cu` ~:1260):** loop `slot = 0..K-1`; if `matScalarProgId[mat*K+slot] >= 0`,
fetch that slot's source texel, run `svm_eval` into a **single reused `vmIn` scratch**
(eval slot, extract `.x`, reuse the scratch for the next slot — keep live state to one
float result at a time), and write the result into the local roughness/metallic/etc.
BEFORE the BSDF/NEE closure is built. Register discipline: the ON-path is
`HasProgram=true`, which is **already an isolated axis** (not the fleet) — so the fleet
`<HasProgram=false>` stays byte-identical by `if constexpr` construction. The register
risk here is therefore LOWER than the report implied: it is confined to the
already-isolated program specialization, NOT the shared REG:254 fleet kernel.

**MANDATORY probe (Claude-last-line, before merge):** (1) fleet `stageShadeBucketedKernel<0,…>`
`<HasProgram=false>` byte-identical to baseline REG 254 / STACK 3368 / CONSTANT[0] 1716
(measure from the actual `.pyd`); (2) `<HasProgram=true>` still compiles and doesn't
tank program-material perf. Spill on (2) is acceptable-if-bounded (program materials are
rare); spill on (1) is impossible-by-construction and, if observed, means the
`if constexpr` was breached — stop and escalate.

**Two gates the implementer MUST wire (grounded, cost real rebuilds before):**
- **UV-upload gate** (memory `uv-upload-gate-needs-new-normal-perturb-consumers`):
  `scene_upload` only sets `GTriangle.hasUV` for aniso/image/normal/bump-mapped
  materials. A material whose ONLY texture is a roughness/metallic map would ship
  **UV-less**, and the scalar program's texel fetch would read garbage. Add scalar-param
  textures to that `hasUV` predicate — verify a scalar-only material actually gets UVs.
- **CPU mirror:** the CPU BSDF eval reads roughness/metallic via the constant
  `get_float_input` path; mirror the op-VM scalar substitution there so CPU↔GPU parity
  holds (the byte-mirror convention).

## CPU-model design pass (parent, 2026-09-03) — injection point pinned

The architect's design pinned the GPU side-table but left the CPU injection point
open. Grounded decision: the addon creates the **`disney` material**
(`plugins/materials/disney.cpp`, DisneyPlugin) for a Blender Principled node
(confirmed: `blender_addon/__init__.py` create_material('disney', …)), and **no
CPU material reads a scalar texture today** — so this is genuinely new.

**Decision: give DisneyPlugin up to K optional `std::shared_ptr<ProgramTexture>`
scalar members (roughness/metallic/transmission/ior). In eval/pdf/sample, if a
slot's program is set, `svm_eval` it at the hit UV (`rec.uv`, the same texel the
base color uses) and substitute for the constant member, recomputing GGX alpha
etc. locally per-hit.** Self-contained — NO integrator change, NO HitRecord
field (unlike normal maps, which needed a decorator; a scalar program is just a
per-hit float substitution the material can do itself). The addon attaches them
via new createMaterial params (`roughness_program` etc., resolved through
`textureManager.getTexture`), mirroring the base-color attach. GPU mirrors the
same substituted VALUES via the side-table above (storage differs — CPU on the
material, GPU in `c_wfProgBinding` — but the numeric result is byte-identical:
same `svm_eval`, same source texel). Dispatched to a fresh implementer
2026-09-03 behind the standard REG-probe + Claude-review gate.

## Scope (design decided above; implement to it)

- **Addon:** detect op-VM-eligible node chains feeding the K scalar BSDF inputs; attach
  a scalar program + record its source-image id per input. Reuse the existing base-color
  op-VM detection/translation — this is the same VM, a new output binding.
- **Engine binding:** the two new `matScalarProgId` / `matScalarTexId` side-table arrays
  above (NOT a `GMaterial` field), uploaded once per frame.
- **CPU + GPU BSDF eval:** substitute the op-VM scalar in place of the constant
  `get_float_input` / `mat.roughness` etc., per the GPU-eval + CPU-mirror notes above.

## Non-goals
- Not new op-VM opcodes (the VM already evaluates the chains).
- Not a full arbitrary-output-socket system — just scalar BSDF param inputs.

## Provenance
Surfaced by the pkg219 completion audit (PR #661, 2026-08-31): pkg219 itself is DONE;
this is the one genuine remaining shader-node-compatibility gap it exposed. Fork
resolved by the architect 2026-09-02 (queue re-vet pass) grounded in
`shader_vm.h:390` + `stage_advance.cu:1249-1259`: extend the existing `c_wfProgBinding`
side-table, do not touch `GMaterial`. Now dispatchable to dv4 behind the standard
REG-probe + `cpp-abi-guard` + Claude-review gate.
