#pragma once
#include "astroray/registry.h"
#include "astroray/param_dict.h"
#include "raytracer.h"
#include <memory>

// Forward-declare base types not yet implemented (pkg02+)
class Texture;
class Light;
class Integrator;
class Pass;

namespace astroray {
    using MaterialRegistry   = Registry<Material>;
    using ShapeRegistry      = Registry<Hittable>;
    using TextureRegistry    = Registry<Texture>;
    using LightRegistry      = Registry<Light>;
    using IntegratorRegistry = Registry<Integrator>;
    using PassRegistry       = Registry<Pass>;
} // namespace astroray

#define ASTRORAY_REGISTER_MATERIAL(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::MaterialRegistry::instance().add(name, \
            [](const astroray::ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }

#define ASTRORAY_REGISTER_SHAPE(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::ShapeRegistry::instance().add(name, \
            [](const astroray::ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }

#define ASTRORAY_REGISTER_TEXTURE(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::TextureRegistry::instance().add(name, \
            [](const astroray::ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }

#define ASTRORAY_REGISTER_LIGHT(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::LightRegistry::instance().add(name, \
            [](const astroray::ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }

#define ASTRORAY_REGISTER_INTEGRATOR(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::IntegratorRegistry::instance().add(name, \
            [](const astroray::ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }

#define ASTRORAY_REGISTER_PASS(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::PassRegistry::instance().add(name, \
            [](const astroray::ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }
