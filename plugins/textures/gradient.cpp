#include "astroray/register.h"
#include "advanced_features.h"

class GradientPlugin : public GradientTexture {
public:
    explicit GradientPlugin(const astroray::ParamDict& p)
        : GradientTexture(
            static_cast<int>(p.getFloat("grad_type", 0.0f)),
            p.getVec3("color1", Vec3(0.0f)),
            p.getVec3("color2", Vec3(1.0f)),
            p.getFloat("scale", 1.0f)) {}
};

ASTRORAY_REGISTER_TEXTURE("gradient", GradientPlugin)
