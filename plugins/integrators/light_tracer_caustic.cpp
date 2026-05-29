// pkg106 Chunk E — forward light-tracer for dispersive prism caustics.
//
// Camera-side MNEE cannot cleanly resolve a flat prism's weak dispersion (the
// connection is a near-delta whose basin is spatially chaotic -> salt-and-pepper
// chromatic noise; see pkg106-research-2026-05-28.md). A prism rainbow is a
// FORWARD light-transport phenomenon: trace wavelengths from the collimated sun
// THROUGH the prism onto the diffuse receiver and deposit them. The dispersion
// (per-wavelength Sellmeier refraction) lands each wavelength at a different
// receiver position -> a smooth continuous spectrum, no specular-connection noise.
//
// Source / citations (CLAUDE.md §6):
//   Arvo, "Backward Ray Tracing", SIGGRAPH 1986 Course Notes — forward light
//     transport (light particles) for caustics.
//   Jensen, "Global Illumination using Photon Maps", EGWR 1996 — diffuse-surface
//     photon deposition + density estimation (here: a 2D grid on the receiver).
//   pkg110: the photon bounce is BSDF-driven — at each transmissive surface the
//     hit material's sampleSpectral (plugins/materials/dielectric.cpp) chooses
//     reflect/refract by Fresnel and handles TIR + Sellmeier dispersion at the hero
//     wavelength, so photons traverse ANY glass shape (sphere/lens/mesh) and
//     multi-bounce/TIR chains — not just the original hard-coded 2-face prism.
//
// Scope: deposits onto a horizontal (normal ~ +y) diffuse receiver. pkg109 stores
// photons in a world-space photon map (kd-tree, photon_map.h) built in beginFrame
// (serial, before the parallel camera loop, so no contention); the camera pass
// gathers via a k-NN density estimate (Jensen 1996 Eq. 8). The per-wavelength CIE
// deposit (spectrum.h cieCmf1964_10deg) gives physically-based colours. The
// horizontal-receiver restriction is lifted in pkg111 (gather on any surface).

#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/shapes.h"
#include "astroray/photon/photon_map.h"        // pkg109 world-space photon map (kd-tree)

#include <algorithm>
#include <cmath>
#include <limits>
#include <random>
#include <vector>

class LightTracerCaustic : public Integrator {
    int   maxDepth_;
    int   photons_;
    int   gatherK_;
    float boost_;
    Renderer* renderer_ = nullptr;

    astroray::photon::PhotonMap pm_;  // pkg109 world-space photon store (was a 2D grid)
    float floorY_ = 0.0f;             // receiver plane (still floor-only; pkg111 generalizes)
    float gatherRadius_ = 0.0f;       // k-NN search radius, auto-calibrated to photon density
    float causticScale_ = 1.0f;       // brightness auto-scale (peak band E -> boost_)
    bool  ready_ = false;
    float depositedFlux_ = 0.0f;

public:
    explicit LightTracerCaustic(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 12)),
          photons_(p.getInt("photon_count", 2000000)),
          gatherK_(p.getInt("caustic_knn", 50)),
          // float params don't route through the Python int-only set_integrator_param,
          // so brightness is an int knob (x0.1); default 10 -> 1.0.
          boost_(p.getInt("caustic_boost", 10) * 0.1f) {}

    IntegratorCapabilities capabilities() const override {
        return {false, "forward light-tracer caustic (CPU-only)"};
    }
    void setMaxDepth(int d) override { maxDepth_ = d; }

    std::unordered_map<std::string, float> debugStats() const override {
        return {{"lt_photons", static_cast<float>(photons_)},
                {"lt_deposited_flux", depositedFlux_},
                {"lt_gather_radius", gatherRadius_},
                {"lt_stored_photons", static_cast<float>(pm_.size())},
                {"lt_grid_ready", ready_ ? 1.0f : 0.0f}};
    }

    void beginFrame(Renderer& scene, Camera& /*cam*/) override {
        renderer_ = &scene;
        buildPhotonMap(scene);
    }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        SampleResult r;
        if (!renderer_) return r;
        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        astroray::SampledWavelengths lambdas =
            astroray::SampledWavelengths::sampleUniform(u01(gen));

        int bounces = 0; float weight = 0.0f; int conn = 0; float energy = 0.0f;
        astroray::SampledSpectrum rad = renderer_->pathTraceSpectralCaustic(
            ray, maxDepth_, 0, lambdas, gen, &bounces, &weight, &conn, &energy,
            nullptr, nullptr, 6);
        astroray::XYZ xyz = rad.toXYZ(lambdas);

        // Add the forward-deposited caustic on the horizontal diffuse receiver.
        if (ready_) {
            const auto* bvh = renderer_->getBVH().get();
            HitRecord rec;
            if (bvh && bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec) &&
                rec.material && !rec.material->isEmissive() &&
                rec.normal.y > 0.9f && std::fabs(rec.point.y - floorY_) < 0.05f) {
                // pkg109: k-NN density estimate at the floor hit (Jensen 1996 Eq. 8)
                // replaces the bilinear 2D-grid lookup.
                astroray::XYZ E = pm_.estimateIrradiance(rec.point, gatherK_, gatherRadius_);
                const Vec3 alb = rec.material->getAlbedo();
                // Lambertian receiver: Lo = albedo/pi * E_irradiance (boost folds 1/pi + scale).
                xyz.X += alb.x * E.X * causticScale_;
                xyz.Y += alb.y * E.Y * causticScale_;
                xyz.Z += alb.z * E.Z * causticScale_;
            }
        }
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        r.albedo = Vec3(0.5f);
        return r;
    }

private:
    // Union AABB of all caustic-caster objects (any shape: triangles, spheres,
    // meshes) flagged via setCausticCaster. We only need their combined bounds to
    // aim the emission aperture — the bounce uses the BVH + the hit material's
    // spectral BSDF, so no per-shape refraction code is needed.
    static bool gatherCausticCasterBounds(Renderer& scene, AABB& out, int& count) {
        AABB acc; bool any = false; count = 0;
        for (const auto& obj : scene.getScene()) {
            if (!obj || !obj->isCausticCaster()) continue;
            AABB ob;
            if (!obj->boundingBox(ob)) continue;
            acc = any ? acc.merge(ob) : ob;
            any = true; ++count;
        }
        if (any) out = acc;
        return any;
    }

    void buildPhotonMap(Renderer& scene) {
        ready_ = false; depositedFlux_ = 0.0f; gatherRadius_ = 0.0f; causticScale_ = 1.0f;
        const auto* bvh = scene.getBVH().get();
        if (!bvh) return;

        // Casters can be ANY transmissive geometry flagged via setCausticCaster;
        // we only need their combined bounds to aim the emission aperture.
        AABB casterBounds; int casterCount = 0;
        if (!gatherCausticCasterBounds(scene, casterBounds, casterCount)) return;
        const Vec3 casterC = casterBounds.centroid();
        const float crad = (casterBounds.max - casterBounds.min).length() * 0.55f + 1e-3f;

        const auto& lights = scene.getLights();
        if (lights.empty()) return;

        std::mt19937 gen(12345u);
        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        astroray::SampledWavelengths probe = astroray::SampledWavelengths::sampleUniform(0.5f);
        LightSample ls; lights.sample(ls, casterC, Vec3(0, 1, 0), probe, gen);
        Vec3 sunDir = (casterC - ls.position).normalized();   // propagation toward the casters
        if (sunDir.length2() < 1e-6f) return;

        // Aperture frame around the sun direction (sample the entry disc).
        Vec3 a = (std::fabs(sunDir.x) < 0.9f) ? Vec3(1, 0, 0) : Vec3(0, 1, 0);
        Vec3 fu = (a - sunDir * a.dot(sunDir)).normalized();
        Vec3 fv = sunDir.cross(fu);
        Vec3 origin0 = casterC - sunDir * (crad + 2.0f);

        // Pass 1: BSDF-driven photon trace. Each photon carries a hero wavelength;
        // at every transmissive surface the material's sampleSpectral chooses
        // reflect/refract by Fresnel — handling TIR, multi-bounce, and Sellmeier
        // dispersion at the hero IOR — so a photon traverses ANY glass shape. It is
        // deposited on the first diffuse (non-transmissive) receiver, but only if it
        // passed >=1 caster (an L S+ D caustic path), so direct light is not
        // double-counted. (The dielectric f carries the radiance eta^2 factor; for
        // an air->glass->air caustic path the enter/exit factors cancel, and the
        // brightness auto-scale below normalizes the rest.)
        // Cited: Jensen 1996 photon tracing; dielectric.cpp sampleSpectral (hero-λ).
        std::vector<astroray::photon::Photon> photons;
        photons.reserve(photons_ / 2);
        std::vector<float> ys;
        const float eps = 1e-3f;
        for (int p = 0; p < photons_; ++p) {
            astroray::SampledWavelengths lambdas =
                astroray::SampledWavelengths::sampleUniform(u01(gen), 380.0f, 720.0f);
            float ra = (u01(gen) * 2.0f - 1.0f) * crad;
            float rb = (u01(gen) * 2.0f - 1.0f) * crad;
            Vec3 o = origin0 + fu * ra + fv * rb;
            Vec3 d = sunDir;
            float throughput = 1.0f;
            bool passedCaster = false;
            for (int bounce = 0; bounce < maxDepth_; ++bounce) {
                HitRecord rec;
                if (!bvh->hit(Ray(o, d), eps, std::numeric_limits<float>::max(), rec)) break;
                if (!rec.material || rec.material->isEmissive()) break;
                if (rec.material->isTransmissive()) {
                    BSDFSampleSpectral bss =
                        rec.material->sampleSpectral(rec, d * -1.0f, gen, lambdas);
                    throughput *= bss.f_spectral[0];          // hero-channel throughput
                    if (rec.hitObject && rec.hitObject->isCausticCaster()) passedCaster = true;
                    if (throughput <= 0.0f || bss.wi.length2() < 1e-8f) break;
                    d = bss.wi.normalized();
                    o = rec.point + d * eps;
                    continue;
                }
                // Diffuse receiver: deposit a caustic photon (only L S+ D paths).
                if (passedCaster && rec.normal.y > 0.7f && throughput > 0.0f) {
                    const float lambdaHero = lambdas.lambda(0);
                    astroray::XYZ cmf = astroray::cieCmf1964_10deg(lambdaHero);
                    astroray::photon::Photon ph;
                    ph.position = rec.point;
                    ph.incidentDir = d;                       // photon travel direction
                    ph.power = astroray::XYZ{cmf.X * throughput, cmf.Y * throughput,
                                             cmf.Z * throughput};
                    ph.lambda = lambdaHero;
                    photons.push_back(ph);
                    depositedFlux_ += ph.power.Y;
                    ys.push_back(rec.point.y);
                }
                break;
            }
        }
        if (photons.size() < 16) return;

        // Receiver plane (median y of deposits) for the floor gate in sampleFull.
        std::sort(ys.begin(), ys.end());
        floorY_ = ys[ys.size() / 2];

        // Build the world-space photon map (kd-tree). Jensen 1996 / photon_map.h.
        pm_.build(std::move(photons));

        // Calibrate the gather. (1) Density-adaptive search radius = 1.5x the median
        // k-th-nearest distance over a subsample of stored photons. (2) Brightness
        // auto-scale so the band's near-peak irradiance maps to ~boost (keeps the
        // result resolution/count-independent, as the old per-cell peak-scale did).
        const int N = static_cast<int>(pm_.size());
        const int S = std::min(N, 4096);
        const int stride = std::max(1, N / S);
        std::vector<int> qi; std::vector<float> qd2;
        std::vector<float> kth;
        for (int i = 0; i < N; i += stride) {
            pm_.knn(pm_.photon(i).position, gatherK_, 1e30f, qi, qd2);
            if (!qd2.empty()) kth.push_back(std::sqrt(qd2.back()));
        }
        if (kth.empty()) return;
        std::sort(kth.begin(), kth.end());
        gatherRadius_ = 1.5f * kth[kth.size() / 2];
        if (gatherRadius_ <= 0.0f) return;

        std::vector<float> peaks;
        for (int i = 0; i < N; i += stride) {
            astroray::XYZ E =
                pm_.estimateIrradiance(pm_.photon(i).position, gatherK_, gatherRadius_);
            if (E.Y > 0.0f) peaks.push_back(E.Y);
        }
        if (peaks.empty()) return;
        std::sort(peaks.begin(), peaks.end());
        const float peak = peaks[static_cast<size_t>(peaks.size() * 0.95f)];
        if (peak <= 0.0f) return;
        causticScale_ = boost_ / peak;
        ready_ = true;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("light_tracer_caustic", LightTracerCaustic)
