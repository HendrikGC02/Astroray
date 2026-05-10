// pkg64 Phase 1 — opt-in Specular Manifold Sampling integrator.
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
//   Mitsuba 2 SMS reference (BSD-3-Clause):
//     https://github.com/tizian/specular-manifold-sampling
//     commit 1f0e40342a8760450d5aa6202ea096feaa70256a (2021-06-27).
//     src/integrators/manifold_ss.cpp / src/librender/manifold_ss.cpp
//     are the integrator + Newton solver we mirror in spirit (no source
//     lines copied; the BSD-3 header would permit verbatim mirroring,
//     but Phase 1 only wires in the geometric skeleton).
//
// Phase 1 scope: RGB only. Spherical refractive casters only — Phase 2
// extends to triangle meshes via BVH-based reprojection, and adds the
// per-wavelength Newton residual from Hanika et al. 2015 §4 for the
// prism rainbow. Phase 3 folds SMS into the default path tracer.

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

    Renderer* renderer_ = nullptr;
    float causticConnections_ = 0.0f;
    float causticEnergy_ = 0.0f;
    float smsAttempts_  = 0.0f;
    float smsConverged_ = 0.0f;
    float smsEnergy_    = 0.0f;

    struct Caster {
        const Sphere* sphere;
        float radius;
        Vec3  center;
        float eta;     // n_outside / n_inside
    };
    std::vector<Caster> casters_;

public:
    explicit SMSCausticPathTracer(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          chainIters_(p.getInt("caustic_chain_iters", 3)),
          smsSeeds_(p.getInt("sms_seeds", 1)),
          smsMaxIters_(p.getInt("sms_max_iterations", 20)),
          smsTolerance_(p.getFloat("sms_tolerance", 1e-4f)),
          smsContribClamp_(p.getFloat("sms_contrib_clamp", 4.0f)) {}

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
                                       1.0f / ior});
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
        };
    }

    IntegratorCapabilities capabilities() const override {
        return {false, "SMS caustic integrator is CPU-only in Phase 1"};
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
                Vec3 sms = sampleSMS(rec, ray, lambdas, gen);
                rad = rad + astroray::RGBIlluminantSpectrum(
                    {sms.x, sms.y, sms.z}).sample(lambdas);
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
    // Sample SMS contribution at a non-delta primary hit. RGB.
    Vec3 sampleSMS(const HitRecord& x0Rec, const Ray& primary,
                   const astroray::SampledWavelengths& lambdas,
                   std::mt19937& gen) {
        const auto& bvh = renderer_->getBVH();
        const auto& lights = renderer_->getLights();
        if (!bvh || lights.empty()) return Vec3(0);

        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        Vec3 wo_eye = -primary.direction.normalized();

        // Pick a single caster uniformly. With one caster (the common
        // Phase 1 test case) this is deterministic.
        const Caster& C = casters_[std::min<size_t>(
            casters_.size() - 1,
            static_cast<size_t>(u01(gen) * casters_.size()))];
        float casterPickPdf = 1.0f / static_cast<float>(casters_.size());

        // Sample one emitter point.
        LightSample ls = lights.sample(x0Rec.point, gen);
        if (ls.pdf <= 0.0f) return Vec3(0);

        Vec3 contrib(0);
        for (int s = 0; s < smsSeeds_; ++s) {
            smsAttempts_ += 1.0f;

            // Uniform seed on the side of the sphere facing x0.
            Vec3 dirToX0 = (x0Rec.point - C.center).normalized();
            Vec3 sphU, sphV;
            buildOrthonormalBasis(dirToX0, sphU, sphV);
            // Cosine-weighted on hemisphere centred on dirToX0.
            float r1 = u01(gen), r2 = u01(gen);
            float phi = 2.0f * M_PI * r1;
            float cosT = std::sqrt(1.0f - r2);
            float sinT = std::sqrt(r2);
            Vec3 nSeed = (sphU * (sinT * std::cos(phi)) +
                          sphV * (sinT * std::sin(phi)) +
                          dirToX0 * cosT).normalized();
            Vec3 x1 = C.center + nSeed * C.radius;
            Vec3 t1, b1; buildOrthonormalBasis(nSeed, t1, b1);

            auto constraint = [&](const Vec3& p, const Vec3& n,
                                  const Vec3& s, const Vec3& t) {
                return amf::halfVectorResidual(x0Rec.point, p, ls.position,
                                               s, t, C.eta, /*refraction=*/true);
            };
            // Reproject by walking in the tangent plane and re-projecting
            // back onto the sphere via radial normalization. Sphere-only
            // shortcut; mesh reprojection (BVH ray cast) is Phase 2.
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
            if (!R.converged) continue;

            // Visibility: x0 → x1 must hit the caster sphere first; the
            // exiting refracted ray must reach the light without being
            // blocked.
            Vec3 dirToX1 = R.x1 - x0Rec.point;
            float distX0X1_2 = dirToX1.length2();
            if (distX0X1_2 < 1e-8f) continue;
            float distX0X1 = std::sqrt(distX0X1_2);
            Vec3 wi_x0 = dirToX1 * (1.0f / distX0X1);
            HitRecord vrec;
            if (!bvh->hit(Ray(x0Rec.point, wi_x0), 0.001f, distX0X1 + 1e-2f, vrec))
                continue;
            if (vrec.hitObject != static_cast<const Hittable*>(C.sphere))
                continue;

            // Refract at x1 (entry) and trace through the sphere; with a
            // uniform-IOR sphere the exit is found by another hit. We
            // approximate the exit point by re-hitting the sphere from
            // x1 + small offset along the refracted dir — the contribution
            // we add is a one-bounce caustic estimator (Phase 1 skeleton),
            // not the full multi-vertex SMS path of Zeltner 2020 §6.
            Vec3 wi_in = -wi_x0;  // ray entering the sphere
            Vec3 nEntry = R.n1;
            float eta = C.eta;
            float cosI = -wi_in.dot(nEntry);
            float sin2T = eta * eta * std::max(0.0f, 1.0f - cosI * cosI);
            if (sin2T >= 1.0f) continue;  // TIR
            Vec3 refracted = wi_in * eta + nEntry * (eta * cosI - std::sqrt(1.0f - sin2T));
            refracted = refracted.normalized();

            // Unblocked toward the light from x1's exit side. Without
            // computing the second refraction analytically, we ray-test
            // x1 → ls.position; if the refracted direction points roughly
            // at the light (and the ray reaches it once we step past the
            // sphere), we accept the connection.
            Vec3 toLight = ls.position - R.x1;
            float distLight2 = toLight.length2();
            float distLight = std::sqrt(distLight2);
            Vec3 dirLight = toLight * (1.0f / distLight);
            // Step past the sphere along the refracted dir to escape it.
            Vec3 exitOrigin = R.x1 + refracted * (2.0f * radius + 1e-3f);
            HitRecord lrec;
            bool hitOcc = bvh->hit(Ray(exitOrigin, dirLight), 0.001f,
                                   distLight + 1e-2f, lrec);
            if (hitOcc && !(lrec.hitObject &&
                            lrec.hitObject->isInfiniteLight())) {
                // Occluded.
                continue;
            }

            // Schlick Fresnel transmittance (RGB-uniform in Phase 1).
            float F0 = (1.0f - eta) / (1.0f + eta);
            F0 *= F0;
            float fresnel = F0 + (1.0f - F0) * std::pow(std::max(0.0f, 1.0f - cosI), 5.0f);
            float Tr = 1.0f - fresnel;

            // BSDF at x0 toward x1.
            astroray::SampledSpectrum f =
                x0Rec.material->evalSpectral(x0Rec, wo_eye, wi_x0, lambdas);
            astroray::XYZ fxyz = f.toXYZ(lambdas);
            Vec3 fRGB(fxyz.X, fxyz.Y, fxyz.Z);

            // Geometric / seed weight. We sampled the seed cosine-weighted
            // on the visible hemisphere of the sphere with pdf
            // p_seed = cos(theta) / pi (in solid-angle measure on the
            // hemisphere) → area-measure pdf cos(theta)/(pi r^2). Convert
            // contribution to area-measure light estimator:
            //   weight = (pi r^2 / cos(theta_seed)) for area normalization.
            // This is the SMS Eq. 11 reduced to one specular vertex, with
            // the solid-angle Jacobian replaced by the seed-pdf inverse.
            // Phase 2 will use the analytic det J from Zeltner 2020 §4.3.
            float cosSeed = std::max(1e-3f, nSeed.dot(dirToX0));
            float seedAreaWeight = (M_PI * radius * radius) / cosSeed;

            float cosX0 = std::max(0.0f, x0Rec.normal.dot(wi_x0));
            float cosLight = std::max(0.0f, ls.normal.dot(-dirLight));
            float G = cosX0 * cosLight / std::max(distX0X1_2 * distLight2, 1e-6f);

            Vec3 Le = ls.emission;
            Vec3 sample = fRGB * Le * (Tr * G * seedAreaWeight /
                                       (ls.pdf * casterPickPdf *
                                        static_cast<float>(smsSeeds_)));

            // Per-attempt clamp to avoid fireflies from near-singular
            // Jacobians while the analytic Jacobian is still pending.
            float maxC = std::max(sample.x, std::max(sample.y, sample.z));
            if (maxC > smsContribClamp_) sample = sample * (smsContribClamp_ / maxC);

            contrib = contrib + sample;
            smsConverged_ += 1.0f;
            smsEnergy_ += maxC;
        }
        return contrib;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("sms_caustic_path_tracer", SMSCausticPathTracer)
