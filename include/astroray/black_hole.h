#pragma once
#include "../raytracer.h"
#include "metric.h"
#include "accretion_disk.h"
#include "emission.h"
#include "gr_integrator.h"
#include "spectral.h"
#include "astroray/register.h"
#include <memory>
#include <random>
#include <cmath>
#include <limits>
#include <vector>

namespace astroray {

// Source: Rybicki & Lightman, "Radiative Processes in Astrophysics", §4.9,
// "Invariant Phase Volumes and Specific Intensity" (1979), DOI:10.1002/9783527618170;
// Cunningham, "The Effects of Redshifts and Focusing on the Spectrum of an
// Accretion Disk around a Kerr Black Hole", ApJ 202 (1975), DOI:10.1086/154033.
// Reference impl: AFD-Illinois/ipole@7f7a482cf91125aeeeb9c431485bba680e8941d7
// — src/radiation.c (Planck-frequency convention and fluid-frame frequency).
// License: BSD-3-Clause (compatible with Astroray's MIT LICENSE); no code copied.
// I_lambda,obs(lambda_obs) = g^5 B_lambda(g lambda_obs, T), g = nu_obs / nu_em.
inline double thinDiskEmittedWavelengthNm(double lambda_obs_nm, double g) {
    if (!gr_isfinite(lambda_obs_nm) || !gr_isfinite(g) ||
        lambda_obs_nm <= 0.0 || g <= 0.0) {
        return 0.0;
    }
    const double lambda_emit_nm = g * lambda_obs_nm;
    return gr_isfinite(lambda_emit_nm) && lambda_emit_nm > 0.0
        ? lambda_emit_nm : 0.0;
}

inline double thinDiskInvariantTransferWavelength(
        double lambda_obs_nm, double temperature_K, double g) {
    const double lambda_emit_nm = thinDiskEmittedWavelengthNm(lambda_obs_nm, g);
    if (lambda_emit_nm <= 0.0 || !gr_isfinite(temperature_K) || temperature_K <= 0.0) {
        return 0.0;
    }
    const double B_lambda = planck(lambda_emit_nm, temperature_K);
    if (!gr_isfinite(B_lambda) || B_lambda <= 0.0) return 0.0;
    const double g2 = g * g;
    const double g5 = g2 * g2 * g;
    const double observed = g5 * B_lambda;
    return gr_isfinite(observed) && observed > 0.0 ? observed : 0.0;
}

inline double thinDiskNormalizedTransferWavelength(
        double lambda_obs_nm, double temperature_K, double g,
        double exposure_scale, double wavelength_span_nm) {
    if (!gr_isfinite(exposure_scale) || !gr_isfinite(wavelength_span_nm) ||
        exposure_scale <= 0.0 || wavelength_span_nm <= 0.0) {
        return 0.0;
    }
    const double observed = thinDiskInvariantTransferWavelength(
        lambda_obs_nm, temperature_K, g);
    const double scaled = observed * exposure_scale / wavelength_span_nm;
    return gr_isfinite(scaled) && scaled > 0.0 ? scaled : 0.0;
}

// Preserve the already accumulated finite value when a physically computed
// double cannot be represented in SampledSpectrum's float storage, or adding a
// representable value would overflow it. This is a storage guard, not a
// radiance cap; the thin-disk transfer itself remains unclamped.
inline float accumulateFiniteThinDiskEmission(float accumulated, double contribution) {
    if (!gr_isfinite(static_cast<double>(accumulated)) || accumulated < 0.0f) return 0.0f;
    const double max_float = static_cast<double>(std::numeric_limits<float>::max());
    if (!gr_isfinite(contribution) || contribution <= 0.0 || contribution > max_float)
        return accumulated;
    const float contribution_float = static_cast<float>(contribution);
    if (!gr_isfinite(static_cast<double>(contribution_float)) ||
        contribution_float > std::numeric_limits<float>::max() - accumulated) {
        return accumulated;
    }
    return accumulated + contribution_float;
}

} // namespace astroray

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

    double spin;             // Kerr a/M; 0 selects SchwarzschildMetric (pkg281)

    std::shared_ptr<Metric> metric;
    std::unique_ptr<NovikovThorneDisk>   disk;
    std::vector<std::shared_ptr<Emission>> emissions;

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

        if (spin != 0.0) {
            // pkg281 Kerr: p_i = g_ii v^i, with v^phi taken relative to the
            // frame-dragging ZAMO (p_phi = g_phiphi v^phi; Bardeen, Press &
            // Teukolsky 1972 §III). p_t solves g^{mu nu} p_mu p_nu = 0 on the
            // PAST-directed root (p^t < 0): the camera ray runs opposite to the
            // photon, so it is the photon geodesic with lambda reversed. A
            // future-directed root would trace the a -> -a spacetime (mirrored
            // shadow). At a=0 only the sign of p_t differs from the branch
            // above, and p_t enters the a=0 dynamics squared.
            const double a2     = spin * spin;
            const double sigma  = r2 + a2 * cos_th * cos_th;
            const double delta  = r2 - 2.0 * M * r + a2;
            const double A_     = (r2 + a2) * (r2 + a2) - delta * a2 * sin2;
            p_r   = sigma / delta * dr;
            p_th  = sigma * dth;
            p_phi = A_ / sigma * sin2 * dph;
            const double g_tt  = -A_ / (sigma * delta);
            const double g_tph = -2.0 * M * spin * r / (sigma * delta);
            const double g_phph = (delta - a2 * sin2) / (sigma * delta * sin2);
            const double C = delta / sigma * p_r * p_r + p_th * p_th / sigma
                           + g_phph * p_phi * p_phi;
            const double b = g_tph * p_phi;
            p_t = (-b - std::sqrt(std::max(b * b - g_tt * C, 0.0))) / g_tt;
        }

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

    struct TraceState {
        bool valid = false;
        IntegrationResult integration{};
    };

    TraceState integrateIncomingRay(const Ray& incomingRay) const {
        TraceState state;

        Vec3 oc      = incomingRay.origin - position;
        float a      = incomingRay.direction.length2();
        float half_b = oc.dot(incomingRay.direction);
        float c_     = oc.length2() - float(influenceRadius * influenceRadius);
        float disc   = half_b * half_b - a * c_;
        if (disc < 0.0f || a < 1e-15f) return state;
        float sqrtd   = std::sqrt(disc);
        float entry_t = (-half_b - sqrtd) / a;
        if (entry_t < 0.001f) entry_t = (-half_b + sqrtd) / a;
        if (entry_t < 0.001f) return state;

        Vec3 hitPoint = incomingRay.at(entry_t);
        GeodesicState s0 = buildInitialState(hitPoint, incomingRay.direction);
        state.integration = integrateGeodesic(
            *metric, disk.get(), s0, inclination,
            /*maxSteps=*/5000, /*h_init=*/0.5,
            /*atol=*/1e-8, /*rtol=*/1e-6,
            /*r_max=*/r_obs_M * 1.05
        );
        state.valid = true;
        return state;
    }

    Vec3 sanitizedExitDirection(const IntegrationResult& ir) const {
        if (ir.escaped) {
            Vec3 d = ir.exitDirection;
            if (gr_isfinite(static_cast<double>(d.x)) &&
                gr_isfinite(static_cast<double>(d.y)) &&
                gr_isfinite(static_cast<double>(d.z)) &&
                d.length2() > 1e-10f) {
                return d.normalized();
            }
        }
        return Vec3(0, 0, 1);
    }

    astroray::SampledSpectrum diskEmissionSpectral(
            const IntegrationResult& ir,
            const astroray::SampledWavelengths& lambdas) const {
        astroray::SampledSpectrum emission(0.0f);
        if (ir.nCrossings <= 0) return emission;

        constexpr double span =
            double(astroray::kLambdaMax - astroray::kLambdaMin);
        for (int ci = 0; ci < ir.nCrossings; ++ci) {
            const DiskCrossing& dc = ir.crossings[ci];
            if (!dc.valid) continue;
            double T = disk->temperatureAt(dc.r);
            if (T <= 0.0 || !gr_isfinite(T)) continue;
            if (!gr_isfinite(dc.g) || dc.g <= 0.0) continue;
            const double g = dc.g;
            for (int wi = 0; wi < astroray::kSpectrumSamples; ++wi) {
                const double scaled = astroray::thinDiskNormalizedTransferWavelength(
                    double(lambdas.lambda(wi)), T, g, double(exposureScale), span);
                if (!gr_isfinite(scaled) || scaled <= 0.0) continue;
                emission[wi] = astroray::accumulateFiniteThinDiskEmission(
                    emission[wi], scaled);
            }
        }
        return emission;
    }

    astroray::SampledSpectrum volumetricEmissionSpectral(
            const Ray& incomingRay,
            const astroray::SampledWavelengths& lambdas) const {
        astroray::SampledSpectrum emission(0.0f);
        if (emissions.empty()) return emission;

        Vec3 oc = incomingRay.origin - position;
        float a = incomingRay.direction.length2();
        float half_b = oc.dot(incomingRay.direction);
        float c = oc.length2() - float(influenceRadius * influenceRadius);
        float disc = half_b * half_b - a * c;
        if (disc < 0.0f || a < 1e-15f) return emission;
        float sqrtd = std::sqrt(disc);
        float t0 = (-half_b - sqrtd) / a;
        float t1 = (-half_b + sqrtd) / a;
        if (t1 < 0.001f) return emission;
        t0 = std::max(t0, 0.001f);
        if (t1 <= t0) return emission;

        constexpr int kSteps = 96;
        const double dt = double(t1 - t0) / double(kSteps);
        const double ds_cm = dt * worldToGR;
        Vec3 photonDir = (-incomingRay.direction).normalized();

        for (int i = 0; i < kSteps; ++i) {
            const float t = float(double(t0) + (double(i) + 0.5) * dt);
            Vec3 p = incomingRay.at(t);
            Vec3 rel = p - position;
            Vec3 pos_M(float(double(rel.x) * worldToGR),
                       float(double(rel.y) * worldToGR),
                       float(double(rel.z) * worldToGR));
            for (const auto& e : emissions) {
                if (!e) continue;
                emission += e->integrateSegment(pos_M, photonDir, lambdas, ds_cm);
            }
        }
        return emission;
    }

public:
    BlackHole(Vec3 pos, double mass_solar, double influence_r,
              double disk_outer_M = 30.0, double mdot = 1.0,
              double incl_deg = 75.0, double r_obs_M_in = 100.0,
              double spin_a = 0.0)
        : position(pos), mass(mass_solar), influenceRadius(influence_r),
          spin(gr_isfinite(spin_a) ? std::clamp(spin_a, -0.998, 0.998) : 0.0)
    {
        // pkg107: r_obs_M_in controls the world-to-GR scale factor.
        // Default 100.0 preserves pkg40-pkg44 baselines. Smaller values
        // (e.g. 20.0) shrink the world-to-GR scale and grow the visible
        // photon-orbit shadow at the same camera distance — required for
        // BH-shadow visualisation scenes (pkg104 gr-*).
        r_obs_M   = r_obs_M_in > 0.0 ? r_obs_M_in : 100.0;
        worldToGR = r_obs_M / double(influence_r);

        // pkg281: honour spin. Kerr lives in plugins/metrics/kerr.cpp (same
        // |a| <= 0.998 clamp as above).
        if (spin != 0.0) {
            astroray::ParamDict kp;
            kp.set("M", 1.0f);
            kp.set("a", static_cast<float>(spin));
            metric = astroray::MetricRegistry::instance().create("kerr", kp);
        } else {
            metric = std::make_shared<SchwarzschildMetric>(1.0);
        }
        disk   = std::make_unique<NovikovThorneDisk>(metric.get(), disk_outer_M, mdot);

        inclination  = incl_deg * GR_PI / 180.0;
        // Matched to NovikovThorneDisk::TARGET_PEAK_TEMP = 20 000 K:
        // Planck at 500 nm → ~2e14 W/(m²·sr·m); CIE pipeline with 4 stratified
        // samples → Y ≈ 1.8e13; exposureScale = 1/1.8e13 ≈ 5.5e-14 → Y ≈ 1.
        exposureScale = 5e-14f;
    }

    void addVolumetricEmission(std::shared_ptr<Emission> emission) {
        if (emission) emissions.push_back(std::move(emission));
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
        rec.objectPoint = rec.point;
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

    ASTRORAY_NOINLINE
    GRResult traceGR(const Ray& incomingRay, std::mt19937& gen) const override {
        // Minimal result: treat as captured (black hole shadow)
        GRResult result;
        result.captured     = false;
        result.hasEmission  = false;
        result.color        = Vec3(0);
        result.exitDirection = Vec3(0, 0, 1);

        TraceState trace = integrateIncomingRay(incomingRay);
        if (!trace.valid) return result;
        const IntegrationResult& ir = trace.integration;

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
                if (T <= 0.0 || !gr_isfinite(T)) continue;
                if (!gr_isfinite(dc.g) || dc.g <= 0.0) continue;
                const double g = dc.g;
                for (int wi = 0; wi < 4; ++wi) {
                    const double contrib = astroray::thinDiskInvariantTransferWavelength(
                        spec.wavelengths[wi], T, g);
                    if (!gr_isfinite(contrib) || contrib <= 0.0) continue;
                    spec.radiance[wi] += contrib;
                }
            }
            Vec3 rgb = spectralToRGB(spec, exposureScale);
            rgb.x = gr_isfinite(static_cast<double>(rgb.x)) ? std::max(0.0f, rgb.x) : 0.0f;
            rgb.y = gr_isfinite(static_cast<double>(rgb.y)) ? std::max(0.0f, rgb.y) : 0.0f;
            rgb.z = gr_isfinite(static_cast<double>(rgb.z)) ? std::max(0.0f, rgb.z) : 0.0f;
            if (rgb.x > 0 || rgb.y > 0 || rgb.z > 0) {
                result.color       = rgb;
                result.hasEmission = true;
            }
        }

        if (!emissions.empty()) {
            SpectralSample spec = sampleHeroWavelengths(gen);
            astroray::SampledWavelengths lambdas =
                astroray::SampledWavelengths::sampleUniform(0.5f);
            astroray::SampledSpectrum vol =
                volumetricEmissionSpectral(incomingRay, lambdas);
            for (int wi = 0; wi < astroray::kSpectrumSamples; ++wi) {
                spec.radiance[wi] += double(vol[wi]);
            }
            Vec3 rgb = spectralToRGB(spec, exposureScale);
            rgb.x = gr_isfinite(static_cast<double>(rgb.x)) ? std::max(0.0f, rgb.x) : 0.0f;
            rgb.y = gr_isfinite(static_cast<double>(rgb.y)) ? std::max(0.0f, rgb.y) : 0.0f;
            rgb.z = gr_isfinite(static_cast<double>(rgb.z)) ? std::max(0.0f, rgb.z) : 0.0f;
            if (rgb.x > 0 || rgb.y > 0 || rgb.z > 0) {
                result.color += rgb;
                result.hasEmission = true;
            }
        }

        result.exitDirection = sanitizedExitDirection(ir);

        return result;
    }

    ASTRORAY_NOINLINE
    GRSpectralResult traceGRSpectral(
            const Ray& incomingRay,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& /*gen*/) const override {
        GRSpectralResult result;
        result.emission = astroray::SampledSpectrum(0.0f);
        result.captured = false;
        result.hasEmission = false;
        result.exitDirection = Vec3(0, 0, 1);

        TraceState trace = integrateIncomingRay(incomingRay);
        if (!trace.valid) return result;
        const IntegrationResult& ir = trace.integration;

        if (ir.captured) {
            result.captured = true;
            return result;
        }

        // pkg99 (2026-05-22): exposureScale (5e-14) is a Novikov-Thorne disk
        // brightness normalization (raw Planck values ~2e14 → ~1). It does NOT
        // belong on volumetric emissions — those have their own intensity_scale
        // parameters carrying any unit conversion they need. Multiplying by
        // 5e-14 here made ADAF effectively invisible (ON==OFF) and forced jet
        // scenes to use intensity_scale ~1e28 as empirical compensation. Scene
        // files updated separately to use physically-meaningful scale values.
        result.emission = diskEmissionSpectral(ir, lambdas)
                        + volumetricEmissionSpectral(incomingRay, lambdas);
        result.hasEmission = !result.emission.isZero();
        result.exitDirection = sanitizedExitDirection(ir);
        // pkg67: expose the integrator's frequency-shift factor so the caller
        // can redshift the exiting ray's carried wavelengths. For
        // Schwarzschild p_t is conserved → 1.0; pkg40 Kerr will compute a
        // non-trivial value.
        result.frequencyShift = gr_isfinite(ir.frequencyShift) && ir.frequencyShift > 0.0
                              ? ir.frequencyShift : 1.0;
        return result;
    }
};
