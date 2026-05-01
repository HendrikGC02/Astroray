#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"

// Pillar 2 spectral path tracer (pkg11, default since pkg14).
// SampleResult.color is the XYZ projection of the path's spectral radiance;
// Renderer converts XYZ to linear sRGB exactly once before gamma.
class SpectralPathTracer : public Integrator {
    int maxDepth_;
    Renderer* renderer_ = nullptr;
public:
    explicit SpectralPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)) {}

    void beginFrame(Renderer& scene, const Camera&) override {
        renderer_ = &scene;
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;
        // Populate first-hit albedo AOV.
        const auto* bvh = renderer_->getBVH().get();
        if (bvh) {
            HitRecord rec;
            if (bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) && rec.material)
                r.albedo = rec.material->getAlbedo();
        }
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

ASTRORAY_REGISTER_INTEGRATOR("path_tracer", SpectralPathTracer)
