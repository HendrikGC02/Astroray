#include "astroray/pass.h"
#include "astroray/register.h"

class NormalAOV : public Pass {
public:
    explicit NormalAOV(const astroray::ParamDict&) {}
    std::string name() const override { return "Normal AOV"; }
    void execute(Framebuffer&) override {}
};

ASTRORAY_REGISTER_PASS("normal_aov", NormalAOV)
