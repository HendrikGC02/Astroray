#include "astroray/register.h"
#include "advanced_features.h"

class VoronoiPlugin : public VoronoiTexture {
public:
    explicit VoronoiPlugin(const astroray::ParamDict& p)
        : VoronoiTexture(
            p.getFloat("scale", 5.0f),
            p.getFloat("randomness", 1.0f),
            static_cast<int>(p.getFloat("dist_metric", 0.0f)),
            static_cast<int>(p.getFloat("feature", 0.0f)),
            p.getFloat("smoothness", 1.0f),
            p.getVec3("color_low", Vec3(0.0f)),
            p.getVec3("color_high", Vec3(1.0f))) {}
    astroray::SampledSpectrum sampleSpectral(
            const Vec2& uv, const Vec3& p,
            const astroray::SampledWavelengths& lambdas) const override {
        Vec3 rgb = value(uv, p);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }
};

ASTRORAY_REGISTER_TEXTURE("voronoi", VoronoiPlugin)
