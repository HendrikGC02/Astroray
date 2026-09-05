# pkg230 — op-VM utility opcodes (Clamp + Math/Mix clamp flags; Vector Math/Rotate)

**Pillar:** 5 (Blender integration / shader-node coverage)
**Track:** A
**Status:** DONE — Phase 1 LANDED (#696); Phase 2 LANDED (#701, 2026-09-06 Sydney)
(branch `codex/pkg230-p2`, reviewed implementation `4035a00`)
**Estimated effort:** Phase 1 S (~1 session); Phase 2 M
**Depends on:** pkg219a/b/c (op-VM evaluator), pkg229 (re-audit that ranked these)

---

## Goal

The pkg229 re-audit's #3/#4 next-wave items are the highest-ROI remaining
DROPPED-SILENT shader features: the **Clamp** node and the **Math/Mix clamp
flags** — all ★★★ frequency, all pure per-texel color/scalar ops that the op-VM
already has the machinery for. This package closes them (Phase 1) and scopes the
adjacent #2/#7 **Vector Math / Vector Rotate** items (Phase 2), which turn out to
carry a real architecture fork the re-audit's one-liner did not surface.

**After Phase 1:** a Blender graph with a Clamp node, or a Math/Mix node with its
clamp checkbox(es) enabled, downstream of a texture renders per-texel-correct on
both CPU and GPU (previously the node was dropped / the flag ignored).

---

## Context

The op-VM (`include/astroray/shader_vm.h`) is a bounded register machine with a
single shared `HD svm_eval` used by **both** the CPU (`DisneyPlugin::substituted`)
and the GPU (behind the isolated `<HasProgram=true>` shade specialization). The
register file is `GVec3[VM_MAX_SLOTS]`, so vectors are already first-class, and
`Instr` carries 5 source slots (`a..e`) + one `imm` byte. Adding opcodes touches
only the `<true>` specialization — **the REG:254 fleet `<false>` kernel compiles
the VM out and is byte-identical by construction** (no register probe needed
beyond a confirmatory `<false>` check). The addon compiler
(`blender_addon/shader_vm_compiler.py`) mirrors the opcode/sub-op enums exactly;
its `compile_socket` is the single dispatch point.

The **fork** (Phase 2): node translation has two paths — the op-VM color/scalar
chain (`compile_socket`) and the coordinate/mapping chain
(`_resolve_vector_input` / `_resolve_mapping_matrix`, which resolve to an **affine
matrix** at upload, not per-texel math). Vector Math / Vector Rotate can appear in
either. The color-chain case is a clean op-VM opcode; the coordinate-chain case
(vector math on UVs *before* a texture lookup) cannot be expressed by the affine
matrix resolver and needs a separate design. Phase 2 must pick a path per case,
not assume "just add an opcode."

---

## Specification — Phase 1 (this PR)

### Sub-op enum (Cycles NodeClampType)

`CLAMP_MINMAX = 0` (clamp to [min,max], swapping if min>max is **not** done by
Cycles — MINMAX clamps to the literal [min,max]) / `CLAMP_RANGE = 1` (order-agnostic:
clamp to [min(min,max), max(min,max)]). Verified against Cycles `svm_clamp` /
`node_clamp.osl`.

### Files to modify

| File | Change |
|---|---|
| `include/astroray/shader_vm.h` | Add `OP_CLAMP` to `OpCode`; add `enum ClampType`; add `HD inline float svm_clamp(type,v,min,max)` (reuse the existing `svm_clampf`/`svm_saturatef`). Add `case OP_CLAMP` to `svm_eval`. Add `SVM_MATH_CLAMP` (0x80) handling in `case OP_MATH` (mask sub-op with 0x7F, saturate result if set) and `SVM_MIX_CLAMP_RESULT` (0x80) in `case OP_MIX` (mask sub-op with 0x3F, saturate result if set). |
| `blender_addon/shader_vm_compiler.py` | Extend the opcode tuple to `range(15)` incl. `OP_CLAMP`; add `CLAMP` handler in `compile_socket` (Value/Min/Max + `clamp_type`); set `imm |= 0x80` on MATH when `node.use_clamp`; set `SVM_MIX_CLAMP_RESULT` from `clamp_result` (modern Mix) or `use_clamp` (legacy MixRGB). |
| `tests/test_pkg230_opvm_clamp.py` (new) | CPU render/parity + unit-level bytecode tests (see gates). |

### Key design decisions

- **Flags in the free `imm` high bits, not new opcodes.** MathOp ≤17 (bit 7 free);
  MixOp ≤8 (bit 7 free). This keeps `Instr` at 8 bytes and adds zero opcodes for
  the flag features — only Clamp gets an opcode.
- **`clamp_factor` is deferred to Phase 2, not shipped as a bit.** `svm_mix`
  already saturates the factor unconditionally (`t = svm_saturatef(t)`), which
  equals Blender's *default* `clamp_factor=ON`. A `clamp_factor=OFF` (unclamped
  factor) would require gating that shared saturate — a base-mix behavior change
  for a rare case — so Phase 1 ships only the genuinely-new `clamp_result` and
  documents the always-saturated factor.
- **Clamp result broadcasts scalar → GVec3** like OP_MATH/OP_MAP_RANGE (Clamp is a
  scalar node).
- **Shared evaluator ⇒ CPU and GPU are correct from one edit.** GPU still needs a
  full CUDA rebuild + an RTX parity render (the shared header is compiled into the
  device kernel), and a confirmatory `<HasProgram=false>` register probe.

### Acceptance criteria — Phase 1

- [ ] Clamp node (both `clamp_type`s) downstream of a texture renders per-texel;
      CPU/GPU mean-ratio parity within tolerance.
- [ ] Math `use_clamp` and Mix `clamp_result` change the render in the correct
      direction vs the flag-off baseline; off ⇒ byte-identical to pre-pkg230.
      (Mix factor is always saturated = Blender default clamp_factor; asserted.)
- [ ] `<HasProgram=false>` fleet shade kernel byte-identical (REG:254/STACK/CONST).
- [ ] Enum parity: addon tuple ↔ `shader_vm.h` verified (a test asserts the values).
- [ ] No new socket read is silently dropped by the pkg229 coverage scanner
      (CLAMP is auto-credited; regenerate is optional, not required).

---

## Specification — Phase 2 (architecture resolved 2026-09-05)

Implement Vector Math (`OP_VEC_MATH=15`, all 30 Blender 5.1 operations) and
Vector Rotate (`OP_VEC_ROTATE=16`, axis-angle, X/Y/Z, Euler XYZ, center/invert)
in the shared HD VM for image-driven **color/scalar chains**. Read only used
operands; index duplicate Vector sockets positionally. Keep VM limits and POD
layouts unchanged. Scalar vector-math outputs broadcast; Euler inverse uses
transpose, axis-angle inverse negates angle, zero axis is identity.

Mix uses negative-polarity `SVM_MIX_UNCLAMP_FACTOR=0x40`: legacy/default raw
bytecode keeps clamping; modern Mix obeys `clamp_factor`. Select enabled typed
sockets, and visibly reject unsupported modes. `clamp_result` remains bit 0x80.

**Coordinate fork resolved:** retain the existing affine Mapping path and make
unsupported Vector Math/Rotate chains emit a visible degradation warning.
Affine vector operations and general per-texel coordinate evaluation are a
separate follow-up; this phase does not claim their support.

Pinned sources, rationale, dependencies and risks:
[`pkg230-phase2-vector-semantics-research.md`](../docs/pkg230-phase2-vector-semantics-research.md).
Independent Claude architecture SIGN-OFF accepted with the warning, negative
flag and inverse-convention conditions included above.

### Acceptance criteria — Phase 2

- [x] All 30 vector operations, all 5 rotation modes, linked operands and edge
      cases evaluated against explicit mathematical oracles; enum/flag parity.
- [x] Legacy/default Mix unchanged; unclamped factors below zero/above one;
      duplicate real Blender socket layout and unsupported-mode rejection.
- [x] Coordinate-chain Vector Math/Rotate emits visible degradation (test).
- [x] CPU/GPU image programs change the control render and per-channel mean
      ratios lie in [0.95,1.05]; saved outputs inspected qualitatively.
- [x] Fresh canonical builds, intended import path, new-op canary, unchanged
      non-program fleet kernel REG/STACK/CONST against same-toolchain baseline.
- [x] Headless Blender real graphs render through exporter; compare saved
      vector/Mix charts with Cycles in common linear space.
- [x] Full local suite, focused regressions, differential lint and caller/binding
      sweep recorded; independent Claude final sign-off and green CI. Two local
      baseline failures remain explicitly accepted/tracked under pkg237/pkg238;
      the original full local run is not represented as green.

---

## Non-goals

- No new coordinate-chain per-texel vector VM; Phase 2 explicitly warns/degrades.
- No touching the fleet `<false>` shade kernel or `GMaterial` layout.
- No Principled advanced-inputs (separate, higher-effort spec).

---

## Progress

- [x] Phase 1 — Clamp opcode + Math `use_clamp` + Mix `clamp_result` (engine +
      addon + tests). CPU-verified via the shared `svm_eval`:
      `tests/test_pkg230_opvm_clamp.py` **7/7** (incl. MINMAX-vs-RANGE Cycles-parity
      — caught & fixed a `svm_clampf` divergence for min>max), and **38/38** pkg219
      op-VM regression (incl. GPU parity renders) green — no regression.
- [x] Phase 1 — GPU HW-verified on RTX 5070 Ti (2026-09-05):
      `tests/test_pkg230_gpu_clamp_parity.py` **3/3** (GPU OP_CLAMP changes the image
      + matches CPU mean-ratio). `cuobjdump --dump-resource-usage` on the built
      `.pyd`: `stageShadeBucketedKernel` **REG:254 across all 128 shade
      specializations** — no spill; the fleet `<0,…>` is REG:254/STACK:3400/
      CONSTANT[0]:1748 (STACK/CONST are current-main baseline; the VM rides
      `<HasProgram=true>`, so the fleet `<false>` path is untouched by construction).
- [x] Phase 2 — Vector Math / Vector Rotate op-VM opcodes (color-chain) + faithful
      Mix `clamp_factor=OFF`, fork resolved. LANDED #701, merge `b38a7d8`.

## Lessons

Hardware/visual verification and investigated baseline failures are recorded in
[Phase 2 delivery evidence](../docs/pkg230-phase2-delivery-evidence.md).
The full suite recorded 2326 passes and four failures; corrected Blender/harness
reruns pass, while HDRI SSIM and PostInit ULP remain baseline-reproduced failures.
No rendering thresholds were weakened. Independent Claude final sign-off granted
on `4035a00`; both CI runs passed before #701 merged as `b38a7d8`.
