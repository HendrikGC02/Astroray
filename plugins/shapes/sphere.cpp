#include "astroray/register.h"
#include "astroray/shapes.h"

class SpherePlugin : public Sphere {
public:
    explicit SpherePlugin(const astroray::ParamDict& p)
        : Sphere(p.getVec3("center", Vec3(0.0f)),
                 p.getFloat("radius", 1.0f),
                 astroray::MaterialRegistry::instance().create(
                     p.getString("material_type", "lambertian"), p)) {}
};

ASTRORAY_REGISTER_SHAPE("sphere", SpherePlugin)
