#pragma once

#include "emission.h"
#include "param_dict.h"
#include "gr_types.h"
#include "synchrotron.h"
#include <algorithm>
#include <cmath>

namespace astroray::adaf {

// Reuse CGS constants from synchrotron where applicable
using synchrotron::kElectronChargeCgs;
using synchrotron::kElectronMassG;
using synchrotron::kLightCgs;
using synchrotron::kBoltzmannCgs;
using synchrotron::kPlanckCgs;
using synchrotron::kMeC2Erg;
using synchrotron::kNmToCm;
using synchrotron::cyclotronFrequencyHz;
using synchrotron::frequencyFromWavelengthNm;
using synchrotron::safeSinTheta;
using synchrotron::jnuThermalI;
using synchrotron::alphaThermalI;

constexpr double kProtonMassG = 1.672621923e-24;   // g
constexpr double kSolarMassG = 1.98847e33;          // g
constexpr double kGravityCgs = 6.67430e-8;          // cm^3/(g s^2)

// Schwarzschild radius (2GM/c^2)
inline double schwarzschildRadius(double mass_g) {
    return 2.0 * kGravityCgs * mass_g / (kLightCgs * kLightCgs);
}

// Eddington accretion rate: ~2.2e18 (M/M_sun) g/s
// Yuan & Narayan 2014 convention
inline double eddingtonAccretionRate(double mass_g) {
    return 2.2e18 * (mass_g / kSolarMassG);
}

// ADAF density profile (Yuan & Narayan 2014 eq. 11)
// n_e(r) = 6.3e19 * alpha^(-1) * m^(-1) * mdot_BH * r^(-3/2 + s)   [cm^-3]
// where r is in Schwarzschild radii R_S, m = M/M_sun, mdot_BH in Eddington units
inline double adafDensity(double r_in_RS, double m_solar, double mdot_BH,
                          double alpha, double s) {
    if (r_in_RS <= 0.0 || m_solar <= 0.0 || mdot_BH <= 0.0 || alpha <= 0.0) {
        return 0.0;
    }
    const double prefactor = 6.3e19;
    const double exponent = -1.5 + s;
    const double ne = prefactor / alpha / m_solar * mdot_BH
                    * std::pow(r_in_RS, exponent);
    return std::isfinite(ne) && ne > 0.0 ? ne : 0.0;
}

// ADAF ion temperature (Yuan & Narayan 2014 eq. 16)
// T_ion(r) ≈ G M m_p / (6 k_B R) ≈ (1.2e12 / r) K
// where r is in Schwarzschild radii
inline double adafIonTemperature(double r_in_RS) {
    if (r_in_RS <= 0.0) return 0.0;
    return 1.2e12 / r_in_RS;
}

// ADAF electron temperature
// T_e(r) = T_e0 * (R_S / r)^q
// where q = 1 (pkg44 fixed), T_e0 is user parameter
inline double adafElectronTemperature(double r_in_RS, double T_e0, double q) {
    if (r_in_RS <= 0.0 || T_e0 <= 0.0) return 0.0;
    const double T_e = T_e0 * std::pow(1.0 / r_in_RS, q);
    return std::isfinite(T_e) && T_e > 0.0 ? T_e : 0.0;
}

// ADAF magnetic field (Yuan & Narayan 2014 eq. 12)
// B(r) = 6.5e8 * (1+beta_Y14)^(-1/2) * alpha^(-1/2) * m^(-1/2)
//              * mdot_BH^(1/2) * r^(-5/4 + s/2)   [G]
// WARNING: beta_Y14 = p_gas / p_mag (Y14 convention)
//          pkg44 user parameter beta_mag = p_mag / p_gas (inverse!)
//          So beta_Y14 = 1.0 / beta_mag
inline double adafMagneticField(double r_in_RS, double m_solar, double mdot_BH,
                                double alpha, double s, double beta_mag) {
    if (r_in_RS <= 0.0 || m_solar <= 0.0 || mdot_BH <= 0.0 ||
        alpha <= 0.0 || beta_mag <= 0.0) {
        return 0.0;
    }
    // Map user parameter beta_mag to Y14 paper beta (inverse!)
    const double beta_Y14 = 1.0 / beta_mag;
    const double prefactor = 6.5e8;
    const double exponent = -1.25 + 0.5 * s;
    const double B = prefactor * std::pow(1.0 + beta_Y14, -0.5)
                   * std::pow(alpha, -0.5) * std::pow(m_solar, -0.5)
                   * std::sqrt(mdot_BH) * std::pow(r_in_RS, exponent);
    return std::isfinite(B) && B > 0.0 ? B : 0.0;
}

// Gaunt factor for free-free emission (Karzas & Latter 1961 fitting formula).
// Velocity-averaged Gaunt factor g_ff(nu, T_e) for bremsstrahlung.
// Accurate to ~10% across the relevant parameter space.
// Used in thermal bremsstrahlung emissivity.
//
// Citation: Karzas, W.J., Latter, R. 1961, ApJS 6, 167.
// Also: Rybicki & Lightman 1979 eq. 5.14b (Born approximation).
//
// The fitting formula for the velocity-averaged Gaunt factor is:
//   g_ff ≈ sqrt(3/pi) * ln(4/C_e * sqrt(k_B T_e / h nu))
// where C_e ≈ 1.781 is Euler's constant exponentiated.
// Simplified form used in practice: g_ff ≈ 1.2 to 1.5 (order-unity, weakly
// frequency-dependent). For pkg44, use the Born approximation constant:
//   g_ff ≈ sqrt(3) / pi * ln((2 k_B T_e) / (h nu))
// Clamp at low T or high nu to avoid log of negative arguments.
inline double gauntFactorFF(double nu_hz, double T_e_K) {
    if (nu_hz <= 0.0 || T_e_K <= 0.0 || !std::isfinite(nu_hz) || !std::isfinite(T_e_K)) {
        return 1.0; // fallback to order-unity
    }
    const double x = kPlanckCgs * nu_hz / (kBoltzmannCgs * T_e_K);
    // Born approximation: g_ff ≈ sqrt(3)/pi * ln(2/x)
    // For x << 1 (low-frequency limit), g_ff grows logarithmically.
    // For x >> 1 (high-frequency tail), the exponential cutoff dominates anyway.
    // Clamp x to avoid log singularities.
    if (x >= 2.0) {
        // High-frequency: g_ff → 1 (order-unity, exact value not critical)
        return 1.0;
    }
    const double g_ff = std::sqrt(3.0) / GR_PI * std::log(2.0 / std::max(x, 1.0e-3));
    return std::clamp(g_ff, 1.0, 10.0); // physical range
}

// Thermal bremsstrahlung (free-free) emissivity.
// j_nu^ff = (2^5 * pi * e^6) / (3 m_e c^3) * sqrt(2 pi / (3 k_B m_e))
//         * n_e^2 * T_e^(-1/2) * exp(-h nu / k_B T_e) * g_ff(nu, T_e)
//
// Numerical prefactor (CGS): (2^5 * pi * e^6) / (3 m_e c^3) * sqrt(2 pi / (3 k_B m_e))
// Evaluate using CGS constants:
//   prefactor ≈ 6.8e-38 erg cm^3 / (s Hz sr) * (n_e / cm^-3)^2 * (T_e / K)^(-1/2)
//
// Rybicki & Lightman 1979 eq. 5.14b.
// Also: Yuan & Narayan 2014 §2.2 (bremsstrahlung in ADAF context).
inline double jnuBremsstrahlungI(double nu_hz, double n_e_cm3, double T_e_K) {
    if (nu_hz <= 0.0 || n_e_cm3 <= 0.0 || T_e_K <= 0.0) {
        return 0.0;
    }
    // Numerical prefactor from Rybicki & Lightman 1979 eq. 5.14b.
    // (2^5 * pi * e^6) / (3 m_e c^3) * sqrt(2 pi / (3 k_B m_e))
    // Evaluate in CGS:
    const double e6 = std::pow(kElectronChargeCgs, 6.0);
    const double me_c3 = kElectronMassG * std::pow(kLightCgs, 3.0);
    const double sqrt_term = std::sqrt(2.0 * GR_PI / (3.0 * kBoltzmannCgs * kElectronMassG));
    const double prefactor = (32.0 * GR_PI * e6) / (3.0 * me_c3) * sqrt_term;

    const double g_ff = gauntFactorFF(nu_hz, T_e_K);
    const double x = kPlanckCgs * nu_hz / (kBoltzmannCgs * T_e_K);
    // For x > 700, exp(-x) underflows to zero.
    if (x > 700.0) return 0.0;

    const double j_ff = prefactor * n_e_cm3 * n_e_cm3 / std::sqrt(T_e_K)
                      * std::exp(-x) * g_ff;
    return std::isfinite(j_ff) && j_ff > 0.0 ? j_ff : 0.0;
}

class ADAF : public Emission {
    double mass_M_sun_;
    double mdot_edd_;
    double electron_temp_;    // T_e0 in Kelvin
    double beta_mag_;         // p_mag / p_gas (user convention, inverse of Y14)
    double r_inner_M_;
    double r_outer_M_;
    double flattening_;       // 0 = spherical, 1 = equatorial
    double alpha_;            // viscosity parameter
    double s_;                // outflow exponent
    double q_;                // electron temperature power-law index (fixed = 1)
    double intensity_scale_;

    // Cached CGS conversions
    double mass_g_;
    double r_s_cm_;           // Schwarzschild radius
    double m_solar_;          // M / M_sun (dimensionless)

public:
    explicit ADAF(const ParamDict& p)
        : mass_M_sun_(double(p.getFloat("mass", 4.0e6f))),
          mdot_edd_(double(p.getFloat("mdot_edd", 1.0e-5f))),
          electron_temp_(double(p.getFloat("electron_temp", 5.0e10f))),
          beta_mag_(double(p.getFloat("beta_mag", 0.1f))),
          r_inner_M_(double(p.getFloat("r_inner", 0.0f))),
          r_outer_M_(double(p.getFloat("r_outer", 100.0f))),
          flattening_(double(p.getFloat("flattening", 0.0f))),
          alpha_(double(p.getFloat("alpha", 0.1f))),
          s_(double(p.getFloat("s", 0.3f))),
          q_(1.0), // Fixed per spec
          intensity_scale_(double(p.getFloat("intensity_scale", 1.0f))) {

        mass_M_sun_ = std::max(1.0, mass_M_sun_);
        mdot_edd_ = std::max(0.0, mdot_edd_);
        electron_temp_ = std::clamp(electron_temp_, 1.0e9, 1.0e11);
        beta_mag_ = std::clamp(beta_mag_, 0.01, 10.0);
        r_outer_M_ = std::max(10.0, r_outer_M_);
        flattening_ = std::clamp(flattening_, 0.0, 1.0);
        alpha_ = std::clamp(alpha_, 0.01, 1.0);
        s_ = std::clamp(s_, 0.0, 1.0);
        intensity_scale_ = std::max(0.0, intensity_scale_);

        // CGS conversions
        mass_g_ = mass_M_sun_ * kSolarMassG;
        r_s_cm_ = schwarzschildRadius(mass_g_);
        m_solar_ = mass_M_sun_;

        // Default r_inner to just outside horizon (1.5 R_S) if not specified
        if (r_inner_M_ <= 0.0) {
            r_inner_M_ = 1.5; // 1.5 Schwarzschild radii
        } else {
            r_inner_M_ = std::max(1.0, r_inner_M_);
        }
        r_outer_M_ = std::max(r_inner_M_ + 1.0, r_outer_M_);
    }

    bool contains(const Vec3& position_M) const override {
        // ADAF is quasi-spherical (H/r ~ 1), occupying a volume around the BH.
        // The flattening parameter controls angular concentration:
        // flattening = 0 → spherical (uniform in theta)
        // flattening = 1 → equatorial (disk-like, concentrated at theta ~ pi/2)

        const double r = std::sqrt(double(position_M.length2()));
        if (r < r_inner_M_ || r > r_outer_M_) return false;

        if (flattening_ < 1.0e-6) {
            // Fully spherical: no angular cutoff
            return true;
        }

        // Equatorial concentration: use a Gaussian-like profile in |cos(theta)|.
        // theta is angle from spin axis (assumed to be +y for now).
        // cos(theta) = y / r; equator is cos(theta) = 0.
        const double cos_theta = std::abs(double(position_M.y)) / std::max(r, 1.0e-12);
        const double theta_factor = std::exp(-flattening_ * cos_theta * cos_theta * 10.0);
        // At flattening=1, this decays quickly away from equator.
        // Accept if theta_factor > 0.01 (1% of midplane density).
        return theta_factor > 0.01;
    }

    double densityAt(double r_M) const {
        // Convert r_M (in geometric units M = GM/c^2) to Schwarzschild radii.
        // r_M is in units of GM/c^2 (gravitational radius r_g).
        // Schwarzschild radius R_S = 2 GM/c^2 = 2 r_g.
        // So r_in_RS = r_M * (r_g / R_S) = r_M / 2.
        const double r_in_RS = r_M / 2.0;
        return adafDensity(r_in_RS, m_solar_, mdot_edd_, alpha_, s_);
    }

    double electronTemperatureAt(double r_M) const {
        const double r_in_RS = r_M / 2.0;
        return adafElectronTemperature(r_in_RS, electron_temp_, q_);
    }

    double ionTemperatureAt(double r_M) const {
        const double r_in_RS = r_M / 2.0;
        return adafIonTemperature(r_in_RS);
    }

    double magneticFieldAt(double r_M) const {
        const double r_in_RS = r_M / 2.0;
        return adafMagneticField(r_in_RS, m_solar_, mdot_edd_, alpha_, s_, beta_mag_);
    }

    astroray::SampledSpectrum emissivity(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas) const override {
        astroray::SampledSpectrum out(0.0f);
        if (!contains(position_M)) return out;

        const double r = std::sqrt(double(position_M.length2()));
        const double ne = densityAt(r);
        const double T_e = electronTemperatureAt(r);
        const double B = magneticFieldAt(r);

        if (ne <= 0.0 || T_e <= 0.0) return out;

        // Magnetic field pitch angle: for an isotropic/toroidal field in a
        // quasi-spherical flow, average over pitch angles. Use theta_B = pi/2
        // (perpendicular) as the canonical value (same as synchrotron jet).
        constexpr double theta_B = GR_PI / 2.0;

        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            const double nu_hz = frequencyFromWavelengthNm(lambdas.lambda(i));
            if (nu_hz <= 0.0) continue;

            // Two emission mechanisms:
            // 1. Thermal synchrotron (reuse pkg42 Pandya 2016 fit)
            const double j_sync = (B > 0.0)
                ? jnuThermalI(nu_hz, ne, T_e, B, theta_B)
                : 0.0;

            // 2. Thermal bremsstrahlung (free-free)
            const double j_ff = jnuBremsstrahlungI(nu_hz, ne, T_e);

            // Total emissivity
            const double j_total = j_sync + j_ff;

            out[i] = static_cast<float>(intensity_scale_ * std::min(j_total, 1.0e30));
        }
        return out;
    }

    astroray::SampledSpectrum integrateSegment(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas,
        double path_length_cm) const override {
        // Optically thin assumption (spec §Radiative transfer):
        // no self-absorption for the initial implementation.
        // The ray accumulates j_nu * ds along its path.
        astroray::SampledSpectrum out = emissivity(position_M, photon_direction, lambdas);
        return out * static_cast<float>(std::max(0.0, path_length_cm));
    }

    double dopplerFactor(const Vec3& position_M,
                         const Vec3& photon_direction) const override {
        // ADAF has orbital motion with v ~ (GM/r)^(1/2).
        // At r ~ 10 R_S, v/c ~ 0.2 (sub-relativistic).
        // Full Doppler boost deferred to pkg67 invariant transfer.
        // For now, return 1.0 (no boost) as the orbital velocity is
        // sub-relativistic and the emissivity is already in the comoving frame.
        (void)position_M;
        (void)photon_direction;
        return 1.0;
    }

    // Accessors for testing
    double mdotEddington() const { return mdot_edd_; }
    double electronTemp() const { return electron_temp_; }
    double betaMag() const { return beta_mag_; }
    double outflowExponent() const { return s_; }
};

} // namespace astroray::adaf
