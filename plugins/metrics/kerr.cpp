#include "astroray/metric.h"
#include "astroray/register.h"
#include "astroray/param_dict.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace {

constexpr double kThetaEps = 1e-8;

double clampTheta(double theta) {
    return std::clamp(theta, kThetaEps, GR_PI - kThetaEps);
}

class KerrMetric : public Metric {
    double a_;

public:
    explicit KerrMetric(const astroray::ParamDict& p)
        : a_(static_cast<double>(p.getFloat("a", 0.998f))) {
        M = static_cast<double>(p.getFloat("M", 1.0f));
        if (M <= 0.0) M = 1.0;
        double limit = 0.998 * M;
        a_ = std::clamp(a_, -limit, limit);
    }

    void christoffel(double, double r, double theta, double,
                     float gamma[4][4][4]) const override {
        for (int alpha = 0; alpha < 4; ++alpha)
            for (int mu = 0; mu < 4; ++mu)
                for (int nu = 0; nu < 4; ++nu)
                    gamma[alpha][mu][nu] = 0.0f;

        theta = clampTheta(theta);
        double sin_th = std::sin(theta);
        double cos_th = std::cos(theta);
        double sigma = r*r + a_*a_*cos_th*cos_th;
        double delta = r*r - 2.0*M*r + a_*a_;
        if (std::abs(delta) < 1e-14) delta = (delta >= 0.0 ? 1e-14 : -1e-14);
        double A_ = (r*r + a_*a_) * (r*r + a_*a_)
                  - delta * a_*a_ * sin_th * sin_th;
        double sigma3 = sigma * sigma * sigma;
        double s2 = 2.0*r*r - sigma;
        double sincos = sin_th * cos_th;

        double g[4][4][4] = {};

        // Bardeen, Press, Teukolsky 1972 ApJ 178, 347; BL Christoffel
        // expressions transcribed from the project research note. RAPTOR
        // GPLv3 was used only for numerical cross-validation; no code copied.
        g[0][0][1] =  (r*r + a_*a_) / (sigma*sigma * delta) * s2;
        g[0][0][2] = -2.0*M*a_*a_*r * sincos / (sigma*sigma);
        g[0][1][3] = -M*a_ * sin_th*sin_th / (sigma * delta)
                   * (2.0*r*r/sigma * (r*r + a_*a_) + r*r - a_*a_);
        g[0][2][3] =  2.0*M*a_*a_*a_*r * sin_th*sin_th * sincos / (sigma*sigma);

        g[1][0][0] =  M * delta / sigma3 * s2;
        g[1][1][1] = (M - r) / delta + r / sigma;
        g[1][1][2] = -a_*a_ * sincos / sigma;
        g[1][2][2] = -r * delta / sigma;
        g[1][0][3] = -M*a_ * delta * sin_th*sin_th / sigma3 * s2;
        g[1][3][3] = -delta * sin_th*sin_th / sigma
                   * (r - a_*a_*sin_th*sin_th / (sigma*sigma) * s2);

        g[2][0][0] = -2.0*M*a_*a_*r * sincos / sigma3;
        g[2][1][1] =  a_*a_ * sincos / (sigma * delta);
        g[2][1][2] =  r / sigma;
        g[2][2][2] = -a_*a_ * sincos / sigma;
        g[2][0][3] =  2.0*M*a_*r*(r*r + a_*a_) * sincos / sigma3;
        g[2][3][3] = -sincos / sigma3
                   * ((r*r+a_*a_)*A_ - sigma*delta*a_*a_*sin_th*sin_th);

        g[3][0][1] =  M*a_ / (sigma*sigma * delta) * s2;
        g[3][0][2] = -2.0*M*a_*r * cos_th / (sigma*sigma * sin_th);
        g[3][1][3] =  r/sigma
                   - a_*a_*sin_th*sin_th/(sigma*delta)
                   * (r - M + 2.0*r*r/sigma);
        g[3][2][3] =  cos_th/sin_th
                   * (1.0 + 2.0*M*a_*a_*r*sin_th*sin_th/(sigma*sigma));

        g[0][1][0] = g[0][0][1];   g[0][3][0] = g[0][0][3];
        g[0][2][0] = g[0][0][2];   g[0][3][1] = g[0][1][3];
        g[0][3][2] = g[0][2][3];
        g[1][3][0] = g[1][0][3];   g[1][2][1] = g[1][1][2];
        g[2][3][0] = g[2][0][3];   g[2][2][1] = g[2][1][2];
        g[3][1][0] = g[3][0][1];   g[3][2][0] = g[3][0][2];
        g[3][3][1] = g[3][1][3];   g[3][3][2] = g[3][2][3];

        for (int alpha = 0; alpha < 4; ++alpha)
            for (int mu = 0; mu < 4; ++mu)
                for (int nu = 0; nu < 4; ++nu)
                    gamma[alpha][mu][nu] = static_cast<float>(g[alpha][mu][nu]);
    }

    float inner_product(double, double r, double theta, double,
                        const float vec_a[4],
                        const float vec_b[4]) const override {
        theta = clampTheta(theta);
        double sin_th = std::sin(theta);
        double cos_th = std::cos(theta);
        double sigma = r*r + a_*a_*cos_th*cos_th;
        double delta = r*r - 2.0*M*r + a_*a_;
        double A_ = (r*r + a_*a_) * (r*r + a_*a_)
                  - delta * a_*a_ * sin_th * sin_th;

        double g00 = -(1.0 - 2.0*M*r / sigma);
        double g11 = sigma / delta;
        double g22 = sigma;
        double g33 = A_ / sigma * sin_th * sin_th;
        double g03 = -2.0*M*a_*r * sin_th * sin_th / sigma;

        double result =
            g00 * double(vec_a[0]) * double(vec_b[0]) +
            g11 * double(vec_a[1]) * double(vec_b[1]) +
            g22 * double(vec_a[2]) * double(vec_b[2]) +
            g33 * double(vec_a[3]) * double(vec_b[3]) +
            g03 * (double(vec_a[0]) * double(vec_b[3])
                 + double(vec_a[3]) * double(vec_b[0]));
        return static_cast<float>(result);
    }

    GeodesicState geodesic_rhs(const GeodesicState&) const override {
        throw std::runtime_error(
            "KerrMetric geodesic_rhs is reserved for pkg41/pkg67; "
            "pkg40 exposes metric tensors, Christoffels, and analytic gates");
    }

    double event_horizon_radius() const override {
        return M + std::sqrt(std::max(0.0, M*M - a_*a_));
    }

    double isco_radius() const override {
        double chi = a_ / M;
        double z1 = 1.0 + std::cbrt(1.0 - chi*chi)
                  * (std::cbrt(1.0 + chi) + std::cbrt(1.0 - chi));
        double z2 = std::sqrt(3.0*chi*chi + z1*z1);
        double inner = (3.0 - z1) * (3.0 + z1 + 2.0*z2);
        return M * (3.0 + z2 - std::sqrt(std::max(0.0, inner)));
    }

    double photon_sphere_radius(bool prograde = true) const override {
        double chi = std::clamp(a_ / M, -1.0, 1.0);
        double arg = prograde ? -chi : chi;
        return 2.0 * M * (1.0 + std::cos((2.0 / 3.0) * std::acos(arg)));
    }

    double horizon_angular_velocity() const override {
        double r_plus = event_horizon_radius();
        return a_ / (r_plus*r_plus + a_*a_);
    }

    bool is_captured(const GeodesicState& s) const override {
        return s.r < event_horizon_radius() + 0.5 * M;
    }

    double disk_omega(double r) const override {
        return std::sqrt(M) / (std::pow(r, 1.5) + a_ * std::sqrt(M));
    }
};

} // namespace

ASTRORAY_REGISTER_METRIC("kerr", KerrMetric)
