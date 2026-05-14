// pkg67 (Option α): register MinkowskiMetric so MetricRegistry can hand out
// a flat-space metric by name. The production render path does not consume
// this (BlackHole owns a SchwarzschildMetric directly); the registry entry
// exists so scripts/tooling can query "is this scene flat?" symmetrically
// with "schwarzschild" and "kerr".
//
// See include/astroray/metric.h::MinkowskiMetric for the algorithm citation.

#include "astroray/metric.h"
#include "astroray/register.h"
#include "astroray/param_dict.h"

namespace {

class MinkowskiMetricPlugin : public MinkowskiMetric {
public:
    explicit MinkowskiMetricPlugin(const astroray::ParamDict&) {}
};

} // namespace

ASTRORAY_REGISTER_METRIC("minkowski", MinkowskiMetricPlugin)
