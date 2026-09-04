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
    // pkg195: gate the dedicated-light NEE + two-sided-MIS legs (Stage A).
    // pkg225-S6: the GPU render path reads THIS SAME param (blender_module.cpp,
    // default 1) instead of deriving naive-ness from the integrator name, so CPU
    // and GPU agree by construction. It used to force the GPU leg naive
    // unconditionally, which rendered every non-emissive, non-specular surface
    // exactly black under GPU multiwavelength. Recall the pkg156 lesson: the naive
    // route is gated to match THIS integrator as the light-sampling-blind oracle,
    // so a NEE/w_B term firing here in naive mode silently breaks CPU<->GPU parity
    // (pkg120/pkg156, test_gpu_multiwavelength / test_pkg55_c3). Default ON so the
    // addon's NIR/UV lamp rendering works (Stage A); parity harnesses that use
    // this integrator as the naive oracle pin `enable_nee=0`.
    bool  enableNEE_;
    Renderer* renderer_ = nullptr;
    Camera*   camera_   = nullptr;

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
        // int route (not getBool): ParamDict::get_ is exact-type-match, and the
        // set_integrator_param(str,int) binding stores an int — so
        // set_integrator_param("enable_nee", 0) is only visible via getInt.
        enableNEE_ = p.getInt("enable_nee", 1) != 0;
    }

    void beginFrame(Renderer& scene, Camera& cam) override { renderer_ = &scene; camera_ = &cam; }

    IntegratorCapabilities capabilities() const override {
        // pkg54: CUDA megakernel in src/gpu/multiwavelength_kernel.cu mirrors
        // this integrator. Spectral profile dispatch is not yet on the GPU
        // (materials without profiles fall through to RGB-to-spectrum, same
        // as the CPU path), so visible-band parity is exact while
        // outside-visible bands rely on the analytic Rayleigh sky fallback.
        return {true, ""};
    }

    void setMaxDepth(int depth) override {
        maxDepth_ = depth;
    }

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
        astroray::SampledSpectrum rad =
            pathTrace(ray, maxDepth_, lambdas, gen, &bounces, &weight,
                      cryptoObjRanks, cryptoMatRanks, cryptoDepth);

        if (useLuminanceOutput_) {
            // Band luminance → neutral grey so the colourmap pass can map it.
            // Simple mean of the 4 spectral samples — wavelengths are already drawn
            // uniformly from [lambdaMin, lambdaMax] so no pdf compensation is needed
            // (we want average radiance over the band, not the integral).
            float L = 0.0f;
            for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                L += rad[i];
            L = std::max(0.0f, L / astroray::kSpectrumSamples);
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
            int* outBounces, float* outWeight,
            float* cryptoObjRanks = nullptr,
            float* cryptoMatRanks = nullptr,
            int cryptoDepth = 6) {

        const int rrDepth = 3;
        astroray::SampledSpectrum color(0.0f);
        astroray::SampledSpectrum throughput(1.0f);
        Ray ray = r;
        bool wasSpecular = true;
        // pkg195 Stage A: BSDF pdf that generated the current continuation ray,
        // used by the two-sided-MIS lamp legs below. Mirrors pathTraceSpectral's
        // bsdfPdfPrev (raytracer.h:2405).
        float bsdfPdfPrev = 0.0f;
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        int lastBounce = 0;
        float weightSum = 0.0f;

        const auto* bvh     = renderer_->getBVH().get();
        const auto& envMapPtr = renderer_->getEnvironmentMap();
        const auto* envMap  = envMapPtr.get();
        const Vec3  bgColor = renderer_->getBackgroundColor();
        // pkg195 Stage A: dedicated-light NEE. The MW integrator had no light
        // sampling of any kind (pre-pkg89), so every Blender lamp (a dedicated
        // astroray::Light) was invisible and lamp-lit scenes rendered black
        // outside the visible band. The blocks below port the in-header path
        // tracer's dedicated-light next-event estimation and two-sided MIS
        // (pathTraceSpectral, raytracer.h:2415-2568) verbatim in structure,
        // swapping evalSpectral/sampleSpectral for the profile-aware
        // evalSpectralExt/sampleSpectralExt so blackbody / measured-SPD lamps
        // emit correctly outside 380-780 nm. No new estimator (CLAUDE.md §6).
        const LightList& lights = renderer_->getLights();

        for (int bounce = 0; bounce < maxDepth; ++bounce) {
            lastBounce = bounce;
            HitRecord rec;
            bool didHit = bvh && bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);

            // pkg195 Stage A: dedicated-lamp visibility to BSDF rays (mirrors
            // pathTraceSpectral raytracer.h:2423-2440). Lamps are invisible to
            // camera rays (bounce == 0); a lamp closer than the surface
            // terminates the path and feeds the same two-sided MIS term the
            // emissive path below uses (wB = 1 after a specular bounce).
            // Gated on enableNEE_: this is a light-sampling/MIS term and must NOT
            // fire in naive mode (the GPU-parity oracle contract, pkg156).
            if (enableNEE_ && bounce > 0 && !lights.getDedicatedLights().empty()) {
                float surfaceT = didHit ? rec.t : std::numeric_limits<float>::max();
                astroray::Light::Intersection lh;
                if (lights.intersectDedicated(ray.origin, ray.direction, 0.001f,
                                              surfaceT, lambdas, lh)) {
                    if (!lh.emission.isZero()) {
                        if (wasSpecular) {
                            color += throughput * lh.emission;
                        } else {
                            float lp = lights.pdfValue(ray.origin, ray.direction);
                            float bp = bsdfPdfPrev;
                            float wB = (bp * bp) / (bp * bp + lp * lp + 1e-8f);
                            color += throughput * lh.emission * wB;
                        }
                    }
                    break;  // path terminates on the lamp
                }
            }

            if (!didHit) {
                // Environment contribution
                astroray::SampledSpectrum envSpec(0.0f);
                Vec3 dir = ray.direction.normalized();
                if (bgColor.x >= 0) {
                    // Explicit background color always takes precedence (including black).
                    envSpec = astroray::RGBIlluminantSpectrum(
                        {bgColor.x, bgColor.y, bgColor.z}).sample(lambdas);
                } else if (envMap && envMap->loaded()) {
                    envSpec = envMap->evalSpectral(dir, lambdas);
                } else if (useLuminanceOutput_) {
                    // Rayleigh sky fallback for outside-visible when no bg/envmap set.
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                        float scale = rayleighScale(lambdas.lambda(i));
                        float horizonFade = 0.5f * (dir.y + 1.0f);
                        envSpec[i] = 0.08f * scale * (0.5f + horizonFade);
                    }
                } else {
                    float t = 0.5f * (dir.y + 1.0f);
                    Vec3 bg = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
                    envSpec = astroray::RGBIlluminantSpectrum({bg.x, bg.y, bg.z}).sample(lambdas);
                }
                color += throughput * envSpec;
                break;
            }

            if (!rec.material) break;

            // Emission. In NEE mode this is the two-sided MIS w_B leg (mirrors
            // pathTraceSpectral raytracer.h:2496-2527); in naive mode it is the
            // BYTE-OLD behavior — emission is taken only on a camera / post-
            // specular ray and DROPPED on a non-specular diffuse hit (no w_B
            // term). pkg156's exact bug was a w_B term left firing unconditionally
            // in naive mode, so this else-branch is gated on enableNEE_.
            astroray::SampledSpectrum Le = rec.material->emittedSpectral(rec, lambdas);
            if (!Le.isZero()) {
                if (bounce == 0 || wasSpecular) {
                    color += throughput * Le;
                } else if (enableNEE_) {
                    // BSDF-sampled continuation ray hit an emitter at a diffuse
                    // bounce: add the BSDF leg weighted by the power heuristic
                    // against the light-sampling pdf that would have generated it.
                    float lp = lights.empty()
                        ? 0.0f
                        : lights.pdfValue(ray.origin, ray.direction);
                    float bp = bsdfPdfPrev;
                    float wB = (bp * bp) / (bp * bp + lp * lp + 1e-8f);
                    color += throughput * Le * wB;
                }
                break;
            }

            Vec3 wo = -ray.direction.normalized();

            // pkg195 Stage A: dedicated-light NEE with MIS (mirrors
            // pathTraceSpectral raytracer.h:2537-2568). Skipped on delta lobes.
            // Uses evalSpectralExt (profile-aware) for the BSDF factor and
            // ls.emission_spec (EmissionSpectrum::eval at these lambdas) for the
            // light, so blackbody / measured-SPD lamps emit outside 380-780 nm.
            // Gated on enableNEE_ (naive mode has no light sampling — the GPU
            // parity oracle contract, pkg156).
            if (enableNEE_ && !rec.isDelta && !lights.empty()) {
                LightSample ls;
                lights.sample(ls, rec.point, rec.normal, lambdas, gen);
                if (ls.pdf > 0) {
                    Vec3 wi = (ls.position - rec.point).normalized();
                    HitRecord shadow;
                    bool hitOccluder = bvh->hit(Ray(rec.point, wi, ray.time), 0.001f,
                                                ls.distance - 0.001f, shadow);
                    bool occluded = hitOccluder &&
                        !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
                    if (!occluded) {
                        astroray::SampledSpectrum f_spec =
                            rec.material->evalSpectralExt(rec, wo, wi, lambdas);
                        astroray::SampledSpectrum L_spec = ls.emission_spec;
                        float bsdfPdf = rec.material->pdf(rec, wo, wi);
                        float a = ls.pdf, b = bsdfPdf;
                        // pkg140: a delta light sample always gets full MIS weight
                        // (BSDF sampling can never reproduce it).
                        float wt = ls.isDelta ? 1.0f : (a * a) / (a * a + b * b + 1e-8f);
                        color += throughput * f_spec * L_spec *
                                 (ls.pdf > 1e-8f ? wt / ls.pdf : 0.0f);
                    }
                }
            }

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
            // pkg195 Stage A: carry this bounce's BSDF pdf for the next iteration's
            // two-sided-MIS lamp/emissive legs (mirrors pathTraceSpectral:2599).
            bsdfPdfPrev = bss.pdf;

            // pkg87b: Cryptomatte accumulation at shade point (before throughput update).
            // Weight = average(throughput · bsdf_eval), per Cycles.
            if (renderer_->getCryptomatteEnabled() && cryptoObjRanks && cryptoMatRanks) {
                astroray::SampledSpectrum contrib = throughput * bss.f_spectral;
                astroray::XYZ contribXYZ = contrib.toXYZ(lambdas);
                float r =  3.2406f * contribXYZ.X - 1.5372f * contribXYZ.Y - 0.4986f * contribXYZ.Z;
                float g = -0.9689f * contribXYZ.X + 1.8758f * contribXYZ.Y + 0.0415f * contribXYZ.Z;
                float b =  0.0557f * contribXYZ.X - 0.2040f * contribXYZ.Y + 1.0570f * contribXYZ.Z;
                float weight = (r + g + b) / 3.0f;

                float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
                if (rec.hitObject && !rec.hitObject->getName().empty()) {
                    objectId = crypto_hash_name(rec.hitObject->getName());
                }
                if (rec.material && !rec.material->getName().empty()) {
                    materialId = crypto_hash_name(rec.material->getName());
                }
                crypto_accumulate_shade_point(cryptoObjRanks, cryptoMatRanks,
                                               0, cryptoDepth, objectId, materialId, weight);
            }

            throughput *= bss.f_spectral * (bss.pdf > 1e-8f ? 1.0f / bss.pdf : 0.0f);

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
