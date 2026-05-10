#ifdef ASTRORAY_OIDN_ENABLED
#  if __has_include(<OpenImageDenoise/oidn.hpp>)
#    include <OpenImageDenoise/oidn.hpp>
#  elif __has_include(<oidn.hpp>)
#    include <oidn.hpp>
#  endif
#endif

#include <cstdio>

#include "astroray/pass.h"
#include "astroray/register.h"

// pkg68: Persistent OIDN device + filter, lazy-initialised on first execute().
// The previous implementation rebuilt the device, allocated four buffers, and
// rebuilt the "RT" filter on every frame, which is the dominant per-frame cost
// for OIDN at viewport SPP. The Cycles denoiser caches the device and filter
// as members of the denoiser class — see
// intern/cycles/integrator/denoiser_oidn.cpp / denoiser_oidn_gpu.cpp in the
// Blender repository (Apache-2.0). We mirror that pattern here:
//   * device + filter live as class members
//   * device init tries CUDA first, falls back to CPU (Cycles' create_device shape)
//   * buffers are reallocated only when the framebuffer dimensions change
//   * filter is rebuilt only when the source pointers/dims change
class OIDNDenoiser : public Pass {
public:
    explicit OIDNDenoiser(const astroray::ParamDict&) {}

    std::string name() const override { return "OIDN Denoiser"; }

    void execute(Framebuffer& fb) override {
#ifdef ASTRORAY_OIDN_ENABLED
        const int w = fb.width();
        const int h = fb.height();
        const size_t pixelCount = static_cast<size_t>(w) * static_cast<size_t>(h);
        if (pixelCount == 0) return;

        const size_t byteSize = pixelCount * 3 * sizeof(float);

        if (!deviceInitialised_) {
            initDevice_();
            deviceInitialised_ = true;
        }

        const float* srcColor  = fb.buffer("color");
        const float* srcAlbedo = fb.hasBuffer("albedo") ? fb.buffer("albedo") : nullptr;
        const float* srcNormal = fb.hasBuffer("normal") ? fb.buffer("normal") : nullptr;

        // (Re)allocate buffers when the framebuffer geometry changes.
        if (w != cachedWidth_ || h != cachedHeight_) {
            colorBuf_  = device_.newBuffer(byteSize);
            albedoBuf_ = device_.newBuffer(byteSize);
            normalBuf_ = device_.newBuffer(byteSize);
            outputBuf_ = device_.newBuffer(byteSize);
            cachedWidth_  = w;
            cachedHeight_ = h;
            // Force filter rebind on next bind check.
            lastBoundColor_  = nullptr;
            lastBoundAlbedo_ = nullptr;
            lastBoundNormal_ = nullptr;
            filterReady_ = false;
        }

        float* colorData  = static_cast<float*>(colorBuf_.getData());
        float* albedoData = static_cast<float*>(albedoBuf_.getData());
        float* normalData = static_cast<float*>(normalBuf_.getData());

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

        // Rebind the filter only when the source pointers (or dims, handled
        // above) change. setImage + commit is the expensive part we want to
        // avoid on every frame.
        const bool needRebind = !filterReady_ ||
            srcColor  != lastBoundColor_  ||
            srcAlbedo != lastBoundAlbedo_ ||
            srcNormal != lastBoundNormal_;

        if (needRebind) {
            filter_ = device_.newFilter("RT");
            filter_.setImage("color",  colorBuf_,  oidn::Format::Float3, w, h);
            if (srcAlbedo) filter_.setImage("albedo", albedoBuf_, oidn::Format::Float3, w, h);
            if (srcNormal) filter_.setImage("normal", normalBuf_, oidn::Format::Float3, w, h);
            filter_.setImage("output", outputBuf_, oidn::Format::Float3, w, h);
            filter_.set("hdr", true);
            filter_.commit();
            lastBoundColor_  = srcColor;
            lastBoundAlbedo_ = srcAlbedo;
            lastBoundNormal_ = srcNormal;
            filterReady_ = true;
        }

        filter_.execute();

        const char* errorMessage = nullptr;
        if (device_.getError(errorMessage) != oidn::Error::None) {
            throw std::runtime_error(std::string("OIDN denoiser failed: ") +
                                     (errorMessage ? errorMessage : "unknown error"));
        }

        float* dst = fb.buffer("color");
        const float* outputData = static_cast<const float*>(outputBuf_.getData());
        for (size_t i = 0; i < pixelCount; ++i) {
            const float r = outputData[i*3];
            const float g = outputData[i*3+1];
            const float b = outputData[i*3+2];
            dst[i*3]   = std::isfinite(r) ? std::max(r, 0.0f) : 0.0f;
            dst[i*3+1] = std::isfinite(g) ? std::max(g, 0.0f) : 0.0f;
            dst[i*3+2] = std::isfinite(b) ? std::max(b, 0.0f) : 0.0f;
        }
#else
        (void)fb;
#endif
    }

private:
#ifdef ASTRORAY_OIDN_ENABLED
    // Cycles' create_device() shape: try the GPU type the build was compiled
    // for, fall back to CPU. OIDN's C API returns a NULL handle if the
    // requested DeviceType is unsupported; the C++ wrapper exposes that as a
    // non-None error from getError() before commit().
    void initDevice_() {
        oidn::DeviceRef dev = oidn::newDevice(oidn::DeviceType::CUDA);
        const char* perr = nullptr;
        bool cudaOk = (dev.getError(perr) == oidn::Error::None);
        if (cudaOk) {
            dev.commit();
            const char* perr2 = nullptr;
            cudaOk = (dev.getError(perr2) == oidn::Error::None);
        }

        if (!cudaOk) {
            dev = oidn::newDevice(oidn::DeviceType::CPU);
            dev.commit();
            const char* perr3 = nullptr;
            if (dev.getError(perr3) != oidn::Error::None) {
                throw std::runtime_error(std::string("OIDN CPU device init failed: ") +
                                         (perr3 ? perr3 : "unknown error"));
            }
            std::printf("[OIDN] Using CPU device\n");
        } else {
            std::printf("[OIDN] Using CUDA device\n");
        }
        std::fflush(stdout);
        device_ = dev;
    }

    oidn::DeviceRef device_;
    oidn::FilterRef filter_;
    oidn::BufferRef colorBuf_;
    oidn::BufferRef albedoBuf_;
    oidn::BufferRef normalBuf_;
    oidn::BufferRef outputBuf_;
    bool deviceInitialised_ = false;
    bool filterReady_       = false;
    int  cachedWidth_       = 0;
    int  cachedHeight_      = 0;
    const float* lastBoundColor_  = nullptr;
    const float* lastBoundAlbedo_ = nullptr;
    const float* lastBoundNormal_ = nullptr;
#endif
};

ASTRORAY_REGISTER_PASS("oidn_denoiser", OIDNDenoiser)
