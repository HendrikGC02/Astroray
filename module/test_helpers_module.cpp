// test_helpers_module.cpp — Python bindings for test/oracle utilities.
//
// This module exposes internal utilities needed for testing but NOT part of
// the public Astroray API. It's loaded only by the test suite.
//
// License: Apache-2.0

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <stdexcept>
#include <string>
#include <vector>

#include "astroray/sampling/wavefront_rng.h"
#include "astroray/sampling/progressive_sobol.h"
#include "astroray/sampling/adaptive_sampling.h"
#include "astroray/energy_compensation.h"
#include "astroray/guiding/dtree.h"
#include "astroray/guiding/sdtree.h"
#include "astroray/black_hole.h"
#include "astroray/adaf.h"
#include "astroray/synchrotron.h"
#include "astroray/integrator.h"
#include "astroray/register.h"

namespace py = pybind11;
using namespace pybind11::literals;

namespace {

class GrDispatchProbe final : public Hittable {
    float emission_;
    int* trace_calls_;

public:
    GrDispatchProbe(float emission, int* trace_calls)
        : emission_(emission), trace_calls_(trace_calls) {}

    bool hit(const Ray& ray, float t_min, float t_max, HitRecord& rec) const override {
        constexpr float t = 1.0f;
        if (t < t_min || t > t_max) return false;
        rec.t = t;
        rec.point = ray.at(t);
        rec.objectPoint = rec.point;
        rec.setFaceNormal(ray, Vec3(0.0f, 0.0f, -1.0f));
        rec.hitObject = this;
        return true;
    }

    bool boundingBox(AABB& box) const override {
        box = AABB(Vec3(-1.0f, -1.0f, -1.5f), Vec3(1.0f, 1.0f, -0.5f));
        return true;
    }

    bool isGRObject() const override { return true; }
    bool isLight() const override { return true; }

    GRSpectralResult traceGRSpectral(
            const Ray&, const astroray::SampledWavelengths&, std::mt19937&) const override {
        ++*trace_calls_;
        GRSpectralResult result;
        result.emission = astroray::SampledSpectrum(emission_);
        result.exitDirection = Vec3(0.0f, 0.0f, 1.0f);
        result.captured = true;
        result.hasEmission = true;
        return result;
    }
};

std::array<float, 2> probeGrRendererDispatch(float emission, float clamp_direct, bool caustic) {
    Renderer renderer;
    renderer.setClampDirect(clamp_direct);
    int trace_calls = 0;
    renderer.addObject(std::make_shared<GrDispatchProbe>(emission, &trace_calls));
    renderer.buildAcceleration();
    astroray::SampledWavelengths lambdas =
        astroray::SampledWavelengths::sampleUniform(0.5f);
    std::mt19937 generator(1234);
    // Renderer defaults to a -Z camera forward axis; match it so its primary
    // clip-depth conversion accepts the synthetic hit at t=1.
    const Ray ray(Vec3(0.0f), Vec3(0.0f, 0.0f, -1.0f));
    const astroray::SampledSpectrum result = caustic
        ? renderer.pathTraceSpectralCaustic(ray, 1, 1, lambdas, generator)
        : renderer.pathTraceSpectral(ray, 1, lambdas, generator);
    return {result[0], static_cast<float>(trace_calls)};
}

std::array<float, 2> probeRegisteredReSTIRGrDispatch(float emission) {
    int trace_calls = 0;
    Renderer renderer;
    renderer.addObject(std::make_shared<GrDispatchProbe>(emission, &trace_calls));
    renderer.buildAcceleration();

    astroray::ParamDict params;
    params.set("max_depth", 1);
    auto integrator = astroray::IntegratorRegistry::instance().create("restir-di", params);
    Camera camera(
        Vec3(0.0f), Vec3(0.0f, 0.0f, -1.0f), Vec3(0.0f, 1.0f, 0.0f),
        45.0f, 1.0f, 0.0f, 1.0f, 1, 1);
    integrator->beginFrame(renderer, camera);

    std::mt19937 generator(1234);
    const Ray ray = camera.getRay(0.0f, 0.0f, 0.0f, generator);
    const SampleResult result = integrator->sampleFull(ray, generator);
    return {result.color.y, static_cast<float>(trace_calls)};
}

// pkg282: per-pixel first-crossing disk redshift g (and GR pass count, see
// BlackHole::probeDiskRedshift) for a pinhole camera looking at a BlackHole. Returns 2*w*h doubles,
// row-major from the top row, pixel (x, y) at camera (u, v) = ((x+0.5)/w,
// 1-(y+0.5)/h).
std::vector<double> grDiskRedshiftImage(
        std::array<float, 3> look_from, std::array<float, 3> look_at, float vfov,
        int w, int h, std::array<float, 3> bh_pos, double influence_radius,
        double disk_outer, double r_obs_M, double spin) {
    const Vec3 from(look_from[0], look_from[1], look_from[2]);
    const Vec3 at(look_at[0], look_at[1], look_at[2]);
    Camera camera(from, at, Vec3(0.0f, 1.0f, 0.0f), vfov, float(w) / float(h),
                  0.0f, (from - at).length(), w, h);
    BlackHole bh(Vec3(bh_pos[0], bh_pos[1], bh_pos[2]), 4.0e6, influence_radius,
                 disk_outer, 1.0, 75.0, r_obs_M, spin);
    std::vector<double> out(size_t(2) * size_t(w) * size_t(h), 0.0);
    std::mt19937 gen(1);
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            const Ray ray = camera.getRay((x + 0.5f) / float(w),
                                          1.0f - (y + 0.5f) / float(h), 0.0f, gen);
            const auto p = bh.probeDiskRedshift(ray);
            const size_t i = size_t(y) * size_t(w) + size_t(x);
            out[2 * i] = p[0];
            out[2 * i + 1] = p[1];
        }
    }
    return out;
}

// #845: film round trip pixel -> u,v (the CPU render loop's (x + jitter)/W
// mapping) -> Camera::getRay -> screenToPixel. Returns the recovered (px, py).
std::array<int, 2> cameraPixelRoundtrip(int width, int height, int x, int y,
                                        float jitterU, float jitterV, bool orthographic) {
    Camera cam(Vec3(0, 0, 5), Vec3(0, 0, 0), Vec3(0, 1, 0), 40.0f,
               float(width) / float(height), 0.0f, 5.0f, width, height,
               0.1f, -0.05f, 0.001f, std::numeric_limits<float>::max(),
               orthographic, 4.0f, 4.0f * float(height) / float(width));
    std::mt19937 gen(7);
    const float u = (x + jitterU) / float(width);
    const float v = 1.0f - (y + jitterV) / float(height);
    const Ray ray = cam.getRay(u, v, 0.0f, gen);
    int px = -1, py = -1;
    screenToPixel(ray.screenU, ray.screenV, width, height, px, py);
    return {px, py};
}

// pkg283: volumetric invariant-transport seams. They call the production
// ADAF / SynchrotronJet transport; beta overrides the model's fluid velocity.
// beta is a py::object (None or 3 floats): a by-value
// std::optional<std::array<double,3>> crashed the MinGW build.
astroray::ParamDict volumetricParams(const py::dict& d) {
    astroray::ParamDict p;
    for (auto item : d) {
        const std::string key = py::str(item.first);
        if (py::isinstance<py::bool_>(item.second)) p.set(key, item.second.cast<bool>());
        else p.set(key, item.second.cast<float>());
    }
    return p;
}

astroray::SampledWavelengths volumetricLambdas(const std::vector<float>& nm) {
    if (nm.size() != size_t(astroray::kSpectrumSamples))
        throw std::invalid_argument("lambdas_nm needs kSpectrumSamples values");
    std::array<float, astroray::kSpectrumSamples> a{};
    for (int i = 0; i < astroray::kSpectrumSamples; ++i) a[i] = nm[i];
    return astroray::SampledWavelengths::fromLambdas(a);
}

Vec3 toVec3(const std::array<double, 3>& v) { return Vec3(float(v[0]), float(v[1]), float(v[2])); }

std::vector<float> spectrumValues(const astroray::SampledSpectrum& s) {
    return std::vector<float>(s.values().begin(), s.values().end());
}

template <class Model>
astroray::SampledSpectrum volumetricSegmentFor(
        const Model& m, const Vec3& pos, const Vec3& dir,
        const astroray::SampledWavelengths& lambdas, double ds,
        const py::object& beta, astroray::SampledSpectrum& tau) {
    Vec3 betaDir;
    double b = 0.0;
    if (!beta.is_none()) {
        const auto v = beta.cast<std::array<double, 3>>();
        b = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
        betaDir = b > 0.0 ? toVec3({v[0] / b, v[1] / b, v[2] / b}) : Vec3(0.0f, 1.0f, 0.0f);
    } else {
        m.fluidVelocity(pos, betaDir, b);
    }
    return m.transportSegment(pos, dir, lambdas, ds, betaDir, b, tau);
}

std::shared_ptr<Emission> makeVolumetric(const std::string& model, const py::dict& params) {
    if (model == "adaf")
        return std::make_shared<astroray::adaf::ADAF>(volumetricParams(params));
    if (model == "synchrotron_jet")
        return std::make_shared<astroray::synchrotron::SynchrotronJet>(volumetricParams(params));
    throw std::invalid_argument("model must be 'adaf' or 'synchrotron_jet'");
}

std::pair<std::vector<float>, std::vector<float>> volumetricSegment(
        const std::string& model, const py::dict& params,
        std::array<double, 3> position, std::array<double, 3> photon_dir,
        const std::vector<float>& lambdas_nm, double ds_cm,
        const py::object& beta) {
    const auto emission = makeVolumetric(model, params);
    const auto lambdas = volumetricLambdas(lambdas_nm);
    astroray::SampledSpectrum tau(0.0f), out(0.0f);
    if (auto* a = dynamic_cast<const astroray::adaf::ADAF*>(emission.get()))
        out = volumetricSegmentFor(*a, toVec3(position), toVec3(photon_dir), lambdas, ds_cm, beta, tau);
    else if (auto* j = dynamic_cast<const astroray::synchrotron::SynchrotronJet*>(emission.get()))
        out = volumetricSegmentFor(*j, toVec3(position), toVec3(photon_dir), lambdas, ds_cm, beta, tau);
    return {spectrumValues(out), spectrumValues(tau)};
}

std::array<double, 3> volumetricFluidVelocity(const std::string& model, const py::dict& params,
                                              std::array<double, 3> position) {
    const auto emission = makeVolumetric(model, params);
    Vec3 dir;
    double b = 0.0;
    if (auto* a = dynamic_cast<const astroray::adaf::ADAF*>(emission.get()))
        a->fluidVelocity(toVec3(position), dir, b);
    else if (auto* j = dynamic_cast<const astroray::synchrotron::SynchrotronJet*>(emission.get()))
        j->fluidVelocity(toVec3(position), dir, b);
    return {b * dir.x, b * dir.y, b * dir.z};
}

// Uniform chord: n identical segments through the production front-to-back march.
std::vector<float> volumetricChord(const std::string& model, const py::dict& params,
                                   std::array<double, 3> position, std::array<double, 3> photon_dir,
                                   const std::vector<float>& lambdas_nm, double ds_cm, int n) {
    const auto emission = makeVolumetric(model, params);
    const auto lambdas = volumetricLambdas(lambdas_nm);
    astroray::SampledSpectrum I(0.0f), T(1.0f);
    for (int i = 0; i < n; ++i) {
        astroray::SampledSpectrum tau(0.0f);
        const auto seg = emission->integrateSegmentTransfer(
            toVec3(position), toVec3(photon_dir), lambdas, ds_cm, tau);
        astroray::invariant_transfer::accumulateSegment(I, T, seg, tau);
    }
    return spectrumValues(I);
}

} // namespace

PYBIND11_MODULE(astroray_test_helpers, m) {
    m.def("camera_pixel_roundtrip", &cameraPixelRoundtrip, "width"_a, "height"_a,
          "x"_a, "y"_a, "jitter_u"_a, "jitter_v"_a, "orthographic"_a = false,
          "#845: pixel -> film (u,v) -> Camera::getRay -> screenToPixel.");
    m.doc() = "Astroray test/oracle utilities (internal, not public API)";

    // pkg280 — expose the exact production thin-disk transfer helper for
    // analytic invariance tests. This is deliberately not part of astroray's
    // public Python API.
    m.def("thin_disk_invariant_transfer_wavelength",
          &astroray::thinDiskInvariantTransferWavelength,
          "lambda_obs_nm"_a, "temperature_K"_a, "g"_a);
    m.def("thin_disk_emitted_wavelength_nm", &astroray::thinDiskEmittedWavelengthNm,
          "lambda_obs_nm"_a, "g"_a);
    m.def("thin_disk_normalized_transfer_wavelength",
          &astroray::thinDiskNormalizedTransferWavelength,
          "lambda_obs_nm"_a, "temperature_K"_a, "g"_a,
          "exposure_scale"_a, "wavelength_span_nm"_a);
    m.def("thin_disk_accumulate_finite", &astroray::accumulateFiniteThinDiskEmission,
          "accumulated"_a, "contribution"_a);
    m.def("gr_disk_redshift_image", &grDiskRedshiftImage,
          "look_from"_a, "look_at"_a, "vfov"_a, "width"_a, "height"_a,
          "bh_pos"_a, "influence_radius"_a, "disk_outer"_a, "r_obs_M"_a, "spin"_a,
          "pkg282: flat [g, passes] per pixel (g=-1 captured, 0 no disk hit).");
    m.def("gr_renderer_dispatch_probe", &probeGrRendererDispatch,
          // cppcheck-suppress assignBoolToPointer -- pybind11 named-argument default.
          "emission"_a, "clamp_direct"_a = 0.0f, "caustic"_a = false,
          "Runs either Renderer GR dispatch and returns (radiance, trace_calls).");
    m.def("gr_restir_registry_dispatch_probe", &probeRegisteredReSTIRGrDispatch,
          "emission"_a,
          "Instantiates registered restir-di and returns (Y_radiance, trace_calls).");
    // pkg283 volumetric invariant-transport seams.
    m.def("volumetric_fluid_frequency",
          [](double nu_obs, std::array<double, 3> n, std::array<double, 3> beta) {
              const double b = std::sqrt(beta[0] * beta[0] + beta[1] * beta[1] + beta[2] * beta[2]);
              const Vec3 dir = b > 0.0 ? toVec3({beta[0] / b, beta[1] / b, beta[2] / b})
                                       : Vec3(0.0f, 1.0f, 0.0f);
              return astroray::invariant_transfer::fluidFrameFrequency(nu_obs, toVec3(n), dir, b);
          },
          "nu_obs"_a, "photon_dir"_a, "beta"_a, "nu_em = -k.u (flat chord frame).");
    m.def("volumetric_fluid_velocity", &volumetricFluidVelocity,
          "model"_a, "params"_a, "position"_a);
    m.def("volumetric_segment", &volumetricSegment,
          "model"_a, "params"_a, "position"_a, "photon_dir"_a, "lambdas_nm"_a,
          "ds_cm"_a, "beta"_a = py::none(),
          "Production transportSegment: (observed intensity, optical depth).");
    m.def("volumetric_chord", &volumetricChord,
          "model"_a, "params"_a, "position"_a, "photon_dir"_a, "lambdas_nm"_a,
          "ds_cm"_a, "n_segments"_a,
          "n identical segments through the production front-to-back march.");

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
