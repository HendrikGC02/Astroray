#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"

// Pillar 2 spectral path tracer (pkg11). Opt-in via
// `set_integrator("spectral_path_tracer")`. The legacy RGB `path_tracer`
// remains the registry default until pkg14 flips it.
//
// SampleResult.color is populated with the XYZ projection of the path's
// spectral radiance; the Renderer (when its integrator advertises
// IntegratorKind::Spectral) treats the per-pixel accumulator as XYZ and
// converts to linear sRGB exactly once before gamma.
class SpectralPathTracer : public Integrator {
    int maxDepth_;
    Renderer* renderer_ = nullptr;
public:
    explicit SpectralPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)) {}

    IntegratorKind kind() const override { return IntegratorKind::Spectral; }

    void beginFrame(Renderer& scene, const Camera&) override {
        renderer_ = &scene;
    }

    Vec3 sample(const Ray&, std::mt19937&) override {
        // Unused: the Renderer dispatches through sampleFull when kind() is
        // Spectral. Returning zero keeps the pure-virtual contract honest.
        return Vec3(0);
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));
        astroray::SampledSpectrum rad =
            renderer_->pathTraceSpectral(ray, maxDepth_, lambdas, gen);
        astroray::XYZ xyz = rad.toXYZ(lambdas);
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        return r;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("spectral_path_tracer", SpectralPathTracer)
