// SPDX-License-Identifier: Apache-2.0
// Copyright 2024 Hendrik Grimm-Baur
//
// Host entry point for the progressive (hash-Owen Sobol') sampler. The full
// implementation is the single __host__/__device__ source in
// progressive_sobol_device.h (host and device share it verbatim so they cannot
// drift). This header exists for pure-host consumers -- the test-helpers
// binding and any future CPU path -- that must not pull in a .cu-only symbol;
// the __constant__ c_wfSamplerMode declaration in the device header is guarded
// behind __CUDACC__, so including it from a host translation unit is safe.
//
// pkg224 -- progressive-sampler primitive (unblocks pkg131).

#ifndef ASTRORAY_SAMPLING_PROGRESSIVE_SOBOL_H
#define ASTRORAY_SAMPLING_PROGRESSIVE_SOBOL_H

#include "astroray/sampling/progressive_sobol_device.h"

#endif  // ASTRORAY_SAMPLING_PROGRESSIVE_SOBOL_H
