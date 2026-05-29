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
//   Refraction/Fresnel mirror plugins/materials/dielectric.cpp; the prism faces
//     are the setCausticCaster-flagged triangles (mesh_attempt.h gather).
//
// Scope: deposits onto a horizontal (normal ~ +y) diffuse receiver via a 2D
// (x,z) grid built in beginFrame (serial, before the parallel camera loop, so no
// contention); the camera pass gathers bilinearly. Per-wavelength CIE deposit
// (spectrum.h cieCmf1964_10deg) gives physically-based rainbow colours.

#include "astroray/register.h"
#include "astroray/integrator.h"
#include "astroray/spectrum.h"
#include "astroray/shapes.h"
#include "astroray/manifold/mesh_attempt.h"   // gatherTriangleCasters, CausticTri
#include "astroray/manifold/mesh_caustic.h"    // rayTriHit

#include <algorithm>
#include <cmath>
#include <limits>
#include <random>
#include <vector>

namespace amf = astroray::manifold;

class LightTracerCaustic : public Integrator {
    int   maxDepth_;
    int   photons_;
    int   gridRes_;
    float boost_;
    Renderer* renderer_ = nullptr;

    std::vector<astroray::XYZ> grid_;  // gridRes_ x gridRes_ accumulated irradiance
    int   gn_ = 0;
    float floorY_ = 0.0f;
    float gx0_ = 0, gx1_ = 0, gz0_ = 0, gz1_ = 0;
    bool  ready_ = false;
    float depositedFlux_ = 0.0f;

public:
    explicit LightTracerCaustic(const astroray::ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 12)),
          photons_(p.getInt("photon_count", 2000000)),
          gridRes_(p.getInt("caustic_grid_res", 256)),
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
                {"lt_grid_ready", ready_ ? 1.0f : 0.0f}};
    }

    void beginFrame(Renderer& scene, Camera& /*cam*/) override {
        renderer_ = &scene;
        buildCausticGrid(scene);
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
                astroray::XYZ E = gather(rec.point.x, rec.point.z);
                const Vec3 alb = rec.material->getAlbedo();
                // Lambertian receiver: Lo = albedo/pi * E_irradiance (boost folds 1/pi + scale).
                xyz.X += alb.x * E.X;
                xyz.Y += alb.y * E.Y;
                xyz.Z += alb.z * E.Z;
            }
        }
        r.color = Vec3(xyz.X, xyz.Y, xyz.Z);
        r.albedo = Vec3(0.5f);
        return r;
    }

private:
    int idx(int i, int j) const { return j * gn_ + i; }

    astroray::XYZ gather(float x, float z) const {
        if (gn_ <= 0 || gx1_ <= gx0_ || gz1_ <= gz0_) return {};
        float fx = (x - gx0_) / (gx1_ - gx0_) * (gn_ - 1);
        float fz = (z - gz0_) / (gz1_ - gz0_) * (gn_ - 1);
        if (fx < 0 || fx > gn_ - 1 || fz < 0 || fz > gn_ - 1) return {};
        int i0 = (int)fx, j0 = (int)fz;
        int i1 = std::min(i0 + 1, gn_ - 1), j1 = std::min(j0 + 1, gn_ - 1);
        float tx = fx - i0, tz = fz - j0;
        auto L = [&](int i, int j) { return grid_[idx(i, j)]; };
        astroray::XYZ out;
        auto add = [&](const astroray::XYZ& v, float w) {
            out.X += v.X * w; out.Y += v.Y * w; out.Z += v.Z * w; };
        add(L(i0, j0), (1 - tx) * (1 - tz)); add(L(i1, j0), tx * (1 - tz));
        add(L(i0, j1), (1 - tx) * tz);       add(L(i1, j1), tx * tz);
        return out;
    }

    // Nearest caster-triangle hit along (o,d); fills the geometric normal
    // oriented against d. Returns t (>0) or -1 on miss.
    static float nearestCaster(const std::vector<amf::CausticTri>& tris,
                               const Vec3& o, const Vec3& d, Vec3& nOut) {
        float best = std::numeric_limits<float>::max(); int bi = -1;
        for (int i = 0; i < (int)tris.size(); ++i) {
            float t;
            if (amf::rayTriHit(o, d, tris[i], t) && t < best) { best = t; bi = i; }
        }
        if (bi < 0) return -1.0f;
        Vec3 n = (tris[bi].v1 - tris[bi].v0).cross(tris[bi].v2 - tris[bi].v0).normalized();
        if (n.dot(d) > 0.0f) n = n * -1.0f;   // orient against the incident ray
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

    void buildCausticGrid(Renderer& scene) {
        ready_ = false; depositedFlux_ = 0.0f;
        std::vector<amf::CausticTri> tris;
        const Material* mat = amf::gatherTriangleCasters(scene, tris);
        if (tris.empty() || !mat) return;
        const auto* bvh = scene.getBVH().get();
        if (!bvh) return;

        // Sun propagation direction: sample the (collimated/distant) light.
        const auto& lights = scene.getLights();
        if (lights.empty()) return;
        Vec3 prismC(0.0f), lo(1e30f), hi(-1e30f);
        for (const auto& tr : tris) {
            for (const Vec3& v : {tr.v0, tr.v1, tr.v2}) {
                prismC = prismC + v;
                lo = Vec3(std::min(lo.x, v.x), std::min(lo.y, v.y), std::min(lo.z, v.z));
                hi = Vec3(std::max(hi.x, v.x), std::max(hi.y, v.y), std::max(hi.z, v.z));
            }
        }
        prismC = prismC * (1.0f / (3.0f * tris.size()));
        float prad = (hi - lo).length() * 0.55f;

        std::mt19937 gen(12345u);
        std::uniform_real_distribution<float> u01(0.0f, 1.0f);
        astroray::SampledWavelengths probe = astroray::SampledWavelengths::sampleUniform(0.5f);
        LightSample ls; lights.sample(ls, prismC, Vec3(0, 1, 0), probe, gen);
        Vec3 sunDir = (prismC - ls.position).normalized();   // propagation (toward prism)
        if (sunDir.length2() < 1e-6f) return;

        // Orthonormal frame around the sun direction for sampling the entry aperture.
        Vec3 a = (std::fabs(sunDir.x) < 0.9f) ? Vec3(1, 0, 0) : Vec3(0, 1, 0);
        Vec3 fu = (a - sunDir * a.dot(sunDir)).normalized();
        Vec3 fv = sunDir.cross(fu);
        Vec3 origin0 = prismC - sunDir * (prad + 2.0f);

        // Pass 1: trace photons, collect receiver deposits.
        struct Dep { float x, z; astroray::XYZ c; };
        std::vector<Dep> deps; deps.reserve(photons_ / 2);
        std::vector<float> ys;
        const float lmin = 380.0f, lmax = 720.0f;
        for (int p = 0; p < photons_; ++p) {
            float lambda = lmin + (lmax - lmin) * u01(gen);
            float ior = mat->iorAt(lambda);
            if (ior <= 1.0f) continue;
            float ra = (u01(gen) * 2.0f - 1.0f) * prad;
            float rb = (u01(gen) * 2.0f - 1.0f) * prad;
            Vec3 o = origin0 + fu * ra + fv * rb;
            Vec3 d = sunDir;
            // entry face (air -> glass)
            Vec3 n1; float t1 = nearestCaster(tris, o, d, n1);
            if (t1 < 0) continue;
            Vec3 p1 = o + d * t1;
            float tr = fresnelT(d.dot(n1), ior);
            Vec3 d1; if (!refract(d, n1, 1.0f / ior, d1)) continue;
            // exit face (glass -> air)
            Vec3 n2; float t2 = nearestCaster(tris, p1 + d1 * 1e-4f, d1, n2);
            if (t2 < 0) continue;
            Vec3 p2 = p1 + d1 * (t2 + 1e-4f);
            tr *= fresnelT(d1.dot(n2), ior);
            Vec3 d2; if (!refract(d1, n2, ior, d2)) continue;
            // trace to the receiver (first non-caster, non-emissive surface)
            HitRecord rec;
            if (!bvh->hit(Ray(p2 + d2 * 1e-3f, d2), 1e-3f,
                          std::numeric_limits<float>::max(), rec)) continue;
            if (!rec.material || rec.material->isEmissive()) continue;
            if (rec.hitObject && rec.hitObject->isCausticCaster()) continue;
            if (rec.normal.y < 0.7f) continue;            // horizontal receiver only
            astroray::XYZ cmf = astroray::cieCmf1964_10deg(lambda);
            deps.push_back({rec.point.x, rec.point.z,
                            {cmf.X * tr, cmf.Y * tr, cmf.Z * tr}});
            ys.push_back(rec.point.y);
        }
        if (deps.size() < 16) return;

        // Receiver plane + (x,z) bounds from the deposits.
        std::sort(ys.begin(), ys.end());
        floorY_ = ys[ys.size() / 2];
        float x0 = 1e30f, x1 = -1e30f, z0 = 1e30f, z1 = -1e30f;
        for (const auto& d : deps) {
            x0 = std::min(x0, d.x); x1 = std::max(x1, d.x);
            z0 = std::min(z0, d.z); z1 = std::max(z1, d.z);
        }
        float mx = (x1 - x0) * 0.08f + 1e-3f, mz = (z1 - z0) * 0.08f + 1e-3f;
        gx0_ = x0 - mx; gx1_ = x1 + mx; gz0_ = z0 - mz; gz1_ = z1 + mz;
        gn_ = std::max(16, gridRes_);
        grid_.assign((size_t)gn_ * gn_, astroray::XYZ{});

        // Bilinear splat of each photon's CIE-weighted flux into the grid.
        for (const auto& d : deps) {
            float fx = (d.x - gx0_) / (gx1_ - gx0_) * (gn_ - 1);
            float fz = (d.z - gz0_) / (gz1_ - gz0_) * (gn_ - 1);
            int i0 = (int)fx, j0 = (int)fz;
            if (i0 < 0 || i0 >= gn_ - 1 || j0 < 0 || j0 >= gn_ - 1) continue;
            float tx = fx - i0, tz = fz - j0;
            auto spl = [&](int i, int j, float w) {
                grid_[idx(i, j)].X += d.c.X * w; grid_[idx(i, j)].Y += d.c.Y * w;
                grid_[idx(i, j)].Z += d.c.Z * w; };
            spl(i0, j0, (1 - tx) * (1 - tz)); spl(i0 + 1, j0, tx * (1 - tz));
            spl(i0, j0 + 1, (1 - tx) * tz);   spl(i0 + 1, j0 + 1, tx * tz);
            depositedFlux_ += d.c.Y;
        }
        // Per-cell area normalization (irradiance = flux / cell area / photon density)
        // then auto-scale so the brightest band cell maps to ~boost (brightness is
        // arbitrary for the hue gate; this keeps it resolution/count-independent).
        float peak = 0.0f;
        for (const auto& c : grid_) peak = std::max(peak, c.Y);
        if (peak <= 0.0f) return;
        float s = boost_ / peak;
        for (auto& c : grid_) { c.X *= s; c.Y *= s; c.Z *= s; }
        ready_ = true;
    }
};

ASTRORAY_REGISTER_INTEGRATOR("light_tracer_caustic", LightTracerCaustic)
