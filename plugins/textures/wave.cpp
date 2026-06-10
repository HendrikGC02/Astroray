#include "astroray/register.h"
#include "advanced_features.h"

class WavePlugin : public WaveTexture {
public:
    explicit WavePlugin(const astroray::ParamDict& p)
        : WaveTexture(
            static_cast<int>(p.getFloat("wave_type", 0.0f)),
            static_cast<int>(p.getFloat("bands_direction", 0.0f)),
            static_cast<int>(p.getFloat("rings_direction", 0.0f)),
            static_cast<int>(p.getFloat("profile", 0.0f)),
            p.getFloat("scale", 5.0f),
            p.getFloat("distortion", 0.0f),
            p.getFloat("detail", 2.0f),
            p.getFloat("detail_scale", 1.0f),
            p.getFloat("detail_roughness", 0.5f),
            p.getFloat("phase_offset", 0.0f),
            p.getVec3("color_low", Vec3(0.0f)),
            p.getVec3("color_high", Vec3(1.0f))) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("wave", WavePlugin)
