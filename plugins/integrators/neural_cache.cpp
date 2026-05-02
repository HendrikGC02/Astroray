#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/spectral.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <limits>
#include <memory>
#include <mutex>
#include <random>
#include <vector>

#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
#include "neural_cache.h"
#endif

namespace {

constexpr float kFeatureAabbLo = -2.2f;
constexpr float kFeatureAabbHi =  2.2f;
constexpr float kFeatureAabbSz = kFeatureAabbHi - kFeatureAabbLo;

float clamp01(float v) {
    return std::clamp(v, 0.0f, 1.0f);
}

Vec3 clampRadiance(const Vec3& c, float maxValue) {
    return Vec3(
        std::clamp(c.x, 0.0f, maxValue),
        std::clamp(c.y, 0.0f, maxValue),
        std::clamp(c.z, 0.0f, maxValue)
    );
}

void directionFeature(const Vec3& dir, float& theta, float& phi) {
    Vec3 d = dir.normalized();
    theta = std::acos(std::clamp(d.y, -1.0f, 1.0f)) / float(M_PI);
    phi = (std::atan2(d.z, d.x) + float(M_PI)) / (2.0f * float(M_PI));
}

std::array<float, 16> buildFeature(
        const HitRecord& rec,
        const Vec3& wo,
        float roughness,
        const Vec3& albedo) {
    std::array<float, 16> feat{};
    feat[0] = clamp01((rec.point.x - kFeatureAabbLo) / kFeatureAabbSz);
    feat[1] = clamp01((rec.point.y - kFeatureAabbLo) / kFeatureAabbSz);
    feat[2] = clamp01((rec.point.z - kFeatureAabbLo) / kFeatureAabbSz);
    directionFeature(wo, feat[3], feat[4]);
    directionFeature(rec.normal, feat[5], feat[6]);
    feat[7] = clamp01(roughness);
    feat[8] = std::max(0.0f, albedo.x);
    feat[9] = std::max(0.0f, albedo.y);
    feat[10] = std::max(0.0f, albedo.z);
    return feat;
}

std::vector<float> paddedFeatureBatch(const std::array<float, 16>& feat) {
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
    std::vector<float> batch(
        size_t(NeuralCache::BATCH_ALIGN) * NeuralCache::N_IN, 0.0f);
    std::copy(feat.begin(), feat.end(), batch.begin());
    return batch;
#else
    (void)feat;
    return {};
#endif
}

class NeuralCacheIntegrator : public Integrator {
    int maxDepth_;
    int warmupFrames_;
    int trainingPct_;
    int minTrainBatch_;
    int maxTrainSamples_;
    bool forceFallback_;
    bool enableInference_;
    int frameIndex_ = 0;
    bool backendReadyThisFrame_ = false;
    Renderer* renderer_ = nullptr;
    std::mutex cacheMutex_;
    std::mutex trainingMutex_;
    std::atomic<int> lastQueuedSamples_{0};
    std::atomic<int> lastTrainedSamples_{0};
    std::atomic<int> lastPaddedTrainSamples_{0};
    std::atomic<int> lastCacheQueries_{0};
    std::atomic<int> lastFallbackSamples_{0};
    std::atomic<int> totalQueuedSamples_{0};
    std::atomic<int> totalTrainedSamples_{0};
    std::atomic<int> totalTrainSteps_{0};

#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
    std::unique_ptr<NeuralCache> cache_;
    bool backendFailed_ = false;
    std::vector<float> pendingTrainFeatures_;
    std::vector<float> pendingTrainTargets_;
#endif

    astroray::SampledSpectrum envOnMiss(
            const Ray& ray,
            const astroray::SampledWavelengths& lambdas) const {
        const std::shared_ptr<EnvironmentMap>& envMap = renderer_->getEnvironmentMap();
        const Vec3& bgColor = renderer_->getBackgroundColor();
        if (envMap && envMap->loaded()) {
            return envMap->evalSpectral(ray.direction.normalized(), lambdas);
        }
        if (bgColor.x >= 0.0f) {
            return astroray::RGBIlluminantSpectrum(
                {bgColor.x, bgColor.y, bgColor.z}).sample(lambdas);
        }
        float t = 0.5f * (ray.direction.normalized().y + 1.0f);
        Vec3 bg = (Vec3(1.0f) * (1.0f - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
        return astroray::RGBIlluminantSpectrum({bg.x, bg.y, bg.z}).sample(lambdas);
    }

    astroray::SampledSpectrum directLighting(
            const HitRecord& rec,
            const Vec3& wo,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) const {
        astroray::SampledSpectrum direct(0.0f);
        if (rec.isDelta || renderer_->getLights().empty()) {
            return direct;
        }

        LightSample ls = renderer_->getLights().sample(rec.point, gen);
        if (ls.pdf <= 0.0f || !std::isfinite(ls.pdf)) {
            return direct;
        }

        Vec3 wi = (ls.position - rec.point).normalized();
        HitRecord shadow;
        bool hitOccluder = renderer_->getBVH()->hit(
            Ray(rec.point, wi), 0.001f, ls.distance - 0.001f, shadow);
        bool occluded = hitOccluder &&
            !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
        if (occluded) {
            return direct;
        }

        astroray::SampledSpectrum f =
            rec.material->evalSpectral(rec, wo, wi, lambdas);
        astroray::SampledSpectrum L =
            astroray::RGBIlluminantSpectrum(
                {ls.emission.x, ls.emission.y, ls.emission.z}).sample(lambdas);
        float bsdfPdf = rec.material->pdf(rec, wo, wi);
        float a = ls.pdf;
        float b = bsdfPdf;
        float wt = (a * a) / (a * a + b * b + 1e-8f);
        return f * L * (wt / (ls.pdf + 0.001f));
    }

    bool backendReady() {
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
        if (forceFallback_ || backendFailed_) {
            return false;
        }
        if (cache_) {
            return true;
        }
        try {
            cache_ = std::make_unique<NeuralCache>();
            return true;
        } catch (...) {
            backendFailed_ = true;
            return false;
        }
#else
        return false;
#endif
    }

    bool refreshBackendReady() {
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
        std::lock_guard<std::mutex> lock(cacheMutex_);
        return backendReady();
#else
        return false;
#endif
    }

    Vec3 queryCacheRGB(const std::array<float, 16>& feat) {
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
        if (!backendReadyThisFrame_) {
            return Vec3(0.0f);
        }
        std::lock_guard<std::mutex> lock(cacheMutex_);
        if (!cache_) {
            return Vec3(0.0f);
        }
        std::vector<float> input = paddedFeatureBatch(feat);
        std::vector<Vec3> out = cache_->query(NeuralCache::BATCH_ALIGN, input);
        lastCacheQueries_.fetch_add(1, std::memory_order_relaxed);
        return out.empty() ? Vec3(0.0f) : clampRadiance(out[0], 5.0f);
#else
        (void)feat;
        return Vec3(0.0f);
#endif
    }

    void enqueueTrainingSample(const std::array<float, 16>& feat, const Vec3& targetRGB) {
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
        if (maxTrainSamples_ <= 0) {
            return;
        }
        std::lock_guard<std::mutex> lock(trainingMutex_);
        size_t n = pendingTrainTargets_.size() / 3;
        if (n >= size_t(maxTrainSamples_)) {
            return;
        }
        Vec3 clamped = clampRadiance(targetRGB, 10.0f);
        pendingTrainFeatures_.insert(pendingTrainFeatures_.end(), feat.begin(), feat.end());
        pendingTrainTargets_.push_back(clamped.x);
        pendingTrainTargets_.push_back(clamped.y);
        pendingTrainTargets_.push_back(clamped.z);
        lastQueuedSamples_.fetch_add(1, std::memory_order_relaxed);
        totalQueuedSamples_.fetch_add(1, std::memory_order_relaxed);
#else
        (void)feat;
        (void)targetRGB;
#endif
    }

    void trainBufferedFrame() {
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
        if (!backendReadyThisFrame_) {
            return;
        }
        std::vector<float> features;
        std::vector<float> targets;
        {
            std::lock_guard<std::mutex> lock(trainingMutex_);
            features.swap(pendingTrainFeatures_);
            targets.swap(pendingTrainTargets_);
        }

        size_t n = targets.size() / 3;
        if (n == 0 || n < size_t(std::max(1, minTrainBatch_))) {
            return;
        }

        uint32_t nPadded = NeuralCache::roundUp(static_cast<uint32_t>(n));
        features.resize(size_t(nPadded) * NeuralCache::N_IN, 0.0f);
        targets.resize(size_t(nPadded) * 3, 0.0f);

        std::lock_guard<std::mutex> lock(cacheMutex_);
        if (cache_) {
            cache_->trainStep(nPadded, features, targets);
            lastTrainedSamples_.store(static_cast<int>(n), std::memory_order_relaxed);
            lastPaddedTrainSamples_.store(static_cast<int>(nPadded), std::memory_order_relaxed);
            totalTrainedSamples_.fetch_add(static_cast<int>(n), std::memory_order_relaxed);
            totalTrainSteps_.fetch_add(1, std::memory_order_relaxed);
        }
#endif
    }

    astroray::SampledSpectrum fullReference(
            const Ray& ray,
            astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) const {
        return renderer_->pathTraceSpectral(ray, maxDepth_, lambdas, gen);
    }

public:
    explicit NeuralCacheIntegrator(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 8))
        , warmupFrames_(std::max(0, p.getInt("warmup_frames", 16)))
        , trainingPct_(std::clamp(p.getInt("training_pct", 4), 0, 100))
        , minTrainBatch_(std::max(1, p.getInt("min_train_batch", 1)))
        , maxTrainSamples_(std::max(1, p.getInt("max_train_samples", 128)))
        , forceFallback_(p.getInt("force_fallback", 0) != 0)
        , enableInference_(p.getInt("enable_inference", 0) != 0) {}

    void beginFrame(Renderer& r, const Camera&) override {
        renderer_ = &r;
        ++frameIndex_;
        backendReadyThisFrame_ = refreshBackendReady();
        lastQueuedSamples_.store(0, std::memory_order_relaxed);
        lastTrainedSamples_.store(0, std::memory_order_relaxed);
        lastPaddedTrainSamples_.store(0, std::memory_order_relaxed);
        lastCacheQueries_.store(0, std::memory_order_relaxed);
        lastFallbackSamples_.store(0, std::memory_order_relaxed);
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
        std::lock_guard<std::mutex> lock(trainingMutex_);
        pendingTrainFeatures_.clear();
        pendingTrainTargets_.clear();
#endif
    }

    void endFrame() override {
        trainBufferedFrame();
    }

    std::unordered_map<std::string, float> debugStats() const override {
        return {
            {"buffered_training", 1.0f},
#if defined(ASTRORAY_NEURAL_CACHE_ENABLED)
            {"backend_compiled", 1.0f},
#else
            {"backend_compiled", 0.0f},
#endif
            {"force_fallback", forceFallback_ ? 1.0f : 0.0f},
            {"backend_ready", backendReadyThisFrame_ ? 1.0f : 0.0f},
            {"enable_inference", enableInference_ ? 1.0f : 0.0f},
            {"frame_index", static_cast<float>(frameIndex_)},
            {"warmup_frames", static_cast<float>(warmupFrames_)},
            {"training_pct", static_cast<float>(trainingPct_)},
            {"min_train_batch", static_cast<float>(minTrainBatch_)},
            {"max_train_samples", static_cast<float>(maxTrainSamples_)},
            {"last_queued_samples", static_cast<float>(lastQueuedSamples_.load(std::memory_order_relaxed))},
            {"last_trained_samples", static_cast<float>(lastTrainedSamples_.load(std::memory_order_relaxed))},
            {"last_padded_train_samples", static_cast<float>(lastPaddedTrainSamples_.load(std::memory_order_relaxed))},
            {"last_cache_queries", static_cast<float>(lastCacheQueries_.load(std::memory_order_relaxed))},
            {"last_fallback_samples", static_cast<float>(lastFallbackSamples_.load(std::memory_order_relaxed))},
            {"total_queued_samples", static_cast<float>(totalQueuedSamples_.load(std::memory_order_relaxed))},
            {"total_trained_samples", static_cast<float>(totalTrainedSamples_.load(std::memory_order_relaxed))},
            {"total_train_steps", static_cast<float>(totalTrainSteps_.load(std::memory_order_relaxed))}
        };
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult result;
        if (!renderer_ || !renderer_->getBVH()) {
            return result;
        }

        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));

        if (!backendReadyThisFrame_) {
            lastFallbackSamples_.fetch_add(1, std::memory_order_relaxed);
            astroray::XYZ xyz = fullReference(ray, lambdas, gen).toXYZ(lambdas);
            result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
            return result;
        }

        HitRecord rec;
        if (!renderer_->getBVH()->hit(
                ray, 0.001f, std::numeric_limits<float>::max(), rec)) {
            astroray::XYZ xyz = envOnMiss(ray, lambdas).toXYZ(lambdas);
            result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
            return result;
        }

        if (!rec.material || (rec.hitObject && rec.hitObject->isGRObject())) {
            astroray::XYZ xyz = fullReference(ray, lambdas, gen).toXYZ(lambdas);
            result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
            return result;
        }

        astroray::SampledSpectrum Le = rec.material->emittedSpectral(rec, lambdas);
        if (!Le.isZero()) {
            astroray::XYZ xyz = Le.toXYZ(lambdas);
            result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
            return result;
        }

        Vec3 wo = -ray.direction.normalized();
        astroray::SampledSpectrum color = directLighting(rec, wo, lambdas, gen);

        BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, gen, lambdas);
        if (bss.pdf <= 0.0f || !std::isfinite(bss.pdf)) {
            astroray::XYZ xyz = color.toXYZ(lambdas);
            result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
            return result;
        }

        astroray::SampledSpectrum f = bss.f_spectral;

        Ray next(rec.point, bss.wi, ray.time, ray.screenU, ray.screenV);
        next.hasCameraFrame = ray.hasCameraFrame;
        next.cameraOrigin = ray.cameraOrigin;
        next.cameraU = ray.cameraU;
        next.cameraV = ray.cameraV;
        next.cameraW = ray.cameraW;

        bool warmup = frameIndex_ <= warmupFrames_;
        bool trainThisSample = warmup && (dist01(gen) * 100.0f < float(trainingPct_));
        Vec3 albedo = rec.material->getAlbedo();
        float roughness = rec.material->isGlossy() ? 0.35f : 1.0f;
        auto feat = buildFeature(rec, wo, roughness, albedo);

        if (warmup || !enableInference_) {
            astroray::SampledSpectrum tail =
                renderer_->pathTraceSpectral(next, std::max(1, maxDepth_ - 1), lambdas, gen);
            astroray::SampledSpectrum indirect = f * tail * (1.0f / (bss.pdf + 0.001f));
            if (trainThisSample) {
                astroray::XYZ xyz = indirect.toXYZ(lambdas);
                Vec3 rgb = xyzToLinearSRGB(Vec3(xyz.X, xyz.Y, xyz.Z));
                enqueueTrainingSample(feat, rgb);
            }
            color += indirect;
        } else {
            Vec3 rgb = queryCacheRGB(feat);
            color += astroray::RGBIlluminantSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
        }

        astroray::XYZ xyz = color.toXYZ(lambdas);
        result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        return result;
    }
};

} // namespace

ASTRORAY_REGISTER_INTEGRATOR("neural-cache", NeuralCacheIntegrator)
