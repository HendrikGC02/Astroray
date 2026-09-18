# issue #818 — procedural textures through the op-VM: design decision

Lane: batchN (`feat/batch-n-opvm-818`). 2026-09-15.

## Problem (from #818)
The pkg219/pkg230 op-VM compiles the *downstream* node chain (Math / Mix / Color
Ramp / Map Range / …) but the upload path requires every program **input** to be
a `TEX_IMAGE`. A procedural input (Noise / Voronoi / Wave / …) hits
`"op-VM input is not an image texture; flattened"` and the whole chain is
constant-folded to one grey value (memory `addon-constant-folds-shader-graph`).
So `Noise → Math → Color Ramp → Base Color` renders flat.

## Options weighed (brief Item 1)
- **(a) bake-to-image at export** — feed the procedural into the existing
  OP_LOAD_TEX path. Generic across every procedural Blender has; resolution-
  limited.
- **(b) native `OP_LOAD_PROC` opcodes** — evaluate Noise/Checker/Gradient/Wave
  per-shade inside `svm_eval` on both backends (clean-room Cycles port).

## Decision: (a), reusing the pkg190 procedural bake — for Item 1.

Rationale (why (a) is the right reuse here, not just the cheap path):
1. **CPU is already done and exact.** `ProgramTexture::value(uv,p)` already calls
   `inputs_[i]->value(uv,p)` generically (advanced_features.h). A procedural
   child evaluates *natively* per-shade — no bake, no resolution loss, exact
   Cycles-parity math (the same evaluators pkg115/pkg190 already ship). **Zero
   C++ change on CPU.**
2. **GPU reuses pkg190 verbatim.** scene_upload.cu already bakes a *direct*
   procedural base colour into the flat texel buffer (2D-UV grid or 3D voxel over
   the Generated domain, Mapping folded in per pkg242) and the wavefront shade
   path (stage_advance.cu) already samples both a voxel (`depth>1`) and a 2D grid
   and *then* runs `svm_eval`. The only gap is that the `ProgramTexture` branch
   in scene_upload.cu accepts an `ImageTexture` child only. Baking a procedural
   child through the SAME bake helper closes it.
3. **`svm_eval` is untouched → REG:254 shade kernel is byte-identical.** Option
   (b) would have to make the shade point a VM input (svm_eval signature change,
   a documented "the VM does NOT fetch textures" divergence) and add HD Perlin /
   Voronoi / Wave ports — real register-pressure risk on the pinned REG:254
   `stageShadeBucketedKernel`. (a) adds no device code to that kernel.
4. **Resolution caveat is the accepted pkg190 tradeoff**, already in effect for
   direct procedural base colours; nothing new is regressed.

No new algorithm is introduced (CLAUDE.md §6): the procedural math is the
existing Cycles-cited pkg115/pkg190 evaluators; the bake is the existing pkg190
path. Nothing to source.

## Item 2 (coordinate-side non-affine math) — surfaced as a fork, NOT built here.
The brief's Item-2 example `Texture Coordinate → Separate XYZ → Math(Sin) →
Combine XYZ → Noise` warps the texture's *input coordinate* with a **non-affine**
op (Sin). Option (a) cannot represent it on either backend:
- CPU samples the procedural natively at the ProgramTexture's resolved `p`; there
  is no hook to apply per-shade Sin to that coordinate.
- The GPU bake calls `tex->value(gridpoint)`; the coordinate math is not inside
  the C++ texture.
The affine-representable subset (per-axis scale/offset, i.e. Vector Math
ADD/SUBTRACT/MULTIPLY/SCALE) is *already* handled by `_resolve_affine_coordinates`.
The genuinely-new value in Item 2 is the non-affine part, which requires the full
`OP_LOAD_PROC` / coordinate-as-VM-input architecture from option (b) — a
materially larger, REG:254-risky change. Recommendation: land Item 1 (closes the
issue's PRIMARY acceptance — the `Noise → Math → Ramp → Base Color` row), and file
option (b) as a scoped follow-up for the non-affine coordinate distortion.

## Follow-ups filed (2026-09-18)
- **#822** — Item 2: coordinate-side non-affine math needs the `OP_LOAD_PROC` /
  coordinate-as-VM-input architecture (option b). Deferred (REG:254 risk, large).
- **#823** — Item 3: the parity coverage scanner targets `compile_socket` (a thin
  wrapper) instead of `_compile_socket_value` (where the op-VM `ntype` dispatch
  lives), so Math/Mix/Map Range/Clamp/… read DROPPED-SILENT in the matrix.
  The one-line target fix flips ~46 rows to SUPPORTED but cascades into a
  46-tag `textures_mapping` corpus-scene obligation (manifest gate) + a plain
  regen drops unrelated pkg256/EMISSION notes — so it is a separate package,
  not committed here.
