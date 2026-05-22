#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"

class CausticPathTracer : public Integrator {
    int maxDepth_;
    int chainIters_;
    Renderer* renderer_ = nullptr;
    Camera* camera_ = nullptr;  // pkg87b
    float causticConnections_ = 0.0f;
    float causticEnergy_ = 0.0f;

public:
    explicit CausticPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          chainIters_(p.getInt("caustic_chain_iters", 3)) {}

    void beginFrame(Renderer& scene, Camera& cam) override {
        renderer_ = &scene;
        camera_ = &cam;  // pkg87b
        causticConnections_ = 0.0f;
        causticEnergy_ = 0.0f;
    }

    std::unordered_map<std::string, float> debugStats() const override {
        return {
            {"caustic_connections", causticConnections_},
            {"caustic_energy", causticEnergy_},
            {"caustic_chain_iters", static_cast<float>(chainIters_)},
        };
    }

    IntegratorCapabilities capabilities() const override {
        return {false, "caustic chain connection integrator has no CUDA kernel"};
    }

    void setMaxDepth(int depth) override {
        maxDepth_ = depth;
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;

        if (const auto* bvh = renderer_->getBVH().get()) {
            HitRecord rec;
            if (bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) && rec.material) {
                r.albedo = rec.material->getAlbedo();
                r.depth = rec.t;
            }
        }

        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));

        // pkg87b: Cryptomatte per-shade-point accumulation.
        float* cryptoObjRanks = nullptr;
        float* cryptoMatRanks = nullptr;
        int cryptoDepth = 6;
        if (renderer_->getCryptomatteEnabled() && camera_) {
            int pixelX = static_cast<int>(ray.screenU * (camera_->width - 1));
            int pixelY = static_cast<int>((1.0f - ray.screenV) * (camera_->height - 1));
            pixelX = std::max(0, std::min(pixelX, camera_->width - 1));
            pixelY = std::max(0, std::min(pixelY, camera_->height - 1));
            int pixelIndex = pixelY * camera_->width + pixelX;
            int offset = pixelIndex * camera_->cryptomatteDepth * 2;
            cryptoObjRanks = camera_->cryptoObjectBuffer.data() + offset;
            cryptoMatRanks = camera_->cryptoMaterialBuffer.data() + offset;
            cryptoDepth = camera_->cryptomatteDepth;
        }

        int bounces = 0;
        float weight = 0.0f;
        int connections = 0;
        float energy = 0.0f;
        astroray::SampledSpectrum rad = renderer_->pathTraceSpectralCaustic(
            ray, maxDepth_, chainIters_, lambdas, gen, &bounces, &weight,
            &connections, &energy, cryptoObjRanks, cryptoMatRanks, cryptoDepth);
        astroray::XYZ xyz = rad.toXYZ(lambdas);
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        r.bounceCount = static_cast<float>(bounces);
        r.sampleWeight = weight;
        causticConnections_ += static_cast<float>(connections);
        causticEnergy_ += energy;
        return r;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("caustic_path_tracer", CausticPathTracer)
