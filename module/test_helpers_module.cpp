// test_helpers_module.cpp — Python bindings for test/oracle utilities.
//
// This module exposes internal utilities needed for testing but NOT part of
// the public Astroray API. It's loaded only by the test suite.
//
// License: Apache-2.0

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "raytracer.h"  // pkg160: GGXEnergyCompensationLUT (runtime-MC table)
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

    // pkg160 — this repo has TWO independent GGX energy-compensation table
    // systems, and until now only one of them was reachable from Python, which
    // is why their disagreement went unmeasured. Both are exposed here so
    // tests/test_pkg160_ggx_table_systems.py can compare them directly:
    //
    //   (1) raytracer.h GGXEnergyCompensationLUT — computed at runtime by MC
    //       integration in its constructor (256 uniform-hemisphere samples per
    //       cell, 32x32). Stored E[roughness*RES + mu], read as
    //       lookupE(mu, roughness). This is what CPU
    //       ggxMultiScatterCompensation() — and therefore MetalPlugin::eval /
    //       evalSpectral — actually uses.
    //   (2) DisneyEnergyCompensationTables — loaded from the shipped Cycles
    //       data/disney_compensation/ggx_E.bin, read as ggxE(roughness, mu),
    //       i.e. the OPPOSITE argument order. This is the only one uploaded to
    //       the GPU (gpu_ggx_tables.cu -> g_ggxE, gpu_ggxE(roughness, mu)).
    //
    // Each system is internally consistent — the mirrored argument orders are
    // NOT a transposition bug. The argument orders below deliberately preserve
    // each system's own convention rather than normalizing them, so callers
    // cannot accidentally compare the wrong axes.
    m.def("ggx_runtime_e", [](float mu, float roughness) {
        return ggxEnergyCompensationLUT().lookupE(mu, roughness);
    }, "mu"_a, "roughness"_a,
       "raytracer.h GGXEnergyCompensationLUT::lookupE — runtime-MC directional "
       "albedo. Argument order (mu, roughness) is this table's own convention.");
    m.def("ggx_runtime_eavg", [](float roughness) {
        return ggxEnergyCompensationLUT().lookupEavg(roughness);
    }, "roughness"_a,
       "raytracer.h GGXEnergyCompensationLUT::lookupEavg — runtime-MC "
       "cosine-weighted average albedo.");
    m.def("ggx_multiscatter_compensation", [](float ndotv, float ndotl, float roughness) {
        return ggxMultiScatterCompensation(ndotv, ndotl, roughness);
    }, "ndotv"_a, "ndotl"_a, "roughness"_a,
       "raytracer.h ggxMultiScatterCompensation — the exact Fms that "
       "MetalPlugin::eval/evalSpectral multiply into their multiscatter term "
       "(Kulla & Conty 2017). Any GPU mirror must reproduce THIS.");
    m.def("disney_ggx_e", [](float roughness, float mu) {
        return astroray::DisneyEnergyCompensationTables::instance().ggxE(roughness, mu);
    }, "roughness"_a, "mu"_a,
       "Shipped Cycles ggx_E.bin lookup — the table the GPU has (gpu_ggxE). "
       "Argument order (roughness, mu) is this table's own convention.");
    m.def("disney_ggx_eavg", [](float roughness) {
        return astroray::DisneyEnergyCompensationTables::instance().ggxEavg(roughness);
    }, "roughness"_a, "Shipped Cycles ggx_Eavg.bin lookup (gpu_ggxEavg).");
}
