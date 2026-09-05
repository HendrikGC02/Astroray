# pkg230 Phase 2 — vector semantics and delivery decision

Architect decision, 2026-09-05, base `31f3029`.

The live STATUS, NEXT_STAGE_REPORT, and ROADMAP all select this phase. No open
PRs or other worktrees were present at selection. pkg219a/b/c and pkg229 are
landed; pkg230 Phase 1 landed in #696 despite its stale Status header.
This closes common Blender shader gaps ahead of the owner-choice research and
larger Principled arcs. Pillar 4 remains paused.

## Reference checked before implementation

The existing pkg219c semantics research already covers Vector Math. This refresh
pins Blender v5.1.0, commit `adfe2921d5f3c0fe699149bcd9bc347543bbd82e`:

- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/kernel/svm/math_util.h
- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/kernel/svm/vector_rotate.h
- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/util/math_float3.h
- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/util/math_base.h
- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/util/transform.h
- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/kernel/svm/color_util.h
- https://github.com/blender/blender/blob/adfe2921d5f3c0fe699149bcd9bc347543bbd82e/intern/cycles/kernel/svm/convert.h

All these files declare Apache-2.0. Preserve attribution in the adapted helpers;
this is compatible with the repository's MIT license. These are node semantics
and textbook vector/rotation formulas, not a new light transport algorithm; no
paper claim is made. The Cycles implementation is the normative reference.

## Bounded architecture

Add OP_VEC_MATH=15 and OP_VEC_ROTATE=16 in the existing shared HD evaluator and
Python compiler. Keep Instr, ShaderVMProgram, GMaterial, slot limits, bindings,
and shader specialization axes unchanged. Implement the 30 vector operations
in the pinned reference. Dot/distance/length broadcast their scalar result.
Read duplicate Vector inputs by position and compile only operands used by the
selected operation, avoiding dead hidden sockets and unnecessary slot pressure.

Rotate supports AXIS_ANGLE, X_AXIS, Y_AXIS, Z_AXIS, EULER_XYZ, center and invert.
Axis-angle and single-axis invert negate the angle.
Use the Cycles Euler XYZ transform, transposed for invert (negating all Euler
angles in the same order is incorrect). A zero axis returns the input vector.

Mix uses bit 0x40 as SVM_MIX_UNCLAMP_FACTOR (set means unclamped), preserving
existing raw bytecode with bit clear. Modern Mix obeys
clamp_factor, legacy MixRGB always clamps its factor. Select the enabled
data-type sockets in real Blender, where names Factor/A/B are duplicated.
Preserve default and legacy results. Unsupported data modes must visibly
degrade rather than select an inactive socket. Sweep hand-written bytecode
callers if introducing a positive clamp flag changes the old encoding.

Scope is the color/scalar chain after image sampling. The affine coordinate
resolver remains a separate path: do not claim general per-texel coordinate
support. Its existing affine subset and warning/degradation behavior must be
checked. Vector Math/Rotate in this path must emit a visible fallback warning,
covered by an addon regression test. Affine vector support and general per-texel
coordinate evaluation become a separate follow-up spec,
not an expansion of this phase.

## Acceptance gates and risks

1. Enum/flag synchronization and all vector operations evaluated against
   explicit expected values, including zero division/normalization, negative
   modulo, wrap bounds, projection, reflection and refraction edge cases.
2. All rotation modes, nonzero centers, zero axis, multi-axis Euler inverse,
   linked operands, and default/clamped/unclamped Mix factors tested.
3. CPU and RTX 5070 Ti representative image-program renders change from the
   plain-texture control and agree per-channel mean within 5%; save images.
4. Build both backends from current sources; verify module path and a new-op
   canary. Compare linked non-program fleet kernel REG/STACK/CONST to a fresh
   baseline from the same compiler/configuration. No new specialization axis.
5. Run focused regressions, full local suite, differential lint, and caller/
   binding review. Investigate failures against baseline without weakening gates.
6. Headless Blender exercises real sockets, exporter and renderer; compare
   representative output to Cycles in a common linear space. Astra visually
   inspects exposure, color, artifacts and expected transforms.
7. Independent Claude architecture and final ABI/parity/PR sign-off before
   autonomous merge; CI green. Planning records contain actual evidence only.

Main risks: operand selection, Euler inverse convention, limited VM slots,
silent coordinate degradation, Mix bytecode compatibility, and stale OneDrive
build products. Spectral/dispersion/IR paths are preserved by the bounded VM
change; no transport or scientific-output behavior is redesigned.

Independent Claude architecture review: SIGN-OFF, with the three conditions
above (coordinate warning gate, negative Mix flag, per-type inverse) accepted.
Transcript: `test_results/pkg230-p2/architecture-claude.txt`.

Integration finding: real Blender links expose socket types. The compiler now
converts linked RGBA to scalar with the existing linear luminance opcode and
VECTOR to scalar with a dot product against (1/3,1/3,1/3), following pinned
Cycles `kernel/svm/convert.h` (Apache-2.0). This is needed for vector -> Math,
modern FLOAT Mix, factors and angles; VM bounds still apply. Bare image paths
remain owned by pkg186. FLOAT and uniform VECTOR Mix interpolate linearly;
ROTATION and non-uniform factors visibly degrade.
