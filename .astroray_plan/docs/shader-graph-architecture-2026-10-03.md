# Shader-graph execution architecture (P4 fork) — Astra memo, 2026-10-03

**Decision (lead, 2026-10-03): adopt B** — shared per-hit graph interpreter in a dedicated graph-eval kernel (never inlined into the shade kernel); op-VM retained as an equivalent small-program lowering; NVRTC JIT later on the same IR. Source: Codex `gpt-6-astra` (high), read-only review of main 48ef43b2 + lane/ar-1007. Phases below are the plan of record for the Stage 0 gate (b) node work (#990 #991 #992 #993 #995 #1005 #1006).

---

Choose **B: a shared per-hit graph interpreter, with the existing op-VM retained as a small-program fast path and NVRTC added later as an optimization backend.**

This memo reflects main `48ef43b2` and inspection of #1007’s implementation on `lane/ar-1007` (`c8ca3d6b`). The procedural evaluator files are on that branch, not main. No files were changed; no builds or render tests were run.

**1. The decisive reasons favor B.**

The corpus identifies per-hit inputs and closure composition as blockers for four materials each; bounds contribute to two, and neither fails on bounds alone. Enlarging A therefore cannot deliver the exit gate. Moreover, ordinary scalar chains allocate slots monotonically; only coordinate programs recycle temporaries. #993 does not establish that eight simultaneously live values are insufficient. [Corpus analysis](C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/docs/pkg310-production-corpus-burndown.md:96), [compiler](C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/blender_addon/shader_vm_compiler.py:127).

B must **not** insert Cycles’ stack directly into `shadePathSlot`. Generic variants already reach REG 254; stack traffic dominated the measured workload. Preserve the dedicated fleet kernels—REG 128/198—and isolate graph execution. Likewise, today’s excellent branch uniformity measures simple material buckets, not heterogeneous shader programs. [pkg300 measurements](C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/docs/pkg300-shade-counter-attribution.md).

Compile the interpreter once, outside the shade-template multiplication. The measured 509-second build versus 1,189 seconds for fully inlined variants makes this consequential. Material edits then upload bytecode rather than rebuild kernels.

B preserves single-source opcode semantics, reuses #1007’s shared procedural math, and accommodates texture reads, shading context and closure emission in one program. Cycles supplies an established semantic reference, but its interpreter explicitly uses local stack storage; copying its memory strategy is not automatically appropriate here. [Cycles SVM](https://raw.githubusercontent.com/blender/blender/blender-v4.5-release/intern/cycles/kernel/svm/svm.h).

B costs more initially than raising bounds, but A eventually needs the same context and closure work. JIT-first adds compilation, caching, linking and fallback machinery before fixing semantics. Honor the approved post-pkg300 JIT direction by targeting the same intermediate representation; NVRTC itself is a compiler, not a complete linking/runtime system. [NVRTC documentation](https://docs.nvidia.com/cuda/nvrtc/index.html#separate-compilation).

**2. Migrate in phases, with both backends delivered together.**

1. **Establish the contract and resource prototype.** Define a versioned, typed graph representation with shared opcode implementations and explicit texture/context services. Record instruction count, peak live scalar slots, resource counts and maximum emitted closures for every corpus graph. Add common-subexpression elimination and last-use slot reuse. Compare old/new CPU/GPU evaluations before changing export routing; prototype graph execution and closure consumption on sm_120 before expanding coverage.

2. **Deliver dynamic value programs.** Store instructions, constants, texture descriptors and curve/ramp tables in immutable global arenas. Per-program descriptors contain offsets, lengths, slot count and closure capacity; use 32-bit addressing rather than today’s byte indices and embedded arrays. Texture instructions consume computed coordinates and parameters, eliminating caller-side pre-sampling limits. This also removes the current scalar GPU path’s broadcasting of one fetched input across all VM inputs. [Call sites](C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/src/gpu/wavefront/stage_advance_device.cuh:1708).

   Use a dedicated graph-evaluation kernel and queue-local scratch, followed by graph-aware shading. Allocate scratch by program requirements in bounded batches: 65,536 hits × 64 float slots costs 16 MiB before closure payloads. Store neither stack nor closures in `GPUWavefrontHitBuffers`; leave `GMaterial` unchanged. Program-size limits become checked resource budgets, with explicit failure rather than truncation. Test repeated consumers, multiple mappings, >2 textures, >32 instructions and #993.

3. **Supply the missing semantics.** Implement #992 curves with Blender-compatible domain, extrapolation, channel composition and factor behavior. #990 requires exported attribute domains/interpolation and instance data; #1006 requires inverse object transforms and reliable object identity. #991 needs path flags/depth/length and evaluation during shadow transparency and emitter sampling, not merely surface hits. #1005 needs footprint differentials and correctly transformed bump taps; use optional path-state storage where necessary, never enlarge the hit buffer. Port each service to CPU/GPU together. Pointiness and residual Noise fidelity remain explicit corpus blockers.

4. **Enable graph closures and score the gate.** Switch whole-material export to the closure contract below. Retain the op-VM as an equivalent lowering for small eligible programs, not an independently evolving language. Every phase requires CPU/GPU value probes, existing regression suites and affected Cycles comparisons. Completion means **8/8 on both backends**, every required ROI channel passing, zero silent drops, removed resolved strict-xfail entries, and inspected images—not merely green tests containing xfails.

After pkg300 Phases 0–2, JIT the same representation asynchronously while the interpreter renders. Cache by graph, semantics/build version, architecture and compilation options; require interpreter/JIT equivalence before activation.

**3. Closures require a new composition contract around existing BSDF implementations.**

`GMAT_CLOSURE_GRAPH` is useful machinery, but currently has eight embedded entries, one shared advanced-Principled parameter block, and normalized graph evaluation. Multiple independently parameterized Principled nodes and Add Shader cannot be represented faithfully by simply appending entries. [GPU layout](C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/include/astroray/gpu_types.h:456), [evaluation](C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/include/astroray/gpu_materials.h:3054).

Emit a flat closure list into temporary storage: type, physical weight, parameter-block reference, and shading frame per closure. Preserve Principled as a monolithic closure with its own parameters.

For `Mix(A,B,f)`, propagate incoming weight multiplied by `1−clamp(f)` and `clamp(f)`; nested mixes multiply along each branch. Add propagates the incoming weight unchanged to both children. This matches Cycles’ mix-weight propagation. [Cycles closure implementation](https://raw.githubusercontent.com/blender/blender/blender-v4.5-release/intern/cycles/kernel/svm/closure.h).

Separate **physical weights** from **sampling probabilities**:

- Evaluate `F = Σ wᵢFᵢ`, without normalizing away Add’s energy.
- Sample with normalized probabilities `qᵢ`; continuous mixture PDF is `Σ qᵢpᵢ`.
- Handle delta probability masses explicitly; accumulate emission separately.

Evaluate spectral closures before summation. Preserve legacy normalized behavior through an explicit adapter; globally removing normalization would reopen previous Disney energy failures.

**4. The three principal risks have early detection gates.**

1. **Memory traffic replaces register pressure.** Measure registers, stack, local/global bytes, occupancy and total render time—including launches/sorting—on corpus and mixed-material stress scenes. Require unchanged non-program fleet SASS; start without sorting and add program grouping only when beneficial.
2. **Closure energy/MIS errors.** Test nested textured mixes, independent Principled normals, glass deltas and Add emission. Use linear floor-and-ceiling energy tests; additive closures need additive expectations.
3. **Shared wrong semantics masquerade as parity.** CPU==GPU is insufficient. Compare against Cycles under transformed instances, attribute seams, shadow-ray tricks and changing bump footprint; audit every reachable unsupported socket.

VERDICT: B A shared graph interpreter addresses the dominant semantic failures while isolating GPU resource costs and providing the correctness baseline for later material JIT.
