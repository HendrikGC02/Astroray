#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/spectral_profile.h"
#include "raytracer.h"
#include <cmath>

// pkg39: Multi-wavelength path tracer.
//
// Registers as "multiwavelength_path_tracer". Supports:
//   lambda_min / lambda_max  — wavelength band to render (nm). Default: 380/780.
//   max_depth                — max path depth. Default: 50.
//   output_mode              — "xyz" (visible, default) or "luminance" (for IR/UV).
//
// When lambda range overlaps [380, 780]: identical to spectral_path_tracer.
// Outside visible: uses SpectralProfile data attached to materials (evalSpectralExt).
// Materials with no profile render black outside the visible band.
// Sky environment outside visible uses a Rayleigh scattering approximation (λ^-4).

class MultiwavelengthPathTracer : public Integrator {
    int   maxDepth_;
    float lambdaMin_;
    float lambdaMax_;
    bool  useLuminanceOutput_;  // true when rendering outside visible
    Renderer* renderer_ = nullptr;

    static constexpr float kVisMin = 380.0f;
    static constexpr float kVisMax = 780.0f;
    static constexpr float kRayleighRef = 550.0f;  // reference wavelength for sky

    // Rayleigh sky radiance scale for a given wavelength relative to 550 nm.
    static float rayleighScale(float lambda_nm) {
        float r = kRayleighRef / lambda_nm;
        return r * r * r * r;  // λ^-4 Rayleigh
    }

    bool isInsideVisible(float lmin, float lmax) const {
        return lmin >= kVisMin - 0.5f && lmax <= kVisMax + 0.5f;
    }

public:
    explicit MultiwavelengthPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50))
        , lambdaMin_(p.getFloat("lambda_min", kVisMin))
        , lambdaMax_(p.getFloat("lambda_max", kVisMax)) {
        std::string mode = p.getString("output_mode", "");
        if (mode.empty())
            useLuminanceOutput_ = !isInsideVisible(lambdaMin_, lambdaMax_);
        else
            useLuminanceOutput_ = (mode == "luminance");
    }

    void beginFrame(Renderer& scene, const Camera&) override { renderer_ = &scene; }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;

        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen), lambdaMin_, lambdaMax_);

        // First-hit albedo AOV
        const auto* bvh = renderer_->getBVH().get();
        if (bvh) {
            HitRecord rec;
            if (bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) && rec.material) {
                r.albedo = rec.material->getAlbedo();
                r.depth = rec.t;
            }
        }

        int bounces = 0;
        float weight = 0.0f;
        astroray::SampledSpectrum rad =
            pathTrace(ray, maxDepth_, lambdas, gen, &bounces, &weight);

        if (useLuminanceOutput_) {
            // Band luminance → neutral grey so the colourmap pass can map it.
            // Mean of 4 spectral samples, averaged over pdf (same as toXYZ but without CMF).
            float L = 0.0f;
            for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                L += rad[i] / (lambdas.pdf(i) * astroray::kSpectrumSamples);
            L = std::max(0.0f, L);
            // Store as neutral XYZ so xyzToLinearSRGB produces neutral grey.
            // xyzToLinearSRGB(L, L, L) ≈ (1.20L, 0.95L, 0.91L); the colourmap
            // pass corrects this by reading the mean of the three channels.
            r.color = Vec3(L, L, L);
        } else {
            astroray::XYZ xyz = rad.toXYZ(lambdas);
            r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        }
        r.bounceCount = static_cast<float>(bounces);
        r.sampleWeight = weight;
        return r;
    }

private:
    // Simplified spectral path tracer that uses evalSpectralExt / sampleSpectralExt.
    // Identical to pathTraceSpectral for visible-range renders; uses profile data
    // and Rayleigh sky fallback for outside-visible wavelengths.
    astroray::SampledSpectrum pathTrace(
            const Ray& r, int maxDepth,
            astroray::SampledWavelengths& lambdas,
            std::mt19937& gen,
            int* outBounces, float* outWeight) {

        const int rrDepth = 3;
        astroray::SampledSpectrum color(0.0f);
        astroray::SampledSpectrum throughput(1.0f);
        Ray ray = r;
        bool wasSpecular = true;
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        int lastBounce = 0;
        float weightSum = 0.0f;

        const auto* bvh     = renderer_->getBVH().get();
        const auto& envMapPtr = renderer_->getEnvironmentMap();
        const auto* envMap  = envMapPtr.get();
        const Vec3  bgColor = renderer_->getBackgroundColor();

        for (int bounce = 0; bounce < maxDepth; ++bounce) {
            lastBounce = bounce;
            HitRecord rec;
            if (!bvh || !bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec)) {
                // Environment contribution
                astroray::SampledSpectrum envSpec(0.0f);
                if (useLuminanceOutput_) {
                    // Rayleigh sky: λ^-4 relative to 550 nm, scaled by a base brightness.
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                        float scale = rayleighScale(lambdas.lambda(i));
                        // Base sky = 0.1 (dim background); above horizon brightens it.
                        float horizonFade = 0.5f * (ray.direction.normalized().y + 1.0f);
                        envSpec[i] = 0.08f * scale * (0.5f + horizonFade);
                    }
                } else if (envMap && envMap->loaded()) {
                    envSpec = envMap->evalSpectral(ray.direction.normalized(), lambdas);
                } else if (bgColor.x >= 0) {
                    envSpec = astroray::RGBIlluminantSpectrum(
                        {bgColor.x, bgColor.y, bgColor.z}).sample(lambdas);
                } else {
                    float t = 0.5f * (ray.direction.normalized().y + 1.0f);
                    Vec3 bg = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
                    envSpec = astroray::RGBIlluminantSpectrum({bg.x, bg.y, bg.z}).sample(lambdas);
                }
                color += throughput * envSpec;
                break;
            }

            if (!rec.material) break;

            // Emission
            astroray::SampledSpectrum Le = rec.material->emittedSpectral(rec, lambdas);
            if (!Le.isZero()) {
                if (bounce == 0 || wasSpecular)
                    color += throughput * Le;
                break;
            }

            Vec3 wo = -ray.direction.normalized();

            // Russian roulette
            if (bounce > rrDepth) {
                float p;
                if (useLuminanceOutput_) {
                    p = std::min(0.95f, std::max(0.0f, throughput.average()));
                } else {
                    astroray::XYZ thrXYZ = throughput.toXYZ(lambdas);
                    p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
                }
                if (dist01(gen) > p) break;
                if (p > 0.0f) throughput = throughput * (1.0f / p);
            }

            // BSDF sample using profile-aware dispatch
            BSDFSampleSpectral bss = rec.material->sampleSpectralExt(rec, wo, gen, lambdas);
            if (bss.pdf <= 0.0f) break;
            wasSpecular = bss.isDelta;
            throughput *= bss.f_spectral * (1.0f / (bss.pdf + 0.001f));

            Ray next(rec.point, bss.wi, ray.time, ray.screenU, ray.screenV);
            next.hasCameraFrame = ray.hasCameraFrame;
            next.cameraOrigin = ray.cameraOrigin;
            next.cameraU = ray.cameraU;
            next.cameraV = ray.cameraV;
            next.cameraW = ray.cameraW;
            ray = next;

            weightSum += throughput.maxValue();
            float maxC = throughput.maxValue();
            if (maxC > 10.0f) throughput = throughput * (10.0f / maxC);
        }

        if (outBounces) *outBounces = lastBounce;
        if (outWeight)  *outWeight  = weightSum;
        return color;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("multiwavelength_path_tracer", MultiwavelengthPathTracer)
