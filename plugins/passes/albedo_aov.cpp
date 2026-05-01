#include <cstring>
#include "astroray/pass.h"
#include "astroray/register.h"

class AlbedoAOV : public Pass {
public:
    explicit AlbedoAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Albedo AOV"; }
    void execute(Framebuffer& fb) override {
        const float* src = fb.hasBuffer("albedo") ? fb.buffer("albedo") : nullptr;
        if (!src) return;
        float* dst = fb.buffer("color");
        const size_t count = static_cast<size_t>(fb.width()) * fb.height() * 3;
        std::memcpy(dst, src, count * sizeof(float));
    }
};

ASTRORAY_REGISTER_PASS("albedo_aov", AlbedoAOV)
