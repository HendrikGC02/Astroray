// simple_cuda_smoke.cu — verifies CUDA 12.9 device init + kernel dispatch.
// Built directly with nvcc (not via CMake), isolating driver compatibility.
#include <cuda_runtime.h>
#include <cstdio>

__global__ void add_kernel(float* out, const float* a, const float* b, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) out[i] = a[i] + b[i];
}

int main() {
    int n = 0;
    cudaError_t e = cudaGetDeviceCount(&n);
    if (e != cudaSuccess || n == 0) {
        printf("FAIL: cudaGetDeviceCount = %s\n", cudaGetErrorString(e));
        return 1;
    }
    cudaDeviceProp p{};
    cudaGetDeviceProperties(&p, 0);
    printf("Device 0: %s (sm_%d%d)\n", p.name, p.major, p.minor);

    const int N = 256;
    float h_a[N], h_b[N], h_out[N];
    for (int i = 0; i < N; ++i) { h_a[i] = (float)i; h_b[i] = (float)(N - i); }
    float *d_a, *d_b, *d_out;
    cudaMalloc(&d_a, N * sizeof(float));
    cudaMalloc(&d_b, N * sizeof(float));
    cudaMalloc(&d_out, N * sizeof(float));
    cudaMemcpy(d_a, h_a, N * sizeof(float), cudaMemcpyHostToDevice);
    cudaMemcpy(d_b, h_b, N * sizeof(float), cudaMemcpyHostToDevice);
    add_kernel<<<1, 256>>>(d_out, d_a, d_b, N);
    cudaMemcpy(h_out, d_out, N * sizeof(float), cudaMemcpyDeviceToHost);
    cudaFree(d_a); cudaFree(d_b); cudaFree(d_out);

    bool ok = true;
    for (int i = 0; i < N; ++i) if (h_out[i] != (float)N) { ok = false; break; }
    printf("CUDA standalone smoke: %s\n", ok ? "OK" : "FAIL (wrong output)");
    return ok ? 0 : 1;
}
