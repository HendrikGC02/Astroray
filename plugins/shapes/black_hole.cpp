#include "astroray/register.h"
#include "astroray/black_hole.h"

class BlackHolePlugin : public BlackHole {
public:
    explicit BlackHolePlugin(const astroray::ParamDict& p)
        : BlackHole(p.getVec3("position", Vec3(0.0f)),
                    static_cast<double>(p.getFloat("mass", 1.0f)),
                    static_cast<double>(p.getFloat("influence_radius", 5.0f)),
                    static_cast<double>(p.getFloat("disk_outer", 30.0f)),
                    static_cast<double>(p.getFloat("accretion_rate", 1.0f)),
                    static_cast<double>(p.getFloat("inclination", 75.0f))) {}
};

ASTRORAY_REGISTER_SHAPE("black_hole", BlackHolePlugin)
