#pragma once
#include "../raytracer.h"
#include "astroray/spectral.h"
#include "astroray/param_dict.h"
#include <random>

// Discriminates RGB- vs spectral-native integrators. The Renderer reads
// kind() once per setIntegrator() call to switch its per-pixel accumulator
// between RGB and XYZ. pkg14 deletes this enum when the legacy RGB path
// is removed.
enum class IntegratorKind { RGB, Spectral };

class Integrator {
public:
    virtual ~Integrator() = default;

    // Returns RGB radiance. Called once per sample per pixel.
    virtual Vec3 sample(const Ray& cameraRay, std::mt19937& gen) = 0;

    // Capability flag: spectral integrators advertise IntegratorKind::Spectral
    // and must populate SampleResult::color with the XYZ projection of the
    // path's spectral radiance. Default RGB keeps every existing plugin
    // working unchanged.
    virtual IntegratorKind kind() const { return IntegratorKind::RGB; }

    // Optional per-frame setup (reservoirs, cache warmup).
    virtual void beginFrame(Renderer&, const Camera&) {}
    virtual void endFrame() {}

    // Full-path sample: returns color plus first-hit AOV data and render passes.
    // Default implementation calls sample() and returns zero AOVs.
    // PathTracer overrides this to fill all AOV buffers via the existing pathTrace path.
    virtual SampleResult sampleFull(const Ray& ray, std::mt19937& gen) {
        SampleResult r;
        r.color = sample(ray, gen);
        return r;
    }

    // Spectral variant. Default: call sample() and treat the RGB result as a flat
    // spectrum (Y channel) across all wavelengths. Spectral-native integrators
    // override this; the actual spectral path tracer comes in Pillar 2 (pkg11).
    virtual SpectralSample sampleSpectral(const Ray& ray,
                                          const SpectralSample& wls,
                                          std::mt19937& gen) {
        Vec3 rgb = sample(ray, gen);
        float lum = 0.2126f * rgb.x + 0.7152f * rgb.y + 0.0722f * rgb.z;
        SpectralSample result = wls;
        for (int i = 0; i < 4; ++i) result.radiance[i] = lum;
        return result;
    }
};
