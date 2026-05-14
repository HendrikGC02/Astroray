#pragma once

#include "emission.h"
#include "param_dict.h"
#include "gr_types.h"
#include <algorithm>
#include <cmath>

namespace astroray::slimdisk {

// CGS constants
constexpr double kLightCgs = 2.99792458e10;        // cm/s
constexpr double kBoltzmannCgs = 1.380649e-16;     // erg/K
constexpr double kPlanckCgs = 6.62607015e-27;      // erg*s
constexpr double kSigmaSBCgs = 5.670374419e-5;     // erg/(s cm^2 K^4)
constexpr double kGravityCgs = 6.67430e-8;         // cm^3/(g s^2)
constexpr double kProtonMassG = 1.672621923e-24;   // g
constexpr double kSolarMassG = 1.98847e33;         // g
constexpr double kNmToCm = 1.0e-7;

// Eddington accretion rate: M_dot_Edd ~ 2.2e18 (M/M_sun) g/s
// Derived from L_Edd = 4*pi*G*M*m_p*c / sigma_T
// where sigma_T = 6.65e-25 cm^2 is Thomson cross-section
inline double eddingtonAccretionRate(double mass_g) {
    // Canonical value: ~1.4e18 g/s per solar mass (see Yuan & Narayan 2014)
    // More precise: eta * L_Edd/c^2 with eta ~ 0.1
    // Simplified: 2.2e18 * (M/M_sun) g/s
    return 2.2e18 * (mass_g / kSolarMassG);
}

inline double schwarzschildRadius(double mass_g) {
    return 2.0 * kGravityCgs * mass_g / (kLightCgs * kLightCgs);
}

// Gravitational radius r_g = GM/c^2 = r_s/2. This is the "M" in geometrized
// units used by Page & Thorne 1974, Sadowski 2009, and the pkg43 spec
// ("r_ISCO = 6 M = 8.86e6 cm" for M = 10 M_sun matches r_g, not r_s).
inline double gravitationalRadius(double mass_g) {
    return kGravityCgs * mass_g / (kLightCgs * kLightCgs);
}

inline double frequencyFromWavelengthNm(double lambda_nm) {
    if (lambda_nm <= 0.0 || !std::isfinite(lambda_nm)) return 0.0;
    return kLightCgs / (lambda_nm * kNmToCm);
}

// Planck function B_nu(T) in CGS: erg/(s cm^2 Hz sr)
// Used for the slim-disk multi-color blackbody emission.
// Rybicki & Lightman 1979 eq. 1.47.
inline double planckBnu(double nu_hz, double T_K) {
    if (nu_hz <= 0.0 || T_K <= 0.0 || !std::isfinite(nu_hz) || !std::isfinite(T_K)) {
        return 0.0;
    }
    const double x = kPlanckCgs * nu_hz / (kBoltzmannCgs * T_K);
    // For large x, exp(x) overflows but Bnu -> 0. Clamp at x = 700.
    if (x > 700.0) return 0.0;
    // For small x, use Wien approximation to avoid catastrophic cancellation.
    if (x < 1.0e-3) {
        // Rayleigh-Jeans limit: B_nu ~ (2 nu^2 k T) / c^2
        return (2.0 * nu_hz * nu_hz * kBoltzmannCgs * T_K) / (kLightCgs * kLightCgs);
    }
    const double prefactor = (2.0 * kPlanckCgs * nu_hz * nu_hz * nu_hz)
                           / (kLightCgs * kLightCgs);
    const double result = prefactor / std::expm1(x);
    return std::isfinite(result) && result > 0.0 ? result : 0.0;
}

// Vertical half-thickness H/r for a slim disk.
// Sadowski 2009 eq. 5 (hydrostatic equilibrium H ~ c_s / Omega_K).
// Fitting function from accretion-emission-research.md §4.1.
// At ISCO: H/r ~ 1.5 * mdot_edd, falling as 1/r^2 outside.
inline double slimDiskHOverR(double r_M, double r_isco_M, double mdot_edd) {
    if (r_M <= 0.0 || r_isco_M <= 0.0 || mdot_edd < 0.0) return 0.0;
    const double r_norm = r_M / r_isco_M;
    const double f_geom = 1.0 / (1.0 + r_norm * r_norm);
    const double h_over_r = 1.5 * mdot_edd * f_geom;
    // Clamp at H/r = 1 for super-Eddington to avoid unphysical aspect ratios.
    // Research note §4.1 mentions the clamp at mdot=10 reaches 7.5 -> 1.0.
    return std::min(h_over_r, 1.0);
}

// Slim-disk midplane temperature T(r) with advective correction.
// Page & Thorne 1974 eq. 11n (Novikov-Thorne baseline) + Sadowski 2009 §3
// advective fraction fit. Formulae from accretion-emission-research.md §4.3.
//
// T_NT^4 = (3 G M M_dot) / (8 pi r^3 sigma_SB) * R_R(r)
// where R_R(r) = 1 - sqrt(r_isco / r) (Page & Thorne 1974 eq. 15n).
//
// Slim correction: f_adv(r, mdot) = fraction of dissipated energy advected
// inward (not radiated). The radiative flux is reduced by (1 - f_adv), so
// T_slim = T_NT * (1 - f_adv)^(1/4).
//
// Exponential form (research note §4.3, corrects the linear form that clamps
// incorrectly at super-Eddington):
//     f_adv = 1 - exp(-(mdot/mdot_Edd) * (r_isco/r)^2)
//
// Citations:
// - Page, D.N., Thorne, K.S. 1974, ApJ 191, 499 (Novikov-Thorne T_NT).
// - Sadowski, A. 2009, ApJS 183, 171 (slim-disk advection; no closed-form
//   solution, the advective fit is an analytic skeleton per research note).
// - Abramowicz & Fragile 2013, Living Rev. Relativity 16, 1 (review).
inline double slimDiskTemperature(double r_cm, double r_isco_cm,
                                   double M_g, double mdot_phys_cgs,
                                   double mdot_edd_ratio) {
    if (r_cm <= r_isco_cm || M_g <= 0.0 || mdot_phys_cgs <= 0.0) return 0.0;

    // Novikov-Thorne temperature (Page & Thorne 1974 eq. 11n).
    const double R_R = 1.0 - std::sqrt(r_isco_cm / r_cm);
    if (R_R <= 0.0) return 0.0;

    const double T4_NT = (3.0 * kGravityCgs * M_g * mdot_phys_cgs)
                       / (8.0 * GR_PI * r_cm * r_cm * r_cm * kSigmaSBCgs) * R_R;
    if (T4_NT <= 0.0 || !std::isfinite(T4_NT)) return 0.0;

    // Advective correction (exponential form, research note §4.3).
    const double r_ratio = r_isco_cm / r_cm;
    const double f_adv = 1.0 - std::exp(-mdot_edd_ratio * r_ratio * r_ratio);
    const double atten = std::max(0.0, 1.0 - f_adv);
    if (atten <= 0.0) return 0.0;

    const double T = std::pow(T4_NT * atten, 0.25);
    return std::isfinite(T) && T > 0.0 ? T : 0.0;
}

// Gaussian vertical density profile for the slim disk.
// The disk is vertically isothermal with rho(z) ~ exp(-z^2 / (2 H^2))
// where z = r * cos(theta) in BL coordinates (theta from spin axis).
// Number density n_e = Sigma / (2 H m_p), scaled by the Gaussian.
//
// For the emission plugin, we evaluate the local density at a point (r, theta).
// The full surface-density Sigma requires the alpha-viscosity closure
// (research note §4.2), but for visualization the emissivity only needs
// the vertical profile shape. Scale by a user parameter "base_density".
inline double gaussianVerticalProfile(double z_over_H) {
    if (!std::isfinite(z_over_H)) return 0.0;
    const double arg = -0.5 * z_over_H * z_over_H;
    // Clamp to avoid exp underflow at large |z|.
    if (arg < -350.0) return 0.0;
    return std::exp(arg);
}

class SlimDisk : public Emission {
    double mass_M_sun_;
    double spin_;
    double mdot_edd_;
    double r_inner_M_;
    double r_outer_M_;
    double r_isco_M_;
    double intensity_scale_;
    double base_density_; // fiducial n_e at midplane, cm^-3

    // Cached CGS conversions
    double mass_g_;
    double r_s_cm_;       // Schwarzschild radius (2GM/c^2)
    double r_g_cm_;       // Gravitational radius (GM/c^2 = r_s/2);
                          // this is the "M" used by Page-Thorne 1974 and the
                          // pkg43 spec ("r_ISCO = 6 M = 8.86e6 cm").
    double mdot_edd_cgs_; // Eddington rate in g/s
    double mdot_cgs_;     // actual accretion rate in g/s

public:
    explicit SlimDisk(const ParamDict& p)
        : mass_M_sun_(double(p.getFloat("mass", 10.0f))),
          spin_(double(p.getFloat("spin", 0.0f))),
          mdot_edd_(double(p.getFloat("mdot", 1.0f))),
          r_inner_M_(double(p.getFloat("r_inner", 0.0f))),
          r_outer_M_(double(p.getFloat("r_outer", 500.0f))),
          intensity_scale_(double(p.getFloat("intensity_scale", 1.0f))),
          base_density_(double(p.getFloat("base_density", 1.0e3f))) {

        mass_M_sun_ = std::max(1.0, mass_M_sun_);
        spin_ = std::clamp(spin_, -0.998, 0.998);
        mdot_edd_ = std::max(0.0, mdot_edd_);
        r_outer_M_ = std::max(10.0, r_outer_M_);
        intensity_scale_ = std::max(0.0, intensity_scale_);
        base_density_ = std::max(0.0, base_density_);

        // CGS conversions
        mass_g_ = mass_M_sun_ * kSolarMassG;
        r_s_cm_ = schwarzschildRadius(mass_g_);
        r_g_cm_ = gravitationalRadius(mass_g_);
        mdot_edd_cgs_ = eddingtonAccretionRate(mass_g_);
        mdot_cgs_ = mdot_edd_ * mdot_edd_cgs_;

        // ISCO radius in M (geometric units). Full Kerr formula from pkg40.
        // Bardeen, Press & Teukolsky 1972 eq. 2.21.
        // Simplified: for a=0 (Schwarzschild) r_ISCO = 6M.
        // For Kerr: Z1, Z2 depend on spin (see pkg40 or research note).
        const double a = spin_;
        const double Z1 = 1.0 + std::pow(1.0 - a * a, 1.0 / 3.0)
                               * (std::pow(1.0 + a, 1.0 / 3.0)
                                + std::pow(1.0 - a, 1.0 / 3.0));
        const double Z2 = std::sqrt(3.0 * a * a + Z1 * Z1);
        const double sign = (a >= 0.0) ? 1.0 : -1.0;
        r_isco_M_ = 3.0 + Z2 - sign * std::sqrt((3.0 - Z1) * (3.0 + Z1 + 2.0 * Z2));
        r_isco_M_ = std::max(1.0, r_isco_M_);

        // Default r_inner to ISCO if not specified.
        if (r_inner_M_ <= 0.0) {
            r_inner_M_ = r_isco_M_;
        } else {
            r_inner_M_ = std::max(1.0, r_inner_M_);
        }
        r_outer_M_ = std::max(r_inner_M_ + 1.0, r_outer_M_);
    }

    bool contains(const Vec3& position_M) const override {
        // Disk occupies the equatorial region between r_inner and r_outer.
        // In Boyer-Lindquist-like coordinates, the disk is near theta ~ pi/2
        // (equator). For flat-space testing, treat as z ~ 0.
        const double r = std::sqrt(double(position_M.length2()));
        if (r < r_inner_M_ || r > r_outer_M_) return false;

        // Vertical extent: check if within ~3 H of the midplane (99.7% of mass).
        const double H_over_r = slimDiskHOverR(r, r_isco_M_, mdot_edd_);
        const double H = H_over_r * r;
        // z-coordinate: approximation in Cartesian-like BL for vertical distance.
        // Full GR would use theta from the metric; flat-space: z ~ position.z.
        const double z = std::abs(double(position_M.z));
        return z <= 3.0 * H;
    }

    double temperatureAt(double r_M) const {
        // r_M is in geometrized units of M = GM/c^2 = r_g (Page-Thorne 1974
        // convention; spec line 222 "r_ISCO = 6 M = 8.86e6 cm" confirms r_g).
        const double r_cm = r_M * r_g_cm_;
        const double r_isco_cm = r_isco_M_ * r_g_cm_;
        return slimDiskTemperature(r_cm, r_isco_cm, mass_g_, mdot_cgs_, mdot_edd_);
    }

    double densityAt(const Vec3& position_M) const {
        const double r = std::sqrt(double(position_M.length2()));
        if (r < r_inner_M_ || r > r_outer_M_) return 0.0;

        const double H_over_r = slimDiskHOverR(r, r_isco_M_, mdot_edd_);
        const double H = H_over_r * r;
        if (H <= 0.0) return 0.0;

        // Vertical profile: Gaussian centered at midplane.
        const double z = std::abs(double(position_M.z));
        const double z_over_H = z / H;
        const double vertical_factor = gaussianVerticalProfile(z_over_H);

        // Radial profile: for visualization, use a power-law falloff.
        // Full model would derive from Sigma(r) (research note §4.2).
        // Simplification: n_e ~ (r_inner / r)^alpha with alpha ~ 1.5.
        const double radial_factor = std::pow(r_inner_M_ / r, 1.5);

        return base_density_ * radial_factor * vertical_factor;
    }

    astroray::SampledSpectrum emissivity(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas) const override {
        astroray::SampledSpectrum out(0.0f);
        if (!contains(position_M)) return out;

        const double r = std::sqrt(double(position_M.length2()));
        const double T_K = temperatureAt(r);
        if (T_K <= 0.0) return out;

        const double ne = densityAt(position_M);
        if (ne <= 0.0) return out;

        // Multi-color blackbody: emit Planck spectrum at local temperature.
        // The emissivity j_nu = n_e * B_nu(T) is a simplification; the full
        // radiative-transfer model would include optical depth. For optically
        // thick disks, the photosphere emits as a blackbody (research note §1).
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            const double nu_hz = frequencyFromWavelengthNm(lambdas.lambda(i));
            const double Bnu = planckBnu(nu_hz, T_K);
            // Scale by density and intensity_scale. The units are schematic;
            // the render pipeline will normalize.
            const double j = intensity_scale_ * ne * Bnu;
            out[i] = static_cast<float>(std::min(j, 1.0e30));
        }
        return out;
    }

    astroray::SampledSpectrum integrateSegment(
        const Vec3& position_M,
        const Vec3& photon_direction,
        const astroray::SampledWavelengths& lambdas,
        double path_length_cm) const override {
        // Optically thick assumption: no self-absorption integration needed.
        // The disk emits from the photosphere, not from the interior.
        // For a slim disk, tau >> 1 at visible/UV, so the observed emission
        // is the local blackbody at the effective temperature.
        astroray::SampledSpectrum out = emissivity(position_M, photon_direction, lambdas);
        return out * static_cast<float>(std::max(0.0, path_length_cm));
    }

    double dopplerFactor(const Vec3& position_M,
                         const Vec3& photon_direction) const override {
        // Disk material orbits at Keplerian velocity. For visualization,
        // the Doppler shift is second-order (v/c ~ 0.1-0.5 near ISCO).
        // Full implementation deferred to pkg67 invariant transfer.
        (void)position_M;
        (void)photon_direction;
        return 1.0;
    }

    // Accessors for testing
    double mdotEddington() const { return mdot_edd_; }
    double iscoRadius() const { return r_isco_M_; }
};

} // namespace astroray::slimdisk
