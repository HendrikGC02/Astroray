#include "astroray/register.h"
#include "advanced_features.h"

class NoisePlugin : public NoiseTexture {
public:
    explicit NoisePlugin(const astroray::ParamDict& p)
        : NoiseTexture(p.getFloat("scale", 1.0f)) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("noise", NoisePlugin)
