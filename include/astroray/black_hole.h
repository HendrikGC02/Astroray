#pragma once
#include "../raytracer.h"
#include "metric.h"
#include "accretion_disk.h"
#include "gr_integrator.h"
#include "spectral.h"
#include <memory>
#include <random>
#include <cmath>

// ============================================================================
// BlackHole — a Hittable that represents a GR influence sphere.
// When hit, traceGR() runs the RK45 integrator and returns a remapped
// direction plus any disk emission.  The path tracer uses isGRObject() to
// route the hit here instead of the normal BSDF evaluation.
// ============================================================================

class BlackHole : public Hittable {
private:
    Vec3   position;         // world-space centre
    double mass;             // solar masses (for display only)
    double influenceRadius;  // world-space radius of influence sphere
    double r_obs_M;          // influence radius in geometrized units (M)
    double worldToGR;        // scale: world unit → BL unit  (= r_obs_M / influenceRadius)
    double inclination;      // observer inclination in radians (from spin axis)

    std::unique_ptr<SchwarzschildMetric> metric;
    std::unique_ptr<NovikovThorneDisk>   disk;

    // Exposure scale for disk emission (tuned so disk is visible but not overexposed)
    float exposureScale = 1e-26f;  // raw Planck values are huge; scale to [0,1]

    // Convert a world-space point (relative to BH centre) to BL spherical coords.
    // Y-up convention: x = r sinθ cosφ, y = r cosθ, z = r sinθ sinφ
    static void cartesianToBL(double cx, double cy, double cz,
                               double& r, double& theta, double& phi)
    {
        r     = std::sqrt(cx*cx + cy*cy + cz*cz);
        if (r < 1e-15) { theta = GR_PI/2.0; phi = 0.0; return; }
        theta = std::acos(std::clamp(cy / r, -1.0, 1.0));
        phi   = std::atan2(cz, cx);
    }

    // Build initial GeodesicState from a hit point + direction in world space.
    GeodesicState buildInitialState(const Vec3& hitPoint, const Vec3& dir) const {
        // Translate to BH-centred coords and scale to geometrized units
        double cx = double(hitPoint.x - position.x) * worldToGR;
        double cy = double(hitPoint.y - position.y) * worldToGR;
        double cz = double(hitPoint.z - position.z) * worldToGR;

        double r, theta, phi;
        cartesianToBL(cx, cy, cz, r, theta, phi);

        double M     = metric->M;
        double f     = 1.0 - 2.0 * M / r;
        double sin_th = std::sin(theta);
        if (std::abs(sin_th) < 1e-10) sin_th = (sin_th >= 0 ? 1e-10 : -1e-10);
        double sin2  = sin_th * sin_th;
        double r2    = r * r;

        // Direction vector components in Cartesian
        double dx = double(dir.x);
        double dy = double(dir.y);
        double dz = double(dir.z);

        double cos_th = std::cos(theta);
        double cos_ph = std::cos(phi);
        double sin_ph = std::sin(phi);

        // Convert Cartesian direction to (dr, dθ, dφ) via inverse Jacobian
        // x = r sinθ cosφ, y = r cosθ, z = r sinθ sinφ
        double dr  = dx * sin_th*cos_ph + dy * cos_th + dz * sin_th*sin_ph;
        double dth = (dx * cos_th*cos_ph - dy * sin_th + dz * cos_th*sin_ph) / r;
        double dph = (-dx * sin_ph + dz * cos_ph) / (r * sin_th);

        // BL coordinate momenta from contravariant velocities
        double p_r   = dr / f;
        double p_th  = r2 * dth;
        double p_phi = r2 * sin2 * dph;

        // Null condition → p_t
        double L2    = p_th * p_th + p_phi * p_phi / sin2;
        double pt2   = f * f * p_r * p_r + f * L2 / r2;
        double p_t   = -std::sqrt(std::max(pt2, 0.0));

        GeodesicState s;
        s.t      = 0.0;
        s.r      = r;
        s.theta  = theta;
        s.phi    = phi;
        s.p_t    = p_t;
        s.p_r    = p_r;
        s.p_theta = p_th;
        s.p_phi  = p_phi;
        return s;
    }

public:
    BlackHole(Vec3 pos, double mass_solar, double influence_r,
              double disk_outer_M = 30.0, double mdot = 1.0,
              double incl_deg = 75.0)
        : position(pos), mass(mass_solar), influenceRadius(influence_r)
    {
        r_obs_M   = 100.0;
        worldToGR = r_obs_M / double(influence_r);

        metric = std::make_unique<SchwarzschildMetric>(1.0);
        disk   = std::make_unique<NovikovThorneDisk>(metric.get(), disk_outer_M, mdot);

        inclination  = incl_deg * GR_PI / 180.0;
        exposureScale = 1e-26f;
    }

    // --------------- Hittable interface ---------------

    bool isGRObject() const override { return true; }

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 oc     = r.origin - position;
        float a     = r.direction.length2();
        float half_b = oc.dot(r.direction);
        float c     = oc.length2() - float(influenceRadius * influenceRadius);
        float disc  = half_b * half_b - a * c;
        if (disc < 0) return false;

        float sqrtd = std::sqrt(disc);
        float root  = (-half_b - sqrtd) / a;
        if (root < tMin || root > tMax) {
            root = (-half_b + sqrtd) / a;
            if (root < tMin || root > tMax) return false;
        }

        rec.t      = root;
        rec.point  = r.at(root);
        Vec3 outN  = (rec.point - position) / float(influenceRadius);
        rec.setFaceNormal(r, outN);
        rec.hitObject = this;
        return true;
    }

    bool boundingBox(AABB& box) const override {
        float ri = float(influenceRadius);
        box = AABB(position - Vec3(ri), position + Vec3(ri));
        return true;
    }

    // --------------- GR rendering via virtual dispatch ---------------

    __attribute__((noinline))
    GRResult traceGR(const Ray& incomingRay, std::mt19937& gen) const override {
        // Minimal result: treat as captured (black hole shadow)
        GRResult result;
        result.captured     = false;
        result.hasEmission  = false;
        result.color        = Vec3(0);
        result.exitDirection = Vec3(0, 0, 1);

        // Find the entry t on the influence sphere
        Vec3 oc      = incomingRay.origin - position;
        float a      = incomingRay.direction.length2();
        float half_b = oc.dot(incomingRay.direction);
        float c_     = oc.length2() - float(influenceRadius * influenceRadius);
        float disc   = half_b * half_b - a * c_;
        if (disc < 0.0f || a < 1e-15f) return result;
        float sqrtd   = std::sqrt(disc);
        float entry_t = (-half_b - sqrtd) / a;
        if (entry_t < 0.001f) entry_t = (-half_b + sqrtd) / a;
        if (entry_t < 0.001f) return result;

        Vec3 hitPoint = incomingRay.at(entry_t);

        GeodesicState s0 = buildInitialState(hitPoint, incomingRay.direction);

        IntegrationResult ir = integrateGeodesic(
            *metric, disk.get(), s0, inclination,
            /*maxSteps=*/5000, /*h_init=*/0.5,
            /*atol=*/1e-8, /*rtol=*/1e-6,
            /*r_max=*/r_obs_M * 1.05
        );

        if (ir.captured) {
            result.captured = true;
            return result;
        }

        // Disk emission
        if (ir.nCrossings > 0) {
            SpectralSample spec = sampleHeroWavelengths(gen);
            for (int ci = 0; ci < ir.nCrossings; ++ci) {
                const DiskCrossing& dc = ir.crossings[ci];
                if (!dc.valid) continue;
                double T = disk->temperatureAt(dc.r);
                if (T <= 0.0) continue;
                for (int wi = 0; wi < 4; ++wi) {
                    double lam_emit = spec.wavelengths[wi];
                    double B  = planck(lam_emit, T);
                    double g4 = dc.g * dc.g * dc.g * dc.g;
                    spec.radiance[wi] += g4 * B;
                }
            }
            Vec3 rgb = spectralToRGB(spec, exposureScale);
            rgb.x = std::max(0.0f, rgb.x);
            rgb.y = std::max(0.0f, rgb.y);
            rgb.z = std::max(0.0f, rgb.z);
            if (rgb.x > 0 || rgb.y > 0 || rgb.z > 0) {
                result.color       = rgb;
                result.hasEmission = true;
            }
        }

        // Exit direction
        if (ir.escaped) {
            Vec3 d = ir.exitDirection;
            if (std::isfinite(d.x) && std::isfinite(d.y) && std::isfinite(d.z)
                && d.length2() > 1e-10f) {
                result.exitDirection = d.normalized();
            }
        }

        return result;
    }
};
