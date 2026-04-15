#pragma once
#include "gr_types.h"
#include "metric.h"
#include "accretion_disk.h"
#include "../raytracer.h"   // for Vec3
#include <cmath>
#include <algorithm>
#include <random>

// ============================================================================
// Dormand-Prince RK45 adaptive integrator for geodesics.
// Direct port of the validated Python integrate_geodesics() function,
// operating on a single ray (C++ uses OpenMP over pixels, not NumPy).
// ============================================================================

static constexpr int MAX_DISK_CROSSINGS = 8;

struct IntegrationResult {
    GeodesicState finalState;
    DiskCrossing  crossings[MAX_DISK_CROSSINGS];
    int           nCrossings;    // actual count
    bool escaped;
    bool captured;
    Vec3 exitDirection;    // Euclidean (float) direction on escape
    double frequencyShift; // cumulative g factor (p_t is conserved → 1.0 for Schwarzschild)
};

// Dormand-Prince Butcher tableau — identical to the Python version
static constexpr double DP_A[6][5] = {
    {1.0/5.0,          0,              0,           0,          0},
    {3.0/40.0,         9.0/40.0,       0,           0,          0},
    {44.0/45.0,       -56.0/15.0,      32.0/9.0,    0,          0},
    {19372.0/6561.0,  -25360.0/2187.0, 64448.0/6561.0, -212.0/729.0, 0},
    {9017.0/3168.0,   -355.0/33.0,     46732.0/5247.0,  49.0/176.0, -5103.0/18656.0}
};
static constexpr double DP_C5[7] = {
    35.0/384.0, 0.0, 500.0/1113.0, 125.0/192.0, -2187.0/6784.0, 11.0/84.0, 0.0
};
static constexpr double DP_C4[7] = {
    5179.0/57600.0, 0.0, 7571.0/16695.0, 393.0/640.0,
    -92097.0/339200.0, 187.0/2100.0, 1.0/40.0
};

// Max component of a state (for error normalisation)
inline double maxAbsState(const GeodesicState& s) {
    double vals[8] = {std::abs(s.t),   std::abs(s.r),     std::abs(s.theta), std::abs(s.phi),
                      std::abs(s.p_t), std::abs(s.p_r),   std::abs(s.p_theta), std::abs(s.p_phi)};
    double m = 1e-12;
    for (double v : vals) if (v > m) m = v;
    return m;
}

// Max component of error state
inline double maxAbsError(const GeodesicState& err) {
    double vals[8] = {std::abs(err.t),   std::abs(err.r),   std::abs(err.theta), std::abs(err.phi),
                      std::abs(err.p_t), std::abs(err.p_r), std::abs(err.p_theta), std::abs(err.p_phi)};
    double m = 0.0;
    for (double v : vals) if (v > m) m = v;
    return m;
}

// DP stage computation helper
inline GeodesicState dpStage(const Metric& metric, const GeodesicState& s0,
                               double h, const GeodesicState k[], int nk, const double coeff[])
{
    GeodesicState s = s0;
    for (int i = 0; i < nk; ++i) s = s + h * coeff[i] * k[i];
    return metric.geodesic_rhs(s);
}

// Convert final GeodesicState Hamiltonian velocities to a Euclidean 3-vector.
// Uses the BL coordinate velocities (dr/dλ, dθ/dλ, dφ/dλ) → Cartesian.
// Y-up convention: x=r sinθ cosφ, y=r cosθ, z=r sinθ sinφ
inline Vec3 blToCartesianDir(const GeodesicState& s, const GeodesicState& ds) {
    // Reject NaN/Inf state outright — return a safe placeholder direction.
    if (!gr_isfinite(s.r)     || !gr_isfinite(s.theta) || !gr_isfinite(s.phi) ||
        !gr_isfinite(ds.r)    || !gr_isfinite(ds.theta) || !gr_isfinite(ds.phi)) {
        return Vec3(0, 0, 1);
    }

    double r     = s.r;
    double theta = s.theta;
    double phi   = s.phi;

    double sin_th = std::sin(theta);
    double cos_th = std::cos(theta);
    double sin_ph = std::sin(phi);
    double cos_ph = std::cos(phi);

    // dr/dλ, dθ/dλ, dφ/dλ from Hamiltonian (already computed in ds)
    double dr  = ds.r;
    double dth = ds.theta;
    double dph = ds.phi;

    // Jacobian: d/dλ (r sinθ cosφ, r cosθ, r sinθ sinφ)
    double dx = dr * sin_th * cos_ph + r * cos_th * cos_ph * dth - r * sin_th * sin_ph * dph;
    double dy = dr * cos_th          - r * sin_th * dth;
    double dz = dr * sin_th * sin_ph + r * cos_th * sin_ph * dth + r * sin_th * cos_ph * dph;

    if (!gr_isfinite(dx) || !gr_isfinite(dy) || !gr_isfinite(dz)) return Vec3(0, 0, 1);

    float len = float(std::sqrt(dx*dx + dy*dy + dz*dz));
    if (len < 1e-15f || !gr_isfinite(double(len))) return Vec3(0, 0, 1);
    return Vec3(float(dx)/len, float(dy)/len, float(dz)/len);
}

ASTRORAY_NOINLINE IntegrationResult integrateGeodesic(
    const Metric&            metric,
    const NovikovThorneDisk* disk,       // nullptr if no disk
    const GeodesicState&     s_init,
    double                   inclination,  // observer inclination (radians)
    int                      maxSteps = 5000,
    double                   h_init   =  0.5,   // positive = forward integration
    double                   atol     = 1e-8,
    double                   rtol     = 1e-6,
    double                   r_max    = 200.0
) {
    GeodesicState s = s_init;
    IntegrationResult result;
    result.escaped        = false;
    result.captured       = false;
    result.nCrossings     = 0;
    result.frequencyShift = 1.0;
    result.exitDirection  = Vec3(0, 0, 1);

    double h = h_init;
    double prev_theta = s.theta;
    for (int step = 0; step < maxSteps; ++step) {
        // --- DP45 stages ---
        GeodesicState k[7];
        k[0] = metric.geodesic_rhs(s);

        // Stage 1
        GeodesicState s1 = s + h * (1.0/5.0) * k[0];
        k[1] = metric.geodesic_rhs(s1);

        // Stage 2
        GeodesicState s2 = s + h * (3.0/40.0 * k[0] + 9.0/40.0 * k[1]);
        k[2] = metric.geodesic_rhs(s2);

        // Stage 3
        GeodesicState s3 = s + h * (44.0/45.0 * k[0] + -56.0/15.0 * k[1] + 32.0/9.0 * k[2]);
        k[3] = metric.geodesic_rhs(s3);

        // Stage 4
        GeodesicState s4 = s + h * (19372.0/6561.0 * k[0] + -25360.0/2187.0 * k[1] +
                                     64448.0/6561.0 * k[2] + -212.0/729.0 * k[3]);
        k[4] = metric.geodesic_rhs(s4);

        // Stage 5
        GeodesicState s5 = s + h * (9017.0/3168.0 * k[0] + -355.0/33.0 * k[1] +
                                     46732.0/5247.0 * k[2] + 49.0/176.0 * k[3] +
                                     -5103.0/18656.0 * k[4]);
        k[5] = metric.geodesic_rhs(s5);

        // 5th-order solution
        GeodesicState s_new = s + h * (DP_C5[0]*k[0] + DP_C5[2]*k[2] + DP_C5[3]*k[3] +
                                        DP_C5[4]*k[4] + DP_C5[5]*k[5]);
        k[6] = metric.geodesic_rhs(s_new);

        // 4th-order solution for error estimate
        GeodesicState s4th = s + h * (DP_C4[0]*k[0] + DP_C4[2]*k[2] + DP_C4[3]*k[3] +
                                       DP_C4[4]*k[4] + DP_C4[5]*k[5] + DP_C4[6]*k[6]);

        // Error estimate
        GeodesicState err;
        err.t      = s_new.t      - s4th.t;
        err.r      = s_new.r      - s4th.r;
        err.theta  = s_new.theta  - s4th.theta;
        err.phi    = s_new.phi    - s4th.phi;
        err.p_t    = s_new.p_t    - s4th.p_t;
        err.p_r    = s_new.p_r    - s4th.p_r;
        err.p_theta= s_new.p_theta- s4th.p_theta;
        err.p_phi  = s_new.p_phi  - s4th.p_phi;

        double e_norm  = maxAbsError(err);
        double s_norm  = maxAbsState(s_new);
        double err_rel = e_norm / (atol + rtol * s_norm);

        // Step size adaptation
        double factor = 0.9 * std::pow(err_rel + 1e-15, -0.2);
        factor = std::clamp(factor, 0.2, 5.0);

        if (err_rel > 1.0) {
            // Reject step, reduce h and retry
            h *= factor;
            // Keep h positive (forward integration) with a safe minimum
            if (h < 0.0) h = -h;
            h = std::clamp(h, 0.001, 50.0);
            continue;
        }

        // Safety: detect NaN/Inf in any component of the accepted step → treat as captured
        if (!gr_isfinite(s_new.t)     || !gr_isfinite(s_new.r)     ||
            !gr_isfinite(s_new.theta) || !gr_isfinite(s_new.phi)   ||
            !gr_isfinite(s_new.p_t)   || !gr_isfinite(s_new.p_r)   ||
            !gr_isfinite(s_new.p_theta) || !gr_isfinite(s_new.p_phi)) {
            result.captured   = true;
            result.finalState = s;
            return result;
        }

        // Accept step
        double curr_theta = s_new.theta;

        // --- Disk crossing detection ---
        // θ crosses π/2 (equatorial plane) between prev and current
        if (disk != nullptr && result.nCrossings < MAX_DISK_CROSSINGS) {
            double p_half = GR_PI / 2.0;
            double dp  = prev_theta - p_half;
            double dc_ = curr_theta - p_half;
            if (dp * dc_ < 0.0 && gr_isfinite(s.r) && gr_isfinite(s_new.r)) {
                double frac = std::abs(dp) / (std::abs(dp) + std::abs(dc_) + 1e-30);
                double r_cross   = s.r   + frac * (s_new.r   - s.r);
                double phi_cross = s.phi + frac * (s_new.phi - s.phi);

                if (disk->inDisk(r_cross)) {
                    DiskCrossing& dc_rec = result.crossings[result.nCrossings++];
                    dc_rec.r     = r_cross;
                    dc_rec.phi   = phi_cross;
                    dc_rec.g     = disk->redshiftFactor(r_cross, phi_cross, inclination);
                    dc_rec.valid = true;
                }
            }
        }

        prev_theta = curr_theta;
        s = s_new;

        // Adapt step size for next iteration (always positive: forward integration)
        h *= factor;
        if (h < 0.0) h = -h;
        h = std::clamp(h, 0.001, 50.0);

        // --- Termination checks ---
        if (metric.is_captured(s)) {
            result.captured    = true;
            result.finalState  = s;
            return result;
        }

        if (s.r > r_max) {
            result.escaped   = true;
            result.finalState = s;
            // Compute exit direction from final BL velocities
            GeodesicState ds = metric.geodesic_rhs(s);
            result.exitDirection = blToCartesianDir(s, ds);
            return result;
        }
    }

    // Ran out of steps without escaping or being captured.  Photons that orbit
    // forever near the photon sphere belong in the shadow — treat them as captured.
    // (Treating them as escaped would feed a stale, possibly NaN exit direction
    // back into the BVH and crash.)
    result.captured   = true;
    result.finalState = s;
    return result;
}
