# pkg223b — Bump node: UV-aligned surface-gradient normal perturbation (pkg223 follow-up)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** M (CPU wiring is thin — the math already exists; GPU port +
register probe is the bulk of the work, mirroring pkg223's shape)
**Depends on:** pkg223 (normal-map infra: `c_wfTexBinding` side-table pattern,
`HasNormalPerturb` axis, UV-aligned tangent frame, addon wiring precedent),
pkg219a (coordinate/mapping path — reuse, don't re-plumb)

---

## Goal

Before: the Blender **Bump** node (`ShaderNodeBump`) silently no-ops — the addon
constant-folds it out of the shader graph (memory `addon-constant-folds-shader-graph`)
and neither the CPU nor GPU shade path reads a height texture. After: a material
with a Bump node feeding a BSDF's Normal input renders with visible relief on CPU
**and** GPU wavefront, at parity, using Cycles' own tangent-space-free
surface-gradient bump formula sourced from the existing UV-aligned tangent frame
as an approximation of the true screen-space ray differential Cycles' default
path uses (see §The derivatives problem for the fork and its accepted
trade-off) — no ray-differential plumbing required for this package.

---

## Confirmed root cause / current gap

Grep-verified 2026-08-29, mirroring pkg223's investigation method:

- **Addon (`blender_addon/`):** zero references to "bump" or "height" anywhere in
  `__init__.py`, `exporter.py`, `settings_map.py`. `ShaderNodeBump` is not
  special-cased in `convert_shader_node` — it constant-folds like any other
  unhandled node. **Confirmed silent no-op**, same class of gap as pkg223's
  Normal Map finding.
- **CPU:** the math already exists and is *more complete* than expected.
  `plugins/materials/normal_mapped.cpp`'s `NormalMappedPlugin` already carries
  `bumpTexture_`, `bumpStrength_`, `bumpDistance_`, a `heightValue()` luminance
  reducer, and a `perturbNormal()` branch that finite-differences the height
  texture via `Texture::valueOffset(rec, wo, du, dv)` (a generic UV-offset
  re-sample already defined on the `Texture` base class,
  `include/advanced_features.h:188`) and perturbs the normal:
  ```cpp
  float eps = std::max(1e-4f, bumpDistance_);
  float h0 = heightValue(bumpTexture_->value(rec, Vec3(0)));
  float hU = heightValue(bumpTexture_->valueOffset(rec, Vec3(0), eps, 0.0f));
  float hV = heightValue(bumpTexture_->valueOffset(rec, Vec3(0), 0.0f, eps));
  float dU = (hU - h0) / eps, dV = (hV - h0) / eps;
  Vec3 dp = rec.tangent * dU + rec.bitangent * dV;
  n = (n - dp * bumpStrength_).normalized();
  ```
  This CPU path is currently **dead code** — nothing constructs a
  `NormalMappedPlugin` with a non-null `bumpTexture_` (the addon never emits one,
  and `normalMapInner()`/`normalMapTexture()`/`normalMapStrength()`, the only
  accessors GPU upload reads, deliberately omit bump — see
  `normal_mapped.cpp:91-97`, "bump is CPU-only / deferred, memory pkg223").
  One CPU-side bug to fix in-flight: the existing bump branch perturbs against
  `rec.tangent`/`rec.bitangent` (the arbitrary ONB frame), **not**
  `rec.uvTangent`/`uvBitangentSign` (the UV-aligned Mikk-TSpace frame the Normal
  Map branch two lines above it correctly uses). A height gradient computed in UV
  space must be un-projected through the UV-aligned frame, or the relief tilts to
  an arbitrary compass direction exactly like the pre-pkg223 Normal Map bug this
  spec's sibling package fixed. Fix this as part of item 1 below.
- **GPU:** no `matBumpTexId`/`matBumpStrength`/`matBumpDistance` fields exist on
  `GWfTexBinding` (`include/astroray/gpu_types.h`), no upload site in
  `src/gpu/scene_upload.cu` or `src/gpu/wavefront/gpu_wavefront_snapshot.cu`, and
  the `HasNormalPerturb` block in `src/gpu/wavefront/stage_advance.cu` (~L992-1048)
  only decodes a tangent-space normal texture — it has no height-texture branch.
  **Confirmed: GPU has zero Bump support**, same as it had zero Normal Map support
  before pkg223.

---

## The derivatives problem (the crux)

Verified 2026-08-29 by reading the live source at
`github.com/blender/cycles/blob/main/src/kernel/svm/displace.h`
(`svm_node_set_bump`) and `.../svm/bump.h` (`svm_node_enter_bump_eval`) — quoting
the exact function so this citation is checkable, not paraphrased:

```c
// src/kernel/svm/displace.h — svm_node_set_bump (abridged, full body verified)
differential3 dP;
if (node.bump_state_offset == SVM_STACK_INVALID) {
  dP = differential_from_compact(sd->Ng, sd->dP);   // true ray differential
} else {
  dP.dx = stack_load_float3(stack, node.bump_state_offset + 4);
  dP.dy = stack_load_float3(stack, node.bump_state_offset + 7);
}
const float3 Rx = cross(dP.dy, normal_in);
const float3 Ry = cross(normal_in, dP.dx);
const float h_c = stack_load_float(stack, node.center_offset);
const float h_x = stack_load_float(stack, node.dx_offset);
const float h_y = stack_load_float(stack, node.dy_offset);
const float det = dot(dP.dx, Rx);
const float3 surfgrad = (h_x - h_c) * Rx + (h_y - h_c) * Ry;
float3 normal_out = safe_normalize(node.bump_filter_width * fabsf(det) * normal_in
                                    - scale * signf(det) * surfgrad);
normal_out = normalize(strength * normal_out + (1.0f - strength) * normal_in);
```

**This overturns the initial assumption in the pkg223 spec and the
NEXT_STAGE_REPORT handoff note** (both speculated Bump needs "screen-space or
analytic derivatives" without citing the source) in one respect and confirms it
in another:

- **Confirmed:** Cycles' `dP.dx`/`dP.dy` in the default path
  (`node.bump_state_offset == SVM_STACK_INVALID`) really are **true
  ray-differential position derivatives** (`differential_from_compact(sd->Ng,
  sd->dP)` — the Igehy-style per-pixel screen-space footprint Cycles propagates
  through every bounce for texture-filtering *and* reuses here). So "Bump needs
  screen-space derivatives" is not a false lead — it is literally how production
  Cycles computes it. Astroray currently has **no ray-differential
  infrastructure anywhere** (not for texture LOD, not for anything) — building
  it means new per-ray `dPdx`/`dPdy` SoA state propagated through every wavefront
  bounce/stage, a materially larger and more invasive change than pkg223.
  Register/bandwidth cost on the already REG:254-pinned shade kernel is unknown
  and would need its own probe-first investigation independent of Bump itself.
- **The one relief valve:** the *other* code path (`bump_state_offset !=
  SVM_STACK_INVALID`, taken when Bump is evaluated as part of a chained/nested
  shader sub-eval via `svm_node_enter_bump_eval`) loads `dP.dx`/`dP.dy` from a
  **saved differential of the surface's own (undisplaced) position attribute**
  — which for a plain UV-parameterized surface reduces to the surface's
  parametric tangent-plane basis, i.e. something proportional to `dP/du`,
  `dP/dv` — not the camera-ray footprint. Cycles uses this same `Rx`/`Ry`/
  `surfgrad`/`det` formula in both cases; only the source of `dP.dx`/`dP.dy`
  differs. This means the **formula itself is derivative-source-agnostic** — it
  is a tangent-space-free "surface gradient" bump technique (cf. Mikkelsen,
  "Bump Mapping Unparametrized Surfaces on the GPU", 2010 — the same author as
  the Mikk-TSpace convention pkg223 already cites) that only needs *some* pair
  of non-parallel tangent-plane offset vectors and the height response along
  each — it does not intrinsically require the screen-space footprint.

**The real fork for the owner (not a forced binary — present as-is):**

1. **Build ray-differential propagation** (ports `dP.dx`/`dP.dy` through the
   wavefront pipeline, matches Cycles' default path exactly, bit-for-bit
   derivative technique). Correct, but scope is an infrastructure project in its
   own right — new per-ray state on every stage, unknown register/bandwidth cost
   on the pinned shade kernel, and (per the pkg131 precedent of surfacing
   architecture prerequisites rather than quietly absorbing them) probably
   deserves its own spec/architect pass rather than living inside "add the Bump
   node."
2. **Reuse Cycles' own `Rx`/`Ry`/`surfgrad` formula, but source `dP.dx`/`dP.dy`
   from the existing UV-aligned tangent frame** (`gpu_pr_uvAlignedTangent`'s
   `nT`/`B`, scaled by the node's "Distance" input as the finite-difference step
   — i.e. take the `bump_state_offset != SVM_STACK_INVALID` code path's
   *meaning* — a parametric surface differential — without literally
   reconstructing Cycles' dual-number attribute machinery). Reuses 100% of
   pkg223's infrastructure (`c_wfTexBinding`, UV-aligned tangent,
   `HasNormalPerturb` isolation), matches Cycles' math structure and handedness
   exactly (same cross-product formula, same sign convention), and is a much
   smaller, self-contained lift. **Trade-off to be explicit about:** this is an
   approximation of Cycles' *default* rendering mode specifically in the source
   of the derivative (parametric-UV-step vs. true screen footprint) — it will
   not reproduce Cycles' anti-aliasing/minification behavior of bump detail at
   grazing angles or distance (where the true ray footprint widens and Cycles'
   bump naturally softens/filters), but reproduces the correct relief direction,
   magnitude, and Strength/Distance semantics for a static camera framing.

**Recommendation:** approach 2, for the same reason pkg223 stayed scoped to
Normal-Map-only rather than absorbing a coordinate-system rewrite — it delivers
the visible, controllable relief that "Bump silently does nothing" is blocking,
reuses proven infrastructure, and keeps the register-probe surface small enough
to reason about. Flag the anti-aliasing gap as a known, accepted approximation
in the PR description; file true ray-differential propagation as a separate
future package if the owner wants exact parity (it would also benefit texture
minification/LOD generally, not just Bump — an argument for scoping it
independently rather than motivating it off this package alone).

**Cite before coding (CLAUDE.md §6):** save a research note with the verified
`svm_node_set_bump` quote above, the citation to Mikkelsen's tangent-space-free
bump technique, and the exact `Rx`/`Ry`/`surfgrad`/`det`/`safe_normalize` formula
translated to use the UV-aligned `nT`/`B` in place of `dP.dx`/`dP.dy`. **Do not
carry forward the current CPU `normal_mapped.cpp` bump formula as-is** — it uses
a simpler `n - (tangent*dU + bitangent*dV)*strength` projection that is neither
Cycles' exact formula nor on the UV-aligned frame (see the CPU bug noted above);
replace it with the verified `Rx`/`Ry` formula for both correctness and
CPU/GPU-mirroring simplicity.

---

## Register discipline

**Mandatory up-front probe** before writing feature code: `cuobjdump -res-usage`
on the current `main` `stageShadeBucketedKernel<0,...>` fleet baseline — the
handoff's stated current baseline (post pkg201-S3 item A) is REG:254 / STACK:3360
/ CONSTANT[0]:1708; re-measure and record the actual numbers from the checked-out
`.pyd` rather than trusting the cited figures, per CLAUDE.md's stale-.pyd
discipline. Height-texture id/strength/distance ride the `c_wfTexBinding` side
table (three new arrays: `matBumpTexId[]`, `matBumpStrength[]`,
`matBumpDistance[]`, or pack strength+distance into one `float2`-shaped array if
that reads cleaner) — **not** `GMaterial`, which must stay 640 B, mirroring
pkg223 exactly (memory `shade-axis-side-table-avoids-spill`).

**Key decision — share `HasNormalPerturb` or add a new axis?**

Bump and Normal Map both do the same *shape* of work: sample a texture at the
hit UV, derive a perturbed shading normal, lerp/apply it, rebuild the ONB, before
the BSDF is touched. They are mutually exclusive per-material in Blender (a
material's Normal socket takes either a Normal Map output or a Bump output, not
both simultaneously in the common case — though Blender does technically allow
chaining Bump-of-Normal-Map). Two options:

- **Option A — share the existing `HasNormalPerturb` axis.** Rename its intent
  slightly ("has a shading-normal perturbation of either kind") and branch
  *inside* the `if constexpr (HasNormalPerturb)` block on a runtime check of
  which texture id is set (`matNormalTexId[mat] >= 0` vs `matBumpTexId[mat] >= 0`,
  mutually exclusive per material). **Zero new specializations** — the fleet
  stays at 128 (pkg223's count), and the extra code (3 texture samples instead
  of 1, for the height central-difference) is compiled into the *same* `<true>`
  kernel that already carries the normal-map branch, so it only costs registers
  in the branch that was already isolated from the `<false>` fleet. Risk: the
  `<true>` kernel's register footprint grows for the union of both features even
  when a scene uses only one, though `if constexpr`/runtime branching on
  `matBumpTexId<0` means the extra texture fetches don't execute — but they may
  still contribute to the compiler's static register allocation for the
  kernel body (the general register-pressure lesson from
  `closure-graph-lobe-count-spills-fused-kernel`: it's live *range*, not dynamic
  execution, that spills registers). Must be probed, not assumed safe.
- **Option B — new `template<bool HasBumpPerturb>` axis.** Clean separation,
  guarantees a Normal-Map-only scene's `<true>` kernel is untouched by Bump code.
  Cost: doubles `stage_advance.cu`'s specialization count from 128 to 256
  (pkg223's own report already flagged 128 specializations at ~9 min compile as
  the current ceiling), for a feature whose runtime code is small.

**Recommendation: Option A (share the axis), probe-first**, consistent with the
owner's pkg201-S3 decision (`pkg201-s3-runtime-comparison-not-axis` memory) to
prefer a runtime branch over a new compile-time axis and only fall back to
compile-time isolation if the probe shows a spill on the *shared* branch
specifically. Concretely: extend the existing `HasNormalPerturb` block to try
Normal Map first (as today), then independently try Bump if
`matBumpTexId[rec.materialId] >= 0`, using the same UV-aligned tangent
(`nT`/`nSign` already computed) so the incremental code is the 3-tap height
finite-difference plus the tangent-plane projection — not a second full tangent
frame rebuild. If the probe shows the shared `<true>` kernel spills where the
Normal-Map-only `<true>` kernel didn't, escalate to Option B for the specific
spilling path (isolate just the Bump texture-fetch block), per the register
ledger's established escalation pattern — do not pre-emptively build Option B.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` (`convert_shader_node`) | Detect a `ShaderNodeBump` feeding a BSDF `Normal` input; emit a per-material bump spec: height-texture handle (reuse the pkg219a coordinate/mapping path), Strength, Distance. If a Normal Map and Bump are chained, degrade the unsupported combination VISIBLY via `_degradation_report`, don't silently pick one. |
| `blender_addon/__init__.py` (`ADDON_FILES` if a new module is added) | Register any new addon module (memory `addon-packaging-file-list`). |
| `plugins/materials/normal_mapped.cpp` | Replace the bump branch's formula with the verified Cycles `Rx`/`Ry`/`surfgrad`/`det` surface-gradient formula (see §The derivatives problem), sourcing `dP.dx`/`dP.dy` from `rec.uvTangent`/`(rec.normal.cross(uvTangent)*uvBitangentSign)` scaled by the node's Distance — not `rec.tangent`/`rec.bitangent` (the arbitrary ONB frame the current dead code uses). Wire the addon-emitted bump texture/strength/distance into `NormalMappedPlugin` construction (the constructor already accepts them). |
| `plugins/materials/normal_mapped.cpp` (`normalMapTexture()`/accessors) | Add `bumpMapTexture()`/`bumpMapStrength()`/`bumpMapDistance()` accessors (or extend the existing `normalMap*` accessors) so GPU upload can read them — currently deliberately omitted ("bump is CPU-only / deferred"). |
| `include/astroray/gpu_types.h` | Add `matBumpTexId`, `matBumpStrength`, `matBumpDistance` arrays to the `c_wfTexBinding`-adjacent struct (mirror `matNormalTexId`/`matNormalStrength` at line ~628-632). |
| `src/gpu/scene_upload.cu` | Upload the bump texture/strength/distance alongside the existing normal-map upload (~L708-709, ~L923). |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | `wfUpload` the new arrays alongside `d_matNormalTexId`/`d_matNormalStrength` (~L1389-1393). |
| `src/gpu/wavefront/stage_advance.cu` | Inside the existing `if constexpr (HasNormalPerturb)` block (~L992-1048), after the Normal Map branch, add the Bump branch: 3-tap height finite-difference (`h_c`, `h_x`, `h_y`) at `(uu,vv)`, `(uu+eps,vv)`, `(uu,vv+eps)` using the same UV-aligned `nT`/`nSign`/barycentric-UV already computed, feed into the verified `Rx = cross(dP.dy, N)`, `Ry = cross(N, dP.dx)`, `surfgrad`, `det`, `safe_normalize` formula (§The derivatives problem) with `dP.dx = eps*nT`, `dP.dy = eps*B`, rebuild ONB. Byte-mirror the corrected CPU math exactly for parity. |
| `include/raytracer.h`, `include/astroray/gpu_wavefront_state.h` | Update the pkg223 comments referencing `matNormalTexId`/`matNormalStrength` as "the normal-texture arrays" to also cover the new bump arrays, per existing comment style. |

### Key design decisions

- **Height reduction:** reuse `heightValue()`'s Rec.709 luminance weights
  (`0.2126/0.7152/0.0722`) already in `normal_mapped.cpp` — confirm against the
  cited Cycles source whether Cycles uses the same luma weights or a different
  height-channel convention (e.g. some Bump setups feed a grayscale/non-color
  texture where R=G=B already, making the weighting moot; note this in the
  research note rather than assuming).
- **Step size (`eps`/Distance):** mirror the CPU's `std::max(1e-4f, bumpDistance_)`
  floor to avoid a divide-by-~0 in the UV-space finite difference.
- **Mutual exclusion with Normal Map:** per §Key decision above, branch at
  runtime on which texture id is set; if the owner wants chained Bump-of-Normal
  supported later, that is an explicit follow-up, not silently attempted here.

---

## Acceptance criteria

- [ ] A quad/sphere with a height-texture-driven Bump node renders with visible
      surface relief (lighting responds to the bump) on CPU **and** GPU,
      qualitatively matching Cycles on the same material and Distance/Strength
      values (side-by-side comparison).
- [ ] **Strength** scales the effect: Strength 0 ≈ flat-normal render (within MC
      noise); intermediate monotonic.
- [ ] **CPU bug fixed + formula corrected:** the bump branch uses the verified
      Cycles `Rx`/`Ry`/`surfgrad`/`det` surface-gradient formula sourced from
      `rec.uvTangent`/`uvBitangentSign` (the UV-aligned frame), not the old
      simpler tangent/bitangent projection on the arbitrary ONB frame; a rotated
      UV island's bump relief tracks the texture's parameterization, not a fixed
      world direction, and handedness matches Cycles (no inverted relief).
- [ ] **No silent degradation:** an unsupported combination (e.g. Bump chained
      after Normal Map) emits a VISIBLE `_degradation_report` entry.
- [ ] **Register gate (HARD):** up-front `cuobjdump -res-usage` baseline captured
      from the actual built `.pyd` before feature code. Post-feature: report
      REG/STACK/CONSTANT histograms for the shared-axis `<true>` kernel vs the
      pkg223 `<true>` baseline and the `<false>` fleet (must stay byte-identical
      to pre-pkg223b `<false>`). A spill on the shared axis triggers the Option B
      escalation described above — do not ship a fleet-wide regression.
- [ ] **CPU/GPU parity** within a per-channel mean-ratio band; visual inspection
      of both PNGs (no NaN/magenta/black, no banding).
- [ ] A render-level test analogous to `tests/test_pkg223_gpu_normal_map.py`
      (bump-relief-visible + Strength-monotonic + CPU/GPU parity).
- [ ] Addon registers correctly in headless Blender if a new module was added;
      build with `-DASTRORAY_DISABLE_OPENMP=ON`.
- [ ] **CI green** + **HW PASS** on RTX 5070 Ti.

---

## Non-goals

- **True displacement (geometry perturbation) is OUT.** Bump only perturbs the
  shading normal fed to the BSDF; it never moves the actual hit point or mesh
  geometry (Blender's separate "Displacement" material output / adaptive
  subdivision is out of scope here).
- Chained Bump-of-Normal-Map (or vice versa) support is deferred; degrade
  visibly, don't implement the composition.
- Ray-differential propagation (approach 1 in §The derivatives problem) is OUT
  of this package's scope — it is a legitimate, more-exact alternative (it is
  literally Cycles' default derivative source), but is an infrastructure
  project in its own right; do not fold it into this package without a new
  owner decision. This package ships approach 2 (UV-aligned parametric
  derivative through Cycles' own surface-gradient formula).
- Object/World-space bump variants (if Blender's Bump node exposes them) beyond
  the standard tangent-space UV height map are out unless trivial; degrade
  visibly otherwise (mirror pkg223's Normal Map precedent).

---

## Progress

- [ ] Research note: save the verified `svm_node_set_bump` quote
      (`src/kernel/svm/displace.h`), the `svm_node_enter_bump_eval` context
      (`src/kernel/svm/bump.h`), and the Mikkelsen surface-gradient citation
      under `.astroray_plan/docs/`.
- [ ] Fix CPU `NormalMappedPlugin` bump branch to use the UV-aligned frame.
- [ ] Addon: detect + export `ShaderNodeBump`.
- [ ] GPU: side-table fields, upload, shade-stage branch (shared axis, probe-first).
- [ ] Register probe (baseline, then post-feature); escalate to Option B only on
      a demonstrated spill.
- [ ] Tests + HW verify.

---

## Lessons

*(Fill in after the package is done.)*
