// pkg59 finishing-touch: UV debug AOV.
//
// Visualizes the first-hit (u, v) the shader actually sampled, written as
// (R=u, G=v, B=0) into the colour buffer. The fastest diagnostic for
// "is this a wiring bug or an unwrap bug" — if the rendered RG matches the
// UV editor, the wiring is correct and the bug is upstream (texture sampling,
// Mapping math, etc.). If it doesn't match, the issue is in the converter or
// per-corner UV upload.
//
// The renderer already populates `Camera::uvBuffer` at first hit (see
// raytracer.h:2392); pkg59 surfaces it through Framebuffer::buffer("uv") so
// this pass can read it via the same pattern as albedo/normal AOVs.

#include <algorithm>
#include "astroray/pass.h"
#include "astroray/register.h"

class UVDebugAOV : public Pass {
public:
    explicit UVDebugAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "UV Debug AOV"; }
    void execute(Framebuffer& fb) override {
        const float* src = fb.hasBuffer("uv") ? fb.buffer("uv") : nullptr;
        if (!src) return;
        float* dst = fb.buffer("color");
        if (!dst) return;
        const size_t pixels = static_cast<size_t>(fb.width()) * fb.height();
        // uvBuffer is Vec3-per-pixel; we want (u, v, 0). Clamp into [0, 1] so
        // the output is directly viewable as a colour image even if the
        // upstream UVs are tiled or transformed beyond [0, 1].
        for (size_t i = 0; i < pixels; ++i) {
            dst[i * 3 + 0] = std::clamp(src[i * 3 + 0], 0.0f, 1.0f);
            dst[i * 3 + 1] = std::clamp(src[i * 3 + 1], 0.0f, 1.0f);
            dst[i * 3 + 2] = 0.0f;
        }
    }
};

ASTRORAY_REGISTER_PASS("uv_debug_aov", UVDebugAOV)
