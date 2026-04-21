#include "astroray/register.h"
#include "advanced_features.h"

class BrickPlugin : public BrickTexture {
public:
    explicit BrickPlugin(const astroray::ParamDict& p)
        : BrickTexture(
            p.getVec3("color_brick", Vec3(0.7f, 0.35f, 0.2f)),
            p.getVec3("color_mortar", Vec3(0.9f)),
            p.getFloat("brick_width", 0.5f),
            p.getFloat("brick_height", 0.25f),
            p.getFloat("mortar_size", 0.02f),
            p.getFloat("offset", 0.5f),
            p.getFloat("scale", 5.0f)) {}
};

ASTRORAY_REGISTER_TEXTURE("brick", BrickPlugin)
