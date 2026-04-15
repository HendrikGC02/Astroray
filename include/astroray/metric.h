#pragma once
#include "gr_types.h"
#include <cmath>

// ============================================================================
// Abstract metric interface + Schwarzschild implementation
// Port of the validated Python Metric / SchwarzschildMetric classes.
// ============================================================================

class Metric {
public:
    double M;  // mass in geometrized units

    virtual ~Metric() = default;

    // Hamiltonian equations of motion: returns d(state)/dλ
    virtual GeodesicState geodesic_rhs(const GeodesicState& s) const = 0;

    virtual double event_horizon_radius() const = 0;
    virtual double isco_radius() const = 0;
    virtual bool   is_captured(const GeodesicState& s) const = 0;

    // Keplerian angular velocity at radius r (for disk model)
    virtual double disk_omega(double r) const = 0;
};

class SchwarzschildMetric : public Metric {
public:
    SchwarzschildMetric(double mass = 1.0) { M = mass; }

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

    bool is_captured(const GeodesicState& s) const override {
        // Relaxed threshold (2.5M not 2M) to avoid BL coordinate stalling
        return s.r < 2.5 * M;
    }

    double disk_omega(double r) const override {
        return std::sqrt(M / (r * r * r));
    }
};
