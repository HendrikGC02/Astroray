#pragma once
#include "gr_types.h"
#include "metric.h"
#include <array>
#include <cmath>
#include <algorithm>

// ============================================================================
// Novikov-Thorne accretion disk with Page-Thorne flux profile.
// Port of the validated Python NovikovThorneDisk class.
// ============================================================================

class NovikovThorneDisk {
public:
    static constexpr int TABLE_SIZE = 1000;

private:
    const Metric* metric;
    double M_val;   // cached metric->M (avoids pointer dereference in hot path)
    double r_isco;
    double r_outer;
    double mdot;

    std::array<double, TABLE_SIZE> r_table;
    std::array<double, TABLE_SIZE> flux_table;
    std::array<double, TABLE_SIZE> temp_table;
    double tempNorm = 1.0;  // applied in temperatureAt() to reach TARGET_PEAK_TEMP

    // Target peak disk temperature (K).  Raw geometric-unit flux fed through
    // SI σ_SB gives ~10 K; we renormalize so the inner disk peaks here instead.
    // 20 000 K produces visible orange-white disk emission through the CIE pipeline.
    static constexpr double TARGET_PEAK_TEMP = 2.0e4;

    // Circular orbit conserved quantities for Schwarzschild
    static double E_circ(double r, double M) {
        double x = 1.0 - 3.0 * M / r;
        if (x <= 0.0) return 1.0;
        return (1.0 - 2.0 * M / r) / std::sqrt(x);
    }

    static double L_circ(double r, double M) {
        double x = 1.0 - 3.0 * M / r;
        if (x <= 0.0) return 0.0;
        return r * std::sqrt(M / r) / std::sqrt(x);
    }

    void buildFluxTable() {
        double M = metric->M;  // safe to call in constructor (metric fully constructed)
        double r_in = r_isco;

        // Build radial table from r_isco to r_outer
        for (int i = 0; i < TABLE_SIZE; ++i) {
            r_table[i] = r_in + (r_outer - r_in) * double(i) / double(TABLE_SIZE - 1);
        }

        // Trapezoidal integration of the Page-Thorne integrand from r_isco outward.
        // F(r) = (3*M*mdot) / (8*pi*r^3) * (1/sqrt(1-3M/r)) * integral
        // where the integrand is (E - Omega*L) * (dL/dr) / (E - Omega*L)^2
        // = dL/dr / (E - Omega*L)
        //
        // Since E,L,Omega are Keplerian:
        //   dL/dr is computed numerically (finite difference on L_circ)
        //   (E - Omega*L) is computed at each r

        // Precompute integrand values
        std::array<double, TABLE_SIZE> integrand;
        const double dr_fd = r_in * 1e-6;  // finite-difference step for dL/dr
        for (int i = 0; i < TABLE_SIZE; ++i) {
            double r = r_table[i];
            if (r < r_in + 1e-10) {
                integrand[i] = 0.0;
                continue;
            }
            double Omega = metric->disk_omega(r);
            double E     = E_circ(r, M);
            double L     = L_circ(r, M);
            double denom = E - Omega * L;
            if (std::abs(denom) < 1e-15) { integrand[i] = 0.0; continue; }

            // dL/dr by central finite difference
            double r_p = r + dr_fd, r_m = r - dr_fd;
            double dLdr = (L_circ(r_p, M) - L_circ(r_m, M)) / (2.0 * dr_fd);
            integrand[i] = dLdr / denom;
        }

        // Trapezoidal cumulative integral from r_isco outward
        std::array<double, TABLE_SIZE> cum_integral;
        cum_integral[0] = 0.0;
        for (int i = 1; i < TABLE_SIZE; ++i) {
            double dr = r_table[i] - r_table[i - 1];
            cum_integral[i] = cum_integral[i - 1] + 0.5 * (integrand[i - 1] + integrand[i]) * dr;
        }

        // Build flux and temperature tables
        constexpr double inv8pi = 1.0 / (8.0 * GR_PI);
        for (int i = 0; i < TABLE_SIZE; ++i) {
            double r = r_table[i];
            double x = 1.0 - 3.0 * M / r;
            double prefactor = (x > 1e-12)
                ? (3.0 * M * mdot * inv8pi) / (r * r * r) / std::sqrt(x)
                : 0.0;
            double F = prefactor * cum_integral[i];
            flux_table[i] = (F > 0.0) ? F : 0.0;

            // Stefan-Boltzmann: T = (F/sigma)^(1/4)
            // NOTE: flux is in geometric units, not SI W/m², so raw temperatures
            // come out ~10 K.  We renormalize via tempNorm (set below).
            temp_table[i] = (flux_table[i] > 0.0)
                ? std::pow(flux_table[i] / SIGMA_SB, 0.25)
                : 0.0;
        }

        // Renormalize so the peak disk temperature equals TARGET_PEAK_TEMP.
        double rawMax = *std::max_element(temp_table.begin(), temp_table.end());
        tempNorm = (rawMax > 0.0) ? TARGET_PEAK_TEMP / rawMax : 1.0;
    }

    double interpolate(const std::array<double, TABLE_SIZE>& table, double r) const {
        if (r <= r_table[0])                return table[0];
        if (r >= r_table[TABLE_SIZE - 1])   return table[TABLE_SIZE - 1];
        // Binary search
        int lo = 0, hi = TABLE_SIZE - 1;
        while (hi - lo > 1) {
            int mid = (lo + hi) / 2;
            if (r_table[mid] <= r) lo = mid; else hi = mid;
        }
        double frac = (r - r_table[lo]) / (r_table[hi] - r_table[lo]);
        return table[lo] * (1.0 - frac) + table[hi] * frac;
    }

public:
    NovikovThorneDisk(const Metric* m, double outer = 30.0, double accretion = 1.0)
        : metric(m), M_val(m->M), r_outer(outer * m->M), mdot(accretion)
    {
        r_isco = metric->isco_radius();
        // Clamp outer radius to be at least a bit beyond ISCO
        if (r_outer <= r_isco) r_outer = r_isco * 5.0;
        buildFluxTable();
    }

    bool inDisk(double r) const {
        return r >= r_isco && r <= r_outer;
    }

    double fluxAt(double r) const {
        return interpolate(flux_table, r);
    }

    ASTRORAY_NOINLINE
    double temperatureAt(double r) const {
        return interpolate(temp_table, r) * tempNorm;
    }

    // g = ν_obs/ν_emit: combined gravitational + Doppler redshift
    // g = 1 / [(1 + Ω·r·sinθ·sinφ) / √(1 - 3M/r)]
    // theta here is the observer inclination, phi is the azimuthal position of the
    // disk element at crossing.
    ASTRORAY_NOINLINE
    double redshiftFactor(double r, double phi, double inclination) const {
        double M     = M_val;
        if (r <= 0.0) return 0.0;
        double r3    = r * r * r;
        double Omega = std::sqrt(M / r3);
        double x     = 1.0 - 3.0 * M / r;
        if (x <= 0.0) return 0.0;
        double sqrt_x    = std::sqrt(x);
        double sin_incl  = std::sin(inclination);
        double numerator = 1.0 + Omega * r * sin_incl * std::sin(phi);
        if (std::abs(numerator) < 1e-15) return 0.0;
        return sqrt_x / numerator;
    }

    double getISCO()  const { return r_isco; }
    double getOuter() const { return r_outer; }
};
