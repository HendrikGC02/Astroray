# pkg108 — Blender Addon Residual Bug Triage

**Pillar:** 5 (Production polish)
**Track:** A (small targeted fixes) + investigation
**Status:** done (PR #432, 2026-06-10 — BUG-09 verified non-reproducing in live Blender 5.1; BUG-14 root cause was the GPU delta-dielectric dropping the tint (`s.f = eta²` without baseColor), fixed CPU-parity (`baseColor * eta²`); BUG-16 GPU half fixed — closure-graph diffuse + GMAT_DISNEY both now apply the Burley §5.3 HK subsurface mix; 6 regression tests incl. GPU variants + headless-Blender routing verify)
**Estimated effort:** 2–4 days (one bug per ½–1 day)
**Depends on:** none

---

## Goal

**Before:** A handful of named addon defects from the 2026-05-16
first-principles plan remain open after the structural-primitive
sweep (P1 build guard, P2 sync re-parse, P3 wires, P4 native
matrices, P5 GPU asymmetry guard) closed in Rounds 12–14. These are
individual material/shader-node bugs that don't roll up to a
primitive collapse:

- **BUG-09 (Astroray Output shader node):** custom `ShaderNode`
  subclass is detected by the addon's `inline_shader_nodes()` flat-
  tening pass via `next(...)` at `:1737` but the node's output
  isn't picked up; the material falls through to standard
  Principled-BSDF translation.
- **BUG-14 (glass color at low roughness):** at near-zero roughness
  the glass material's base-color tint is invisible. Hypothesis:
  surface BTDF tint (lines 2763–2767 of `__init__.py`) instead of
  Beer-Lambert volumetric absorption inside the glass.
- **BUG-16 (Subsurface possibly no-op):** Principled-BSDF
  `subsurface_weight` / `subsurface_radius` may not be plumbed
  through to the C++ Disney implementation.

BUG-08 (32mm sensor hardcode) was closed 2026-05-27 by changing
the `_setup_viewport_camera` fallback path to 36mm (matching
`_compute_vfov_degrees`). See pkg104 commit.

**After:** Each remaining bug is either fixed surgically or has a
documented next-step plan.

---

## Specification

### BUG-09 — Astroray Output node

**Likely already fixed** (verified during pkg104 night):
- The original-tree fallback `(P3-c probe & fix)` at `__init__.py:1987-2016`
  detects `AstrorayOutputNode` in the pre-flatten tree and switches the
  conversion path to it if flattening stripped it.
- The handler `convert_astroray_output()` at `:2055-2080` dispatches
  to the right Astroray BSDF (Sellmeier, IR/UV, NRC hint, spectral
  profile) and produces the correct material id.
- `tests/test_blender_native_nodes.py::test_astroray_output_takes_precedence_with_sellmeier_glass`
  exercises the chain end-to-end with stub-Blender and passes.

**Remaining action:** owner verification on a live Blender scene with
an actual AstrorayOutputNode wired up. If the bug still reproduces,
attach the reproduction scene + capture the path that's broken.

### BUG-14 — Glass color at low roughness

**Does NOT reproduce in basic configuration** (verified during pkg104
night via `tests/test_pkg108_glass_color_lowroughness.py`): a glass
slab with `roughness=0.02` + `base_color` set to strong red vs strong
blue produces visibly different transmission on a white floor below.
The dielectric BSDF's tint slot IS reaching the renderer at low
roughness in this path.

**Remaining action:** owner verification with the actual Blender shader
graph that triggered the original report. The most likely scenario
that still breaks is when the tint goes through the Blender addon's
`_principled_shader_spec` → `disney` material routing at line ~2763,
which may have different tint plumbing than the direct
`dielectric` material path. If owner can reproduce on a specific
.blend file, attach it and the test can be extended.

### BUG-16 — Subsurface no-op

**Investigation needed:** Run a test with `subsurface_weight=0` vs
`subsurface_weight=1` on a thick sphere; if the rendered output is
identical, the subsurface plumbing is broken. Inspect
`module/blender_module.cpp` for whether `subsurface_*` params reach
the Disney material constructor.

**Likely fix:** Either it's a missing binding (Python sees the
param, C++ ignores it) or a missing material-implementation branch.

---

## Acceptance criteria

- [ ] Each bug closed has a regression test showing the fix.
- [ ] BUG-09: setting "Astroray Output" as material output → render
      matches manually-configured material spec.
- [ ] BUG-14: glass cube with base_color = strong tint, low
      roughness, in a Cornell-like scene → tinted transmission
      visible vs untinted variant.
- [ ] BUG-16: subsurface_weight=0 vs subsurface_weight=1 produces a
      measurable color difference on a same-geometry render.

---

## Non-goals

- Not BUG-08 (already closed by 2026-05-27 fallback fix).
- Not full Beer-Lambert volumetric absorption (large C++ scope; if
  needed, separate spec).
- Not the deferred Phase-2b astrophysics tuning.

---

## Progress

- [x] BUG-08 closed (pkg104 sensor-width fallback fix).
- [x] BUG-09 closed (2026-06-10): live-Blender verification done headlessly
      (`scripts/verify_pkg108_bug09_bug14_blender.py`, Blender 5.1
      `--background --factory-startup`). A REAL `AstrorayOutputNode` →
      `AstrorayShaderNodeSellmeierGlass` tree (with a decoy Cycles
      OUTPUT_MATERIAL + Principled) routes to `dielectric`/`sellmeier_preset
      ='bk7'` through the full engine render path, including the real
      `inline_shader_nodes()` flattening pass. Does not reproduce; the P3-c
      probe + `convert_astroray_output` handler work as designed.
- [x] BUG-14 closed (2026-06-10): the report WAS real — on the **CUDA
      backend only**. `gpu_dielectric_sample` / `gpu_dielectric_sample_spectral`
      set the refraction throughput to `eta²` with no baseColor, so tinted
      glass rendered clear on GPU at any roughness ≤0.03 (the delta regime —
      exactly "tint invisible at low roughness"). The closure-graph lowering
      (disney glass AND plain dielectric both lower to GMAT_CLOSURE_GRAPH →
      GMAT_DIELECTRIC at low roughness) carried the tint into `baseColor` but
      the sampler ignored it. Fix mirrors CPU `dielectric.cpp` (`s.f = tint_
      * eta²`): refraction now multiplies `mat.baseColor`. Reflection stays
      untinted (CPU parity). Direct dispersive-dielectric uploads use white
      baseColor → Sellmeier/BK7 paths bit-identical. Regression tests:
      dielectric + disney-routed (addon config) × CPU + GPU in
      `tests/test_pkg108_glass_color_lowroughness.py`. Addon-side plumbing
      separately verified in the live-Blender script (red tint +
      transmission=1.0 reach `create_material('disney', ...)`).
- [x] BUG-16 closed (2026-06-10): CPU half was fixed in PR #375; the GPU half
      remained — `subsurface` was uploaded but never read. TWO GPU paths fixed:
      (a) `gpu_disney_eval` (direct GMAT_DISNEY) now applies the Burley 2012
      §5.3 Hanrahan-Krueger mix mirroring the CPU fix; (b) the closure-graph
      path (what the Disney plugin actually lowers to: GCLOSURE_DIFFUSE →
      GMAT_LAMBERTIAN) now carries `subsurface` + parent roughness through
      `convertMaterial` → `gpu_closure_as_material` → gated HK mix in
      `gpu_lambertian_eval` (subsurface==0 renders bit-identical).
      GPU regression test added (`test_subsurface_weight_changes_rendered_output_gpu`).

---

## Lessons

*(Fill in after the package is done.)*
