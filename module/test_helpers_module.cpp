// test_helpers_module.cpp — Python bindings for test/oracle utilities.
//
// This module exposes internal utilities needed for testing but NOT part of
// the public Astroray API. It's loaded only by the test suite.
//
// License: Apache-2.0

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>

#include "astroray/sampling/wavefront_rng.h"
#include "astroray/sampling/progressive_sobol.h"
#include "astroray/sampling/adaptive_sampling.h"
#include "astroray/energy_compensation.h"
#include "astroray/guiding/dtree.h"
#include "astroray/guiding/sdtree.h"

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

    // pkg224 — progressive (hash-Owen Sobol') sampler primitive
    // (include/astroray/sampling/progressive_sobol_device.h). The host build of
    // these __host__/__device__ functions is byte-identical to the CUDA device
    // build (single source), so pinning the host output against
    // scipy.stats.qmc.Sobol (test_pkg224_progressive_sobol.py) validates the GPU
    // sampler too. Exposed for tests only.
    m.attr("SOBOL_NUM_DIMS") = astroray::kSobolNumDims;
    m.def("sobol_direct", &astroray::SobolDirect, "sample_index"_a, "dimension"_a,
          "Unscrambled direct Sobol' integer (XOR of the direction vectors "
          "selected by the set bits of sample_index). Top-bit-first 32-bit fixed "
          "point; divide by 2^32 for the [0,1) point.");
    m.def("progressive_sobol_sample", &astroray::ProgressiveSobolSample,
          "pixel"_a, "sample"_a, "dimension"_a, "scene_seed"_a = 0,
          "Hash-Owen-scrambled Sobol' draw in [0,1) — the value the GPU shade "
          "kernel returns from WavefrontRNG::Uniform() when c_wfSamplerMode is on.");
    m.def("fast_owen_scramble", &astroray::FastOwenScramble, "v"_a, "seed"_a,
          "Burley 2020 FastOwenScrambler (pbrt-v4).");

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

    // pkg160 — the GGX reflection-lobe multi-scatter compensation, exposed so
    // tests/test_pkg160_metal_energy_compensation.py can pin that the CPU
    // conductor lobe (plugins/materials/metal.cpp) and the GPU one
    // (gpu_metal_eval) now read the SAME table with the SAME formula.
    //
    // This repo used to have two independent GGX E-table systems: the
    // runtime-MC `GGXEnergyCompensationLUT` in raytracer.h, which only
    // metal.cpp used, and the shipped Cycles `DisneyEnergyCompensationTables`
    // below, which is the only one uploaded to the GPU (gpu_ggx_tables.cu ->
    // g_ggxE). They disagreed by 24.6x in E and ~1030x in the downstream Fms
    // at roughness 0.15. pkg160 deleted the runtime LUT and moved metal.cpp
    // onto the shipped tables, so there is now exactly one.
    //
    // `disney_ggx_e`/`disney_ggx_eavg` deliberately keep the table's own
    // (roughness, mu) argument order — the same order gpu_ggxE uses.
    m.def("disney_ggx_e", [](float roughness, float mu) {
        return astroray::DisneyEnergyCompensationTables::instance().ggxE(roughness, mu);
    }, "roughness"_a, "mu"_a,
       "Shipped Cycles ggx_E.bin lookup — the exact array uploaded to the GPU "
       "as g_ggxE (gpu_ggx_tables.cu) and read by CPU metal.cpp/disney.cpp.");
    m.def("disney_ggx_eavg", [](float roughness) {
        return astroray::DisneyEnergyCompensationTables::instance().ggxEavg(roughness);
    }, "roughness"_a, "Shipped Cycles ggx_Eavg.bin lookup (g_ggxEavg / gpu_ggxEavg).");
    m.def("ggx_darkening_channel", &astroray::ggxDarkeningChannel,
          "f"_a, "e"_a, "eavg"_a,
          "astroray::ggxDarkeningChannel (include/astroray/energy_compensation.h) "
          "— the single host definition of the Kulla & Conty 2017 / Cycles "
          "microfacet_ggx_preserve_energy net factor 1 + Fms*(1-E)/E, called by "
          "both metal.cpp and disney.cpp. Device twin: gpu_ggxDarkeningChannel.");

    // pkg131 — zero-knob adaptive sampling core (Cycles adaptive_sampling.h +
    // integrator.cpp get_adaptive_sampling). The __host__ __device__ free
    // functions in include/astroray/sampling/adaptive_sampling.h are the SAME
    // ones the CPU sample loop and the GPU compacted-active-pixel round call, so
    // pinning the host build here validates the device math directly.
    m.def("adaptive_derive",
          [](int max_samples, float user_threshold, int user_min_samples) {
              astroray::adaptive::AdaptiveParams p =
                  astroray::adaptive::deriveAdaptiveParams(
                      max_samples, user_threshold, user_min_samples);
              return py::make_tuple(p.threshold, p.min_samples,
                                    p.adaptive_step, p.max_samples, p.use);
          }, "max_samples"_a, "user_threshold"_a = 0.0f, "user_min_samples"_a = 0,
          "Cycles zero-knob derivation → (threshold, min_samples, adaptive_step, "
          "max_samples, use). user_threshold<=0 / user_min_samples<=0 = auto.");
    m.def("adaptive_need_check",
          [](float threshold, int min_samples, int samples_done) {
              astroray::adaptive::AdaptiveParams p;
              p.use = true; p.threshold = threshold; p.min_samples = min_samples;
              p.max_samples = 1 << 30; p.adaptive_step = astroray::adaptive::kAdaptiveStep;
              return astroray::adaptive::needConvergenceCheck(p, samples_done);
          }, "threshold"_a, "min_samples"_a, "samples_done"_a,
          "needConvergenceCheck: true only past the floor and on step-aligned counts.");
    m.def("adaptive_pixel_converged",
          &astroray::adaptive::pixelConverged,
          "full_lum_sum"_a, "half_lum_sum"_a, "samples_done"_a,
          "threshold"_a, "exposure"_a = 1.0f,
          "film_adaptive_sampling_convergence_check (scalar-luminance half-buffer).");
    m.def("adaptive_dilate",
          [](const std::vector<uint8_t>& converged, int width, int height) {
              std::vector<uint8_t> tmp(converged.size()), out(converged.size());
              astroray::adaptive::dilateConvergedMaskPass(
                  converged.data(), tmp.data(), width, height, 1);
              astroray::adaptive::dilateConvergedMaskPass(
                  tmp.data(), out.data(), width, height, width);
              return out;
          }, "converged"_a, "width"_a, "height"_a,
          "Two-pass 3x3 dilation of the converged mask (1=converged/retired).");
    m.attr("ADAPTIVE_STEP") = astroray::adaptive::kAdaptiveStep;

    // pkg136 — SD-tree path guiding, directional quadtree (Stage 1A). The
    // host DTree (include/astroray/guiding/dtree.h) is a clean-room port of the
    // Müller 2017 directional tree; binding it here lets
    // tests/test_pkg136_dtree_unit.py drive the exact primitives (splat / refine
    // / reset / sample / pdf / snapshot) and reproduce the numpy-de-risked
    // variance-reduction + unbiasedness result in C++. Not public API.
    m.def("guiding_dir_to_square", [](float wx, float wy, float wz) {
        float x, y;
        astroray::guiding::dirToSquare(wx, wy, wz, x, y);
        return py::make_tuple(x, y);
    }, "wx"_a, "wy"_a, "wz"_a,
       "Equal-area cylindrical map: world unit direction → unit-square (x,y).");
    m.def("guiding_square_to_dir", [](float x, float y) {
        float wx, wy, wz;
        astroray::guiding::squareToDir(x, y, wx, wy, wz);
        return py::make_tuple(wx, wy, wz);
    }, "x"_a, "y"_a,
       "Inverse equal-area map: unit-square (x,y) → world unit direction.");
    m.attr("GUIDING_SPHERE_JACOBIAN") = astroray::guiding::kGuidingSphereJacobian;

    py::class_<astroray::guiding::DTree>(m, "DTree")
        .def(py::init<>())
        .def("splat", &astroray::guiding::DTree::splat, "x"_a, "y"_a, "v"_a,
             "Splat flux v at square point (x,y) along the descent path.")
        .def("refine", &astroray::guiding::DTree::refine, "rho"_a,
             "Subdivide (one level) every leaf holding > rho of total flux. Call "
             "between iterations, using the finished iteration's flux, before reset().")
        .def("reset", &astroray::guiding::DTree::reset,
             "Zero all node flux, keeping topology.")
        .def("sample", [](const astroray::guiding::DTree& t, float u1, float u2) {
            float x, y, pdf;
            t.sample(u1, u2, x, y, pdf);
            return py::make_tuple(x, y, pdf);
        }, "u1"_a, "u2"_a,
           "Hierarchical-warp sample → (x, y, square-measure pdf).")
        .def("pdf", &astroray::guiding::DTree::pdf, "x"_a, "y"_a,
             "Square-measure pdf of point (x,y).")
        .def("pdf_dir", &astroray::guiding::DTree::pdfDir, "wx"_a, "wy"_a, "wz"_a,
             "Solid-angle pdf of a world direction (folds in the 1/4π jacobian).")
        .def("total_flux", &astroray::guiding::DTree::totalFlux)
        .def("num_nodes", &astroray::guiding::DTree::numNodes)
        .def("num_leaves", &astroray::guiding::DTree::numLeaves)
        .def("snapshot", [](const astroray::guiding::DTree& t) {
            return astroray::guiding::DTree(t);  // deep copy (frozen guide)
        }, "Deep copy — the frozen previous-iteration guide for training draws.");

    // pkg136 — SD-tree spatial binary tree (Stage 1A). Wraps the float[3] API
    // in tuples so tests/test_pkg136_sdtree_unit.py can de-risk the spatial
    // half: leaf lookup, point-count split with directional-tree inheritance,
    // and that spatially-separated regions specialise to different guides.
    using SDT = astroray::guiding::SDTree;
    py::class_<SDT>(m, "SDTree")
        .def(py::init([](std::array<float, 3> mn, std::array<float, 3> mx) {
            return SDT(mn.data(), mx.data());
        }), "minb"_a, "maxb"_a)
        .def("record", [](SDT& t, std::array<float, 3> p,
                          float wx, float wy, float wz, float value) {
            t.record(p.data(), wx, wy, wz, value);
        }, "p"_a, "wx"_a, "wy"_a, "wz"_a, "value"_a,
           "Splat radiance `value` at world dir (wx,wy,wz) into the leaf at p.")
        .def("sample_dir", [](const SDT& t, std::array<float, 3> p, float u1, float u2) {
            float wx, wy, wz, pdf;
            t.sampleDir(p.data(), u1, u2, wx, wy, wz, pdf);
            return py::make_tuple(wx, wy, wz, pdf);
        }, "p"_a, "u1"_a, "u2"_a,
           "Sample a world direction from the leaf at p → (wx,wy,wz,pdf_sa).")
        .def("pdf_dir", [](const SDT& t, std::array<float, 3> p,
                           float wx, float wy, float wz) {
            return t.pdfDir(p.data(), wx, wy, wz);
        }, "p"_a, "wx"_a, "wy"_a, "wz"_a)
        .def("refine", &SDT::refine, "spatial_threshold"_a, "dir_rho"_a,
             "Spatial split (count > threshold) with DTree inheritance, then "
             "directional refine of every leaf.")
        .def("reset_iteration", &SDT::resetIteration,
             "Zero all directional flux + spatial sample counts, keep topology.")
        .def("snapshot", &SDT::snapshot, "Deep copy (frozen guide).")
        .def("num_leaves", &SDT::numLeaves)
        .def("num_nodes", &SDT::numNodes)
        .def("leaf_bounds", [](const SDT& t, std::array<float, 3> p) {
            float mn[3], mx[3];
            t.leafBounds(p.data(), mn, mx);
            return py::make_tuple(mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]);
        }, "p"_a, "AABB (minx,miny,minz,maxx,maxy,maxz) of the leaf at p.")
        .def("leaf_sample_count", [](const SDT& t, std::array<float, 3> p) {
            return t.leafSampleCount(p.data());
        }, "p"_a);
}
