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

// ============================================================================
// #897: Cartesian Kerr-Schild (KS) chart for rays near the BL polar axis.
// BL is singular at sin(theta)=0: dphi/dlambda ~ L_z/sin^2(theta) gets stiff,
// the RK45 hits its h floor and rejected steps burn maxSteps ("captured").
// Near the axis we integrate Hamilton's equations in Cartesian KS, which has
// no pole singularity, and switch back to BL away from it (chart atlas).
// Source: Chan, Medeiros, Ozel & Psaltis, "GRay2: A General Purpose Geodesic
//   Integrator for Kerr Spacetimes", ApJ 867, 59 (2018), arXiv:1706.07062
//   (Cartesian KS removes the BL pole/horizon singularities); ingoing KS form
//   g^{mu nu} = eta^{mu nu} - f l^mu l^nu from Visser, "The Kerr spacetime: a
//   brief introduction", arXiv:0706.0622 (2007), §3.
// Transform + derivatives derived in-house (no code copied); checked against
// the BL inverse metric and finite differences of H:
// .astroray_plan/docs/kerr-axis-chart-research.md.
// KS state reuses GeodesicState: (t, r, theta, phi) = (t_KS, X, Y, Z),
// (p_r, p_theta, p_phi) = (p_X, p_Y, p_Z); Z is the spin axis.
// ============================================================================
namespace grks {

// BL r from KS Cartesian: r^4 - (R^2 - a^2) r^2 - a^2 Z^2 = 0.
inline double radius(double a, double x, double y, double z) {
    const double w = x*x + y*y + z*z - a*a;
    return std::sqrt(0.5 * w + std::sqrt(0.25 * w * w + a*a * z*z));
}

// phi_KS = phi_BL + Phi(r), t_KS = t_BL + T(r); Phi' = a/Delta, T' = 2Mr/Delta.
inline double phiShift(double M, double a, double r) {
    if (a == 0.0) return 0.0;
    const double d = std::sqrt(std::max(M*M - a*a, 0.0));
    return a / (2.0 * d) * std::log(std::abs((r - (M + d)) / (r - (M - d))));
}
inline double timeShift(double M, double a, double r) {
    const double d = std::sqrt(std::max(M*M - a*a, 0.0));
    const double rp = M + d, rm = M - d;
    return M / d * (rp * std::log(std::abs(r - rp))
                    - (rm > 0.0 ? rm * std::log(std::abs(r - rm)) : 0.0));
}

// KS position X[i] and J[k][i] = dX_i/dq_k for q = (r, theta, phi_BL).
// X + iY = (r + i a) sin(theta) e^{i psi}, psi = phi + Phi(r); Z = r cos(theta).
inline void blToKsJacobian(double M, double a, double r, double th, double ph,
                           double X[3], double J[3][3]) {
    const double psi = ph + phiShift(M, a, r);
    const double st = std::sin(th), ct = std::cos(th);
    const double cp = std::cos(psi), sp = std::sin(psi);
    const double dpsi = a / (r*r - 2.0*M*r + a*a);
    X[0] = (r * cp - a * sp) * st;
    X[1] = (r * sp + a * cp) * st;
    X[2] = r * ct;
    J[0][0] = st * cp - X[1] * dpsi;  J[0][1] = st * sp + X[0] * dpsi;  J[0][2] = ct;
    J[1][0] = (r * cp - a * sp) * ct; J[1][1] = (r * sp + a * cp) * ct; J[1][2] = -r * st;
    J[2][0] = -X[1];                  J[2][1] = X[0];                   J[2][2] = 0.0;
}

// Covectors transform as p_BL = J^T p_KS (plus the t_KS(r) term).
inline GeodesicState fromBL(double M, double a, const GeodesicState& s) {
    double X[3], J[3][3];
    blToKsJacobian(M, a, s.r, s.theta, s.phi, X, J);
    const double delta = s.r*s.r - 2.0*M*s.r + a*a;
    const double b[3] = {s.p_r - s.p_t * 2.0*M*s.r / delta, s.p_theta, s.p_phi};
    // Solve J p = b (Cramer).
    auto det3 = [](const double m[3][3]) {
        return m[0][0]*(m[1][1]*m[2][2] - m[1][2]*m[2][1])
             - m[0][1]*(m[1][0]*m[2][2] - m[1][2]*m[2][0])
             + m[0][2]*(m[1][0]*m[2][1] - m[1][1]*m[2][0]);
    };
    const double D = det3(J);
    double p[3];
    for (int i = 0; i < 3; ++i) {
        double m[3][3];
        for (int k = 0; k < 3; ++k)
            for (int j = 0; j < 3; ++j) m[k][j] = (j == i) ? b[k] : J[k][j];
        p[i] = det3(m) / D;
    }
    GeodesicState o;
    o.t = s.t + timeShift(M, a, s.r);
    o.r = X[0]; o.theta = X[1]; o.phi = X[2];
    o.p_t = s.p_t;
    o.p_r = p[0]; o.p_theta = p[1]; o.p_phi = p[2];
    return o;
}

inline GeodesicState toBL(double M, double a, const GeodesicState& k) {
    const double r = radius(a, k.r, k.theta, k.phi);
    const double th = std::acos(std::clamp(k.phi / r, -1.0, 1.0));
    const double ph = std::atan2(k.theta, k.r) - std::atan2(a, r) - phiShift(M, a, r);
    double X[3], J[3][3];
    blToKsJacobian(M, a, r, th, ph, X, J);
    const double p[3] = {k.p_r, k.p_theta, k.p_phi};
    GeodesicState s;
    s.t = k.t - timeShift(M, a, r);
    s.r = r; s.theta = th; s.phi = ph;
    s.p_t = k.p_t;
    s.p_r = k.p_t * 2.0*M*r / (r*r - 2.0*M*r + a*a);
    s.p_theta = 0.0; s.p_phi = 0.0;
    for (int i = 0; i < 3; ++i) {
        s.p_r     += J[0][i] * p[i];
        s.p_theta += J[1][i] * p[i];
        s.p_phi   += J[2][i] * p[i];
    }
    return s;
}

// Hamilton's equations for H = (eta^{mu nu} p p - f (l.p)^2)/2, l^mu = (-1, l_i),
// l_i = ((rX + aY), (rY - aX))/(r^2+a^2), Z/r;  f = 2 M r^3/(r^4 + a^2 Z^2).
inline GeodesicState rhs(double M, double a, const GeodesicState& k) {
    const double x = k.r, y = k.theta, z = k.phi;
    const double p[3] = {k.p_r, k.p_theta, k.p_phi};
    const double a2 = a * a;
    const double r = radius(a, x, y, z);
    if (!gr_isfinite(r) || r < 0.5 * M) return GeodesicState{0, 0, 0, 0, 0, 0, 0, 0};
    const double r2a2 = r*r + a2;
    const double den = r*r*r*r + a2*z*z;
    const double dr[3] = {r*r*r * x / den, r*r*r * y / den, r * r2a2 * z / den};
    const double f = 2.0*M*r*r*r / den;
    const double n1 = r*x + a*y, n2 = r*y - a*x;
    const double l[3] = {n1 / r2a2, n2 / r2a2, z / r};
    const double L = -k.p_t + l[0]*p[0] + l[1]*p[1] + l[2]*p[2];

    GeodesicState ds;
    ds.t = -k.p_t + f * L;
    ds.r     = p[0] - f * L * l[0];
    ds.theta = p[1] - f * L * l[1];
    ds.phi   = p[2] - f * L * l[2];
    ds.p_t = 0.0;
    double dp[3];
    for (int i = 0; i < 3; ++i) {
        const double ex = (i == 0), ey = (i == 1), ez = (i == 2);
        const double df = (6.0*M*r*r*dr[i]*den
                           - 2.0*M*r*r*r*(4.0*r*r*r*dr[i] + 2.0*a2*z*ez)) / (den*den);
        const double dl0 = ((dr[i]*x + r*ex + a*ey) * r2a2 - n1 * 2.0*r*dr[i]) / (r2a2*r2a2);
        const double dl1 = ((dr[i]*y + r*ey - a*ex) * r2a2 - n2 * 2.0*r*dr[i]) / (r2a2*r2a2);
        const double dl2 = ez / r - z * dr[i] / (r*r);
        dp[i] = 0.5 * df * L * L + f * L * (dl0*p[0] + dl1*p[1] + dl2*p[2]);
    }
    ds.p_r = dp[0]; ds.p_theta = dp[1]; ds.p_phi = dp[2];
    return ds;
}

// Hysteresis: enter KS below kEnter, return to BL above kExit (|sin theta|).
constexpr double kEnter = 0.1;
constexpr double kExit  = 0.2;
// Max KS step as a fraction of r (|dX/dlambda| ~ E ~ 1): <= ~6 deg of arc,
// so a KS leg (|sin theta| < 0.2) can never jump over the equatorial disk.
constexpr double kMaxStepFrac = 0.1;

} // namespace grks

inline ASTRORAY_NOINLINE IntegrationResult integrateGeodesic(
    const Metric&            metric,
    const NovikovThorneDisk* disk,       // nullptr if no disk
    const GeodesicState&     s_init,
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

    // pkg282: p_t and p_phi are Killing-conserved (stationary, axisymmetric
    // metric), so the photon's specific angular momentum is fixed per ray.
    const double lambda = (s.p_t != 0.0) ? -s.p_phi / s.p_t : 0.0;

    // #897: KS chart near the polar axis (see grks above); BL elsewhere.
    double ks_a = 0.0;
    const bool ks_ok = metric.kerrSpin(ks_a);
    const double ks_M = metric.M;
    bool in_ks = false;
    auto rhs = [&](const GeodesicState& x) {
        return in_ks ? grks::rhs(ks_M, ks_a, x) : metric.geodesic_rhs(x);
    };

    double h = h_init;
    double prev_theta = s.theta;
    for (int step = 0; step < maxSteps; ++step) {
        // --- DP45 stages ---
        GeodesicState k[7];
        k[0] = rhs(s);

        // Stage 1
        GeodesicState s1 = s + h * (1.0/5.0) * k[0];
        k[1] = rhs(s1);

        // Stage 2
        GeodesicState s2 = s + h * (3.0/40.0 * k[0] + 9.0/40.0 * k[1]);
        k[2] = rhs(s2);

        // Stage 3
        GeodesicState s3 = s + h * (44.0/45.0 * k[0] + -56.0/15.0 * k[1] + 32.0/9.0 * k[2]);
        k[3] = rhs(s3);

        // Stage 4
        GeodesicState s4 = s + h * (19372.0/6561.0 * k[0] + -25360.0/2187.0 * k[1] +
                                     64448.0/6561.0 * k[2] + -212.0/729.0 * k[3]);
        k[4] = rhs(s4);

        // Stage 5
        GeodesicState s5 = s + h * (9017.0/3168.0 * k[0] + -355.0/33.0 * k[1] +
                                     46732.0/5247.0 * k[2] + 49.0/176.0 * k[3] +
                                     -5103.0/18656.0 * k[4]);
        k[5] = rhs(s5);

        // 5th-order solution
        GeodesicState s_new = s + h * (DP_C5[0]*k[0] + DP_C5[2]*k[2] + DP_C5[3]*k[3] +
                                        DP_C5[4]*k[4] + DP_C5[5]*k[5]);
        k[6] = rhs(s_new);

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

        // #897: accepted KS step. Stay in KS while near the axis; otherwise
        // map back to BL and fall through to the BL termination checks.
        if (in_ks) {
            h *= factor;
            if (h < 0.0) h = -h;
            h = std::clamp(h, 0.001, 50.0);
            const GeodesicState bl = grks::toBL(ks_M, ks_a, s_new);
            if (std::abs(std::sin(bl.theta)) < grks::kExit && bl.r <= r_max &&
                !metric.is_captured(bl)) {
                s = s_new;
                h = std::min(h, grks::kMaxStepFrac * bl.r);
                continue;
            }
            in_ks = false;
            s = bl;
            prev_theta = s.theta;
        } else {
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
                    dc_rec.g     = disk->redshiftFactor(r_cross, lambda);
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
        }

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

        if (ks_ok && std::abs(std::sin(s.theta)) < grks::kEnter) {
            h = std::min(h, grks::kMaxStepFrac * s.r);
            s = grks::fromBL(ks_M, ks_a, s);
            in_ks = true;
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
