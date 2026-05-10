#include "astroray/metric.h"
#include "astroray/register.h"
#include "astroray/param_dict.h"

#include <memory>

namespace {

class SchwarzschildMetricPlugin : public Metric {
    std::shared_ptr<Metric> kerr_;

public:
    explicit SchwarzschildMetricPlugin(const astroray::ParamDict& p) {
        astroray::ParamDict kp;
        M = static_cast<double>(p.getFloat("M", 1.0f));
        kp.set("M", static_cast<float>(M));
        kp.set("a", 0.0f);
        kerr_ = astroray::MetricRegistry::instance().create("kerr", kp);
    }

    void christoffel(double t, double r, double theta, double phi,
                     float gamma[4][4][4]) const override {
        kerr_->christoffel(t, r, theta, phi, gamma);
    }

    float inner_product(double t, double r, double theta, double phi,
                        const float vec_a[4],
                        const float vec_b[4]) const override {
        return kerr_->inner_product(t, r, theta, phi, vec_a, vec_b);
    }

    GeodesicState geodesic_rhs(const GeodesicState& s) const override {
        return kerr_->geodesic_rhs(s);
    }

    double event_horizon_radius() const override { return kerr_->event_horizon_radius(); }
    double isco_radius() const override { return kerr_->isco_radius(); }
    double photon_sphere_radius(bool prograde = true) const override {
        return kerr_->photon_sphere_radius(prograde);
    }
    double horizon_angular_velocity() const override {
        return kerr_->horizon_angular_velocity();
    }
    bool is_captured(const GeodesicState& s) const override {
        return kerr_->is_captured(s);
    }
    double disk_omega(double r) const override { return kerr_->disk_omega(r); }
};

} // namespace

ASTRORAY_REGISTER_METRIC("schwarzschild", SchwarzschildMetricPlugin)
