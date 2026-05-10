// pkg64 Phases 1+2 — opt-in Specular Manifold Sampling integrator.
//
// Augments caustic_path_tracer with an SMS connection attempt at each
// non-delta primary hit. The Newton iteration in include/astroray/manifold/
// finds a stationary point on a refractive sphere caster between the
// shading point and a sampled emitter; the resulting contribution is
// added on top of the baseline caustic walk.
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
//   vertex; contribution upsampled via RGBIlluminantSpectrum.
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
// Phase 3 (NOT in this package) folds SMS into the default path tracer.

#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/shapes.h"
#include "astroray/manifold/half_vector_constraint.h"
#include "astroray/manifold/newton_iterate.h"

#include <algorithm>
#include <limits>
#include <vector>

namespace amf = astroray::manifold;

class SMSCausticPathTracer : public Integrator {
    int   maxDepth_;
    int   chainIters_;
    int   smsSeeds_;          // seed attempts per primary hit
    int   smsMaxIters_;       // Newton iteration budget per seed
    float smsTolerance_;      // |c| convergence threshold
    float smsContribClamp_;   // safety clamp on per-attempt SMS energy
    bool  spectralNewton_;    // pkg64 Phase 2: hero-λ Newton (Hanika 2015 §4)

    Renderer* renderer_ = nullptr;
    float causticConnections_ = 0.0f;
    float causticEnergy_ = 0.0f;
    float smsAttempts_  = 0.0f;
    float smsConverged_ = 0.0f;
    float smsEnergy_    = 0.0f;

    struct Caster {
        const Sphere*   sphere;
        float           radius;
        Vec3            center;
        const Material* mat;     // for iorAt(λ) at hero wavelength (Phase 2)
        float           iorFlat; // cached scalar IOR (Phase 1 fast path)
    };
    std::vector<Caster> casters_;

public:
    explicit SMSCausticPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          chainIters_(p.getInt("caustic_chain_iters", 3)),
          smsSeeds_(p.getInt("sms_seeds", 1)),
          smsMaxIters_(p.getInt("sms_max_iterations", 20)),
          smsTolerance_(p.getFloat("sms_tolerance", 1e-4f)),
          smsContribClamp_(p.getFloat("sms_contrib_clamp", 4.0f)),
          // set_integrator_param Python binding routes through int values
          // (module/blender_module.cpp), so the toggle reads as int.
          spectralNewton_(p.getInt("spectral_newton", 0) != 0) {}

    void beginFrame(Renderer& scene, const Camera&) override {
        renderer_ = &scene;
        causticConnections_ = causticEnergy_ = 0.0f;
        smsAttempts_ = smsConverged_ = smsEnergy_ = 0.0f;
        casters_.clear();
        for (const auto& obj : scene.getScene()) {
            const auto* sph = dynamic_cast<const Sphere*>(obj.get());
            if (!sph) continue;
            const auto& mat = sph->getMaterial();
            if (!mat || !mat->isTransmissive()) continue;
            float ior = mat->getIOR();
            if (ior <= 1.0f) continue;
            casters_.push_back(Caster{sph, sph->getRadius(), sph->getCenter(),
                                       mat.get(), ior});
        }
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

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;

        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(dist01(gen));

        // 1. Baseline caustic path-tracer contribution (unchanged).
        int   bounces = 0;
        float weight  = 0.0f;
        int   connections = 0;
        float energy = 0.0f;
        astroray::SampledSpectrum rad = renderer_->pathTraceSpectralCaustic(
            ray, maxDepth_, chainIters_, lambdas, gen, &bounces, &weight,
            &connections, &energy);

        // 2. Primary hit + SMS attempt on top.
        HitRecord rec;
        bool primaryHit = false;
        if (const auto* bvh = renderer_->getBVH().get()) {
            primaryHit = bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);
        }
        if (primaryHit && rec.material) {
            r.albedo = rec.material->getAlbedo();
            r.depth  = rec.t;
            if (!rec.material->isEmissive() && !rec.isDelta && !casters_.empty()) {
                if (spectralNewton_) {
                    // Phase 2: hero-λ Newton. Contribution is hero-only.
                    astroray::SampledSpectrum sms =
                        sampleSMSSpectral(rec, ray, lambdas, gen);
                    rad = rad + sms;
                } else {
                    // Phase 1: RGB Newton, RGB-upsampled contribution.
                    Vec3 sms = sampleSMSRGB(rec, ray, lambdas, gen);
                    rad = rad + astroray::RGBIlluminantSpectrum(
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
    // Result of one SMS Newton attempt: scalar throughput along the
    // single-vertex caustic path, plus a converged flag. Used by both
    // the RGB and spectral entry points below.
    struct SMSAttempt {
        bool   ok;
        float  throughput;   // f * Le_color * Tr * G * weight, color stripped
        Vec3   fRGB;         // BSDF at x0 toward x1 (RGB-evaluated)
        Vec3   Le;           // light emission RGB at sampled emitter
        float  Tr;           // Schlick transmittance at the entry vertex (hero η)
    };

    // Run one Newton seed → optional valid SMS path. Returns ok=false on
    // miss/TIR/occlusion. The geometric pieces (Newton, refraction, Fresnel)
    // are wavelength-aware via `eta`: callers pass either the flat IOR
    // ratio (Phase 1) or 1/iorAt(λ_hero) (Phase 2).
    bool runSMSAttempt(const HitRecord& x0Rec, const Ray& primary,
                       const astroray::SampledWavelengths& lambdas,
                       std::mt19937& gen,
                       const Caster& C, float eta, float casterPickPdf,
                       const LightSample& ls,
                       astroray::SampledSpectrum& outFSpec,
                       float& outScalarWeight,
                       Vec3& outLeRGB,
                       float& outTr) {
        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        Vec3 wo_eye = -primary.direction.normalized();
        const auto& bvh = renderer_->getBVH();

        // Uniform seed on the side of the sphere facing x0 (Zeltner 2020 §4.4).
        Vec3 dirToX0 = (x0Rec.point - C.center).normalized();
        Vec3 sphU, sphV;
        buildOrthonormalBasis(dirToX0, sphU, sphV);
        float r1 = u01(gen), r2 = u01(gen);
        float phi = 2.0f * M_PI * r1;
        float cosT = std::sqrt(1.0f - r2);
        float sinT = std::sqrt(r2);
        Vec3 nSeed = (sphU * (sinT * std::cos(phi)) +
                      sphV * (sinT * std::sin(phi)) +
                      dirToX0 * cosT).normalized();
        Vec3 x1 = C.center + nSeed * C.radius;
        Vec3 t1, b1; buildOrthonormalBasis(nSeed, t1, b1);

        // pkg64 Phase 2 — Hanika 2015 §4, half-vector residual evaluated
        // with η(λ_hero). The residual decouples per-wavelength because
        // h(λ) = ω_i + η(λ)·ω_o is linear in the wavelength-dependent
        // η; each Newton solve uses the hero η baked into `eta`.
        auto constraint = [&](const Vec3& p, const Vec3& n,
                              const Vec3& s, const Vec3& t) {
            return amf::halfVectorResidual(x0Rec.point, p, ls.position,
                                           s, t, eta, /*refraction=*/true);
        };
        const float radius = C.radius;
        const Vec3& centerRef = C.center;
        auto reproject = [&](const Vec3& p, const Vec3& sIn, const Vec3& tIn,
                             float du, float dv,
                             Vec3& outX, Vec3& outN, Vec3& outS, Vec3& outT) {
            Vec3 q = p + sIn * du + tIn * dv;
            Vec3 d = q - centerRef;
            float len2 = d.length2();
            if (len2 < 1e-12f) return false;
            Vec3 nNew = d * (1.0f / std::sqrt(len2));
            outX = centerRef + nNew * radius;
            outN = nNew;
            buildOrthonormalBasis(nNew, outS, outT);
            return true;
        };

        amf::NewtonConfig cfg;
        cfg.maxIterations = smsMaxIters_;
        cfg.tolerance     = smsTolerance_;
        amf::NewtonResult R = amf::solve(x1, nSeed, t1, b1,
                                         constraint, reproject, cfg);
        if (!R.converged) return false;

        // Visibility from x0 to the converged x1 must hit the caster sphere.
        Vec3 dirToX1 = R.x1 - x0Rec.point;
        float distX0X1_2 = dirToX1.length2();
        if (distX0X1_2 < 1e-8f) return false;
        float distX0X1 = std::sqrt(distX0X1_2);
        Vec3 wi_x0 = dirToX1 * (1.0f / distX0X1);
        HitRecord vrec;
        if (!bvh->hit(Ray(x0Rec.point, wi_x0), 0.001f, distX0X1 + 1e-2f, vrec))
            return false;
        if (vrec.hitObject != static_cast<const Hittable*>(C.sphere))
            return false;

        // Refract entry direction at x1 using the wavelength-aware η.
        Vec3 wi_in = -wi_x0;
        Vec3 nEntry = R.n1;
        float cosI = -wi_in.dot(nEntry);
        float sin2T = eta * eta * std::max(0.0f, 1.0f - cosI * cosI);
        if (sin2T >= 1.0f) return false;  // TIR (wavelength-specific)
        Vec3 refracted = wi_in * eta + nEntry * (eta * cosI - std::sqrt(1.0f - sin2T));
        refracted = refracted.normalized();

        // The exit refraction is approximated by stepping past the sphere
        // along `refracted` and checking unobstructed visibility to the
        // light — the same Phase 1 single-vertex shortcut. Re-deriving the
        // full multi-vertex SMS estimator is future work.
        Vec3 toLight = ls.position - R.x1;
        float distLight2 = toLight.length2();
        float distLight = std::sqrt(distLight2);
        Vec3 dirLight = toLight * (1.0f / distLight);
        Vec3 exitOrigin = R.x1 + refracted * (2.0f * radius + 1e-3f);
        HitRecord lrec;
        bool hitOcc = bvh->hit(Ray(exitOrigin, dirLight), 0.001f,
                               distLight + 1e-2f, lrec);
        if (hitOcc && !(lrec.hitObject &&
                        lrec.hitObject->isInfiniteLight())) {
            return false;
        }

        // Schlick Fresnel transmittance with hero-λ η.
        float F0 = (1.0f - eta) / (1.0f + eta);
        F0 *= F0;
        float fresnel = F0 + (1.0f - F0) * std::pow(std::max(0.0f, 1.0f - cosI), 5.0f);
        outTr = 1.0f - fresnel;

        // BSDF at x0 toward x1 (spectral, queried on the caller's lambdas).
        outFSpec = x0Rec.material->evalSpectral(x0Rec, wo_eye, wi_x0, lambdas);

        // Geometric weight + seed-pdf inverse (Zeltner 2020 §4.4 simplified;
        // analytic Jacobian replacement is Phase-3+).
        float cosSeed = std::max(1e-3f, nSeed.dot(dirToX0));
        float seedAreaWeight = (M_PI * radius * radius) / cosSeed;

        float cosX0 = std::max(0.0f, x0Rec.normal.dot(wi_x0));
        float cosLight = std::max(0.0f, ls.normal.dot(-dirLight));
        float G = cosX0 * cosLight / std::max(distX0X1_2 * distLight2, 1e-6f);

        outLeRGB = ls.emission;
        outScalarWeight = (G * seedAreaWeight) /
                          (ls.pdf * casterPickPdf * static_cast<float>(smsSeeds_));
        return true;
    }

    // Phase 1 path: RGB throughput, scalar IOR. Untouched semantics so the
    // existing test_sms_caustic_validation regression baseline holds.
    Vec3 sampleSMSRGB(const HitRecord& x0Rec, const Ray& primary,
                      const astroray::SampledWavelengths& lambdas,
                      std::mt19937& gen) {
        const auto& lights = renderer_->getLights();
        if (lights.empty()) return Vec3(0);

        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        const Caster& C = casters_[std::min<size_t>(
            casters_.size() - 1,
            static_cast<size_t>(u01(gen) * casters_.size()))];
        float casterPickPdf = 1.0f / static_cast<float>(casters_.size());
        float eta = 1.0f / C.iorFlat;

        LightSample ls = lights.sample(x0Rec.point, gen);
        if (ls.pdf <= 0.0f) return Vec3(0);

        Vec3 contrib(0);
        for (int s = 0; s < smsSeeds_; ++s) {
            smsAttempts_ += 1.0f;

            astroray::SampledSpectrum fSpec;
            float w = 0.0f, Tr = 0.0f;
            Vec3 Le(0);
            if (!runSMSAttempt(x0Rec, primary, lambdas, gen, C, eta,
                               casterPickPdf, ls, fSpec, w, Le, Tr))
                continue;

            astroray::XYZ fxyz = fSpec.toXYZ(lambdas);
            Vec3 fRGB(fxyz.X, fxyz.Y, fxyz.Z);

            Vec3 sample = fRGB * Le * (Tr * w);
            float maxC = std::max(sample.x, std::max(sample.y, sample.z));
            if (maxC > smsContribClamp_) sample = sample * (smsContribClamp_ / maxC);

            contrib = contrib + sample;
            smsConverged_ += 1.0f;
            smsEnergy_ += maxC;
        }
        return contrib;
    }

    // Phase 2 path: hero-λ Newton (Hanika 2015 §4) — the geometric
    // residual + refraction + Fresnel use η evaluated at the hero
    // wavelength of `lambdas`. The contribution is written to the hero
    // spectral channel only; secondaries are zero. Because each ray draws
    // an independent λ_hero, per-pixel accumulation across rays produces
    // the prism-accurate chromatic spread.
    astroray::SampledSpectrum sampleSMSSpectral(
            const HitRecord& x0Rec, const Ray& primary,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) {
        astroray::SampledSpectrum out(0.0f);
        const auto& lights = renderer_->getLights();
        if (lights.empty()) return out;

        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        const Caster& C = casters_[std::min<size_t>(
            casters_.size() - 1,
            static_cast<size_t>(u01(gen) * casters_.size()))];
        float casterPickPdf = 1.0f / static_cast<float>(casters_.size());

        // pkg64 Phase 2, Hanika 2015 §4 — η(λ_hero). The Newton residual
        // h(x1; λ_hero) is the only place wavelength enters the geometric
        // solve; all spectral throughput downstream rides on the resulting
        // direction.
        float lambdaHero = lambdas.lambda(0);
        float iorHero    = C.mat ? C.mat->iorAt(lambdaHero) : C.iorFlat;
        if (iorHero <= 1.0f) return out;
        float eta = 1.0f / iorHero;

        LightSample ls = lights.sample(x0Rec.point, gen);
        if (ls.pdf <= 0.0f) return out;

        // Hero-λ contribution accumulator. Other channels stay zero — the
        // refracted direction is wavelength-specific so the secondary
        // wavelengths in this `lambdas` bundle are not valid for this
        // path. Same hero-only convention used by the dispersive
        // dielectric (plugins/materials/dielectric.cpp) on refraction.
        float heroAccum = 0.0f;

        for (int s = 0; s < smsSeeds_; ++s) {
            smsAttempts_ += 1.0f;

            astroray::SampledSpectrum fSpec;
            float w = 0.0f, Tr = 0.0f;
            Vec3 Le(0);
            if (!runSMSAttempt(x0Rec, primary, lambdas, gen, C, eta,
                               casterPickPdf, ls, fSpec, w, Le, Tr))
                continue;

            // Project the RGB emission to the hero wavelength via the
            // standard Jakob-Hanika upsampling — same path used elsewhere
            // for RGB → spectrum. This is the per-λ Le evaluation needed
            // for the prism rainbow: a white emitter is upsampled to a
            // ~D65-ish illuminant, so different hero λ values pick up
            // different emission magnitudes consistent with the source.
            float LeHero = astroray::RGBIlluminantSpectrum(
                {Le.x, Le.y, Le.z}).sample(lambdas)[0];

            float fHero  = fSpec[0];
            float sampleHero = fHero * LeHero * Tr * w;
            if (sampleHero > smsContribClamp_) sampleHero = smsContribClamp_;
            if (sampleHero < 0.0f) sampleHero = 0.0f;

            heroAccum += sampleHero;
            smsConverged_ += 1.0f;
            smsEnergy_ += sampleHero;
        }
        out[0] = heroAccum;
        return out;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("sms_caustic_path_tracer", SMSCausticPathTracer)
