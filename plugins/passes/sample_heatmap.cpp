#include <cmath>
#include "astroray/pass.h"
#include "astroray/register.h"

static Vec3 heatmapColor(float t) {
    // Blue -> Cyan -> Green -> Yellow -> Red
    float r = 0.0f, g = 0.0f, b = 0.0f;
    if (t < 0.25f) {
        float s = t / 0.25f;
        r = 0.0f; g = s; b = 1.0f;
    } else if (t < 0.5f) {
        float s = (t - 0.25f) / 0.25f;
        r = 0.0f; g = 1.0f; b = 1.0f - s;
    } else if (t < 0.75f) {
        float s = (t - 0.5f) / 0.25f;
        r = s; g = 1.0f; b = 0.0f;
    } else {
        float s = (t - 0.75f) / 0.25f;
        r = 1.0f; g = 1.0f - s; b = 0.0f;
    }
    return Vec3(r, g, b);
}

class SampleHeatmap : public Pass {
public:
    explicit SampleHeatmap(const astroray::ParamDict&) {}
    std::string name() const override { return "Sample Heatmap"; }
    void execute(Framebuffer& fb) override {
        const float* sw = fb.buffer("sample_weight");
        if (!sw) return;

        const int n = fb.width() * fb.height();

        float max_w = 0.0f;
        for (int i = 0; i < n; ++i) {
            if (sw[i] > max_w) max_w = sw[i];
        }
        if (max_w <= 0.0f) return;

        const float log1_max = std::log(1.0f + max_w);
        float* color = fb.buffer("color");
        for (int i = 0; i < n; ++i) {
            float t = std::log(1.0f + sw[i]) / log1_max;
            Vec3 c = heatmapColor(t);
            color[i * 3]     = c.x;
            color[i * 3 + 1] = c.y;
            color[i * 3 + 2] = c.z;
        }
    }
};

ASTRORAY_REGISTER_PASS("sample_heatmap", SampleHeatmap)
