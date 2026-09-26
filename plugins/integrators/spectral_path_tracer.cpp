#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/manifold/sms_attempt.h"
#include "astroray/photon/photon_map.h"        // pkg111
#include "astroray/photon_lights.h"            // pkg286/287: per-light physical photon emission
#include "astroray/manifold/mesh_attempt.h"    // pkg111: gatherTriangleCasters
#include "astroray/manifold/mesh_caustic.h"    // pkg111: rayTriHit

#include <atomic>     // #919: race-free SMS debug stats
#include <array>      // pkg198: std::array<SampledSpectrum, PASS_COUNT> pass buffers
#include <algorithm>  // pkg111: std::sort, std::min, std::max
#include <cstdio>     // pkg113 CAUSTIC_DBG
#include <cstdlib>    // pkg113 CAUSTIC_DBG (getenv)
#include <cmath>      // pkg111: std::sqrt, std::pow, std::fabs
#include <limits>     // pkg111: std::numeric_limits
#include <random>     // pkg111: std::mt19937
#include <utility>    // pkg111: std::pair
#include <vector>     // pkg111: std::vector

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
// pkg111 — photon-map caustics on the default path_tracer. When the
// integrator parameter `caustics` is set to "photon_map", the integrator
// builds a forward light-traced photon map in beginFrame (mirroring
// light_tracer_caustic.cpp, but as a PRE-PASS before the camera loop, not
// a separate integrator) and gathers at diffuse hits in sampleFull. The
// gather is NOT restricted to horizontal floors (the pkg106/109/110
// limitation) — it works at ANY (point, normal, bsdf), making caustics
// render on tilted/curved/wall receivers (pkg111 acceptance).
//
// Behaviour gates, by design (CLAUDE.md §2 / §3):
//   - Renderer::useRefractiveCaustics OFF (the default `false` path is
//     enabled by setting it via set_use_refractive_caustics): no hook is
//     installed, integrator is byte-for-byte identical to pre-pkg64-3.
//   - No caustic caster flagged: no hook is installed (skipping the
//     gather + std::function construction). Ditto.
//   - Otherwise: the hook fires only at non-delta vertices, and only
//     when there is at least one flagged refractive sphere caster.
//   - caustics != "photon_map": no photon map is built, integrator behaves
//     identically to pre-pkg111.
namespace amf = astroray::manifold;

class SpectralPathTracer : public Integrator {
    int  maxDepth_;
    bool spectralNewton_;     // default ON for the prism use case
    bool specularPoly_;       // pkg127: deterministic sphere seed finding (default OFF)
    int  sphereChainRefl_ = 0; // pkg227: sphere internal-reflection rainbow depth (0=off)
    amf::SMSConfig smsCfg_;
    std::string causticMode_; // pkg111: "none", "sms" (default), or "photon_map"
    // pkg125: band awareness. Mirrors multiwavelength_path_tracer.cpp:22-23,45-46
    // — read the wavelength range Renderer::setWavelengthRange wrote into
    // integratorParams_ ("lambda_min"/"lambda_max", raytracer.h:2160-2162) so
    // set_wavelength_range is honored instead of silently ignored.
    float lambdaMin_;
    float lambdaMax_;
    // pkg206: luminance-weighted hero-wavelength importance sampling on the
    // primary path. Default ON (internal sampler-quality change, NOT a UI artist
    // knob — spec Non-goal). Exposed via set_integrator_param("hero_importance",
    // 0|1) purely so the pkg206 benchmark can A/B uniform vs importance.
    bool heroImportance_;

    Renderer* renderer_ = nullptr;
    Camera* camera_ = nullptr;  // pkg87b: for Cryptomatte buffer access
    std::vector<amf::SMSCaster> casters_;
    // #919: sampleFull runs concurrently on render threads; plain float `+=`
    // lost updates. Double CAS add (C++17 has no atomic<double>::fetch_add).
    std::atomic<double> smsAttempts_{0.0};
    std::atomic<double> smsConverged_{0.0};
    std::atomic<double> smsEnergy_{0.0};
    static void statAdd(std::atomic<double>& a, double v) {
        double cur = a.load(std::memory_order_relaxed);
        while (!a.compare_exchange_weak(cur, cur + v, std::memory_order_relaxed)) {}
    }

    // pkg111: photon map state (when causticMode_ == "photon_map")
    astroray::photon::PhotonMap photonMap_;
    float photonGatherRadius_ = 0.0f;
    int   photonGatherK_      = 50;
    float photonCausticScale_ = 1.0f;
    bool  photonMapReady_     = false;
    // pkg286: artistic multiplier on the physical caustic. Default 1.2 kept
    // pending the owner decision (1.0 = physically exact).
    float causticBoost_       = 1.2f;
    float photonFluxY_        = 0.0f;   // Σ deposited photon flux (Y), debug stat
    static constexpr bool kPhotonDistantOnly = true;   // pkg286: suns only
public:
    explicit SpectralPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          // Phase 3 default: spectral wavelength-Newton ON. The Phase-3
          // acceptance gate is the prism rainbow, which only appears
          // with hero-λ Newton (Hanika 2015 §4). Toggle is exposed via
          // set_integrator_param("spectral_newton", 0|1) for parity
          // with sms_caustic_path_tracer.
          spectralNewton_(p.getInt("spectral_newton", 1) != 0),
          // pkg127: deterministic Specular-Polynomials seed finding for sphere
          // casters (Fan et al. 2024). OFF by default -> byte-identical to the
          // stochastic uniform-seed + Newton path; on, one polynomial solve
          // enumerates every specular vertex (no per-seed misses). Exposed via
          // set_integrator_param("sms_specular_poly", 0|1).
          specularPoly_(p.getInt("sms_specular_poly", 0) != 0),
          // pkg111: caustic mode. "sms" is the default (existing SMS behavior).
          // "photon_map" builds a forward light-traced photon map + gathers at
          // diffuse hits. "none" disables caustics entirely.
          causticMode_(p.getString("caustics", "sms")),
          // pkg125: mirror multiwavelength_path_tracer.cpp:45-46 — read the
          // band set_wavelength_range() wrote (module/blender_module.cpp:2160-2162).
          // Defaults are astroray::kLambdaMin/kLambdaMax (360/830 nm,
          // spectrum.h:26-27) — the SAME defaults sampleUniform(u) applied
          // implicitly pre-pkg125 (this file previously called
          // sampleUniform(dist01(gen)) with no band args). Keeping these as the
          // getFloat() fallback preserves byte-identical output when
          // set_wavelength_range was never called (acceptance: no regression).
          lambdaMin_(p.getFloat("lambda_min", astroray::kLambdaMin)),
          lambdaMax_(p.getFloat("lambda_max", astroray::kLambdaMax)),
          // pkg206: importance-sample the hero wavelength (default ON).
          heroImportance_(p.getInt("hero_importance", 1) != 0) {
        smsCfg_.seeds         = p.getInt("sms_seeds", 1);
        smsCfg_.maxIterations = p.getInt("sms_max_iterations", 20);
        smsCfg_.tolerance     = p.getFloat("sms_tolerance", 1e-4f);
        smsCfg_.contribClamp  = p.getFloat("sms_contrib_clamp", 4.0f);
        // pkg111: photon map parameters (used when caustics == "photon_map")
        photonGatherK_ = p.getInt("photon_knn", 50);
        causticBoost_  = p.getNumber("caustic_boost", 1.2f);   // pkg286
        // pkg227 Phase 2a: sphere internal-reflection rainbow chain depth. 0 = off
        // (byte-identical to the pkg127 single-vertex lens caustic); 1 = primary
        // bow, 2 = secondary. Owner decision #4: sphere cap 3 vertices (=1 reflect)
        // with headroom to 4 (=2). Clamped to [0,2]; only active with sms_specular_poly.
        sphereChainRefl_ = std::max(0, std::min(2, p.getInt("sphere_chain_reflections", 0)));
    }

    void beginFrame(Renderer& scene, Camera& cam) override {
        renderer_ = &scene;
        camera_ = &cam;  // pkg87b: store for Cryptomatte buffer access
        casters_.clear();
        smsAttempts_.store(0.0);
        smsConverged_.store(0.0);
        smsEnergy_.store(0.0);
        photonMapReady_ = false;  // pkg111

        // pkg111: if caustics == "photon_map", build the photon map here (before
        // the camera pass). Otherwise, fall through to the SMS path.
        if (causticMode_ == "photon_map") {
            buildPhotonMap(scene);
        } else if (scene.getUseRefractiveCaustics()) {
            // SMS path: per-object opt-in: only flagged objects participate.
            amf::gatherSphereCasters(scene, casters_, /*requireFlag=*/true);
            // pkg227: apply the global rainbow-chain depth to every caster.
            for (auto& c : casters_) c.chainReflections = sphereChainRefl_;
        }
    }

    std::unordered_map<std::string, float> debugStats() const override {
        // pkg111: report photon map stats when in photon_map mode.
        if (causticMode_ == "photon_map") {
            return {
                {"pm_ready",          photonMapReady_ ? 1.0f : 0.0f},
                {"pm_stored_photons", static_cast<float>(photonMap_.size())},
                {"pm_gather_radius",  photonGatherRadius_},
                {"pm_caustic_scale",  photonCausticScale_},
                {"pm_flux_y",         photonFluxY_},   // pkg286
            };
        }
        // Pre-pkg64-3 callers (test_integrator_plugin) expect an empty
        // stats map when nothing SMS-related happened. Emit stats only
        // when at least one caustic caster is flagged — otherwise the
        // integrator is byte-for-byte the pre-pkg64-3 path tracer and
        // should look like one in its diagnostics too.
        if (casters_.empty()) return {};
        return {
            {"sms_caster_count",    static_cast<float>(casters_.size())},
            {"sms_attempts",        static_cast<float>(smsAttempts_.load())},
            {"sms_converged",       static_cast<float>(smsConverged_.load())},
            {"sms_energy",          static_cast<float>(smsEnergy_.load())},
            {"sms_spectral_newton", spectralNewton_ ? 1.0f : 0.0f},
            {"sms_specular_poly",   specularPoly_ ? 1.0f : 0.0f},
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
            float tMin, tMax;  // #873: the AOV first hit honours the clip planes
            renderer_->primaryClipBounds(ray.direction, tMin, tMax);
            if (bvh->hit(ray, tMin, tMax, rec) && rec.material) {
                r.albedo = rec.material->getAlbedo();
                r.depth = rec.t;
                r.normal = rec.normal;
                // World-space first-hit position (Cycles PASS_POSITION,
                // intern/cycles/integrator/pass.cpp; Apache-2.0). Was never
                // filled — get_position_buffer returned Vec3(0) for every shape;
                // the only prior consumer (test_python_bindings) asserted shape/
                // finiteness, not value, so the gap went unnoticed. Misses keep
                // Vec3(0), matching depth/normal here.
                r.position = rec.point;
            }
        }
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        // pkg125: honor set_wavelength_range (lambdaMin_/lambdaMax_), mirroring
        // multiwavelength_path_tracer.cpp:74-75.
        // pkg206: importance-sample the hero wavelength (luminance-weighted D65
        // logistic CDF; unbiased per-lane density pdf). The sampler WINDOWS the
        // CDF to [lambdaMin_, lambdaMax_] and renormalizes its pdf, so it is
        // unbiased on the full band AND any narrowed set_wavelength_range band —
        // no defaultBand fallback needed (pkg206 refix, parity review). One
        // uniform draw either way — RNG dimension count is identical.
        astroray::SampledWavelengths lambdas =
            heroImportance_
                ? astroray::SampledWavelengths::sampleImportance(dist01(gen), lambdaMin_, lambdaMax_)
                : astroray::SampledWavelengths::sampleUniform(dist01(gen), lambdaMin_, lambdaMax_);
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

        // pkg87b: Cryptomatte per-shade-point accumulation.
        // Compute pixel index from ray screen coordinates and pass per-pixel crypto buffers.
        float* cryptoObjRanks = nullptr;
        float* cryptoMatRanks = nullptr;
        int cryptoDepth = 6;
        if (renderer_->getCryptomatteEnabled() && camera_) {
            int pixelX, pixelY;  // #845: inverse of the /W film mapping
            screenToPixel(ray.screenU, ray.screenV, camera_->width, camera_->height, pixelX, pixelY);
            int pixelIndex = pixelY * camera_->width + pixelX;
            int offset = pixelIndex * camera_->cryptomatteDepth * 2;
            cryptoObjRanks = camera_->cryptoObjectBuffer.data() + offset;
            cryptoMatRanks = camera_->cryptoMaterialBuffer.data() + offset;
            cryptoDepth = camera_->cryptomatteDepth;
        }

        // pkg198 Stage 1: per-pass spectral accumulators for the light-path AOVs.
        // pathTraceSpectral splats every radiance contribution to exactly one pass
        // (total partition), so Σpasses == rad exactly in spectral space.
        std::array<astroray::SampledSpectrum, PASS_COUNT> passSpectra;
        passSpectra.fill(astroray::SampledSpectrum(0.0f));
        astroray::SampledSpectrum rad =
            renderer_->pathTraceSpectral(ray, maxDepth_, lambdas, gen,
                                          &bounces, &weight, smsHook,
                                          cryptoObjRanks, cryptoMatRanks, cryptoDepth,
                                          &passSpectra);
        astroray::XYZ xyz = rad.toXYZ(lambdas);
        // Project each pass to XYZ (same convention as r.color); the render loop
        // converts to linear sRGB alongside beauty so the sum invariant survives.
        for (int p = 0; p < PASS_COUNT; ++p) {
            astroray::XYZ pxyz = passSpectra[p].toXYZ(lambdas);
            r.passes[p] = Vec3(pxyz.X, pxyz.Y, pxyz.Z);
        }

        // pkg111: Add photon-mapped caustic at the first diffuse hit (when ready).
        if (photonMapReady_ && bvh) {
            HitRecord rec;
            if (bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) &&
                rec.material && !rec.material->isEmissive()) {
                // k-NN density estimate (Jensen 1996 Eq. 8) at ANY diffuse surface.
                astroray::XYZ E = photonMap_.estimateIrradiance(
                    rec.point, photonGatherK_, photonGatherRadius_);
                const Vec3 alb = rec.material->getAlbedo();
                // Lambertian receiver: L = (albedo/π) · E; photonCausticScale_ = boost/π.
                Vec3 causticXYZ(alb.x * E.X * photonCausticScale_,
                                alb.y * E.Y * photonCausticScale_,
                                alb.z * E.Z * photonCausticScale_);
                xyz.X += causticXYZ.x;
                xyz.Y += causticXYZ.y;
                xyz.Z += causticXYZ.z;
                // pkg198: keep Σpasses == beauty when photon caustics are on — the
                // gather lands on a diffuse receiver → diffuse-indirect pass.
                r.passes[PASS_DIFFUSE_INDIRECT] += causticXYZ;
            }
        }

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

        LightSample ls;
        lights.sample(ls, x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return out;

        // The SMS attempt depends only on the vertex (x0) and the picked
        // caster — no need for a real "primary" ray. We synthesize one
        // pointing back along the BSDF outgoing direction; it is only
        // used inside runSMSAttempt to compute wo_eye = -primary.dir,
        // so any direction whose negative is x0Rec.normal-side works.
        Ray syntheticPrimary(x0Rec.point - x0Rec.normal,
                              x0Rec.normal * (-1.0f));

        float heroAccum = 0.0f;
        // pkg127: deterministic Specular-Polynomials seed finding. One solve
        // enumerates every specular vertex on the sphere; the axial-degenerate
        // case falls back to the stochastic Newton loop below.
        if (specularPoly_) {
            amf::SMSPolyResult pr = amf::runSMSAttemptPoly(
                *renderer_, x0Rec, syntheticPrimary, lambdas, C, eta, iorHero,
                casterPickPdf, ls, smsCfg_);
            if (!pr.fellBack) {
                float hero = pr.hero;
                int nSol = pr.nSolutions, nVal = pr.nValid;
                // pkg227: ADD the internal-reflection rainbow chain (distinct
                // light path from the single-vertex lens caustic).
                if (C.chainReflections > 0) {
                    amf::SMSPolyResult cr = amf::runSphereChainAttempt(
                        *renderer_, x0Rec, syntheticPrimary, lambdas, C, eta,
                        iorHero, casterPickPdf, ls, smsCfg_, C.chainReflections);
                    if (!cr.fellBack) {
                        hero += cr.hero; nSol += cr.nSolutions; nVal += cr.nValid;
                    }
                }
                statAdd(smsAttempts_, static_cast<float>(nSol));
                statAdd(smsConverged_, static_cast<float>(nVal));
                statAdd(smsEnergy_, hero);
                out[0] = hero;
                return out;
            }
        }
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            statAdd(smsAttempts_, 1.0f);
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
            statAdd(smsConverged_, 1.0f);
            statAdd(smsEnergy_, sampleHero);
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

        LightSample ls;
        lights.sample(ls, x0Rec.point, x0Rec.normal, lambdas, gen);
        if (ls.pdf <= 0.0f) return out;

        Ray syntheticPrimary(x0Rec.point - x0Rec.normal,
                              x0Rec.normal * (-1.0f));
        // pkg127: deterministic Specular-Polynomials seed finding (RGB path).
        if (specularPoly_) {
            amf::SMSPolyResult pr = amf::runSMSAttemptPoly(
                *renderer_, x0Rec, syntheticPrimary, lambdas, C, eta, C.iorFlat,
                casterPickPdf, ls, smsCfg_);
            if (!pr.fellBack) {
                Vec3 rgb = pr.rgb;
                int nSol = pr.nSolutions, nVal = pr.nValid;
                // pkg227: ADD the internal-reflection rainbow chain (RGB path).
                if (C.chainReflections > 0) {
                    amf::SMSPolyResult cr = amf::runSphereChainAttempt(
                        *renderer_, x0Rec, syntheticPrimary, lambdas, C, eta,
                        C.iorFlat, casterPickPdf, ls, smsCfg_, C.chainReflections);
                    if (!cr.fellBack) {
                        rgb = rgb + cr.rgb; nSol += cr.nSolutions; nVal += cr.nValid;
                    }
                }
                statAdd(smsAttempts_, static_cast<float>(nSol));
                statAdd(smsConverged_, static_cast<float>(nVal));
                statAdd(smsEnergy_, std::max(rgb.x, std::max(rgb.y, rgb.z)));
                return astroray::RGBIlluminantSpectrum(
                    {rgb.x, rgb.y, rgb.z}).sample(lambdas);
            }
        }
        Vec3 contribRGB(0);
        for (int s = 0; s < smsCfg_.seeds; ++s) {
            statAdd(smsAttempts_, 1.0f);
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
            statAdd(smsConverged_, 1.0f);
            statAdd(smsEnergy_, maxC);
        }
        return astroray::RGBIlluminantSpectrum(
            {contribRGB.x, contribRGB.y, contribRGB.z}).sample(lambdas);
    }

    // pkg111: Build the photon map (forward light-tracing from caustic casters).
    // Mirrors light_tracer_caustic.cpp buildPhotonMap, but deposits on ANY diffuse
    // receiver (not just horizontal floors), removing the `rec.normal.y > 0.7` gate.
    // Citation: Jensen 1996 (photon map), pkg109-110-111-photon-map-research.md.
    // pkg286: photons carry physical flux Phi_p = S(λ) W / N_i (Jensen 2001 §7.1,
    // photon_emitter.h), so the gather E = Σ Phi_p w_p / (norm π r²) is irradiance
    // in the same units as NEE; no per-map calibration. pkg287: one emitter per
    // dedicated lamp with its own geometry (photon_lights.h).
    void buildPhotonMap(Renderer& scene) {
        photonMapReady_ = false;
        photonGatherRadius_ = 0.0f;
        photonFluxY_ = 0.0f;
        // Lambertian receiver L = (albedo/π) E; boost is an artistic multiplier.
        photonCausticScale_ = causticBoost_ / 3.14159265358979323846f;
        const auto* bvh = scene.getBVH().get();
        if (!bvh) return;

        // Gather caustic caster bounds (union AABB of all flagged casters).
        AABB casterBounds;
        int casterCount = 0;
        if (!gatherCausticCasterBounds(scene, casterBounds, casterCount)) return;

        const auto& lights = scene.getLights();
        if (lights.empty()) return;

        const int photonCount = 3000000;  // match light_tracer_caustic default
        const std::vector<astroray::photon::PhotonLight> emitters =
            astroray::photon::buildPhotonLights(lights, casterBounds, photonCount,
                                                /*distantOnly=*/kPhotonDistantOnly);
        if (emitters.empty()) return;

        std::mt19937 gen(12345u);
        std::vector<astroray::photon::Photon> photons;
        photons.reserve(photonCount / 2);
        const float eps = 1e-3f;

        // Auto-select tracing path: flat prism (2 planar faces) -> explicit 2-face
        // refraction for collimated (distant) photons; otherwise -> general BVH loop.
        std::vector<amf::CausticTri> tris;
        const Material* prismMat = amf::gatherTriangleCasters(scene, tris);
        const bool flatPrism = (prismMat != nullptr) && countDistinctCasterPlanes(tris) == 2;

        auto deposit = [&](const HitRecord& rec, const Vec3& d, float lambda, float w) {
            // pkg286: no receiver cosine — the photon hit density already carries it.
            astroray::XYZ cmf = astroray::cieCmf1931_2deg(lambda);
            astroray::photon::Photon ph;
            ph.position = rec.point;
            ph.incidentDir = d;
            ph.power = astroray::XYZ{cmf.X * w, cmf.Y * w, cmf.Z * w};
            ph.lambda = lambda;
            photons.push_back(ph);
        };

        for (const auto& L : emitters) {
            const bool prismPath =
                flatPrism && L.emitter.kind == astroray::photon::kPeDistant;
            for (int p = 0; p < L.count; ++p) {
                Vec3 o, d;
                float lambda;
                const float w = astroray::photon::emitPhoton(L, gen, o, d, lambda);
                if (!(w > 0.0f)) continue;
                if (prismPath) {
                    // Explicit 2-face prism (mirrors light_tracer_caustic.cpp:238-275).
                    const float ior = prismMat->iorAt(lambda);
                    if (ior <= 1.0f) continue;
                    Vec3 n1;
                    float t1 = nearestCaster(tris, o, d, n1);
                    if (t1 < 0) continue;
                    Vec3 p1 = o + d * t1;
                    float tr = fresnelT(d.dot(n1), ior);
                    Vec3 d1;
                    if (!refract(d, n1, 1.0f / ior, d1)) continue;
                    Vec3 n2;
                    float t2 = nearestCaster(tris, p1 + d1 * 1e-4f, d1, n2);
                    if (t2 < 0) continue;
                    Vec3 p2 = p1 + d1 * (t2 + 1e-4f);
                    tr *= fresnelT(d1.dot(n2), ior);
                    Vec3 d2;
                    if (!refract(d1, n2, ior, d2)) continue;
                    HitRecord rec;
                    if (!bvh->hit(Ray(p2 + d2 * eps, d2), eps, std::numeric_limits<float>::max(), rec))
                        continue;
                    if (!rec.material || rec.material->isEmissive()) continue;
                    if (rec.hitObject && rec.hitObject->isCausticCaster()) continue;
                    // pkg111: REMOVED the `rec.normal.y < 0.7f` gate — deposit on ANY diffuse surface.
                    deposit(rec, d2, lambda, w * tr);
                    continue;
                }
                // General BVH loop (curved/solid glass).
                float tr = 1.0f;
                bool passedCaster = false;
                for (int bounce = 0; bounce < maxDepth_; ++bounce) {
                    HitRecord rec;
                    if (!bvh->hit(Ray(o, d), eps, std::numeric_limits<float>::max(), rec)) break;
                    if (!rec.material || rec.material->isEmissive()) break;
                    if (rec.material->isTransmissive()) {
                        float ior = rec.material->iorAt(lambda);
                        if (ior <= 1.0f) ior = 1.5f;
                        // pkg113: rec.normal is the RAY-ORIENTED normal (Sphere::hit ->
                        // setFaceNormal flips it to face the ray), NOT the geometric outward
                        // normal. Recover the geometric outward normal so the enter/exit test
                        // selects eta=ior at the glass->air exit. The old `ng = rec.normal`
                        // always took the "entering" branch (eta=1/ior at the exit) — a
                        // refraction-sign bug that lengthened the focal distance. The GPU
                        // pre-pass (photon_caustic.cu) already recovers it this way.
                        const Vec3 ng = rec.frontFace ? rec.normal : -rec.normal;
                        Vec3 nf;
                        float eta;
                        if (d.dot(ng) < 0.0f) {
                            nf = ng;
                            eta = 1.0f / ior;
                        } else {
                            nf = ng * -1.0f;
                            eta = ior;
                        }
                        Vec3 nd;
                        if (refract(d, nf, eta, nd)) {
                            tr *= fresnelT(d.dot(nf), ior);
                            d = nd;
                        } else {
                            d = (d - nf * (2.0f * d.dot(nf))).normalized();
                        }
                        passedCaster = true;
                        o = rec.point + d * eps;
                        continue;
                    }
                    // pkg111: REMOVED `rec.normal.y > 0.7f` — deposit on ANY diffuse receiver.
                    if (passedCaster && tr > 0.0f) deposit(rec, d, lambda, w * tr);
                    break;
                }
            }
        }
        if (photons.size() < 16) return;
        for (const auto& p : photons) photonFluxY_ += p.power.Y;

        if (std::getenv("CAUSTIC_DBG")) {
            Vec3 c(0, 0, 0); float wsum = 0.f;
            for (const auto& p : photons) { c = c + p.position * p.power.Y; wsum += p.power.Y; }
            c = c * (1.0f / std::max(wsum, 1e-12f));
            float rms = 0.f;
            for (const auto& p : photons) {
                Vec3 d = p.position - c;
                rms += p.power.Y * (d.x * d.x + d.z * d.z);
            }
            rms = std::sqrt(rms / std::max(wsum, 1e-12f));
            std::fprintf(stderr, "[CAUSTIC_DBG CPU] n=%zu centroidXZ=(%.3f,%.3f) rmsXZ=%.4f "
                         "totalY=%.4f\n", photons.size(), c.x, c.z, rms, wsum);
        }

        // Build the kd-tree photon map (Jensen 1996, photon_map.h).
        photonMap_.build(std::move(photons));

        // Calibrate gather radius (density-adaptive: 1.5x median k-th nearest).
        // Geometry only — pkg286 removed the brightness (peak) calibration.
        const int N = static_cast<int>(photonMap_.size());
        const int S = std::min(N, 4096);
        const int stride = std::max(1, N / S);
        std::vector<int> qi;
        std::vector<float> qd2;
        std::vector<float> kth;
        for (int i = 0; i < N; i += stride) {
            photonMap_.knn(photonMap_.photon(i).position, photonGatherK_, 1e30f, qi, qd2);
            if (!qd2.empty()) kth.push_back(std::sqrt(qd2.back()));
        }
        if (kth.empty()) return;
        std::sort(kth.begin(), kth.end());
        photonGatherRadius_ = 1.5f * kth[kth.size() / 2];
        if (photonGatherRadius_ <= 0.0f) return;
        photonMapReady_ = true;
    }

    // Helper: union AABB of all caustic-caster objects.
    static bool gatherCausticCasterBounds(Renderer& scene, AABB& out, int& count) {
        AABB acc;
        bool any = false;
        count = 0;
        for (const auto& obj : scene.getScene()) {
            if (!obj || !obj->isCausticCaster()) continue;
            AABB ob;
            if (!obj->boundingBox(ob)) continue;
            acc = any ? acc.merge(ob) : ob;
            any = true;
            ++count;
        }
        if (any) out = acc;
        return any;
    }

    // Helper: count distinct planar faces among triangle casters (2 = flat prism).
    static int countDistinctCasterPlanes(const std::vector<amf::CausticTri>& tris) {
        std::vector<std::pair<Vec3, float>> planes;
        for (const auto& t : tris) {
            Vec3 n = (t.v1 - t.v0).cross(t.v2 - t.v0).normalized();
            float d = std::fabs(n.dot(t.v0));
            bool found = false;
            for (const auto& pl : planes) {
                if (std::fabs(pl.first.dot(n)) > 0.999f &&
                    std::fabs(pl.second - d) < 1e-2f * (1.0f + d)) {
                    found = true;
                    break;
                }
            }
            if (!found) planes.emplace_back(n, d);
        }
        return static_cast<int>(planes.size());
    }

    // Helper: nearest triangle hit (explicit 2-face prism path).
    static float nearestCaster(const std::vector<amf::CausticTri>& tris,
                               const Vec3& o, const Vec3& d, Vec3& nOut) {
        float best = std::numeric_limits<float>::max();
        int bi = -1;
        for (int i = 0; i < static_cast<int>(tris.size()); ++i) {
            float t;
            if (amf::rayTriHit(o, d, tris[i], t) && t < best) {
                best = t;
                bi = i;
            }
        }
        if (bi < 0) return -1.0f;
        Vec3 n = (tris[bi].v1 - tris[bi].v0).cross(tris[bi].v2 - tris[bi].v0).normalized();
        if (n.dot(d) > 0.0f) n = n * -1.0f;
        nOut = n;
        return best;
    }

    // Helper: Snell refraction (returns false on TIR).
    static bool refract(const Vec3& d, const Vec3& n, float eta, Vec3& out) {
        float cosi = -d.dot(n);
        float s2 = eta * eta * (1.0f - cosi * cosi);
        if (s2 >= 1.0f) return false;
        out = (d * eta + n * (eta * cosi - std::sqrt(1.0f - s2))).normalized();
        return true;
    }

    // Helper: Fresnel transmission (Schlick approximation).
    static float fresnelT(float cosi, float eta) {
        float f0 = (1.0f - eta) / (1.0f + eta);
        f0 *= f0;
        float fr = f0 + (1.0f - f0) * std::pow(std::max(0.0f, 1.0f - std::fabs(cosi)), 5.0f);
        return 1.0f - fr;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("path_tracer", SpectralPathTracer)
