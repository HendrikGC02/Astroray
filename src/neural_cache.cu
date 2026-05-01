// src/neural_cache.cu — NeuralCache implementation (pkg26).
// Compiled only when ASTRORAY_TINY_CUDA_NN=ON.
//
// Uses tcnn::create_from_config to build a FullyFusedMLP + Adam + RelativeL2
// loss in one shot. Training is done via tcnn::Trainer::training_step().

#include "neural_cache.h"

// tcnn master on CUDA 12.8 auto-detects Blackwell (sm_120) as TCNN_MIN_GPU_ARCH.
// Override for sm_89 (Ada) before any tcnn header sees it.
#ifdef TCNN_MIN_GPU_ARCH
#undef TCNN_MIN_GPU_ARCH
#endif
#define TCNN_MIN_GPU_ARCH 89

#include <tiny-cuda-nn/config.h>   // create_from_config, TrainableModel
// nlohmann::json is brought in transitively by tiny-cuda-nn/config.h
#include <cuda_runtime.h>

#include <cstdio>
#include <stdexcept>

using json = nlohmann::json;
using T    = tcnn::network_precision_t;   // __half on sm_70+

#define CUDA_CHECK(call) do {                                                  \
    cudaError_t _e = (call);                                                   \
    if (_e != cudaSuccess) {                                                   \
        fprintf(stderr, "CUDA error %s:%d: %s\n",                             \
                __FILE__, __LINE__, cudaGetErrorString(_e));                   \
        throw std::runtime_error(cudaGetErrorString(_e));                     \
    }                                                                           \
} while (0)

// ---------------------------------------------------------------------------
// Opaque implementation backed by a tcnn::TrainableModel
// ---------------------------------------------------------------------------
struct NeuralCache::Impl {
    tcnn::TrainableModel model;
};

NeuralCache::NeuralCache() : impl_(std::make_unique<Impl>()) {
    json config = {
        // RelativeL2 handles high-dynamic-range radiance better than plain L2.
        {"loss",     {{"otype", "RelativeL2"}}},
        // Adam lr=1e-3 per spec.
        {"optimizer",{{"otype", "Adam"}, {"learning_rate", 1e-3}}},
        // Identity encoding: pass 16 floats straight to the MLP.
        {"encoding", {{"otype", "Identity"}, {"n_dims_to_encode", N_IN}}},
        // 2 hidden layers of 64 neurons per spec; ReLU hidden, linear output.
        {"network",  {
            {"otype",              "FullyFusedMLP"},
            {"n_neurons",         64},
            {"n_hidden_layers",   2},
            {"activation",        "ReLU"},
            {"output_activation", "None"}
        }}
    };
    impl_->model = tcnn::create_from_config(N_IN, N_OUT, config);
}

NeuralCache::~NeuralCache() = default;

// ---------------------------------------------------------------------------
// query — batch GPU inference (use_inference_params=true)
// ---------------------------------------------------------------------------
std::vector<Vec3> NeuralCache::query(uint32_t n, const std::vector<float>& inputs) {
    if (n == 0) return {};
    if (n % BATCH_ALIGN != 0)
        throw std::invalid_argument("NeuralCache::query: n must be a multiple of BATCH_ALIGN");

    // Upload inputs: host layout [n × N_IN] (sample-major) == column-major [N_IN × n].
    tcnn::GPUMatrix<float> gpu_in(N_IN, n);
    CUDA_CHECK(cudaMemcpy(gpu_in.data(), inputs.data(),
                          (size_t)n * N_IN * sizeof(float), cudaMemcpyHostToDevice));

    // Allocate output [N_OUT × n] in __half.
    tcnn::GPUMatrix<T> gpu_out(N_OUT, n);

    // Inference: use_inference_params=true so we read the EMA/inference copy.
    impl_->model.network->forward(nullptr, gpu_in, &gpu_out,
                                  /*use_inference_params=*/true,
                                  /*prepare_input_gradients=*/false);
    CUDA_CHECK(cudaDeviceSynchronize());

    // Download and unpack.
    size_t out_bytes = gpu_out.n_bytes();
    std::vector<uint8_t> raw(out_bytes);
    CUDA_CHECK(cudaMemcpy(raw.data(), gpu_out.data(), out_bytes, cudaMemcpyDeviceToHost));
    const T* h = reinterpret_cast<const T*>(raw.data());

    // Column-major [N_OUT × n]: element (feat, sample) at feat + sample * N_OUT.
    std::vector<Vec3> result(n);
    for (uint32_t i = 0; i < n; ++i) {
        result[i] = Vec3(
            std::max(0.0f, (float)h[0 + i * N_OUT]),
            std::max(0.0f, (float)h[1 + i * N_OUT]),
            std::max(0.0f, (float)h[2 + i * N_OUT])
        );
    }
    return result;
}

// ---------------------------------------------------------------------------
// trainStep — one forward + backward + Adam update
// ---------------------------------------------------------------------------
void NeuralCache::trainStep(uint32_t n,
                             const std::vector<float>& inputs,
                             const std::vector<float>& targets_rgb) {
    if (n == 0) return;
    if (n % BATCH_ALIGN != 0)
        throw std::invalid_argument("NeuralCache::trainStep: n must be a multiple of BATCH_ALIGN");

    tcnn::GPUMatrix<float> gpu_in(N_IN, n);
    CUDA_CHECK(cudaMemcpy(gpu_in.data(), inputs.data(),
                          (size_t)n * N_IN * sizeof(float), cudaMemcpyHostToDevice));

    // Pad RGB targets to N_OUT=16 wide; slots 3-15 are 0. The loss is
    // computed across all 16 outputs, but the network learns to match only
    // the first 3; the remaining outputs converge to 0 (neutral for RelativeL2).
    std::vector<float> targets_padded((size_t)n * N_OUT, 0.0f);
    for (uint32_t i = 0; i < n; ++i) {
        targets_padded[(size_t)i * N_OUT + 0] = targets_rgb[(size_t)i * 3 + 0];
        targets_padded[(size_t)i * N_OUT + 1] = targets_rgb[(size_t)i * 3 + 1];
        targets_padded[(size_t)i * N_OUT + 2] = targets_rgb[(size_t)i * 3 + 2];
    }

    tcnn::GPUMatrix<float> gpu_target(N_OUT, n);
    CUDA_CHECK(cudaMemcpy(gpu_target.data(), targets_padded.data(),
                          (size_t)n * N_OUT * sizeof(float), cudaMemcpyHostToDevice));

    // training_step: forward + backward + optimizer step in one call.
    impl_->model.trainer->training_step(gpu_in, gpu_target);
    CUDA_CHECK(cudaDeviceSynchronize());
}
