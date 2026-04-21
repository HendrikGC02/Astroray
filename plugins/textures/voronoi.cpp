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
};

ASTRORAY_REGISTER_TEXTURE("voronoi", VoronoiPlugin)
