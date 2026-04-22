#include "astroray/register.h"
#include "astroray/integrator.h"

// Demo integrator: returns a greyscale ambient-occlusion value by sampling
// the hemisphere around the primary hit normal.  Non-hit rays return white.
class AmbientOcclusion : public Integrator {
    float maxDist_;
    const Renderer* renderer_ = nullptr;
public:
    explicit AmbientOcclusion(const astroray::ParamDict& p)
        : maxDist_(p.getFloat("max_distance", 1.0f)) {}

    void beginFrame(Renderer& scene, const Camera&) override { renderer_ = &scene; }

    Vec3 sample(const Ray& ray, std::mt19937& gen) override {
        if (!renderer_) return Vec3(1.0f);
        const auto* bvh = renderer_->getBVH().get();
        if (!bvh) return Vec3(1.0f);
        HitRecord rec;
        if (!bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec))
            return Vec3(1.0f);
        Vec3 u, v;
        buildOrthonormalBasis(rec.normal, u, v);
        Vec3 local = Vec3::randomCosineDirection(gen);
        Vec3 dir = (u * local.x + v * local.y + rec.normal * local.z).normalized();
        HitRecord shadow;
        float vis = bvh->hit(Ray(rec.point, dir), 0.001f, maxDist_, shadow) ? 0.0f : 1.0f;
        return Vec3(vis);
    }
};

ASTRORAY_REGISTER_INTEGRATOR("ambient_occlusion", AmbientOcclusion)
