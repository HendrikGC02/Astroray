// SPDX-License-Identifier: Apache-2.0
// Copyright 2024 Hendrik Grimm-Baur
//
// pkg305 -- pixel-filter importance sampling from a tabulated CDF. One uniform
// in, one sub-pixel offset out, so the filter can take a fixed (stratified)
// Sobol' input; the rejection / Box-Muller samplers it replaces consumed a
// variable number of draws. The map u -> offset is monotone on each half, so
// equal u-strata map to equal-mass filter strata.
//
// Filter functions and width semantics: Blender Cycles scene/film.cpp
// (Apache-2.0) filter_func_gaussian / filter_func_blackman_harris with the
// filter_table() width pre-scale (Gaussian width*=3, Blackman-Harris width*=2) --
// the pkg203 semantics: Gaussian sigma = w/4, support +-1.5w; BH support +-w.
// Like Cycles' util_cdf_inverted(make_symmetric=true), the CDF of |f| is
// tabulated over the half range and mirrored.
//
// Sampling (deviation from Cycles, see
// .astroray_plan/docs/pkg305-camera-group-research.md): Cycles stores the
// INVERSE CDF on a uniform u grid and lerps it (lookup_table_read). That makes
// every table cell carry equal mass, so the near-zero tails of both filters get
// wide, uniformly filled cells (outer 0.15 px bin of BH 1.5 over-sampled ~5x;
// chi2 vs the analytic profile fails at 1e5 samples). Here the FORWARD CDF is
// tabulated on a uniform x grid and inverted by binary search + linear
// interpolation, i.e. exact sampling of the piecewise-constant density (pbrt-v4
// PiecewiseConstant1D::Sample, src/pbrt/util/sampling.h, Apache-2.0).
//
// Box (type 0) keeps Astroray's width-ignored unit box and needs no table.

#ifndef ASTRORAY_SAMPLING_FILTER_TABLE_H
#define ASTRORAY_SAMPLING_FILTER_TABLE_H

#include <cstdint>

#ifndef __CUDA_ARCH__
#include <algorithm>
#include <cmath>
#include <vector>
#endif

#ifdef __CUDACC__
#  define FT_HD __host__ __device__
#else
#  define FT_HD
#endif

namespace astroray {
namespace filter_table {

inline constexpr int kCells = 1024;        // uniform CDF cells over the half range
inline constexpr int kSize = kCells + 1;   // CDF entries: cdf[0] = 0 .. cdf[kCells] = 1

// Half support in pixels (pkg203): Gaussian 1.5 w, Blackman-Harris w.
FT_HD inline float halfSupport(int type, float width) {
    return (type == 1 ? 1.5f : 1.0f) * width;
}

#ifndef __CUDA_ARCH__
// Cycles filter functions, evaluated at the pre-scaled width W.
inline float filterFunc(int type, float v, float W) {
    if (type == 1) {  // filter_func_gaussian
        v *= 6.0f / W;
        return std::exp(-2.0f * v * v);
    }
    // filter_func_blackman_harris
    v = 2.0f * 3.14159265358979323846f * (v / W + 0.5f);
    return 0.35875f - 0.48829f * std::cos(v) + 0.14128f * std::cos(2.0f * v) -
           0.01168f * std::cos(3.0f * v);
}

// Fill cdf[kSize]: normalised CDF of |f| over [0, halfSupport] (midpoint rule),
// for type 1 (Gaussian) or 2 (Blackman-Harris).
inline void build(int type, float width, float* cdf) {
    const float W = width * (type == 1 ? 3.0f : 2.0f);
    const float R = halfSupport(type, width);
    double acc = 0.0;
    std::vector<double> c(kSize);
    c[0] = 0.0;
    for (int k = 0; k < kCells; ++k) {
        const float x = R * (static_cast<float>(k) + 0.5f) / static_cast<float>(kCells);
        acc += std::fabs(filterFunc(type, x, W));
        c[k + 1] = acc;
    }
    for (int k = 0; k < kSize; ++k)
        cdf[k] = acc > 0.0 ? static_cast<float>(c[k] / acc) : static_cast<float>(k) / kCells;
    cdf[0] = 0.0f;
    cdf[kCells] = 1.0f;
}
#endif  // !__CUDA_ARCH__

// Position in [0, R] of CDF value x in [0, 1] (piecewise-constant density).
FT_HD inline float sampleHalf(const float* cdf, float R, float x) {
    int lo = 0, hi = kCells;  // cdf[lo] <= x; cdf[kCells] == 1
    while (hi - lo > 1) {
        const int mid = (lo + hi) >> 1;
        if (cdf[mid] <= x) lo = mid; else hi = mid;
    }
    const float d = cdf[lo + 1] - cdf[lo];
    float t = d > 0.0f ? (x - cdf[lo]) / d : 0.5f;
    t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
    return R * (static_cast<float>(lo) + t) / static_cast<float>(kCells);
}

// Centred sub-pixel offset for filter `type` from one uniform u in [0,1).
// Box (0): u - 0.5 (unit box, width ignored). 1/2: mirrored CDF inversion,
// u in [0.5,1) -> [0, R], u in [0,0.5) -> [-R, 0).
FT_HD inline float sampleOffset(int type, float width, const float* cdf, float u) {
    if (type == 0) return u - 0.5f;
    const float R = halfSupport(type, width);
    if (u >= 0.5f) return sampleHalf(cdf, R, 2.0f * u - 1.0f);
    return -sampleHalf(cdf, R, 1.0f - 2.0f * u);
}

}  // namespace filter_table
}  // namespace astroray

#undef FT_HD

#endif  // ASTRORAY_SAMPLING_FILTER_TABLE_H
