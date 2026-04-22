#ifdef ASTRORAY_OIDN_ENABLED
#  if __has_include(<OpenImageDenoise/oidn.hpp>)
#    include <OpenImageDenoise/oidn.hpp>
#  elif __has_include(<oidn.hpp>)
#    include <oidn.hpp>
#  endif
#endif

#include "astroray/pass.h"
#include "astroray/register.h"

class OIDNDenoiser : public Pass {
public:
    explicit OIDNDenoiser(const astroray::ParamDict&) {}

    std::string name() const override { return "OIDN Denoiser"; }

    void execute(Framebuffer& fb) override {
#ifdef ASTRORAY_OIDN_ENABLED
        const int w = fb.width();
        const int h = fb.height();
        const size_t pixelCount = static_cast<size_t>(w * h);
        if (pixelCount == 0) return;

        const size_t byteSize = pixelCount * 3 * sizeof(float);

        oidn::DeviceRef device = oidn::newDevice();
        device.commit();

        oidn::BufferRef colorBuf  = device.newBuffer(byteSize);
        oidn::BufferRef albedoBuf = device.newBuffer(byteSize);
        oidn::BufferRef normalBuf = device.newBuffer(byteSize);
        oidn::BufferRef outputBuf = device.newBuffer(byteSize);

        float* colorData  = static_cast<float*>(colorBuf.getData());
        float* albedoData = static_cast<float*>(albedoBuf.getData());
        float* normalData = static_cast<float*>(normalBuf.getData());

        const float* srcColor  = fb.buffer("color");
        const float* srcAlbedo = fb.hasBuffer("albedo") ? fb.buffer("albedo") : nullptr;
        const float* srcNormal = fb.hasBuffer("normal") ? fb.buffer("normal") : nullptr;

        auto safeF = [](float v) { return std::isfinite(v) ? v : 0.0f; };
        for (size_t i = 0; i < pixelCount; ++i) {
            colorData[i*3]   = safeF(srcColor[i*3]);
            colorData[i*3+1] = safeF(srcColor[i*3+1]);
            colorData[i*3+2] = safeF(srcColor[i*3+2]);

            if (srcAlbedo) {
                albedoData[i*3]   = safeF(srcAlbedo[i*3]);
                albedoData[i*3+1] = safeF(srcAlbedo[i*3+1]);
                albedoData[i*3+2] = safeF(srcAlbedo[i*3+2]);
            }

            if (srcNormal) {
                float nx = safeF(srcNormal[i*3]);
                float ny = safeF(srcNormal[i*3+1]);
                float nz = safeF(srcNormal[i*3+2]);
                float len = std::sqrt(nx*nx + ny*ny + nz*nz);
                if (len > 0.0f) { nx /= len; ny /= len; nz /= len; }
                normalData[i*3]   = nx;
                normalData[i*3+1] = ny;
                normalData[i*3+2] = nz;
            }
        }

        oidn::FilterRef filter = device.newFilter("RT");
        filter.setImage("color",  colorBuf,  oidn::Format::Float3, w, h);
        if (srcAlbedo) filter.setImage("albedo", albedoBuf, oidn::Format::Float3, w, h);
        if (srcNormal) filter.setImage("normal", normalBuf, oidn::Format::Float3, w, h);
        filter.setImage("output", outputBuf, oidn::Format::Float3, w, h);
        filter.set("hdr", true);
        filter.commit();
        filter.execute();

        const char* errorMessage = nullptr;
        if (device.getError(errorMessage) != oidn::Error::None) {
            throw std::runtime_error(std::string("OIDN denoiser failed: ") +
                                     (errorMessage ? errorMessage : "unknown error"));
        }

        float* dst = fb.buffer("color");
        const float* outputData = static_cast<const float*>(outputBuf.getData());
        for (size_t i = 0; i < pixelCount; ++i) {
            const float r = outputData[i*3];
            const float g = outputData[i*3+1];
            const float b = outputData[i*3+2];
            dst[i*3]   = std::isfinite(r) ? std::max(r, 0.0f) : 0.0f;
            dst[i*3+1] = std::isfinite(g) ? std::max(g, 0.0f) : 0.0f;
            dst[i*3+2] = std::isfinite(b) ? std::max(b, 0.0f) : 0.0f;
        }
#endif
    }
};

ASTRORAY_REGISTER_PASS("oidn_denoiser", OIDNDenoiser)
