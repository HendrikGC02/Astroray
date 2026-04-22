#include "astroray/register.h"
#include "astroray/integrator.h"

class PathTracer : public Integrator {
    int maxDepth_;
    float rrThreshold_;
    Renderer* renderer_ = nullptr;
    const Camera* camera_ = nullptr;
public:
    explicit PathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          rrThreshold_(p.getFloat("rr_threshold", 0.1f)) {}

    void beginFrame(Renderer& scene, const Camera& cam) override {
        renderer_ = &scene;
        camera_ = &cam;
    }

    Vec3 sample(const Ray& ray, std::mt19937& gen) override {
        if (!renderer_) return Vec3(0);
        return renderer_->traceFull(ray, maxDepth_, gen).color;
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        if (!renderer_) return SampleResult{};
        return renderer_->traceFull(ray, maxDepth_, gen);
    }
};

ASTRORAY_REGISTER_INTEGRATOR("path", PathTracer)
