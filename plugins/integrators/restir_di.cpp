#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/restir/reservoir.h"
#include "astroray/restir/light_sample.h"
#include "astroray/restir/frame_state.h"

// pkg22 — ReSTIR DI prototype: initial candidate generation only.
//
// Implements Algorithm 1 of Bitterli et al. 2020 (initial sampling) per pixel.
// For each shading point, numCandidates_ light samples are drawn from the scene
// light list and fed into a Reservoir<ReSTIRCandidate> with RIS weight
//   w_i = p_hat(x_i) / q(x_i)
// where p_hat = spectral luminance (Y channel) and q = the light sampling PDF.
// The selected candidate is then tested for visibility; its contribution is
//   throughput * f_spectral * L_emission * W
// where W = w_sum / (p_hat(y) * M) is the final RIS weight.
//
// pkg23: frameState_ is declared here and resized in beginFrame. It is not yet
// written to or read from during sampleFull; the temporal and spatial passes
// are added in pkg24 once the validation plan in
// .astroray_plan/docs/restir-temporal-spatial-design.md is implemented.
//
// No temporal reuse, spatial reuse, or CUDA kernels active yet.
// The classic path_tracer integrator is unchanged.

class ReSTIRDI : public Integrator {
    int   maxDepth_;
    int   numCandidates_;
    Renderer* renderer_ = nullptr;
    astroray::restir::FrameState frameState_;  // pkg23: history buffers, inactive until pkg24

public:
    explicit ReSTIRDI(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50))
        , numCandidates_(p.getInt("num_candidates", 4)) {}

    void beginFrame(Renderer& r, const Camera& cam) override {
        renderer_ = &r;
        // pkg23: resize and advance the frame-state buffers each frame so that
        // pkg24 temporal/spatial passes can read frameState_.previous without
        // a resize-on-demand step. Current render output is unchanged because
        // frameState_ is not read during sampleFull yet.
        int w = cam.width;
        int h = cam.height;
        if (w > 0 && h > 0) {
            frameState_.resize(w, h);
            frameState_.advanceFrame();
        }
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult result;
        if (!renderer_) return result;

        const auto* bvh = renderer_->getBVH().get();
        if (!bvh) return result;

        const LightList&                         lights        = renderer_->getLights();
        const std::shared_ptr<EnvironmentMap>&   envMap        = renderer_->getEnvironmentMap();
        const Vec3&                              bgColor       = renderer_->getBackgroundColor();
        const int                                worldMaxB     = renderer_->getWorldMaxBounces();

        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));

        astroray::SampledSpectrum color(0.0f);
        astroray::SampledSpectrum throughput(1.0f);
        Ray   pathRay    = ray;
        bool  wasSpecular = true;
        const int rrDepth = 3;

        for (int bounce = 0; bounce < maxDepth_; ++bounce) {
            HitRecord rec;
            if (!bvh->hit(pathRay, 0.001f, std::numeric_limits<float>::max(), rec)) {
                if (bounce <= worldMaxB) {
                    astroray::SampledSpectrum envSpec(0.0f);
                    if (envMap && envMap->loaded()) {
                        envSpec = envMap->evalSpectral(pathRay.direction.normalized(), lambdas);
                    } else if (bgColor.x >= 0) {
                        envSpec = astroray::RGBIlluminantSpectrum(
                            {bgColor.x, bgColor.y, bgColor.z}).sample(lambdas);
                    } else {
                        float t = 0.5f * (pathRay.direction.normalized().y + 1.0f);
                        Vec3 bg = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
                        envSpec = astroray::RGBIlluminantSpectrum(
                            {bg.x, bg.y, bg.z}).sample(lambdas);
                    }
                    color += throughput * envSpec;
                }
                break;
            }

            // GR object: delegate entirely to the object's own spectral trace.
            if (rec.hitObject && rec.hitObject->isGRObject()) {
                auto grResult = rec.hitObject->traceGRSpectral(pathRay, lambdas, gen);
                if (grResult.hasEmission) {
                    astroray::SampledSpectrum grEm(0.0f);
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                        float v = grResult.emission[i];
                        grEm[i] = (std::isfinite(v) && v >= 0.0f) ? std::min(v, 20.0f) : 0.0f;
                    }
                    if (!grEm.isZero()) color += throughput * grEm;
                }
                if (grResult.captured) break;

                Vec3 exitDir  = grResult.exitDirection;
                float len2    = exitDir.length2();
                if (!std::isfinite(exitDir.x) || !std::isfinite(exitDir.y) ||
                    !std::isfinite(exitDir.z) || !std::isfinite(len2) || len2 < 1e-10f)
                    break;

                Ray next(rec.point, exitDir, pathRay.time, pathRay.screenU, pathRay.screenV);
                next.hasCameraFrame = pathRay.hasCameraFrame;
                next.cameraOrigin   = pathRay.cameraOrigin;
                next.cameraU        = pathRay.cameraU;
                next.cameraV        = pathRay.cameraV;
                next.cameraW        = pathRay.cameraW;
                pathRay             = next;
                wasSpecular         = true;
                continue;
            }

            if (!rec.material) break;

            // Emission (camera ray or post-specular bounce only).
            astroray::SampledSpectrum Le = rec.material->emittedSpectral(rec, lambdas);
            if (!Le.isZero()) {
                if (bounce == 0 || wasSpecular) color += throughput * Le;
                break;
            }

            Vec3 wo = -pathRay.direction.normalized();

            // RIS direct lighting (initial sampling).
            if (!rec.isDelta && !lights.empty()) {
                using astroray::restir::Reservoir;
                using astroray::restir::ReSTIRCandidate;

                Reservoir<ReSTIRCandidate> res;
                for (int i = 0; i < numCandidates_; ++i) {
                    LightSample ls = lights.sample(rec.point, gen);
                    if (ls.pdf <= 0.0f || !std::isfinite(ls.pdf)) continue;
                    ReSTIRCandidate cand = ReSTIRCandidate::fromLightSample(ls);
                    float pHat = cand.targetLuminance(lambdas);
                    res.update(cand, pHat / ls.pdf, gen);
                }

                if (res.w_sum > 0.0f) {
                    float pHatY = res.y.targetLuminance(lambdas);
                    res.finalizeWeight(pHatY);

                    if (res.W > 0.0f && res.y.isValid()) {
                        Vec3 wi = (res.y.position - rec.point).normalized();
                        HitRecord shadow;
                        bool hitOcc = bvh->hit(
                            Ray(rec.point, wi), 0.001f, res.y.distance - 0.001f, shadow);
                        bool occluded = hitOcc &&
                            !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
                        if (!occluded) {
                            astroray::SampledSpectrum f_spec =
                                rec.material->evalSpectral(rec, wo, wi, lambdas);
                            astroray::SampledSpectrum L_spec =
                                astroray::RGBIlluminantSpectrum(
                                    {res.y.emission.x, res.y.emission.y, res.y.emission.z}
                                ).sample(lambdas);
                            color += throughput * f_spec * L_spec * res.W;
                        }
                    }
                }
            }

            // Russian roulette.
            if (bounce > rrDepth) {
                astroray::XYZ thrXYZ = throughput.toXYZ(lambdas);
                float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
                if (dist01(gen) > p) break;
                if (p > 0.0f) throughput = throughput * (1.0f / p);
            }

            // BSDF sample.
            BSDFSample bs = rec.material->sample(rec, wo, gen);
            if (bs.pdf <= 0.0f) break;
            astroray::SampledSpectrum f_bs =
                rec.material->evalSpectral(rec, wo, bs.wi, lambdas);
            wasSpecular = bs.isDelta;
            if (bs.isDelta && f_bs.isZero()) {
                f_bs = astroray::RGBAlbedoSpectrum(
                    {bs.f.x, bs.f.y, bs.f.z}).sample(lambdas);
            }
            throughput *= f_bs * (1.0f / (bs.pdf + 0.001f));

            Ray next(rec.point, bs.wi, pathRay.time, pathRay.screenU, pathRay.screenV);
            next.hasCameraFrame = pathRay.hasCameraFrame;
            next.cameraOrigin   = pathRay.cameraOrigin;
            next.cameraU        = pathRay.cameraU;
            next.cameraV        = pathRay.cameraV;
            next.cameraW        = pathRay.cameraW;
            pathRay             = next;

            float maxC = throughput.maxValue();
            if (maxC > 10.0f) throughput = throughput * (10.0f / maxC);
        }

        astroray::XYZ xyz = color.toXYZ(lambdas);
        result.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        return result;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("restir-di", ReSTIRDI)
