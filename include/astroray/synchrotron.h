#pragma once

#include "emission.h"
#include "param_dict.h"
#include "gr_types.h"
#include <algorithm>
#include <cmath>

namespace astroray::synchrotron {

constexpr double kElectronChargeCgs = 4.803204712570263e-10; // statC
constexpr double kElectronMassG     = 9.1093837015e-28;
constexpr double kLightCgs          = 2.99792458e10;         // cm/s
constexpr double kBoltzmannCgs      = 1.380649e-16;          // erg/K
constexpr double kPlanckCgs         = 6.62607015e-27;        // erg*s
constexpr double kMeC2Erg           = kElectronMassG * kLightCgs * kLightCgs;
constexpr double kNmToCm            = 1.0e-7;

inline double safeSinTheta(double theta_B) {
    return std::max(1.0e-6, std::abs(std::sin(theta_B)));
}

inline double cyclotronFrequencyHz(double B_gauss) {
    if (B_gauss <= 0.0 || !std::isfinite(B_gauss)) return 0.0;
    return kElectronChargeCgs * B_gauss
         / (2.0 * GR_PI * kElectronMassG * kLightCgs);
}

inline double frequencyFromWavelengthNm(double lambda_nm) {
    if (lambda_nm <= 0.0 || !std::isfinite(lambda_nm)) return 0.0;
    return kLightCgs / (lambda_nm * kNmToCm);
}

// j_nu, Stokes I, Maxwell-Juettner thermal distribution.
// Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34, eqs. 29 & 31.
// C++ expression follows the project research note, cross-checked against
// ipole src/symphony/maxwell_juettner_fits.c (BSD-3, AFD Group at UIUC;
// master 2024-Q4 per pkg42 spec). RAPTOR/symphony GPLv3 were not mirrored.
inline double jnuThermalI(double nu_hz, double n_e_cm3, double T_e_K,
                          double B_gauss, double theta_B) {
    if (nu_hz <= 0.0 || n_e_cm3 <= 0.0 || T_e_K <= 0.0 || B_gauss <= 0.0) {
        return 0.0;
    }
    const double sin_theta = safeSinTheta(theta_B);
    const double theta_e = kBoltzmannCgs * T_e_K / kMeC2Erg;
    if (theta_e <= 0.0) return 0.0;
    const double nu_c = cyclotronFrequencyHz(B_gauss);
    const double nu_s = (2.0 / 9.0) * nu_c * sin_theta * theta_e * theta_e;
    if (nu_s <= 0.0) return 0.0;
    const double X = std::max(1.0e-300, nu_hz / nu_s);
    const double prefactor = n_e_cm3 * kElectronChargeCgs * kElectronChargeCgs
                           * nu_c / kLightCgs;
    const double term1 = std::sqrt(2.0) * GR_PI / 27.0 * sin_theta;
    const double t = std::pow(X, 0.5)
                   + std::pow(2.0, 11.0 / 12.0) * std::pow(X, 1.0 / 6.0);
    const double result = prefactor * term1 * t * t
                        * std::exp(-std::pow(X, 1.0 / 3.0));
    return std::isfinite(result) && result > 0.0 ? result : 0.0;
}

// j_nu, Stokes I, isotropic power-law distribution.
// Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34, eqs. 29 & 33.
// Formula shape matches the pkg42 research note and the ipole-vendored
// BSD-3 symphony file power_law_fits.c; GPLv3 RAPTOR/symphony not mirrored.
inline double jnuPowerLawI(double nu_hz, double n_e_cm3, double B_gauss,
                           double theta_B, double p,
                           double gamma_min, double gamma_max) {
    if (nu_hz <= 0.0 || n_e_cm3 <= 0.0 || B_gauss <= 0.0 ||
        p <= 1.0 || gamma_min <= 0.0 || gamma_max <= gamma_min) {
        return 0.0;
    }
    const double sin_theta = safeSinTheta(theta_B);
    const double nu_c = cyclotronFrequencyHz(B_gauss);
    if (nu_c <= 0.0) return 0.0;
    const double norm = std::pow(gamma_min, 1.0 - p)
                      - std::pow(gamma_max, 1.0 - p);
    if (std::abs(norm) < 1.0e-300) return 0.0;
    const double prefactor = n_e_cm3 * kElectronChargeCgs * kElectronChargeCgs
                           * nu_c / kLightCgs;
    const double term1 = std::pow(3.0, p / 2.0) * (p - 1.0) * sin_theta;
    const double term2 = 2.0 * (p + 1.0) * norm;
    const double term3 = std::tgamma((3.0 * p - 1.0) / 12.0)
                       * std::tgamma((3.0 * p + 19.0) / 12.0);
    const double term4 = std::pow(nu_hz / (nu_c * sin_theta),
                                  -(p - 1.0) / 2.0);
    const double result = prefactor * term1 / term2 * term3 * term4;
    return std::isfinite(result) && result > 0.0 ? result : 0.0;
}

// alpha_nu, Stokes I, isotropic power-law distribution.
// Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34, eqs. 29 & 33.
inline double alphaPowerLawI(double nu_hz, double n_e_cm3, double B_gauss,
                             double theta_B, double p,
                             double gamma_min, double gamma_max) {
    if (nu_hz <= 0.0 || n_e_cm3 <= 0.0 || B_gauss <= 0.0 ||
        p <= 1.0 || gamma_min <= 0.0 || gamma_max <= gamma_min) {
        return 0.0;
    }
    const double sin_theta = safeSinTheta(theta_B);
    const double nu_c = cyclotronFrequencyHz(B_gauss);
    if (nu_c <= 0.0) return 0.0;
    const double norm = std::pow(gamma_min, 1.0 - p)
                      - std::pow(gamma_max, 1.0 - p);
    if (std::abs(norm) < 1.0e-300) return 0.0;
    const double prefactor = n_e_cm3 * kElectronChargeCgs * kElectronChargeCgs
                           / (nu_hz * kElectronMassG * kLightCgs);
    const double term1 = std::pow(3.0, (p + 1.0) / 2.0) * (p - 1.0);
    const double term2 = 4.0 * norm;
    const double term3 = std::tgamma((3.0 * p + 2.0) / 12.0)
                       * std::tgamma((3.0 * p + 22.0) / 12.0);
    const double term4 = std::pow(nu_hz / (nu_c * sin_theta),
                                  -(p + 2.0) / 2.0);
    const double result = prefactor * term1 / term2 * term3 * term4;
    return std::isfinite(result) && result > 0.0 ? result : 0.0;
}

inline double alphaThermalI(double nu_hz, double n_e_cm3, double T_e_K,
                            double B_gauss, double theta_B) {
    if (nu_hz <= 0.0 || T_e_K <= 0.0) return 0.0;
    const double x = kPlanckCgs * nu_hz / (kBoltzmannCgs * T_e_K);
    const double Bnu = (2.0 * kPlanckCgs * nu_hz * nu_hz * nu_hz
                        / (kLightCgs * kLightCgs)) / std::expm1(x);
    if (Bnu <= 0.0 || !std::isfinite(Bnu)) return 0.0;
    return jnuThermalI(nu_hz, n_e_cm3, T_e_K, B_gauss, theta_B) / Bnu;
}

inline double specialRelativisticDoppler(double lorentz_gamma,
                                         const Vec3& velocity_dir,
                                         const Vec3& photon_dir) {
    const double gamma = std::max(1.0, lorentz_gamma);
    const double beta = std::sqrt(std::max(0.0, 1.0 - 1.0 / (gamma * gamma)));
    Vec3 v = velocity_dir.normalized();
    Vec3 k = photon_dir.normalized();
    const double mu = std::clamp(double(v.dot(k)), -1.0, 1.0);
    const double denom = gamma * (1.0 - beta * mu);
    return denom > 0.0 ? 1.0 / denom : 0.0;
}

class SynchrotronJet : public Emission {
    double half_angle_rad_;
    double r_base_M_;
    double r_max_M_;
    double lorentz_gamma_;
    double p_;
    double gamma_min_;
    double gamma_max_;
    double base_density_;
    double base_B_;
    double intensity_scale_;
    bool include_self_absorption_;

public:
    explicit SynchrotronJet(const ParamDict& p)
        : half_angle_rad_(double(p.getFloat("half_angle_degrees", 5.0f)) * GR_PI / 180.0),
          r_base_M_(double(p.getFloat("r_base", 6.0f))),
          r_max_M_(double(p.getFloat("r_max", 500.0f))),
          lorentz_gamma_(double(p.getFloat("lorentz_factor", 5.0f))),
          p_(double(p.getFloat("power_law_index", 2.5f))),
          gamma_min_(double(p.getFloat("gamma_min", 10.0f))),
          gamma_max_(double(p.getFloat("gamma_max", 1.0e5f))),
          base_density_(double(p.getFloat("base_density", 1.0f))),
          base_B_(double(p.getFloat("magnetic_field", 30.0f))),
          intensity_scale_(double(p.getFloat("intensity_scale", 1.0f))),
          include_self_absorption_(p.getBool("include_self_absorption", false)) {
        half_angle_rad_ = std::clamp(half_angle_rad_, 0.001, GR_PI / 3.0);
        r_base_M_ = std::max(1.0e-6, r_base_M_);
        r_max_M_ = std::max(r_base_M_, r_max_M_);
        lorentz_gamma_ = std::max(1.0, lorentz_gamma_);
        p_ = std::clamp(p_, 1.5, 6.5);
        gamma_min_ = std::max(1.0, gamma_min_);
        gamma_max_ = std::max(gamma_min_ * (1.0 + 1.0e-6), gamma_max_);
        base_density_ = std::max(0.0, base_density_);
        base_B_ = std::max(0.0, base_B_);
        intensity_scale_ = std::max(0.0, intensity_scale_);
    }

    bool contains(const Vec3& position_M) const override {
        const double r = std::sqrt(double(position_M.length2()));
        if (r < r_base_M_ || r > r_max_M_) return false;
        const double axis_mu = std::abs(double(position_M.y)) / std::max(r, 1.0e-12);
        const double theta_to_axis = std::acos(std::clamp(axis_mu, -1.0, 1.0));
        return theta_to_axis <= half_angle_rad_;
    }

    double densityAt(double r_M) const {
        return base_density_ * std::pow(std::max(r_M / r_base_M_, 1.0e-12), -2.0);
    }

    double magneticFieldAt(double r_M) const {
        return base_B_ * std::pow(std::max(r_M / r_base_M_, 1.0e-12), -1.0);
    }

    Vec3 bulkDirection(const Vec3& position_M) const {
        if (position_M.length2() > 1.0e-20f) return position_M.normalized();
        return Vec3(0.0f, position_M.y >= 0.0f ? 1.0f : -1.0f, 0.0f);
    }

    double dopplerFactor(const Vec3& position_M,
                         const Vec3& photon_direction) const override {
        if (!contains(position_M)) return 0.0;
        return specialRelativisticDoppler(lorentz_gamma_, bulkDirection(position_M),
                                          photon_direction);
    }

    astroray::SampledSpectrum emissivity(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas) const override {
        astroray::SampledSpectrum out(0.0f);
        if (!contains(position_M)) return out;

        const double r = std::sqrt(double(position_M.length2()));
        const double ne = densityAt(r);
        const double B = magneticFieldAt(r);
        const double D = std::max(1.0e-12, dopplerFactor(position_M, photon_direction));

        // Toroidal-field-average approximation for an unresolved conical jet:
        // the pitch-angle factor is set to pi/2 so the power-law spectrum is
        // isolated in pkg42. Polarized angle transport is deferred.
        constexpr double theta_B = GR_PI / 2.0;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            const double nu_obs = frequencyFromWavelengthNm(lambdas.lambda(i));
            const double nu_fluid = nu_obs / D;
            const double j = jnuPowerLawI(nu_fluid, ne, B, theta_B,
                                          p_, gamma_min_, gamma_max_);
            // The full pkg67 path will integrate j/nu^2 in invariant form.
            // Current BlackHole fallback has only ray segments, so this local
            // observed emissivity recovers the D^3 optically-thin limit without
            // double-counting anywhere else.
            const double boosted = intensity_scale_ * D * D * D * j;
            out[i] = static_cast<float>(std::min(boosted, 1.0e30));
        }
        return out;
    }

    astroray::SampledSpectrum integrateSegment(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas,
        double path_length_cm) const override {
        astroray::SampledSpectrum out = emissivity(position_M, photon_direction, lambdas);
        if (!include_self_absorption_) {
            return out * static_cast<float>(std::max(0.0, path_length_cm));
        }
        if (!contains(position_M)) return astroray::SampledSpectrum(0.0f);
        const double r = std::sqrt(double(position_M.length2()));
        const double ne = densityAt(r);
        const double B = magneticFieldAt(r);
        const double D = std::max(1.0e-12, dopplerFactor(position_M, photon_direction));
        constexpr double theta_B = GR_PI / 2.0;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            const double nu_obs = frequencyFromWavelengthNm(lambdas.lambda(i));
            const double nu_fluid = nu_obs / D;
            const double alpha = alphaPowerLawI(nu_fluid, ne, B, theta_B,
                                                p_, gamma_min_, gamma_max_);
            const double tau = std::max(0.0, alpha * path_length_cm);
            const double ds_eff = tau > 1.0e-8
                ? (1.0 - std::exp(-tau)) / alpha
                : path_length_cm;
            out[i] *= static_cast<float>(std::max(0.0, ds_eff));
        }
        return out;
    }

    double powerLawIndex() const { return p_; }
    double lorentzFactor() const { return lorentz_gamma_; }
};

} // namespace astroray::synchrotron

