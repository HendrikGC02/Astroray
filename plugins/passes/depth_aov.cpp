#include <cmath>
#include <limits>
#include "astroray/pass.h"
#include "astroray/register.h"

class DepthAOV : public Pass {
public:
    explicit DepthAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Depth AOV"; }
    void execute(Framebuffer& fb) override {
        const float* depth = fb.hasBuffer("depth") ? fb.buffer("depth") : nullptr;
        if (!depth) return;

        const int n = fb.width() * fb.height();

        float dmin = std::numeric_limits<float>::max();
        float dmax = 0.0f;
        for (int i = 0; i < n; ++i) {
            float d = depth[i];
            if (d > 0.0f && std::isfinite(d)) {
                if (d < dmin) dmin = d;
                if (d > dmax) dmax = d;
            }
        }
        if (dmax <= 0.0f || dmin == std::numeric_limits<float>::max()) return;

        float range = dmax - dmin;
        float* color = fb.buffer("color");
        for (int i = 0; i < n; ++i) {
            float d = depth[i];
            float norm = (d > 0.0f && std::isfinite(d))
                         ? (d - dmin) / range
                         : 0.0f;
            color[i * 3]     = norm;
            color[i * 3 + 1] = norm;
            color[i * 3 + 2] = norm;
        }
    }
};

ASTRORAY_REGISTER_PASS("depth_aov", DepthAOV)
