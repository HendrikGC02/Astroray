// SPDX-License-Identifier: Apache-2.0
// Copyright 2024 Hendrik Grimm-Baur
//
// Sobol-Burley dimension-set layout shared by the CPU tile loop and the GPU
// wavefront. pkg305 lands the camera group only; pkg297 adds the per-bounce sets
// at rngOffset = kBounceStride * (bounce + 1) + slot.
//
// Adapted from Cycles kernel/types.h enum PathTraceDimension (Apache-2.0):
// PRNG_FILTER = 0, PRNG_LENS_TIME = 1, PRNG_BOUNCE_NUM = 16. Time is not in the
// camera group here: it keeps its deterministic Halton base 2 (pkg88).

#ifndef ASTRORAY_SAMPLING_PATH_DIMENSIONS_H
#define ASTRORAY_SAMPLING_PATH_DIMENSIONS_H

#include <cstdint>

namespace astroray {

enum PathDim : uint32_t {
    // Camera group (consumed once per path, at ray generation).
    PATHDIM_FILTER = 0,       // 2D: pixel-filter offset (x, y)
    PATHDIM_LENS = 1,         // 2D: aperture position
    PATHDIM_HERO_LAMBDA = 2,  // 1D: hero-wavelength uniform
};

// Dimension sets per bounce; the camera group owns sets [0, kBounceStride).
inline constexpr uint32_t kBounceStride = 16u;

}  // namespace astroray

#endif  // ASTRORAY_SAMPLING_PATH_DIMENSIONS_H
