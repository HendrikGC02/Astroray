#include "raytracer.h"
#include "astroray/register.h"

#include <algorithm>

void Renderer::ensureDefaultIntegrator() {
    if (integrator_) {
        return;
    }

    astroray::ParamDict params;
    auto& registry = astroray::IntegratorRegistry::instance();
    std::vector<std::string> names = registry.names();
    auto hasIntegrator = [&](const std::string& name) {
        return std::find(names.begin(), names.end(), name) != names.end();
    };

    if (hasIntegrator("neural-cache")) {
        integrator_ = registry.create("neural-cache", params);
        return;
    }
    if (hasIntegrator("path_tracer")) {
        integrator_ = registry.create("path_tracer", params);
    }
}
