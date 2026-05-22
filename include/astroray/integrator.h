#pragma once
#include "../raytracer.h"
#include "astroray/spectral.h"
#include "astroray/param_dict.h"
#include <random>
#include <string>
#include <unordered_map>

struct IntegratorCapabilities {
    bool gpuSupported = false;
    std::string gpuFallbackReason = "no GPU kernel implemented";
};

class Integrator {
public:
    virtual ~Integrator() = default;

    // Optional per-frame setup (reservoirs, cache warmup).
    // pkg87b: Camera is now non-const to allow Cryptomatte per-shade-point writes.
    virtual void beginFrame(Renderer&, Camera&) {}
    virtual void endFrame() {}

    // Optional observability for tests and developer diagnostics.
    virtual std::unordered_map<std::string, float> debugStats() const { return {}; }

    // Backend support metadata for UI diagnostics and GPU fallback policy.
    virtual IntegratorCapabilities capabilities() const { return {}; }

    // pkg91: runtime max-depth mutation (called by Renderer::render once per
    // frame, before the tile loop). Default impl is a no-op; integrators that
    // store maxDepth_ override this to update their private member. Cycles
    // pattern (intern/cycles/integrator/path_trace.h set_max_bounces).
    virtual void setMaxDepth(int depth) { (void)depth; }

    // Full-path sample: returns XYZ color plus first-hit AOV data and render passes.
    virtual SampleResult sampleFull(const Ray& ray, std::mt19937& gen) = 0;
};
