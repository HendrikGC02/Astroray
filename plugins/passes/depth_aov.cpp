#include "astroray/pass.h"
#include "astroray/register.h"

class DepthAOV : public Pass {
public:
    explicit DepthAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Depth AOV"; }
    void execute(Framebuffer&) override {}
};

ASTRORAY_REGISTER_PASS("depth_aov", DepthAOV)
