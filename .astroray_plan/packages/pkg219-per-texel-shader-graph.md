# pkg219 — Per-texel shader-graph evaluation (stop constant-folding the Blender node tree)

**Pillar:** Blender/DCC integration (integration-first directive, 2026-08 — this comes
BEFORE Pillar 4; memory `integration-first-directive-2026-08`).
**Track:** A (architect researches the fork + sizes before implementation).
**Status:** open (filed 2026-08-22). **RESEARCH SPEC.**
**Priority:** HIGH for usability — the owner (2026-08-22) flagged that "lots of shader
nodes don't really work" and that this must be fixed "if we ever want good useability and
Blender integration without reinventing the wheel 100 times."
**Estimated effort:** L–XL (a real engine feature; see the fork).

## The problem

The addon translates a Blender material's node tree by **constant-folding** it to a small
set of per-material constants (a base colour, a roughness float, …), with **image textures
special-cased** (wired straight to a BSDF input with a 2-D UV transform). Anything that
needs **per-texel / per-shading-point** evaluation *downstream of a texture* cannot be
represented and **silently degrades** to a constant, grey, or an ignored transform.

**Concretely broken (reproduced in the owner's scene, `Material.001`):**
- Chain `TexCoord(UV) → Mapping → Image → ColorRamp.Fac → Base Color`.
  - `convert_shader_node`'s `VALTORGB` handler (`blender_addon/__init__.py:2772`) does
    `node.color_ramp.evaluate(fac)` where `fac = _get_socket_float(...)` — a **single
    constant**. When the Fac is driven by an image (spatially varying), that returns `None`
    → the Color Ramp returns `None` → Base Color falls back to grey. **A Color Ramp on a
    texture always breaks.** Same for MixRGB/Mix Color of two textures, Math / Map Range /
    Bright-Contrast / HSV / Invert / Gamma / Separate-Combine Color on a texture, Bump,
    Normal Map, etc.
  - **Mapping** (`:2961`) reads Location/Rotation/Scale but collapses the 3-D mapping to a
    **2-D UV transform** (only Z-rotation; X/Y rotation dropped) and does not follow linked
    inputs ("would require a real expression evaluator"). The owner's non-default mapping
    (Loc 0,5.6,0 / Rot 1.30,0.87,0.95 / Scale 0.4) is only partly applied — and is invisible
    anyway because the Color Ramp downstream greys the whole thing.
  - **TexCoord** (`:2993`) only really supports UV / Generated / Object; Camera / Window /
    Reflection / Normal fall back to UV.

**Why this matters:** most non-trivial Blender materials use *something* between a texture
and the BSDF (a Color Ramp to remap, a Mix to blend, Math to drive roughness, a Mapping to
place it). Under constant-folding, those silently produce the wrong image. This is the
single biggest Blender-integration usability gap.

## The fork (genuinely different outcomes — architect to choose)

- **(a) Real shader-graph evaluator.** Compile the Blender node tree to a bytecode/VM
  evaluated per shading point on CPU **and** GPU — the **Cycles SVM** pattern
  (`intern/cycles/kernel/svm/*`, Apache-2.0) or OSL. Correct and *general* — every node
  combination "just works", no more whack-a-mole. This is the "don't reinvent the wheel"
  answer the owner wants, but it is a large engine feature (a node compiler + a device-side
  interpreter + register/perf budget on the GPU wavefront — mind the REG:254 shade-kernel
  ceiling, memory `wavefront-shade-kernels-register-saturated`).
- **(b) Incremental special-casing.** Extend the constant-fold translator to emit small
  procedural specs for the *common* per-texel chains (Color Ramp on a texture, Mix of two
  textures, Math/MapRange on a factor, full 3-D mapping). Cheaper and bounded, but never
  general — exactly the "reinventing the wheel 100 times" the owner called out. Acceptable
  only as a stopgap.
- **(c) Hybrid.** A minimal per-texel op VM for scalar/colour ops downstream of textures
  (ramp, mix, math, separate/combine, hsv, invert), constant-folding everything provably
  constant. Most of (a)'s coverage for a fraction of the cost; a clean migration path to (a).

**Owner lean (inferred, confirm at research):** toward a *general* solution ((a) or (c)),
not endless special-casing.

## Specification (architect to expand)
1. `cite-algorithm` first: **Cycles SVM** node compilation + device interpreter as the
   reference architecture (and OSL as the alternative); save a research note.
2. Decide the fork with an explicit cost/coverage/perf table. If (a)/(c): design the node
   compiler (Blender tree → op stream), the CPU evaluator, and the GPU wavefront evaluator
   (register budget!). If (b): enumerate the exact node set and their procedural specs.
3. Unify the texture-coordinate path (full 3-D Mapping incl. X/Y rotation; real
   Generated/Object/Camera/Window coordinates), since it's needed regardless of fork.

## Acceptance criteria
- [ ] A node-graph matrix renders correctly CPU **and** GPU, qualitatively matching Cycles:
      image→ColorRamp→BaseColor; image→MixRGB→BaseColor; Math/MapRange driving roughness;
      a 3-D-Mapping-transformed image (scale+rotate+offset visibly applied); Generated and
      Object coordinates; Separate/Combine Color round-trip.
- [ ] No silent degradation: an unsupported node reports a *visible* degradation entry (not
      a silent grey) — pairs with the `_degradation_report` mechanism already present.
- [ ] GPU shade-kernel register budget respected (no non-texture-path perf regression).
- [ ] CI green.

## Reference
- Repro: owner's `Material.001` scene, 2026-08-22 (this file's Problem section).
- `blender_addon/__init__.py`: `convert_shader_node` (~2700+), `VALTORGB` (:2772),
  `_resolve_vector_input` / `MAPPING` (:2961) / `TEX_COORD` (:2993), `_degradation_report`.
- Cycles SVM (`intern/cycles/kernel/svm`), OSL.
- Memory: `integration-first-directive-2026-08`, `wavefront-shade-kernels-register-saturated`,
  `astroray-native-nodes-need-astroray-output`.
