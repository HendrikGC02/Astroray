# pkg219 — Per-texel shader-graph evaluation (stop constant-folding the Blender node tree)

**Pillar:** Blender/DCC integration (integration-first directive, 2026-08 — this comes
BEFORE Pillar 4; memory `integration-first-directive-2026-08`).
**Track:** A (architect researches the fork + sizes before implementation).
**Status:** open (filed 2026-08-22; fork DECIDED + staged 2026-08-23).
**Research note:** [`../docs/pkg219-per-texel-svm-evaluator-research.md`](../docs/pkg219-per-texel-svm-evaluator-research.md) — READ FIRST.

## Decision (2026-08-23 architect planning pass)

**Fork (c) — bounded hybrid op-VM, staged, as the on-ramp to full (a).** (b)
special-casing is the rejected "reinvent the wheel 100 times" anti-pattern; (a)
full-SVM in one shot is XL and register-hostile with no incremental delivery. (c)
covers the confirmed-broken chains (all scalar/colour ops ≤4-wide downstream of a
texture) with a **bounded** `uint4` bytecode VM whose format is a strict prefix of
full SVM. **The critical constraint vs Cycles SVM: a STATIC compile-time stack
bound** (Cycles' dynamic float stack overflows "with relatively few nodes" and is
untenable on the REG:254 wavefront) — overflow → visible degradation entry + fall
back to constant-fold, never a silent grey.

**Staging (dispatch as three sub-packages; 219a is independently useful):**
- **pkg219a — Coordinate + Mapping unification** (M, Track A, no VM).
  **Status: in review (PR #640, 2026-08-23 — CPU+GPU, register-neutral; needs HW verify).**
  Full 3-D Mapping matrix (incl. X/Y rotation) + real
  Generated/Object/Camera/Window/Reflection/Normal TexCoord, wired into the
  existing texture special-case. Fixes the "mapping only partly applied" repro
  half on its own. Implemented Option B (CPU + GPU parity): addon composes the
  exact Blender Mapping matrix via numpy (Cycles svm/mapping_util.h POINT order),
  ships it through `set_texture_mapping_matrix`; CPU `Texture` and the GPU
  wavefront (`GImageTexture` → scene_upload.cu → stage_advance.cu) apply it.
  cuobjdump register probe: shade-kernel REG/STACK histogram IDENTICAL with vs
  without the GPU apply (constant-memory matrix, FMAs on already-live coords) —
  no `HasTexMapping` template axis needed. Research note:
  `../docs/pkg219a-mapping-transform-research.md`.
- **pkg219b — Bounded op-VM core** (L, Track A, Claude-implementer). Host-side
  Blender-tree→`uint4` compiler, CPU evaluator, GPU device evaluator with the
  static stack-bound check + `<bool HasProgram>` isolation + REG probe gate. Ship
  Color-Ramp / Mix / Math / MapRange opcodes (highest-frequency broken chains).
- **pkg219c — Opcode coverage fill-out** (M, Track A/B). HSV / Invert / Gamma /
  BrightContrast / Separate-Combine / Bump / NormalMap, each with a Cycles parity
  render.

Old `**RESEARCH SPEC**` framing below retained for context.
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

## Hardware verification 2026-08-23 (pkg219a slice, PR #640, independent re-verify)

**Hardware:** RTX 5070 Ti, Windows 11 Enterprise 10.0.26200, driver 610.47, CUDA 12.8
(nvcc), sm_120 target.

**Build:** `build_cuda_worktree.bat` on worktree
`Astroray-pkg219a` @ `6ed06e085b3af3831ec3f9f4906854a3355178e6` (HEAD SHA verified by
the build script's Phase-2 guard). `astroray.__file__` =
`build_cuda\Release\astroray.cp313-win_amd64.pyd` (canonical build output, not a
shadow copy). `cuobjdump --list-elf` confirms sm_120 embedded. ABI canary green
(`cpu/spectral/gpu/gpu_spectral: True`).

**Gate tests (`tests/test_pkg219a_mapping_render.py` +
`tests/test_pkg219a_mapping_unification.py`, 20 items):** 20 passed, 0 failed.

**Fleet register gate — independently re-run (`cuobjdump -res-usage` on the built
.pyd, all 32 `stageShadeBucketedKernel` specializations):**

| REG | STACK | count |
|-----|-------|-------|
| 254 | 3352  | 8 |
| 254 | 3608  | 4 |
| 254 | 3672  | 4 |
| 254 | 7720  | 6 |
| 254 | 7784  | 2 |
| 254 | 7848  | 8 |

Exact match to the implementer-reported histogram. All specializations REG:254
(fleet baseline) — no spill from the 3-D Mapping apply block.

**CPU/GPU parity (UV-mode image texture, scale-2 Mapping matrix, 64 spp, seed=1),
independently re-rendered on this run:**
- Per-channel mean-ratio (GPU/CPU): `[0.99955284, 1.00044285, 0.99764865]`
  (implementer reported 0.9996 / 1.0004 / 0.9976 — matches).
- GPU mapped-vs-plain mean|diff| = `0.065956` (implementer reported 0.066 — matches).
- CPU mapped-vs-plain mean|diff| = `0.065791` (new measurement, not previously
  reported; consistent with the GPU number, confirms CPU also honors the mapping).

**Visual inspection:** GPU plain render vs GPU scale-2-mapped render
(`test_results/pkg219a_gpu_plain.png`, `pkg219a_gpu_mapped.png`) — the 2x2
red/green/blue/yellow quadrant image visibly retiles/rescales between the two
renders (quadrant boundaries shift), confirming the mapping matrix reaches the
GPU wavefront image-sample path, not just changing numerically. No fireflies,
banding, NaN pixels, or mode regressions observed in either render.

**Verdict: PASS.** Both implementer claims (register-gate identity, CPU/GPU
parity) independently reproduced within MC noise on a clean, dedicated RTX 5070
Ti run (device not shared with another verifier this time). No regressions
found. Ready for `pr-reviewer` merge decision.

## Hardware verification 2026-08-23 (pkg219b slice, PR #641, independent re-verify)

**Hardware:** RTX 5070 Ti, Windows 11 Enterprise 10.0.26200, CUDA 12.8 (nvcc),
sm_120 target.

**Build:** `build_cuda_worktree.bat` (PowerShell, not `cmd /c`) on worktree
`Astroray-pkg219b` @ `99146ed9905788b2438aa9ae7424bc111a078847` (HEAD SHA
verified by the build script's Phase-2 guard). Exit 0. `astroray.__file__` =
`build_cuda\Release\astroray.cp313-win_amd64.pyd` (canonical build output).
`cuobjdump --list-elf` confirms sm_120 embedded. ABI canary green
(`cpu/spectral/gpu/gpu_spectral: True`). Note: `.pyd` mtime (06:54 local) is
earlier in wall-clock terms than the HEAD commit timestamp (10:15:57) — checked
and this is benign: HEAD only touched Python test files (author dates reflect
when the coordinator committed a recovered checkpoint, not when the C++
sources were last edited); all C++/CUDA source file mtimes (06:14-06:23)
predate the .pyd build (06:54), so the build is genuinely current for the
compiled sources.

**Gate tests** (`tests/test_pkg219b_op_vm.py` + `tests/test_pkg219b_addon_compiler.py`
+ `tests/test_pkg219b_parity_render.py`, 14 items): **14 passed, 0 failed.**

**Regression smoke** (`tests/test_material_properties.py` +
`tests/test_disney_reflection_not_black.py`, 23 items): **21 passed, 2 xfailed**
(pre-existing `test_disney_metallic_tints_specular_highlight`,
`test_disney_roughness_changes_glossiness` — unrelated to this PR, non-VM path
unaffected). No new failures.

**Fleet register gate — independently re-run** (`cuobjdump -res-usage` on the
built `.pyd`, all 64 `stageShadeBucketedKernel` specializations, template axis
isolated by parsing the mangled name — last bool = `HasProgram`):

All 64 specializations: **REG:254, no spill.**

`HasProgram=false` (32 specializations) STACK histogram — exact match to the
pkg219a baseline:

| REG | STACK | count |
|-----|-------|-------|
| 254 | 3352  | 8 |
| 254 | 3608  | 4 |
| 254 | 3672  | 4 |
| 254 | 7720  | 6 |
| 254 | 7784  | 2 |
| 254 | 7848  | 8 |

`HasProgram=true` (32 specializations) STACK histogram — bounded increase,
still no register spill:

| REG | STACK | count |
|-----|-------|-------|
| 254 | 3352  | 4 |
| 254 | 3416  | 4 |
| 254 | 3608  | 2 |
| 254 | 3672  | 4 |
| 254 | 3736  | 2 |
| 254 | 7720  | 4 |
| 254 | 7784  | 2 |
| 254 | 7848  | 6 |
| 254 | 7912  | 4 |

Max STACK 7912 (vs 7848 baseline max) — matches PR's claimed bound. Non-VM
materials confirmed byte-identical to pkg219a; VM materials pay a small
bounded STACK cost, no fleet regression.

**Visual repro — headline claim (Color Ramp downstream of a texture):**
Built an independent scene (`TexCoord(UV) → Image(16×16 horizontal gradient) →
ColorRamp(blue→yellow).Fac → Base Color`) on a quad, 128×128, 128 spp, rendered
CPU and GPU (script deleted after use per repo convention). Results:
- CPU/GPU per-channel mean-ratio: `[0.99845, 0.99925, 0.99967]` — matches
  within MC noise.
- CPU left-quad mean RGB `[0.153, 0.184, 0.252]` (blue-dominant) vs right-quad
  mean RGB `[0.256, 0.250, 0.161]` (yellow-dominant) — confirms the ramp is
  applied **per-texel**, spatially varying with the underlying texture, not a
  flat/constant-folded grey.
- Visual inspection of both PNGs: smooth horizontal blue→olive-yellow gradient
  across the quad on both CPU and GPU, visually indistinguishable between
  backends. No fireflies, no banding/quantization artifacts, no NaN pixels
  (no magenta/solid-black), no mode regressions.

**Verdict: PASS.** All three items independently re-confirmed: fleet register
gate (no spill, `<false>` byte-identical to pkg219a baseline), functional
tests (14/14) and regression smoke (21/23 + 2 pre-existing xfail, no new
failures), and the visual headline repro (Color Ramp on a texture renders
correctly per-texel on both CPU and GPU, in close numerical parity). Ready for
`pr-reviewer` merge decision.
