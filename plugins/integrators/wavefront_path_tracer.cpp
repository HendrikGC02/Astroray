// wavefront_path_tracer.cpp — pkg55 Phase B
//
// CPU-side integrator plugin shell for the wavefront GPU path tracer.
// The actual rendering happens in cuda_renderer.cu via wavefrontRenderSample();
// this plugin exists so the Blender addon can select "wavefront_path_tracer"
// from the integrator dropdown and the CUDARenderer detects gpuSupported=true.
//
// sampleFull() is a no-op stub — the wavefront path is driven entirely
// from CUDARenderer::render() when the integrator name is "wavefront_path_tracer".
// CPU fallback renders via the default path_tracer integrator.
//
// Architecture: Cycles blender_python.cpp / blender_render.cpp (Apache-2.0)
//   The integrator plugin is a registry marker; Cycles does the same with
//   its PathIntegrator CPU stub that defers to the GPU session.

#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/param_dict.h"

class WavefrontPathTracer : public Integrator {
    int maxDepth_;
public:
    explicit WavefrontPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)) {}

    IntegratorCapabilities capabilities() const override {
        return {true, ""};  // gpuSupported = true
    }

    SampleResult sampleFull(const Ray& /*ray*/, std::mt19937& /*gen*/) override {
        // CPU path: falls back to the megakernel path tracer when CUDA is
        // unavailable. CUDARenderer bypasses sampleFull() entirely.
        return {};
    }
};

ASTRORAY_REGISTER_INTEGRATOR("wavefront_path_tracer", WavefrontPathTracer)
