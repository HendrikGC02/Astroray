#include "astroray/register.h"
#include "advanced_features.h"

class MusgravePlugin : public MusgraveTexture {
public:
    explicit MusgravePlugin(const astroray::ParamDict& p)
        : MusgraveTexture(
            static_cast<int>(p.getFloat("mus_type", 0.0f)),
            p.getFloat("scale", 5.0f),
            p.getFloat("detail", 2.0f),
            p.getFloat("dimension", 2.0f),
            p.getFloat("lacunarity", 2.0f),
            p.getFloat("gain", 1.0f),
            p.getVec3("color_low", Vec3(0.0f)),
            p.getVec3("color_high", Vec3(1.0f))) {}
};

ASTRORAY_REGISTER_TEXTURE("musgrave", MusgravePlugin)
