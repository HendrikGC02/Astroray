# pkg174 — shade-kernel register-pressure: measured split design + handoff

**Status:** measured design (2026-08-08). The micro-lever avenue is closed
(#548, merged — `pkg174-register-pressure-ledger.md`). This doc redirects the
structural work with **measured** evidence and hands it to a dedicated session.

**Machine/toolchain:** RTX 5070 Ti, Ninja + CUDA 12.8 + native sm_120.
Measurement method: edit `gpu_materials.h` / `stage_advance.cu`, rebuild the
`pkg174` worktree, `cuobjdump --dump-resource-usage` on the linked `.pyd`,
read `stageShadeBucketedKernel` REG/STACK. (Perf A/B protocol: burn-in to
2887 MHz P0 + min-of-N — see `gpu-perf-ab-clock-drift` memory; clock-lock needs
admin, unavailable.)

## The headline finding (measured — do not re-derive)

**The shade kernel's REG:254 / STACK:2576 ceiling is NOT driven by the
per-material BSDF code. It is the shared shading infrastructure.**

| Experiment | `stageShadeBucketedKernel` | Δ vs baseline |
| --- | --- | --- |
| Baseline (production) | REG:254  STACK:2576 | — |
| Stub `GMAT_DISNEY`+`GMAT_CLOSURE_GRAPH` sample cases | REG:255  STACK:2576 | none |
| **Stub ALL of `gpu_material_sample` / `_eval` / `_pdf` to trivial** | **REG:254  STACK:2576** | **none** |

Removing essentially all per-material sampling/eval/pdf code left the register
and spill footprint **byte-identical**. (Builds verified fresh by `.pyd` mtime,
not stale.)

### Consequence — the naive per-material stage-split will NOT recover ≤1.0s

Laine/Karras/Aila 2013 "Megakernels Considered Harmful" is usually applied by
splitting the shade megakernel into **per-material** kernels. Here that would
give every split kernel the **same** REG:254 floor, because the floor is the
NEE/MIS/traversal/light-sampling/spectral infrastructure they all share — not
the material union. **A per-material split is the wrong lever for the ≤1.0s
perf goal.** This confirms the spec addendum's "occupancy-cliff-bounded"
warning with a concrete mechanism.

## Where the register pressure actually lives (prioritized suspects)

`shadePathSlot` (`src/gpu/wavefront/stage_advance.cu:316`) carries, all live
across the NEE section, the real consumers to attribute and attack:

1. **`gpu_nee_sample`** (`:435`, executed in production) — light-tree +
   light-list sampling. Light-tree traversal keeps a stack + node state live.
2. **The dead immediate-NEE `else` branch** (`:507-518+`, `gpu_nee_occlude` —
   inline shadow-ray BVH/TLAS traversal). In the production bucketed path
   `nee_f != nullptr` is ALWAYS true, so this branch is **dead at runtime but
   still compiled in**, so ptxas allocates for its BVH-traversal live set.
   *Candidate cheap win: compile it out of the production kernel via a
   `template<bool Deferred>` on `shadePathSlot` / `stageShadeBucketedKernel`.*
3. **`gpu_material_eval_spectral`** (`:448`, the deferred-NEE BSDF eval) — a
   SEPARATE function from the `gpu_material_eval` stubbed above; not isolated
   by the experiments here. Attribute it.
4. **Spectral state + the enormous parameter list** — `GSampledSpectrum`
   throughput/color (4 floats each), `GSampledWavelengths` (8 floats),
   `GHitRecord`, live `WavefrontRNG` with dimension counter, plus ~30 kernel
   params (tlas/instances/blas/bvh/prims/tris/spheres/materials/lights/
   dedLights/lightTree/photonGrid/crypto…). Much of this is unavoidably live.
5. **Photon grid + cryptomatte** paths (`hasPhotonGrid`, `cryptoDepth`) — gated
   at runtime but compiled in; attribute and consider compiling out when off.

## The real split axis: by STAGE, not by material

The effective structural lever is to move register-heavy WORK out of the shade
kernel into its own wavefront stage (the actual Laine 2013 principle —
separate traversal/sampling from shading):

- **(a) Compile out the dead immediate-NEE branch** (suspect #2) — smallest,
  safest first step; measure the REG drop. Pure specialization, output
  unchanged (the branch is already dead in production).
- **(b) Move NEE light-sampling to its own stage** — a `stageNeeSample` kernel
  produces the shadow-ray work items (already a queue: `shadow_queue`/`nee_f`),
  so `gpu_nee_sample`'s light-tree state leaves the shade kernel entirely.
  Shade then only does BSDF sample + continuation-ray enqueue.
- **(c) Attribute spectral/param pressure** (#3–#5) with Nsight Compute
  (source-level register/occupancy view) rather than stub-and-rebuild — the
  right tool for this; stub-and-rebuild is coarse and missed #3 here.

Each step is **bit-identity gated** (`tests/wavefront_diff/`, 1e-5 MC
convention; wavefront is not run-to-run bit-exact) and measured by the
Contract's isolated wall-time A/B, never cuobjdump alone (per-kernel deltas do
not sum to runtime — addendum trap).

## Extensibility framing (owner directive 2026-08-08)

The owner will add many material types via the plugin architecture —
diffraction gratings, thin films, thin translucents (Blender 5.x), astro
materials, more — and wants the foundation right first. This changes the
calculus:

- **Good news from the finding:** since material code is NOT the shade kernel's
  register bottleneck today, adding materials does not immediately worsen the
  REG:254 ceiling. There is headroom before the material union itself becomes
  the constraint.
- **But** every new material still inlines into the `gpu_material_sample/eval/
  pdf` switches → growing megakernel, compile time, and eventually the material
  union WILL matter (multilayer thin-film interference, dispersive gratings are
  heavy). And a monolithic switch is at odds with the plugin design.
- **Therefore the design has TWO separable goals; do not conflate them:**
  1. **Perf (≤1.0s):** attack the shared infrastructure (steps a–c). Per-
     material splitting does nothing for this.
  2. **Extensibility:** a per-material **kernel-dispatch** foundation (each
     material family compiled into its own shade kernel, selected off the
     already-existing per-type shade buckets) so a new plugin material adds a
     kernel instead of inflating a shared switch. Valuable for the plugin
     roadmap **even though it won't move the ≤1.0s number** — size it as
     architecture, not perf.

  The already-sorted per-type shade queues (`G_WF_NUM_MAT_TYPES` buckets,
  `stage_advance.cu:1058`) are the dispatch substrate for goal 2. The leftover
  `stageShadeLambertianKernel`/`stageShadeMetalKernel` are **feature-incomplete
  N+3-era relics** (no NEE/MIS/photon/crypto) — a template/pattern to grow, not
  code to route into.

## Concrete next experiments (ordered, for the dedicated session)

1. `template<bool Deferred>` on the shade path; compile out the immediate-NEE
   branch for the production (Deferred=true) instantiation. Rebuild → REG. If
   it drops materially, wall-time A/B on the perf-gate scene (burn-in P0,
   min-of-N). **Cheapest potential win; do first.**
2. Nsight Compute on `stageShadeBucketedKernel` for the perf-gate scene: get
   the source-level register/live-range attribution (which lines pin 254).
   This replaces the coarse stub-and-rebuild used here.
3. Based on #2, extract the top consumer (likely `gpu_nee_sample` light-tree)
   into its own stage; bit-identity gate; wall-time A/B.
4. Only if ≤1.0s proves unreachable after #1–#3: report the occupancy-cliff
   floor with numbers and leave the ceiling raise in place (do NOT re-pin the
   perf gate below its 1.0s intent without an owner — that revert is pkg174's
   definition of done and is only valid at a real ≤1.0s).

## Hard constraints (unchanged)

- Correctness frozen: wavefront output bit-identical on the standard gates.
  PERF ONLY. No material-eval math moves.
- Do NOT revert the temporary 1.5s ceiling raise in
  `tests/wavefront_diff/test_pkg55_perf_gate.py` until the scene actually
  measures ≤1.0s. Leaving it in place is correct; reverting early is a FAIL.
- Cite Laine/Karras/Aila 2013 for any stage-split (pkg55 docs already carry it).
