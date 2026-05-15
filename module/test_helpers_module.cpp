// test_helpers_module.cpp — Python bindings for test/oracle utilities.
//
// This module exposes internal utilities needed for testing but NOT part of
// the public Astroray API. It's loaded only by the test suite.
//
// License: Apache-2.0

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "astroray/sampling/wavefront_rng.h"

namespace py = pybind11;
using namespace pybind11::literals;

PYBIND11_MODULE(astroray_test_helpers, m) {
    m.doc() = "Astroray test/oracle utilities (internal, not public API)";

    // pkg92 — WavefrontRNG (PCG32 counter-based RNG for wavefront oracles).
    // This is a test/oracle utility, not production API.
    py::class_<astroray::WavefrontRNG>(m, "WavefrontRNG")
        .def(py::init<uint32_t, uint32_t, uint64_t>(),
             "pixel_index"_a, "sample_index"_a, "scene_seed"_a = 0,
             "Construct RNG for a specific (pixel, sample) path. Dimension counter "
             "starts at 0 and auto-increments with each Uniform() or UniformUInt32() call.")
        .def("Uniform", &astroray::WavefrontRNG::Uniform,
             "Generate uniform float in [0, 1). Increments internal dimension counter.")
        .def("UniformUInt32", &astroray::WavefrontRNG::UniformUInt32,
             "Generate uniform uint32_t. Increments internal dimension counter.");
}
