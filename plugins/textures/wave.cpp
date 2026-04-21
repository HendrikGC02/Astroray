#include "astroray/register.h"
#include "advanced_features.h"

class WavePlugin : public WaveTexture {
public:
    explicit WavePlugin(const astroray::ParamDict& p)
        : WaveTexture(
            static_cast<int>(p.getFloat("band_dir", 0.0f)),
            static_cast<int>(p.getFloat("profile", 0.0f)),
            p.getFloat("scale", 5.0f),
            p.getFloat("distortion", 0.0f),
            p.getFloat("detail", 2.0f),
            p.getFloat("roughness", 0.5f),
            p.getFloat("lacunarity", 2.0f),
            p.getVec3("color_low", Vec3(0.0f)),
            p.getVec3("color_high", Vec3(1.0f))) {}
};

ASTRORAY_REGISTER_TEXTURE("wave", WavePlugin)
