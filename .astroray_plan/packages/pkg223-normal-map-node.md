# pkg223 — Normal Map node: tangent-space normal-texture perturbation of the shading normal (pkg219d, part 1)

**Pillar:** 5
**Track:** A
**Status:** DONE (PR #647 merged 2026-08-26, be7cbec). GPU-only scope confirmed on investigation: the addon export, CPU decode, and UV-aligned tangent infra already existed; the gap was GPU consumption + a latent CPU arbitrary-frame bug. Register probe PASS (64 HasNormalPerturb=false specializations byte-identical to main, 64 =true no spill/no STACK increase — normal-map data rides the c_wfTexBinding side arrays so GMaterial stays 640 B). CPU/GPU parity + visible-relief + Strength gates pass on RTX 5070 Ti. **Bump remains deferred** (pkg223b follow-up). Splits the pkg219c-deferred "pkg219d" Bump+Normal-Map item; **this package is Normal Map ONLY.** Bump (which needs height-texture derivatives) is deferred to a separate follow-up — see §Scope.
**Depends on:** TBD
**Priority:** HIGH usability — Normal maps are ubiquitous in real Blender materials
and currently silently do nothing (the addon constant-folds the node tree; memory
`addon-constant-folds-shader-graph`).
**Estimated effort:** M–L. **Register-sensitive** (perturbs the shading normal in the REG:254 GPU shade kernel) — a REG probe gate is MANDATORY.
**Implementer tier:** deepseek-v4-pro for the implementation, **but the GPU
shade-path register budget is Opus-last-line territory** — dispatch with a HARD
`cuobjdump` register-probe gate and a `cpp-abi-guard` + Claude review before merge.
If the probe shows a spill, STOP and escalate (isolate via `template<bool
HasNormalPerturb>` per §3) rather than shipping a fleet-wide regression.

---

## Why this is separate from the op-VM (pkg219b/c)

Per the pkg219c spec's own deferral note: Bump and Normal Map perturb the
**shading normal** — a geometry-dependent quantity fed to the BSDF's `N` — not a
per-texel colour/scalar value. They do NOT fit the colour op-VM (whose output is an
RGB register consumed as a texture value). Normal Map needs its own path: read a
tangent-space normal from a texture, decode it, and rotate the interpolated shading
frame accordingly, on BOTH CPU and GPU. Forcing it into the colour VM would require
the VM to write back into the shading frame — out of scope there.

## Scope (Normal Map only; Bump deferred)

- **IN:** the Blender **Normal Map** node (`ShaderNodeNormalMap`) in
  tangent-space mode: sample an RGB normal texture, decode `n_ts = 2·rgb − 1`,
  apply the node's **Strength**, transform tangent→world via the shading TBN frame,
  feed the perturbed `N` to the BSDF. Object/World space modes if cheap; otherwise
  degrade them VISIBLY (see gates), don't silently ignore.
- **OUT (deferred to a future pkg223b / pkg219d-bump):** the **Bump** node. Bump
  perturbs `N` from the *screen-space or analytic derivatives* of a height texture;
  it needs ray differentials or finite-difference texture derivatives on the
  wavefront — a materially harder, more register-hostile change. File it separately
  once Normal Map lands.

## Specification

1. **`cite-algorithm` first (CLAUDE.md §6):** cite **Cycles `svm/svm_tex_coord.h` /
   the Normal Map node (`node_normal_map`)** and Mikkelsen's tangent-space normal
   mapping convention (the exact decode + TBN handedness Blender/Cycles use —
   Blender uses the Mikk-TSpace convention). Save a research note. Getting the
   handedness/green-channel convention wrong flips the lighting — match Cycles
   exactly, do not invent.
2. **Addon (`blender_addon/`):** the node compiler currently constant-folds the
   tree (`convert_shader_node`, memory `addon-constant-folds-shader-graph`). Detect a
   Normal Map node feeding a BSDF `Normal` input; emit a per-material "normal-map
   spec" that carries: the source normal-texture handle (reuse the existing image
   special-case + pkg219a coordinate/mapping path — do NOT re-plumb UVs), the
   Strength, and the space mode. Wire it through the addon's material export
   (mirror how the base-colour texture is shipped). Register any new addon module in
   `ADDON_FILES` (memory `addon-packaging-file-list`).
3. **CPU shade path:** where the BSDF reads the shading normal, if a normal-map spec
   is attached, sample the normal texture at the hit UV (through the same
   coordinate/mapping transform as other textures), decode `n_ts = normalize(2·rgb −
   1)`, apply Strength by slerp/lerp toward the geometric `n_ts=(0,0,1)`
   (`n = normalize(lerp((0,0,1), n_ts, strength))` — the Cycles Strength semantic),
   build the world normal `N' = normalize(T·n.x + B·n.y + Ng·n.z)` from the hit's
   TBN, and use `N'` for shading. Requires a tangent frame at the hit — if the mesh
   has no tangents, derive a stable arbitrary TBN from `Ng` + the UV gradient (cite
   Cycles' fallback). Keep the geometric normal for shadow-terminator / self-shadow
   offsets.
4. **GPU wavefront shade path:** mirror the CPU decode + TBN rotate in the shade
   stage. **Isolate behind `template<bool HasNormalPerturb>`** (the pkg198/pkg199/
   pkg219b pattern) so scenes without a normal map stay byte-identical and pay ZERO
   register cost — the shade kernels are pinned at REG:254 and any per-hit normal
   state that spills tanks non-normal-map perf (memory
   `wavefront-shade-kernels-register-saturated`,
   `closure-graph-lobe-count-spills-fused-kernel`). The TBN + a texture sample + threed
   FMAs are modest, but PROBE it — do not assume.
5. **CPU/GPU parity:** byte-mirror the decode + TBN math; the render is a per-channel
   mean-ratio gate (independent MC streams), not bit-exact.

## Acceptance criteria

- [ ] A quad/sphere with a tangent-space normal map renders with visible surface
      relief (lighting responds to the map) on CPU **and** GPU, qualitatively
      matching Cycles on the same material (side-by-side; the highlight moves with
      the mapped normal, handedness matches — a Cycles-baked normal map must not
      invert). Assert the shaded result differs from the flat-normal render by a
      stated mean|diff| in lit regions, and matches Cycles' lighting *direction*
      (not inverted).
- [ ] **Strength** scales the effect: Strength 0 ≈ flat-normal render (within MC
      noise); Strength 1 = full perturbation; intermediate monotonic.
- [ ] **No silent degradation:** an unsupported mode (e.g. Object/World space if not
      implemented) emits a VISIBLE `_degradation_report` entry, never a silent
      wrong-render (pairs with the existing degradation mechanism, memory
      `addon-constant-folds-shader-graph`).
- [ ] **Register gate (HARD):** `cuobjdump -res-usage` on the built `.pyd` — the
      `HasNormalPerturb=false` shade-fleet specializations are BYTE-IDENTICAL in
      REG/STACK to `main` (no fleet regression); the `=true` specializations stay
      REG:254 with a bounded STACK increase (report both histograms, like pkg219b/c).
      A spill = STOP + escalate.
- [ ] **CPU/GPU parity** within a per-channel mean-ratio band; visual inspection of
      both PNGs (no NaN/magenta/black, no banding).
- [ ] Addon registers correctly in headless Blender (new module in `ADDON_FILES`,
      panel/register smoke — memory `addon-packaging-file-list`); build the addon
      `.pyd` with `-DASTRORAY_DISABLE_OPENMP=ON` (memory
      `mingw_openmp_blender_deadlock`).
- [ ] **CI green** + **HW PASS** on RTX 5070 Ti (rebuild, canonical `.pyd`, sm_120).

## Build / verification notes

- Verify the normal-map render headlessly yourself in Blender 5.1/5.2 (memory
  `blender-5-1-installed-locally`); do NOT defer to the owner.
- Signature/ABI sweep before push (`cpp-abi-guard`): any change to the shade-stage
  material struct crossing CPU→GPU is ABI-reachable from the addon target (memory
  `cpu-only-carveout-misses-gpu-headers` — a CUDA-reachable `.h` change needs the
  HW leg, not just CI).
- Reuse the pkg219a coordinate/mapping path and the existing image-texture
  special-case; do NOT fork a new texture-sampling code path (CLAUDE.md §5b).

## Reference

- pkg219 (`pkg219-per-texel-shader-graph.md`, the deferred pkg219d note is the
  origin of this spec), pkg219a (coordinate/mapping unification — reuse it),
  pkg219b/c (the `<bool HasProgram>` isolation pattern to mirror).
- Cycles `intern/cycles/kernel/svm/svm_tex_coord.h` (`node_normal_map`),
  Mikk-TSpace tangent convention.
- `blender_addon/__init__.py` (`convert_shader_node`, `_degradation_report`),
  the GPU shade stage under `src/gpu/wavefront/`.
- Memory: `addon-constant-folds-shader-graph`,
  `wavefront-shade-kernels-register-saturated`,
  `closure-graph-lobe-count-spills-fused-kernel`, `addon-packaging-file-list`,
  `mingw_openmp_blender_deadlock`, `cpu-only-carveout-misses-gpu-headers`,
  `blender-5-1-installed-locally`.
