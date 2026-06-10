#include "astroray/register.h"
#include "advanced_features.h"

class WhiteNoisePlugin : public WhiteNoiseTexture {
public:
    explicit WhiteNoisePlugin(const astroray::ParamDict&) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("white_noise", WhiteNoisePlugin)
