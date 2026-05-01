# Pillar 3: Light Transport Upgrades

**Status:** Validation (pkg20-pkg28 implemented; acceptance scenes pending)
**Depends on:** Pillars 1, 2
**Track:** A (ReSTIR core), C (neural cache prototype)
**Duration:** 4–6 weeks

## Goal

Add two state-of-the-art path tracing techniques as plugin integrators:
**ReSTIR DI** for dramatically better direct lighting and **Neural
Radiance Caching** for indirect illumination speedup. The classic path
tracer remains the default; these are opt-in.

## Why these two, not everything

The 2025 survey paper (research report §3) lists ~15 viable techniques.
Two were picked deliberately:

- **ReSTIR DI** — single biggest quality-per-cost win available. Drops
  into the existing NEE+MIS slot. Adds 1–2 ms per frame at 1080p.
  Improves direct-lighting variance by 10–100× in scenes with many
  lights. Essential for Blender-viewport interactivity.
- **Neural Radiance Caching** — specifically good at indirect
  illumination. Complements ReSTIR DI (which only helps direct).
  40–70% speedup in complex indirect scenes. Controllable bias.

Other techniques (BDPT, MLT, photon mapping, PPG) are lower priority:
either the quality lift is smaller, the implementation cost is higher,
or they overlap with ReSTIR/NRC. They can be added later as plugins;
nothing here precludes them.

## Reference implementations

### ReSTIR DI

- **RTXDI SDK 3.0**: https://github.com/NVIDIA-RTX/RTXDI
  Production-quality HLSL/GLSL implementation. We translate the core
  algorithm to CUDA (already have CUDA infra from Pillar 1+2) — not the
  D3D12 plumbing. Budget: the reservoir data structure and the three
  kernels (initial sample, temporal reuse, spatial reuse).
- **Original paper**: Bitterli et al., "Spatiotemporal reservoir
  resampling for real-time ray tracing with dynamic direct lighting,"
  SIGGRAPH 2020.
- **Reference port (simpler, educational)**:
  https://github.com/Apress/Ray-Tracing-Gems-II ch. 23 "ReSTIR DI".

### Neural Radiance Caching

- **tiny-cuda-nn**: https://github.com/NVlabs/tiny-cuda-nn
  Fused-MLP library on Tensor Cores. FP16 inference in ~2.6 ms at
  1080p. BSD-3 license. Adds a CUDA-dependent submodule; our build
  already has CUDA so this integrates cleanly.
- **Original paper**: Müller et al., "Real-time Neural Radiance Caching
  for Path Tracing," SIGGRAPH 2021.
- **Reference pattern**: falcor-ngp and the instant-ngp repo at
  https://github.com/NVlabs/instant-ngp have the inference pattern.

## Design

### The Integrator interface

Added as part of Pillar 1 (step 5 of that migration). Looks like:

```cpp
// include/astroray/integrator.h
class Integrator {
public:
    virtual ~Integrator() = default;

    // Chance to build per-frame data structures (ReSTIR reservoirs,
    // neural cache training buffers).
    virtual void beginFrame(Renderer&, const Camera&) {}
    virtual void endFrame() {}

    // Full-path sample: returns XYZ color plus first-hit AOV data and render
    // passes. The current path_tracer implementation is spectral-first.
    virtual SampleResult sampleFull(const Ray& ray, std::mt19937& gen) = 0;
};

ASTRORAY_REGISTER_INTEGRATOR("path_tracer", PathTracer)
ASTRORAY_REGISTER_INTEGRATOR("restir-di", ReSTIRDI)
ASTRORAY_REGISTER_INTEGRATOR("neural-cache", NeuralCache)
```

User selects integrator via Blender property, Python API
`renderer.set_integrator("restir-di")`, or CLI flag.

### ReSTIR DI — the minimal skeleton

```cpp
struct Reservoir {
    LightSample y;      // the currently chosen sample
    float w_sum;        // sum of weights
    int M;              // number of candidates seen
    float W;            // final RIS weight
    void update(LightSample x, float w, std::mt19937& gen);
};

class ReSTIRDI : public Integrator {
public:
    void beginFrame(const Scene&, const Camera&) override;
    Vec3 sample(const Ray&, std::mt19937&) override;
private:
    std::vector<Reservoir> reservoirs_;     // one per pixel
    std::vector<Reservoir> reservoirsPrev_; // temporal reuse
    // ... three kernels: initial, temporal, spatial
};
```

Three kernels, roughly 200 lines each. The data flow is what matters;
the algorithms are well-documented. Initial implementation is CUDA;
CPU fallback deferred (not essential — ReSTIR is GPU-first by design).

### Neural Radiance Caching — phased approach

Because tiny-cuda-nn is a significant dependency and NRC is
experimental, this goes through track C first:

1. **Prototype (track C, Cline)**: get tiny-cuda-nn building alongside
   Astroray. Verify inference works on a dummy network. No integration.
2. **Feasibility (track A, Claude Code)**: promote the prototype to a
   minimal `NeuralCache` integrator that queries a 2-hidden-layer MLP
   for indirect radiance at each bounce. Training happens online,
   same-frame.
3. **Production (track A)**: add proper training/inference
   double-buffering, cache warmup, bias-variance controls.

### Interaction with spectral pipeline

ReSTIR is naturally spectral-aware because it operates on
`SampledSpectrum` radiance, not RGB. The RIS weight is the target-pdf
luminance at the current wavelengths, which already exists on
`SampledSpectrum`.

NRC is RGB-only as originally published. We train on
`SampledSpectrum.toXYZ(lambdas) → sRGB` and query similarly. Spectral
NRC is a research project for another day.

## Migration strategy

### Phase 3A: Integrator interface + path tracer plugin (part of Pillar 1)

No net work here — just surface the existing path tracer through the
new interface. `pkg05-integrator-interface.md` lands as part of Pillar
1.

### Phase 3B: ReSTIR DI (2–3 weeks, track A)

- `pkg20-reservoir-core.md` — reservoir type, invariants, and unit
  tests.
- `pkg21-light-sample-abstraction.md` — reusable direct-light candidate
  payload and spectral target-weight helpers.
- `pkg22-restir-initial-sampling.md` — opt-in `restir-di` prototype with
  initial candidate generation only.
- `pkg23-restir-temporal-spatial-design.md` — temporal/spatial reuse
  design, history ownership, validation gates, and CPU/GPU boundary.
  Detailed design note: `.astroray_plan/docs/restir-temporal-spatial-design.md`.
- `pkg24-restir-validation.md` — validation scenes and bias/variance
  checks against vanilla path tracer.

### Phase 3C: NRC prototype (1–2 weeks, track C)

- `pkg25-tiny-cuda-nn-prototype.md` — build-system and dummy network.
- `pkg26-nrc-prototype.md` — standalone integrator test, not wired
  into plugin system yet.

### Phase 3D: NRC production (1–2 weeks, track A)

- `pkg27-nrc-plugin.md` — promote prototype, wire as
  `ASTRORAY_REGISTER_INTEGRATOR("neural-cache", NeuralCache)`.
  Implemented with a default-build fallback and an opt-in tiny-cuda-nn backend.
- `pkg28-nrc-training-buffer.md` — double-buffered training. Implemented with
  frame-buffered targets and one aligned `endFrame()` training step.

## Acceptance criteria

- [ ] ReSTIR DI renders the Sponza scene with equal or better quality
      than vanilla path tracer at 4× fewer samples per pixel.
- [ ] ReSTIR DI matches vanilla path tracer converged output within
      noise tolerance (no systematic bias).
- [ ] NRC reduces indirect-dominated scene render time by ≥30% at equal
      quality on the Cornell box with sphere light source.
- [ ] Both integrators are selectable from Blender UI and via the
      Python API without touching core code.
- [ ] Unit tests verify reservoir invariants (W ≥ 0, M correctly
      accumulated).

## Non-goals

- **ReSTIR GI** (indirect light reservoir reuse). Paper is young,
  quality is mixed. NRC covers this space.
- **Full neural path guiding (Müller et al. 2019).** Different
  technique, significant implementation cost, modest additional win
  over NRC.
- **BDPT, MLT, photon mapping.** Future plugins; nothing here blocks
  them.
