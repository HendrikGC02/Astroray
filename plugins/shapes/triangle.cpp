#include "astroray/register.h"
#include "astroray/shapes.h"

class TrianglePlugin : public Triangle {
public:
    explicit TrianglePlugin(const astroray::ParamDict& p)
        : Triangle(p.getVec3("v0", Vec3(-0.5f, 0.0f, 0.0f)),
                   p.getVec3("v1", Vec3( 0.5f, 0.0f, 0.0f)),
                   p.getVec3("v2", Vec3( 0.0f, 1.0f, 0.0f)),
                   astroray::MaterialRegistry::instance().create(
                       p.getString("material_type", "lambertian"), p)) {}
};

ASTRORAY_REGISTER_SHAPE("triangle", TrianglePlugin)
