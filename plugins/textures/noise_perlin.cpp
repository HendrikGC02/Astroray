#include "astroray/register.h"
#include "advanced_features.h"

class NoisePerlinPlugin : public NoiseTextureCycles {
public:
    explicit NoisePerlinPlugin(const astroray::ParamDict& p)
        : NoiseTextureCycles(
            p.getFloat("scale", 5.0f),
            p.getFloat("detail", 2.0f),
            p.getFloat("roughness", 0.5f),
            p.getFloat("lacunarity", 2.0f),
            p.getFloat("offset", 0.0f),
            p.getFloat("gain", 1.0f),
            p.getFloat("distortion", 0.0f),
            // int-like params arrive as floats through the Python dict
            // bindings — read via getFloat like gradient.cpp's grad_type.
            static_cast<int>(p.getFloat("noise_type", 0.0f)),
            p.getFloat("normalize", 1.0f) != 0.0f) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("noise_perlin", NoisePerlinPlugin)
