#include "astroray/register.h"
#include "advanced_features.h"

class NoisePlugin : public NoiseTexture {
public:
    explicit NoisePlugin(const astroray::ParamDict& p)
        : NoiseTexture(p.getFloat("scale", 1.0f)) {}
};

ASTRORAY_REGISTER_TEXTURE("noise", NoisePlugin)
