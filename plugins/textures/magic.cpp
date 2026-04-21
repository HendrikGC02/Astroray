#include "astroray/register.h"
#include "advanced_features.h"

class MagicPlugin : public MagicTexture {
public:
    explicit MagicPlugin(const astroray::ParamDict& p)
        : MagicTexture(
            static_cast<int>(p.getFloat("turb_depth", 2.0f)),
            p.getFloat("scale", 5.0f),
            p.getFloat("distortion", 1.0f),
            p.getVec3("color1", Vec3(0.0f)),
            p.getVec3("color2", Vec3(1.0f))) {}
};

ASTRORAY_REGISTER_TEXTURE("magic", MagicPlugin)
