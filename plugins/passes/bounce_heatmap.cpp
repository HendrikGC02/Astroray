#include <cmath>
#include "astroray/pass.h"
#include "astroray/register.h"

class BounceHeatmap : public Pass {
public:
    explicit BounceHeatmap(const astroray::ParamDict&) {}
    std::string name() const override { return "Bounce Heatmap"; }
    void execute(Framebuffer& fb) override {
        const float* bounce = fb.hasBuffer("bounce_count") ? fb.buffer("bounce_count") : nullptr;
        if (!bounce) return;

        const int n = fb.width() * fb.height();

        float max_count = 0.0f;
        for (int i = 0; i < n; ++i) {
            if (bounce[i] > max_count) max_count = bounce[i];
        }
        if (max_count <= 0.0f) return;

        float* color = fb.buffer("color");
        for (int i = 0; i < n; ++i) {
            float t = bounce[i] / max_count;
            t = std::clamp(t, 0.0f, 1.0f);
            float r = std::clamp(1.5f - std::abs(t - 0.75f) * 4.0f, 0.0f, 1.0f);
            float g = std::clamp(1.5f - std::abs(t - 0.5f)  * 4.0f, 0.0f, 1.0f);
            float b = std::clamp(1.5f - std::abs(t - 0.25f) * 4.0f, 0.0f, 1.0f);
            color[i * 3]     = r;
            color[i * 3 + 1] = g;
            color[i * 3 + 2] = b;
        }
    }
};

ASTRORAY_REGISTER_PASS("bounce_heatmap", BounceHeatmap)
