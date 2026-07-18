// light_tree_probe.cu — pkg55 Phase C Session C1.
//
// The pkg86-B GPU parity probe (batch light-tree pick), extracted verbatim
// from path_trace_kernel.cu so it survives the RGB-megakernel deletion planned
// for pkg55 Phase C Session C7. It is not path-trace code: it only needs the
// device light-tree traversal in light_tree_device.cuh. Behaviour-preserving.
//
// Runs the SAME gpu_light_tree_pick the NEE path uses on a batch of
// (point, normal, u) queries and writes the picked GLight index + traversal
// pdf, for tests/test_pkg86_B_gpu_parity.py (debug_light_tree_pick_gpu).

#include "astroray/gpu_types.h"
#include "light_tree_device.cuh"  // pkg86-B: gpu_light_tree_pick

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

__global__ void lightTreePickKernel(
    GLightTreeView view, const float* pts, const float* nrms, const float* us,
    int n, int* outIdx, float* outPdf)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    GVec3 P(pts[i*3], pts[i*3+1], pts[i*3+2]);
    GVec3 N(nrms[i*3], nrms[i*3+1], nrms[i*3+2]);
    float pdf = 0.f;
    int e = gpu_light_tree_pick(view, P, N, us[i], &pdf);
    outIdx[i] = (e >= 0) ? view.emitters[e].lightIndex : -1;
    outPdf[i] = pdf;
}

void launchLightTreePick(
    GLightTreeView view, const float* d_pts, const float* d_nrms,
    const float* d_us, int n, int* d_outIdx, float* d_outPdf)
{
    int blocks = (n + 255) / 256;
    lightTreePickKernel<<<blocks, 256>>>(view, d_pts, d_nrms, d_us, n,
                                         d_outIdx, d_outPdf);
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        fprintf(stderr, "lightTreePick launch error: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
    cudaError_t syncErr = cudaDeviceSynchronize();
    if (syncErr != cudaSuccess) {
        fprintf(stderr, "lightTreePick runtime error: %s\n", cudaGetErrorString(syncErr));
        throw std::runtime_error(cudaGetErrorString(syncErr));
    }
}
