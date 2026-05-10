#include "astroray/pass.h"
#include "astroray/register.h"
#include <algorithm>
#include <cmath>

// pkg72: visualisation pass for the per-pixel motion buffer (float2/pixel,
// previous->current screen-space offset, OptiX flow convention). Mirrors the
// shape of plugins/passes/normal_aov.cpp; the buffer it reads is documented
// at Camera::motionBuffer in include/raytracer.h. Encoding: red channel =
// +x flow (clamped to ±10 px), green channel = +y flow, blue channel =
// magnitude. Saturated at 10 px so typical viewport motion is visible.
class MotionVectorAOV : public Pass {
public:
    explicit MotionVectorAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Motion Vector AOV"; }
    void execute(Framebuffer& fb) override {
        const float* src = fb.hasBuffer("motion") ? fb.buffer("motion") : nullptr;
        if (!src) return;
        float* dst = fb.buffer("color");
        if (!dst) return;
        const int w = fb.width(), h = fb.height();
        const float scale = 1.0f / 10.0f;  // ±10 px maps to ±1.
        for (int i = 0; i < w * h; ++i) {
            const float mx = src[2 * i + 0];
            const float my = src[2 * i + 1];
            const float r = std::clamp(0.5f + 0.5f * mx * scale, 0.0f, 1.0f);
            const float g = std::clamp(0.5f + 0.5f * my * scale, 0.0f, 1.0f);
            const float mag = std::sqrt(mx * mx + my * my) * scale;
            const float b = std::clamp(mag, 0.0f, 1.0f);
            dst[3 * i + 0] = r;
            dst[3 * i + 1] = g;
            dst[3 * i + 2] = b;
        }
    }
};

ASTRORAY_REGISTER_PASS("motion_vector_aov", MotionVectorAOV)
