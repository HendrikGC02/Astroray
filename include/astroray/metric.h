#pragma once
#include "gr_types.h"
#include <algorithm>
#include <cmath>

// ============================================================================
// Abstract metric interface + Schwarzschild implementation
// Port of the validated Python Metric / SchwarzschildMetric classes.
// ============================================================================

class Metric {
public:
    double M;  // mass in geometrized units

    virtual ~Metric() = default;

    // Boyer-Lindquist metric helpers. pkg40 exposes these for validation and
    // pkg67 will use isFlat() as a fast-path hook when metrics reach the tracer.
    virtual void christoffel(double t, double r, double theta, double phi,
                             float gamma[4][4][4]) const = 0;

    virtual float inner_product(double t, double r, double theta, double phi,
                                const float vec_a[4],
                                const float vec_b[4]) const = 0;

    virtual bool isFlat() const { return false; }

    // Hamiltonian equations of motion: returns d(state)/dλ
    virtual GeodesicState geodesic_rhs(const GeodesicState& s) const = 0;

    virtual double event_horizon_radius() const = 0;
    virtual double isco_radius() const = 0;
    virtual double photon_sphere_radius(bool prograde = true) const = 0;
    virtual double horizon_angular_velocity() const = 0;
    virtual bool   is_captured(const GeodesicState& s) const = 0;

    // Keplerian angular velocity at radius r (for disk model)
    virtual double disk_omega(double r) const = 0;
};

class SchwarzschildMetric : public Metric {
public:
    SchwarzschildMetric(double mass = 1.0) { M = mass; }

    void christoffel(double, double r, double theta, double,
                     float gamma[4][4][4]) const override {
        for (int a = 0; a < 4; ++a)
            for (int b = 0; b < 4; ++b)
                for (int c = 0; c < 4; ++c)
                    gamma[a][b][c] = 0.0f;

        double sin_th = std::sin(theta);
        double cos_th = std::cos(theta);
        double sin2 = sin_th * sin_th;
        if (sin2 < 1e-12) sin2 = 1e-12;
        double delta = r * r - 2.0 * M * r;
        if (std::abs(delta) < 1e-12) delta = (delta >= 0.0 ? 1e-12 : -1e-12);

        gamma[0][0][1] = static_cast<float>(M / delta);
        gamma[0][1][0] = gamma[0][0][1];
        gamma[1][0][0] = static_cast<float>(M * delta / (r * r * r * r));
        gamma[1][1][1] = static_cast<float>((M - r) / delta + 1.0 / r);
        gamma[1][2][2] = static_cast<float>(-delta / r);
        gamma[1][3][3] = static_cast<float>(-delta * sin2 / r);
        gamma[2][1][2] = static_cast<float>(1.0 / r);
        gamma[2][2][1] = gamma[2][1][2];
        gamma[2][3][3] = static_cast<float>(-sin_th * cos_th);
        gamma[3][1][3] = static_cast<float>(1.0 / r);
        gamma[3][3][1] = gamma[3][1][3];
        gamma[3][2][3] = static_cast<float>(cos_th / std::max(std::abs(sin_th), 1e-12));
        gamma[3][3][2] = gamma[3][2][3];
    }

    float inner_product(double, double r, double theta, double,
                        const float vec_a[4],
                        const float vec_b[4]) const override {
        double f = 1.0 - 2.0 * M / r;
        double sin_th = std::sin(theta);
        double sin2 = sin_th * sin_th;
        double result =
            -f * double(vec_a[0]) * double(vec_b[0]) +
            (1.0 / f) * double(vec_a[1]) * double(vec_b[1]) +
            r * r * double(vec_a[2]) * double(vec_b[2]) +
            r * r * sin2 * double(vec_a[3]) * double(vec_b[3]);
        return static_cast<float>(result);
    }

    ASTRORAY_NOINLINE GeodesicState geodesic_rhs(const GeodesicState& s) const override {
        // Hamiltonian: H = -p_t²/(2f) + f·p_r²/2 + (p_θ² + p_φ²/sin²θ)/(2r²) = 0
        // f = 1 - 2M/r,  f' = 2M/r²

        // Safety: if any state component is non-finite or r is in the danger zone,
        // return zero derivative to halt the integrator cleanly.
        double r = s.r;
        if (!gr_isfinite(r) || !gr_isfinite(s.theta) || !gr_isfinite(s.phi) ||
            !gr_isfinite(s.p_t) || !gr_isfinite(s.p_r) ||
            !gr_isfinite(s.p_theta) || !gr_isfinite(s.p_phi) ||
            r < 0.5 * M) {
            return GeodesicState{0,0,0,0,0,0,0,0};
        }

        double theta  = s.theta;
        double f      = 1.0 - 2.0 * M / r;
        // Clamp f away from zero to prevent divide-by-zero (soft capture guard)
        if (f <= 1e-8) f = 1e-8;
        double r2     = r * r;
        double sin_th = std::sin(theta);
        double cos_th = std::cos(theta);
        double sin2   = sin_th * sin_th;
        if (sin2 < 1e-12) sin2 = 1e-12;

        GeodesicState ds;

        // dx^μ/dλ = ∂H/∂p_μ
        ds.t     = -s.p_t / f;
        ds.r     =  f * s.p_r;
        ds.theta =  s.p_theta / r2;
        ds.phi   =  s.p_phi / (r2 * sin2);

        // dp_μ/dλ = -∂H/∂x^μ
        double df_dr = 2.0 * M / (r * r);
        double L2    = s.p_theta * s.p_theta + s.p_phi * s.p_phi / sin2;

        ds.p_t     = 0.0;  // t is cyclic → E conserved
        ds.p_r     = -(s.p_t * s.p_t * df_dr / (2.0 * f * f)
                       + df_dr * s.p_r * s.p_r / 2.0
                       - L2 / (r * r2));
        ds.p_theta = s.p_phi * s.p_phi * cos_th / (r2 * sin2 * sin_th);
        ds.p_phi   = 0.0;  // φ is cyclic → L conserved

        return ds;
    }

    double event_horizon_radius() const override { return 2.0 * M; }
    double isco_radius()          const override { return 6.0 * M; }
    double photon_sphere_radius(bool = true) const override { return 3.0 * M; }
    double horizon_angular_velocity() const override { return 0.0; }

    bool is_captured(const GeodesicState& s) const override {
        // Relaxed threshold (2.5M not 2M) to avoid BL coordinate stalling
        return s.r < 2.5 * M;
    }

    double disk_omega(double r) const override {
        return std::sqrt(M / (r * r * r));
    }
};

// ============================================================================
// MinkowskiMetric — flat spacetime, g_{μν} = diag(-1, 1, 1, 1).
//
// pkg67 (Option α): added so the Metric hierarchy can represent the flat-space
// case explicitly. The production rendering hot path does NOT call this — flat
// scenes never go through `BlackHole::isGRObject()` dispatch, so the geodesic
// machinery is bypassed entirely. `isFlat() == true` is the marker callers use
// to short-circuit any GR-aware code path; the virtual overrides below exist
// only to satisfy the abstract base.
//
// References (see .astroray_plan/docs/metric-aware-tracer-research.md §2):
//   - Christoffel symbols of Minkowski in Cartesian coords vanish identically.
//   - Null geodesics are straight lines: X^μ(λ) = X^μ_0 + λ k^μ, k^μ constant.
// ============================================================================
class MinkowskiMetric : public Metric {
public:
    MinkowskiMetric() { M = 0.0; }

    bool isFlat() const override { return true; }

    void christoffel(double, double, double, double,
                     float gamma[4][4][4]) const override {
        for (int a = 0; a < 4; ++a)
            for (int b = 0; b < 4; ++b)
                for (int c = 0; c < 4; ++c)
                    gamma[a][b][c] = 0.0f;
    }

    float inner_product(double, double, double, double,
                        const float vec_a[4],
                        const float vec_b[4]) const override {
        double result =
            -double(vec_a[0]) * double(vec_b[0]) +
             double(vec_a[1]) * double(vec_b[1]) +
             double(vec_a[2]) * double(vec_b[2]) +
             double(vec_a[3]) * double(vec_b[3]);
        return static_cast<float>(result);
    }

    // Trivial geodesic RHS — Minkowski has zero Christoffel symbols, so the
    // momenta are conserved and dx^μ/dλ = p^μ. Never invoked along the
    // production render path (isFlat() short-circuits the dispatch).
    GeodesicState geodesic_rhs(const GeodesicState& s) const override {
        GeodesicState ds{};
        ds.t     = -s.p_t;   // raise time index with η^{tt} = -1
        ds.r     =  s.p_r;
        ds.theta =  s.p_theta;
        ds.phi   =  s.p_phi;
        ds.p_t     = 0.0;
        ds.p_r     = 0.0;
        ds.p_theta = 0.0;
        ds.p_phi   = 0.0;
        return ds;
    }

    double event_horizon_radius()        const override { return 0.0; }
    double isco_radius()                 const override { return 0.0; }
    double photon_sphere_radius(bool = true) const override { return 0.0; }
    double horizon_angular_velocity()    const override { return 0.0; }
    bool   is_captured(const GeodesicState&) const override { return false; }
    double disk_omega(double)            const override { return 0.0; }
};
