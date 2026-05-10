// profile.h — pkg55 Phase A baseline instrumentation.
//
// Env-gated CUDA-event timing + NVTX ranges + one-shot kernel-attribute
// dump for the existing AoS megakernel. Used as the baseline that
// pkg55 Phases B + C (wavefront SoA refactor) must beat.
//
// Activation: set ASTRORAY_PROFILE=1. When unset (production default)
// every helper compiles to a no-op pair of branches around the
// underlying call — zero behaviour change, no extra device work, no
// extra host-side cudaEvent allocations. The "off" branch is what CI
// exercises and what the bit-identical-output gate covers.
//
// Reference patterns (cite, do not mirror code; both Apache-2.0):
//   - blender/cycles intern/cycles/device/cuda/queue.cpp
//     (CUDADeviceQueue::synchronize / enqueue) — per-launch CUDA events
//     gated by a debug flag, written into a flat per-kernel timer table.
//   - mmp/pbrt-v4 src/pbrt/wavefront/wavefront.h + util/profile.h —
//     scoped NVTX ranges around each wavefront stage and a JSON dump
//     on shutdown driven by --profile.
//
// Output: when ASTRORAY_PROFILE=1, summary JSON is written to
// $ASTRORAY_PROFILE_OUT (default: ./astroray_profile.json) at process
// exit via a static destructor. The Python harness
// benchmarks/wavefront_baseline.py runs the renderer once per scene
// with this env var set and aggregates the per-run JSON files into
// benchmarks/wavefront/baseline.json.

#ifndef ASTRORAY_GPU_PROFILE_H
#define ASTRORAY_GPU_PROFILE_H

#include <cuda_runtime.h>
#include <nvtx3/nvToolsExt.h>

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace astroray::gpu_profile {

// Read ASTRORAY_PROFILE once. Cheap subsequent calls.
inline bool enabled() {
    static const bool e = []() {
        const char* v = std::getenv("ASTRORAY_PROFILE");
        return v != nullptr && v[0] != 0 && std::strcmp(v, "0") != 0;
    }();
    return e;
}

struct LaunchStat {
    long long count    = 0;       // number of launches
    double    sum_ms   = 0.0;     // sum of GPU times
    double    min_ms   = 1e30;
    double    max_ms   = 0.0;
    // One-shot kernel attribute snapshot (filled on first observation).
    int       regs_per_thread     = -1;
    int       shared_mem_bytes    = -1;
    int       max_threads_per_blk = -1;
    int       occupancy_blocks    = -1; // active blocks per SM at launch config
    int       launch_threads      = -1;
    int       launch_blocks       = -1;
};

class Aggregator {
public:
    static Aggregator& instance() {
        static Aggregator a;
        return a;
    }
    void record(const std::string& name, double ms, int blocks, int threads,
                const cudaFuncAttributes* attrs, int occ_blocks) {
        std::lock_guard<std::mutex> g(mu_);
        LaunchStat& s = stats_[name];
        s.count++;
        s.sum_ms += ms;
        if (ms < s.min_ms) s.min_ms = ms;
        if (ms > s.max_ms) s.max_ms = ms;
        if (s.regs_per_thread < 0 && attrs) {
            s.regs_per_thread     = attrs->numRegs;
            s.shared_mem_bytes    = (int)attrs->sharedSizeBytes;
            s.max_threads_per_blk = attrs->maxThreadsPerBlock;
            s.occupancy_blocks    = occ_blocks;
            s.launch_threads      = threads;
            s.launch_blocks       = blocks;
        }
    }
    ~Aggregator() {
        if (stats_.empty()) return;
        const char* out = std::getenv("ASTRORAY_PROFILE_OUT");
        std::string path = (out && out[0]) ? out : "astroray_profile.json";
        FILE* fp = std::fopen(path.c_str(), "w");
        if (!fp) {
            std::fprintf(stderr,
                "[astroray-profile] could not open %s for write\n", path.c_str());
            return;
        }
        std::fprintf(fp, "{\n  \"schema\": \"astroray.profile.v1\",\n  \"kernels\": {\n");
        bool first = true;
        for (const auto& [name, s] : stats_) {
            if (!first) std::fprintf(fp, ",\n");
            first = false;
            double mean = s.count > 0 ? s.sum_ms / (double)s.count : 0.0;
            std::fprintf(fp,
                "    \"%s\": {\n"
                "      \"count\": %lld,\n"
                "      \"mean_ms\": %.6f,\n"
                "      \"min_ms\": %.6f,\n"
                "      \"max_ms\": %.6f,\n"
                "      \"sum_ms\": %.6f,\n"
                "      \"regs_per_thread\": %d,\n"
                "      \"shared_mem_bytes\": %d,\n"
                "      \"max_threads_per_block\": %d,\n"
                "      \"active_blocks_per_sm\": %d,\n"
                "      \"launch_threads\": %d,\n"
                "      \"launch_blocks\": %d\n"
                "    }",
                name.c_str(), s.count, mean, s.min_ms, s.max_ms, s.sum_ms,
                s.regs_per_thread, s.shared_mem_bytes, s.max_threads_per_blk,
                s.occupancy_blocks, s.launch_threads, s.launch_blocks);
        }
        std::fprintf(fp, "\n  }\n}\n");
        std::fclose(fp);
        std::fprintf(stderr, "[astroray-profile] wrote %s (%zu kernels)\n",
                     path.c_str(), stats_.size());
    }
private:
    std::mutex mu_;
    std::map<std::string, LaunchStat> stats_;
};

// Scoped NVTX range. No-op when profiling is off.
class NvtxRange {
public:
    explicit NvtxRange(const char* name) : active_(enabled()) {
        if (active_) nvtxRangePushA(name);
    }
    ~NvtxRange() { if (active_) nvtxRangePop(); }
    NvtxRange(const NvtxRange&) = delete;
    NvtxRange& operator=(const NvtxRange&) = delete;
private:
    bool active_;
};

// Scoped CUDA event timer. On destruction (after the wrapped launch's
// implicit/explicit synchronize), records elapsed time + kernel
// attributes into the global Aggregator. No-op when profiling is off.
//
// Usage:
//   {
//     astroray::gpu_profile::ScopedTimer t("path_trace_megakernel",
//         (const void*)pathTraceKernel, blocks, threads);
//     pathTraceKernel<<<blocks,threads>>>(...);
//     cudaDeviceSynchronize();   // launchers already do this
//   }
class ScopedTimer {
public:
    ScopedTimer(const char* name, const void* func_ptr,
                int blocks, int threads)
        : name_(name), func_(func_ptr), blocks_(blocks), threads_(threads),
          active_(enabled()) {
        if (!active_) return;
        nvtxRangePushA(name);
        cudaEventCreate(&start_);
        cudaEventCreate(&stop_);
        cudaEventRecord(start_);
    }
    ~ScopedTimer() {
        if (!active_) return;
        cudaEventRecord(stop_);
        cudaEventSynchronize(stop_);
        float ms = 0.0f;
        cudaEventElapsedTime(&ms, start_, stop_);
        cudaFuncAttributes attrs{};
        const cudaFuncAttributes* attrp = nullptr;
        int active_blocks = 0;
        if (func_) {
            if (cudaFuncGetAttributes(&attrs, func_) == cudaSuccess) attrp = &attrs;
            cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                &active_blocks, func_, threads_, 0);
        }
        Aggregator::instance().record(name_, (double)ms, blocks_, threads_,
                                      attrp, active_blocks);
        cudaEventDestroy(start_);
        cudaEventDestroy(stop_);
        nvtxRangePop();
    }
    ScopedTimer(const ScopedTimer&) = delete;
    ScopedTimer& operator=(const ScopedTimer&) = delete;
private:
    const char* name_;
    const void* func_;
    int blocks_;
    int threads_;
    bool active_;
    cudaEvent_t start_{}, stop_{};
};

}  // namespace astroray::gpu_profile

#endif  // ASTRORAY_GPU_PROFILE_H
