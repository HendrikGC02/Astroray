// pkg64 Phases 1+2 — opt-in Specular Manifold Sampling integrator.
//
// Augments caustic_path_tracer with an SMS connection attempt at each
// non-delta primary hit. The shared SMS attempt code (Newton iteration
// on the half-vector constraint, Schlick Fresnel, refraction, visibility)
// lives in include/astroray/manifold/sms_attempt.h; Phase 3 re-uses the
// same helper from inside the default `path_tracer`.
//
// References (CLAUDE.md §6):
//   Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for Rendering
//     High-Frequency Caustics and Glints", SIGGRAPH 2020,
//     DOI 10.1145/3386569.3392408.
//   Hanika, Droske, Manakov, "Manifold Next Event Estimation",
//     EGSR 2015, DOI 10.1111/cgf.12681.  §4 derives the per-wavelength
//     half-vector residual h(λ) = ω_i + η(λ)·ω_o, which is the math
//     source for the Phase 2 spectral wavelength-Newton path.
//   Mitsuba 2 SMS reference (BSD-3-Clause):
//     https://github.com/tizian/specular-manifold-sampling
//     commit 1f0e40342a8760450d5aa6202ea096feaa70256a (2021-06-27).
//     The Mitsuba 2 reference is RGB-only; the spectral extension below
//     is re-derived from Hanika 2015 §4 (NOT consulted from Cycles' MNEE
//     source — Cycles is GPL-2.0+, license-fenced per
//     .astroray_plan/docs/caustics-research.md).
//
// Phase 1 scope (default, `spectral_newton=false`): RGB only, scalar IOR.
//   Spherical refractive casters; one Newton solve per ray, one specular
//   vertex; contribution upsampled via RGBUnboundedSpectrum (pkg142 Defect 4).
//
// Phase 2 scope (`spectral_newton=true`): the Newton residual, refraction
//   direction, and Schlick Fresnel are evaluated at the hero wavelength
//   of the current SampledWavelengths bundle, and the resulting
//   contribution is written to the hero spectral channel only (secondary
//   wavelengths are zero — same convention used by the dispersive
//   dielectric in plugins/materials/dielectric.cpp). Different rays
//   sample different hero λ, so per-pixel accumulation produces the
//   chromatic spread of a prism-accurate caustic.
//
// Phase 3 (the default path_tracer) folds the same SMS attempt into
// `path_tracer` via MIS — see plugins/integrators/spectral_path_tracer.cpp.

#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/shapes.h"
#include "astroray/manifold/sms_attempt.h"
#include "astroray/manifold/mesh_attempt.h"   // pkg106 Chunk D: triangulated-prism MNEE

#include <algorithm>
#include <limits>
#include <vector>

namespace amf = astroray::manifold;

class SMSCausticPathTracer : public Integrator {
    int   maxDepth_;
    int   chainIters_;
    bool  spectralNewton_;    // pkg64 Phase 2: hero-λ Newton (Hanika 2015 §4)
    amf::SMSConfig smsCfg_;

    Renderer* renderer_ = nullptr;
    float causticConnections_ = 0.0f;
    float causticEnergy_ = 0.0f;
    float smsAttempts_  = 0.0f;
    float smsConverged_ = 0.0f;
    float smsEnergy_    = 0.0f;
    std::vector<amf::SMSCaster> casters_;
    // pkg106 Chunk D: triangle-mesh caustic casters (a triangulated prism) for
    // the multi-vertex MNEE path. Sphere casters above stay on the single-vertex
    // path; mesh casters use the chromatic 2-vertex chain.
    std::vector<amf::CausticTri> meshCasters_;
    const Material* meshCasterMat_ = nullptr;

public:
    explicit SMSCausticPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          chainIters_(p.getInt("caustic_chain_iters", 3)),
          // set_integrator_param Python binding routes through int values
          // (module/blender_module.cpp), so the toggle reads as int.
          spectralNewton_(p.getInt("spectral_newton", 0) != 0) {
        smsCfg_.seeds         = p.getInt("sms_seeds", 1);
        smsCfg_.maxIterations = p.getInt("sms_max_iterations", 20);
        smsCfg_.tolerance     = p.getFloat("sms_tolerance", 1e-4f);
        smsCfg_.contribClamp  = p.getFloat("sms_contrib_clamp", 4.0f);
    }

    Camera* camera_ = nullptr;  // pkg87b

    void beginFrame(Renderer& scene, Camera& cam) override {
        renderer_ = &scene;
        camera_ = &cam;  // pkg87b
        causticConnections_ = causticEnergy_ = 0.0f;
        smsAttempts_ = smsConverged_ = smsEnergy_ = 0.0f;
        // sms_caustic_path_tracer keeps the Phase-1+2 behavior of treating
        // every transmissive sphere as a candidate (requireFlag=false), so
        // its acceptance test scenes don't need to flip the new opt-in.
        amf::gatherSphereCasters(scene, casters_, /*requireFlag=*/false);
        // pkg106 Chunk D: gather triangle-mesh caustic-casters (opt-in flag).
        meshCasterMat_ = amf::gatherTriangleCasters(scene, meshCasters_);
    }

    std::unordered_map<std::string, float> debugStats() const override {
        return {
            {"caustic_connections", causticConnections_},
            {"caustic_energy",      causticEnergy_},
            {"caustic_chain_iters", static_cast<float>(chainIters_)},
            {"sms_attempts",        smsAttempts_},
            {"sms_converged",       smsConverged_},
            {"sms_energy",          smsEnergy_},
            {"sms_caster_count",    static_cast<float>(casters_.size())},
            {"sms_spectral_newton", spectralNewton_ ? 1.0f : 0.0f},
        };
    }

    IntegratorCapabilities capabilities() const override {
        return {false, "SMS caustic integrator is CPU-only in Phase 1/2"};
    }

    void setMaxDepth(int depth) override {
        maxDepth_ = depth;
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;

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

        // 1. Baseline caustic path-tracer contribution (unchanged).
        int   bounces = 0;
        float weight  = 0.0f;
        int   connections = 0;
        float energy = 0.0f;
        astroray::SampledSpectrum rad = renderer_->pathTraceSpectralCaustic(
            ray, maxDepth_, chainIters_, lambdas, gen, &bounces, &weight,
            &connections, &energy, cryptoObjRanks, cryptoMatRanks, cryptoDepth);

        // 2. Primary hit + SMS attempt on top.
        HitRecord rec;
        bool primaryHit = false;
        if (const auto* bvh = renderer_->getBVH().get()) {
            primaryHit = bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);
        }
        if (primaryHit && rec.material) {
            r.albedo = rec.material->getAlbedo();
            r.depth  = rec.t;
            if (!rec.material->isEmissive() && !rec.isDelta) {
                if (spectralNewton_) {
                    astroray::SampledSpectrum sms(0.0f);
                    if (!casters_.empty())
                        sms = sms + sampleSMSSpectral(rec, ray, lambdas, gen);
                    // pkg106: EXPERIMENTAL chromatic multi-vertex MNEE on
                    // triangulated casters. Validated math (analytic transfer-
                    // matrix geometry term, caster-aimed seed), but camera-side
                    // MNEE on a FLAT/weakly-dispersing prism is salt-and-pepper
                    // grainy (deterministic basin chaos). The prism RAINBOW ships
                    // via the forward light_tracer_caustic integrator instead;
                    // this path is kept for focusing mesh casters. See
                    // pkg106-forward-lighttracing-research.md.
                    if (!meshCasters_.empty())
                        sms = sms + sampleMeshSMSSpectral(rec, ray, lambdas, gen);
                    rad = rad + sms;
                } else if (!casters_.empty()) {
                    Vec3 sms = sampleSMSRGB(rec, ray, lambdas, gen);
                    // pkg142 (Defect 4): UNBOUNDED (no-D65) emission lift.
                    rad = rad + astroray::RGBUnboundedSpectrum(
                        {sms.x, sms.y, sms.z}).sample(lambdas);
                }
            }
        }

        astroray::XYZ xyz = rad.toXYZ(lambdas);
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        r.bounceCount = static_cast<float>(bounces);
        r.sampleWeight = weight;
        causticConnections_ += static_cast<float>(connections);
        causticEnergy_ += energy;
        return r;
    }

private:
    // Phase 1 path: RGB throughput, scalar IOR. Untouched semantics so the
    // existing test_sms_caustic_validation regression baseline holds.
    Vec3 sampleSMSRGB(const HitRecord& x0Rec, const Ray& primary,
                      const astroray::SampledWavelengths& lambdas,
                      std::mt19937& gen) {
        const auto& lights = renderer_->getLights();
        if (lights.empty()) return Vec3(0);

        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        const amf::SMSCaster& C = casters_[std::min<size_t>(
            casters_.size() - 1,
            static_cast<size_t>(u01(gen) * casters_.size()))];
        float casterPickPdf = 1.0f / static_cast<float>(casters_.size());
        float eta = 1.0f / C.iorFlat;

        LightSample ls;
        lights.sample(ls, x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return Vec3(0);

        Vec3 contrib(0);
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            smsAttempts_ += 1.0f;

            astroray::SampledSpectrum fSpec;
            float w = 0.0f, Tr = 0.0f;
            Vec3 Le(0), wi(0);
            if (!amf::runSMSAttempt(*renderer_, x0Rec, primary, lambdas, gen,
                                    C, eta, casterPickPdf, ls, smsCfg_,
                                    fSpec, w, Le, Tr, wi))
                continue;

            astroray::XYZ fxyz = fSpec.toXYZ(lambdas);
            Vec3 fRGB(fxyz.X, fxyz.Y, fxyz.Z);

            Vec3 sample = fRGB * Le * (Tr * w);
            float maxC = std::max(sample.x, std::max(sample.y, sample.z));
            if (maxC > smsCfg_.contribClamp) sample = sample * (smsCfg_.contribClamp / maxC);

            contrib = contrib + sample;
            smsConverged_ += 1.0f;
            smsEnergy_ += maxC;
        }
        return contrib;
    }

    // Phase 2 path: hero-λ Newton (Hanika 2015 §4). Hero-only spectral write.
    astroray::SampledSpectrum sampleSMSSpectral(
            const HitRecord& x0Rec, const Ray& primary,
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

        // Hanika 2015 §4 — η(λ_hero); the Newton residual is the only place
        // wavelength enters the geometric solve.
        float lambdaHero = lambdas.lambda(0);
        float iorHero    = C.mat ? C.mat->iorAt(lambdaHero) : C.iorFlat;
        if (iorHero <= 1.0f) return out;
        float eta = 1.0f / iorHero;

        LightSample ls;
        lights.sample(ls, x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return out;

        float heroAccum = 0.0f;
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            smsAttempts_ += 1.0f;

            astroray::SampledSpectrum fSpec;
            float w = 0.0f, Tr = 0.0f;
            Vec3 Le(0), wi(0);
            if (!amf::runSMSAttempt(*renderer_, x0Rec, primary, lambdas, gen,
                                    C, eta, casterPickPdf, ls, smsCfg_,
                                    fSpec, w, Le, Tr, wi))
                continue;

            // Project RGB emission to the hero wavelength via Jakob-Hanika
            // upsampling — the per-λ Le evaluation needed for the prism
            // rainbow. pkg142 (Defect 4): UNBOUNDED (no-D65) emission lift.
            float LeHero = astroray::RGBUnboundedSpectrum(
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

    // pkg106 Chunk D — chromatic multi-vertex MNEE on triangulated (prism)
    // casters. Like sampleSMSSpectral but the geometric solve is the 2-vertex
    // (entry+exit face) block-tridiagonal chain at the hero-wavelength IOR; the
    // contribution is written to the hero channel only, so per-ray hero rotation
    // spreads the caustic into a rainbow (mesh_attempt.h / manifold_chain.h).
    astroray::SampledSpectrum sampleMeshSMSSpectral(
            const HitRecord& x0Rec, const Ray& primary,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) {
        astroray::SampledSpectrum out(0.0f);
        const auto& lights = renderer_->getLights();
        if (lights.empty() || meshCasters_.empty()) return out;

        LightSample ls;
        lights.sample(ls, x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return out;

        float heroAccum = 0.0f;
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            smsAttempts_ += 1.0f;
            float c = amf::runMeshSMSAttempt(*renderer_, x0Rec, primary, lambdas,
                                             meshCasters_, meshCasterMat_,
                                             /*casterPickPdf=*/1.0f, ls, smsCfg_);
            if (c > 0.0f) { heroAccum += c; smsConverged_ += 1.0f; smsEnergy_ += c; }
        }
        out[0] = heroAccum;
        return out;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("sms_caustic_path_tracer", SMSCausticPathTracer)
