#include "astroray/register.h"
#include "advanced_features.h"

class BrickPlugin : public BrickTexture {
public:
    explicit BrickPlugin(const astroray::ParamDict& p)
        : BrickTexture(
            p.getVec3("color1", Vec3(0.8f)),
            p.getVec3("color2", Vec3(0.2f)),
            p.getVec3("color_mortar", Vec3(0.0f)),
            p.getFloat("scale", 5.0f),
            p.getFloat("mortar_size", 0.02f),
            p.getFloat("mortar_smooth", 0.1f),
            p.getFloat("bias", 0.0f),
            p.getFloat("brick_width", 0.5f),
            p.getFloat("row_height", 0.25f),
            p.getFloat("offset_amount", 0.5f),
            static_cast<int>(p.getFloat("offset_frequency", 2.0f)),
            p.getFloat("squash_amount", 1.0f),
            static_cast<int>(p.getFloat("squash_frequency", 2.0f))) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("brick", BrickPlugin)
