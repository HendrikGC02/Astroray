#ifdef _WIN32
#  define NOMINMAX
#endif

// pkg70 — NVIDIA OptiX AI denoiser as a co-equal alternative to OIDN.
// pkg73 — Extended with TEMPORAL_AOV mode when pkg72's motion buffer is
//         present and non-zero. Mode is selected per execute(); model-kind
//         transitions destroy + recreate the OptiX denoiser handle (the
//         model kind is locked at optixDenoiserCreate time).
//
// Mirrors the pkg68 OIDN class shape (member-cached state, lazy init,
// dimension-cached buffers). Where OIDN owns its own device, here we
// piggyback on the CUDA driver context that the runtime already opens
// for the path tracer (cuda_renderer.cu) — OptiX accepts a
// CUcontext/CUstream pair via optixDeviceContextCreate.
//
// References:
//   - OptiX 8 Programming Guide, "AI-Accelerated Denoiser":
//     https://raytracing-docs.nvidia.com/optix8/guide/index.html#ai_denoiser
//   - OptiX 8 host API:
//     https://raytracing-docs.nvidia.com/optix8/api/optix__host_8h.html
//   - Cycles `intern/cycles/device/optix/device_impl.cpp`
//     (Apache-2.0) — `OptiXDevice::denoise_buffer()` for the
//     setup/invoke shape, model-kind selection, and the
//     destroy-and-recreate transition pattern used in pkg73.
//   - Cycles `intern/cycles/integrator/denoiser_gpu.cpp` (Apache-2.0)
//     — temporal previous-output lifecycle + resize invalidation.
//
// Constraints (per pkg70/pkg73 spec):
//   - HDR model when no guides; AOV model when albedo+normal both present;
//     TEMPORAL_AOV when motion+albedo+normal are all present and motion
//     is non-zero (static cameras stay on AOV — no point paying the
//     prev-output buffer cost).
//   - No SDK headers redistributed: build only when find_package(OptiX)
//     succeeds and ASTRORAY_OPTIX_ENABLED is defined.

#include "astroray/pass.h"
#include "astroray/register.h"

#include <cstdio>
#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef ASTRORAY_OPTIX_ENABLED
#  include <cuda_runtime.h>
#  include <optix.h>
#  include <optix_function_table_definition.h>
#  include <optix_stubs.h>

namespace {

// One-shot OptiX function table init. Returns true on success.
bool ensureOptixInit_() {
    static bool tried = false;
    static bool ok    = false;
    if (tried) return ok;
    tried = true;
    OptixResult r = optixInit();
    ok = (r == OPTIX_SUCCESS);
    if (!ok) {
        std::fprintf(stderr, "[OptiX] optixInit failed (%d)\n", static_cast<int>(r));
    }
    return ok;
}

void optixLogCallback_(unsigned int level, const char* tag,
                       const char* message, void*) {
    // Levels: 1 fatal, 2 error, 3 warning, 4 print. Surface fatals/errors
    // unconditionally; everything else only at >= warning to avoid spam.
    if (level <= 3) {
        std::fprintf(stderr, "[OptiX %s] %s\n", tag ? tag : "?", message ? message : "");
    }
}

#define ASTRORAY_OPTIX_CHECK(expr) do {                                        \
        OptixResult _r = (expr);                                               \
        if (_r != OPTIX_SUCCESS) {                                             \
            throw std::runtime_error(std::string("OptiX call failed: " #expr " -> ") \
                                     + std::to_string(static_cast<int>(_r)));  \
        }                                                                      \
    } while (0)

#define ASTRORAY_CUDA_CHECK(expr) do {                                         \
        cudaError_t _e = (expr);                                               \
        if (_e != cudaSuccess) {                                               \
            throw std::runtime_error(std::string("CUDA call failed: " #expr " -> ") \
                                     + cudaGetErrorString(_e));                \
        }                                                                      \
    } while (0)

} // namespace
#endif // ASTRORAY_OPTIX_ENABLED


class OptiXDenoiser : public Pass {
public:
    explicit OptiXDenoiser(const astroray::ParamDict&) {}

    ~OptiXDenoiser() override {
#ifdef ASTRORAY_OPTIX_ENABLED
        try { destroy_(); } catch (...) {}
#endif
    }

    std::string name() const override { return "OptiX Denoiser"; }

    void execute(Framebuffer& fb) override {
#ifdef ASTRORAY_OPTIX_ENABLED
        const int w = fb.width();
        const int h = fb.height();
        const size_t pixels = static_cast<size_t>(w) * static_cast<size_t>(h);
        if (pixels == 0) return;

        const float* srcColor  = fb.buffer("color");
        const float* srcAlbedo = fb.hasBuffer("albedo") ? fb.buffer("albedo") : nullptr;
        const float* srcNormal = fb.hasBuffer("normal") ? fb.buffer("normal") : nullptr;
        const float* srcMotion = fb.hasBuffer("motion") ? fb.buffer("motion") : nullptr;
        const bool   hasGuides = (srcAlbedo != nullptr) && (srcNormal != nullptr);

        // pkg73: only upgrade to TEMPORAL_AOV when motion is actually moving.
        // pkg72 zero-fills the motion buffer for static cameras, sky pixels,
        // and the first frame after setup_camera; in those cases the prev-
        // output buffer + ping-pong internal-guide pair is wasted memory.
        bool hasNonzeroMotion = false;
        if (srcMotion) {
            const size_t n2 = pixels * 2;
            for (size_t i = 0; i < n2; ++i) {
                if (srcMotion[i] != 0.0f) {
                    hasNonzeroMotion = true;
                    break;
                }
            }
        }

        OptixDenoiserModelKind desiredKind;
        if (hasGuides && hasNonzeroMotion) {
            desiredKind = OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV;
        } else if (hasGuides) {
            desiredKind = OPTIX_DENOISER_MODEL_KIND_AOV;
        } else {
            desiredKind = OPTIX_DENOISER_MODEL_KIND_HDR;
        }

        if (!initialised_) {
            initContext_();
            modelKind_ = desiredKind;
            createDenoiser_();
            initialised_ = true;
        } else if (desiredKind != modelKind_) {
            // Mirror Cycles `device_impl.cpp`: model kind is locked at
            // optixDenoiserCreate time, so transitioning means destroy +
            // recreate. Buffers tied to the handle (state + scratch +
            // internal-guide pair + prev-output) are also freed and will
            // be reallocated below.
            std::printf("[OptiX] denoiser model kind transition %d -> %d\n",
                        static_cast<int>(modelKind_), static_cast<int>(desiredKind));
            std::fflush(stdout);
            freeDeviceBuffers_();
            if (denoiser_) { optixDenoiserDestroy(denoiser_); denoiser_ = nullptr; }
            modelKind_    = desiredKind;
            cachedWidth_  = 0;  // force allocateBuffers_ on next branch
            cachedHeight_ = 0;
            prev_valid_   = false;
            frame_index_  = 0;
            createDenoiser_();
        }

        if (w != cachedWidth_ || h != cachedHeight_) {
            // pkg73: prev-output is sized for the old resolution; drop it
            // (allocateBuffers_ recreates) and treat next frame as first.
            allocateBuffers_(w, h);
            cachedWidth_  = w;
            cachedHeight_ = h;
            prev_valid_   = false;
            frame_index_  = 0;
        }

        const bool isTemporal = (modelKind_ == OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV);
        const bool isAOV      = (modelKind_ == OPTIX_DENOISER_MODEL_KIND_AOV) || isTemporal;

        // Sanitize NaNs/Infs in the host buffers (path tracer can produce
        // them from very-rare divide edge cases) before HtoD copy. Mirrors
        // the OIDN plugin's safeF lambda.
        const size_t rgbBytes = pixels * 3 * sizeof(float);
        sanitised_.resize(pixels * 3);
        auto sanitiseInto = [&](const float* src) {
            for (size_t i = 0; i < pixels * 3; ++i) {
                const float v = src[i];
                sanitised_[i] = std::isfinite(v) ? v : 0.0f;
            }
        };

        sanitiseInto(srcColor);
        ASTRORAY_CUDA_CHECK(cudaMemcpy(reinterpret_cast<void*>(colorDev_),
                                       sanitised_.data(), rgbBytes,
                                       cudaMemcpyHostToDevice));
        if (isAOV) {
            sanitiseInto(srcAlbedo);
            ASTRORAY_CUDA_CHECK(cudaMemcpy(reinterpret_cast<void*>(albedoDev_),
                                           sanitised_.data(), rgbBytes,
                                           cudaMemcpyHostToDevice));
            // Normalise normals before upload (OIDN plugin does the same;
            // OptiX expects unit-length normals). pkg70 §6 confirms our
            // normal buffer is camera-space-3-channel, which is what
            // TEMPORAL_AOV's normal-guide rule also requires.
            for (size_t i = 0; i < pixels; ++i) {
                float nx = std::isfinite(srcNormal[i*3+0]) ? srcNormal[i*3+0] : 0.0f;
                float ny = std::isfinite(srcNormal[i*3+1]) ? srcNormal[i*3+1] : 0.0f;
                float nz = std::isfinite(srcNormal[i*3+2]) ? srcNormal[i*3+2] : 0.0f;
                const float len = std::sqrt(nx*nx + ny*ny + nz*nz);
                if (len > 0.0f) { nx /= len; ny /= len; nz /= len; }
                sanitised_[i*3+0] = nx;
                sanitised_[i*3+1] = ny;
                sanitised_[i*3+2] = nz;
            }
            ASTRORAY_CUDA_CHECK(cudaMemcpy(reinterpret_cast<void*>(normalDev_),
                                           sanitised_.data(), rgbBytes,
                                           cudaMemcpyHostToDevice));
        }
        if (isTemporal) {
            // pkg72 writes motion as `prev_pixel - curr_pixel` in pixel units
            // (see pkg72 Lessons "Sign convention"), which is exactly the
            // OptixDenoiserGuideLayer::flow contract — no remap here.
            const size_t flowBytes = pixels * 2 * sizeof(float);
            sanitisedFlow_.resize(pixels * 2);
            for (size_t i = 0; i < pixels * 2; ++i) {
                const float v = srcMotion[i];
                sanitisedFlow_[i] = std::isfinite(v) ? v : 0.0f;
            }
            ASTRORAY_CUDA_CHECK(cudaMemcpy(reinterpret_cast<void*>(motionDev_),
                                           sanitisedFlow_.data(), flowBytes,
                                           cudaMemcpyHostToDevice));
        }

        // Build per-frame layer/guide descriptors.
        OptixImage2D colorImg  = makeImage_(colorDev_,  w, h);
        OptixImage2D outputImg = makeImage_(outputDev_, w, h);

        OptixDenoiserLayer layer = {};
        layer.input  = colorImg;
        layer.output = outputImg;
        if (isTemporal) {
            // First-frame fallback per the OptiX programming guide: when no
            // valid prev-output exists yet, feed the noisy current beauty as
            // previousOutput and rely on pkg72's zero-fill flow.
            CUdeviceptr prev = prev_valid_ ? prevOutputDev_ : colorDev_;
            layer.previousOutput = makeImage_(prev, w, h);
        }

        OptixDenoiserGuideLayer guide = {};
        if (isAOV) {
            guide.albedo = makeImage_(albedoDev_, w, h);
            guide.normal = makeImage_(normalDev_, w, h);
        }
        if (isTemporal) {
            guide.flow = makeFlowImage_(motionDev_, w, h);
            // Internal-guide-layer ping-pong: this frame's `output` becomes
            // next frame's `previous`. Mirror Cycles `device_impl.cpp`.
            const int prevSlot = (frame_index_ & 1);
            const int currSlot = 1 - prevSlot;
            guide.previousOutputInternalGuideLayer =
                makeInternalGuideImage_(internalGuideDev_[prevSlot], w, h);
            guide.outputInternalGuideLayer =
                makeInternalGuideImage_(internalGuideDev_[currSlot], w, h);
        }

        // Compute intensity (HDR exposure normalisation). Documented to
        // work for HDR, AOV and TEMPORAL_AOV models.
        ASTRORAY_OPTIX_CHECK(optixDenoiserComputeIntensity(
            denoiser_, /*stream*/ 0,
            &colorImg, intensityDev_,
            scratchDev_, scratchSize_));

        OptixDenoiserParams params = {};
        params.hdrIntensity      = intensityDev_;
        params.blendFactor       = 0.0f;
        params.hdrAverageColor   = 0;
        // Older OptiX 7.x SDKs had `denoiseAlpha` as a bool field; OptiX 8
        // moved it to an enum (OPTIX_DENOISER_ALPHA_MODE_*). 3-channel
        // float means the default zero-init is correct for both ABIs.
        // pkg73 defect-2026-05-10: `temporalModeUsePreviousLayers` must be
        // 1 on the second and subsequent frames so OptiX actually consumes
        // previousOutput + previousOutputInternalGuideLayer; otherwise
        // every frame is treated as the start of a new sequence and the
        // temporal accumulation is silently dropped (rms_t ~= rms_a).
        // See OptiX SDK 9.1 optix_types.h::OptixDenoiserParams docs.
        if (isTemporal) {
            params.temporalModeUsePreviousLayers = prev_valid_ ? 1u : 0u;
        }

        ASTRORAY_OPTIX_CHECK(optixDenoiserInvoke(
            denoiser_, /*stream*/ 0, &params,
            stateDev_, stateSize_,
            &guide, &layer, /*numLayers*/ 1,
            /*offsetX*/ 0, /*offsetY*/ 0,
            scratchDev_, scratchSize_));

        ASTRORAY_CUDA_CHECK(cudaDeviceSynchronize());

        if (isTemporal) {
            // Cache denoised output for next frame's previousOutput binding.
            ASTRORAY_CUDA_CHECK(cudaMemcpy(reinterpret_cast<void*>(prevOutputDev_),
                                           reinterpret_cast<void*>(outputDev_),
                                           rgbBytes, cudaMemcpyDeviceToDevice));
            prev_valid_ = true;
            ++frame_index_;
        }

        // DtoH copy back into the framebuffer's color buffer, clamping
        // any residual non-finite or negative values.
        ASTRORAY_CUDA_CHECK(cudaMemcpy(sanitised_.data(),
                                       reinterpret_cast<void*>(outputDev_),
                                       rgbBytes, cudaMemcpyDeviceToHost));
        float* dst = fb.buffer("color");
        for (size_t i = 0; i < pixels * 3; ++i) {
            const float v = sanitised_[i];
            dst[i] = std::isfinite(v) ? std::max(v, 0.0f) : 0.0f;
        }
#else
        (void)fb;
#endif
    }

private:
#ifdef ASTRORAY_OPTIX_ENABLED
    void initContext_() {
        if (!ensureOptixInit_()) {
            throw std::runtime_error("OptiX function table init failed (no NVIDIA driver?)");
        }

        // Force a CUDA primary context to exist on the current device. We
        // share whatever the runtime already opened in cuda_renderer.cu;
        // calling cudaFree(0) is the documented way to lazily create the
        // primary context without taking a runtime API dependency.
        ASTRORAY_CUDA_CHECK(cudaFree(0));

        OptixDeviceContextOptions ctxOpts = {};
        ctxOpts.logCallbackFunction = &optixLogCallback_;
        ctxOpts.logCallbackLevel    = 3; // warnings + errors
        // CUcontext = nullptr → use the current thread's primary context.
        ASTRORAY_OPTIX_CHECK(optixDeviceContextCreate(/*ctx*/ 0, &ctxOpts, &context_));

        int dev = 0;
        ASTRORAY_CUDA_CHECK(cudaGetDevice(&dev));
        cudaDeviceProp props{};
        if (cudaGetDeviceProperties(&props, dev) == cudaSuccess) {
            std::printf("[OptiX] Using CUDA device %d (%s)\n", dev, props.name);
        } else {
            // pkg85-B: clear the latent error so it doesn't contaminate
            // the next CUDA call. The print is informational; failure
            // here is non-fatal but the error must not persist.
            cudaGetLastError();
            std::printf("[OptiX] Using CUDA device %d\n", dev);
        }
        std::fflush(stdout);
    }

    void createDenoiser_() {
        OptixDenoiserOptions opts = {};
        if (modelKind_ == OPTIX_DENOISER_MODEL_KIND_AOV ||
            modelKind_ == OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV) {
            opts.guideAlbedo = 1;
            opts.guideNormal = 1;
        }
        ASTRORAY_OPTIX_CHECK(optixDenoiserCreate(context_, modelKind_, &opts, &denoiser_));
        std::printf("[OptiX] denoiser created (kind=%d%s)\n",
                    static_cast<int>(modelKind_),
                    modelKind_ == OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV
                        ? " TEMPORAL_AOV" : "");
        std::fflush(stdout);
    }

    void allocateBuffers_(int w, int h) {
        // Free anything previously allocated.
        freeDeviceBuffers_();

        OptixDenoiserSizes sizes = {};
        ASTRORAY_OPTIX_CHECK(optixDenoiserComputeMemoryResources(
            denoiser_, static_cast<unsigned int>(w),
            static_cast<unsigned int>(h), &sizes));

        stateSize_   = sizes.stateSizeInBytes;
        scratchSize_ = sizes.withoutOverlapScratchSizeInBytes;

        ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&stateDev_),   stateSize_));
        ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&scratchDev_), scratchSize_));

        const size_t rgbBytes = static_cast<size_t>(w) * h * 3 * sizeof(float);
        ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&colorDev_),  rgbBytes));
        ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&outputDev_), rgbBytes));
        if (modelKind_ == OPTIX_DENOISER_MODEL_KIND_AOV ||
            modelKind_ == OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV) {
            ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&albedoDev_), rgbBytes));
            ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&normalDev_), rgbBytes));
        }
        ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&intensityDev_), sizeof(float)));

        if (modelKind_ == OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV) {
            const size_t flowBytes = static_cast<size_t>(w) * h * 2 * sizeof(float);
            ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&motionDev_),     flowBytes));
            ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&prevOutputDev_), rgbBytes));

            // Internal-guide-layer pair (ping-pong). Size in bytes per pixel
            // is reported by optixDenoiserComputeMemoryResources (OptiX 7.5+
            // OptixDenoiserSizes::internalGuideLayerPixelSizeInBytes).
            const size_t igBytes = static_cast<size_t>(w) * h *
                sizes.internalGuideLayerPixelSizeInBytes;
            ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&internalGuideDev_[0]), igBytes));
            ASTRORAY_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&internalGuideDev_[1]), igBytes));
            ASTRORAY_CUDA_CHECK(cudaMemset(reinterpret_cast<void*>(internalGuideDev_[0]), 0, igBytes));
            ASTRORAY_CUDA_CHECK(cudaMemset(reinterpret_cast<void*>(internalGuideDev_[1]), 0, igBytes));
            internalGuidePixelSize_ = sizes.internalGuideLayerPixelSizeInBytes;
        }

        ASTRORAY_OPTIX_CHECK(optixDenoiserSetup(
            denoiser_, /*stream*/ 0,
            static_cast<unsigned int>(w), static_cast<unsigned int>(h),
            stateDev_, stateSize_,
            scratchDev_, scratchSize_));
    }

    OptixImage2D makeImage_(CUdeviceptr ptr, int w, int h) const {
        OptixImage2D img = {};
        img.data               = ptr;
        img.width              = static_cast<unsigned int>(w);
        img.height             = static_cast<unsigned int>(h);
        img.rowStrideInBytes   = static_cast<unsigned int>(w) * 3 * sizeof(float);
        img.pixelStrideInBytes = 3 * sizeof(float);
        img.format             = OPTIX_PIXEL_FORMAT_FLOAT3;
        return img;
    }

    OptixImage2D makeFlowImage_(CUdeviceptr ptr, int w, int h) const {
        OptixImage2D img = {};
        img.data               = ptr;
        img.width              = static_cast<unsigned int>(w);
        img.height             = static_cast<unsigned int>(h);
        img.rowStrideInBytes   = static_cast<unsigned int>(w) * 2 * sizeof(float);
        img.pixelStrideInBytes = 2 * sizeof(float);
        img.format             = OPTIX_PIXEL_FORMAT_FLOAT2;
        return img;
    }

    OptixImage2D makeInternalGuideImage_(CUdeviceptr ptr, int w, int h) const {
        OptixImage2D img = {};
        img.data               = ptr;
        img.width              = static_cast<unsigned int>(w);
        img.height             = static_cast<unsigned int>(h);
        img.rowStrideInBytes   = static_cast<unsigned int>(w) *
            static_cast<unsigned int>(internalGuidePixelSize_);
        img.pixelStrideInBytes = static_cast<unsigned int>(internalGuidePixelSize_);
        img.format             = OPTIX_PIXEL_FORMAT_INTERNAL_GUIDE_LAYER;
        return img;
    }

    void freeDeviceBuffers_() {
        auto freeIf = [](CUdeviceptr& p) {
            if (p) { cudaFree(reinterpret_cast<void*>(p)); p = 0; }
        };
        // pkg85-B: see below — clear any latent free error at end of scope
        // so denoiser teardown doesn't leak state into the next CUDA call.
        freeIf(stateDev_);
        freeIf(scratchDev_);
        freeIf(colorDev_);
        freeIf(albedoDev_);
        freeIf(normalDev_);
        freeIf(outputDev_);
        freeIf(intensityDev_);
        freeIf(motionDev_);
        freeIf(prevOutputDev_);
        freeIf(internalGuideDev_[0]);
        freeIf(internalGuideDev_[1]);
        stateSize_              = 0;
        scratchSize_            = 0;
        internalGuidePixelSize_ = 0;
        cudaGetLastError();  // pkg85-B: swallow cudaFree errors in cleanup.
    }

    void destroy_() {
        freeDeviceBuffers_();
        if (denoiser_) { optixDenoiserDestroy(denoiser_); denoiser_ = nullptr; }
        if (context_)  { optixDeviceContextDestroy(context_); context_ = nullptr; }
    }

    OptixDeviceContext      context_      = nullptr;
    OptixDenoiser           denoiser_     = nullptr;
    OptixDenoiserModelKind  modelKind_    = OPTIX_DENOISER_MODEL_KIND_HDR;
    CUdeviceptr             stateDev_     = 0;
    CUdeviceptr             scratchDev_   = 0;
    CUdeviceptr             colorDev_     = 0;
    CUdeviceptr             albedoDev_    = 0;
    CUdeviceptr             normalDev_    = 0;
    CUdeviceptr             outputDev_    = 0;
    CUdeviceptr             intensityDev_ = 0;
    // pkg73 TEMPORAL_AOV state.
    CUdeviceptr             motionDev_           = 0;
    CUdeviceptr             prevOutputDev_       = 0;
    CUdeviceptr             internalGuideDev_[2] = {0, 0};
    size_t                  internalGuidePixelSize_ = 0;
    int                     frame_index_  = 0;
    bool                    prev_valid_   = false;
    size_t                  stateSize_    = 0;
    size_t                  scratchSize_  = 0;
    int                     cachedWidth_  = 0;
    int                     cachedHeight_ = 0;
    bool                    initialised_  = false;
    std::vector<float>      sanitised_;
    std::vector<float>      sanitisedFlow_;
#endif
};

ASTRORAY_REGISTER_PASS("optix_denoiser", OptiXDenoiser)
