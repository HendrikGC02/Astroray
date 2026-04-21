#include "astroray/register.h"
#include "astroray/shapes.h"

class ConstantMediumPlugin : public ConstantMedium {
public:
    explicit ConstantMediumPlugin(const astroray::ParamDict& p)
        : ConstantMedium(
            astroray::ShapeRegistry::instance().create(
                p.getString("inner_type", "sphere"), p),
            p.getFloat("density", 0.1f),
            p.getVec3("albedo", Vec3(1.0f))) {}
};

ASTRORAY_REGISTER_SHAPE("constant_medium", ConstantMediumPlugin)
