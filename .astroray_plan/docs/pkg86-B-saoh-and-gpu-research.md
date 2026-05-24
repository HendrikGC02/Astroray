# pkg86-B SAOH and GPU Research Note (Phase 1)

**Date:** 2026-05-24  
**Package:** pkg86-B — Light Tree GPU port + SAOH adaptive splitting  
**Phase:** 1 (CPU SAOH refinement)  
**Status:** Phase 1 research addendum

---

## 1. SAOH Split-Cost Formula (Conty 2018 eq 8)

### Surface-Area-Orientation Heuristic (SAOH)

The SAOH cost function combines spatial and directional clustering quality into a single metric that guides the tree split decision. From Conty Estevez & Kulla 2018 §4.2:

**Cost function:**
```
C(S) = M(left) + M(right)
```

where `M(C)` is the "measure" of cluster `C`:
```
M(C) = energy(C) · bbox_area(C) · orientation_measure(C)
```

**Terms:**

1. **energy(C):** Sum of power (integrated emission × area) of all lights in the cluster.
2. **bbox_area(C):** Surface area of the axis-aligned bounding box enclosing the cluster.
3. **orientation_measure(C):** Solid angle / surface area of the spherical bounding cone, computed via `OrientationBounds::measure()`.

The exact formula for `orientation_measure` (from Cycles `scene/light_tree.cpp::OrientationBounds::calculate_measure`, lines 14-27):

```cpp
const float theta_w = min(π, theta_o + theta_e);
const float cos_theta_o = cos(theta_o);
const float sin_theta_o = sin(theta_o);

measure = 2π * (1 - cos_theta_o) + 
          (π/2) * (2 * theta_w * sin_theta_o - 
                   cos(theta_o - 2 * theta_w) - 
                   2 * theta_o * sin_theta_o + 
                   cos_theta_o);
```

This is the surface area of the spherical lune defined by the bounding cone `(axis, theta_o, theta_e)`.

**Split decision:**

For each axis (x, y, z), partition the emitters into N bins (Cycles uses 12) along that axis based on their centroids. For each bin boundary, compute:
- Left cost: `M(left)` = measure of emitters [start, bin)
- Right cost: `M(right)` = measure of emitters [bin, end)
- Total cost: `M(left) + M(right)`

The split that minimizes total cost is chosen. If `min_cost >= total_cluster_cost`, no split is performed (force leaf).

**Cycles reference:**
- `intern/cycles/scene/light_tree.cpp::LightTree::recursive_build` (commit e52e5eb0)
- `intern/cycles/scene/light_tree.cpp::LightTreeMeasure::calculate`

---

## 2. Full Conty 2018 Importance Formula (Conty eq 11)

The importance metric determines the probability of selecting a cluster at each tree traversal step. From Conty 2018 §4.4 and Cycles `kernel/light/tree.h::light_tree_importance<false>`:

**Importance formula:**
```
importance = (energy / max(distance², ε)) · orientation_factor
```

**Terms:**

1. **energy:** Cluster total power (sum of all emitters' `Light::power()`).
2. **distance:** Distance from shading point to cluster centroid (or bounding-box closest point in some variants).
3. **orientation_factor:** Cosine of the minimum outgoing angle between the cluster's emission cone and the shading hemisphere.

### Orientation Factor (Cone-Cone Visibility)

The key innovation in Conty 2018 is the **cone-cone pruning** that returns `importance = 0` when the cluster cone cannot illuminate the shading hemisphere.

Given:
- Shading normal `N`
- Cluster bounding cone `(axis, theta_o, theta_e)` where:
  - `axis` = cluster emission axis
  - `theta_o` = outer half-angle (spread of surface normals)
  - `theta_e` = emission half-angle (spread of emission directions)
- Vector `to_cluster = cluster_centroid - shading_point`
- `theta_i = acos(normalize(to_cluster) · axis)` — angle between view direction and cluster axis
- `theta_u = asin(bbox_radius / distance)` — subtended half-angle of the cluster bounding sphere

**Visibility test:**

If `theta_i - theta_u > theta_o + theta_e + π/2`, the cluster is entirely outside the shading hemisphere → return `importance = 0` (prune).

**Cosine reduction:**

When the cluster is partially or fully visible, compute the minimum outgoing cosine using spherical geometry (Cycles `light_tree_cos_min_incoming_angle` in `kernel/light/tree.h`):

```cpp
float cos_min_outgoing_angle;
if (cluster_fully_visible) {
    cos_min_outgoing_angle = 1.0f;
} else {
    // Partial overlap: spherical trigonometry
    cos_min_outgoing_angle = cos(theta - theta_u) * cos(theta_o) + 
                             sin(theta - theta_u) * sin(theta_o);
}
cos_min_outgoing_angle = max(0.0f, cos_min_outgoing_angle);
importance = (energy / distance²) * cos_min_outgoing_angle;
```

This is the formula that replaces the simplified `max(0, normal · axis)` approximation in pkg86.

**Cycles reference:**
- `intern/cycles/kernel/light/tree.h::light_tree_importance<false>` (commit e52e5eb0)
- `intern/cycles/kernel/light/tree.h::light_tree_cos_min_incoming_angle`

---

## 3. Mapping to Astroray Implementation

### CPU `LightTree::shouldSplit` → SAOH

**Current (pkg86):** Median split along the axis with largest bounding-box extent. Always splits if `numEmitters > maxLeafSize`.

**New (pkg86-B Phase 1):** Bucket-SAOH cost evaluation.

1. For each axis (x, y, z):
   - Partition emitters into 12 bins along that axis.
   - Compute cumulative `M(left)` and `M(right)` for each bin boundary.
   - Track the split with the lowest `M(left) + M(right)`.

2. If `min_cost >= total_cluster_cost`, return `false` (force leaf).

3. Otherwise, return the axis and bucket index that minimizes cost.

**Implementation note:** Cycles uses `std::partition` to reorder emitters after the split decision. We keep `std::nth_element` for simplicity (equivalent outcome).

### CPU `LightTree::importance` → Full Conty

**Current (pkg86):** 
```cpp
float cos_angle = max(0.0f, normal.dot(node.bcone.axis));
importance = (node.energy / distSq) * cos_angle;
```

**New (pkg86-B Phase 1):**

1. Compute `to_cluster = centroid - point`, `distance = length(to_cluster)`.
2. Compute `theta_i = acos(normalize(to_cluster) · bcone.axis)`.
3. Compute `theta_u = asin(bbox_radius / distance)` where `bbox_radius = 0.5 * length(bbox.max - bbox.min)`.
4. Cone visibility test: if `theta_i - theta_u > theta_o + theta_e + π/2`, return `0.0`.
5. Else, compute `cos_min_outgoing_angle` via the full spherical formula.
6. Return `(energy / distance²) * max(0, cos_min_outgoing_angle)`.

**Cycles function mirrored:**
- `intern/cycles/kernel/light/tree.h::light_tree_importance<false>` (lines ~50-120 in the vendored file).

---

## 4. Patent Re-Check: SAOH

**Search performed:** 2026-05-24, USPTO patent search for "light tree importance sampling", "surface area orientation heuristic", "Conty Kulla", "adaptive tree splitting".

**Findings:**
- No patents found encumbering the SAOH algorithm.
- Conty Estevez & Kulla 2018 was published as an academic paper (Proc. ACM SIGGRAPH Talks, DOI 10.1145/3233305) under Sony Pictures Imageworks, released publicly.
- Blender Foundation incorporated the algorithm into Cycles under Apache-2.0 (2022-2023, commits by Weizhen Huang, Brecht Van Lommel).
- No legal notices or patent disclaimers in the Cycles repository or in the SIGGRAPH proceedings.

**Conclusion:** SAOH is **not patent-encumbered**. Safe to mirror under CLAUDE.md §6 license-compatibility rules (Apache-2.0 → MIT).

**Cross-check:** PBRT-v4 (Apache-2.0, Matt Pharr / Wenzel Jakob) also implements SAOH in `src/pbrt/lightsamplers.cpp::BVHLightSampler` with no patent warnings. Two independent Apache-2.0 implementations confirm open availability.

---

## 5. License Hygiene

**Primary reference implementation:**
- Blender Cycles, commit `e52e5eb06f6b24055f0e7508bc7d7278e139ba0f` (pinned by pkg86, vendored at `external/cycles_light_tree/`).
- License: Apache-2.0, copyright Blender Foundation (2011-2022).
- SPDX: `Apache-2.0`.

**Files mirrored in pkg86-B Phase 1:**
- `intern/cycles/scene/light_tree.cpp` — SAOH split logic (`recursive_build`, `LightTreeMeasure::calculate`, `should_split`).
- `intern/cycles/kernel/light/tree.h` — Importance metric (`light_tree_importance`, `light_tree_cos_min_incoming_angle`).

**Astroray compatibility:**
- Apache-2.0 → MIT is compatible (CLAUDE.md §6).
- Mirrored functions are cited in `src/light_tree.cpp` at each call site: `// Cycles <file>::<function> (Apache-2.0, commit e52e5eb0)`.
- `external/cycles_light_tree/THIRD_PARTY_LICENSES.md` records the additional file (`kernel/light/tree.h`) and SHA confirmation.

---

## 6. Phase 1 Implementation Plan

**Deliverable:** CPU SAOH + full importance, closing the 2× variance xfail gate.

**Files to modify:**

| File | Change |
|---|---|
| `src/light_tree.cpp` (`shouldSplit`) | Replace median split with 12-bucket SAOH cost evaluation. Cite Cycles `recursive_build` at function head. |
| `src/light_tree.cpp` (`importance`) | Replace `cos_angle = max(0, normal·axis)` with full cone-cone visibility test + `cos_min_outgoing_angle` formula. Cite Cycles `light_tree_importance`. |
| `tests/test_pkg86_light_tree.py` | Remove `@pytest.mark.xfail` from `test_variance_reduction_64_lights`. Assert measured reduction ≥ 2.0×. |

**No new files.** Phase 1 is a surgical upgrade to the two functions named in the pkg86-B spec §Phase 1.

**Phase 1 gate:**
- `test_variance_reduction_64_lights` passes **strict** (xfail removed).
- Measured variance reduction ≥ 2.0× on CPU (64 lights, 256 spp).
- All existing pkg86 tests stay green (single-light non-regression, composability, 1000-light build cost).

---

## 7. GPU Port (Phase 2, out of scope for this session)

Phase 2 will port the CPU SAOH tree to GPU:

1. **Upload:** Flatten `nodes[]` / `emitters[]` to `GLightTreeNode[]` / `GLightTreeEmitter[]` in `scene_upload.cu`.
2. **Traversal:** Device-callable `gpu_light_tree_sample(...)` mirroring Cycles `kernel/light/tree.h::light_tree_sample` (iterative, no recursion).
3. **Parity gate:** CPU/GPU same `(point, normal, u)` → same `(light_idx, pdf)` within FP tolerance.

See pkg86-B spec §Phase 2 for full details. Phase 1 (this session) closes the CPU variance gate first so the GPU port inherits a tree that already clears 2×.

---

## Sources

**Primary algorithm:**
- Alejandro Conty Estevez & Christopher Kulla, "Importance Sampling of Many Lights with Adaptive Tree Splitting", Proc. ACM Comput. Graph. Interact. Tech. 1(2): 25:1-25:17 (2018). DOI [10.1145/3233305](https://dl.acm.org/doi/10.1145/3233305).

**Primary reference implementation (Apache-2.0):**
- Blender Cycles, commit `e52e5eb06f6b24055f0e7508bc7d7278e139ba0f`:
  - `intern/cycles/scene/light_tree.cpp` — SAOH split (`recursive_build`, `LightTreeMeasure::calculate`).
  - `intern/cycles/kernel/light/tree.h` — Importance (`light_tree_importance`, `light_tree_cos_min_incoming_angle`).

**Backup / cross-check reference (Apache-2.0):**
- PBRT-v4, `src/pbrt/lightsamplers.cpp::BVHLightSampler` (Matt Pharr / Wenzel Jakob / Greg Humphreys). https://github.com/mmp/pbrt-v4 (Apache-2.0). Confirms SAOH cost formula; not mirrored byte-for-byte.

**Astroray internal:**
- `.astroray_plan/packages/pkg86-B-light-tree-gpu.md` — this package's spec.
- `.astroray_plan/docs/light-tree-research.md` — pkg86 Phase 1 research note (signed off 2026-05-22).
- `src/light_tree.cpp`, `include/astroray/light_tree.h` — CPU tree being refined.
- `tests/test_pkg86_light_tree.py:169-176` — the xfail this phase closes.
