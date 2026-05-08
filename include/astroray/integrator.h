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
    virtual void beginFrame(Renderer&, const Camera&) {}
    virtual void endFrame() {}

    // Optional observability for tests and developer diagnostics.
    virtual std::unordered_map<std::string, float> debugStats() const { return {}; }

    // Backend support metadata for UI diagnostics and GPU fallback policy.
    virtual IntegratorCapabilities capabilities() const { return {}; }

    // Full-path sample: returns XYZ color plus first-hit AOV data and render passes.
    virtual SampleResult sampleFull(const Ray& ray, std::mt19937& gen) = 0;
};
