// tiny_cuda_nn_smoke.cu — pkg25 feasibility prototype.
//
// Builds only when -DASTRORAY_TINY_CUDA_NN=ON.
// Creates a tiny 4→64→4 MLP, runs one forward pass, verifies all outputs
// are finite.  Returns 0 on success, 1 on failure.
//
// This is a throwaway harness; not wired into production rendering.

#include <tiny-cuda-nn/common.h>
#include <tiny-cuda-nn/network_with_input_encoding.h>
#include <tiny-cuda-nn/gpu_matrix.h>

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <cmath>

#define CUDA_CHECK(call) do {                                              \
    cudaError_t _e = (call);                                               \
    if (_e != cudaSuccess) {                                               \
        fprintf(stderr, "CUDA error %s:%d — %s\n",                        \
                __FILE__, __LINE__, cudaGetErrorString(_e));               \
        return 1;                                                          \
    }                                                                      \
} while (0)

int main() {
    // -----------------------------------------------------------------------
    // 1. Device check
    // -----------------------------------------------------------------------
    int n_devices = 0;
    CUDA_CHECK(cudaGetDeviceCount(&n_devices));
    if (n_devices == 0) {
        fprintf(stderr, "FAIL: no CUDA devices\n");
        return 1;
    }

    cudaDeviceProp prop{};
    CUDA_CHECK(cudaGetDeviceProperties(&prop, 0));
    printf("Device 0: %s (sm_%d%d, %.0f MiB)\n",
           prop.name, prop.major, prop.minor,
           static_cast<double>(prop.totalGlobalMem) / (1 << 20));

    if (prop.major < 7) {
        fprintf(stderr, "SKIP: FullyFusedMLP requires sm_70+ (tensor cores)\n");
        return 0;  // not a hard failure — hardware constraint
    }

    // -----------------------------------------------------------------------
    // 2. Network configuration
    // -----------------------------------------------------------------------
    // Identity encoding (pass-through) + tiny FullyFusedMLP.
    // n_neurons must be 16, 32, or 64; batch must be a multiple of 16.
    nlohmann::json config = {
        {"encoding", {
            {"otype", "Identity"},
            {"n_dims_to_encode", 4}
        }},
        {"network", {
            {"otype", "FullyFusedMLP"},
            {"n_neurons",       64},
            {"n_hidden_layers",  1},
            {"activation",      "ReLU"},
            {"output_activation", "None"}
        }}
    };

    const uint32_t N_IN     = 4;
    const uint32_t N_OUT    = 4;
    const uint32_t BATCH    = 64;   // multiple of 16

    // -----------------------------------------------------------------------
    // 3. Build model
    // -----------------------------------------------------------------------
    using T = tcnn::network_precision_t;  // __half on sm_70+
    std::shared_ptr<tcnn::NetworkWithInputEncoding<T>> model;
    try {
        model = std::make_shared<tcnn::NetworkWithInputEncoding<T>>(
            N_IN, N_OUT, config["encoding"], config["network"]);
    } catch (const std::exception& ex) {
        fprintf(stderr, "FAIL: model construction — %s\n", ex.what());
        return 1;
    }
    printf("Model params: %zu\n", model->n_params());

    // -----------------------------------------------------------------------
    // 4. Allocate inputs (float32) and outputs (T = half)
    // -----------------------------------------------------------------------
    tcnn::GPUMatrix<float>  inputs (N_IN,  BATCH);
    tcnn::GPUMatrix<T>      outputs(N_OUT, BATCH);

    // Fill inputs with 0.5 (arbitrary non-zero values).
    std::vector<float> h_in(N_IN * BATCH, 0.5f);
    CUDA_CHECK(cudaMemcpy(inputs.data(), h_in.data(),
                          h_in.size() * sizeof(float), cudaMemcpyHostToDevice));

    // -----------------------------------------------------------------------
    // 5. Forward pass
    // -----------------------------------------------------------------------
    try {
        // nvcc can't deduce auto for unique_ptr return; discard context (not needed for inference).
        model->forward(nullptr, inputs, &outputs, false, false);
    } catch (const std::exception& ex) {
        fprintf(stderr, "FAIL: forward pass — %s\n", ex.what());
        return 1;
    }
    CUDA_CHECK(cudaDeviceSynchronize());

    // -----------------------------------------------------------------------
    // 6. Verify outputs are finite
    // -----------------------------------------------------------------------
    std::vector<T> h_out(N_OUT * BATCH);
    CUDA_CHECK(cudaMemcpy(h_out.data(), outputs.data(),
                          h_out.size() * sizeof(T), cudaMemcpyDeviceToHost));

    int non_finite = 0;
    for (auto v : h_out) {
        if (!std::isfinite(static_cast<float>(v))) ++non_finite;
    }

    printf("tiny-cuda-nn smoke: %s  (non-finite: %d / %zu outputs)\n",
           non_finite == 0 ? "OK" : "FAIL",
           non_finite, h_out.size());
    return non_finite == 0 ? 0 : 1;
}
