#include "astroray/register.h"
#include "astroray/spectrum.h"
#include "astroray/integrator.h"

// Pillar 3 light-transport: caustic-aware spectral path tracing.
//
// Strategy: Manifold Next Event Estimation (MNEE) for specular chains.
// We keep the existing unidirectional spectral kernel for baseline transport,
// but add an optional specular-caustic connection step when a path enters a
// delta transmission/reflection chain (glass, prisms). This targets the common
// "prism -> screen" and "glass caustic on diffuse" cases without a full BDPT.
//
// This is intentionally scoped: CPU reference stays available, existing
// integrator behavior remains default unless selected explicitly.
class CausticPathTracer : public Integrator {
    int maxDepth_;
    int maxManifoldIters_;
    Renderer* renderer_ = nullptr;

public:
    explicit CausticPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          maxManifoldIters_(p.getInt("mnee_iters", 8)) {}

    void beginFrame(Renderer& scene, const Camera&) override {
        renderer_ = &scene;
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;

        // First-hit AOV data.
        if (auto bvh = renderer_->getBVH()) {
            HitRecord rec;
            if (bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) && rec.material) {
                r.albedo = rec.material->getAlbedo();
                r.depth = rec.t;
            }
        }

        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));

        int bounces = 0;
        float weight = 0.0f;
        astroray::SampledSpectrum rad = renderer_->pathTraceSpectralCaustic(
            ray, maxDepth_, maxManifoldIters_, lambdas, gen, &bounces, &weight);
        astroray::XYZ xyz = rad.toXYZ(lambdas);
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        r.bounceCount = static_cast<float>(bounces);
        r.sampleWeight = weight;
        return r;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("caustic_path_tracer", CausticPathTracer)
