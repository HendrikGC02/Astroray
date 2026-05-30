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
//   Refraction/Fresnel mirror plugins/materials/dielectric.cpp.
//
// pkg110: the photon bounce AUTO-SELECTS by caster geometry.
//   * A FLAT prism (caster triangles forming exactly two planar refracting faces)
//     uses the explicit 2-face refraction — a clean, dense, single dispersed-path
//     deposit that yields a smooth rainbow. (A wide forward aperture through a
//     *solid* prism scatters photons through the extra faces into chromatic noise,
//     so the flat case is kept on the special 2-face path.)
//   * Any OTHER caster (a curved/solid shape: sphere, lens, triangulated mesh) uses
//     the GENERAL deterministic BVH refraction loop: at each transmissive hit it
//     refracts (Snell + Schlick-Fresnel, enter/exit from the geometric-normal sign,
//     per-wavelength iorAt) or reflects on TIR, through any number of faces — this
//     is what makes a glass SPHERE focus a caustic.
// Both paths deposit per-wavelength CIE flux into the same world-space photon map.
//
// Scope: deposits onto a horizontal (normal ~ +y) diffuse receiver (pkg111 lifts
// this). pkg109 stores photons in a world-space kd-tree (photon_map.h) built in
// beginFrame (serial, before the parallel camera loop); the camera pass gathers via
// a k-NN density estimate (Jensen 1996 Eq. 8). The per-wavelength CIE deposit
// (spectrum.h cieCmf1964_10deg) gives physically-based rainbow colours.

#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/shapes.h"
#include "astroray/manifold/mesh_attempt.h"   // gatherTriangleCasters, CausticTri (flat-prism path)
#include "astroray/manifold/mesh_caustic.h"    // rayTriHit
#include "astroray/photon/photon_map.h"        // pkg109 world-space photon map (kd-tree)

#include <algorithm>
#include <cmath>
#include <limits>
#include <random>
#include <utility>
#include <vector>

namespace amf = astroray::manifold;

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
          // pkg-integrator-float-param: caustic_boost is now a direct float
          // brightness multiplier read via getNumber (accepts the int or float
          // Python route: set_integrator_param_float / set_integrator_param).
          boost_(p.getNumber("caustic_boost", 1.0f)) {}

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
    // meshes) flagged via setCausticCaster. Only the combined bounds are needed to
    // aim the emission aperture; the bounce uses the BVH + each hit's geometric
    // normal + material iorAt, so no per-shape refraction code is needed.
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

    // Number of distinct planar faces among flat triangle casters. A genuine prism
    // is two coplanar-grouped refracting faces (== 2); a curved/triangulated mesh or
    // many-faced solid is > 2. Used to route the flat prism to the clean 2-face path.
    static int countDistinctCasterPlanes(const std::vector<amf::CausticTri>& tris) {
        std::vector<std::pair<Vec3, float>> planes;  // (unit normal, |offset|)
        for (const auto& t : tris) {
            Vec3 n = (t.v1 - t.v0).cross(t.v2 - t.v0).normalized();
            float d = std::fabs(n.dot(t.v0));
            bool found = false;
            for (const auto& pl : planes) {
                if (std::fabs(pl.first.dot(n)) > 0.999f &&        // parallel or anti-parallel
                    std::fabs(pl.second - d) < 1e-2f * (1.0f + d)) { found = true; break; }
            }
            if (!found) planes.emplace_back(n, d);
        }
        return static_cast<int>(planes.size());
    }

    // Nearest caster-triangle hit along (o,d); fills the geometric normal oriented
    // against d. Returns t (>0) or -1 on miss. (explicit flat-prism 2-face path)
    static float nearestCaster(const std::vector<amf::CausticTri>& tris,
                               const Vec3& o, const Vec3& d, Vec3& nOut) {
        float best = std::numeric_limits<float>::max(); int bi = -1;
        for (int i = 0; i < (int)tris.size(); ++i) {
            float t;
            if (amf::rayTriHit(o, d, tris[i], t) && t < best) { best = t; bi = i; }
        }
        if (bi < 0) return -1.0f;
        Vec3 n = (tris[bi].v1 - tris[bi].v0).cross(tris[bi].v2 - tris[bi].v0).normalized();
        if (n.dot(d) > 0.0f) n = n * -1.0f;
        nOut = n;
        return best;
    }

    static bool refract(const Vec3& d, const Vec3& n, float eta, Vec3& out) {
        float cosi = -d.dot(n);
        float s2 = eta * eta * (1.0f - cosi * cosi);
        if (s2 >= 1.0f) return false;          // TIR
        out = (d * eta + n * (eta * cosi - std::sqrt(1.0f - s2))).normalized();
        return true;
    }
    static float fresnelT(float cosi, float eta) {
        float f0 = (1.0f - eta) / (1.0f + eta); f0 *= f0;
        float fr = f0 + (1.0f - f0) * std::pow(std::max(0.0f, 1.0f - std::fabs(cosi)), 5.0f);
        return 1.0f - fr;
    }

    void buildPhotonMap(Renderer& scene) {
        ready_ = false; depositedFlux_ = 0.0f; gatherRadius_ = 0.0f; causticScale_ = 1.0f;
        const auto* bvh = scene.getBVH().get();
        if (!bvh) return;

        // Casters can be ANY transmissive geometry flagged via setCausticCaster;
        // only their combined bounds are needed to aim the emission aperture.
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

        std::vector<astroray::photon::Photon> photons;
        photons.reserve(photons_ / 2);
        std::vector<float> ys;
        const float lmin = 380.0f, lmax = 720.0f;
        const float eps = 1e-3f;

        // Auto-select the tracing path by caster geometry (see file header). A flat
        // prism (caster triangles forming exactly two planar faces) -> explicit
        // 2-face refraction (clean single dispersed path); anything else -> the
        // general deterministic BVH loop (curved/solid glass: sphere, lens, mesh).
        std::vector<amf::CausticTri> tris;
        const Material* prismMat = amf::gatherTriangleCasters(scene, tris);
        const bool flatPrism = (prismMat != nullptr) && countDistinctCasterPlanes(tris) == 2;

        if (flatPrism) {
            // Explicit 2-face prism: entry face (air->glass) then exit face
            // (glass->air) via the nearest caster triangle; deposit on the first
            // horizontal diffuse receiver — one clean dispersed gradient per lambda.
            for (int p = 0; p < photons_; ++p) {
                const float lambda = lmin + (lmax - lmin) * u01(gen);
                const float ior = prismMat->iorAt(lambda);
                if (ior <= 1.0f) continue;
                const float ra = (u01(gen) * 2.0f - 1.0f) * crad;
                const float rb = (u01(gen) * 2.0f - 1.0f) * crad;
                Vec3 o = origin0 + fu * ra + fv * rb;
                Vec3 d = sunDir;
                Vec3 n1; float t1 = nearestCaster(tris, o, d, n1);
                if (t1 < 0) continue;
                Vec3 p1 = o + d * t1;
                float tr = fresnelT(d.dot(n1), ior);
                Vec3 d1; if (!refract(d, n1, 1.0f / ior, d1)) continue;
                Vec3 n2; float t2 = nearestCaster(tris, p1 + d1 * 1e-4f, d1, n2);
                if (t2 < 0) continue;
                Vec3 p2 = p1 + d1 * (t2 + 1e-4f);
                tr *= fresnelT(d1.dot(n2), ior);
                Vec3 d2; if (!refract(d1, n2, ior, d2)) continue;
                HitRecord rec;
                if (!bvh->hit(Ray(p2 + d2 * eps, d2), eps,
                              std::numeric_limits<float>::max(), rec)) continue;
                if (!rec.material || rec.material->isEmissive()) continue;
                if (rec.hitObject && rec.hitObject->isCausticCaster()) continue;
                if (rec.normal.y < 0.7f) continue;            // horizontal receiver only
                astroray::XYZ cmf = astroray::cieCmf1964_10deg(lambda);
                astroray::photon::Photon ph;
                ph.position = rec.point;
                ph.incidentDir = d2;
                ph.power = astroray::XYZ{cmf.X * tr, cmf.Y * tr, cmf.Z * tr};
                ph.lambda = lambda;
                photons.push_back(ph);
                depositedFlux_ += ph.power.Y;
                ys.push_back(rec.point.y);
            }
        } else {
            // General deterministic refraction loop (curved/solid glass: sphere,
            // lens, mesh). At each transmissive hit refract (Snell + Schlick-Fresnel,
            // enter/exit from the geometric-normal sign, per-wavelength iorAt) or
            // reflect on TIR; deposit on the first diffuse receiver, only on an L S+ D
            // path (passed >= 1 caster) so direct light is not double-counted.
            for (int p = 0; p < photons_; ++p) {
                const float lambda = lmin + (lmax - lmin) * u01(gen);
                const float ra = (u01(gen) * 2.0f - 1.0f) * crad;
                const float rb = (u01(gen) * 2.0f - 1.0f) * crad;
                Vec3 o = origin0 + fu * ra + fv * rb;
                Vec3 d = sunDir;
                float tr = 1.0f;
                bool passedCaster = false;
                for (int bounce = 0; bounce < maxDepth_; ++bounce) {
                    HitRecord rec;
                    if (!bvh->hit(Ray(o, d), eps, std::numeric_limits<float>::max(), rec)) break;
                    if (!rec.material || rec.material->isEmissive()) break;
                    if (rec.material->isTransmissive()) {
                        float ior = rec.material->iorAt(lambda);
                        if (ior <= 1.0f) ior = 1.5f;
                        const Vec3 ng = rec.normal;            // geometric outward normal
                        Vec3 nf; float eta;
                        if (d.dot(ng) < 0.0f) { nf = ng;         eta = 1.0f / ior; }  // entering
                        else                  { nf = ng * -1.0f; eta = ior; }         // exiting
                        Vec3 nd;
                        if (refract(d, nf, eta, nd)) { tr *= fresnelT(d.dot(nf), ior); d = nd; }
                        else { d = (d - nf * (2.0f * d.dot(nf))).normalized(); }       // TIR
                        // Mark the path as a caustic path on transmission (not via the
                        // per-hit caster flag): a mesh caster's flag sits on the wrapping
                        // Translate/Scale decorator, not its per-triangle hits, so checking
                        // rec.hitObject->isCausticCaster() would never trip for a mesh. The
                        // integrator only runs when a flagged caster exists, so this is safe.
                        passedCaster = true;
                        o = rec.point + d * eps;
                        continue;
                    }
                    if (passedCaster && rec.normal.y > 0.7f && tr > 0.0f) {
                        astroray::XYZ cmf = astroray::cieCmf1964_10deg(lambda);
                        astroray::photon::Photon ph;
                        ph.position = rec.point;
                        ph.incidentDir = d;
                        ph.power = astroray::XYZ{cmf.X * tr, cmf.Y * tr, cmf.Z * tr};
                        ph.lambda = lambda;
                        photons.push_back(ph);
                        depositedFlux_ += ph.power.Y;
                        ys.push_back(rec.point.y);
                    }
                    break;
                }
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
