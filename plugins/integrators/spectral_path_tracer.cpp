#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/manifold/sms_attempt.h"

// Pillar 2 spectral path tracer (pkg11, default since pkg14).
// SampleResult.color is the XYZ projection of the path's spectral radiance;
// Renderer converts XYZ to linear sRGB exactly once before gamma.
//
// pkg64 Phase 3 — when the renderer's `use_refractive_caustics` toggle is
// on AND at least one scene object is flagged as a caustic caster
// (Hittable::setCausticCaster), the per-bounce loop in
// Renderer::pathTraceSpectral receives an SMS connection hook (shared
// helper in include/astroray/manifold/sms_attempt.h). The hook performs
// a Specular Manifold Sampling attempt at every non-delta vertex through
// any flagged refractive sphere caster and returns the per-vertex
// spectral contribution; the path tracer adds it on top of the existing
// NEE direct-light estimate. The two strategies sample disjoint
// direction subsets (NEE: straight shadow ray; SMS: refractive chain),
// so the balance heuristic reduces to additive composition — see the
// comment at the call site in raytracer.h.
//
// Behaviour gates, by design (CLAUDE.md §2 / §3):
//   - Renderer::useRefractiveCaustics OFF (the default `false` path is
//     enabled by setting it via set_use_refractive_caustics): no hook is
//     installed, integrator is byte-for-byte identical to pre-pkg64-3.
//   - No caustic caster flagged: no hook is installed (skipping the
//     gather + std::function construction). Ditto.
//   - Otherwise: the hook fires only at non-delta vertices, and only
//     when there is at least one flagged refractive sphere caster.
namespace amf = astroray::manifold;

class SpectralPathTracer : public Integrator {
    int  maxDepth_;
    bool spectralNewton_;     // default ON for the prism use case
    amf::SMSConfig smsCfg_;

    Renderer* renderer_ = nullptr;
    std::vector<amf::SMSCaster> casters_;
    float smsAttempts_  = 0.0f;
    float smsConverged_ = 0.0f;
    float smsEnergy_    = 0.0f;
public:
    explicit SpectralPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          // Phase 3 default: spectral wavelength-Newton ON. The Phase-3
          // acceptance gate is the prism rainbow, which only appears
          // with hero-λ Newton (Hanika 2015 §4). Toggle is exposed via
          // set_integrator_param("spectral_newton", 0|1) for parity
          // with sms_caustic_path_tracer.
          spectralNewton_(p.getInt("spectral_newton", 1) != 0) {
        smsCfg_.seeds         = p.getInt("sms_seeds", 1);
        smsCfg_.maxIterations = p.getInt("sms_max_iterations", 20);
        smsCfg_.tolerance     = p.getFloat("sms_tolerance", 1e-4f);
        smsCfg_.contribClamp  = p.getFloat("sms_contrib_clamp", 4.0f);
    }

    void beginFrame(Renderer& scene, const Camera&) override {
        renderer_ = &scene;
        casters_.clear();
        smsAttempts_ = smsConverged_ = smsEnergy_ = 0.0f;
        if (scene.getUseRefractiveCaustics()) {
            // Per-object opt-in: only flagged objects participate.
            amf::gatherSphereCasters(scene, casters_, /*requireFlag=*/true);
        }
    }

    std::unordered_map<std::string, float> debugStats() const override {
        // Pre-pkg64-3 callers (test_integrator_plugin) expect an empty
        // stats map when nothing SMS-related happened. Emit stats only
        // when at least one caustic caster is flagged — otherwise the
        // integrator is byte-for-byte the pre-pkg64-3 path tracer and
        // should look like one in its diagnostics too.
        if (casters_.empty()) return {};
        return {
            {"sms_caster_count",    static_cast<float>(casters_.size())},
            {"sms_attempts",        smsAttempts_},
            {"sms_converged",       smsConverged_},
            {"sms_energy",          smsEnergy_},
            {"sms_spectral_newton", spectralNewton_ ? 1.0f : 0.0f},
        };
    }

    IntegratorCapabilities capabilities() const override {
        return {true, ""};
    }

    void setMaxDepth(int depth) override {
        maxDepth_ = depth;
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;
        // Populate first-hit albedo + normal AOVs (pkg75).
        // Normal is the world-space, front-facing shading normal at the
        // first non-transparent hit, matching Cycles' PASS_NORMAL semantics
        // (intern/cycles/integrator/pass.cpp; Apache-2.0). OIDN and OptiX
        // denoiser AOV mode both expect unit-length world-space normals as
        // guide images; misses keep Vec3(0) per OIDN's documented default.
        const auto* bvh = renderer_->getBVH().get();
        if (bvh) {
            HitRecord rec;
            if (bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) && rec.material) {
                r.albedo = rec.material->getAlbedo();
                r.depth = rec.t;
                r.normal = rec.normal;
            }
        }
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));
        int bounces = 0;
        float weight = 0.0f;

        // Build the SMS hook only when actually needed. When casters_ is
        // empty (no opt-in / no flag) we pass an empty std::function and
        // the path tracer's per-vertex check short-circuits — the
        // overhead is one branch per non-delta vertex.
        Renderer::SMSHook smsHook;
        if (!casters_.empty()) {
            smsHook = [this](const HitRecord& rec, const Vec3& /*wo*/,
                             const astroray::SampledSpectrum& /*throughput*/,
                             const astroray::SampledWavelengths& l,
                             std::mt19937& g) {
                return spectralNewton_
                    ? smsHookSpectral(rec, l, g)
                    : smsHookRGB(rec, l, g);
            };
        }

        astroray::SampledSpectrum rad =
            renderer_->pathTraceSpectral(ray, maxDepth_, lambdas, gen,
                                          &bounces, &weight, smsHook);
        astroray::XYZ xyz = rad.toXYZ(lambdas);
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        r.bounceCount = static_cast<float>(bounces);
        r.sampleWeight = weight;
        return r;
    }

private:
    // Hero-λ spectral SMS: the contribution is written to the hero
    // channel of the bundle only, secondary λ are zero (same convention
    // as the dispersive dielectric on refraction events). Across a
    // pixel, different rays draw different λ_hero, producing the
    // prism-accurate chromatic spread.
    astroray::SampledSpectrum smsHookSpectral(
            const HitRecord& x0Rec,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) {
        astroray::SampledSpectrum out(0.0f);
        const auto& lights = renderer_->getLights();
        if (lights.empty()) return out;

        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        const amf::SMSCaster& C = casters_[std::min<size_t>(
            casters_.size() - 1,
            static_cast<size_t>(u01(gen) * casters_.size()))];
        float casterPickPdf = 1.0f / static_cast<float>(casters_.size());

        float lambdaHero = lambdas.lambda(0);
        float iorHero    = C.mat ? C.mat->iorAt(lambdaHero) : C.iorFlat;
        if (iorHero <= 1.0f) return out;
        float eta = 1.0f / iorHero;

        LightSample ls = lights.sample(x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return out;

        // The SMS attempt depends only on the vertex (x0) and the picked
        // caster — no need for a real "primary" ray. We synthesize one
        // pointing back along the BSDF outgoing direction; it is only
        // used inside runSMSAttempt to compute wo_eye = -primary.dir,
        // so any direction whose negative is x0Rec.normal-side works.
        Ray syntheticPrimary(x0Rec.point - x0Rec.normal,
                              x0Rec.normal * (-1.0f));

        float heroAccum = 0.0f;
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            smsAttempts_ += 1.0f;
            astroray::SampledSpectrum fSpec;
            float w = 0.0f, Tr = 0.0f;
            Vec3 Le(0), wi(0);
            if (!amf::runSMSAttempt(*renderer_, x0Rec, syntheticPrimary, lambdas, gen,
                                    C, eta, casterPickPdf, ls, smsCfg_,
                                    fSpec, w, Le, Tr, wi))
                continue;
            float LeHero = astroray::RGBIlluminantSpectrum(
                {Le.x, Le.y, Le.z}).sample(lambdas)[0];
            float fHero  = fSpec[0];
            float sampleHero = fHero * LeHero * Tr * w;
            if (sampleHero > smsCfg_.contribClamp) sampleHero = smsCfg_.contribClamp;
            if (sampleHero < 0.0f) sampleHero = 0.0f;
            heroAccum += sampleHero;
            smsConverged_ += 1.0f;
            smsEnergy_ += sampleHero;
        }
        out[0] = heroAccum;
        return out;
    }

    // RGB fallback (parity with sms_caustic_path_tracer's Phase-1 path).
    astroray::SampledSpectrum smsHookRGB(
            const HitRecord& x0Rec,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) {
        astroray::SampledSpectrum out(0.0f);
        const auto& lights = renderer_->getLights();
        if (lights.empty()) return out;

        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        const amf::SMSCaster& C = casters_[std::min<size_t>(
            casters_.size() - 1,
            static_cast<size_t>(u01(gen) * casters_.size()))];
        float casterPickPdf = 1.0f / static_cast<float>(casters_.size());
        float eta = 1.0f / C.iorFlat;

        LightSample ls = lights.sample(x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return out;

        Ray syntheticPrimary(x0Rec.point - x0Rec.normal,
                              x0Rec.normal * (-1.0f));
        Vec3 contribRGB(0);
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            smsAttempts_ += 1.0f;
            astroray::SampledSpectrum fSpec;
            float w = 0.0f, Tr = 0.0f;
            Vec3 Le(0), wi(0);
            if (!amf::runSMSAttempt(*renderer_, x0Rec, syntheticPrimary, lambdas, gen,
                                    C, eta, casterPickPdf, ls, smsCfg_,
                                    fSpec, w, Le, Tr, wi))
                continue;
            astroray::XYZ fxyz = fSpec.toXYZ(lambdas);
            Vec3 fRGB(fxyz.X, fxyz.Y, fxyz.Z);
            Vec3 sample = fRGB * Le * (Tr * w);
            float maxC = std::max(sample.x, std::max(sample.y, sample.z));
            if (maxC > smsCfg_.contribClamp) sample = sample * (smsCfg_.contribClamp / maxC);
            contribRGB = contribRGB + sample;
            smsConverged_ += 1.0f;
            smsEnergy_ += maxC;
        }
        return astroray::RGBIlluminantSpectrum(
            {contribRGB.x, contribRGB.y, contribRGB.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_INTEGRATOR("path_tracer", SpectralPathTracer)
