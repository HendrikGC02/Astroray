#include "astroray/pass.h"
#include "astroray/register.h"

class AlbedoAOV : public Pass {
public:
    explicit AlbedoAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Albedo AOV"; }
    void execute(Framebuffer&) override {}
};

ASTRORAY_REGISTER_PASS("albedo_aov", AlbedoAOV)
