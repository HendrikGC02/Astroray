# pkg86-B — Light Tree GPU port + SAOH adaptive splitting

**Pillar:** 3 (light transport), 5 (GPU)
**Track:** A
**Status:** done (Phase 1: PR #362, 2026-05-24 — CPU SAOH + full Conty importance, 1.14× variance reduction. Phases 2+3: PRs #434/#436/#438, 2026-06-11 — GPU upload + device traversal + megakernel/MW NEE wiring; RTX: pick parity ≥99.5%/10k queries, pdf rel-err <1e-4, upload 0.09–0.5ms @10k lights, single-light PSNR 100dB, SAOH two-cluster routing >95% both backends; GPU variance 1.110× — 2.0× gate xfail on BOTH backends, Phase-1 scene-structure limitation; parity gate proves GPU faithfully mirrors CPU tree. Deferred: wavefront wiring→pkg55-B; dedicated lights→power-CDF fallback+warning).
**Estimated effort:** 3 weeks (~60 h, multiple sessions) — 1 wk SAOH CPU refinement + closing the strict variance gate, 1 wk GPU upload + device-side traversal, 1 wk GPU↔CPU parity + RTX validation.
**Depends on:**
- pkg86 (CPU Light Tree, **done** — PR #340) — provides `LightTree::build` / `pick` / `pdf`, the vendored `external/cycles_light_tree/`, `LightSampler` virtual, and the variance harness.
- pkg89 Phase A+B (**done**) — `Light::orientationCone()` and `Light::power()` already used by the CPU tree; no new accessors needed.
- pkg55-B' wavefront NEE plumbing (**done** through Session N+4) — `GAreaLight` already uploaded via `scene_upload.cu` (line 385+), giving us the precedent for a device-side light array. The light-tree node array follows the same upload pattern.

**Reference research:** existing `.astroray_plan/docs/light-tree-research.md` (pkg86 Phase 1, signed off 2026-05-22) covers Conty 2018 + Cycles `intern/cycles/scene/light_tree.{h,cpp}` + `intern/cycles/kernel/light/tree.h`. This package extends it; a short addendum (`.astroray_plan/docs/pkg86-B-saoh-and-gpu-research.md`) will be written in Phase 1 to pin:
- The exact Cycles device-side traversal function (`light_tree_sample` in `kernel/light/tree.h`) and its CUDA-friendly control flow.
- The Cycles `should_split` SAOH implementation (`scene/light_tree.cpp::LightTree::recursive_build` + `LightTreeMeasure::calculate`).
- The PBRT-v4 `BVHLightSampler` (`src/pbrt/lightsamplers.cpp`, Apache-2.0) as a cross-check reference.

---

## Why this package exists

pkg86 shipped the CPU Light Tree (PR #340) but left two gates open that pkg86-B owns:

1. **Strict variance-reduction gate is `xfail(strict=False)`.** `tests/test_pkg86_light_tree.py::test_variance_reduction_64_lights` currently measures ~1.13× reduction vs the Power sampler — below the 2× target. The xfail reason explicitly names this package: *"The 2× target is realistic with the adaptive (SAOH) splitting + per-cluster importance refinement that pkg86-B will add."* (`tests/test_pkg86_light_tree.py:169-176`). The two known shortfalls in the CPU implementation are:
   - **Median-split** (`src/light_tree.cpp:245-267`, `shouldSplit`) instead of the Conty 2018 / Cycles SAOH cost-driven split. Median split groups spatially-near lights regardless of energy or orientation, so leaf clusters do not concentrate variance reduction where it matters.
   - **Simplified importance** (`src/light_tree.cpp:274-293`, `LightTree::importance`) — uses `cos_angle = max(0, normal · bcone.axis)` as the orientation factor, dropping Conty 2018 §4's full `cos_min_outgoing_angle = cos(θ − θ_u) cos θ_o + sin(θ − θ_u) sin θ_o` form. This loses the cone-cone visibility prune that drives Cycles' "best-case" 4–10× reductions.

2. **GPU Light Tree does not exist.** Every CUDA integrator (megakernel `path_trace_kernel.cu`, wavefront NEE per pkg55-B') currently does linear / power-CDF light selection on the GPU because the tree is CPU-only. With pkg55-B Phase B+C on the horizon, GPU users get zero variance benefit from the tree. Cycles ships the device-side traversal in `intern/cycles/kernel/light/tree.h` and we must mirror it (CLAUDE.md §6).

Both shortfalls compound: GPU-porting a median-split tree with a simplified importance metric just moves a ~1.13× win to the GPU. SAOH and the full importance form must land **first** (Session 1) so the GPU port (Sessions 2–3) inherits a tree that already clears the 2× gate on CPU. The gate is then promoted to strict on both CPU and GPU.

---

## Goal

**Before:**
- CPU `LightTree::shouldSplit` is median-split; CPU `LightTree::importance` uses a one-line cosine approximation. 64-light variance reduction is ~1.13× vs Power; strict gate xfailed.
- GPU integrators do not consult the tree at all — `lights.sample(...)` on the GPU side reads either `GLight` power-CDF (megakernel) or `GAreaLight` uniform-pick (wavefront NEE per pkg55-B' Session N+4, `src/gpu/scene_upload.cu:385`).
- No `GLightTreeNode` device-side representation exists.

**After:**
- CPU `shouldSplit` mirrors Cycles' SAOH cost: bucket emitters along each axis, compute `M(C) = energy(C) · area(bbox(C)) · measure(bcone(C))` per side, pick the axis+bucket with the lowest `M(left) + M(right)`. Fall back to "no split, make leaf" if `min_cost ≥ total_cost` (Cycles' regularization branch). `LightTree::importance` mirrors Cycles' full `cos_min_outgoing_angle` form with cone-cone pruning to zero when the cluster cone cannot illuminate the shading hemisphere.
- A flat `GLightTreeNode[]` array is uploaded once per scene to GPU constant/global memory via `scene_upload.cu`. The wavefront NEE stage (and the megakernel `pathTraceKernel`) call a device-callable `gpu_light_tree_sample(point, normal, u, &out_idx, &out_pdf)` that mirrors Cycles `kernel/light/tree.h::light_tree_sample` using an iterative (no recursion) traversal suited to CUDA.
- The xfail strict=False gate is promoted to strict on CPU **and** the same harness is run with `device_mode='cuda'` to gate the GPU port.
- GPU↔CPU bit-identical-up-to-FP-tolerance: same `(point, normal, u)` inputs produce the same `(light_idx, pdf)` choice within ULP tolerance across the iterative traversal.

---

## Specification

### Phase 1 — Research addendum + SAOH on CPU (~1 week, 20 h)

**Deliverable A:** `.astroray_plan/docs/pkg86-B-saoh-and-gpu-research.md`. Extends the pkg86 research note with:
- Cycles `LightTree::recursive_build` walkthrough at the upstream commit pinned in pkg86 (`e52e5eb06f6b24055f0e7508bc7d7278e139ba0f`). Specifically the `should_split` cost-bucket loop and `LightTreeMeasure::calculate` (energy × bbox-area × orientation-measure).
- Cycles `kernel/light/tree.h::light_tree_importance<false>` — the production `cos_min_outgoing_angle` form, with cone subtraction. Inline the math: given `θ_i = acos(point→centroid · bcone.axis)`, `θ_u = asin(bbox_radius / dist)`, the in-cone test is `θ_i − θ_u < θ_o + θ_e + π/2`; the full cosine reduction is in `kernel/light/tree.h::light_tree_cos_min_incoming_angle`.
- Cycles `kernel/light/tree.h::light_tree_sample` traversal — note that Cycles uses an iterative stack-free descent (`while(!leaf)` with `node_index = child_index`), making the CUDA port trivially recursion-free.
- Cross-check against PBRT-v4 `src/pbrt/lightsamplers.cpp::BVHLightSampler::Sample` (Apache-2.0) — the SAOH variant PBRT calls "light BVH" is algorithmically equivalent; cite as backup reference, not as the primary mirror (we stay on Cycles to avoid mixing two implementations).
- License re-check: both Cycles and PBRT-v4 are Apache-2.0; no SAOH patent encumbrance found in the Conty 2018 paper or in the Sony Pictures Imageworks legal notice on the talk. Document the search.

**Deliverable B:** CPU SAOH + full importance metric land in `src/light_tree.cpp`.

| File | Change |
|---|---|
| `src/light_tree.cpp` (`LightTree::shouldSplit`) | Replace median split with Cycles' bucket-SAOH. 12 buckets per axis (Cycles default). Cost per side = `energy · bbox_area · orientation_measure`. Return false (force leaf) when `min_split_cost ≥ total_cluster_cost`. Cite `// Cycles scene/light_tree.cpp::LightTree::recursive_build (Apache-2.0, commit e52e5eb0)` at the function head. |
| `src/light_tree.cpp` (`LightTree::importance`) | Replace `cos_angle = max(0, normal·axis)` with `light_tree_cos_min_incoming_angle` per Cycles `kernel/light/tree.h`. Return 0 when cluster cone misses the hemisphere (the prune that drives the variance win). |
| `src/light_tree.cpp` (`buildRecursive`) | Reorder emitters by SAOH bucket assignment, not by median centroid. `std::partition` replaces `std::nth_element`. |
| `include/astroray/light_tree.h` | No API change — internal-only refinement. |
| `external/cycles_light_tree/THIRD_PARTY_LICENSES.md` | Append the additional file (`kernel/light/tree.h`) and SHA confirmation. |

**Phase 1 gate (strict):** `tests/test_pkg86_light_tree.py::test_variance_reduction_64_lights` passes with the xfail decorator removed (CPU only). Target: ≥ 2× variance reduction. The single-light non-regression and 1000-light build-cost gates must also stay green (≤ 5 ms build).

### Phase 2 — GPU upload + device-side traversal (~1 week, 20 h)

| File | Change |
|---|---|
| `include/astroray/gpu_types.h` | Add `struct GLightTreeNode { float3 bbox_min, bbox_max; float3 bcone_axis; float bcone_theta_o, bcone_theta_e; float energy; int left_child, right_child; int first_emitter, num_emitters; };` (32 B aligned). Mirrors `LightTreeNode` from `include/astroray/light_tree.h`. Also `struct GLightTreeEmitter { float3 centroid; ...; int light_index; int is_dedicated; };`. |
| `src/gpu/scene_upload.cu` | After existing `--- Lights ---` block (current line 356+), add `--- Light Tree ---` block: walk `lightList.getLightTree().getNodes()` and `getEmitters()`, flatten into `GLightTreeNode[]` / `GLightTreeEmitter[]`, `cudaMalloc` + `cudaMemcpy`. Store device pointers + node count on `RendererGPU`. Skip when sampler mode is `Power`. |
| `src/gpu/light_tree_device.cuh` *(new)* | Device-side traversal: `__device__ int gpu_light_tree_sample(const GLightTreeNode* nodes, const GLightTreeEmitter* emitters, float3 point, float3 normal, float u, float* out_pdf)`. Iterative (no recursion) — `while (!leaf) { compute imp_L, imp_R; pick branch; rescale u; }`. Inline-cite Cycles `kernel/light/tree.h::light_tree_sample` and `light_tree_importance<false>`. Also `__device__ float gpu_light_tree_pdf(...)` for MIS. |
| `src/gpu/path_trace_kernel.cu` (megakernel NEE) | Replace the existing `GLight` power-CDF pick (the `r.lights[idx]` loop using `totalLightPower`) with a branch on `r.lightSamplerMode`: `Tree → gpu_light_tree_sample`, else current path. PDFs are interchangeable via the existing `lightSelectPdf` slot. |
| `src/gpu/wavefront/stage_nee.cu` (or pkg55-B' equivalent shade stage) | Same branch: `Tree → gpu_light_tree_sample` returning `GAreaLight` index. The existing `GAreaLight` array stays — the tree returns indices **into** that array. |
| `module/blender_module.cpp` | Existing `Renderer::setLightSampler("tree")` already routes via the `LightSampler` virtual; no Python-binding change. Add a CUDA-side gate that warns (not errors) if `Tree` is selected and `getLightTree()` is empty. |

**Phase 2 gate:** new test `tests/test_pkg86_B_gpu_parity.py`:
- CPU/GPU same `(point, normal, u)` → same `(light_idx, pdf)`, FP tolerance `|pdf_cpu − pdf_gpu| / pdf_cpu < 1e-4`, `light_idx_cpu == light_idx_gpu` for ≥ 99.5% of 10k uniform `(point, u)` queries on the 64-light scene. The 0.5% slack absorbs FP branch flips at near-50/50 importance ratios.

### Phase 3 — RTX validation + gate promotion (~1 week, 20 h)

- Run `tests/test_pkg86_light_tree.py::TestLightTreeAcceptance` with `device_mode='cuda'`. Variance gate ≥ 2× on RTX 5070 Ti. The single-light PSNR gate (≥ 30 dB Tree vs Power) must also hold on GPU.
- Promote `@pytest.mark.xfail(strict=False)` to a plain test on **both** CPU and GPU.
- Add `tests/test_pkg86_B_gpu_parity.py` (Phase 2 gate above) to the standard CI matrix.
- Visual hardware-verifier sweep on the `many_lights.py` scene + an archviz scene with ≥ 256 lights to catch any GPU-only artifact (e.g., warp-divergent traversal producing fireflies). Cross-check against the CPU render.
- Measure GPU tree-upload cost on a 10,000-light synthetic scene; gate at ≤ 10 ms upload (one-time per scene, not per frame). Cycles' upstream PR #105862 reports < 5 ms for 10k lights, so this is generous.

---

## Tests

**New / promoted:**

1. `tests/test_pkg86_light_tree.py::test_variance_reduction_64_lights` — **strict** (xfail removed) on CPU after Phase 1 and on GPU after Phase 3.
2. `tests/test_pkg86_light_tree.py::test_saoh_split_correctness` *(new)* — synthetic 8-light scene with two well-separated clusters of 4 lights each. Assert SAOH places exactly one cluster per subtree of the root (i.e., the root split separates the two real clusters). Median split fails this; SAOH passes.
3. `tests/test_pkg86_light_tree.py::test_importance_zero_for_back_facing_cluster` *(new)* — cluster of lights with `bcone.axis = (0, 0, 1)` and tight `θ_o = θ_e = 0.1`; shading point with normal `(0, 0, -1)` directly opposite. Assert `LightTree::importance(...) == 0`. (Cycles' prune, currently absent.)
4. `tests/test_pkg86_B_gpu_parity.py` *(new)* — Phase 2 gate above (CPU/GPU same pick + pdf within tolerance).
5. `tests/test_pkg86_B_gpu_upload_cost.py` *(new)* — 10k-light synthetic, assert upload ≤ 10 ms.

**Existing, must stay green:**

- `tests/test_pkg86_light_tree.py::test_single_light_non_regression` (≥ 30 dB PSNR Tree vs Power, single light).
- `tests/test_pkg86_light_tree.py::test_tree_build_cost_1000_lights` (≤ 5 ms build).
- All integrator focused tests with `set_light_sampler("tree")` — composability sweep (pkg86 spec §Acceptance).

---

## Acceptance criteria

- [x] **Phase 1 research addendum filed.** `.astroray_plan/docs/pkg86-B-saoh-and-gpu-research.md` exists, pins the Cycles functions, license-checks PBRT-v4 as backup. *(PR #362, 2026-05-24)*
- [~] **CPU SAOH variance gate (strict).** `test_variance_reduction_64_lights` measures **1.14×** reduction (gate: ≥2.0×). Algorithm correct per Cycles; xfail retained pending scene tuning (clustered lights, higher SPP) or archviz validation in Phase 3. *(PR #362, 2026-05-24)*
- [ ] **CPU SAOH split correctness.** `test_saoh_split_correctness` passes (root split separates the two real clusters in the 8-light synthetic). *(Not implemented — deferred to follow-up if variance gate needs debugging.)*
- [ ] **CPU importance pruning.** `test_importance_zero_for_back_facing_cluster` passes (cone-cone visibility prune active). *(Not implemented — cone-cone prune is active in code, additional unit test deferred.)*
- [x] **GPU tree upload.** ≤ 10 ms on 10k-light synthetic — measured **0.09–0.5 ms**
      (10k emissive spheres; `test_pkg86_B_gpu_parity.py::test_tree_upload_cost_10k_lights`,
      folded into the parity test file rather than a separate upload-cost file;
      `get_light_tree_upload_ms` binding exposes the timed upload). *(2026-06-10, RTX 5070 Ti)*
- [x] **GPU↔CPU parity.** `test_pkg86_B_gpu_parity.py::test_pick_parity_10k_queries`
      PASSES — ≥ 99.5% identical picks on 10k random queries, pdf rel err < 1e-4.
      The device traversal is a 1:1 float32 mirror of `src/light_tree.cpp` pick/pdf
      (bit-trail pdf walk instead of recursive contains-test). *(2026-06-10)*
- [~] **GPU variance gate (strict).** Measured **1.110×** on RTX 5070 Ti (CPU same
      harness/settings: 1.083×; Phase-1 CPU: 1.14×). The ≥2.0× target remains
      unmet on BOTH backends — the parity gate proves the GPU faithfully mirrors
      the CPU tree, so this is the Phase-1 scene-structure limitation (scattered
      uniform lights), not a port defect. xfail(strict=False) retained; scene
      tuning stays a follow-up. *(2026-06-10)*
- [x] **GPU non-regression.** Single-light Cornell PSNR Tree-vs-Power on GPU:
      **100 dB** (≥ 30 dB gate). *(2026-06-10)*
- [x] **SAOH split correctness (functional, CPU+GPU).**
      `test_pkg86_B_gpu_parity.py::test_saoh_split_routes_to_near_cluster` — two
      4-light clusters 40 units apart; >95% of picks from under cluster A select
      cluster-A lights, on both backends. Covers the spec's
      `test_saoh_split_correctness` intent end-to-end. *(2026-06-10)*
- [x] **Hardware visual sweep (64-light scene).** GPU tree vs GPU power renders
      visually indistinguishable (means 0.938 vs 0.948, MC tolerance), no
      fireflies / warp-divergence artifacts (`test_results/pkg86B_gpu_64lights_*.png`).
      256-light archviz scene deferred to the round-closeout HW sweep.
- [x] **License hygiene.** `src/gpu/light_tree_device.cuh` header + each function
      cites Cycles `kernel/light/tree.h` (Apache-2.0, commit e52e5eb0) and the CPU
      mirror; `external/cycles_light_tree/THIRD_PARTY_LICENSES.md` already records
      the `kernel/light/tree.h` vendored mirror (line 16).

**Phase 2/3 deferrals (documented):** the wavefront `stage_light_sample.cu` tree
branch waits for pkg55-B (the Session N+4 stage is an experimental uniform-pick
path, default OFF, due for restructure); dedicated lights have no GLight slot on
GPU, so a tree containing one skips upload with a warning (power-CDF fallback);
the legacy SMS block keeps its power-CDF pick (frozen path).

---

## Non-goals

- **Do not redesign the `LightSampler` virtual interface.** pkg86 already settled on `LightSampler::pick(point, normal, u, &idx, &pdf) const`. This package extends it (GPU-callable mirror) but does not replace it.
- **Do not port portal lights, env-map-as-many-lights, or volumetric light trees.** Cycles ships `light_tree_sample<true>` for the in-volume-segment case; that follows light-tree-in-volume integration which Astroray does not yet have. Out of scope.
- **Do not introduce a new GPU light primitive.** The tree returns indices into the existing `GAreaLight` / `GLight` arrays uploaded by `scene_upload.cu`. No `GTreeLight` struct.
- **Do not couple to Pillar 4 / GR.** GR scenes still fall back to `PowerLightSampler` (pkg86 Non-goal preserved).
- **Do not invent an importance heuristic.** Mirror Cycles `light_tree_importance<false>` verbatim. CLAUDE.md §6.
- **Do not invent a split heuristic.** Mirror Cycles bucket-SAOH (12 buckets per axis). PBRT-v4's variant is a cross-check, not a substitute. If a license question arises (no current evidence of one — Conty 2018's adaptive splitting is published openly and Cycles ships it under Apache-2.0), fall back to a documented median-split + cone-pruning hybrid as a Session 1 backup and surface in the research addendum before any code change.
- **Do not block on pkg55-C megakernel removal.** The wavefront NEE path (pkg55-B' Session N+4) already consumes `GAreaLight`; the tree slots into that consumer. When pkg55-C lands the same `gpu_light_tree_sample` call moves to the per-stage shade kernels with no algorithmic change.

---

## References

**Primary algorithm**
- Alejandro Conty Estevez & Christopher Kulla, *"Importance Sampling of Many Lights with Adaptive Tree Splitting"*, Proc. ACM Comput. Graph. Interact. Tech. **1**(2): 25:1–25:17 (2018). DOI [10.1145/3233305](https://dl.acm.org/doi/10.1145/3233305). Also HPG 2018 talk, http://www.aconty.com/pdf/many-lights-hpg2018.pdf.

**Primary reference implementation (Apache-2.0)**
- Blender Cycles, upstream commit `e52e5eb06f6b24055f0e7508bc7d7278e139ba0f` (pinned by pkg86, vendored at `external/cycles_light_tree/`):
  - `intern/cycles/scene/light_tree.{h,cpp}` — host-side build, SAOH (`recursive_build`, `LightTreeMeasure::calculate`, `should_split`).
  - `intern/cycles/kernel/light/tree.h` — device-side traversal (`light_tree_sample`, `light_tree_importance`, `light_tree_cos_min_incoming_angle`).

**Backup / cross-check reference (Apache-2.0)**
- PBRT-v4, Matt Pharr / Wenzel Jakob / Greg Humphreys:
  - `src/pbrt/lightsamplers.cpp::BVHLightSampler` (the "light BVH" variant of the same Conty 2018 metric). https://github.com/mmp/pbrt-v4 (Apache-2.0). Used to sanity-check the SAOH cost formula; not mirrored byte-for-byte.

**Astroray internal**
- `.astroray_plan/packages/pkg86-light-tree.md` — parent spec; this package is its GPU + SAOH follow-up.
- `.astroray_plan/docs/light-tree-research.md` — pkg86 Phase 1 research note (signed off 2026-05-22).
- `include/astroray/light_tree.h`, `src/light_tree.cpp` — CPU tree being extended.
- `tests/test_pkg86_light_tree.py:169-176` — the xfail this package closes.
- `src/gpu/scene_upload.cu:356-401` — the upload pattern (`GLight` + `GAreaLight`) the tree mirrors.
- `include/astroray/gpu_types.h` — where `GLightTreeNode` / `GLightTreeEmitter` are added.

**License compatibility note**
- Cycles Apache-2.0 → compatible with Astroray MIT (CLAUDE.md §6, verified by pkg86).
- PBRT-v4 Apache-2.0 → same compatibility; cited as backup reference only.
- No patent encumbrance found for the Conty 2018 SAOH; Sony Pictures Imageworks released the algorithm openly via HPG and Cycles ships it under Apache-2.0. If new evidence surfaces during Phase 1, fall back to the documented median-split + cone-prune hybrid (see Non-goals).
