// Cryptomatte pass plugin skeleton (pkg87a)
// Reads crypto_object / crypto_material buffers and (future pkg87c) writes EXR.
// Non-functional at pkg87a stage — buffers are zero-filled until pkg87b populates them.

#include "astroray/pass.h"
#include "astroray/register.h"
#include "astroray/cryptomatte.h"
#include <cstring>

class CryptomattePass : public Pass {
public:
    explicit CryptomattePass(const astroray::ParamDict&) {}
    std::string name() const override { return "Cryptomatte"; }

    void execute(Framebuffer& fb) override {
        // pkg87a: infrastructure-only. The crypto buffers exist and are
        // zero-filled; nothing populates them yet (that is pkg87b).
        // pkg87c will add EXR write, manifest emission, and Blender integration.
        //
        // For now, validate buffers are accessible (smoke test).
        const float* objBuf = fb.buffer("crypto_object");
        const float* matBuf = fb.buffer("crypto_material");
        if (!objBuf || !matBuf) {
            return;  // Crypto passes not enabled
        }

        // pkg87a acceptance: buffers are allocated and readable.
        // No further action until pkg87b provides data to sort.
        (void)objBuf;
        (void)matBuf;
    }
};

ASTRORAY_REGISTER_PASS("cryptomatte", CryptomattePass)
