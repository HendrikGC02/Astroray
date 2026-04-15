#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>

// MSVC does not support GCC __attribute__ syntax — provide a portable alias.
#ifndef ASTRORAY_NOINLINE
#  ifdef _MSC_VER
#    define ASTRORAY_NOINLINE __declspec(noinline)
#  else
#    define ASTRORAY_NOINLINE __attribute__((noinline))
#  endif
#endif

// ============================================================================
// GR-specific data structures (all double precision for integrator stability)
// ============================================================================

// Bit-pattern based finiteness check.  std::isfinite is unreliable under
// -ffast-math because GCC predefines __FINITE_MATH_ONLY__ at the preprocessor
// level, which lets <cmath> fold isfinite() to constant true regardless of any
// later -fno-finite-math-only flag.  We bypass that by inspecting the IEEE-754
// exponent bits directly: a finite double has an exponent field that is not
// all-ones (NaN/Inf both have all-ones exponents).
inline bool gr_isfinite(double x) {
    uint64_t bits;
    std::memcpy(&bits, &x, sizeof(bits));
    return ((bits >> 52) & 0x7ffULL) != 0x7ffULL;
}

// 8-component geodesic state: (t, r, θ, φ, p_t, p_r, p_θ, p_φ)
struct GeodesicState {
    double t, r, theta, phi;
    double p_t, p_r, p_theta, p_phi;
};

inline GeodesicState operator+(const GeodesicState& a, const GeodesicState& b) {
    return {a.t + b.t, a.r + b.r, a.theta + b.theta, a.phi + b.phi,
            a.p_t + b.p_t, a.p_r + b.p_r, a.p_theta + b.p_theta, a.p_phi + b.p_phi};
}

inline GeodesicState operator*(double s, const GeodesicState& a) {
    return {s*a.t, s*a.r, s*a.theta, s*a.phi,
            s*a.p_t, s*a.p_r, s*a.p_theta, s*a.p_phi};
}

inline GeodesicState operator*(const GeodesicState& a, double s) { return s * a; }

struct DiskCrossing {
    double r;     // Boyer-Lindquist radius of crossing
    double phi;   // azimuthal angle at crossing
    double g;     // redshift factor ν_obs/ν_emit
    bool valid;
};

// Physical constants
constexpr double GR_PI    = 3.14159265358979323846;
constexpr double h_PLANCK = 6.62607015e-34;   // J·s
constexpr double c_LIGHT  = 2.99792458e8;     // m/s
constexpr double k_BOLTZ  = 1.380649e-23;     // J/K
constexpr double SIGMA_SB = 5.670374419e-8;   // W/(m²·K⁴)
constexpr double M_SUN_KG = 1.989e30;         // kg
constexpr double G_NEWTON = 6.674e-11;        // m³/(kg·s²)
