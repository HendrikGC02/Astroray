// test_helpers_module.cpp — Python bindings for test/oracle utilities.
//
// This module exposes internal utilities needed for testing but NOT part of
// the public Astroray API. It's loaded only by the test suite.
//
// License: Apache-2.0

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "astroray/sampling/wavefront_rng.h"
#include "astroray/energy_compensation.h"

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

    // pkg151 — DisneyEnergyCompensationTables glass (rough-transmission)
    // lookups, exposed read-only for the trilinear sample3D + z(ior)-remap +
    // inv-table-swap unit test (test_pkg151_glass_table_lookup.py). Not
    // public API — these mirror internal table lookups used by
    // plugins/materials/disney.cpp::roughTransmissionEval.
    m.def("disney_ggx_glass_e", [](float roughness, float mu, float ior) {
        return astroray::DisneyEnergyCompensationTables::instance().ggxGlassE(roughness, mu, ior);
    }, "roughness"_a, "mu"_a, "ior"_a,
       "Trilinear lookup of the Cycles table_ggx_glass_E (or _inv_E when ior<1) table.");
    m.def("disney_ggx_glass_eavg", [](float roughness, float ior) {
        return astroray::DisneyEnergyCompensationTables::instance().ggxGlassEavg(roughness, ior);
    }, "roughness"_a, "ior"_a,
       "Bilinear lookup of the Cycles table_ggx_glass_Eavg (or _inv_Eavg when ior<1) table.");
    m.def("disney_compensation_tables_loaded", []() {
        return astroray::DisneyEnergyCompensationTables::instance().loaded();
    }, "Whether data/disney_compensation/*.bin loaded successfully.");
}
