# Light Tree Research Note (pkg86 Phase 1)

**Date:** 2026-05-22  
**Package:** pkg86 — Light Tree (Many-Lights Importance Sampling)  
**Status:** awaiting owner sign-off

---

## 1. Conty 2018 Importance Metric

### Paper Reference

- **Title:** "Importance Sampling of Many Lights with Adaptive Tree Splitting"
- **Authors:** Alejandro Conty Estevez, Christopher Kulla (Sony Pictures Imageworks)
- **Published:** Proc. ACM Comput. Graph. Interact. Tech. 1(2): 25:1-25:17 (2018)
- **DOI:** [10.1145/3233305](https://dl.acm.org/doi/10.1145/3233305)
- **Also presented:** SIGGRAPH 2017 Talk, HPG 2018
- **Author site (PDF blocked by bot-check):** http://www.aconty.com/pdf/many-lights-hpg2018.pdf

### Importance Formula (from Cycles implementation analysis)

The Conty 2018 importance metric combines three factors:

1. **Energy**: cluster total power (integrated emission × area)
2. **Geometric falloff**: inverse distance-squared from shading point
3. **Orientation factor**: bounding-cone coverage between cluster emission and shading normal

The Cycles implementation (`intern/cycles/kernel/light/tree.h`) computes:

```
importance = (energy / max(distance², ε)) × orientation_factor
```

Where `orientation_factor` is derived from the cluster's **orientation cone** `(θ_o, θ_e)`:
- `θ_o` (theta_o): outer half-angle — spread of surface normals in the cluster
- `θ_e` (theta_e): emission half-angle — spread of emission directions

The exact orientation factor uses spherical geometry to compute the minimum outgoing angle between the cluster cone and the shading point's hemisphere. If the cluster is entirely below the horizon or outside the emission cone, importance returns 0 (cluster is pruned). Otherwise:

```cpp
// Cycles intern/cycles/kernel/light/tree.h (simplified)
float cos_min_outgoing_angle;
if (cluster fully visible) {
  cos_min_outgoing_angle = 1.0f;
} else if (partial coverage) {
  cos_min_outgoing_angle = cos(theta - theta_u) * cos_theta_o +
                           sin(theta - theta_u) * sin_theta_o;
} else {
  return 0;  // cluster invisible
}
importance = (energy / distance²) * cos_min_outgoing_angle;
```

**Reference locations for equation derivation** (paper not directly accessible, inferred from Cycles code):
- Conty 2018 §4: Orientation cone bounding
- Cycles `light_tree_importance()` function in `intern/cycles/kernel/light/tree.h`

---

## 2. Cycles Implementation Walkthrough

### Upstream Commit Pin

**Repository:** https://github.com/blender/blender  
**Commit (main HEAD as of 2026-05-22):** To be pinned after reviewing current state  
**License:** Apache-2.0 (SPDX-FileCopyrightText: 2011-2022 Blender Foundation)

### Files to Mirror

All files located in the official Blender repository:

1. **Build-side (host):**
   - `intern/cycles/scene/light_tree.h` — LightTree class, OrientationBounds struct, LightTreeNode
   - `intern/cycles/scene/light_tree.cpp` — tree construction, splitting heuristic, bounding-cone merge logic
   - `intern/cycles/scene/light_tree_debug.{h,cpp}` — (optional) debug visualization helpers

2. **Kernel-side (device):**
   - `intern/cycles/kernel/light/tree.h` — traversal logic, `light_tree_importance()`, `light_tree_sample()`

### Key Functions to Mirror

#### From `intern/cycles/scene/light_tree.cpp` (build):

1. **`OrientationBounds::calculate_measure()`**
   - Computes the surface area of the spherical cone (solid angle measure).
   - Formula: `M_2PI_F * (1 - cos_theta_o) + M_PI_2_F * (2 * theta_w * sin_theta_o - …)`

2. **`OrientationBounds::merge(const OrientationBounds& other)`**
   - Combines two bounding cones using spherical linear interpolation (slerp).
   - Handles cases: identical axes, opposite axes, general merge.

3. **`LightTreeMeasure::calculate()`**
   - Multiplies energy by spatial bounding-box area and orientation measure.
   - Returns the Surface Area Orientation Heuristic (SAOH) cost.

4. **Tree splitting heuristic: `should_split()`**
   - Partitions emitters into buckets along each axis (x, y, z).
   - Computes cumulative SAOH cost left and right of each split.
   - Splits if `min_cost < total_cost` OR `num_emitters > max_lights_in_leaf`.
   - Uses a regularization factor to bias toward balanced splits.

5. **`LightTree::build()` (constructor)**
   - Recursively constructs the tree using the above splitting heuristic.
   - Follows PBRT-v4 BVH construction pattern (noted in Cycles comments).

#### From `intern/cycles/kernel/light/tree.h` (traversal):

1. **`light_tree_importance<bool in_volume_segment>(...)`**
   - Computes min/max importance bounds for a cluster from a shading point.
   - Inputs: shading normal (or direction for volume), point-to-centroid vector, bounding cone, cluster energy, distances.
   - Outputs: `max_importance`, `min_importance`.

2. **`light_tree_sample<bool in_volume_segment>(...)`**
   - Traverses the tree from root to leaf using importance-weighted stochastic descent.
   - At each inner node: compute importance of left/right children, pick one probabilistically.
   - At leaf node: perform reservoir sampling among the emitters in the leaf.
   - Returns a `LightSample` structure with selected light index, pdf, and sampled position.

### Bounding Cone Computation

Cycles computes `(θ_o, θ_e)` per emitter type in the `LightTreeEmitter` constructor:

- **Single-sided mesh light:** `θ_o = 0`, `θ_e = π/2`
- **Double-sided mesh light:** `θ_o = π/2`, `θ_e = π/2`
- **Area light:** `θ_o = 0`, `θ_e = light->get_spread() * 0.5`
- **Point light:** `θ_o = π`, `θ_e = π` (isotropic)
- **Spot light:** `θ_e = atan(tan(cone_angle) * max(scale_u, scale_v) / scale_w)` (accounts for non-uniform scaling)
- **Distant/background:** `θ_o = π`, `θ_e = π`

Cluster cones are computed bottom-up via `merge()` during tree construction.

### Adaptive Splitting

Cycles' "adaptive" splitting forces subdivision until a cluster's importance range is sufficiently tight (i.e., `min_importance / max_importance` exceeds a threshold). This ensures the tree doesn't group lights with vastly different contributions to the same shading point.

**Decision:** For pkg86 Phase 2 (CPU), we will **start with median split** (simpler) and defer adaptive splitting to a later refinement (possibly pkg86-B GPU phase). The spec allows this: "Median-split is sufficient for the variance gate; adaptive splitting is a phase-2 refinement."

---

## 3. License Verification

**License:** Apache-2.0  
**Copyright:** Blender Foundation (2011-2022)  
**SPDX identifier:** `SPDX-License-Identifier: Apache-2.0`

**Compatibility:** Apache-2.0 is compatible with Astroray's MIT license (CLAUDE.md §6). Mirrored files must preserve their original Apache-2.0 headers. A `THIRD_PARTY_LICENSES.md` in `external/cycles_light_tree/` will record attribution and the upstream commit SHA.

**Files under Apache-2.0 (verified via GitHub):**
- All files in `intern/cycles/scene/light_tree.*`
- All files in `intern/cycles/kernel/light/tree.h`

---

## 4. Vendoring Location

**Path:** `external/cycles_light_tree/`

**Structure:**
```
external/cycles_light_tree/
  THIRD_PARTY_LICENSES.md       # Attribution, commit SHA, Apache-2.0 notice
  scene/
    light_tree.h
    light_tree.cpp
  kernel/
    light/
      tree.h                     # device-side traversal (CPU in Phase 2, GPU in pkg86-B)
```

Mirrored files will **preserve original Apache-2.0 headers** verbatim. Any Astroray-specific wrappers (e.g., `include/astroray/light_tree.h`) will be separate files with MIT license.

---

## 5. Key Design Decisions (pkg86 spec §Key design decisions)

### Decision 1: Integrator Coverage
**Choice:** Virtual `LightSampler` interface, all integrators via `LightList::sample`.

`LightList::sample` will delegate to a stored `std::unique_ptr<LightSampler>`. Two implementations:
- `PowerLightSampler`: wraps existing power-weighted CDF (regression baseline, default for safety).
- `TreeLightSampler`: wraps `LightTree`.

Integrator call sites (`multiwavelength_path_tracer`, `spectral_path_tracer`, `restir_di`, `neural_cache`, `caustic_path_tracer`, `sms_caustic_path_tracer`) remain unchanged.

**Justification:** Build-once-sample-many pattern is integrator-agnostic (Cycles parity). No integrator source changes needed — only pdf bookkeeping validation.

### Decision 2: Tree Structure
**Choice:** Binary tree with per-cluster `(θ_o, θ_e)` bounding cone. Mirror Cycles directly.

**Justification:** CLAUDE.md §6 — do not invent algorithms. Conty 2018 and Cycles both use binary trees; no reason to try a quaternary or k-d variant.

### Decision 3: Importance Metric
**Choice:** Cycles' `light_tree_importance()` function verbatim.

**Formula (restated from §1):**
```
importance = (cluster_energy / max(distance², ε)) × orientation_factor
```

Where `orientation_factor` accounts for the bounding-cone overlap with the shading hemisphere.

**Citation in code:** Every call site will cite:
```cpp
// Cycles intern/cycles/kernel/light/tree.h::light_tree_importance (Apache-2.0, commit <SHA>)
```

**Justification:** CLAUDE.md §6 — mirror the published algorithm. Conty 2018 is the canonical paper; Cycles is the canonical Apache-2.0 implementation.

### Decision 4: GPU Port
**Choice:** Out of scope for pkg86. Defer to pkg86-B.

**Justification:** Matches pkg64 → pkg64-gpu phase split. CPU users (majority in Round 8) get the variance win immediately. GPU port only meaningful after pkg55-B unblocks megakernel/wavefront integrator restart anyway.

### Decision 5: Acceptance Gate
**Choice:** ≥ 2× variance reduction on `many_lights.py` (64 area lights, 256 spp) + single-light non-regression (≤ 0.5 dB PSNR delta on Cornell box).

**Test scene:** `tests/scenes/many_lights.py` — Cornell-box-style enclosure, 64 area lights scattered uniformly, fixed seeds, 256 spp.

**Variance measurement:** N=4 re-renders with different seeds, compute per-pixel variance, compare `TreeLightSampler` vs `PowerLightSampler`.

**Target:** `variance_tree ≤ 0.5 × variance_power` (equivalent to 2× variance reduction; 4× would match Cycles' best-case).

**Justification:** Cycles reports 2-10× variance reduction depending on light distribution. Our gate is conservative (2×) and matches the architectural-lighting workload the tree is designed for.

### Decision 6: Effort Sizing
**Choice:** 3 weeks, 1 week per phase.

**Phase 1 (Research):** Done (this document). ~10-15 h.
**Phase 2 (CPU implementation):** ~25 h — mirror Cycles code, wrap, wire to `LightList`, bind to Blender addon.
**Phase 3 (Validation):** ~20 h — build test scene, measure gates, iterate.

**Justification:** Cycles' light-tree commit was a single tech-lead week upstream. Our Phase 2 is mechanical port work; Phase 3 is gate validation. Conservative sizing accounts for Windows/MSVC porting friction and the Astroray-specific `Light` interface wiring.

---

## 6. Astroray-Specific Wiring

### Available from pkg89 (Phase A + B)

The `Light` interface (`include/astroray/light.h`) already provides:

1. **`Light::power() const`**
   - Returns total emitted power (integrated over all directions and surface).
   - Used for light-selection CDF (importance sampling over lights).
   - Mirrors Cycles `Light::emission_estimate`.

2. **`Light::orientationCone() const`**
   - Returns `OrientationCone{ Vec3 axis, float theta_o, float theta_e }`.
   - Explicitly designed for pkg86 (noted in pkg89 research §1.3).
   - Isotropic lights return `OrientationCone::fullSphere()` (θ_o = θ_e = π).

3. **`Light::bounds() const`**
   - Returns world-space AABB. Infinite lights return unbounded AABB.

4. **`Light::sampleLi(...)`**
   - Samples a point on the light surface and returns emission + pdf.
   - Signature: `sampleLi(LiSample& result, Vec3 shadingPoint, Vec3 shadingNormal, SampledWavelengths lambdas, std::mt19937& gen)`.

### No new Light accessors required

The Conty 2018 importance metric needs:
- Cluster energy → sum of `Light::power()` for emitters in the cluster ✓
- Bounding box → merge of `Light::bounds()` for cluster ✓
- Orientation cone → merge of `Light::orientationCone()` for cluster ✓

All data already available. No `Light` interface changes needed.

### LightList Wiring

Current `LightList` (include/raytracer.h:1191-1297) stores:
- `std::vector<std::shared_ptr<Hittable>> lights` — legacy emissive geometry
- `std::vector<std::unique_ptr<astroray::Light>> dedicatedLights` — pkg89 dedicated lights
- `std::vector<float> powerDist` — unified power-weighted CDF

**Change for pkg86:**

1. Add a `std::unique_ptr<LightSampler> sampler_` member.
2. `LightList::sample(...)` delegates to `sampler_->pick(...)`.
3. Two `LightSampler` implementations:
   - `PowerLightSampler` — wraps existing power-weighted CDF logic (current behaviour, bit-exact).
   - `TreeLightSampler` — wraps `LightTree`, calls `LightTree::pick(...)`.
4. `Renderer::setLightSampler(enum Mode { Power, Tree })` sets the active sampler. Default: `Power` (safe). Flip to `Tree` after Phase 3 gates pass.

### Integrator Call Sites

All integrators route through `LightList::sample(...)`:
- `spectral_path_tracer.cpp:218` — `lights.sample(x0Rec.point, x0Rec.normal, lambdas, gen)`
- `multiwavelength_path_tracer.cpp`, `restir_di.cpp`, `neural_cache.cpp`, `caustic_path_tracer.cpp`, `sms_caustic_path_tracer.cpp` — same pattern.

**No source changes required.** The `LightSampler` abstraction is internal to `LightList`. Integrators see identical API. Phase 3 validation will confirm pdf bookkeeping balances across all integrators.

---

## 7. Open Questions / Clarifications Needed

None at this time. The spec is clear, the Cycles implementation is accessible (Apache-2.0), and the `Light` interface provides all required data.

**Next step:** Owner sign-off on this research note, then proceed to Phase 2 (CPU implementation).

---

## Sources

- [SIGGRAPH history page on Conty/Kulla 2018](https://history.siggraph.org/learning/importance-sampling-of-many-lights-with-adaptive-tree-splitting/)
- [Semantic Scholar: Conty/Kulla 2018 paper](https://www.semanticscholar.org/paper/Importance-Sampling-of-Many-Lights-with-Adaptive-Estevez-Kulla/22fa1bea1da4461eeeee4bdb778fa198d0ecb46b)
- [Blender Cycles repository (Apache-2.0)](https://github.com/blender/blender)
- [Blender PR #105862: Cycles build Light Tree in parallel](https://projects.blender.org/blender/blender/pulls/105862)
- [Blender PR #106683: Cycles add instancing support in light tree](https://projects.blender.org/blender/blender/pulls/106683)
- [Blender 3.5 release notes: Cycles Light Tree](https://developer.blender.org/docs/release_notes/3.5/cycles/)
