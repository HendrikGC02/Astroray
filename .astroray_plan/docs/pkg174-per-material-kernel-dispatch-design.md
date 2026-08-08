# pkg174 — per-material shade-kernel dispatch: extensibility foundation

**Status:** design (2026-08-08). Companion to
`pkg174-stage-split-design.md` (perf) and `pkg174-register-pressure-ledger.md`
(levers). **This document is scoped to EXTENSIBILITY, not perf.** The measured
finding below is that per-material kernel dispatch does **not** move the ≤1.0s
number — it is proposed for the plugin-material roadmap, and sized as
architecture.

**Machine/toolchain:** RTX 5070 Ti, Ninja + CUDA 12.8 + native sm_120. Every
REG/STACK below is `cuobjdump --dump-resource-usage` on the linked `.pyd`.

## Measured attribution that frames this design (2026-08-08 session)

Nsight Compute source attribution was unavailable (`ncu` → `ERR_NVGPUCTRPERM`,
no perf-counter permission, same missing elevation as clock-lock). Targeted
stub-and-rebuild on `stageShadeBucketedKernel` gave:

| Config | REG | STACK |
| --- | --- | --- |
| baseline (NEE on, BSDF on) | 254 | 2576 |
| NEE section OFF, BSDF on | 254 | 2064 |
| NEE on, BSDF sampler bypassed | 255 | 2320 |
| NEE OFF **and** BSDF bypassed | **95** | 584 |

**Interpretation (this corrects `pkg174-stage-split-design.md`'s headline).**
The REG:254 ceiling is held by **two independent ~160-register consumers** on a
**~95-register irreducible state-marshalling base**:

- the NEE light-sampling section (`gpu_nee_sample` light-tree descent +
  `gpu_material_eval_spectral`/`_pdf` + shadow-ray park), and
- the BSDF material union (`gpu_material_sample_spectral` → the 7-way
  `gpu_material_sample` switch + spectral upsampling).

**Either one alone saturates the 254 cap**; only removing *both* drops to 95.
ptxas caps at 254 and spills the combined ~415-register want to local memory
(STACK 2576 B). This is why every single removal moves only STACK (spill), never
REG.

The earlier design doc concluded "material code is NOT the register bottleneck"
after stubbing the **non-spectral** `gpu_material_sample/_eval/_pdf` (thin
wrappers). Its own note #3 flagged that the `_spectral` variants — the ones
actually on the wavefront hot path — were never isolated. They are, in fact, a
~160-register consumer.

### Consequence for perf (measured, not hypothesized)

Per-material kernel dispatch **cannot raise the shade kernel's occupancy**:

- Every bucket's shade kernel still runs the **NEE** section (all non-delta
  hits do NEE), and NEE alone pins REG at 254 (measured: "NEE on, BSDF
  bypassed" = 255). Slicing only the BSDF union per material leaves NEE holding
  the ceiling.
- Even slicing *both* (per-material BSDF **and** NEE moved to its own stage),
  the perf-gate scene (`disney_contact_sheet`) is dominated by heavy buckets —
  `GMAT_DISNEY`, `GMAT_THIN_GLASS`, `GMAT_CLOSURE_GRAPH` — whose individual
  samplers, on the ~95 base, stay above the 128-register threshold needed for
  2 blocks/SM. The light buckets (`GMAT_LAMBERTIAN`, `GMAT_DIFFUSE_LIGHT`)
  would gain occupancy, but they are not the bottleneck.

So this design is justified by the **plugin roadmap**, not the ≤1.0s ceiling.
Do not re-pin the perf gate on the strength of it.

## Why it is still worth building (extensibility)

The owner will add many material families through the plugin architecture —
diffraction gratings, thin films, thin translucents (Blender 5.x), astro
materials. Each new family today must be added **into the shared switch** in
`gpu_material_sample` / `gpu_material_eval_spectral` / `gpu_material_pdf`
(`include/astroray/gpu_materials.h`). That has three costs that compound with
material count:

1. **Megakernel growth.** Every family's sampler inlines into the one union that
   `stageShadeBucketedKernel` compiles. Heavy future families (multilayer
   thin-film interference, dispersive gratings) are large; the union's
   ~160-register contribution and the kernel's compile time both grow with the
   roster, even though a given *path* only ever needs one arm.
2. **Compile time & code size** scale with the roster, not with what any launch
   uses.
3. **It is at odds with the plugin design** — a plugin should add a
   self-contained unit, not edit a shared switch in a core header.

The already-sorted per-type shade queues are the dispatch substrate:
`stageQueueScatterKernel` buckets each surviving path by `matType` (0..6) into
`shade_queues[matType * capacity + slot]` (`stage_advance.cu:~1027`), and
`stageShadeBucketedKernel` launches `G_WF_NUM_MAT_TYPES * capacity` threads with
`bucket = i / capacity` (`stage_advance.cu:1058`). **Bucket m already contains
only material type m** — the launch just doesn't exploit it: it runs the same
megakernel body for every bucket.

## The design: `template<int MatType>` per-bucket shade kernels

Specialize the shade kernel on the compile-time material type, dispatched off the
existing buckets. Concretely:

1. **Add a `template<int MatType>` overload of `gpu_material_sample_spectral`
   (and `_eval_spectral` / `_pdf`)** whose body is the current one with the
   runtime `switch (mat.type)` replaced by `if constexpr (MatType == GMAT_X)`.
   For a concrete `MatType`, the compiler keeps exactly one arm; the other six
   samplers are never instantiated into that kernel. The `GMAT_CLOSURE_GRAPH`
   arm stays general (it is itself an interpreter), so it specializes least —
   which is fine; the concrete families (0..5) are where slicing pays.

2. **`template<int MatType> __global__ void stageShadeBucketedKernelT(...)`** —
   the body of today's `stageShadeBucketedKernel` (still `shadePathSlot<true>`,
   i.e. keeping ALL shared features: NEE/MIS/photon/crypto — this is the point of
   difference from the feature-incomplete relic kernels), calling the
   `template<MatType>` material fns. Grid covers one bucket's `capacity`, not
   `NUM_TYPES * capacity`.

3. **A dispatch table + launcher**: `launchStageShadeBucketed` iterates material
   types, and for each **non-empty** bucket (`shade_counts[m] > 0`, already
   resident) launches `stageShadeBucketedKernelT<m>` on that bucket's slice. A
   `constexpr` type-list drives the instantiation; a plugin material family adds
   (a) its enum value, (b) its `if constexpr` arm (or, longer-term, a registered
   specialization), and (c) a type-list entry — **not** an edit to a shared
   runtime switch.

### Rejected alternative: device function-pointer registry

A `__device__` function-pointer table indexed by material type (the most
"plugin-native" shape) is **rejected for the hot path**: indirect `__device__`
calls defeat inlining and cross-function register/scheduling optimization on
CUDA, and would *regress* the shade path. Compile-time specialization keeps the
inlined codegen while still giving each family its own kernel. Plugin
registration can live at the *host* launch-table level (which
`stageShadeBucketedKernelT<m>` to launch), not as device indirect calls.

### The relic kernels are a pattern, not a target

`stageShadeLambertianKernel` / `stageShadeMetalKernel`
(`src/gpu/wavefront/stage_shade_lambertian.cu`, `stage_shade_metal.cu`) are
N+3-era per-type kernels that predate NEE/MIS/photon/cryptomatte and are
feature-incomplete. **Do not route production paths into them.** The
`template<int MatType>` kernel grows from the full `shadePathSlot<true>`, so it
carries every feature. The relics should be deleted or converted to the
templated form in the same change.

## Cost axis to measure (not assume)

The dispatch trades **1 launch/bounce for up-to-7 launches/bounce**. Launching
only non-empty buckets bounds this, but a scene exercising all families pays the
extra launch overhead every bounce. Because this is an **extensibility** change,
its acceptance bar is **no wall-time regression** on the perf-gate scene (burn-in
P0 + min-of-N, per the ledger protocol), not a speedup. If per-bucket launch
overhead measurably regresses, fall back to launching the concrete families
(0..5) individually while keeping `GMAT_CLOSURE_GRAPH` (and any residual
low-population buckets) merged in one general kernel.

## Scope / sequencing

- Independent of the ≤1.0s perf question — it can land whenever the plugin
  roadmap needs it, gated on bit-identity (`tests/wavefront_diff/`) + the perf
  gate as a no-regression tripwire.
- Correctness-frozen while pkg174 is open: this design is **not** implemented in
  the pkg174 perf PR (which is Exp1 only). Filed as a follow-up for the plugin
  arc.

## Citations

- Laine, Karras & Aila 2013, "Megakernels Considered Harmful: Wavefront Path
  Tracing on GPUs" — the wavefront/stage-split argument the codebase already
  cites from pkg55. Note this design applies its *material-coherence* half
  (already realized by the buckets) to codegen, not to occupancy.
