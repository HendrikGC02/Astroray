#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/restir/reservoir.h"
#include "astroray/restir/light_sample.h"
#include "astroray/restir/frame_state.h"

// ReSTIR DI integrator — Bitterli et al. 2020, Algorithms 1–3.
//
// Initial sampling (pkg22, always active):
//   Per shading point, M light candidates are drawn and fed into a
//   Reservoir<ReSTIRCandidate> with RIS weight w_i = p_hat(x_i)/q(x_i).
//
// Temporal reuse (pkg24, opt-in via use_temporal=1):
//   The previous frame's reservoir at the same pixel is merged into the
//   current reservoir using the target function at the current shading point.
//   Reads from frameState_.previous (stable, no races). Biased (no shadow-ray
//   correction yet); bias magnitude is measured by the validation tests.
//
// Spatial reuse (pkg24, opt-in via use_spatial=1):
//   N random neighbours from the previous frame's reservoir buffer are merged
//   into the current reservoir. Reading from the previous buffer avoids races
//   with the current frame's writes, at the cost of one-frame lag. For static
//   scenes this is equivalent to same-frame spatial reuse.
//
// M-cap (Bitterli §5.2): M is capped at m_cap_ after initial sampling to
// prevent history build-up from over-weighting past candidates.
//
// Thread safety: sampleFull writes to frameState_.current.at(px,py). Each
// pixel is owned by exactly one OpenMP tile, so writes are serial per pixel.
// Reads always target frameState_.previous, which is immutable during the frame.

using namespace astroray::restir;

class ReSTIRDI : public Integrator {
    int   maxDepth_;
    int   numCandidates_;
    bool  useTemporal_;
    bool  useSpatial_;
    int   spatialRadius_;
    int   spatialNeighbors_;
    int   mCap_;
    int   frameW_ = 0;
    int   frameH_ = 0;
    Renderer* renderer_ = nullptr;
    FrameState frameState_;

    // Recover integer pixel coords from the ray's [0,1] screen coordinates.
    void pixelCoords(const Ray& ray, int& px, int& py) const {
        px = std::max(0, std::min(frameW_ - 1,
                static_cast<int>(std::round(ray.screenU * (frameW_ - 1)))));
        py = std::max(0, std::min(frameH_ - 1,
                static_cast<int>(std::round((1.0f - ray.screenV) * (frameH_ - 1)))));
    }

public:
    explicit ReSTIRDI(const astroray::ParamDict& p)
        : maxDepth_       (p.getInt ("max_depth",         50))
        , numCandidates_  (p.getInt ("num_candidates",     4))
        , useTemporal_    (p.getInt ("use_temporal",       0) != 0)
        , useSpatial_     (p.getInt ("use_spatial",        0) != 0)
        , spatialRadius_  (p.getInt ("spatial_radius",     5))
        , spatialNeighbors_(p.getInt("spatial_neighbors",  5))
        , mCap_           (p.getInt ("m_cap",              0))   // 0 = auto (20×M)
    {}

    void beginFrame(Renderer& r, const Camera& cam) override {
        renderer_ = &r;
        int w = cam.width;
        int h = cam.height;
        if (w > 0 && h > 0) {
            // Only resize when dimensions change; resize() clears all history.
            if (w != frameW_ || h != frameH_) {
                frameW_ = w;
                frameH_ = h;
                frameState_.resize(w, h);
            }
            frameState_.advanceFrame();
        }
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult result;
        if (!renderer_) return result;

        const auto* bvh = renderer_->getBVH().get();
        if (!bvh) return result;

        const LightList&                       lights   = renderer_->getLights();
        const std::shared_ptr<EnvironmentMap>& envMap   = renderer_->getEnvironmentMap();
        const Vec3&                            bgColor  = renderer_->getBackgroundColor();
        const int                              worldMaxB = renderer_->getWorldMaxBounces();

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

            // Direct lighting: RIS initial sampling + optional temporal/spatial reuse.
            if (!rec.isDelta && !lights.empty()) {
                Reservoir<ReSTIRCandidate> res;

                // --- Initial sampling (Algorithm 1) ---
                // Use RGB luminance (wavelength-independent) so W values are
                // consistent across frames with different wavelength samples.
                for (int i = 0; i < numCandidates_; ++i) {
                    LightSample ls = lights.sample(rec.point, gen);
                    if (ls.pdf <= 0.0f || !std::isfinite(ls.pdf)) continue;
                    ReSTIRCandidate cand = ReSTIRCandidate::fromLightSample(ls);
                    float pHat = cand.targetLuminanceRGB();
                    res.update(cand, pHat / ls.pdf, gen);
                }

                // M-cap: prevent history build-up (Bitterli §5.2).
                int effectiveMCap = (mCap_ > 0) ? mCap_ : (20 * numCandidates_);
                res.M = std::min(res.M, effectiveMCap);

                // --- Reuse (only at primary shading point) ---
                // Reuse reads from frameState_.previous (stable, no race conditions).
                // The history buffer is populated from the second render call onwards.
                if (bounce == 0 && frameW_ > 0 && frameState_.frameIndex >= 2) {
                    int px, py;
                    pixelCoords(ray, px, py);

                    // Finalize initial reservoir so W is valid for use as merge weight.
                    res.finalizeWeight(res.y.targetLuminanceRGB());

                    // Temporal reuse (Algorithm 2, Bitterli 2020).
                    if (useTemporal_) {
                        if (isTemporallyValid(frameState_.previous, px, py,
                                              rec.normal, rec.t)) {
                            const Reservoir<ReSTIRCandidate>& prev =
                                frameState_.previous.at(px, py);
                            float pHatPrev = prev.y.targetLuminanceRGB();
                            res.merge(prev, pHatPrev, gen);
                            res.M = std::min(res.M, effectiveMCap);
                        }
                    }

                    // Spatial reuse: sample neighbours from previous frame's buffer.
                    if (useSpatial_ && spatialNeighbors_ > 0) {
                        SpatialNeighbor nbuf[32];
                        int nActual = std::min(spatialNeighbors_, 32);
                        selectSpatialNeighbors(px, py, frameW_, frameH_,
                                               spatialRadius_, nActual, gen, nbuf);
                        for (int ni = 0; ni < nActual; ++ni) {
                            if (!nbuf[ni].valid) continue;
                            int nx = nbuf[ni].x, ny = nbuf[ni].y;
                            if (!isTemporallyValid(frameState_.previous, nx, ny,
                                                   rec.normal, rec.t))
                                continue;
                            const Reservoir<ReSTIRCandidate>& nbr =
                                frameState_.previous.at(nx, ny);
                            float pHatNbr = nbr.y.targetLuminanceRGB();
                            res.merge(nbr, pHatNbr, gen);
                            res.M = std::min(res.M, effectiveMCap);
                        }
                    }
                }

                // Final weight computation and geometry record.
                // Store AFTER final finalization so next frame's merge uses correct W.
                float pHatY = res.y.targetLuminanceRGB();
                res.finalizeWeight(pHatY);

                if (bounce == 0 && frameW_ > 0) {
                    int px, py;
                    pixelCoords(ray, px, py);
                    // Write geometry metadata (for next frame's validity gates).
                    auto& hist = frameState_.current.meta(px, py);
                    hist.normal = rec.normal;
                    hist.depth  = rec.t;
                    hist.valid  = true;
                    // Store fully-finalized reservoir for next frame's temporal reuse.
                    frameState_.current.at(px, py) = res;
                }

                if (res.W > 0.0f && res.y.isValid()) {
                    // Recompute direction and distance from THIS shading point, not from
                    // whichever pixel originally generated the candidate (neighbour/prev-frame).
                    Vec3 toLight    = res.y.position - rec.point;
                    float distLocal = toLight.length();
                    Vec3 wi         = distLocal > 1e-6f ? toLight / distLocal : toLight.normalized();
                    HitRecord shadow;
                    bool hitOcc = bvh->hit(
                        Ray(rec.point, wi), 0.001f, distLocal - 0.001f, shadow);
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
