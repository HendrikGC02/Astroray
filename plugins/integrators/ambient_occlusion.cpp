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

    Camera* camera_ = nullptr;  // pkg87b

    void beginFrame(Renderer& scene, Camera& cam) override {
        renderer_ = &scene;
        camera_ = &cam;  // pkg87b
    }

    IntegratorCapabilities capabilities() const override {
        return {true, ""};
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) { r.color = Vec3(1.0f); return r; }
        const auto* bvh = renderer_->getBVH().get();
        if (!bvh) { r.color = Vec3(1.0f); return r; }
        HitRecord rec;
        if (!bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec)) {
            r.color = Vec3(1.0f);
            return r;
        }
        Vec3 u, v;
        buildOrthonormalBasis(rec.normal, u, v);
        Vec3 local = Vec3::randomCosineDirection(gen);
        Vec3 dir = (u * local.x + v * local.y + rec.normal * local.z).normalized();
        HitRecord shadow;
        float vis = bvh->hit(Ray(rec.point, dir), 0.001f, maxDist_, shadow) ? 0.0f : 1.0f;

        // pkg87b: Cryptomatte accumulation for AO integrator.
        // Weight = visibility-fraction (the degenerate Cycles behaviour for non-lighting integrators).
        if (renderer_->getCryptomatteEnabled() && camera_) {
            int pixelX = static_cast<int>(ray.screenU * (camera_->width - 1));
            int pixelY = static_cast<int>((1.0f - ray.screenV) * (camera_->height - 1));
            pixelX = std::max(0, std::min(pixelX, camera_->width - 1));
            pixelY = std::max(0, std::min(pixelY, camera_->height - 1));
            int pixelIndex = pixelY * camera_->width + pixelX;
            int offset = pixelIndex * camera_->cryptomatteDepth * 2;
            float* cryptoObjRanks = camera_->cryptoObjectBuffer.data() + offset;
            float* cryptoMatRanks = camera_->cryptoMaterialBuffer.data() + offset;

            float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
            if (rec.hitObject && !rec.hitObject->getName().empty()) {
                objectId = crypto_hash_name(rec.hitObject->getName());
            }
            if (rec.material && !rec.material->getName().empty()) {
                materialId = crypto_hash_name(rec.material->getName());
            }
            crypto_accumulate_shade_point(cryptoObjRanks, cryptoMatRanks,
                                           0, camera_->cryptomatteDepth, objectId, materialId, vis);
        }

        r.color = Vec3(vis);
        return r;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("ambient_occlusion", AmbientOcclusion)
