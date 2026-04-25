#include "astroray/register.h"
#include "advanced_features.h"

class CheckerPlugin : public CheckerTexture {
public:
    explicit CheckerPlugin(const astroray::ParamDict& p)
        : CheckerTexture(
            p.getVec3("color1", Vec3(0.0f)),
            p.getVec3("color2", Vec3(1.0f)),
            p.getFloat("scale", 10.0f)) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("checker", CheckerPlugin)
