#pragma once
#include "../raytracer.h"
#include "astroray/spectral.h"
#include "astroray/param_dict.h"
#include <random>

class Integrator {
public:
    virtual ~Integrator() = default;

    // Optional per-frame setup (reservoirs, cache warmup).
    virtual void beginFrame(Renderer&, const Camera&) {}
    virtual void endFrame() {}

    // Full-path sample: returns XYZ color plus first-hit AOV data and render passes.
    virtual SampleResult sampleFull(const Ray& ray, std::mt19937& gen) = 0;
};
