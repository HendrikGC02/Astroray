#include "astroray/pass.h"
#include "astroray/register.h"

class NormalAOV : public Pass {
public:
    explicit NormalAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Normal AOV"; }
    void execute(Framebuffer& fb) override {
        const float* src = fb.hasBuffer("normal") ? fb.buffer("normal") : nullptr;
        if (!src) return;
        float* dst = fb.buffer("color");
        const size_t count = static_cast<size_t>(fb.width()) * fb.height() * 3;
        for (size_t i = 0; i < count; ++i)
            dst[i] = src[i] * 0.5f + 0.5f;
    }
};

ASTRORAY_REGISTER_PASS("normal_aov", NormalAOV)
