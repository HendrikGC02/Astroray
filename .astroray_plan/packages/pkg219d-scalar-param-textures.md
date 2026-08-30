# pkg219d — Scalar parameter textures (op-VM → roughness/metallic/etc.)

**Pillar:** 5 (Blender/DCC integration — shader-node compatibility)
**Track:** A (engine + addon; CPU + GPU BSDF eval)
**Status:** open (filed 2026-08-31 — residual surfaced by the pkg219 completion audit, PR #661).
**Estimated effort:** M–L (register-hostile GPU shade path — Claude-last-line).
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

## Scope (to be detailed by the architect before dispatch)

Add a per-texel **scalar parameter-texture** path:
- Addon: detect op-VM-eligible node chains feeding scalar BSDF inputs (roughness,
  metallic, transmission, IOR, …); attach a scalar program texture per input.
- Engine material: a scalar-param-texture slot (or small set) alongside the existing
  base-color/normal/bump program hooks.
- CPU + GPU BSDF eval: sample the op-VM scalar at the shade point and use it in place
  of the constant `get_float_input`. **GPU is register-hostile** — this touches the
  REG:254 shade kernel; ride the `__constant__` side-table pattern (memory
  `shade-axis-side-table-avoids-spill`), keep it off `GMaterial`, and gate behind an
  `if-constexpr`/side-table axis with a MANDATORY up-front `cuobjdump` register probe
  (memory `closure-graph-lobe-count-spills-fused-kernel`). Spill → escalate/park.

## Non-goals
- Not new op-VM opcodes (the VM already evaluates the chains).
- Not a full arbitrary-output-socket system — just scalar BSDF param inputs.

## Provenance
Surfaced by the pkg219 completion audit (PR #661, 2026-08-31): pkg219 itself is DONE;
this is the one genuine remaining shader-node-compatibility gap it exposed. Owner/
architect to decide priority vs other Pillar-5 work.
