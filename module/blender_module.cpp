#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <pybind11/functional.h>
#include <pybind11/operators.h>
#include <array>
#include <cctype>
#include <cmath>
#include <mutex>
#include <random>  // pkg191: std::random_device for the GPU seed-0 contract
#include "raytracer.h"
#include "advanced_features.h"
#include "astroray/shapes.h"
#include "astroray/black_hole.h"
#include "astroray/register.h"
#include "astroray/metric.h"
#include "astroray/emission.h"
#include "astroray/synchrotron.h"
#include "astroray/slim_disk.h"
#include "astroray/adaf.h"
#include "astroray/optical_presets.h"
#include "astroray/integrator.h"
#include "astroray/pass.h"
#include "astroray/spectrum.h"
#include "astroray/spectral_profile.h"
#include "astroray/manifold/half_vector_constraint.h"  // pkg106 Chunk A test helper
#include "astroray/manifold/surface_partials.h"         // pkg106 Chunk B test helper
#include "astroray/manifold/newton_iterate.h"           // pkg106 Chunk B test helper
#include "astroray/manifold/manifold_chain.h"           // pkg106 Chunk C test helper
#include "astroray/manifold/mesh_caustic.h"              // pkg106 Chunk D test helper
#include "astroray/photon/photon_map.h"                   // pkg109 photon-map test helper
#include "astroray/restir/reservoir.h"
#include "astroray/restir/light_sample.h"
#include "astroray/restir/frame_state.h"
#include "../src/cpu/wavefront/reference_pt_production.h"
#include "../src/cpu/wavefront/reference_pt_wavefront.h"
#include "../src/cpu/wavefront/cpu_wavefront_driver.h"
#include "../src/cpu/wavefront/snapshot_diff.h"
#include "astroray/sampling/wavefront_rng.h"
#include "astroray/emission_spectrum.h"
#include "astroray/light.h"
#include "astroray/light_tree.h"  // pkg86-B: debug pick probe
#include "astroray/lights/point_light.h"
#include "astroray/lights/spot_light.h"
#include "astroray/lights/distant_light.h"
#include "astroray/lights/area_light.h"
#ifdef ASTRORAY_CUDA_ENABLED
#  include "astroray/gpu_renderer.h"
#  include "astroray/gpu_photon_store.h"   // pkg113 Phase 1 — GPU photon store query
#  include "astroray/gpu_photon_emit.h"    // pkg113 Phase 2 — GPU photon emission/bounce
#  include "astroray/gpu_tlas_parity.h"    // pkg114 inc 1 — two-level BVH identity parity probe
#  ifdef ASTRORAY_WAVEFRONT_CUDA_N3
#    include "../src/gpu/wavefront/gpu_wavefront_snapshot.h"
#  endif
#endif
// pkg87a — Cryptomatte infrastructure
#include "astroray/cryptomatte.h"
// pkg87d — EXR writer for manifest emission
#include "../src/io/exr_writer.h"

namespace py = pybind11;
using namespace pybind11::literals;

static astroray::ParamDict metricParamsFromDict(py::dict params) {
    astroray::ParamDict p;
    for (auto& item : params) {
        auto key = item.first.cast<std::string>();
        if (py::isinstance<py::float_>(item.second) || py::isinstance<py::int_>(item.second)) {
            p.set(key, item.second.cast<float>());
        } else if (py::isinstance<py::bool_>(item.second)) {
            p.set(key, item.second.cast<bool>());
        } else if (py::isinstance<py::str>(item.second)) {
            p.set(key, item.second.cast<std::string>());
        }
    }
    return p;
}

static astroray::ParamDict paramDictFromPyDict(py::dict params) {
    astroray::ParamDict p;
    for (auto& item : params) {
        auto key = item.first.cast<std::string>();
        if (py::isinstance<py::bool_>(item.second)) {
            p.set(key, item.second.cast<bool>());
        } else if (py::isinstance<py::float_>(item.second) || py::isinstance<py::int_>(item.second)) {
            p.set(key, item.second.cast<float>());
        } else if (py::isinstance<py::str>(item.second)) {
            p.set(key, item.second.cast<std::string>());
        } else if (py::isinstance<py::list>(item.second) || py::isinstance<py::tuple>(item.second)) {
            auto values = item.second.cast<std::vector<float>>();
            if (values.size() == 3) p.set(key, Vec3(values[0], values[1], values[2]));
            else p.set(key, values);
        }
    }
    return p;
}

// pkg89 Phase B: parse EmissionSpectrum from Python dict.
// Expected keys:
//   - "mode": "blackbody" | "rgb" | "measured_spd" | "composite"
//   - For blackbody: "temperature_K" (float), "tint_rgb" ([r,g,b])
//   - For rgb: "color" ([r,g,b])
//   - For measured_spd: "profile_name" (string)
//   - For composite: "base" (dict), "filter_rgb" ([r,g,b])
static astroray::EmissionSpectrum parseEmissionSpectrum(py::dict emissionDict) {
    std::string mode = "blackbody";  // default
    if (emissionDict.contains("mode")) {
        mode = emissionDict["mode"].cast<std::string>();
    }

    if (mode == "blackbody") {
        float tempK = emissionDict.contains("temperature_K") ?
            emissionDict["temperature_K"].cast<float>() : 6500.0f;
        Vec3 tint(1.0f, 1.0f, 1.0f);
        if (emissionDict.contains("tint_rgb")) {
            auto tintVec = emissionDict["tint_rgb"].cast<std::vector<float>>();
            if (tintVec.size() == 3) {
                tint = Vec3(tintVec[0], tintVec[1], tintVec[2]);
            }
        }
        return astroray::EmissionSpectrum(
            astroray::EmissionSpectrum::Blackbody{tempK, tint}
        );
    } else if (mode == "rgb") {
        Vec3 color(1.0f, 1.0f, 1.0f);
        if (emissionDict.contains("color")) {
            auto colorVec = emissionDict["color"].cast<std::vector<float>>();
            if (colorVec.size() == 3) {
                color = Vec3(colorVec[0], colorVec[1], colorVec[2]);
            }
        }
        return astroray::EmissionSpectrum(
            astroray::EmissionSpectrum::RGB{color}
        );
    } else if (mode == "measured_spd") {
        std::string profileName = emissionDict.contains("profile_name") ?
            emissionDict["profile_name"].cast<std::string>() : "D65";
        return astroray::EmissionSpectrum(
            astroray::EmissionSpectrum::MeasuredSPD{profileName}
        );
    } else if (mode == "composite") {
        if (!emissionDict.contains("base")) {
            throw std::runtime_error("Composite EmissionSpectrum requires 'base' dict");
        }
        auto baseDict = emissionDict["base"].cast<py::dict>();
        auto baseSpectrum = parseEmissionSpectrum(baseDict);
        Vec3 filter(1.0f, 1.0f, 1.0f);
        if (emissionDict.contains("filter_rgb")) {
            auto filterVec = emissionDict["filter_rgb"].cast<std::vector<float>>();
            if (filterVec.size() == 3) {
                filter = Vec3(filterVec[0], filterVec[1], filterVec[2]);
            }
        }
        return astroray::EmissionSpectrum(
            astroray::EmissionSpectrum::Composite{
                std::make_unique<astroray::EmissionSpectrum>(std::move(baseSpectrum)),
                filter
            }
        );
    } else {
        throw std::runtime_error("Unknown EmissionSpectrum mode: " + mode);
    }
}

class TextureManager {
    std::unordered_map<std::string, std::shared_ptr<ImageTexture>> imageTextures;
    std::unordered_map<std::string, std::shared_ptr<Texture>> proceduralTextures;
    // pkg219b — per-texel op-VM chains (Color Ramp / Mix / Math / Map Range
    // downstream of a texture). Registered separately so scene_upload can
    // detect them and upload the compiled program to the GPU.
    std::unordered_map<std::string, std::shared_ptr<ProgramTexture>> programTextures;
    static Texture::CoordMode parseCoordMode(const std::string& mode) {
        std::string m = mode;
        for (char& c : m) c = static_cast<char>(std::toupper(c));
        if (m == "UV") return Texture::CoordMode::UV;
        if (m == "GENERATED") return Texture::CoordMode::Generated;
        if (m == "OBJECT") return Texture::CoordMode::Object;
        if (m == "CAMERA") return Texture::CoordMode::Camera;
        if (m == "NORMAL") return Texture::CoordMode::Normal;
        if (m == "REFLECTION") return Texture::CoordMode::Reflection;
        if (m == "WINDOW") return Texture::CoordMode::Window;
        throw std::runtime_error("Unknown texture coordinate mode: " + mode);
    }
public:
    void loadImageTexture(const std::string& name, py::array_t<float> imageData, int width, int height,
                          const std::string& coordMode = "UV") {
        auto buf = imageData.request();
        float* ptr = static_cast<float*>(buf.ptr);
        std::vector<Vec3> data(width * height);
        for (int i = 0; i < width * height; i++)
            data[i] = Vec3(ptr[i*3], ptr[i*3+1], ptr[i*3+2]);
        auto tex = std::make_shared<ImageTexture>();
        tex->setData(data, width, height);
        tex->setCoordMode(parseCoordMode(coordMode));
        imageTextures[name] = tex;
    }
    void createProceduralTexture(const std::string& name, const std::string& type, const std::vector<float>& params,
                                 const std::string& coordMode = "UV") {
        auto mode = parseCoordMode(coordMode);
        if (type == "checker") {
            Vec3 c1(params[0], params[1], params[2]), c2(params[3], params[4], params[5]);
            float scale = params.size() > 6 ? params[6] : 10.0f;
            proceduralTextures[name] = std::make_shared<CheckerTexture>(c1, c2, scale);
        } else if (type == "noise") {
            proceduralTextures[name] = std::make_shared<NoiseTexture>(params.size() > 0 ? params[0] : 1.0f);
        } else if (type == "noise_perlin") {
            // pkg115 chunk 2 + chunk 6 (addon dedup): ShaderNodeTexNoise → NoiseTextureCycles.
            // Params: [scale, detail, roughness, lacunarity, offset, gain, distortion, noise_type, normalize]
            float scale = params.size() > 0 ? params[0] : 5.0f;
            float detail = params.size() > 1 ? params[1] : 2.0f;
            float roughness = params.size() > 2 ? params[2] : 0.5f;
            float lacunarity = params.size() > 3 ? params[3] : 2.0f;
            float offset = params.size() > 4 ? params[4] : 0.0f;
            float gain = params.size() > 5 ? params[5] : 1.0f;
            float distortion = params.size() > 6 ? params[6] : 0.0f;
            int noise_type = params.size() > 7 ? (int)params[7] : 0;
            bool normalize = params.size() > 8 ? (params[8] != 0.0f) : true;
            proceduralTextures[name] = std::make_shared<NoiseTextureCycles>(
                scale, detail, roughness, lacunarity, offset, gain, distortion, noise_type, normalize);
        } else if (type == "marble") {
            proceduralTextures[name] = std::make_shared<MarbleTexture>(params.size() > 0 ? params[0] : 1.0f);
        } else if (type == "wood") {
            proceduralTextures[name] = std::make_shared<WoodTexture>(params.size() > 0 ? params[0] : 1.0f);
        } else if (type == "gradient") {
            // params: [grad_type, scale, r1,g1,b1, r2,g2,b2]
            int gt = params.size() > 0 ? (int)params[0] : 0;
            float sc = params.size() > 1 ? params[1] : 1.0f;
            Vec3 c1 = params.size() > 4 ? Vec3(params[2], params[3], params[4]) : Vec3(0);
            Vec3 c2 = params.size() > 7 ? Vec3(params[5], params[6], params[7]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<GradientTexture>(gt, c1, c2, sc);
        } else if (type == "wave") {
            // pkg115 chunk 3 + chunk 6 (addon dedup): full Cycles-parity Wave.
            // Params: [wave_type, bands_direction, rings_direction, profile, scale, distortion,
            //          detail, detail_scale, detail_roughness, phase_offset, r1,g1,b1, r2,g2,b2]
            // Legacy 13-param scripts (band_dir, profile, scale, distortion, detail, roughness,
            // lacunarity, r,g,b, r,g,b) are handled by treating param[0] as bands_direction and
            // defaulting wave_type=0, rings_dir=0, phase=0, dscale=1 — preserves old behavior.
            int wt = params.size() > 0 ? (int)params[0] : 0;
            int bd = params.size() > 1 ? (int)params[1] : 0;
            int rd = params.size() > 2 ? (int)params[2] : 0;
            int pf = params.size() > 3 ? (int)params[3] : 0;
            float sc = params.size() > 4 ? params[4] : 5.0f;
            float dist = params.size() > 5 ? params[5] : 0.0f;
            float det = params.size() > 6 ? params[6] : 2.0f;
            float dscale = params.size() > 7 ? params[7] : 1.0f;
            float rough = params.size() > 8 ? params[8] : 0.5f;
            float phase = params.size() > 9 ? params[9] : 0.0f;
            Vec3 c1 = params.size() > 12 ? Vec3(params[10], params[11], params[12]) : Vec3(0);
            Vec3 c2 = params.size() > 15 ? Vec3(params[13], params[14], params[15]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<WaveTexture>(
                wt, bd, rd, pf, sc, dist, det, dscale, rough, phase, c1, c2);
        } else if (type == "magic") {
            // params: [depth, scale, distortion, r1,g1,b1, r2,g2,b2]
            int depth = params.size() > 0 ? (int)params[0] : 2;
            float sc = params.size() > 1 ? params[1] : 5.0f;
            float dist = params.size() > 2 ? params[2] : 1.0f;
            Vec3 c1 = params.size() > 5 ? Vec3(params[3], params[4], params[5]) : Vec3(0);
            Vec3 c2 = params.size() > 8 ? Vec3(params[6], params[7], params[8]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<MagicTexture>(depth, sc, dist, c1, c2);
        } else if (type == "voronoi") {
            // Params (positional, backward-compatible):
            //   [0..4]  scale, randomness, dist_metric, feature, smoothness
            //   [5..10] r1,g1,b1, r2,g2,b2            (color_low, color_high)
            //   [11..15] detail, roughness, lacunarity, exponent, normalize   (pkg115 item 10)
            // Legacy 5-param + colour scripts (size <= 11) keep working: the trailing
            // Cycles-parity params (detail/roughness/lacunarity/exponent/normalize) default
            // off, so a non-fractal, non-normalised F1 matches the old behaviour. The addon
            // translator passes all 16 to drive full ShaderNodeTexVoronoi parity.
            float sc = params.size() > 0 ? params[0] : 5.0f;
            float rand = params.size() > 1 ? params[1] : 1.0f;
            int dm = params.size() > 2 ? (int)params[2] : 0;
            int feat = params.size() > 3 ? (int)params[3] : 0;
            float smooth = params.size() > 4 ? params[4] : 1.0f;
            Vec3 c1 = params.size() > 7 ? Vec3(params[5], params[6], params[7]) : Vec3(0);
            Vec3 c2 = params.size() > 10 ? Vec3(params[8], params[9], params[10]) : Vec3(1);
            float det = params.size() > 11 ? params[11] : 0.0f;
            float rough = params.size() > 12 ? params[12] : 0.5f;
            float lac = params.size() > 13 ? params[13] : 2.0f;
            float expo = params.size() > 14 ? params[14] : 0.5f;
            bool norm = params.size() > 15 ? (params[15] != 0.0f) : false;
            // New ctor: (scale, detail, roughness, lacunarity, smoothness, exponent, randomness,
            //            normalize, dist_metric, feature, color_low, color_high).
            proceduralTextures[name] = std::make_shared<VoronoiTexture>(
                sc, det, rough, lac, smooth, expo, rand, norm, dm, feat, c1, c2);
        } else if (type == "brick") {
            // pkg115 chunk 3 + chunk 6 (addon dedup): full Cycles-parity Brick.
            // Params: [brick1_r,g,b, brick2_r,g,b, mortar_r,g,b, scale, mortar_size, mortar_smooth,
            //          bias, brick_width, row_height, offset_amount, offset_freq, squash, squash_freq]
            // Legacy 11-param scripts (brick, mortar, bw, bh, ms, offset, scale) default color2=color1
            // (no per-brick variation) and the Blender-default mortar_smooth/bias/offsets.
            Vec3 c1 = params.size() > 2 ? Vec3(params[0], params[1], params[2]) : Vec3(0.8f);
            Vec3 c2 = params.size() > 5 ? Vec3(params[3], params[4], params[5]) : c1;
            Vec3 mortar = params.size() > 8 ? Vec3(params[6], params[7], params[8]) : Vec3(0.0f);
            float sc = params.size() > 9 ? params[9] : 5.0f;
            float ms = params.size() > 10 ? params[10] : 0.02f;
            float msmooth = params.size() > 11 ? params[11] : 0.1f;
            float bias = params.size() > 12 ? params[12] : 0.0f;
            float bw = params.size() > 13 ? params[13] : 0.5f;
            float rh = params.size() > 14 ? params[14] : 0.25f;
            float offamt = params.size() > 15 ? params[15] : 0.5f;
            int offfreq = params.size() > 16 ? (int)params[16] : 2;
            float sq = params.size() > 17 ? params[17] : 1.0f;
            int sqfreq = params.size() > 18 ? (int)params[18] : 2;
            proceduralTextures[name] = std::make_shared<BrickTexture>(
                c1, c2, mortar, sc, ms, msmooth, bias, bw, rh, offamt, offfreq, sq, sqfreq);
        } else if (type == "musgrave") {
            // params: [musgrave_type, scale, detail, dimension, lacunarity, gain, r1,g1,b1, r2,g2,b2]
            int mt = params.size() > 0 ? (int)params[0] : 0;
            float sc = params.size() > 1 ? params[1] : 5.0f;
            float det = params.size() > 2 ? params[2] : 2.0f;
            float dim = params.size() > 3 ? params[3] : 2.0f;
            float lac = params.size() > 4 ? params[4] : 2.0f;
            float g = params.size() > 5 ? params[5] : 1.0f;
            Vec3 c1 = params.size() > 8 ? Vec3(params[6], params[7], params[8]) : Vec3(0);
            Vec3 c2 = params.size() > 11 ? Vec3(params[9], params[10], params[11]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<MusgraveTexture>(mt, sc, det, dim, lac, g, c1, c2);
        }
        auto it = proceduralTextures.find(name);
        if (it != proceduralTextures.end() && it->second) {
            it->second->setCoordMode(mode);
        }
    }
    void setTextureCoordMode(const std::string& name, const std::string& coordMode) {
        auto mode = parseCoordMode(coordMode);
        if (auto tex = getTexture(name)) tex->setCoordMode(mode);
    }

    void setTextureGeneratedBBox(const std::string& name,
                                 const std::vector<float>& bmin,
                                 const std::vector<float>& bsize) {
        if (bmin.size() < 3 || bsize.size() < 3)
            throw std::runtime_error("set_texture_generated_bbox: 3 floats each");
        if (auto tex = getTexture(name))
            tex->setGeneratedBBox(Vec3(bmin[0], bmin[1], bmin[2]),
                                  Vec3(bsize[0], bsize[1], bsize[2]));
    }
    // pkg59 follow-up: bake a Blender Mapping node's Location + Rotation.z +
    // Scale into a per-texture UV transform applied at sample time.
    void setTextureUVTransform(const std::string& name,
                               float sx, float sy, float ox, float oy,
                               float rotZRad = 0.0f) {
        if (auto tex = getTexture(name)) tex->setUVTransform(sx, sy, ox, oy, rotZRad);
    }
    void setTextureUVLayerName(const std::string& name, const std::string& layerName) {
        if (auto tex = getTexture(name)) tex->setUVLayerName(layerName);
    }
    // pkg219a: full 3-D Mapping matrix (top 3x4 rows, row-major) composed by the
    // addon with mathutils.Matrix.LocRotScale (exact Blender euler parity).
    void setTextureMappingMatrix(const std::string& name,
                                 const std::vector<float>& m) {
        if (m.size() != 12)
            throw std::runtime_error("set_texture_mapping_matrix: expected 12 floats (3x4 row-major)");
        if (auto tex = getTexture(name)) tex->setMappingMatrix(m.data());
    }
    std::shared_ptr<Texture> getTexture(const std::string& name) {
        auto it1 = imageTextures.find(name);
        if (it1 != imageTextures.end()) return it1->second;
        auto it2 = proceduralTextures.find(name);
        if (it2 != proceduralTextures.end()) return it2->second;
        auto it3 = programTextures.find(name);
        if (it3 != programTextures.end()) return it3->second;
        return nullptr;
    }

    // ---- pkg219b op-VM builder API -----------------------------------------
    void createProgramTexture(const std::string& name, const std::string& coordMode) {
        auto pt = std::make_shared<ProgramTexture>();
        pt->setCoordMode(parseCoordMode(coordMode));
        programTextures[name] = pt;
    }
    void programTextureAddInput(const std::string& name, const std::string& inputName) {
        auto it = programTextures.find(name);
        if (it == programTextures.end())
            throw std::runtime_error("program_texture_add_input: unknown program texture " + name);
        auto child = getTexture(inputName);
        if (!child)
            throw std::runtime_error("program_texture_add_input: unknown input texture " + inputName);
        it->second->addInput(child);
    }
    // Set the compiled program from flat buffers. code_flat is 8 ints/instr
    // (op,out,a,b,c,d,e,imm); consts_flat is 3 floats/const; ramps_flat is
    // numRamps*RAMP_TABLE_SIZE*3 floats (row-major per ramp).
    void setProgramTextureProgram(const std::string& name, int numTex, int outSlot,
                                  const std::vector<int>& code_flat,
                                  const std::vector<float>& consts_flat,
                                  const std::vector<float>& ramps_flat) {
        using namespace astroray::svm;
        auto it = programTextures.find(name);
        if (it == programTextures.end())
            throw std::runtime_error("set_program_texture_program: unknown program texture " + name);
        if (code_flat.size() % 8 != 0)
            throw std::runtime_error("set_program_texture_program: code_flat not a multiple of 8");
        int numInstr = (int)(code_flat.size() / 8);
        if (numInstr > VM_MAX_INSTR)
            throw std::runtime_error("set_program_texture_program: program exceeds VM_MAX_INSTR");
        int numConst = (int)(consts_flat.size() / 3);
        if (numConst > VM_MAX_CONST)
            throw std::runtime_error("set_program_texture_program: too many constants");
        if (ramps_flat.size() % (RAMP_TABLE_SIZE * 3) != 0)
            throw std::runtime_error("set_program_texture_program: ramps_flat wrong length");
        int numRamps = (int)(ramps_flat.size() / (RAMP_TABLE_SIZE * 3));
        if (numRamps > VM_MAX_RAMPS)
            throw std::runtime_error("set_program_texture_program: too many ramps");
        ShaderVMProgram prog;
        prog.numInstr = numInstr;
        prog.outSlot  = outSlot;
        prog.numTex   = numTex;
        prog.numRamps = numRamps;
        for (int i = 0; i < numInstr; ++i) {
            Instr& in = prog.code[i];
            in.op  = (unsigned char)code_flat[i*8+0];
            in.out = (unsigned char)code_flat[i*8+1];
            in.a   = (unsigned char)code_flat[i*8+2];
            in.b   = (unsigned char)code_flat[i*8+3];
            in.c   = (unsigned char)code_flat[i*8+4];
            in.d   = (unsigned char)code_flat[i*8+5];
            in.e   = (unsigned char)code_flat[i*8+6];
            in.imm = (unsigned char)code_flat[i*8+7];
        }
        for (int i = 0; i < numConst; ++i)
            prog.consts[i] = GVec3(consts_flat[i*3], consts_flat[i*3+1], consts_flat[i*3+2]);
        for (int r = 0; r < numRamps; ++r)
            for (int s = 0; s < RAMP_TABLE_SIZE; ++s) {
                int base = (r * RAMP_TABLE_SIZE + s) * 3;
                prog.ramp[r][s] = GVec3(ramps_flat[base], ramps_flat[base+1], ramps_flat[base+2]);
            }
        it->second->setProgram(prog);
    }
};

class PyRenderer {
    Renderer renderer;
    std::shared_ptr<Camera> camera;
    TextureManager textureManager;
    std::unordered_map<int, std::shared_ptr<Material>> materials;
    int nextMaterialId = 0;
    bool useAdaptiveSampling = true;
    std::shared_ptr<EnvironmentMap> envMap;
    bool useGPU = false;
    astroray::ParamDict integratorParams_;
    // pkg148: default-construct to "path_tracer" instead of empty. This mirrors
    // Renderer::ensureDefaultIntegrator()'s lazy CPU default (src/default_integrator.cpp),
    // which silently patches a null CPU integrator_ to "path_tracer" inside
    // Renderer::render() — a fallback the GPU dispatch below has no equivalent
    // of. The GPU branch keys directly off integratorName_ (":1745-1766"), so an
    // empty name fell through to the legacy no-NEE megakernel and rendered
    // dedicated-light scenes solid black on a fresh Renderer. See
    // .astroray_plan/packages/pkg148-default-integrator-empty-string.md.
    std::string integratorName_ = "path_tracer";
    // pkg55-C6b: globally-unique id assigned at each set_integrator call. The
    // GPU ReSTIR driver keys its persistent (double-buffered) reservoir history
    // on this id and RESETS the temporal history when it changes — so a fresh
    // integrator instance (e.g. a new renderer) starts with no prior frame,
    // while a persistent renderer that renders a sequence WITHOUT recreating its
    // integrator keeps accumulating. This mirrors the CPU restir_di frameState_
    // per-instance ownership (frame_state.h), defeating global-WfContext bleed
    // across independent renders (the TestDeterminism isolation requirement).
    uint64_t restirSessionId_ = 0;
    // pkg89 Phase B: IES profile cache (shared_ptr keeps profiles alive).
    std::unordered_map<std::string, std::shared_ptr<IESProfile>> iesProfiles_;
#ifdef ASTRORAY_CUDA_ENABLED
    std::unique_ptr<CUDARenderer> cudaRenderer;
#endif

    // pkg89 Phase B: load and cache IES profile.
    const IESProfile* getOrLoadIESProfile(const std::string& iesFile) {
        if (iesFile.empty()) return nullptr;
        auto it = iesProfiles_.find(iesFile);
        if (it != iesProfiles_.end()) {
            return it->second.get();
        }
        auto profile = IESProfile::loadFromFile(iesFile);
        if (!profile) return nullptr;
        iesProfiles_[iesFile] = profile;
        return profile.get();
    }

public:
    void loadTexture(const std::string& name, py::array_t<float> imageData, int width, int height,
                     const std::string& coordMode = "UV") {
        textureManager.loadImageTexture(name, imageData, width, height, coordMode);
    }
    void createProceduralTexture(const std::string& name, const std::string& type, const std::vector<float>& params,
                                 const std::string& coordMode = "UV") {
        textureManager.createProceduralTexture(name, type, params, coordMode);
    }
    void setTextureGeneratedBBox(const std::string& name,
                                 const std::vector<float>& bmin,
                                 const std::vector<float>& bsize) {
        textureManager.setTextureGeneratedBBox(name, bmin, bsize);
    }
    void setTextureCoordMode(const std::string& name, const std::string& coordMode) {
        textureManager.setTextureCoordMode(name, coordMode);
    }
    void setTextureUVTransform(const std::string& name,
                               float sx, float sy, float ox, float oy,
                               float rotZRad = 0.0f) {
        textureManager.setTextureUVTransform(name, sx, sy, ox, oy, rotZRad);
    }
    void setTextureUVLayerName(const std::string& name, const std::string& layerName) {
        textureManager.setTextureUVLayerName(name, layerName);
    }
    void setTextureMappingMatrix(const std::string& name,
                                 const std::vector<float>& m) {
        textureManager.setTextureMappingMatrix(name, m);
    }
    // pkg219b op-VM builder forwarders.
    void createProgramTexture(const std::string& name, const std::string& coordMode) {
        textureManager.createProgramTexture(name, coordMode);
    }
    void programTextureAddInput(const std::string& name, const std::string& inputName) {
        textureManager.programTextureAddInput(name, inputName);
    }
    void setProgramTextureProgram(const std::string& name, int numTex, int outSlot,
                                  const std::vector<int>& code_flat,
                                  const std::vector<float>& consts_flat,
                                  const std::vector<float>& ramps_flat) {
        textureManager.setProgramTextureProgram(name, numTex, outSlot,
                                                code_flat, consts_flat, ramps_flat);
    }

    // pkg219b test helper — sample a registered texture (image / procedural /
    // program) at (u,v), with p=(u,v,0). Exercises the op-VM directly.
    std::vector<float> sampleNamedTexture(const std::string& name, float u, float v) {
        auto tex = textureManager.getTexture(name);
        if (!tex) throw std::runtime_error("sample_named_texture: unknown texture " + name);
        Vec3 r = tex->value(Vec2(u, v), Vec3(u, v, 0.0f));
        return {r.x, r.y, r.z};
    }

    std::vector<float> sampleTexture(const std::string& type, py::dict params, float u, float v) {
        astroray::ParamDict p;
        for (auto& item : params) {
            auto key = item.first.cast<std::string>();
            if (py::isinstance<py::float_>(item.second) || py::isinstance<py::int_>(item.second))
                p.set(key, item.second.cast<float>());
            else if (py::isinstance<py::str>(item.second))
                p.set(key, item.second.cast<std::string>());
            else if (py::isinstance<py::list>(item.second) || py::isinstance<py::tuple>(item.second)) {
                auto seq = item.second.cast<std::vector<float>>();
                if (seq.size() == 3) p.set(key, Vec3(seq[0], seq[1], seq[2]));
            }
        }
        auto tex = astroray::TextureRegistry::instance().create(type, p);
        Vec3 result = tex->value(Vec2(u, v), Vec3(u, v, u));
        return {result.x, result.y, result.z};
    }

    // pkg115: debug helper for procedural-parity tests. Evaluates a texture at an
    // explicit 3D point (not constrained to (u,v,u) like sample_texture).
    std::vector<float> evalTextureAt3D(const std::string& type, py::dict params, float x, float y, float z) {
        astroray::ParamDict p;
        for (auto& item : params) {
            auto key = item.first.cast<std::string>();
            if (py::isinstance<py::float_>(item.second) || py::isinstance<py::int_>(item.second))
                p.set(key, item.second.cast<float>());
            else if (py::isinstance<py::str>(item.second))
                p.set(key, item.second.cast<std::string>());
            else if (py::isinstance<py::list>(item.second) || py::isinstance<py::tuple>(item.second)) {
                auto seq = item.second.cast<std::vector<float>>();
                if (seq.size() == 3) p.set(key, Vec3(seq[0], seq[1], seq[2]));
            }
        }
        auto tex = astroray::TextureRegistry::instance().create(type, p);
        Vec3 result = tex->value(Vec2(x, y), Vec3(x, y, z));
        return {result.x, result.y, result.z};
    }

    std::shared_ptr<Material> makeLegacyMaterial(
            const std::string& type, const Vec3& color, const py::dict& params) {
        auto getFloat = [&](const char* k, float d) { return params.contains(k) ? params[k].cast<float>() : d; };
        if (type == "lambertian" || type == "diffuse") {
            if (params.contains("texture")) {
                auto tex = textureManager.getTexture(params["texture"].cast<std::string>());
                if (tex) return std::make_shared<TexturedLambertian>(tex);
            }
            return std::make_shared<Lambertian>(color);
        }
        // All other types (metal, glass, dielectric, light, emission, disney, subsurface, phong,
        // normal_mapped, mirror) are handled by the registry in createMaterial before this fallback.
        return std::make_shared<Lambertian>(color);
    }

    int createMaterial(const std::string& type, const std::vector<float>& baseColor, py::dict params) {
        Vec3 color(baseColor[0], baseColor[1], baseColor[2]);
        auto getFloat = [&](const char* k, float d) { return params.contains(k) ? params[k].cast<float>() : d; };
        auto getTexture = [&](const char* k) -> std::shared_ptr<Texture> {
            return params.contains(k) ? textureManager.getTexture(params[k].cast<std::string>()) : nullptr;
        };
        astroray::ParamDict p;
        p.set("albedo", color);
        for (auto& item : params) {
            auto key = item.first.cast<std::string>();
            if (py::isinstance<py::float_>(item.second) || py::isinstance<py::int_>(item.second))
                p.set(key, item.second.cast<float>());
            else if (py::isinstance<py::str>(item.second))
                p.set(key, item.second.cast<std::string>());
            // pkg178 Stage 3: list/tuple -> Vec3, mirroring paramDictFromPyDict.
            // Without this, EVERY vec3 material socket driven via the params dict
            // (Principled coat_tint / sheen_tint / subsurface_radius / emission_color,
            // and even Stage-1 specular_tint) was silently dropped to its default.
            else if (py::isinstance<py::list>(item.second) || py::isinstance<py::tuple>(item.second)) {
                auto values = item.second.cast<std::vector<float>>();
                if (values.size() == 3) p.set(key, Vec3(values[0], values[1], values[2]));
                else p.set(key, values);
            }
        }
        std::shared_ptr<Material> mat;
        if (!params.contains("texture")) {
            try { mat = astroray::MaterialRegistry::instance().create(type, p); }
            catch (const std::runtime_error&) {}
        }
        if (!mat) mat = makeLegacyMaterial(type, color, params);
        auto normalTex = getTexture("normal_map_texture"), bumpTex = getTexture("bump_map_texture");
        if (normalTex || bumpTex)
            mat = astroray::makeNormalMapped(mat, normalTex, bumpTex,
                getFloat("normal_strength", 1.0f), getFloat("bump_strength", 1.0f), getFloat("bump_distance", 0.01f));
        int id = nextMaterialId++;
        materials[id] = mat;
        return id;
    }

    static float halton(int index, int base) {
        float f = 1.0f;
        float r = 0.0f;
        while (index > 0) {
            f /= float(base);
            r += f * float(index % base);
            index /= base;
        }
        return r;
    }

    HitRecord makeMaterialTestRecord(const std::vector<float>& normalInput) const {
        Vec3 n(0.0f, 1.0f, 0.0f);
        if (normalInput.size() == 3) {
            n = Vec3(normalInput[0], normalInput[1], normalInput[2]).normalized();
        }
        HitRecord rec;
        rec.normal = n;
        rec.frontFace = true;
        buildOrthonormalBasis(rec.normal, rec.tangent, rec.bitangent);
        // pkg178 PR-4b: give the aniso path a well-defined UV tangent (= the
        // arbitrary frame, exactly what a sphere hit carries). Isotropic materials
        // never read this, so existing gates are unaffected.
        rec.uvTangent = rec.tangent;
        rec.uvBitangentSign = 1.0f;
        return rec;
    }

    std::vector<float> evalMaterial(int materialId,
                                    const std::vector<float>& woInput,
                                    const std::vector<float>& wiInput,
                                    const std::vector<float>& normalInput = {0.0f, 1.0f, 0.0f}) const {
        auto it = materials.find(materialId);
        if (it == materials.end() || !it->second) {
            throw std::runtime_error("Unknown material id");
        }
        if (woInput.size() != 3 || wiInput.size() != 3) {
            throw std::runtime_error("wo and wi must be 3-element vectors");
        }
        HitRecord rec = makeMaterialTestRecord(normalInput);
        Vec3 wo(woInput[0], woInput[1], woInput[2]);
        Vec3 wi(wiInput[0], wiInput[1], wiInput[2]);
        Vec3 v = it->second->eval(rec, wo.normalized(), wi.normalized());
        return {v.x, v.y, v.z};
    }

    std::vector<float> integrateMaterialReflectance(int materialId,
                                                    float cosThetaO,
                                                    int samples = 4096) const {
        auto it = materials.find(materialId);
        if (it == materials.end() || !it->second) {
            throw std::runtime_error("Unknown material id");
        }
        if (samples <= 0) throw std::runtime_error("samples must be positive");

        HitRecord rec = makeMaterialTestRecord({0.0f, 1.0f, 0.0f});
        cosThetaO = std::clamp(cosThetaO, 0.0f, 1.0f);
        const float sinThetaO = std::sqrt(std::max(0.0f, 1.0f - cosThetaO * cosThetaO));
        const Vec3 wo = (rec.tangent * sinThetaO + rec.normal * cosThetaO).normalized();

        // Hemispherical-directional reflectance via BSDF importance sampling
        // (pbrt-v4 §14.1.6, BxDF::rho hemispherical-directional variant):
        //     rho_hd(wo) = integral_hemisphere f(wo,wi) |cos_i| dwi
        //               ~= (1/N) sum_k  s.f_k / s.pdf_k ,  wi_k ~ Material::sample()
        // Material::sample()'s s.f already carries the |cos_i| factor (eval() returns
        // BRDF * NdotL), so no extra cosine is applied — matching pbrt's Sample_f*cos/pdf
        // when f is defined with the cosine folded in. Reflection only: lower-hemisphere
        // (transmission) draws contribute 0 but still count in N, so a BTDF material's
        // rho stays a true reflectance.
        //
        // pkg123: replaces the previous UNIFORM-hemisphere integration of eval(). Uniform
        // sampling is high-variance and DIVERGES for near-delta GGX lobes once the eval()
        // firefly cap is removed (5e2080c): a lone Halton sample on an uncapped D~1e3-1e4
        // peak inflates the estimate (metallic r=0.1 read 1.31 vs the true ~1.00 verified
        // by furnace render + N->1e6 convergence), while sharp grazing peaks are
        // under-sampled and their real energy violation hidden. Importance sampling draws
        // from the lobe the sampler actually uses, so the estimate is low-variance and
        // does not depend on the D magnitude.
        std::mt19937 gen(0x9e3779b9u);
        Vec3 sum(0.0f);
        for (int i = 0; i < samples; ++i) {
            BSDFSample s = it->second->sample(rec, wo, gen);
            if (s.pdf > 0.0f && rec.normal.dot(s.wi) > 0.0f) {
                sum += s.f / s.pdf;
            }
        }
        const Vec3 reflected = sum / float(samples);
        return {reflected.x, reflected.y, reflected.z};
    }

    // pkg121: batched BSDF sample+pdf for chi² tests (CPU-only).
    // Convention: wo = outgoing to viewer (fixed), sample() returns wi = incoming from light.
    // Returns (wi_array, pdf_array) where wi_array is (N,3) sampled incident directions.
    // u2_array is (2, N) uniform random samples in [0,1]² (currently unused, RNG advances internally).
    py::tuple debug_bsdf_sample_batch(int materialId,
                                      const std::vector<float>& woInput,
                                      py::array_t<float, py::array::c_style | py::array::forcecast> u2_array) {
        auto it = materials.find(materialId);
        if (it == materials.end() || !it->second) {
            throw std::runtime_error("Unknown material id");
        }
        if (woInput.size() != 3) {
            throw std::runtime_error("wo must be a 3-element vector");
        }

        auto u2_buf = u2_array.request();
        if (u2_buf.ndim != 2 || u2_buf.shape[0] != 2) {
            throw std::runtime_error("u2_array must be shape (2, N)");
        }
        const size_t N = static_cast<size_t>(u2_buf.shape[1]);

        HitRecord rec = makeMaterialTestRecord({0.0f, 1.0f, 0.0f});
        Vec3 wo(woInput[0], woInput[1], woInput[2]);
        wo = wo.normalized();

        // Output arrays
        auto wi_array = py::array_t<float>({static_cast<py::ssize_t>(N), py::ssize_t(3)});
        auto pdf_array = py::array_t<float>(static_cast<py::ssize_t>(N));
        auto wi_buf = wi_array.request();
        auto pdf_buf = pdf_array.request();
        float* wi_ptr = static_cast<float*>(wi_buf.ptr);
        float* pdf_ptr = static_cast<float*>(pdf_buf.ptr);

        // Sample in batch (CPU serial, but avoids pybind overhead per sample).
        // Use a single RNG instance that advances state across all samples for
        // statistical independence. The chi² harness generates its own u2_array
        // via NumPy, but Material::sample() consumes random samples from gen,
        // so we let gen advance naturally rather than trying to inject u2 values.
        std::mt19937 gen(12345);
        for (size_t i = 0; i < N; ++i) {
            BSDFSample bs = it->second->sample(rec, wo, gen);
            wi_ptr[i * 3 + 0] = bs.wi.x;
            wi_ptr[i * 3 + 1] = bs.wi.y;
            wi_ptr[i * 3 + 2] = bs.wi.z;
            pdf_ptr[i] = bs.pdf;
        }

        return py::make_tuple(wi_array, pdf_array);
    }

    // pkg121: batched BSDF PDF evaluation (CPU-only).
    // Convention: wo = outgoing to viewer (fixed), wi_array = incoming from light (query points).
    // wi_array is (N, 3), returns pdf_array (N,).
    py::array_t<float> debug_bsdf_pdf_batch(int materialId,
                                            const std::vector<float>& woInput,
                                            py::array_t<float, py::array::c_style | py::array::forcecast> wi_array) {
        auto it = materials.find(materialId);
        if (it == materials.end() || !it->second) {
            throw std::runtime_error("Unknown material id");
        }
        if (woInput.size() != 3) {
            throw std::runtime_error("wo must be a 3-element vector");
        }

        auto wi_buf = wi_array.request();
        if (wi_buf.ndim != 2 || wi_buf.shape[1] != 3) {
            throw std::runtime_error("wi_array must be shape (N, 3)");
        }
        const size_t N = static_cast<size_t>(wi_buf.shape[0]);
        const float* wi_ptr = static_cast<const float*>(wi_buf.ptr);

        HitRecord rec = makeMaterialTestRecord({0.0f, 1.0f, 0.0f});
        Vec3 wo(woInput[0], woInput[1], woInput[2]);
        wo = wo.normalized();

        auto pdf_array = py::array_t<float>(static_cast<py::ssize_t>(N));
        auto pdf_buf = pdf_array.request();
        float* pdf_ptr = static_cast<float*>(pdf_buf.ptr);

        for (size_t i = 0; i < N; ++i) {
            Vec3 wi(wi_ptr[i * 3 + 0], wi_ptr[i * 3 + 1], wi_ptr[i * 3 + 2]);
            wi = wi.normalized();
            pdf_ptr[i] = it->second->pdf(rec, wo, wi);
        }

        return pdf_array;
    }

    void addSphere(const std::vector<float>& center, float radius, int materialId,
                   const std::vector<float>& iesDirection = std::vector<float>(),
                   const std::string& iesFile = "",
                   int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 pos(center[0], center[1], center[2]);
        Vec3 dir(0.0f, -1.0f, 0.0f);
        if (iesDirection.size() == 3) dir = Vec3(iesDirection[0], iesDirection[1], iesDirection[2]);
        auto iesProfile = IESProfile::loadFromFile(iesFile);
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        auto sphere = std::make_shared<Sphere>(pos, radius, mat, dir, iesProfile);
        sphere->setObjectPassIndex(objectPassIndex);
        sphere->setMaterialPassIndex(materialPassIndex);
        renderer.addObject(sphere);
    }

    void addSunLight(const std::vector<float>& direction, float angularDiameter, int materialId,
                     int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 dir(direction[0], direction[1], direction[2]);
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        auto sun = std::make_shared<DistantLight>(dir, angularDiameter, mat);
        sun->setObjectPassIndex(objectPassIndex);
        sun->setMaterialPassIndex(materialPassIndex);
        renderer.addObject(sun);
    }

    void addSpotLight(const std::vector<float>& center, const std::vector<float>& direction, float radius,
                     int materialId, float spotAngle, float spotSmooth, const std::string& iesFile = "",
                     int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 pos(center[0], center[1], center[2]);
        Vec3 dir(direction[0], direction[1], direction[2]);
        auto iesProfile = IESProfile::loadFromFile(iesFile);
        auto mat = [&]() -> std::shared_ptr<Material> {
            if (materials.count(materialId)) return materials[materialId];
            astroray::ParamDict dp; dp.set("albedo", Vec3(1.0f)); dp.set("intensity", 1.0f);
            return astroray::MaterialRegistry::instance().create("light", dp);
        }();
        auto spot = std::make_shared<SpotLightSphere>(pos, radius, mat, dir, spotAngle, spotSmooth, iesProfile);
        spot->setObjectPassIndex(objectPassIndex);
        spot->setMaterialPassIndex(materialPassIndex);
        renderer.addObject(spot);
    }

    void addAreaLight(const std::vector<float>& center, const std::vector<float>& axisU,
                      const std::vector<float>& axisV, float sizeX, float sizeY,
                      const std::string& shape, int materialId, float spread = 1.0f,
                      int objectPassIndex = 0, int materialPassIndex = 0) {
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        std::string shapeUpper = shape;
        for (char& c : shapeUpper) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));

        AreaLightShape::Shape lightShape = AreaLightShape::Shape::Rectangle;
        if (shapeUpper == "DISK") {
            lightShape = AreaLightShape::Shape::Disk;
        } else if (shapeUpper == "ELLIPSE") {
            lightShape = AreaLightShape::Shape::Ellipse;
        }

        auto area = std::make_shared<AreaLightShape>(
            Vec3(center[0], center[1], center[2]),
            Vec3(axisU[0], axisU[1], axisU[2]),
            Vec3(axisV[0], axisV[1], axisV[2]),
            sizeX, sizeY, lightShape, spread, mat);
        area->setObjectPassIndex(objectPassIndex);
        area->setMaterialPassIndex(materialPassIndex);
        renderer.addObject(area);
    }

    // pkg89 Phase B: Dedicated light bindings (use EmissionSpectrum instead of material_id).
    void addPointLight(const std::vector<float>& position, py::dict emissionDict, float intensity,
                       float radius = 0.0f, const std::string& iesFile = "",
                       int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 pos(position[0], position[1], position[2]);
        auto emission = parseEmissionSpectrum(emissionDict);
        const IESProfile* iesProfile = getOrLoadIESProfile(iesFile);
        auto light = std::make_unique<astroray::PointLight>(pos, emission, intensity, radius, iesProfile);
        // Dedicated lights don't have pass indices yet (Phase C unification), so we skip setObjectPassIndex.
        renderer.addDedicatedLight(std::move(light));
    }

    void addSunLightDedicated(const std::vector<float>& direction, float angularDiameter,
                              py::dict emissionDict, float intensity,
                              int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 dir(direction[0], direction[1], direction[2]);
        auto emission = parseEmissionSpectrum(emissionDict);
        auto light = std::make_unique<astroray::DistantLight>(dir, angularDiameter, emission, intensity);
        renderer.addDedicatedLight(std::move(light));
    }

    void addAreaLightDedicated(const std::vector<float>& center, const std::vector<float>& axisU,
                               const std::vector<float>& axisV, float sizeX, float sizeY,
                               const std::string& shape, py::dict emissionDict, float intensity,
                               float spread = 1.0f,
                               int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 pos(center[0], center[1], center[2]);
        Vec3 u(axisU[0], axisU[1], axisU[2]);
        Vec3 v(axisV[0], axisV[1], axisV[2]);
        auto emission = parseEmissionSpectrum(emissionDict);

        std::string shapeUpper = shape;
        for (char& c : shapeUpper) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));

        astroray::AreaLight::Shape lightShape = astroray::AreaLight::Shape::Rectangle;
        if (shapeUpper == "DISK") {
            lightShape = astroray::AreaLight::Shape::Disk;
        } else if (shapeUpper == "ELLIPSE") {
            lightShape = astroray::AreaLight::Shape::Ellipse;
        }

        auto light = std::make_unique<astroray::AreaLight>(
            pos, u, v, sizeX, sizeY, lightShape, emission, intensity, spread
        );
        renderer.addDedicatedLight(std::move(light));
    }

    void addSpotLightDedicated(const std::vector<float>& center, const std::vector<float>& direction,
                               float innerAngle, float outerAngle, py::dict emissionDict, float intensity,
                               float radius = 0.0f, const std::string& iesFile = "",
                               int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 pos(center[0], center[1], center[2]);
        Vec3 dir(direction[0], direction[1], direction[2]);
        auto emission = parseEmissionSpectrum(emissionDict);
        const IESProfile* iesProfile = getOrLoadIESProfile(iesFile);
        auto light = std::make_unique<astroray::SpotLight>(
            pos, dir, innerAngle, outerAngle, emission, intensity, radius, iesProfile
        );
        renderer.addDedicatedLight(std::move(light));
    }

    void addTriangle(const std::vector<float>& v0, const std::vector<float>& v1, const std::vector<float>& v2,
                     int materialId, const std::vector<float>& uv0 = {}, const std::vector<float>& uv1 = {},
                     const std::vector<float>& uv2 = {},
                     const std::vector<float>& n0 = {}, const std::vector<float>& n1 = {},
                     const std::vector<float>& n2 = {},
                     int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 p0(v0[0], v0[1], v0[2]), p1(v1[0], v1[1], v1[2]), p2(v2[0], v2[1], v2[2]);
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        std::shared_ptr<Triangle> tri;
        if (!uv0.empty() && !uv1.empty() && !uv2.empty()) {
            tri = std::make_shared<Triangle>(p0, p1, p2,
                Vec2(uv0[0], uv0[1]), Vec2(uv1[0], uv1[1]), Vec2(uv2[0], uv2[1]), mat);
        } else {
            tri = std::make_shared<Triangle>(p0, p1, p2, mat);
        }
        // Optional per-vertex normals for smooth shading. All three must be
        // provided together; empty vectors trigger the face-normal fallback.
        if (n0.size() == 3 && n1.size() == 3 && n2.size() == 3) {
            tri->setVertexNormals(
                Vec3(n0[0], n0[1], n0[2]),
                Vec3(n1[0], n1[1], n1[2]),
                Vec3(n2[0], n2[1], n2[2]));
        }
        tri->setObjectPassIndex(objectPassIndex);
        tri->setMaterialPassIndex(materialPassIndex);
        renderer.addObject(tri);
    }

    // pkg114 — register a mesh's OBJECT-LOCAL flat-shaded triangles once; the
    // returned mesh id is shared by every add_instance() of it. Mirrors
    // addTriangle's material lookup + Triangle ctor. Flat-shaded (face normals)
    // so the instanced render and a baked-world-space reference agree exactly
    // (avoids interpolate-vs-transform normal-order drift).
    int registerMeshTriangles(const std::vector<std::array<float, 9>>& tris, int materialId,
                              const std::string& objectName = "") {
        auto mat = materials.count(materialId) ? materials[materialId]
                                               : std::make_shared<Lambertian>(Vec3(0.5f));
        std::vector<std::shared_ptr<Hittable>> prims;
        prims.reserve(tris.size());
        for (const auto& t : tris) {
            Vec3 p0(t[0], t[1], t[2]), p1(t[3], t[4], t[5]), p2(t[6], t[7], t[8]);
            auto tri = std::make_shared<Triangle>(p0, p1, p2, mat);
            if (!objectName.empty()) tri->setName(objectName);
            prims.push_back(tri);
        }
        return renderer.registerMesh(prims);
    }
    // pkg114 — instantiate a registered mesh with a row-major 4x4 object->world
    // transform (16 floats, same layout as update_object_transform).
    int addInstance(int meshId, const std::vector<float>& transform) {
        if (transform.size() != 16)
            throw std::runtime_error("add_instance: transform must have 16 floats (row-major 4x4)");
        std::array<float, 16> m;
        for (int i = 0; i < 16; ++i) m[i] = transform[i];
        return renderer.addInstance(meshId, m);
    }

    void addTriangleLayers(const std::vector<float>& v0, const std::vector<float>& v1, const std::vector<float>& v2,
                           int materialId, py::dict uvLayers,
                           const std::vector<float>& n0 = {}, const std::vector<float>& n1 = {},
                           const std::vector<float>& n2 = {},
                           int objectPassIndex = 0, int materialPassIndex = 0) {
        Vec3 p0(v0[0], v0[1], v0[2]), p1(v1[0], v1[1], v1[2]), p2(v2[0], v2[1], v2[2]);
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));

        std::vector<std::array<Vec2, 3>> layers;
        std::vector<std::string> names;
        for (auto item : uvLayers) {
            std::string name = py::cast<std::string>(item.first);
            std::vector<std::vector<float>> coords = py::cast<std::vector<std::vector<float>>>(item.second);
            if (coords.size() != 3 || coords[0].size() < 2 || coords[1].size() < 2 || coords[2].size() < 2) {
                throw std::runtime_error("uv_layers entries must contain three [u, v] pairs");
            }
            names.push_back(name.empty() ? (names.empty() ? "UVMap" : ("UVMap" + std::to_string(names.size() + 1))) : name);
            layers.push_back({
                Vec2(coords[0][0], coords[0][1]),
                Vec2(coords[1][0], coords[1][1]),
                Vec2(coords[2][0], coords[2][1]),
            });
        }

        auto tri = std::make_shared<Triangle>(p0, p1, p2, layers, names, mat);
        if (n0.size() == 3 && n1.size() == 3 && n2.size() == 3) {
            tri->setVertexNormals(
                Vec3(n0[0], n0[1], n0[2]),
                Vec3(n1[0], n1[1], n1[2]),
                Vec3(n2[0], n2[1], n2[2]));
        }
        tri->setObjectPassIndex(objectPassIndex);
        tri->setMaterialPassIndex(materialPassIndex);
        renderer.addObject(tri);
    }

    // pkg112: bulk triangle ingest. One pybind call uploads an entire mesh's
    // triangles from contiguous NumPy arrays, looping in C++ to avoid the
    // per-triangle Python/pybind round-trip that dominates geometry-sync cost.
    // Mirrors addTriangle / addTriangleLayers EXACTLY (same Triangle constructors,
    // same UV-layer-count branching, same normal + pass-index handling) so the
    // result is pixel-identical to the per-triangle path. Layout (all C-contiguous,
    // forcecast): positions (Nt,3,3) world-space corners; materialIds (Nt,) engine
    // material ids (already slot-remapped by the addon); materialPassIndices (Nt,);
    // uvs (nLayers,Nt,3,2) with the ACTIVE layer first (empty -> no UVs); normals
    // (Nt,3,3) world-space corner normals (empty -> face-normal fallback).
    void addTrianglesBulk(
            py::array_t<float, py::array::c_style | py::array::forcecast> positions,
            py::array_t<int,   py::array::c_style | py::array::forcecast> materialIds,
            py::array_t<int,   py::array::c_style | py::array::forcecast> materialPassIndices,
            int objectPassIndex,
            py::array_t<float, py::array::c_style | py::array::forcecast> uvs,
            std::vector<std::string> uvLayerNames,
            py::array_t<float, py::array::c_style | py::array::forcecast> normals) {
        auto pos = positions.unchecked<3>();              // (Nt, 3, 3)
        const py::ssize_t nt = pos.shape(0);
        if (pos.shape(1) != 3 || pos.shape(2) != 3)
            throw std::runtime_error("add_triangles_bulk: positions must be (N,3,3)");
        auto mid = materialIds.unchecked<1>();            // (Nt,)
        auto mpi = materialPassIndices.unchecked<1>();    // (Nt,)
        if (mid.shape(0) != nt || mpi.shape(0) != nt)
            throw std::runtime_error("add_triangles_bulk: material arrays must match triangle count");

        const py::ssize_t nLayers = (uvs.size() > 0) ? uvs.shape(0) : 0;
        const bool hasNormals = normals.size() > 0;
        if (hasNormals && normals.shape(0) != nt)
            throw std::runtime_error("add_triangles_bulk: normals must be (N,3,3)");
        // Layer names are constant across triangles (the mesh's UV-layer set).
        // Mirrors addTriangleLayers' empty-name fallback.
        std::vector<std::string> names;
        for (py::ssize_t l = 0; l < nLayers; ++l) {
            std::string nm = (l < (py::ssize_t)uvLayerNames.size()) ? uvLayerNames[l] : std::string();
            names.push_back(nm.empty() ? (l == 0 ? "UVMap" : "UVMap" + std::to_string(l + 1)) : nm);
        }
        const float* uvPtr = (nLayers > 0) ? uvs.data() : nullptr;   // (nLayers, nt, 3, 2)
        const float* nPtr  = hasNormals ? normals.data() : nullptr;  // (nt, 3, 3)
        auto uvAt = [&](py::ssize_t l, py::ssize_t t, int c) -> Vec2 {
            const float* p = uvPtr + (((l * nt + t) * 3 + c) * 2);
            return Vec2(p[0], p[1]);
        };

        for (py::ssize_t t = 0; t < nt; ++t) {
            Vec3 p0(pos(t, 0, 0), pos(t, 0, 1), pos(t, 0, 2));
            Vec3 p1(pos(t, 1, 0), pos(t, 1, 1), pos(t, 1, 2));
            Vec3 p2(pos(t, 2, 0), pos(t, 2, 1), pos(t, 2, 2));
            int materialId = mid(t);
            auto mat = materials.count(materialId) ? materials[materialId]
                                                   : std::make_shared<Lambertian>(Vec3(0.5f));
            std::shared_ptr<Triangle> tri;
            if (nLayers == 0) {
                tri = std::make_shared<Triangle>(p0, p1, p2, mat);
            } else if (nLayers == 1) {
                tri = std::make_shared<Triangle>(p0, p1, p2,
                        uvAt(0, t, 0), uvAt(0, t, 1), uvAt(0, t, 2), mat);
            } else {
                std::vector<std::array<Vec2, 3>> layers;
                layers.reserve(nLayers);
                for (py::ssize_t l = 0; l < nLayers; ++l)
                    layers.push_back({ uvAt(l, t, 0), uvAt(l, t, 1), uvAt(l, t, 2) });
                tri = std::make_shared<Triangle>(p0, p1, p2, layers, names, mat);
            }
            if (hasNormals) {
                const float* n = nPtr + (t * 9);
                tri->setVertexNormals(Vec3(n[0], n[1], n[2]),
                                      Vec3(n[3], n[4], n[5]),
                                      Vec3(n[6], n[7], n[8]));
            }
            tri->setObjectPassIndex(objectPassIndex);
            tri->setMaterialPassIndex(mpi(t));
            renderer.addObject(tri);
        }
    }

    // pkg114 inc 3 — register a mesh's OBJECT-LOCAL geometry once (UVs / split
    // normals / multi-material), returning its mesh id for add_instance(). This
    // is the bulk twin of registerMeshTriangles: byte-for-byte the same Triangle
    // construction as addTrianglesBulk, but the prims are collected and handed to
    // renderer.registerMesh() (built into one shared BLAS) instead of pushed flat
    // into the scene. Callers pass OBJECT-space corners (identity model matrix);
    // the per-instance world transform is supplied later by add_instance().
    int registerMeshBulk(
            py::array_t<float, py::array::c_style | py::array::forcecast> positions,
            py::array_t<int,   py::array::c_style | py::array::forcecast> materialIds,
            py::array_t<int,   py::array::c_style | py::array::forcecast> materialPassIndices,
            int objectPassIndex,
            py::array_t<float, py::array::c_style | py::array::forcecast> uvs,
            std::vector<std::string> uvLayerNames,
            py::array_t<float, py::array::c_style | py::array::forcecast> normals,
            const std::string& objectName = "") {
        auto pos = positions.unchecked<3>();              // (Nt, 3, 3)
        const py::ssize_t nt = pos.shape(0);
        if (pos.shape(1) != 3 || pos.shape(2) != 3)
            throw std::runtime_error("register_mesh_bulk: positions must be (N,3,3)");
        auto mid = materialIds.unchecked<1>();            // (Nt,)
        auto mpi = materialPassIndices.unchecked<1>();    // (Nt,)
        if (mid.shape(0) != nt || mpi.shape(0) != nt)
            throw std::runtime_error("register_mesh_bulk: material arrays must match triangle count");

        const py::ssize_t nLayers = (uvs.size() > 0) ? uvs.shape(0) : 0;
        const bool hasNormals = normals.size() > 0;
        if (hasNormals && normals.shape(0) != nt)
            throw std::runtime_error("register_mesh_bulk: normals must be (N,3,3)");
        std::vector<std::string> names;
        for (py::ssize_t l = 0; l < nLayers; ++l) {
            std::string nm = (l < (py::ssize_t)uvLayerNames.size()) ? uvLayerNames[l] : std::string();
            names.push_back(nm.empty() ? (l == 0 ? "UVMap" : "UVMap" + std::to_string(l + 1)) : nm);
        }
        const float* uvPtr = (nLayers > 0) ? uvs.data() : nullptr;   // (nLayers, nt, 3, 2)
        const float* nPtr  = hasNormals ? normals.data() : nullptr;  // (nt, 3, 3)
        auto uvAt = [&](py::ssize_t l, py::ssize_t t, int c) -> Vec2 {
            const float* p = uvPtr + (((l * nt + t) * 3 + c) * 2);
            return Vec2(p[0], p[1]);
        };

        std::vector<std::shared_ptr<Hittable>> prims;
        prims.reserve(nt);
        for (py::ssize_t t = 0; t < nt; ++t) {
            Vec3 p0(pos(t, 0, 0), pos(t, 0, 1), pos(t, 0, 2));
            Vec3 p1(pos(t, 1, 0), pos(t, 1, 1), pos(t, 1, 2));
            Vec3 p2(pos(t, 2, 0), pos(t, 2, 1), pos(t, 2, 2));
            int materialId = mid(t);
            auto mat = materials.count(materialId) ? materials[materialId]
                                                   : std::make_shared<Lambertian>(Vec3(0.5f));
            std::shared_ptr<Triangle> tri;
            if (nLayers == 0) {
                tri = std::make_shared<Triangle>(p0, p1, p2, mat);
            } else if (nLayers == 1) {
                tri = std::make_shared<Triangle>(p0, p1, p2,
                        uvAt(0, t, 0), uvAt(0, t, 1), uvAt(0, t, 2), mat);
            } else {
                std::vector<std::array<Vec2, 3>> layers;
                layers.reserve(nLayers);
                for (py::ssize_t l = 0; l < nLayers; ++l)
                    layers.push_back({ uvAt(l, t, 0), uvAt(l, t, 1), uvAt(l, t, 2) });
                tri = std::make_shared<Triangle>(p0, p1, p2, layers, names, mat);
            }
            if (hasNormals) {
                const float* n = nPtr + (t * 9);
                tri->setVertexNormals(Vec3(n[0], n[1], n[2]),
                                      Vec3(n[3], n[4], n[5]),
                                      Vec3(n[6], n[7], n[8]));
            }
            tri->setObjectPassIndex(objectPassIndex);
            tri->setMaterialPassIndex(mpi(t));
            // pkg114 inc 3b — name the BLAS triangles so scene_upload's
            // appendOnePrim hashes the right Cryptomatte object id (the shared
            // BLAS is reused by every instance; the dupli case wants one matte,
            // distinct registrations get distinct names).
            if (!objectName.empty()) tri->setName(objectName);
            prims.push_back(tri);
        }
        return renderer.registerMesh(prims);
    }

    // pkg88-C.0 — bulk motion triangle ingest. Per Cycles motion_triangle.h (Apache-2.0):
    // positions_start (Nt,3,3) is the center step; positions_end (Nt,3,3) is the
    // additional motion step at shutter close. motionSteps=2 → one additional step.
    // Linear interpolation only (matches Cycles, suitable for ≤3 steps).
    void addTrianglesBulkMotion(
            py::array_t<float, py::array::c_style | py::array::forcecast> positions_start,
            py::array_t<float, py::array::c_style | py::array::forcecast> positions_end,
            py::array_t<int,   py::array::c_style | py::array::forcecast> materialIds,
            py::array_t<int,   py::array::c_style | py::array::forcecast> materialPassIndices,
            int objectPassIndex,
            py::array_t<float, py::array::c_style | py::array::forcecast> uvs,
            std::vector<std::string> uvLayerNames,
            py::array_t<float, py::array::c_style | py::array::forcecast> normals) {
        auto pos_start = positions_start.unchecked<3>();              // (Nt, 3, 3)
        auto pos_end   = positions_end.unchecked<3>();                // (Nt, 3, 3)
        const py::ssize_t nt = pos_start.shape(0);
        if (pos_start.shape(1) != 3 || pos_start.shape(2) != 3)
            throw std::runtime_error("add_triangles_bulk_motion: positions_start must be (N,3,3)");
        if (pos_end.shape(0) != nt || pos_end.shape(1) != 3 || pos_end.shape(2) != 3)
            throw std::runtime_error("add_triangles_bulk_motion: positions_end must match positions_start shape");
        auto mid = materialIds.unchecked<1>();            // (Nt,)
        auto mpi = materialPassIndices.unchecked<1>();    // (Nt,)
        if (mid.shape(0) != nt || mpi.shape(0) != nt)
            throw std::runtime_error("add_triangles_bulk_motion: material arrays must match triangle count");

        const py::ssize_t nLayers = (uvs.size() > 0) ? uvs.shape(0) : 0;
        const bool hasNormals = normals.size() > 0;
        if (hasNormals && normals.shape(0) != nt)
            throw std::runtime_error("add_triangles_bulk_motion: normals must be (N,3,3)");
        std::vector<std::string> names;
        for (py::ssize_t l = 0; l < nLayers; ++l) {
            std::string nm = (l < (py::ssize_t)uvLayerNames.size()) ? uvLayerNames[l] : std::string();
            names.push_back(nm.empty() ? (l == 0 ? "UVMap" : "UVMap" + std::to_string(l + 1)) : nm);
        }
        const float* uvPtr = (nLayers > 0) ? uvs.data() : nullptr;
        const float* nPtr  = hasNormals ? normals.data() : nullptr;
        auto uvAt = [&](py::ssize_t l, py::ssize_t t, int c) -> Vec2 {
            const float* p = uvPtr + (((l * nt + t) * 3 + c) * 2);
            return Vec2(p[0], p[1]);
        };

        // Append all motion vertices in one batch, then assign per-triangle offsets
        std::vector<Vec3> motionBatch;
        motionBatch.reserve(nt * 3);  // 3 verts per triangle at shutter close
        for (py::ssize_t t = 0; t < nt; ++t) {
            motionBatch.emplace_back(pos_end(t, 0, 0), pos_end(t, 0, 1), pos_end(t, 0, 2));
            motionBatch.emplace_back(pos_end(t, 1, 0), pos_end(t, 1, 1), pos_end(t, 1, 2));
            motionBatch.emplace_back(pos_end(t, 2, 0), pos_end(t, 2, 1), pos_end(t, 2, 2));
        }
        // pkg98 review fix: appendMotionVertices stores the batch in stable
        // per-batch storage and returns a lifetime-stable pointer (a second
        // bulk call can no longer dangle this batch's triangle pointers).
        const Vec3* motionBase = renderer.appendMotionVertices(std::move(motionBatch));

        for (py::ssize_t t = 0; t < nt; ++t) {
            Vec3 p0(pos_start(t, 0, 0), pos_start(t, 0, 1), pos_start(t, 0, 2));
            Vec3 p1(pos_start(t, 1, 0), pos_start(t, 1, 1), pos_start(t, 1, 2));
            Vec3 p2(pos_start(t, 2, 0), pos_start(t, 2, 1), pos_start(t, 2, 2));
            int materialId = mid(t);
            auto mat = materials.count(materialId) ? materials[materialId]
                                                   : std::make_shared<Lambertian>(Vec3(0.5f));
            std::shared_ptr<Triangle> tri;
            if (nLayers == 0) {
                tri = std::make_shared<Triangle>(p0, p1, p2, mat);
            } else if (nLayers == 1) {
                tri = std::make_shared<Triangle>(p0, p1, p2,
                        uvAt(0, t, 0), uvAt(0, t, 1), uvAt(0, t, 2), mat);
            } else {
                std::vector<std::array<Vec2, 3>> layers;
                layers.reserve(nLayers);
                for (py::ssize_t l = 0; l < nLayers; ++l)
                    layers.push_back({ uvAt(l, t, 0), uvAt(l, t, 1), uvAt(l, t, 2) });
                tri = std::make_shared<Triangle>(p0, p1, p2, layers, names, mat);
            }
            if (hasNormals) {
                const float* n = nPtr + (t * 9);
                tri->setVertexNormals(Vec3(n[0], n[1], n[2]),
                                      Vec3(n[3], n[4], n[5]),
                                      Vec3(n[6], n[7], n[8]));
            }
            tri->setObjectPassIndex(objectPassIndex);
            tri->setMaterialPassIndex(mpi(t));
            // pkg88-C.0: attach motion data. motionSteps=2 means buffer has center+end.
            tri->setMotionData(motionBase + t * 3, 2);
            renderer.addObject(tri);
        }
    }

    void addMesh(const std::string& filename, int materialId, const std::vector<float>& position = {0,0,0},
                const std::vector<float>& scale = {1,1,1}, float rotationY = 0, bool smoothNormals = false) {
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        auto mesh = std::make_shared<Mesh>(mat);
        if (mesh->loadOBJ(filename, smoothNormals)) {
            std::shared_ptr<Hittable> obj = mesh;
            if (scale[0] != 1 || scale[1] != 1 || scale[2] != 1)
                obj = std::make_shared<Scale>(obj, Vec3(scale[0], scale[1], scale[2]));
            if (rotationY != 0) obj = std::make_shared<RotateY>(obj, rotationY);
            if (position[0] != 0 || position[1] != 0 || position[2] != 0)
                obj = std::make_shared<Translate>(obj, Vec3(position[0], position[1], position[2]));
            renderer.addObject(obj);
        }
    }

    void addBlackHole(const std::vector<float>& position, float mass_solar,
                     float influence_radius, py::dict params) {
        double disk_outer = params.contains("disk_outer")
            ? params["disk_outer"].cast<double>() : 30.0;
        double mdot = params.contains("accretion_rate")
            ? params["accretion_rate"].cast<double>() : 1.0;
        double incl = params.contains("inclination")
            ? params["inclination"].cast<double>() : 75.0;
        // pkg107: world-to-GR scale factor. Default 100.0 matches pkg40-pkg44
        // baselines. Smaller values produce a larger visible shadow.
        double r_obs_M = params.contains("r_obs_M")
            ? params["r_obs_M"].cast<double>() : 100.0;

        // pkg43: accretion model selector. Default to NOVIKOV_THORNE for backward compatibility.
        std::string accretion_model = params.contains("accretion_model")
            ? params["accretion_model"].cast<std::string>() : "NOVIKOV_THORNE";

        auto bh = std::make_shared<BlackHole>(
            Vec3(position[0], position[1], position[2]),
            double(mass_solar), double(influence_radius),
            disk_outer, mdot, incl, r_obs_M);

        // pkg43: Add slim disk emission if selected
        if (accretion_model == "SLIM_DISK") {
            astroray::ParamDict slim_params;
            slim_params.set("mass", static_cast<float>(mass_solar));
            slim_params.set("mdot", static_cast<float>(mdot));
            slim_params.set("r_outer", static_cast<float>(disk_outer));

            // Slim disk specific parameters with defaults
            if (params.contains("slim_disk_spin")) {
                slim_params.set("spin", params["slim_disk_spin"].cast<float>());
            } else {
                slim_params.set("spin", 0.0f);
            }
            if (params.contains("slim_disk_r_inner")) {
                slim_params.set("r_inner", params["slim_disk_r_inner"].cast<float>());
            } else {
                slim_params.set("r_inner", 0.0f); // 0 = use ISCO
            }
            if (params.contains("slim_disk_intensity_scale")) {
                slim_params.set("intensity_scale", params["slim_disk_intensity_scale"].cast<float>());
            } else {
                slim_params.set("intensity_scale", 1.0f);
            }
            if (params.contains("slim_disk_base_density")) {
                slim_params.set("base_density", params["slim_disk_base_density"].cast<float>());
            } else {
                slim_params.set("base_density", 1.0e3f);
            }

            auto slim_disk = astroray::EmissionRegistry::instance().create("slim_disk", slim_params);
            bh->addVolumetricEmission(slim_disk);
        }
        // For NOVIKOV_THORNE, the BlackHole constructor already creates the disk

        // pkg44: Add ADAF emission if selected. The scene uses adaf_-prefixed
        // keys (same convention as slim_disk_ above) to avoid collision with
        // generic BH params; ADAFPlugin reads un-prefixed keys, so map them
        // explicitly. mass comes from the BlackHole mass argument.
        bool enableAdaf = params.contains("enable_adaf")
            ? params["enable_adaf"].cast<bool>() : false;
        if (enableAdaf) {
            astroray::ParamDict adaf_params;
            adaf_params.set("mass", static_cast<float>(mass_solar));
            if (params.contains("adaf_mdot_edd"))
                adaf_params.set("mdot_edd", params["adaf_mdot_edd"].cast<float>());
            if (params.contains("adaf_electron_temp"))
                adaf_params.set("electron_temp", params["adaf_electron_temp"].cast<float>());
            if (params.contains("adaf_beta_mag"))
                adaf_params.set("beta_mag", params["adaf_beta_mag"].cast<float>());
            if (params.contains("adaf_r_inner"))
                adaf_params.set("r_inner", params["adaf_r_inner"].cast<float>());
            if (params.contains("adaf_r_outer"))
                adaf_params.set("r_outer", params["adaf_r_outer"].cast<float>());
            if (params.contains("adaf_flattening"))
                adaf_params.set("flattening", params["adaf_flattening"].cast<float>());
            if (params.contains("adaf_alpha"))
                adaf_params.set("alpha", params["adaf_alpha"].cast<float>());
            if (params.contains("adaf_s"))
                adaf_params.set("s", params["adaf_s"].cast<float>());
            if (params.contains("adaf_intensity_scale"))
                adaf_params.set("intensity_scale", params["adaf_intensity_scale"].cast<float>());
            auto adaf = astroray::EmissionRegistry::instance().create("adaf", adaf_params);
            bh->addVolumetricEmission(adaf);
        }

        bool enableJet = params.contains("enable_jet")
            ? params["enable_jet"].cast<bool>() : false;
        if (enableJet) {
            astroray::ParamDict jp = paramDictFromPyDict(params);
            if (!params.contains("r_base")) {
                jp.set("r_base", static_cast<float>(6.0));
            }
            auto jet = astroray::EmissionRegistry::instance().create("synchrotron_jet", jp);
            bh->addVolumetricEmission(jet);
        }
        renderer.addObject(bh);
    }

    void addVolume(const std::vector<float>& center, float radius, float density,
                  const std::vector<float>& color, float anisotropy = 0,
                  float emissionStrength = 0.0f,
                  const std::vector<float>& emissionColor = {1.0f, 1.0f, 1.0f}) {
        auto boundary = std::make_shared<Sphere>(Vec3(center[0], center[1], center[2]), radius,
            std::make_shared<Lambertian>(Vec3(1)));
        renderer.addObject(std::make_shared<ConstantMedium>(boundary, density,
            Vec3(color[0], color[1], color[2]), anisotropy));
        if (emissionStrength > 0.0f && emissionColor.size() >= 3) {
            astroray::ParamDict gp;
            gp.set("albedo", Vec3(emissionColor[0], emissionColor[1], emissionColor[2]));
            gp.set("intensity", emissionStrength);
            auto glow = astroray::MaterialRegistry::instance().create("light", gp);
            // Keep the emissive proxy slightly inside the volume boundary to avoid
            // exact overlap with the medium shell intersection points.
            renderer.addObject(std::make_shared<Sphere>(
                Vec3(center[0], center[1], center[2]), radius * 0.98f, glow));
        }
    }

    void setupCamera(const std::vector<float>& lookFrom, const std::vector<float>& lookAt,
                    const std::vector<float>& vup, float vfov, float aspectRatio,
                    float aperture, float focusDist, int width, int height,
                    float shiftX = 0.0f, float shiftY = 0.0f) {
        auto oldCamera = camera;
        camera = std::make_shared<Camera>(
            Vec3(lookFrom[0], lookFrom[1], lookFrom[2]),
            Vec3(lookAt[0], lookAt[1], lookAt[2]),
            Vec3(vup[0], vup[1], vup[2]),
            vfov, aspectRatio, aperture, focusDist, width, height, shiftX, shiftY);
        // pkg72: Blender re-uploads the camera every viewport frame via
        // setup_camera; carry the previous-frame projection snapshot across
        // so motion vectors are non-zero on the second and later frames.
        if (oldCamera && oldCamera->hasPrevCamera &&
            oldCamera->width == camera->width && oldCamera->height == camera->height) {
            camera->prevOrigin    = oldCamera->prevOrigin;
            camera->prevU         = oldCamera->prevU;
            camera->prevV         = oldCamera->prevV;
            camera->prevW         = oldCamera->prevW;
            camera->prevVw        = oldCamera->prevVw;
            camera->prevVh        = oldCamera->prevVh;
            camera->prevFocusDist = oldCamera->prevFocusDist;
            camera->prevShiftX    = oldCamera->prevShiftX;
            camera->prevShiftY    = oldCamera->prevShiftY;
            camera->hasPrevCamera = true;
        }
    }

    // pkg88-A: programmatically set camera motion blur keyframes (T/R/S decomposed).
    // Called by test scenes or the Blender addon after decomposing camera matrices.
    void setCameraMotionBlur(const std::vector<float>& startT, const std::vector<float>& startR,
                             const std::vector<float>& startS, const std::vector<float>& endT,
                             const std::vector<float>& endR, const std::vector<float>& endS,
                             float shutter, int shutterPosition) {
        if (!camera) throw std::runtime_error("Camera not set up");
        if (startT.size() != 3 || endT.size() != 3)
            throw std::runtime_error("Translation vectors must be length 3");
        if (startR.size() != 4 || endR.size() != 4)
            throw std::runtime_error("Rotation quaternions must be length 4 (w,x,y,z)");
        if (startS.size() != 3 || endS.size() != 3)
            throw std::runtime_error("Scale vectors must be length 3");

        camera->shutterStartT = Vec3(startT[0], startT[1], startT[2]);
        camera->shutterEndT   = Vec3(endT[0], endT[1], endT[2]);
        camera->shutterStartR = Quaternion(startR[0], startR[1], startR[2], startR[3]);
        camera->shutterEndR   = Quaternion(endR[0], endR[1], endR[2], endR[3]);
        camera->shutterStartS = Vec3(startS[0], startS[1], startS[2]);
        camera->shutterEndS   = Vec3(endS[0], endS[1], endS[2]);
        camera->shutter = shutter;
        camera->shutterPosition = static_cast<Camera::ShutterPosition>(shutterPosition);
    }

    void setAdaptiveSampling(bool enable) {
        useAdaptiveSampling = enable;             // CPU render() path (arg)
        renderer.setUseAdaptiveSampling(enable);  // pkg131: GPU wavefront reads this
    }

    void setUseGPU(bool enable) {
#ifdef ASTRORAY_CUDA_ENABLED
        if (enable) {
            if (!cudaRenderer) cudaRenderer = std::make_unique<CUDARenderer>();
            if (!cudaRenderer->isAvailable()) {
                cudaRenderer.reset();
                throw std::runtime_error("No CUDA GPU available");
            }
            useGPU = true;
        } else {
            useGPU = false;
        }
#else
        if (enable) throw std::runtime_error("CUDA support not compiled");
#endif
    }

    py::dict getMaterialBackendCapabilities(int materialId) const {
        auto it = materials.find(materialId);
        if (it == materials.end() || !it->second) {
            throw std::runtime_error("Unknown material id");
        }
        MaterialBackendCapabilities caps = it->second->backendCapabilities();
        py::dict out;
        out["cpu"] = caps.cpu;
        out["spectral"] = caps.spectral;
        out["gpu"] = caps.gpu;
        out["gpu_spectral"] = caps.gpuSpectral;
        out["gpu_approximate"] = caps.gpuApproximate;
        out["closure_graph"] = caps.closureGraph;
        out["closure_count"] = it->second->closureGraph().count();
        out["gpu_type"] = caps.gpuType;
        out["notes"] = caps.notes;
        return out;
    }

    py::list getMaterialClosureGraph(int materialId) const {
        auto it = materials.find(materialId);
        if (it == materials.end() || !it->second) {
            throw std::runtime_error("Unknown material id");
        }

        py::list out;
        astroray::MaterialClosureGraph graph = it->second->closureGraph();
        for (int i = 0; i < graph.count(); ++i) {
            const astroray::MaterialClosure& c = graph.closure(i);
            py::dict item;
            item["type"] = astroray::closureTypeName(c.type);
            item["color"] = py::make_tuple(c.color.x, c.color.y, c.color.z);
            item["weight"] = c.weight;
            item["roughness"] = c.roughness;
            item["metallic"] = c.metallic;
            item["ior"] = c.ior;
            item["transmission"] = c.transmission;
            item["clearcoat_gloss"] = c.clearcoatGloss;
            item["two_sided_emission"] = c.twoSidedEmission;
            out.append(item);
        }
        return out;
    }

    bool getGPUAvailable() const {
#ifdef ASTRORAY_CUDA_ENABLED
        CUDARenderer test;
        return test.isAvailable();
#else
        return false;
#endif
    }

    std::string getGPUDeviceName() const {
#ifdef ASTRORAY_CUDA_ENABLED
        CUDARenderer test;
        return test.isAvailable() ? test.deviceName() : "none";
#else
        return "CUDA not compiled";
#endif
    }

    float gpuProfileLookup(int profileIndex, float lambda) {
#ifdef ASTRORAY_CUDA_ENABLED
        if (!cudaRenderer) cudaRenderer = std::make_unique<CUDARenderer>();
        if (!cudaRenderer->isAvailable()) {
            throw std::runtime_error("No CUDA GPU available");
        }
        return cudaRenderer->lookupProfileReflectance(profileIndex, lambda);
#else
        (void)profileIndex;
        (void)lambda;
        throw std::runtime_error("CUDA support not compiled");
#endif
    }

    // pkg168: batch device RGB→spectral upsampling probe for the CPU↔GPU
    // parity A/B (tests/test_pkg168_upsampling_parity.py). `rgbs` is flat
    // 3*nRgb, `lambdas` is nLambda; returns nRgb*nLambda floats, rgb-major.
    // mode is a GSpectralMode (1=ALBEDO, 2=ILLUMINANT).
    std::vector<float> gpuRgbUpsampleBatch(const std::vector<float>& rgbs,
                                           const std::vector<float>& lambdas,
                                           int mode) {
#ifdef ASTRORAY_CUDA_ENABLED
        if (!cudaRenderer) cudaRenderer = std::make_unique<CUDARenderer>();
        if (!cudaRenderer->isAvailable()) {
            throw std::runtime_error("No CUDA GPU available");
        }
        return cudaRenderer->rgbUpsampleBatch(rgbs, lambdas, mode);
#else
        (void)rgbs;
        (void)lambdas;
        (void)mode;
        throw std::runtime_error("CUDA support not compiled");
#endif
    }

    // pkg63: extended for full Blender Mapping node parity (XYZ Euler rotation,
    // multiplicative Background Color tint). Backward-compatible — direct callers
    // that pass (path, strength, 0.0) just get rx=0 (identity matrix).
    bool loadEnvironmentMap(const std::string& path, float strength = 1.0f,
                            float rx = 0.0f, float ry = 0.0f, float rz = 0.0f,
                            float tr = 1.0f, float tg = 1.0f, float tb = 1.0f,
                            bool blender_convention = false) {
        envMap = std::make_shared<EnvironmentMap>();
        if (envMap->load(path, strength, rx, ry, rz, tr, tg, tb, blender_convention)) {
            renderer.setEnvironmentMap(envMap);
            return true;
        }
        envMap.reset();
        return false;
    }

    // Returns [s0,s1,s2,s3] from the spectral atlas for direction dir and wavelength
    // stratum u in [0,1). Used by tests to validate evalSpectral parity.
    std::vector<float> evalEnvSpectral(const std::vector<float>& dir, float u) const {
        if (!envMap || !envMap->loaded()) return {0,0,0,0};
        Vec3 d(dir[0], dir[1], dir[2]);
        astroray::SampledWavelengths wls = astroray::SampledWavelengths::sampleUniform(u);
        astroray::SampledSpectrum s = envMap->evalSpectral(d, wls);
        return {s[0], s[1], s[2], s[3]};
    }

    // Reference fallback: RGB lookup then RGBIlluminantSpectrum upsample.
    // Mirrors the pkg11-style path that evalSpectral replaces.
    std::vector<float> evalEnvRGBUpsample(const std::vector<float>& dir, float u) const {
        if (!envMap || !envMap->loaded()) return {0,0,0,0};
        Vec3 d(dir[0], dir[1], dir[2]);
        Vec3 c = envMap->lookup(d);
        astroray::SampledWavelengths wls = astroray::SampledWavelengths::sampleUniform(u);
        astroray::SampledSpectrum s =
            astroray::RGBIlluminantSpectrum({c.x, c.y, c.z}).sample(wls);
        return {s[0], s[1], s[2], s[3]};
    }

    void setBackgroundColor(const std::vector<float>& color) {
        renderer.setBackgroundColor(Vec3(color[0], color[1], color[2]));
    }

    void setFilmExposure(float exposure) {
        renderer.setFilmExposure(exposure);
    }

    void setClampDirect(float value) {
        renderer.setClampDirect(value);
    }

    void setClampIndirect(float value) {
        renderer.setClampIndirect(value);
    }

    void setFilterGlossy(float value) {
        renderer.setFilterGlossy(value);
    }

    void setSeed(int seed) {
        renderer.setSeed(seed);
    }

    void setPixelFilter(int filterType, float filterWidth) {
        renderer.setPixelFilter(filterType, filterWidth);
    }

    void setLightSampler(const std::string& mode) {
        if (mode == "power") {
            renderer.setLightSampler(LightList::SamplerMode::Power);
        } else if (mode == "tree") {
            renderer.setLightSampler(LightList::SamplerMode::Tree);
        } else {
            throw std::invalid_argument("Unknown light sampler mode: " + mode + " (valid: 'power', 'tree')");
        }
    }

    // pkg86-B: CPU-side batch light-tree pick probe. points/normals are
    // flattened xyz triples; us are the per-query traversal randoms. Returns
    // (light_indices, pdfs); index -2 marks a dedicated-light pick.
    std::pair<std::vector<int>, std::vector<float>> debugLightTreePick(
            const std::vector<float>& points,
            const std::vector<float>& normals,
            const std::vector<float>& us) {
        size_t n = us.size();
        std::vector<int> idx(n, -1);
        std::vector<float> pdf(n, 0.f);
        const astroray::LightTree* tree = renderer.getLights().lightTree();
        if (tree == nullptr || tree->empty()) return {idx, pdf};
        std::mt19937 gen(0);  // unused by pick() — u drives the traversal
        for (size_t i = 0; i < n; ++i) {
            Vec3 P(points[i*3], points[i*3+1], points[i*3+2]);
            Vec3 N(normals[i*3], normals[i*3+1], normals[i*3+2]);
            astroray::LightTree::PickResult r = tree->pick(P, N, us[i], gen);
            idx[i] = r.isDedicated ? -2 : r.lightIndex;
            pdf[i] = r.pdf;
        }
        return {idx, pdf};
    }

    // pkg86-B: GPU twin of debugLightTreePick — runs the production
    // gpu_light_tree_pick on the resident device tree. Requires
    // set_use_gpu(True) + set_light_sampler('tree') + upload_scene().
    std::pair<std::vector<int>, std::vector<float>> debugLightTreePickGpu(
            const std::vector<float>& points,
            const std::vector<float>& normals,
            const std::vector<float>& us) {
#ifdef ASTRORAY_CUDA_ENABLED
        if (!cudaRenderer)
            throw std::runtime_error(
                "debug_light_tree_pick_gpu: call upload_scene (with set_use_gpu) first");
        size_t n = us.size();
        std::vector<Vec3> P(n), N(n);
        for (size_t i = 0; i < n; ++i) {
            P[i] = Vec3(points[i*3], points[i*3+1], points[i*3+2]);
            N[i] = Vec3(normals[i*3], normals[i*3+1], normals[i*3+2]);
        }
        std::vector<int> idx;
        std::vector<float> pdf;
        if (!cudaRenderer->debugLightTreePick(P, N, us, idx, pdf))
            throw std::runtime_error(
                "debug_light_tree_pick_gpu: no light tree resident "
                "(set_light_sampler('tree') + upload_scene required)");
        return {idx, pdf};
#else
        (void)points; (void)normals; (void)us;
        throw std::runtime_error("CUDA not enabled in this build");
#endif
    }

    // pkg86-B: wall-clock ms of the most recent GPU light-tree upload.
    float getLightTreeUploadMs() const {
#ifdef ASTRORAY_CUDA_ENABLED
        return cudaRenderer ? cudaRenderer->lightTreeUploadMs() : 0.f;
#else
        return 0.f;
#endif
    }

    void setWorldMaxBounces(int maxB) {
        renderer.setWorldMaxBounces(maxB);
    }

    void setWorldVolume(float density, const std::vector<float>& color,
                        float anisotropy = 0.0f, float scatter = 0.0f) {
        renderer.setWorldVolume(density, Vec3(color[0], color[1], color[2]), anisotropy, scatter);
    }

    void setUseReflectiveCaustics(bool use) {
        renderer.setUseReflectiveCaustics(use);
    }

    void setUseRefractiveCaustics(bool use) {
        renderer.setUseRefractiveCaustics(use);
    }
    void setUsePhotonCaustics(bool use) {  // pkg113 Phase-3: opt-in GPU photon-map caustics
        renderer.setUsePhotonCaustics(use);
    }
    void setUseProgressiveSampler(bool use) {  // pkg224: opt-in GPU progressive (Sobol') sampler
        renderer.setUseProgressiveSampler(use);
    }

    // pkg64 Phase 3 — per-object opt-in for SMS connection attempts in
    // the default path_tracer. `objectId` is the addObject call order
    // (same as Renderer::getScene() index).
    //
    // pkg64-gpu Phase 1: this mutates CPU Hittable state only. No GPU
    // "scene dirty" mark is needed — render() (and upload_scene())
    // re-run cudaRenderer->uploadScene() unconditionally every frame,
    // and scene_upload.cu re-reads sph->isCausticCaster() fresh on each
    // upload, so the flag crosses the CPU→GPU boundary on the next
    // render with no extra plumbing. (When pkg56 Phase C replaces the
    // unconditional upload with depsgraph-selective dispatch, this flag
    // must be added to the per-object dirty set — tracked in the
    // pkg64-gpu spec follow-ups, out of scope for Phase 1.)
    bool setObjectCausticCaster(int objectId, bool enabled) {
        return renderer.setObjectCausticCaster(objectId, enabled);
    }

    int getCausticCasterCount() const {
        return renderer.getCausticCasterCount();
    }

    int getSceneObjectCount() const {
        return renderer.getSceneObjectCount();
    }

    // pkg87c — Cryptomatte name setters
    // pkg87d — register names in manifest registry
    bool setObjectName(int objectId, const std::string& name) {
        bool ok = renderer.setObjectName(objectId, name);
        if (ok) {
            crypto_name_registry::instance().add_object(name);
        }
        return ok;
    }

    void setMaterialName(int materialId, const std::string& name) {
        if (materials.count(materialId)) {
            materials[materialId]->setName(name);
            crypto_name_registry::instance().add_material(name);
        }
    }

    void setCryptomatteEnabled(bool enabled) {
        renderer.setCryptomatteEnabled(enabled);
    }

    // pkg197: toggle GPU wavefront first-hit denoise-guide AOV capture.
    void setGpuGuideAOVs(bool enabled) {
        renderer.setGpuGuideAOVs(enabled);
    }
    bool getGpuGuideAOVs() const {
        return renderer.getGpuGuideAOVs();
    }
    // pkg198 Stage 2: opt-in GPU light-path render passes.
    void setGpuLightPathPasses(bool enabled) {
        renderer.setGpuLightPathPasses(enabled);
    }
    bool getGpuLightPathPasses() const {
        return renderer.getGpuLightPathPasses();
    }

    void setCryptomatteDepth(int depth) {
        if (camera) {
            camera->cryptomatteDepth = depth;
        }
    }

    void setUseTransparentFilm(bool use) {
        renderer.setUseTransparentFilm(use);
    }

    void setTransparentGlass(bool use) {
        renderer.setTransparentGlass(use);
    }

    void addPass(const std::string& passName) {
        astroray::ParamDict p;
        renderer.addPass(astroray::PassRegistry::instance().create(passName, p));
    }

    void clearPasses() {
        renderer.clearPasses();
    }

    py::array_t<float> render(int samplesPerPixel, int maxDepth, py::object progressCallback = py::none(), bool applyGamma = true,
                              int diffuseBounces = -1, int glossyBounces = -1, int transmissionBounces = -1,
                              int volumeBounces = -1, int transparentBounces = -1,
                              bool skipUpload = false) {
        if (!camera) throw std::runtime_error("Camera not set up");

#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            // pkg171: a CPU-only integrator (no GPU kernel) would otherwise fall
            // through to the generic wavefront route below, which renders it as if
            // it were a plain path tracer — silently producing a NEAR-BLACK frame
            // (#540 HW verification: light_tracer_caustic peak 0.019 vs CPU 0.500).
            // Fail LOUDLY here instead of shipping a black render. The CPU-only set
            // is enumerated by capabilities().gpuSupported == false — the same
            // source integrator_capabilities() and the addon's configure_backend
            // read — so no integrator name is hardcoded. This is the raw-binding
            // backstop; the Blender addon already guards this at the Python layer
            // (configure_backend: error on device_mode='gpu', CPU fallback on
            // 'auto'), but direct PyRenderer callers (test scripts, HW verifiers)
            // bypass it.
            if (!integratorName_.empty()) {
                auto probe = astroray::IntegratorRegistry::instance().create(
                    integratorName_, integratorParams_);
                const IntegratorCapabilities caps = probe->capabilities();
                if (!caps.gpuSupported) {
                    throw std::runtime_error(
                        "Astroray: integrator '" + integratorName_ +
                        "' has no GPU implementation (" + caps.gpuFallbackReason +
                        ") and would render silently near-black on GPU. Render this "
                        "integrator on CPU (set_use_gpu(false) / device_mode='cpu').");
                }
            }
            // GPU path: build BVH on CPU (needed for upload), then render on GPU.
            // pkg114 inc 3d: skipUpload renders from existing device state, so the
            // CPU BVH rebuild is unnecessary too (geometry is unchanged).
            if (!skipUpload)
                renderer.buildAcceleration();
#ifdef ASTRORAY_WAVEFRONT_CUDA_N3
            // pkg55-C7 (megakernel removal): EVERY GPU integrator routes to
            // the wavefront pipeline (path regeneration + material-bucketed
            // shade + dedicated shadow stage, Laine 2013 / Cycles X). The
            // wavefront does its OWN buildSceneArrays + upload into its
            // persistent context; the megakernel uploadScene is no longer
            // part of the render path (upload_scene stays available for the
            // probe/refit surfaces).
            //
            // pkg64-gpu Phase 1 probe hook (moved here from the deleted
            // CUDARenderer::render): when ASTRORAY_PKG64_GPU_SMS_PROBE is
            // set, run the SMS device probe instead of rendering.
            // pkg191: mirror the CPU Renderer::render seed contract
            // (include/raytracer.h:3028-3030 + the renderSeed doc at :2102):
            // renderSeed==0 means "non-deterministic" — draw a FRESH seed per
            // render() call. The GPU dispatch previously passed the fixed
            // renderer.getSeed() (==0 for the Blender viewport renderer) verbatim
            // to the wavefront, whose RNG is WavefrontRNG(pixel, sample_idx, seed)
            // (src/gpu/wavefront/stage_init.cu:189). With a fixed seed AND the same
            // local sample range every call, each viewport chunk reproduced
            // IDENTICAL noise, so the addon's Python running-mean accumulator
            // (blender_addon/exporter.py:585-597) averaged duplicates and the
            // GPU viewport stayed frozen at the 1-sample noise while the CPU
            // viewport (which already honours this contract) refined. A non-zero
            // pin stays deterministic (final render / parity + golden tests).
            const uint64_t effectiveSeed =
                (renderer.getSeed() == 0)
                    ? static_cast<uint64_t>(std::random_device{}())
                    : static_cast<uint64_t>(renderer.getSeed());
            // pkg201 Stage 3 (Finding A) — the GPU branch does NOT call
            // Renderer::render(), so store the per-type bounce limits on the
            // renderer here; cuda_wavefront_render reads them
            // (getMaxDiffuse/Glossy/TransmissionBounces) and publishes the
            // shade-kernel __constant__. -1 (the default) = unlimited.
            renderer.setPerTypeBounces(diffuseBounces, glossyBounces, transmissionBounces);
            bool smsProbeRan = false;
            {
                const char* probe_env = std::getenv("ASTRORAY_PKG64_GPU_SMS_PROBE");
                if (probe_env && probe_env[0] && std::strcmp(probe_env, "0") != 0) {
                    cudaRenderer->uploadScene(renderer, *camera);
                    cudaRenderer->runSmsProbe();
                    smsProbeRan = true;  // probe replaced the render; the test
                                         // parses stderr, the image is unused
                }
            }
            if (smsProbeRan) {
                // fall through to pixel packaging with untouched pixels.
            } else
            // pkg55-C6b / pkg24: GPU ReSTIR-DI wavefront. The reservoir stages
            // (RIS -> temporal -> spatial -> resolve) run at the primary hit; the
            // per-pixel reservoirs are double-buffered + persisted across frames
            // in the wavefront's WfContext so temporal reuse reads the previous
            // frame. use_temporal/use_spatial/spatial_* come from the same
            // ParamDict the CPU restir_di integrator reads.
            if (integratorName_ == "restir-di") {
                int  numCandidates    = integratorParams_.getInt("num_candidates",   4);
                int  mCap             = integratorParams_.getInt("m_cap",             0);
                bool useTemporal      = integratorParams_.getInt("use_temporal",      0) != 0;
                bool useSpatial       = integratorParams_.getInt("use_spatial",       0) != 0;
                int  spatialRadius    = integratorParams_.getInt("spatial_radius",    5);
                int  spatialNeighbors = integratorParams_.getInt("spatial_neighbors", 5);
                auto rgb = astroray::wavefront::cuda_wavefront_render_restir(
                    renderer, *camera, camera->width, camera->height,
                    samplesPerPixel, maxDepth, effectiveSeed,
                    numCandidates, mCap, useTemporal, useSpatial,
                    spatialRadius, spatialNeighbors, restirSessionId_);
                for (size_t i = 0; i < camera->pixels.size(); ++i) {
                    camera->pixels[i] = Vec3(rgb[i * 3 + 0],
                                             rgb[i * 3 + 1],
                                             rgb[i * 3 + 2]);
                }
            } else {
                // pkg55-C7: unified wavefront route for every other GPU
                // integrator name. `path_tracer` mirrors the CPU
                // pathTraceSpectral (NEE + MIS); `multiwavelength_path_tracer`
                // mirrors the naive no-NEE MultiwavelengthPathTracer;
                // `wavefront_path_tracer` keeps its pkg55-B' semantics
                // (identical to path_tracer). Any legacy name that used to
                // hit the RGB megakernel gets the same spectral transport
                // (the RGB kernel was deleted in C7; its lossy RGB env
                // sampling was already superseded per pkg85-D).
                // pkg55-C3: resolve spectral params (visible-band spectral is
                // the default; non-visible bands need lambda_min/max +
                // output_mode).
                float lmin = integratorParams_.getFloat("lambda_min", 380.0f);
                float lmax = integratorParams_.getFloat("lambda_max", 780.0f);
                std::string mode = integratorParams_.getString("output_mode", "");
                bool useLum;
                if (mode.empty())
                    useLum = !(lmin >= 379.5f && lmax <= 780.5f);
                else
                    useLum = (mode == "luminance");
                bool enableNEE = (integratorName_ != "multiwavelength_path_tracer");
                // pkg159: restore GPU cryptomatte (dropped with the megakernels
                // in pkg55-C7). The driver writes the Camera's rank buffers
                // directly — sorted + normalised — so get_cryptomatte_*_buffer
                // and write_cryptomatte_exr see the same shape the CPU leg
                // produces. Only wired when the buffers are actually sized for
                // the current depth; set_cryptomatte_depth does not resize them
                // (pre-existing: Camera sizes them at construction with the
                // default depth 6), and writing past them would corrupt the heap.
                float* cryptoObjOut = nullptr;
                float* cryptoMatOut = nullptr;
                int cryptoDepth = 0;
                if (renderer.getCryptomatteEnabled()) {
                    const size_t need = static_cast<size_t>(camera->width) *
                                        camera->height * camera->cryptomatteDepth * 2;
                    if (camera->cryptoObjectBuffer.size() == need &&
                        camera->cryptoMaterialBuffer.size() == need) {
                        cryptoObjOut = camera->cryptoObjectBuffer.data();
                        cryptoMatOut = camera->cryptoMaterialBuffer.data();
                        cryptoDepth  = camera->cryptomatteDepth;
                    }
                }
                // pkg197: first-hit denoise-guide AOVs. On the GPU backend these
                // Camera buffers stayed zero-filled (CPU fills them in its render
                // loop; the wavefront returned only beauty), so the OIDN/OptiX
                // denoiser ran guide-less and the addon Albedo/Normal/Depth AOVs
                // + Blender Denoising Data passes were black. The wavefront now
                // captures them at the bounce-0 first hit (mirrors the cryptomatte
                // out-param plumbing). Vec3 is 3 contiguous floats, so the Camera
                // buffers alias the H*W*3 / H*W float layouts the driver writes.
                // Gated on setGpuGuideAOVs (default on): null out-params leave the
                // buffers zero (the pre-pkg197 guide-less state — used as the
                // denoise A/B control and as a viewport copy-back lever).
                float* albedoOut = nullptr;
                float* normalOut = nullptr;
                float* depthOut  = nullptr;
                if (renderer.getGpuGuideAOVs()) {
                    albedoOut = reinterpret_cast<float*>(camera->albedoBuffer.data());
                    normalOut = reinterpret_cast<float*>(camera->normalBuffer.data());
                    depthOut  = camera->depthBuffer.data();
                }
                // pkg198 Stage 2: light-path render passes. Opt-in
                // (setGpuLightPathPasses). Staging buffer is pass-major
                // [p*numPixels*3 + pixel*3 + c] linear sRGB; copied into
                // camera->renderPassBuffers so get_render_pass_buffer(name) returns
                // the GPU passes exactly like the CPU route (Renderer::render fills
                // renderPassBuffers directly). Null out-param leaves the wavefront on
                // its byte-identical fleet path.
                static_assert(ASTRORAY_LP_NUM_PASSES == PASS_ENVIRONMENT + 1,
                    "light-path pass count must cover PASS_DIFFUSE_DIRECT..PASS_ENVIRONMENT");
                const size_t numPixels = camera->pixels.size();
                std::vector<float> passesStaging;
                float* passesOut = nullptr;
                if (renderer.getGpuLightPathPasses()) {
                    passesStaging.assign(
                        size_t(ASTRORAY_LP_NUM_PASSES) * numPixels * 3, 0.0f);
                    passesOut = passesStaging.data();
                }
                // pkg201 Stage 2 (Finding F): give the driver the Camera alpha
                // buffer so GPU renders honour transparent film. The driver fills it
                // with per-pixel coverage when useTransparentFilm is set, else 1.0
                // (opaque) — matching the CPU default alphaBuffer (resized to 1.0).
                // alphaBuffer is width*height floats.
                float* alphaOut = camera->alphaBuffer.data();
                auto rgb = astroray::wavefront::cuda_wavefront_render(
                    renderer, *camera, camera->width, camera->height,
                    samplesPerPixel, maxDepth, effectiveSeed,
                    lmin, lmax, useLum, enableNEE,
                    cryptoObjOut, cryptoMatOut, cryptoDepth,  // pkg159
                    albedoOut, normalOut, depthOut,           // pkg197
                    passesOut,                                 // pkg198
                    alphaOut);                                 // pkg201
                // camera->pixels is std::vector<Vec3>; rgb is H*W*3 floats.
                for (size_t i = 0; i < camera->pixels.size(); ++i) {
                    camera->pixels[i] = Vec3(rgb[i * 3 + 0],
                                             rgb[i * 3 + 1],
                                             rgb[i * 3 + 2]);
                }
                // pkg198 Stage 2: scatter the staged light-path passes into the
                // Camera pass buffers (the CPU route fills these in Renderer::render).
                if (passesOut != nullptr) {
                    for (int p = 0; p < ASTRORAY_LP_NUM_PASSES; ++p) {
                        std::vector<Vec3>& pb = camera->renderPassBuffers[p];
                        if (pb.size() != numPixels) continue;
                        const float* src = passesOut + size_t(p) * numPixels * 3;
                        for (size_t i = 0; i < numPixels; ++i) {
                            pb[i] = Vec3(src[i * 3 + 0], src[i * 3 + 1], src[i * 3 + 2]);
                        }
                    }
                }
            }
            // pkg197: run the registered pass pipeline on the GPU-rendered frame,
            // mirroring what Renderer::render() does for the CPU path. Without
            // this the addon's use_denoising (which add_pass()es the OIDN/OptiX
            // denoiser) and the cryptomatte pass never executed on GPU renders —
            // so the first-hit guide AOVs captured above had no denoiser consumer
            // on the default backend. No-op when no pass was added (the guard
            // inside applyPasses), so plain GPU renders stay byte-identical. The
            // GPU cryptomatte copy-back already sorts+normalises the rank buffers;
            // re-running the CryptomattePass over them is idempotent (see the
            // copy-back note in gpu_wavefront_snapshot.cu).
            renderer.applyPasses(*camera);
#else
            // pkg55-C7: the megakernels are deleted; a CUDA build without the
            // wavefront has no GPU render path.
            throw std::runtime_error(
                "GPU rendering requires the wavefront build "
                "(ASTRORAY_WAVEFRONT_CUDA_N3=ON)");
#endif
        } else
#endif
        {
            // CPU path (unchanged)
            std::function<void(float)> callback = nullptr;
            if (!progressCallback.is_none()) {
                callback = [&progressCallback](float progress) {
                    py::gil_scoped_acquire acquire;
                    progressCallback(progress);
                };
            }
            renderer.render(*camera, samplesPerPixel, maxDepth, callback, useAdaptiveSampling, false,
                            diffuseBounces, glossyBounces, transmissionBounces, volumeBounces, transparentBounces);
        }

        // Package pixels into numpy array (height, width, 3)
        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height),
                                 static_cast<py::ssize_t>(camera->width), 3};
        auto result = py::array_t<float>(shape);
        {
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = camera->pixels.size();
            for (size_t i = 0; i < size; i++) {
                const Vec3& c = camera->pixels[i];
                if (applyGamma) {
                    ptr[i*3]   = std::pow(std::clamp(c.x, 0.0f, 1.0f), 1.0f / 2.2f);
                    ptr[i*3+1] = std::pow(std::clamp(c.y, 0.0f, 1.0f), 1.0f / 2.2f);
                    ptr[i*3+2] = std::pow(std::clamp(c.z, 0.0f, 1.0f), 1.0f / 2.2f);
                } else {
                    ptr[i*3]   = std::max(c.x, 0.0f);
                    ptr[i*3+1] = std::max(c.y, 0.0f);
                    ptr[i*3+2] = std::max(c.z, 0.0f);
                }
            }
        }
        return result;
    }

    py::array_t<float> getAlbedoBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        // Create 3D array with shape (height, width, 3)
        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
        auto result = py::array_t<float>(shape);
        {
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = camera->albedoBuffer.size();
            for (size_t i = 0; i < size; i++) {
                ptr[i*3] = camera->albedoBuffer[i].x;
                ptr[i*3+1] = camera->albedoBuffer[i].y;
                ptr[i*3+2] = camera->albedoBuffer[i].z;
            }
        }
        return result;
    }

    py::array_t<float> getNormalBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        // Create 3D array with shape (height, width, 3)
        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
        auto result = py::array_t<float>(shape);
        {
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = camera->normalBuffer.size();
            for (size_t i = 0; i < size; i++) {
                ptr[i*3] = camera->normalBuffer[i].x;
                ptr[i*3+1] = camera->normalBuffer[i].y;
                ptr[i*3+2] = camera->normalBuffer[i].z;
            }
        }
        return result;
    }

    // pkg72: per-pixel previous->current screen-space motion vector
    // (float2/pixel, OptiX flow convention). Returns a NumPy view that
    // shares memory with Camera::motionBuffer (no copy); base is a capsule
    // holding a shared_ptr<Camera> ref so the data outlives the array.
    py::array_t<float> getMotionBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");
        auto ref = new std::shared_ptr<Camera>(camera);
        py::capsule keepalive(ref, [](void* p) {
            delete static_cast<std::shared_ptr<Camera>*>(p);
        });
        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height),
                                 static_cast<py::ssize_t>(camera->width), 2};
        py::ssize_t strides[3] = {
            static_cast<py::ssize_t>(camera->width) * 2 * sizeof(float),
            2 * sizeof(float),
            sizeof(float),
        };
        return py::array_t<float>(shape, strides, camera->motionBuffer.data(), keepalive);
    }

    py::array_t<float> getAlphaBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[2] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width)};
        auto result = py::array_t<float>(shape);
        {
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = camera->alphaBuffer.size();
            for (size_t i = 0; i < size; i++) {
                ptr[i] = camera->alphaBuffer[i];
            }
        }
        return result;
    }

    py::array_t<float> getDepthBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[2] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width)};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->depthBuffer.size();
        for (size_t i = 0; i < size; ++i) ptr[i] = camera->depthBuffer[i];
        return result;
    }

    py::array_t<float> getPositionBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->positionBuffer.size();
        for (size_t i = 0; i < size; ++i) {
            ptr[i*3] = camera->positionBuffer[i].x;
            ptr[i*3+1] = camera->positionBuffer[i].y;
            ptr[i*3+2] = camera->positionBuffer[i].z;
        }
        return result;
    }

    py::array_t<float> getUVBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->uvBuffer.size();
        for (size_t i = 0; i < size; ++i) {
            ptr[i*3] = camera->uvBuffer[i].x;
            ptr[i*3+1] = camera->uvBuffer[i].y;
            ptr[i*3+2] = camera->uvBuffer[i].z;
        }
        return result;
    }

    py::array_t<float> getObjectIndexBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[2] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width)};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->objectIndexBuffer.size();
        for (size_t i = 0; i < size; ++i) ptr[i] = camera->objectIndexBuffer[i];
        return result;
    }

    py::array_t<float> getMaterialIndexBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[2] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width)};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->materialIndexBuffer.size();
        for (size_t i = 0; i < size; ++i) ptr[i] = camera->materialIndexBuffer[i];
        return result;
    }

    // pkg87a — Cryptomatte buffers (flat float arrays of ranked [id, weight] pairs)
    py::array_t<float> getCryptomatteObjectBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");
        // Shape: [height, width, depth*2] where depth*2 = [id0, weight0, id1, weight1, ...]
        py::ssize_t shape[3] = {
            static_cast<py::ssize_t>(camera->height),
            static_cast<py::ssize_t>(camera->width),
            static_cast<py::ssize_t>(camera->cryptomatteDepth * 2)
        };
        return py::array_t<float>(shape, camera->cryptoObjectBuffer.data());
    }

    py::array_t<float> getCryptomatteMaterialBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");
        // Shape: [height, width, depth*2] where depth*2 = [id0, weight0, id1, weight1, ...]
        py::ssize_t shape[3] = {
            static_cast<py::ssize_t>(camera->height),
            static_cast<py::ssize_t>(camera->width),
            static_cast<py::ssize_t>(camera->cryptomatteDepth * 2)
        };
        return py::array_t<float>(shape, camera->cryptoMaterialBuffer.data());
    }

    // pkg87d — Write Cryptomatte EXR with Psyop §3 manifest headers
    void writeCryptomatteEXR(const std::string& filepath) {
#ifdef ASTRORAY_EXR_ENABLED
        if (!camera) throw std::runtime_error("Camera not set up");

        int width = camera->width;
        int height = camera->height;
        int depth = camera->cryptomatteDepth;

        // Build channel list (per Psyop naming convention: CryptoObject00.{R,G,B,A}, etc.)
        std::vector<astroray::ExrChannel> channels;
        int numLayers = (depth + 1) / 2;  // depth 6 → 3 layers

        // Temporary buffers to unpack [id,weight] pairs into separate RGBA channels
        std::vector<float> objChannels[3][4];  // [layer][RGBA]
        std::vector<float> matChannels[3][4];
        for (int layer = 0; layer < numLayers && layer < 3; ++layer) {
            for (int ch = 0; ch < 4; ++ch) {
                objChannels[layer][ch].resize(width * height, 0.0f);
                matChannels[layer][ch].resize(width * height, 0.0f);
            }
        }

        // Unpack ranked [id, weight] pairs into RGBA channels
        // Layer N contains ranks 2*N and 2*N+1: R=id(2N), G=weight(2N), B=id(2N+1), A=weight(2N+1)
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                int pixelIdx = y * width + x;
                int bufferOffset = pixelIdx * depth * 2;

                for (int layer = 0; layer < numLayers && layer < 3; ++layer) {
                    int rank0 = layer * 2;
                    int rank1 = layer * 2 + 1;

                    // Object layer
                    if (rank0 < depth) {
                        objChannels[layer][0][pixelIdx] = camera->cryptoObjectBuffer[bufferOffset + rank0 * 2];     // R = id0
                        objChannels[layer][1][pixelIdx] = camera->cryptoObjectBuffer[bufferOffset + rank0 * 2 + 1]; // G = weight0
                    }
                    if (rank1 < depth) {
                        objChannels[layer][2][pixelIdx] = camera->cryptoObjectBuffer[bufferOffset + rank1 * 2];     // B = id1
                        objChannels[layer][3][pixelIdx] = camera->cryptoObjectBuffer[bufferOffset + rank1 * 2 + 1]; // A = weight1
                    }

                    // Material layer
                    if (rank0 < depth) {
                        matChannels[layer][0][pixelIdx] = camera->cryptoMaterialBuffer[bufferOffset + rank0 * 2];
                        matChannels[layer][1][pixelIdx] = camera->cryptoMaterialBuffer[bufferOffset + rank0 * 2 + 1];
                    }
                    if (rank1 < depth) {
                        matChannels[layer][2][pixelIdx] = camera->cryptoMaterialBuffer[bufferOffset + rank1 * 2];
                        matChannels[layer][3][pixelIdx] = camera->cryptoMaterialBuffer[bufferOffset + rank1 * 2 + 1];
                    }
                }
            }
        }

        // Add channels to EXR
        const char* chanNames[4] = {"R", "G", "B", "A"};
        for (int layer = 0; layer < numLayers && layer < 3; ++layer) {
            for (int ch = 0; ch < 4; ++ch) {
                char objName[64], matName[64];
                snprintf(objName, sizeof(objName), "CryptoObject%02d.%s", layer, chanNames[ch]);
                snprintf(matName, sizeof(matName), "CryptoMaterial%02d.%s", layer, chanNames[ch]);
                channels.push_back({objName, objChannels[layer][ch].data()});
                channels.push_back({matName, matChannels[layer][ch].data()});
            }
        }

        // Build Psyop §3 manifest headers
        auto objHeaders = crypto_manifest_headers("CryptoObject");
        auto matHeaders = crypto_manifest_headers("CryptoMaterial");
        std::map<std::string, std::string> allHeaders;
        allHeaders.insert(objHeaders.begin(), objHeaders.end());
        allHeaders.insert(matHeaders.begin(), matHeaders.end());

        // Write EXR
        astroray::writeExr(filepath, width, height, channels, allHeaders);
#else
        throw std::runtime_error("Cryptomatte EXR writer not available — OpenEXR not found at build time");
#endif
    }

    py::array_t<float> getRenderPassBuffer(const std::string& passName) {
        if (!camera) throw std::runtime_error("Camera not set up");

        std::string key = passName;
        for (char& c : key) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));

        if (key == "depth" || key == "object_index" || key == "material_index") {
            const std::vector<float>* scalarBuffer = nullptr;
            if (key == "depth") scalarBuffer = &camera->depthBuffer;
            else if (key == "object_index") scalarBuffer = &camera->objectIndexBuffer;
            else if (key == "material_index") scalarBuffer = &camera->materialIndexBuffer;
            py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
            auto result = py::array_t<float>(shape);
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = scalarBuffer->size();
            for (size_t i = 0; i < size; ++i) {
                float value = (*scalarBuffer)[i];
                ptr[i*3] = value;
                ptr[i*3+1] = value;
                ptr[i*3+2] = value;
            }
            return result;
        }
        if (key == "position" || key == "uv") {
            const std::vector<Vec3>* vecBuffer = (key == "position") ? &camera->positionBuffer : &camera->uvBuffer;
            py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
            auto result = py::array_t<float>(shape);
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = vecBuffer->size();
            for (size_t i = 0; i < size; ++i) {
                ptr[i*3] = (*vecBuffer)[i].x;
                ptr[i*3+1] = (*vecBuffer)[i].y;
                ptr[i*3+2] = (*vecBuffer)[i].z;
            }
            return result;
        }
        // Dead code: cryptoObjectBuffer / cryptoMaterialBuffer are std::vector<float>,
        // not std::vector<Vec3>. Dedicated getCryptomatteObjectBuffer/MaterialBuffer
        // methods exist at lines 1285-1305. Remove in pkg87b cleanup.
        /*
        if (key == "cryptomatte_object" || key == "cryptomatte_material") {
            const std::vector<Vec3>* vecBuffer = (key == "cryptomatte_object")
                ? &camera->cryptoObjectBuffer
                : &camera->cryptoMaterialBuffer;
            py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
            auto result = py::array_t<float>(shape);
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            size_t size = vecBuffer->size();
            for (size_t i = 0; i < size; ++i) {
                ptr[i*3] = (*vecBuffer)[i].x;
                ptr[i*3+1] = (*vecBuffer)[i].y;
                ptr[i*3+2] = (*vecBuffer)[i].z;
            }
            return result;
        }
        */

        static const std::unordered_map<std::string, int> kPassNameToIndex = {
            {"diffuse_direct", PASS_DIFFUSE_DIRECT},
            {"diffuse_indirect", PASS_DIFFUSE_INDIRECT},
            {"diffuse_color", PASS_DIFFUSE_COLOR},
            {"glossy_direct", PASS_GLOSSY_DIRECT},
            {"glossy_indirect", PASS_GLOSSY_INDIRECT},
            {"glossy_color", PASS_GLOSSY_COLOR},
            {"transmission_direct", PASS_TRANSMISSION_DIRECT},
            {"transmission_indirect", PASS_TRANSMISSION_INDIRECT},
            {"transmission_color", PASS_TRANSMISSION_COLOR},
            {"volume_direct", PASS_VOLUME_DIRECT},
            {"volume_indirect", PASS_VOLUME_INDIRECT},
            {"emission", PASS_EMISSION},
            {"environment", PASS_ENVIRONMENT},
            {"ao", PASS_AO},
            {"shadow", PASS_SHADOW}
        };

        auto it = kPassNameToIndex.find(key);
        if (it == kPassNameToIndex.end()) {
            throw std::runtime_error("Unknown render pass: " + passName);
        }

        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 3};
        auto result = py::array_t<float>(shape);
        {
            py::buffer_info buf = result.request();
            float* ptr = static_cast<float*>(buf.ptr);
            const std::vector<Vec3>& passBuffer = camera->renderPassBuffers[it->second];
            size_t size = passBuffer.size();
            for (size_t i = 0; i < size; i++) {
                ptr[i*3] = passBuffer[i].x;
                ptr[i*3+1] = passBuffer[i].y;
                ptr[i*3+2] = passBuffer[i].z;
            }
        }
        return result;
    }

    void setIntegratorParam(const std::string& key, int value) {
        integratorParams_.set(key, value);
        // pkg91: if an integrator is already registered, rebuild it with the
        // updated params (option B.1 from spec). Mirrors PBRT-v4 scene rebuild
        // on parameter change (src/pbrt/integrators.cpp, Apache-2.0). The cost
        // is one integrator constructor invocation; all current integrators
        // are cheap to construct (no pre-allocated reservoirs or caches at
        // construction time — those are allocated in beginFrame).
        if (!integratorName_.empty()) {
            auto integrator = astroray::IntegratorRegistry::instance().create(
                integratorName_, integratorParams_);
            renderer.setIntegrator(integrator);
        }
    }

    // pkg-integrator-float-param: float route mirroring setIntegratorParam.
    // ParamDict distinguishes int and float storage (std::get_if exact-type match),
    // so a float-valued integrator param must be set via this route; integrators
    // read such params with ParamDict::getNumber (accepts either int or float).
    void setIntegratorParamFloat(const std::string& key, float value) {
        integratorParams_.set(key, value);
        if (!integratorName_.empty()) {
            auto integrator = astroray::IntegratorRegistry::instance().create(
                integratorName_, integratorParams_);
            renderer.setIntegrator(integrator);
        }
    }

    // pkg111: string parameter route (mirrors setIntegratorParam / setIntegratorParamFloat).
    void setIntegratorParamStr(const std::string& key, const std::string& value) {
        integratorParams_.set(key, value);
        if (!integratorName_.empty()) {
            auto integrator = astroray::IntegratorRegistry::instance().create(
                integratorName_, integratorParams_);
            renderer.setIntegrator(integrator);
        }
    }

    // pkg39: multi-wavelength rendering helpers
    void setWavelengthRange(float lambdaMin, float lambdaMax) {
        integratorParams_.set("lambda_min", lambdaMin);
        integratorParams_.set("lambda_max", lambdaMax);
    }

    void setOutputMode(const std::string& mode) {
        integratorParams_.set("output_mode", mode);
    }

    void setMaterialSpectralProfile(int materialId, const std::string& profileName,
                                    bool replace = false) {
        auto it = materials.find(materialId);
        if (it == materials.end()) return;
        auto& db = astroray::SpectralProfileDatabase::instance();
        const auto* profile = db.get(profileName);
        // pkg195 Stage C: `replace` picks Replace mode (authored SPD drives all λ,
        // set by source nodes wired to a Surface); the pkg58 material-panel
        // fallback passes replace=false (ExtendOnly — out-of-band only).
        if (profile) it->second->setSpectralProfile(
            profile, replace ? astroray::ProfileMode::Replace
                             : astroray::ProfileMode::ExtendOnly);
    }

    void clearMaterialSpectralProfile(int materialId) {
        auto it = materials.find(materialId);
        if (it != materials.end()) it->second->setSpectralProfile(nullptr);
    }

    void setIntegrator(const std::string& name) {
        if (name == "auto" || name == "default" || name.empty()) {
            // pkg148: reset to the "path_tracer" default rather than empty —
            // an empty integratorName_ only fell back correctly on CPU (via
            // Renderer::ensureDefaultIntegrator()'s lazy default); the GPU
            // dispatch has no such fallback and silently dropped dedicated-light
            // NEE. This is itself one of the reset sites the footgun could
            // reappear through, so it gets the same default as construction.
            auto integrator = astroray::IntegratorRegistry::instance().create(
                "path_tracer", integratorParams_);
            renderer.setIntegrator(integrator);
            integratorName_ = "path_tracer";
            return;
        }
        auto integrator = astroray::IntegratorRegistry::instance().create(name, integratorParams_);
        renderer.setIntegrator(integrator);
        integratorName_ = name;
        // pkg55-C6b: a new integrator instance == a new ReSTIR temporal session.
        // Monotonic + globally unique (static counter) so it never collides with
        // a freed-then-realloc'd renderer address.
        static uint64_t g_restirSessionCounter = 0;
        restirSessionId_ = ++g_restirSessionCounter;
    }

    // pkg148: expose the currently-selected integrator name so the default
    // (now "path_tracer" rather than empty) can be pinned by a binding-level
    // test — see test_pkg148_default_integrator.py.
    std::string getIntegrator() const {
        return integratorName_;
    }

    py::dict getIntegratorStats() const {
        py::dict out;
        for (const auto& kv : renderer.integratorDebugStats()) {
            out[py::str(kv.first)] = kv.second;
        }
        return out;
    }

    // ------------------------------------------------------------------
    // pkg84 — CUDA kernel pre-warm at viewport start
    //
    // Cycles pattern (intern/cycles/device/cuda/device.cpp reserve_local_memory,
    // Apache-2.0): launch a minimal kernel to JIT-compile and pre-allocate
    // resources before the user's first "real" render. This moves the ~12s
    // CUDA context init + kernel JIT cost to a moment the user expects to wait
    // (addon load, viewport "Rendered" button click) instead of mid-navigation.
    //
    // Called by the Blender addon when the persistent viewport renderer is
    // instantiated with device_mode='cuda'. Renders 1 pixel of a trivial scene
    // (single triangle), swallowing the result. Idempotent (guarded by the
    // addon, not here).
    // ------------------------------------------------------------------
    void prewarmCUDA() {
#ifdef ASTRORAY_CUDA_ENABLED
        if (!useGPU || !cudaRenderer || !cudaRenderer->isAvailable()) {
            return;
        }

        // Use a fully isolated temporary renderer to avoid leaving dangling
        // GPU pointers. This ensures the main renderer's state
        // (this->renderer) is never polluted with throwaway geometry that
        // gets cleared before the GPU pointers are freed. (pkg55-C7: the
        // temporary CUDARenderer went with the megakernels; the wavefront
        // warm below owns its context/state.)
        Renderer tempRenderer;

        // Trivial scene: single grey triangle at origin + camera looking at it.
        // Minimal cost to build but still enough to force full kernel JIT.
        auto grey = std::make_shared<Lambertian>(Vec3(0.5f));
        auto tri = std::make_shared<Triangle>(
            Vec3(-1, 0, 5), Vec3(1, 0, 5), Vec3(0, 1, 5), grey
        );
        tempRenderer.addObject(tri);

        // 1-pixel camera, 1 spp, 1 bounce — just enough to hit the kernel.
        // We discard the result; the goal is to populate the JIT cache.
        auto cam = std::make_shared<Camera>(
            Vec3(0, 0, 0), Vec3(0, 0, 1), Vec3(0, 1, 0),
            60.0f, 1.0f, 0.0f, 1.0f, 1, 1
        );

        tempRenderer.buildAcceleration();

        // Launch the production (wavefront) kernels. This is where the JIT +
        // context init happens. The JIT cache is process-wide, so triggering
        // it here warms the cache for the real renders as well.
        // pkg55-C7: the megakernels are deleted; warm the wavefront pipeline
        // (the only GPU render path). uploadScene is not needed — the
        // wavefront does its own scene flatten/upload.
#ifdef ASTRORAY_WAVEFRONT_CUDA_N3
        (void)astroray::wavefront::cuda_wavefront_render(
            tempRenderer, *cam, 1, 1, /*samples=*/1, /*max_depth=*/1,
            /*seed=*/1, 380.0f, 780.0f, /*useLuminanceOutput=*/false,
            /*enableNEE=*/true);
#endif

        // tempRenderer is automatically destroyed at scope exit via RAII,
        // freeing all GPU resources cleanly. No dangling pointers.
#endif
        // CPU path: no pre-warm needed.
    }

    // ------------------------------------------------------------------
    // pkg56 Phase B — per-domain incremental uploaders.
    //
    // Cycles BlenderSync (intern/cycles/blender/sync.cpp, Apache-2.0) splits
    // its viewport sync into geometry / shaders / lights / world per-domain
    // entry points keyed off ID_RECALC_GEOMETRY / _SHADING / etc. We mirror
    // that surface here so Phase C's depsgraph dispatch (separate package)
    // can target the affected uploader instead of always paying the full
    // re-upload cost.
    //
    // All five entries are also exposed under stable Python names below.
    // Behaviour for callers that invoke the full sequence (or call the
    // existing render() entry) is unchanged — uploadScene() composes the
    // four domain uploads in the same order BlenderSync uses in sync_data().
    //
    // The CPU Renderer requires a built BVH for uploadGeometry(). The other
    // three tolerate a missing BVH (partial state); they log and return
    // without touching device memory in that case — matching pkg56 spec
    // "Uploaders are order-independent for state".
    // ------------------------------------------------------------------

    // Build (or rebuild) the CPU BVH and push geometry buffers to the GPU.
    // Materials, lights and environment device buffers are untouched.
    void uploadGeometry() {
        renderer.buildAcceleration();
#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            if (!camera) {
                throw std::runtime_error(
                    "upload_geometry: camera must be set up before GPU upload");
            }
            cudaRenderer->uploadGeometry(renderer, *camera);
        }
#endif
    }

    // pkg114 inc 3d — update one instance's object->world transform on the CPU
    // (no geometry rebuild). Call upload_instance_transforms() once after a batch
    // of these to re-push the TLAS to the device.
    void updateInstanceTransform(int instanceId, const std::vector<float>& transform) {
        if (transform.size() != 16)
            throw std::runtime_error("update_instance_transform: transform must have 16 floats");
        std::array<float, 16> m;
        for (int i = 0; i < 16; ++i) m[i] = transform[i];
        renderer.updateInstanceTransform(instanceId, m);
    }

    // pkg114 inc 3d — TLAS-only re-upload: re-push d_instances + d_tlas from the
    // current instance transforms, leaving all BLAS geometry on the device intact.
    // The cheap path for a transform-only viewport edit of an instanced object.
    void uploadInstanceTransforms() {
#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            cudaRenderer->uploadInstanceTransforms(renderer);
        }
#endif
    }

    // Push only material payloads (GMaterial flat array + spectral profile
    // table) to the GPU. Geometry / BVH / lights / env are untouched.
    // Cycles equivalent: Shader::tag_update() → ShaderManager::device_update.
    void uploadMaterials() {
#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            cudaRenderer->uploadMaterials(renderer);
        }
#endif
    }

    // Push only light buffer + power CDF to the GPU. Geometry / materials /
    // env are untouched. Cycles equivalent: LightManager::device_update.
    void uploadLights() {
#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            cudaRenderer->uploadLights(renderer);
        }
#endif
        // CPU path: light data lives inside Renderer::lights, which the
        // path tracer reads on the fly from buildAcceleration()'s output.
        // No CPU-side action needed — the addition itself was via addObject.
    }

    // Push only env map buffers + sampling tables (and post-pkg63 the MIS
    // CDF) to the GPU. Geometry / materials / lights are untouched.
    // Cycles equivalent: world_recalc → BackgroundManager::device_update.
    void uploadEnvironment() {
#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            // PyRenderer mirrors envMap onto Renderer at load_environment_map
            // time; ensure that link is current before pushing.
            if (envMap) renderer.setEnvironmentMap(envMap);
            cudaRenderer->uploadEnvironment(renderer);
        }
#endif
    }

    // Sequenced full upload — calls all four domain uploaders + builds the
    // BVH. Behaviour is identical (same final device state) to today's
    // implicit upload inside render(); existing callers and tests are
    // unaffected. Phase C will _stop_ calling this in favour of selective
    // dispatch on bpy.types.Depsgraph.updates.
    void uploadScene() {
        renderer.buildAcceleration();
        if (envMap) renderer.setEnvironmentMap(envMap);
#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            if (!camera) {
                throw std::runtime_error(
                    "upload_scene: camera must be set up before GPU upload");
            }
            cudaRenderer->uploadScene(renderer, *camera);
        }
#endif
    }

    // Replace an existing scene primitive's transform in place.
    //
    // pkg56 Phase B note: Astroray's BVH is a single combined TLAS+BLAS
    // today (research note §4.1). A transform-only edit therefore still
    // rebuilds the whole BVH from inside this binding — the binding is
    // about giving Phase C a *dispatch target* that maps to Cycles'
    // Object-with-ID_RECALC_TRANSFORM-only branch, not a hot path. The
    // bigger win arrives when a future package introduces a two-level
    // acceleration structure. Documented in the Python docstring.
    //
    // `obj_id` is the 0-based insertion index into the renderer's scene
    // list (the order in which add_sphere / add_triangle / add_area_light
    // / add_sun_light / add_spot_light / add_mesh / add_volume / etc.
    // were called). `transform_matrix` is a 16-element row-major 4x4
    // affine matrix (Blender's matrix_world.transposed-or-flattened layout).
    //
    // Currently supports Sphere translation and Triangle full-affine
    // vertex transform. Returns silently if the object id is out of range
    // or refers to an unsupported Hittable type — the upstream caller
    // (Phase C) should fall back to a full uploadGeometry() in that case.
    void updateObjectTransform(int objId,
                               const std::vector<float>& transformMatrix) {
        auto& scene = renderer.getSceneMutable();
        if (objId < 0 || static_cast<size_t>(objId) >= scene.size()) {
            throw std::runtime_error(
                "update_object_transform: object id " + std::to_string(objId) +
                " out of range (scene has " + std::to_string(scene.size()) +
                " objects)");
        }
        if (transformMatrix.size() != 16) {
            throw std::runtime_error(
                "update_object_transform: transform_matrix must have 16 floats");
        }
        const float* m = transformMatrix.data();
        auto applyAffine = [&](const Vec3& p) {
            // Row-major: m[r*4+c]. Result = M * (p; 1).
            float x = m[0]*p.x + m[1]*p.y + m[2]*p.z + m[3];
            float y = m[4]*p.x + m[5]*p.y + m[6]*p.z + m[7];
            float z = m[8]*p.x + m[9]*p.y + m[10]*p.z + m[11];
            return Vec3(x, y, z);
        };

        Hittable* h = scene[objId].get();
        if (auto* sph = dynamic_cast<Sphere*>(h)) {
            // Spheres: apply translation only (uniform scale would change
            // radius — out of scope for Phase B; would be a separate
            // setRadius binding).
            Vec3 oldC = sph->getCenter();
            sph->setCenter(applyAffine(oldC));
        } else if (auto* tri = dynamic_cast<Triangle*>(h)) {
            tri->setVertices(applyAffine(tri->getV0()),
                             applyAffine(tri->getV1()),
                             applyAffine(tri->getV2()));
        } else {
            // Unsupported Hittable type. Phase C dispatch falls back to
            // full uploadGeometry on this branch — no-op here is correct.
            return;
        }

        // Single-level BVH: rebuild + republish geometry. Documented as the
        // current cost; pkg56 Phase C still wires through this binding
        // because the dispatch itself remains valuable, even though the
        // cost win waits on the two-level BVH follow-up.
        uploadGeometry();
    }

    void clear() {
        renderer = Renderer();
        camera.reset();
        materials.clear();
        nextMaterialId = 0;
        textureManager = TextureManager();
        envMap.reset();
        useGPU = false;
        // pkg148: reset to the "path_tracer" default, not empty — see the
        // construction-site comment above integratorName_'s declaration.
        integratorName_ = "path_tracer";
        integratorParams_ = astroray::ParamDict();
#ifdef ASTRORAY_CUDA_ENABLED
        cudaRenderer.reset();
#endif
    }
    int getWidth() const { return camera ? camera->width : 0; }
    int getHeight() const { return camera ? camera->height : 0; }

    // pkg56 Phase B — observability hooks for the partial-state tests.
    // Cheap CPU-side counters that let test_pkg56_phase_b_uploaders.py
    // assert "uploadMaterials() did not rebuild the BVH" without poking
    // device memory. No external behaviour change.
    py::dict getSceneStats() const {
        py::dict out;
        out["objects"]  = static_cast<int>(renderer.getScene().size());
        out["materials"] = static_cast<int>(materials.size());
        auto& bvh = renderer.getBVH();
        out["bvh_built"] = static_cast<bool>(bvh);
        out["bvh_nodes"] = bvh ? static_cast<int>(bvh->getNodes().size()) : 0;
        out["lights"]    = static_cast<int>(renderer.getLights().getLights().size());
        out["env_loaded"] = (envMap && envMap->loaded());
        return out;
    }

    // pkg55 Phase B' Session 2b — accessors for reference PT bindings.
    Renderer& getRenderer() { return renderer; }
    const Renderer& getRenderer() const { return renderer; }
    std::shared_ptr<Camera> getCamera() { return camera; }
    const std::shared_ptr<Camera> getCamera() const { return camera; }
};

// pkg56 Phase A: viewport-sync per-stage timing ring buffer storage.
// Lifted to namespace scope because GCC rejects static-constexpr members
// inside a local class declared in a function body.
namespace {

struct ViewportPerfRing {
    static constexpr size_t kCapacity = 100;
    static constexpr size_t kStages = 5;
    std::array<std::array<double, kStages>, kCapacity> frames{};
    std::array<double, kStages> current{};  // accumulator for in-flight frame
    size_t head = 0;                        // next slot to write
    size_t size = 0;                        // filled slots (≤ kCapacity)
    std::mutex mtx;
};

ViewportPerfRing g_viewport_perf_ring;

constexpr std::array<const char*, ViewportPerfRing::kStages>
kViewportPerfStageNames = {
    "geometry", "materials", "lights", "environment", "render"
};

int viewport_perf_stage_index(const std::string& name) {
    for (size_t i = 0; i < kViewportPerfStageNames.size(); ++i) {
        if (name == kViewportPerfStageNames[i]) return static_cast<int>(i);
    }
    return -1;
}

}  // namespace

PYBIND11_MODULE(astroray, m) {
    m.doc() = "Astroray - Physically Based Path Tracer";
    py::class_<PyRenderer>(m, "Renderer")
        .def(py::init<>())
        .def("load_texture", &PyRenderer::loadTexture,
             "name"_a, "image_data"_a, "width"_a, "height"_a, "coord_mode"_a = "UV")
        .def("create_procedural_texture", &PyRenderer::createProceduralTexture,
             "name"_a, "type"_a, "params"_a, "coord_mode"_a = "UV")
        .def("set_texture_coord_mode", &PyRenderer::setTextureCoordMode, "name"_a, "coord_mode"_a)
        .def("set_texture_generated_bbox", &PyRenderer::setTextureGeneratedBBox,
             "name"_a, "bbox_min"_a, "bbox_size"_a,
             "pkg115: bake the object's bounding box for GENERATED-coordinate "
             "procedural textures (Blender Texture Coordinate > Generated).")
        .def("set_texture_uv_transform", &PyRenderer::setTextureUVTransform,
             "name"_a, "scale_x"_a, "scale_y"_a, "offset_x"_a, "offset_y"_a,
             "rotation"_a = 0.0f,
             "Apply scale + Z-rotation + offset (UV-space) to a texture; "
             "baked from a Blender Mapping node. Order matches Blender Point "
             "mapping: scale → rotate → translate. Rotation is in radians.")
        .def("set_texture_mapping_matrix", &PyRenderer::setTextureMappingMatrix,
             "name"_a, "matrix"_a,
             "pkg219a: apply a full 3-D Blender Mapping node transform (top 3x4 "
             "rows, row-major) to a texture. Supersedes set_texture_uv_transform; "
             "composed addon-side via mathutils.Matrix.LocRotScale for exact "
             "euler parity. Image textures sample at (M*coord).xy.")
        .def("set_texture_uv_layer", &PyRenderer::setTextureUVLayerName,
             "name"_a, "layer_name"_a)
        .def("create_program_texture", &PyRenderer::createProgramTexture,
             "name"_a, "coord_mode"_a = "UV",
             "pkg219b: register a per-texel op-VM chain (Color Ramp / Mix / Math "
             "/ Map Range downstream of a texture). Add inputs with "
             "program_texture_add_input, then compile with "
             "set_program_texture_program; reference by name as a material texture.")
        .def("program_texture_add_input", &PyRenderer::programTextureAddInput,
             "name"_a, "input_name"_a,
             "pkg219b: append an input (child) texture to a program texture, in "
             "OP_LOAD_TEX index order.")
        .def("set_program_texture_program", &PyRenderer::setProgramTextureProgram,
             "name"_a, "num_tex"_a, "out_slot"_a,
             "code_flat"_a, "consts_flat"_a, "ramps_flat"_a,
             "pkg219b: set the compiled bytecode. code_flat = 8 ints/instr "
             "(op,out,a,b,c,d,e,imm); consts_flat = 3 floats/const; ramps_flat = "
             "numRamps*256*3 floats (baked Color-Ramp tables, RGB).")
        .def("create_material", &PyRenderer::createMaterial, "type"_a, "base_color"_a, "params"_a)
        .def("eval_material", &PyRenderer::evalMaterial,
             "material_id"_a, "wo"_a, "wi"_a,
             "normal"_a = std::vector<float>{0.0f, 1.0f, 0.0f})
        .def("integrate_material_reflectance", &PyRenderer::integrateMaterialReflectance,
             "material_id"_a, "cos_theta_o"_a, "samples"_a = 4096,
             "Halton hemisphere integration of material eval(), used for BRDF conservation tests.")
        .def("debug_bsdf_sample_batch", &PyRenderer::debug_bsdf_sample_batch,
             "material_id"_a, "wo"_a, "u2_array"_a,
             "pkg121: batched BSDF sample for chi² tests (CPU-only). "
             "wo = outgoing to viewer (fixed), u2_array is (2, N) uniform samples, "
             "returns (wi_array (N,3) sampled incident directions, pdf_array (N,)).")
        .def("debug_bsdf_pdf_batch", &PyRenderer::debug_bsdf_pdf_batch,
             "material_id"_a, "wo"_a, "wi_array"_a,
             "pkg121: batched BSDF PDF eval for chi² tests (CPU-only). "
             "wo = outgoing to viewer (fixed), wi_array is (N,3) incident directions, "
             "returns pdf_array (N,).")
        .def("add_sphere", &PyRenderer::addSphere, "center"_a, "radius"_a, "material_id"_a,
            "ies_direction"_a = std::vector<float>(), "ies_file"_a = std::string(),
            "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_spot_light", &PyRenderer::addSpotLight, "center"_a, "direction"_a, "radius"_a,
             "material_id"_a, "spot_angle"_a, "spot_smooth"_a, "ies_file"_a = std::string(),
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_sun_light", &PyRenderer::addSunLight, "direction"_a, "angular_diameter"_a, "material_id"_a,
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_area_light", &PyRenderer::addAreaLight,
             "center"_a, "axis_u"_a, "axis_v"_a, "size_x"_a, "size_y"_a,
             "shape"_a, "material_id"_a, "spread"_a = 1.0f,
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_point_light", &PyRenderer::addPointLight,
             "position"_a, "emission"_a, "intensity"_a, "radius"_a = 0.0f,
             "ies_file"_a = std::string(), "object_pass_index"_a = 0, "material_pass_index"_a = 0,
             "pkg89 Phase B: dedicated PointLight with EmissionSpectrum")
        .def("add_sun_light_dedicated", &PyRenderer::addSunLightDedicated,
             "direction"_a, "angular_diameter"_a, "emission"_a, "intensity"_a,
             "object_pass_index"_a = 0, "material_pass_index"_a = 0,
             "pkg89 Phase B: dedicated DistantLight with EmissionSpectrum")
        .def("add_area_light_dedicated", &PyRenderer::addAreaLightDedicated,
             "center"_a, "axis_u"_a, "axis_v"_a, "size_x"_a, "size_y"_a,
             "shape"_a, "emission"_a, "intensity"_a, "spread"_a = 1.0f,
             "object_pass_index"_a = 0, "material_pass_index"_a = 0,
             "pkg89 Phase B: dedicated AreaLight with EmissionSpectrum")
        .def("add_spot_light_dedicated", &PyRenderer::addSpotLightDedicated,
             "center"_a, "direction"_a, "inner_angle"_a, "outer_angle"_a,
             "emission"_a, "intensity"_a, "radius"_a = 0.0f, "ies_file"_a = std::string(),
             "object_pass_index"_a = 0, "material_pass_index"_a = 0,
             "pkg89 Phase B: dedicated SpotLight with EmissionSpectrum")
        .def("add_triangle", &PyRenderer::addTriangle, "v0"_a, "v1"_a, "v2"_a, "material_id"_a,
             "uv0"_a = std::vector<float>(), "uv1"_a = std::vector<float>(), "uv2"_a = std::vector<float>(),
             "n0"_a = std::vector<float>(), "n1"_a = std::vector<float>(), "n2"_a = std::vector<float>(),
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_triangle_layers", &PyRenderer::addTriangleLayers,
             "v0"_a, "v1"_a, "v2"_a, "material_id"_a, "uv_layers"_a,
             "n0"_a = std::vector<float>(), "n1"_a = std::vector<float>(), "n2"_a = std::vector<float>(),
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_triangles_bulk", &PyRenderer::addTrianglesBulk,
             "positions"_a, "material_ids"_a, "material_pass_indices"_a, "object_pass_index"_a,
             "uvs"_a, "uv_layer_names"_a, "normals"_a,
             "pkg112: bulk triangle ingest from NumPy arrays (loops in C++ to cut per-tri "
             "pybind overhead). positions (N,3,3) world; uvs (nLayers,N,3,2) active-first; "
             "normals (N,3,3) or empty. Pixel-identical to add_triangle/add_triangle_layers.")
        .def("add_triangles_bulk_motion", &PyRenderer::addTrianglesBulkMotion,
             "positions_start"_a, "positions_end"_a, "material_ids"_a, "material_pass_indices"_a,
             "object_pass_index"_a, "uvs"_a, "uv_layer_names"_a, "normals"_a,
             "pkg88-C.0: bulk motion triangle ingest. positions_start (N,3,3) is center step, "
             "positions_end (N,3,3) is shutter close. Linear interpolation per Cycles (Apache-2.0). "
             "motionSteps=2 (pre+post). uvs/normals same as add_triangles_bulk.")
        .def("register_mesh_triangles", &PyRenderer::registerMeshTriangles,
             "triangles"_a, "material_id"_a, "object_name"_a = "",
             "pkg114: register a mesh's OBJECT-LOCAL flat-shaded triangles (list of "
             "(9,) [v0,v1,v2]) once; returns mesh_id for add_instance(). object_name "
             "(optional) sets the Cryptomatte object id baked into the shared BLAS.")
        .def("register_mesh_bulk", &PyRenderer::registerMeshBulk,
             "positions"_a, "material_ids"_a, "material_pass_indices"_a, "object_pass_index"_a,
             "uvs"_a, "uv_layer_names"_a, "normals"_a, "object_name"_a = "",
             "pkg114: register a mesh's OBJECT-LOCAL geometry once (UVs/normals/multi-"
             "material) into a shared BLAS; returns mesh_id for add_instance(). Bulk twin "
             "of register_mesh_triangles. positions (N,3,3) object-space; arrays match "
             "add_triangles_bulk. object_name (optional) sets the Cryptomatte object id "
             "baked into the shared BLAS triangles.")
        .def("add_instance", &PyRenderer::addInstance, "mesh_id"_a, "transform"_a,
             "pkg114: instance a registered mesh with a row-major 4x4 object->world "
             "transform (16 floats). Returns instance_id.")
        .def("add_mesh", &PyRenderer::addMesh, "filename"_a, "material_id"_a,
             "position"_a = std::vector<float>{0,0,0}, "scale"_a = std::vector<float>{1,1,1}, "rotation_y"_a = 0.0f,
             "smooth_normals"_a = false)
        .def("add_volume", &PyRenderer::addVolume,
             "center"_a, "radius"_a, "density"_a, "color"_a,
             "anisotropy"_a = 0.0f, "emission_strength"_a = 0.0f,
             "emission_color"_a = std::vector<float>{1.0f, 1.0f, 1.0f})
        .def("add_black_hole", &PyRenderer::addBlackHole,
             "position"_a, "mass"_a, "influence_radius"_a, "params"_a = py::dict())
        .def("setup_camera", &PyRenderer::setupCamera, "look_from"_a, "look_at"_a, "vup"_a, "vfov"_a,
             "aspect_ratio"_a, "aperture"_a, "focus_dist"_a, "width"_a, "height"_a,
             "shift_x"_a = 0.0f, "shift_y"_a = 0.0f)
        .def("set_camera_motion_blur", &PyRenderer::setCameraMotionBlur,
             "start_t"_a, "start_r"_a, "start_s"_a, "end_t"_a, "end_r"_a, "end_s"_a,
             "shutter"_a, "shutter_position"_a,
             "pkg88-A: set camera motion blur keyframes (T/R/S decomposed). "
             "start_t/end_t: translation [x,y,z]. start_r/end_r: rotation quaternion [w,x,y,z]. "
             "start_s/end_s: scale [x,y,z]. shutter: duration in frames. "
             "shutter_position: 0=Start, 1=Center, 2=End.")
        .def("set_adaptive_sampling", &PyRenderer::setAdaptiveSampling, "enable"_a)
        .def("set_clamp_direct", &PyRenderer::setClampDirect, "value"_a)
        .def("set_clamp_indirect", &PyRenderer::setClampIndirect, "value"_a)
        .def("set_filter_glossy", &PyRenderer::setFilterGlossy, "value"_a)
        .def("set_seed", &PyRenderer::setSeed, "seed"_a)
        .def("set_pixel_filter", &PyRenderer::setPixelFilter, "filter_type"_a, "filter_width"_a)
        .def("set_light_sampler", &PyRenderer::setLightSampler, "mode"_a)
        .def("debug_light_tree_pick", &PyRenderer::debugLightTreePick,
             "points"_a, "normals"_a, "us"_a,
             "pkg86-B: batch CPU light-tree pick probe (flattened xyz points/normals "
             "+ per-query u). Returns (light_indices, pdfs); -2 marks dedicated lights.")
        .def("debug_light_tree_pick_gpu", &PyRenderer::debugLightTreePickGpu,
             "points"_a, "normals"_a, "us"_a,
             "pkg86-B: GPU twin of debug_light_tree_pick on the resident device tree. "
             "Requires set_use_gpu(True) + set_light_sampler('tree') + upload_scene().")
        .def("get_light_tree_upload_ms", &PyRenderer::getLightTreeUploadMs,
             "pkg86-B: wall-clock ms of the most recent GPU light-tree upload (0 = none).")
        .def("set_world_max_bounces", &PyRenderer::setWorldMaxBounces, "max_bounces"_a)
        .def("set_world_volume", &PyRenderer::setWorldVolume,
             "density"_a, "color"_a, "anisotropy"_a = 0.0f, "scatter"_a = 0.0f)
        .def("set_use_reflective_caustics", &PyRenderer::setUseReflectiveCaustics, "use"_a)
        .def("set_use_refractive_caustics", &PyRenderer::setUseRefractiveCaustics, "use"_a)
        .def("set_use_photon_caustics", &PyRenderer::setUsePhotonCaustics, "use"_a)
        .def("set_use_progressive_sampler", &PyRenderer::setUseProgressiveSampler, "use"_a)
        .def("set_object_caustic_caster", &PyRenderer::setObjectCausticCaster,
             "object_id"_a, "enabled"_a,
             "pkg64 Phase 3 — flag an object (by addObject order) as a "
             "caustic caster. Default path_tracer attempts SMS connections "
             "through flagged objects when use_refractive_caustics=True.")
        .def("caustic_caster_count", &PyRenderer::getCausticCasterCount)
        .def("scene_object_count", &PyRenderer::getSceneObjectCount)
        .def("set_object_name", &PyRenderer::setObjectName,
             "object_id"_a, "name"_a,
             "pkg87c — Set object name for Cryptomatte hashing (by addObject order)")
        .def("set_material_name", &PyRenderer::setMaterialName,
             "material_id"_a, "name"_a,
             "pkg87c — Set material name for Cryptomatte hashing (by create_material return ID)")
        .def("set_cryptomatte_enabled", &PyRenderer::setCryptomatteEnabled,
             "enabled"_a,
             "pkg87c — Enable/disable Cryptomatte per-shade-point accumulation")
        .def("set_cryptomatte_depth", &PyRenderer::setCryptomatteDepth,
             "depth"_a,
             "pkg87c — Set Cryptomatte rank depth (number of ID/weight pairs per pixel)")
        .def("set_gpu_guide_aovs", &PyRenderer::setGpuGuideAOVs,
             "enabled"_a,
             "pkg197 — Enable/disable GPU wavefront first-hit denoise-guide AOV "
             "capture (albedo/normal/depth). On by default; off leaves the buffers "
             "zero (guide-less denoise control / viewport copy-back lever).")
        .def("get_gpu_guide_aovs", &PyRenderer::getGpuGuideAOVs,
             "pkg197 — Query the GPU denoise-guide AOV capture flag.")
        .def("set_gpu_light_path_passes", &PyRenderer::setGpuLightPathPasses,
             "enabled"_a,
             "pkg198 Stage 2 — enable/disable GPU wavefront light-path render passes "
             "(diffuse/glossy/transmission direct+indirect, emission, environment). "
             "Off by default; when on, the wavefront fills camera renderPassBuffers so "
             "get_render_pass_buffer(name) returns the GPU passes (Σpasses == beauty).")
        .def("get_gpu_light_path_passes", &PyRenderer::getGpuLightPathPasses,
             "pkg198 Stage 2 — query the GPU light-path render-pass flag.")
        .def("load_environment_map", &PyRenderer::loadEnvironmentMap,
             "path"_a, "strength"_a = 1.0f,
             "rx"_a = 0.0f, "ry"_a = 0.0f, "rz"_a = 0.0f,
             "tr"_a = 1.0f, "tg"_a = 1.0f, "tb"_a = 1.0f,
             "blender_convention"_a = false,
             "Load env map. (rx,ry,rz) is the Blender Mapping XYZ Euler rotation; "
             "(tr,tg,tb) is the Background Color tint; blender_convention=True bakes "
             "the Astroray->Blender coord-swap into the rotation matrix. pkg63.")
        .def("eval_env_spectral", &PyRenderer::evalEnvSpectral, "direction"_a, "u"_a)
        .def("eval_env_rgb_upsample", &PyRenderer::evalEnvRGBUpsample, "direction"_a, "u"_a)
        .def("set_background_color", &PyRenderer::setBackgroundColor, "color"_a)
        .def("set_film_exposure", &PyRenderer::setFilmExposure, "exposure"_a)
        .def("set_use_transparent_film", &PyRenderer::setUseTransparentFilm, "use"_a)
        .def("set_transparent_glass", &PyRenderer::setTransparentGlass, "use"_a)
        .def("add_pass", &PyRenderer::addPass, "name"_a)
        .def("clear_passes", &PyRenderer::clearPasses)
        .def("render", &PyRenderer::render, "samples_per_pixel"_a, "max_depth"_a,
             "progress_callback"_a = py::none(), "apply_gamma"_a = true,
             "diffuse_bounces"_a = -1, "glossy_bounces"_a = -1, "transmission_bounces"_a = -1,
             "volume_bounces"_a = -1, "transparent_bounces"_a = -1, "skip_upload"_a = false)
        .def("get_albedo_buffer", &PyRenderer::getAlbedoBuffer)
        .def("get_normal_buffer", &PyRenderer::getNormalBuffer)
        .def("get_motion_buffer", &PyRenderer::getMotionBuffer)
        .def("get_alpha_buffer", &PyRenderer::getAlphaBuffer)
        .def("get_depth_buffer", &PyRenderer::getDepthBuffer)
        .def("get_position_buffer", &PyRenderer::getPositionBuffer)
        .def("get_uv_buffer", &PyRenderer::getUVBuffer)
        .def("get_object_index_buffer", &PyRenderer::getObjectIndexBuffer)
        .def("get_material_index_buffer", &PyRenderer::getMaterialIndexBuffer)
        .def("get_cryptomatte_object_buffer", &PyRenderer::getCryptomatteObjectBuffer)
        .def("get_cryptomatte_material_buffer", &PyRenderer::getCryptomatteMaterialBuffer)
        .def("write_cryptomatte_exr", &PyRenderer::writeCryptomatteEXR, "filepath"_a,
             "pkg87d: Write Cryptomatte EXR with Psyop §3 manifest headers")
        .def("get_render_pass_buffer", &PyRenderer::getRenderPassBuffer, "pass_name"_a)
        .def("clear", &PyRenderer::clear)
        .def("get_width", &PyRenderer::getWidth)
        .def("get_height", &PyRenderer::getHeight)
        .def("set_use_gpu", &PyRenderer::setUseGPU, "enable"_a)
        .def("prewarm_cuda", &PyRenderer::prewarmCUDA,
             "pkg84: Pre-warm CUDA kernel JIT by rendering 1 pixel of a trivial "
             "scene. Moves ~12s cold-start cost to addon load / viewport Rendered "
             "button click. No-op on CPU. Idempotent (guarded by addon).")
        // pkg56 Phase B — per-domain incremental scene uploaders. Mirrors
        // Cycles BlenderSync's geometry / shaders / lights / world split
        // (intern/cycles/blender/sync.cpp, Apache-2.0). Phase C wires the
        // addon-side bpy.types.Depsgraph.updates iteration to dispatch into
        // these instead of always paying the full re-upload cost.
        //
        // GIL: upload_geometry is the heavy one (BVH rebuild + bulk device
        // copy) and releases the GIL; upload_materials / upload_lights /
        // upload_environment / update_object_transform / upload_scene are
        // short and hold it (research note §8 risk 3).
        .def("upload_geometry", &PyRenderer::uploadGeometry,
             py::call_guard<py::gil_scoped_release>(),
             "pkg56 Phase B: rebuild the CPU BVH and push geometry buffers "
             "(BVH nodes, primitives, triangles, spheres, vertex normals) "
             "to the GPU. Materials, lights and environment device buffers "
             "are left untouched. Use after add_triangle / add_sphere edits "
             "or vertex-position changes. Cycles equivalent: "
             "GeometryManager::device_update.")
        .def("upload_materials", &PyRenderer::uploadMaterials,
             "pkg56 Phase B: push only the GMaterial flat array and "
             "spectral profile table to the GPU. Geometry, BVH, lights and "
             "environment device buffers are untouched. The most common "
             "user action (a material slider drag) maps to this single "
             "call. Cycles equivalent: ShaderManager::device_update / "
             "Shader::tag_update().")
        .def("upload_lights", &PyRenderer::uploadLights,
             "pkg56 Phase B: push only the light buffer + power CDF to "
             "the GPU. Geometry, materials and environment device buffers "
             "are untouched. Cycles equivalent: LightManager::device_update.")
        .def("upload_environment", &PyRenderer::uploadEnvironment,
             "pkg56 Phase B: push only environment-map data and sampling "
             "tables to the GPU (post-pkg63 also the MIS CDF). Geometry, "
             "materials and lights device buffers are untouched. Cycles "
             "equivalent: world_recalc → BackgroundManager::device_update.")
        .def("upload_scene", &PyRenderer::uploadScene,
             py::call_guard<py::gil_scoped_release>(),
             "pkg56 Phase B: thin sequenced wrapper over upload_environment "
             "+ upload_materials + upload_lights + upload_geometry. "
             "Behaviour matches the implicit upload that render() performs "
             "on its first call — exposed explicitly so Phase C's full-sync "
             "fallback (and current full-render callers) have a stable "
             "entry point. The four per-domain calls are guaranteed to "
             "produce the same final device state in any order.")
        .def("update_object_transform", &PyRenderer::updateObjectTransform,
             "object_id"_a, "transform_matrix"_a,
             "pkg56 Phase B: replace a scene primitive's transform in "
             "place. `object_id` is the 0-based insertion index into the "
             "scene (the order in which add_sphere / add_triangle / "
             "add_*_light / add_mesh were called). `transform_matrix` is "
             "16 floats, row-major 4x4 affine.\n\n"
             "Single-level BVH limitation (pkg56 spec §Key design "
             "decisions): a transform-only edit still rebuilds the whole "
             "BVH and re-uploads geometry buffers inside this binding "
             "today. The binding exists so Phase C can dispatch the "
             "Object-with-ID_RECALC_TRANSFORM-only branch correctly; the "
             "cost win waits on a future two-level acceleration structure. "
             "Cycles equivalent: ObjectManager::tag_update_modified_flag, "
             "intern/cycles/blender/object.cpp:246-249.")
        .def("update_instance_transform", &PyRenderer::updateInstanceTransform,
             "instance_id"_a, "transform_matrix"_a,
             "pkg114 inc 3d: replace a registered instance's object->world "
             "transform (16 floats, row-major 4x4) in place on the CPU. No "
             "geometry rebuild. Call upload_instance_transforms() after a batch "
             "to re-push only the TLAS to the GPU.")
        .def("upload_instance_transforms", &PyRenderer::uploadInstanceTransforms,
             py::call_guard<py::gil_scoped_release>(),
             "pkg114 inc 3d: TLAS-only re-upload — re-push d_instances + d_tlas "
             "from the current instance transforms, leaving all BLAS geometry on "
             "the device untouched (the cheap transform-only viewport-edit path).")
        .def("get_scene_stats", &PyRenderer::getSceneStats,
             "pkg56 Phase B: cheap CPU-side counters (objects, materials, "
             "BVH node count, lights, env_loaded) used by partial-state "
             "tests to assert that an upload_materials() / "
             "upload_lights() / upload_environment() call did not touch "
             "the geometry/BVH state.")
        .def("_gpu_profile_lookup", &PyRenderer::gpuProfileLookup,
             "profile_index"_a, "lambda_nm"_a,
             "Return device-side reflectance for an uploaded spectral profile slot.")
        .def("_gpu_rgb_upsample_batch", &PyRenderer::gpuRgbUpsampleBatch,
             "rgbs"_a, "lambdas"_a, "mode"_a,
             "pkg168 test probe: device RGB->spectral upsample. rgbs is flat "
             "3*nRgb, lambdas is nLambda; returns nRgb*nLambda floats rgb-major. "
             "mode: 1=ALBEDO, 2=ILLUMINANT.")
        .def("get_material_backend_capabilities",
             &PyRenderer::getMaterialBackendCapabilities, "material_id"_a)
        .def("get_material_closure_graph",
             &PyRenderer::getMaterialClosureGraph, "material_id"_a)
        .def_property_readonly("gpu_available",   &PyRenderer::getGPUAvailable)
        .def_property_readonly("gpu_device_name", &PyRenderer::getGPUDeviceName)
        .def("sample_texture", &PyRenderer::sampleTexture,
             "type"_a, "params"_a, "u"_a = 0.5f, "v"_a = 0.5f)
        .def("sample_named_texture", &PyRenderer::sampleNamedTexture,
             "name"_a, "u"_a = 0.5f, "v"_a = 0.5f,
             "pkg219b: sample a registered texture (image/procedural/program) at (u,v).")
        .def("eval_texture_at_3d", &PyRenderer::evalTextureAt3D,
             "type"_a, "params"_a, "x"_a, "y"_a, "z"_a,
             "pkg115 debug helper: evaluate texture at explicit (x,y,z) point")
        .def("set_integrator", &PyRenderer::setIntegrator, "name"_a)
        .def("get_integrator", &PyRenderer::getIntegrator,
             "pkg148: return the currently-selected integrator name. Defaults "
             "to 'path_tracer' on a fresh Renderer (and after clear() / "
             "set_integrator('auto'|'default'|'')) rather than an empty "
             "string, so the GPU dedicated-light NEE branch is always engaged.")
        .def("get_integrator_stats", &PyRenderer::getIntegratorStats,
             "Return optional diagnostic counters from the active integrator.")
        .def("set_integrator_param", &PyRenderer::setIntegratorParam,
             "key"_a, "value"_a,
             "Set an integer parameter passed to the integrator constructor.")
        .def("set_integrator_param_float", &PyRenderer::setIntegratorParamFloat,
             "key"_a, "value"_a,
             "Set a float parameter passed to the integrator constructor "
             "(read via ParamDict::getNumber, which accepts int or float).")
        .def("set_integrator_param_str", &PyRenderer::setIntegratorParamStr,
             "key"_a, "value"_a,
             "Set a string parameter passed to the integrator constructor.")
        // pkg39: multi-wavelength rendering
        .def("set_wavelength_range", &PyRenderer::setWavelengthRange,
             "lambda_min"_a, "lambda_max"_a,
             "Set wavelength band (nm) for the next set_integrator() call.")
        .def("set_output_mode", &PyRenderer::setOutputMode, "mode"_a,
             "Output mode: 'xyz' (visible) or 'luminance' (IR/UV).")
        .def("set_material_spectral_profile", &PyRenderer::setMaterialSpectralProfile,
             "material_id"_a, "profile_name"_a, "replace"_a = false,
             "Attach a spectral profile to a material. replace=False (default) is "
             "ExtendOnly (out-of-band only, pkg58 fallback); replace=True is "
             "Replace mode (authored SPD drives all wavelengths, pkg195 Stage C).")
        .def("clear_material_spectral_profile", &PyRenderer::clearMaterialSpectralProfile,
             "material_id"_a,
             "Remove the spectral profile from a material.");
    m.def("material_registry_names", []() {
        return astroray::MaterialRegistry::instance().names();
    });
    m.def("optical_glass_preset_names", []() {
        return astroray::opticalGlassPresetNames();
    });
    m.def("texture_registry_names", []() {
        return astroray::TextureRegistry::instance().names();
    });
    m.def("shape_registry_names", []() {
        return astroray::ShapeRegistry::instance().names();
    });
    m.def("integrator_registry_names", []() {
        return astroray::IntegratorRegistry::instance().names();
    });
    m.def("metric_registry_names", []() {
        return astroray::MetricRegistry::instance().names();
    });
    m.def("emission_registry_names", []() {
        return astroray::EmissionRegistry::instance().names();
    });

    // pkg168: CPU RGB→spectral upsampling probe — the host counterpart of
    // PyRenderer._gpu_rgb_upsample_batch, for the parity A/B in
    // tests/test_pkg168_upsampling_parity.py. `rgbs` is flat 3*nRgb, `lambdas`
    // is nLambda; returns nRgb*nLambda floats, rgb-major. mode: 1=ALBEDO
    // (RGBAlbedoSpectrum), 2=ILLUMINANT (RGBIlluminantSpectrum). These are the
    // exact per-wavelength scalars RGB*Spectrum::sample() fills each slot with.
    m.def("_cpu_rgb_upsample_batch",
          [](const std::vector<float>& rgbs, const std::vector<float>& lambdas,
             int mode) {
        int nRgb    = static_cast<int>(rgbs.size() / 3);
        int nLambda = static_cast<int>(lambdas.size());
        std::vector<float> out(static_cast<size_t>(nRgb) * nLambda, 0.f);
        for (int ri = 0; ri < nRgb; ++ri) {
            std::array<float, 3> rgb{ rgbs[ri * 3 + 0], rgbs[ri * 3 + 1],
                                      rgbs[ri * 3 + 2] };
            if (mode == 2) {
                astroray::RGBIlluminantSpectrum sp(rgb);
                for (int li = 0; li < nLambda; ++li)
                    out[ri * nLambda + li] = sp.evalAt(lambdas[li]);
            } else {
                astroray::RGBAlbedoSpectrum sp(rgb);
                for (int li = 0; li < nLambda; ++li)
                    out[ri * nLambda + li] = sp.evalAt(lambdas[li]);
            }
        }
        return out;
    }, "rgbs"_a, "lambdas"_a, "mode"_a,
       "pkg168 test probe: CPU RGB->spectral upsample (host mirror of "
       "_gpu_rgb_upsample_batch). mode: 1=ALBEDO, 2=ILLUMINANT.");

    // pkg106 Chunk A test helper — evaluate the analytic half-vector constraint
    // Jacobian (astroray::manifold::halfVectorConstraintJacobian) from pytest.
    // Each vector arg is a length-3 sequence. Returns a tuple:
    //   (residual_u, residual_v, j00, j01, j10, j11, valid).
    m.def("_mnee_half_vector_constraint",
          [](const std::array<float, 3>& x0, const std::array<float, 3>& x1,
             const std::array<float, 3>& x2, const std::array<float, 3>& n1,
             const std::array<float, 3>& dp_du, const std::array<float, 3>& dp_dv,
             const std::array<float, 3>& dn_du, const std::array<float, 3>& dn_dv,
             float eta, bool refraction) {
              auto V = [](const std::array<float, 3>& a) {
                  return Vec3(a[0], a[1], a[2]);
              };
              astroray::manifold::HalfVectorConstraint c =
                  astroray::manifold::halfVectorConstraintJacobian(
                      V(x0), V(x1), V(x2), V(n1), V(dp_du), V(dp_dv),
                      V(dn_du), V(dn_dv), eta, refraction);
              return py::make_tuple(c.residual.u, c.residual.v,
                                    c.j00, c.j01, c.j10, c.j11, c.valid);
          },
          "x0"_a, "x1"_a, "x2"_a, "n1"_a, "dp_du"_a, "dp_dv"_a,
          "dn_du"_a, "dn_dv"_a, "eta"_a, "refraction"_a);

    // pkg106 Chunk B test helpers ----------------------------------------------
    auto vtuple = [](const Vec3& v) { return py::make_tuple(v.x, v.y, v.z); };

    // Triangle (u,v) partials: returns (dp_du, dp_dv, dn_du, dn_dv) each a 3-tuple.
    m.def("_mnee_triangle_partials",
          [vtuple](const std::array<float, 3>& v0, const std::array<float, 3>& v1,
                   const std::array<float, 3>& v2) {
              auto V = [](const std::array<float, 3>& a) { return Vec3(a[0], a[1], a[2]); };
              Vec3 dpu, dpv, dnu, dnv;
              astroray::manifold::trianglePartials(V(v0), V(v1), V(v2), dpu, dpv, dnu, dnv);
              return py::make_tuple(vtuple(dpu), vtuple(dpv), vtuple(dnu), vtuple(dnv));
          },
          "v0"_a, "v1"_a, "v2"_a);

    // Sphere (u,v) partials at point p on a sphere(center, radius).
    m.def("_mnee_sphere_partials",
          [vtuple](const std::array<float, 3>& center, const std::array<float, 3>& p,
                   float radius) {
              auto V = [](const std::array<float, 3>& a) { return Vec3(a[0], a[1], a[2]); };
              Vec3 dpu, dpv, dnu, dnv;
              astroray::manifold::spherePartials(V(center), V(p), radius, dpu, dpv, dnu, dnv);
              return py::make_tuple(vtuple(dpu), vtuple(dpv), vtuple(dnu), vtuple(dnv));
          },
          "center"_a, "p"_a, "radius"_a);

    // Analytic-Jacobian manifold Newton on a FLAT refractor (constant normal +
    // partials; tangent step stays on the plane). Returns
    // (converged, iterations, residual_norm, x1_u, x1_v, x1_w).
    m.def("_mnee_newton_solve_flat",
          [](const std::array<float, 3>& x0, const std::array<float, 3>& x2,
             const std::array<float, 3>& n1, const std::array<float, 3>& dp_du,
             const std::array<float, 3>& dp_dv, const std::array<float, 3>& x1_init,
             float eta, bool refraction, int max_iter, float tol) {
              auto V = [](const std::array<float, 3>& a) { return Vec3(a[0], a[1], a[2]); };
              const Vec3 n = V(n1), dpu = V(dp_du), dpv = V(dp_dv);
              // Flat reprojection: stay on the plane, normal + partials constant.
              astroray::manifold::ReprojectFnAnalytic reproject =
                  [n, dpu, dpv](const Vec3& x1, const Vec3& s, const Vec3& t,
                                float du, float dv, Vec3& ox, Vec3& on,
                                Vec3& odpu, Vec3& odpv, Vec3& odnu, Vec3& odnv) {
                      ox = x1 + s * du + t * dv;
                      on = n; odpu = dpu; odpv = dpv;
                      odnu = Vec3(0.0f); odnv = Vec3(0.0f);
                      return true;
                  };
              astroray::manifold::NewtonConfig cfg;
              cfg.maxIterations = max_iter;
              cfg.tolerance = tol;
              astroray::manifold::AnalyticNewtonResult r =
                  astroray::manifold::solveAnalytic(
                      V(x0), V(x2), eta, refraction, V(x1_init), n,
                      dpu, dpv, Vec3(0.0f), Vec3(0.0f), reproject, cfg);
              return py::make_tuple(r.converged, r.iterations, r.residualNorm,
                                    r.x1.x, r.x1.y, r.x1.z);
          },
          "x0"_a, "x2"_a, "n1"_a, "dp_du"_a, "dp_dv"_a, "x1_init"_a,
          "eta"_a, "refraction"_a, "max_iter"_a = 20, "tol"_a = 1e-5f);

    // pkg106 Chunk C test helpers — multi-vertex manifold chain ----------------
    {
        namespace am = astroray::manifold;
        auto buildChain = [](const std::vector<std::array<float, 3>>& ps,
                             const std::vector<std::array<float, 3>>& ns,
                             const std::vector<std::array<float, 3>>& dpus,
                             const std::vector<std::array<float, 3>>& dpvs,
                             const std::vector<std::array<float, 3>>& dnus,
                             const std::vector<std::array<float, 3>>& dnvs,
                             const std::vector<float>& etas,
                             am::ChainVertex* v) {
            auto V = [](const std::array<float, 3>& a) { return Vec3(a[0], a[1], a[2]); };
            int N = static_cast<int>(ps.size());
            for (int i = 0; i < N; ++i) {
                v[i].p = V(ps[i]); v[i].n = V(ns[i]);
                v[i].dp_du = V(dpus[i]); v[i].dp_dv = V(dpvs[i]);
                v[i].dn_du = V(dnus[i]); v[i].dn_dv = V(dnvs[i]);
                v[i].eta = etas[i];
            }
            return N;
        };

        // Returns (ok, residual[2N], J_flat[(2N)^2]) for the FD Jacobian check.
        m.def("_mnee_chain_eval",
              [buildChain](const std::vector<std::array<float, 3>>& ps,
                           const std::vector<std::array<float, 3>>& ns,
                           const std::vector<std::array<float, 3>>& dpus,
                           const std::vector<std::array<float, 3>>& dpvs,
                           const std::vector<std::array<float, 3>>& dnus,
                           const std::vector<std::array<float, 3>>& dnvs,
                           const std::vector<float>& etas,
                           const std::array<float, 3>& x0,
                           const std::array<float, 3>& light, bool refraction) {
                  am::ChainVertex v[am::kMaxChainVertices];
                  int N = buildChain(ps, ns, dpus, dpvs, dnus, dnvs, etas, v);
                  int n2 = 2 * N;
                  std::vector<float> residual(n2, 0.f), J(static_cast<size_t>(n2) * n2, 0.f);
                  Vec3 s[am::kMaxChainVertices], t[am::kMaxChainVertices];
                  bool ok = am::chainEval(v, N, Vec3(x0[0], x0[1], x0[2]),
                                          Vec3(light[0], light[1], light[2]),
                                          refraction, residual.data(), J.data(), s, t);
                  return py::make_tuple(ok, residual, J);
              },
              "ps"_a, "ns"_a, "dp_dus"_a, "dp_dvs"_a, "dn_dus"_a, "dn_dvs"_a,
              "etas"_a, "x0"_a, "light"_a, "refraction"_a);

        // Damped block Newton on a FLAT chain (dn=0; tangent step stays on each
        // plane). Returns (converged, iterations, residual_norm, final_ps_flat[3N]).
        m.def("_mnee_chain_solve_flat",
              [buildChain](const std::vector<std::array<float, 3>>& ps,
                           const std::vector<std::array<float, 3>>& ns,
                           const std::vector<std::array<float, 3>>& dpus,
                           const std::vector<std::array<float, 3>>& dpvs,
                           const std::vector<float>& etas,
                           const std::array<float, 3>& x0,
                           const std::array<float, 3>& light, bool refraction,
                           int max_iter, float tol, float max_step) {
                  std::vector<std::array<float, 3>> z(ps.size(), {0.f, 0.f, 0.f});
                  am::ChainVertex v[am::kMaxChainVertices];
                  int N = buildChain(ps, ns, dpus, dpvs, z, z, etas, v);
                  am::ReprojectChainFn rp = [](int, const Vec3& s, const Vec3& t,
                                               float du, float dv, am::ChainVertex& vv) {
                      vv.p = vv.p + s * du + t * dv;  // flat: stay on the plane
                      return true;
                  };
                  am::NewtonConfig cfg;
                  cfg.maxIterations = max_iter;
                  cfg.tolerance = tol;
                  am::ChainResult r = am::solveChain(
                      v, N, Vec3(x0[0], x0[1], x0[2]),
                      Vec3(light[0], light[1], light[2]), refraction, rp, cfg, max_step);
                  std::vector<float> finalP;
                  for (int i = 0; i < N; ++i) { finalP.push_back(v[i].p.x); finalP.push_back(v[i].p.y); finalP.push_back(v[i].p.z); }
                  return py::make_tuple(r.converged, r.iterations, r.residualNorm, finalP);
              },
              "ps"_a, "ns"_a, "dp_dus"_a, "dp_dvs"_a, "etas"_a, "x0"_a, "light"_a,
              "refraction"_a, "max_iter"_a = 30, "tol"_a = 1e-5f, "max_step"_a = 0.3f);

        // pkg106 Chunk D — mesh seed-ray + chain solve on a triangulated caster.
        // tris is a flat list of 9 floats per triangle (v0,v1,v2). Returns
        // (n_vertices, converged, iterations, residual, final_ps_flat[3N]).
        m.def("_mnee_mesh_solve",
              [](const std::vector<std::array<float, 9>>& tris,
                 const std::array<float, 3>& x0, const std::array<float, 3>& light,
                 float ior, int max_iter, float tol, float max_step) {
                  std::vector<am::CausticTri> ctris(tris.size());
                  for (size_t i = 0; i < tris.size(); ++i) {
                      const auto& a = tris[i];
                      ctris[i].v0 = Vec3(a[0], a[1], a[2]);
                      ctris[i].v1 = Vec3(a[3], a[4], a[5]);
                      ctris[i].v2 = Vec3(a[6], a[7], a[8]);
                  }
                  const Vec3 X0(x0[0], x0[1], x0[2]);
                  const Vec3 L(light[0], light[1], light[2]);
                  am::ChainVertex v[am::kMaxChainVertices];
                  int N = am::seedChainFromRay(ctris.data(), (int)ctris.size(), X0, L,
                                               ior, v, am::kMaxChainVertices);
                  if (N == 0)
                      return py::make_tuple(0, false, 0, 0.0f, std::vector<float>{});
                  am::NewtonConfig cfg; cfg.maxIterations = max_iter; cfg.tolerance = tol;
                  am::ChainResult r = am::solveChain(v, N, X0, L, /*refraction=*/true,
                                                     am::makeFlatReproject(), cfg, max_step);
                  std::vector<float> fp;
                  for (int i = 0; i < N; ++i) { fp.push_back(v[i].p.x); fp.push_back(v[i].p.y); fp.push_back(v[i].p.z); }
                  return py::make_tuple(N, r.converged, r.iterations, r.residualNorm, fp);
              },
              "tris"_a, "x0"_a, "light"_a, "ior"_a,
              "max_iter"_a = 30, "tol"_a = 1e-5f, "max_step"_a = 0.3f);

        // pkg106 Chunk D (radiance) — MNEE generalized geometry term.
        // Builds a FLAT chain (dn=0) at the supplied (converged) vertices and
        // returns (dx1_dxlight, dh_dx). Used by test_mnee_geometry_term.py to
        // check the C++ transfer matrix vs a float64 finite-difference of the
        // re-solved manifold (Cycles mnee_compute_transfer_matrix l.663-731).
        m.def("_mnee_geometry_term",
              [buildChain](const std::vector<std::array<float, 3>>& ps,
                           const std::vector<std::array<float, 3>>& ns,
                           const std::vector<std::array<float, 3>>& dpus,
                           const std::vector<std::array<float, 3>>& dpvs,
                           const std::vector<float>& etas,
                           const std::array<float, 3>& x0,
                           const std::array<float, 3>& light,
                           const std::array<float, 3>& light_n,
                           bool light_fixed_dir,
                           const std::array<float, 3>& light_dir) {
                  std::vector<std::array<float, 3>> z(ps.size(), {0.f, 0.f, 0.f});
                  am::ChainVertex v[am::kMaxChainVertices];
                  int N = buildChain(ps, ns, dpus, dpvs, z, z, etas, v);
                  float dhdx = 0.0f;
                  float dx1 = am::chainGeometryTerm(
                      v, N, Vec3(x0[0], x0[1], x0[2]),
                      Vec3(light[0], light[1], light[2]),
                      Vec3(light_n[0], light_n[1], light_n[2]), &dhdx,
                      light_fixed_dir, Vec3(light_dir[0], light_dir[1], light_dir[2]));
                  return py::make_tuple(dx1, dhdx);
              },
              "ps"_a, "ns"_a, "dp_dus"_a, "dp_dvs"_a, "etas"_a, "x0"_a,
              "light"_a, "light_n"_a, "light_fixed_dir"_a = false,
              "light_dir"_a = std::array<float, 3>{0.f, 0.f, 0.f});
    }

    // pkg109 — photon-map kd-tree test bindings. Validate the balanced kd-tree
    // build + k-NN locate + Jensen density estimate against a numpy float64
    // brute-force oracle (tests/test_photon_map.py). Both functions build a
    // throwaway PhotonMap from the supplied points.
    m.def("_photon_map_knn_d2",
          [](const std::vector<std::array<float, 3>>& pts,
             const std::array<float, 3>& q, int k, float max_radius) {
              std::vector<astroray::photon::Photon> ph;
              ph.reserve(pts.size());
              for (const auto& p : pts) {
                  astroray::photon::Photon pt;
                  pt.position = Vec3(p[0], p[1], p[2]);
                  ph.push_back(pt);
              }
              astroray::photon::PhotonMap pm;
              pm.build(std::move(ph));
              std::vector<int> idx;
              std::vector<float> d2;
              pm.knn(Vec3(q[0], q[1], q[2]), k, max_radius, idx, d2);
              return d2;  // squared distances of the k nearest, sorted ascending
          },
          "points"_a, "query"_a, "k"_a, "max_radius"_a);

    m.def("_photon_map_irradiance",
          [](const std::vector<std::array<float, 3>>& pts,
             const std::vector<std::array<float, 3>>& powers,
             const std::array<float, 3>& q, int k, float max_radius) {
              std::vector<astroray::photon::Photon> ph;
              ph.reserve(pts.size());
              for (std::size_t i = 0; i < pts.size(); ++i) {
                  astroray::photon::Photon pt;
                  pt.position = Vec3(pts[i][0], pts[i][1], pts[i][2]);
                  if (i < powers.size())
                      pt.power = astroray::XYZ{powers[i][0], powers[i][1], powers[i][2]};
                  ph.push_back(pt);
              }
              astroray::photon::PhotonMap pm;
              pm.build(std::move(ph));
              astroray::XYZ E =
                  pm.estimateIrradiance(Vec3(q[0], q[1], q[2]), k, max_radius);
              return py::make_tuple(E.X, E.Y, E.Z);
          },
          "points"_a, "powers"_a, "query"_a, "k"_a, "max_radius"_a);

#ifdef ASTRORAY_CUDA_ENABLED
    // pkg113 Phase 1 — GPU photon STORE + query parity binding. Builds the
    // uniform spatial hash grid on the GPU from a fixed photon set, runs a
    // fixed-radius gather at each query point, and returns the per-query
    // (irradiance estimate, in-radius neighbor index set, in-radius count).
    // Validated against a numpy float64 brute-force oracle in
    // tests/test_gpu_photon_store.py (mirrors tests/test_photon_map.py for the
    // CPU kd-tree). STORE+QUERY only — no emission/bounce, no integrator wiring.
    m.def("_gpu_photon_store_query",
          [](const std::vector<std::array<float, 3>>& pts,
             const std::vector<std::array<float, 3>>& powers,
             const std::vector<std::array<float, 3>>& queries,
             float radius, int max_neighbors) {
              namespace pg = astroray::photon::gpu;
              std::vector<pg::GPhoton> photons;
              photons.reserve(pts.size());
              for (std::size_t i = 0; i < pts.size(); ++i) {
                  pg::GPhoton ph;
                  ph.position = GVec3(pts[i][0], pts[i][1], pts[i][2]);
                  if (i < powers.size())
                      ph.power = GVec3(powers[i][0], powers[i][1], powers[i][2]);
                  else
                      ph.power = GVec3(0.f);
                  ph.incidentDir = GVec3(0.f);
                  ph.lambda = 0.f;
                  photons.push_back(ph);
              }
              std::vector<GVec3> qs;
              qs.reserve(queries.size());
              for (const auto& q : queries) qs.push_back(GVec3(q[0], q[1], q[2]));

              auto res = pg::cuda_photon_store_query(photons, qs, radius,
                                                     max_neighbors);
              // Return one tuple per query:
              //   (irradiance[3], neighbor_indices[list], found_count)
              py::list out;
              for (const auto& r : res) {
                  py::list idx;
                  for (int v : r.neighborIdx) idx.append(v);
                  out.append(py::make_tuple(
                      py::make_tuple(r.irradiance.x, r.irradiance.y, r.irradiance.z),
                      idx, r.foundCount));
              }
              return out;
          },
          "points"_a, "powers"_a, "queries"_a, "radius"_a,
          "max_neighbors"_a = 256,
          "pkg113 Phase 1: build the GPU photon hash grid and gather at each "
          "query. Returns [(irradiance(3), neighbor_indices, found_count), ...].");

    // pkg114 increment 1 — two-level BVH (TLAS-over-BLAS) identity-passthrough
    // parity probe. Builds a single identity instance (one BLAS = the whole
    // uploaded scene, M = Minv = I, a 1-leaf TLAS) and, for every primary camera
    // ray, dual-traces gpu_tlas_hit(identity) against the single-level
    // gpu_bvh_hit. The identity case must reduce EXACTLY to single-level on
    // t / primId / materialId / frontFace / point, with at most a sub-ulp normal
    // drift (the no-op inverse-transpose renormalize). Touches no production
    // kernel. Validated by tests/test_tlas_blas_parity.py. See
    // .astroray_plan/docs/two-level-bvh-research.md.
    m.def("_gpu_tlas_identity_parity",
          [](PyRenderer& r, int width, int height) {
              auto cam = r.getCamera();
              if (!cam)
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              r.getRenderer().buildAcceleration();
              auto res = astroray::twolevel::cuda_tlas_identity_parity(
                  r.getRenderer(), *cam, width, height);
              py::dict d;
              d["total_rays"]       = res.totalRays;
              d["hit_disagree"]     = res.hitDisagree;
              d["field_mismatch"]   = res.fieldMismatch;
              d["max_t_delta"]      = res.maxTDelta;
              d["max_point_delta"]  = res.maxPointDelta;
              d["max_normal_delta"] = res.maxNormalDelta;
              return d;
          },
          "renderer"_a, "width"_a, "height"_a,
          "pkg114 inc 1: two-level BVH identity-passthrough parity probe. Returns "
          "dict(total_rays, hit_disagree, field_mismatch, max_t_delta, "
          "max_point_delta, max_normal_delta).");

    // pkg113 Phase 2 — GPU photon EMISSION + BOUNCE parity binding. Forward-
    // traces a batch of collimated-sun photons through a single glass sphere
    // (Snell + Schlick-Fresnel + enter/exit from the geometric-normal sign +
    // per-λ Sellmeier iorAt + TIR) and returns the surviving per-λ CIE-weighted
    // deposit set — the GPhotons Phase 1's store ingests. Validated against a
    // numpy float64 oracle (identical math, same jittered aperture lattice) by
    // tests/test_gpu_photon_emission.py with AGGREGATE energy/position bounds
    // (the flat-prism 2-face path stays CPU — see gpu_photon_emit.h).
    m.def("_gpu_photon_emit_sphere",
          [](const std::array<float, 3>& center, float radius,
             const std::array<float, 6>& sellmeier, float flat_ior,
             bool is_dispersive,
             const std::array<float, 3>& sun_dir,
             const std::array<float, 3>& aperture_center, float aperture_radius,
             float receiver_y, int aperture_n,
             float lambda_min, float lambda_max, int max_depth) {
              namespace pe = astroray::photon::gpu;
              pe::PhotonEmitSphereScene sc;
              sc.sphereCenter   = GVec3(center[0], center[1], center[2]);
              sc.sphereRadius   = radius;
              sc.dispersion     = GDispersion{sellmeier[0], sellmeier[1],
                                              sellmeier[2], sellmeier[3],
                                              sellmeier[4], sellmeier[5]};
              sc.flatIor        = flat_ior;
              sc.isDispersive   = is_dispersive;
              sc.sunDir         = GVec3(sun_dir[0], sun_dir[1], sun_dir[2]);
              sc.apertureCenter = GVec3(aperture_center[0], aperture_center[1],
                                        aperture_center[2]);
              sc.apertureRadius = aperture_radius;
              sc.receiverY      = receiver_y;
              sc.apertureN      = aperture_n;
              sc.lambdaMin      = lambda_min;
              sc.lambdaMax      = lambda_max;
              sc.maxDepth       = max_depth;

              auto deposits = pe::cuda_photon_emit_sphere(sc);
              // Return one tuple per surviving deposit:
              //   (position[3], power_xyz[3], lambda)
              py::list out;
              for (const auto& dpt : deposits) {
                  out.append(py::make_tuple(
                      py::make_tuple(dpt.position.x, dpt.position.y, dpt.position.z),
                      py::make_tuple(dpt.power.x, dpt.power.y, dpt.power.z),
                      dpt.lambda));
              }
              return out;
          },
          "center"_a, "radius"_a, "sellmeier"_a, "flat_ior"_a,
          "is_dispersive"_a, "sun_dir"_a, "aperture_center"_a,
          "aperture_radius"_a, "receiver_y"_a, "aperture_n"_a,
          "lambda_min"_a = 380.f, "lambda_max"_a = 720.f, "max_depth"_a = 12,
          "pkg113 Phase 2: forward-trace photons through a glass sphere and "
          "return the GPhoton deposit set [(position(3), power_xyz(3), lambda), ...].");
#endif

    m.def("synchrotron_thermal_emissivity",
          &astroray::synchrotron::jnuThermalI,
          "nu_hz"_a, "n_e_cm3"_a, "T_e_K"_a, "B_gauss"_a, "theta_B"_a,
          "Pandya 2016 thermal Stokes-I synchrotron emissivity.");
    m.def("synchrotron_powerlaw_emissivity",
          &astroray::synchrotron::jnuPowerLawI,
          "nu_hz"_a, "n_e_cm3"_a, "B_gauss"_a, "theta_B"_a,
          "p"_a, "gamma_min"_a, "gamma_max"_a,
          "Pandya 2016 power-law Stokes-I synchrotron emissivity.");
    m.def("synchrotron_powerlaw_absorptivity",
          &astroray::synchrotron::alphaPowerLawI,
          "nu_hz"_a, "n_e_cm3"_a, "B_gauss"_a, "theta_B"_a,
          "p"_a, "gamma_min"_a, "gamma_max"_a,
          "Pandya 2016 power-law Stokes-I synchrotron absorptivity.");
    m.def("synchrotron_cyclotron_frequency",
          &astroray::synchrotron::cyclotronFrequencyHz,
          "B_gauss"_a);
    m.def("synchrotron_jet_contains",
          [](py::dict params, const std::vector<float>& position) {
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              auto jet = astroray::EmissionRegistry::instance().create(
                  "synchrotron_jet", paramDictFromPyDict(params));
              return jet->contains(Vec3(position[0], position[1], position[2]));
          },
          "params"_a, "position"_a);
    m.def("synchrotron_jet_doppler_factor",
          [](py::dict params, const std::vector<float>& position,
             const std::vector<float>& photon_direction) {
              if (position.size() != 3 || photon_direction.size() != 3) {
                  throw std::runtime_error("position and photon_direction must have 3 values");
              }
              auto jet = astroray::EmissionRegistry::instance().create(
                  "synchrotron_jet", paramDictFromPyDict(params));
              return jet->dopplerFactor(Vec3(position[0], position[1], position[2]),
                                        Vec3(photon_direction[0], photon_direction[1], photon_direction[2]));
          },
          "params"_a, "position"_a, "photon_direction"_a);
    m.def("synchrotron_jet_sample_visible",
          [](py::dict params, const std::vector<float>& position,
             const std::vector<float>& photon_direction,
             float u, float path_length_cm) {
              if (position.size() != 3 || photon_direction.size() != 3) {
                  throw std::runtime_error("position and photon_direction must have 3 values");
              }
              auto jet = astroray::EmissionRegistry::instance().create(
                  "synchrotron_jet", paramDictFromPyDict(params));
              auto lambdas = astroray::SampledWavelengths::sampleUniform(u);
              auto values = jet->integrateSegment(
                  Vec3(position[0], position[1], position[2]),
                  Vec3(photon_direction[0], photon_direction[1], photon_direction[2]),
                  lambdas, path_length_cm);
              py::dict out;
              out["lambdas"] = std::vector<float>(lambdas.lambdas().begin(), lambdas.lambdas().end());
              out["values"] = std::vector<float>(values.values().begin(), values.values().end());
              return out;
          },
          "params"_a, "position"_a, "photon_direction"_a,
          "u"_a = 0.5f, "path_length_cm"_a = 1.0f);

    // pkg43 slim disk bindings (handle-based + caller-supplied lambdas API
    // per .astroray_plan/docs/pkg43-handoff-notes.md).
    py::class_<Emission, std::shared_ptr<Emission>>(m, "Emission");
    m.def("slim_disk_create",
          [](py::dict params) -> std::shared_ptr<Emission> {
              return astroray::EmissionRegistry::instance().create(
                  "slim_disk", paramDictFromPyDict(params));
          },
          "params"_a,
          "Create a slim disk emission object from parameters.");
    m.def("slim_disk_contains",
          [](std::shared_ptr<Emission> disk, const std::vector<float>& position) {
              if (!disk) throw std::runtime_error("slim_disk_contains requires a disk handle");
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              return disk->contains(Vec3(position[0], position[1], position[2]));
          },
          "disk"_a, "position"_a);
    m.def("slim_disk_temperature_at",
          [](std::shared_ptr<Emission> disk_ptr, double r_M) {
              auto disk = std::dynamic_pointer_cast<astroray::slimdisk::SlimDisk>(disk_ptr);
              if (!disk) throw std::runtime_error("slim_disk_temperature_at requires a SlimDisk");
              return disk->temperatureAt(r_M);
          },
          "disk"_a, "r_M"_a,
          "Return midplane temperature at radius r (in units of M).");
    m.def("slim_disk_emissivity",
          [](std::shared_ptr<Emission> disk, const std::vector<float>& position,
             const std::vector<float>& photon_direction,
             const std::vector<float>& lambdas_nm) {
              if (!disk) throw std::runtime_error("slim_disk_emissivity requires a disk handle");
              if (position.size() != 3 || photon_direction.size() != 3) {
                  throw std::runtime_error("position and photon_direction must have 3 values");
              }
              if (lambdas_nm.empty()) {
                  throw std::runtime_error("lambdas_nm must not be empty");
              }

              // Build SampledWavelengths from the provided wavelengths.
              std::array<float, astroray::kSpectrumSamples> lambda_arr;
              for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                  lambda_arr[i] = lambdas_nm[std::min<size_t>(i, lambdas_nm.size() - 1)];
              }
              auto lambdas = astroray::SampledWavelengths::fromLambdas(lambda_arr);

              auto values = disk->emissivity(
                  Vec3(position[0], position[1], position[2]),
                  Vec3(photon_direction[0], photon_direction[1], photon_direction[2]),
                  lambdas);

              py::dict out;
              out["lambdas"] = std::vector<float>(lambdas.lambdas().begin(), lambdas.lambdas().end());
              out["values"] = std::vector<float>(values.values().begin(), values.values().end());
              return out;
          },
          "disk"_a, "position"_a, "photon_direction"_a, "lambdas"_a,
          "Evaluate slim disk emissivity at given wavelengths.");

    // pkg44 ADAF bindings (follows pkg42/pkg43 pattern).
    m.def("adaf_density_at",
          [](py::dict params, const std::vector<float>& position) {
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              auto adaf = std::dynamic_pointer_cast<astroray::adaf::ADAF>(
                  astroray::EmissionRegistry::instance().create("adaf", paramDictFromPyDict(params)));
              if (!adaf) throw std::runtime_error("Failed to create ADAF");
              double r_M = std::sqrt(position[0]*position[0] + position[1]*position[1] + position[2]*position[2]);
              return adaf->densityAt(r_M);
          },
          "params"_a, "position"_a,
          "Return electron density at position (in cm^-3).");
    m.def("adaf_electron_temperature_at",
          [](py::dict params, const std::vector<float>& position) {
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              auto adaf = std::dynamic_pointer_cast<astroray::adaf::ADAF>(
                  astroray::EmissionRegistry::instance().create("adaf", paramDictFromPyDict(params)));
              if (!adaf) throw std::runtime_error("Failed to create ADAF");
              double r_M = std::sqrt(position[0]*position[0] + position[1]*position[1] + position[2]*position[2]);
              return adaf->electronTemperatureAt(r_M);
          },
          "params"_a, "position"_a,
          "Return electron temperature at position (in K).");
    m.def("adaf_ion_temperature_at",
          [](py::dict params, const std::vector<float>& position) {
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              auto adaf = std::dynamic_pointer_cast<astroray::adaf::ADAF>(
                  astroray::EmissionRegistry::instance().create("adaf", paramDictFromPyDict(params)));
              if (!adaf) throw std::runtime_error("Failed to create ADAF");
              double r_M = std::sqrt(position[0]*position[0] + position[1]*position[1] + position[2]*position[2]);
              return adaf->ionTemperatureAt(r_M);
          },
          "params"_a, "position"_a,
          "Return ion temperature at position (in K).");
    m.def("adaf_magnetic_field_at",
          [](py::dict params, const std::vector<float>& position) {
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              auto adaf = std::dynamic_pointer_cast<astroray::adaf::ADAF>(
                  astroray::EmissionRegistry::instance().create("adaf", paramDictFromPyDict(params)));
              if (!adaf) throw std::runtime_error("Failed to create ADAF");
              double r_M = std::sqrt(position[0]*position[0] + position[1]*position[1] + position[2]*position[2]);
              return adaf->magneticFieldAt(r_M);
          },
          "params"_a, "position"_a,
          "Return magnetic field at position (in Gauss).");
    m.def("adaf_contains",
          [](py::dict params, const std::vector<float>& position) {
              if (position.size() != 3) throw std::runtime_error("position must have 3 values");
              auto adaf = astroray::EmissionRegistry::instance().create(
                  "adaf", paramDictFromPyDict(params));
              return adaf->contains(Vec3(position[0], position[1], position[2]));
          },
          "params"_a, "position"_a,
          "Check if position is inside ADAF volume.");
    m.def("adaf_sample_visible",
          [](py::dict params, const std::vector<float>& position,
             const std::vector<float>& photon_direction,
             float lambda_min, float lambda_max) {
              if (position.size() != 3 || photon_direction.size() != 3) {
                  throw std::runtime_error("position and photon_direction must have 3 values");
              }
              auto adaf = astroray::EmissionRegistry::instance().create(
                  "adaf", paramDictFromPyDict(params));
              // Build SampledWavelengths uniformly in [lambda_min, lambda_max]
              std::array<float, astroray::kSpectrumSamples> lambda_arr;
              for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                  lambda_arr[i] = lambda_min + (lambda_max - lambda_min)
                                * float(i) / float(astroray::kSpectrumSamples - 1);
              }
              auto lambdas = astroray::SampledWavelengths::fromLambdas(lambda_arr);
              auto values = adaf->emissivity(
                  Vec3(position[0], position[1], position[2]),
                  Vec3(photon_direction[0], photon_direction[1], photon_direction[2]),
                  lambdas);
              py::dict out;
              out["lambdas"] = std::vector<float>(lambdas.lambdas().begin(), lambdas.lambdas().end());
              out["values"] = std::vector<float>(values.values().begin(), values.values().end());
              return out;
          },
          "params"_a, "position"_a, "photon_direction"_a,
          "lambda_min"_a, "lambda_max"_a,
          "Sample ADAF emissivity at visible wavelengths.");
    m.def("gaunt_factor_ff",
          &astroray::adaf::gauntFactorFF,
          "nu_hz"_a, "T_e_K"_a,
          "Karzas & Latter 1961 Gaunt factor for free-free emission.");
    m.def("bremsstrahlung_emissivity",
          &astroray::adaf::jnuBremsstrahlungI,
          "nu_hz"_a, "n_e_cm3"_a, "T_e_K"_a,
          "Thermal bremsstrahlung emissivity (Rybicki & Lightman 1979).");

    m.def("metric_isco_radius", [](const std::string& name, py::dict params) {
        auto metric = astroray::MetricRegistry::instance().create(name, metricParamsFromDict(params));
        return metric->isco_radius();
    }, "name"_a, "params"_a = py::dict(), "Return metric ISCO radius in units of M.");
    m.def("metric_photon_sphere_radius", [](const std::string& name, py::dict params, bool prograde) {
        auto metric = astroray::MetricRegistry::instance().create(name, metricParamsFromDict(params));
        return metric->photon_sphere_radius(prograde);
    }, "name"_a, "params"_a = py::dict(), "prograde"_a = true,
       "Return equatorial circular photon orbit radius in units of M.");
    m.def("metric_horizon_angular_velocity", [](const std::string& name, py::dict params) {
        auto metric = astroray::MetricRegistry::instance().create(name, metricParamsFromDict(params));
        return metric->horizon_angular_velocity();
    }, "name"_a, "params"_a = py::dict(),
       "Return frame-dragging angular velocity at the outer horizon.");
    m.def("metric_christoffel", [](const std::string& name, py::dict params,
                                   double t, double r, double theta, double phi) {
        auto metric = astroray::MetricRegistry::instance().create(name, metricParamsFromDict(params));
        float gamma[4][4][4];
        metric->christoffel(t, r, theta, phi, gamma);
        py::list out;
        for (int a = 0; a < 4; ++a) {
            py::list alpha;
            for (int b = 0; b < 4; ++b) {
                py::list beta;
                for (int c = 0; c < 4; ++c) beta.append(gamma[a][b][c]);
                alpha.append(beta);
            }
            out.append(alpha);
        }
        return out;
    }, "name"_a, "params"_a, "t"_a, "r"_a, "theta"_a, "phi"_a,
       "Return Christoffel symbols Gamma^alpha_mu_nu.");
    m.def("metric_inner_product", [](const std::string& name, py::dict params,
                                     double t, double r, double theta, double phi,
                                     const std::vector<float>& a,
                                     const std::vector<float>& b) {
        if (a.size() != 4 || b.size() != 4) {
            throw std::runtime_error("metric_inner_product expects two 4-vectors");
        }
        auto metric = astroray::MetricRegistry::instance().create(name, metricParamsFromDict(params));
        float va[4] = {a[0], a[1], a[2], a[3]};
        float vb[4] = {b[0], b[1], b[2], b[3]};
        return metric->inner_product(t, r, theta, phi, va, vb);
    }, "name"_a, "params"_a, "t"_a, "r"_a, "theta"_a, "phi"_a, "a"_a, "b"_a,
       "Return g_mu_nu a^mu b^nu.");
    m.def("integrator_capabilities", [](const std::string& name) {
        auto integrator = astroray::IntegratorRegistry::instance().create(name, astroray::ParamDict{});
        IntegratorCapabilities caps = integrator->capabilities();
        py::dict out;
        out["gpuSupported"] = caps.gpuSupported;
        out["gpuFallbackReason"] = caps.gpuFallbackReason;
        return out;
    }, "name"_a, "Return backend capability metadata for an integrator.");
    m.def("pass_registry_names", []() {
        return astroray::PassRegistry::instance().names();
    });

    // pkg70 — runtime probe for the OptiX denoiser. The Blender addon uses
    // this to decide whether to default to OptiX or OIDN on viewport.
    // Returns true only when (a) the build was compiled with OptiX support,
    // (b) the optix_denoiser pass is registered, and (c) a CUDA device is
    // visible at runtime. We don't actually create a denoiser here — that
    // would force a CUDA context init just to answer a Python query.
    m.def("gpu_optix_available", []() {
#if defined(ASTRORAY_OPTIX_ENABLED) && defined(ASTRORAY_CUDA_ENABLED)
        const auto names = astroray::PassRegistry::instance().names();
        bool registered = false;
        for (const auto& n : names) {
            if (n == "optix_denoiser") { registered = true; break; }
        }
        if (!registered) return false;
        // Cheap CUDA-visibility check — same probe getGPUAvailable() uses.
        try {
            CUDARenderer test;
            return test.isAvailable();
        } catch (...) {
            return false;
        }
#else
        return false;
#endif
    }, "Return True when the OptiX denoiser plugin is built in and a CUDA "
       "device is visible at runtime.");

    // pkg39: spectral profile database
    m.def("load_spectral_profiles", [](const std::string& path) {
        astroray::SpectralProfileDatabase::instance().load(path);
    }, "path"_a, "Load the ASPR profiles.bin database.");
    m.def("spectral_profile_names", []() {
        return astroray::SpectralProfileDatabase::instance().names();
    }, "Return names of all loaded spectral profiles (file + runtime).");
    // pkg195 Stage C: register (or overwrite) a runtime spectral profile from a
    // regular λ grid. Drawn / preset / baked-blackbody spectra register under
    // __blend__/<owner>/<node> names and then participate in everything existing
    // (material attach, emission MeasuredSPD, GPU profile-table upload). Returns
    // True on success (non-empty values, positive step).
    m.def("register_spectral_profile",
          [](const std::string& name, float lambda_min_nm, float lambda_step_nm,
             const std::vector<float>& values) -> bool {
        const auto* p = astroray::SpectralProfileDatabase::instance().registerProfile(
            name, lambda_min_nm, lambda_step_nm, values);
        return p != nullptr;
    }, "name"_a, "lambda_min_nm"_a, "lambda_step_nm"_a, "values"_a,
       "Register a runtime spectral profile sampled on a regular grid "
       "(lambda_min_nm + i*lambda_step_nm). Overwrites an existing runtime "
       "profile of the same name in place.");
    m.def("spectral_profile_reflectance", [](const std::string& name, float lambda_nm) -> float {
        const auto* p = astroray::SpectralProfileDatabase::instance().get(name);
        if (!p) return 0.0f;
        return p->reflectance(lambda_nm);
    }, "name"_a, "lambda_nm"_a, "Sample reflectance of a named profile at lambda_nm.");
    // pkg195 Stage B: (lambda_min_nm, lambda_max_nm, step_nm) for the named
    // profile, so the addon light panel can label the profile's actual range.
    // Returns (0, 0, 0) when the name is unknown.
    m.def("spectral_profile_range", [](const std::string& name) {
        const auto* p = astroray::SpectralProfileDatabase::instance().get(name);
        if (!p || !p->valid()) return py::make_tuple(0.0f, 0.0f, 0.0f);
        float lmin = p->lambdaMin();
        float step = p->lambdaStep();
        float lmax = lmin + step * static_cast<float>(p->count() - 1);
        return py::make_tuple(lmin, lmax, step);
    }, "name"_a, "Return (lambda_min_nm, lambda_max_nm, step_nm) for a named profile.");

    // -----------------------------------------------------------------
    // Pillar 2 spectral core (pkg10). Scaffolding types — not consumed
    // by the render loop yet; exposed so pytest can exercise them.
    // -----------------------------------------------------------------
    py::class_<astroray::XYZ>(m, "XYZ")
        .def(py::init<>())
        .def_readwrite("X", &astroray::XYZ::X)
        .def_readwrite("Y", &astroray::XYZ::Y)
        .def_readwrite("Z", &astroray::XYZ::Z)
        .def("as_tuple", [](const astroray::XYZ& v) {
            return py::make_tuple(v.X, v.Y, v.Z);
        });

    py::class_<astroray::SampledWavelengths>(m, "SampledWavelengths")
        .def(py::init<>())
        .def_static("sample_uniform",
                    &astroray::SampledWavelengths::sampleUniform,
                    "u"_a,
                    "lambda_min"_a = astroray::kLambdaMin,
                    "lambda_max"_a = astroray::kLambdaMax)
        // pkg206: luminance-weighted hero-wavelength importance sampler
        // (unbiased; per-lane logistic-density pdf). Exposed for the pkg206
        // CPU unit tests (pdf normalization / histogram chi-square / MC
        // unbiasedness); the render path wires it internally.
        .def_static("sample_importance",
                    &astroray::SampledWavelengths::sampleImportance,
                    "u"_a,
                    "lambda_min"_a = astroray::kLambdaMin,
                    "lambda_max"_a = astroray::kLambdaMax)
        .def("lambda_", &astroray::SampledWavelengths::lambda, "i"_a)
        .def("pdf",     &astroray::SampledWavelengths::pdf,    "i"_a)
        .def("lambdas", [](const astroray::SampledWavelengths& w) {
            return std::vector<float>(w.lambdas().begin(), w.lambdas().end());
        })
        .def("pdfs", [](const astroray::SampledWavelengths& w) {
            return std::vector<float>(w.pdfs().begin(), w.pdfs().end());
        })
        .def("terminate_secondary", &astroray::SampledWavelengths::terminateSecondary)
        .def("secondary_terminated", &astroray::SampledWavelengths::secondaryTerminated)
        // pkg67: redshift the carried wavelengths by g = ν_obs / ν_emit.
        .def("redshift", &astroray::SampledWavelengths::redshift, "g"_a);

    py::class_<astroray::SampledSpectrum>(m, "SampledSpectrum")
        .def(py::init<>())
        .def(py::init<float>(), "v"_a)
        .def(py::init([](const std::vector<float>& v) {
            if (v.size() != static_cast<std::size_t>(astroray::kSpectrumSamples)) {
                throw std::runtime_error(
                    "SampledSpectrum requires exactly "
                    + std::to_string(astroray::kSpectrumSamples) + " values");
            }
            std::array<float, astroray::kSpectrumSamples> a{};
            for (int i = 0; i < astroray::kSpectrumSamples; ++i) a[i] = v[i];
            return astroray::SampledSpectrum(a);
        }), "values"_a)
        .def("__getitem__", [](const astroray::SampledSpectrum& s, int i) {
            if (i < 0 || i >= astroray::kSpectrumSamples) throw py::index_error();
            return s[i];
        })
        .def("__setitem__", [](astroray::SampledSpectrum& s, int i, float v) {
            if (i < 0 || i >= astroray::kSpectrumSamples) throw py::index_error();
            s[i] = v;
        })
        .def("__len__", [](const astroray::SampledSpectrum&) { return astroray::kSpectrumSamples; })
        .def("values", [](const astroray::SampledSpectrum& s) {
            return std::vector<float>(s.values().begin(), s.values().end());
        })
        .def("sum",       &astroray::SampledSpectrum::sum)
        .def("average",   &astroray::SampledSpectrum::average)
        .def("max_value", &astroray::SampledSpectrum::maxValue)
        .def("min_value", &astroray::SampledSpectrum::minValue)
        .def("has_nan",   &astroray::SampledSpectrum::hasNaN)
        .def("is_zero",   &astroray::SampledSpectrum::isZero)
        .def("to_xyz",    &astroray::SampledSpectrum::toXYZ, "wavelengths"_a)
        .def(py::self + py::self)
        .def(py::self - py::self)
        .def(py::self * py::self)
        .def(py::self / py::self)
        .def(py::self * float())
        .def(py::self / float())
        .def(float() * py::self)
        .def(py::self == py::self);

    py::class_<astroray::RGBAlbedoSpectrum>(m, "RGBAlbedoSpectrum")
        .def(py::init<>())
        .def(py::init([](const std::array<float, 3>& rgb) {
            return astroray::RGBAlbedoSpectrum(rgb);
        }), "rgb"_a)
        .def("sample", &astroray::RGBAlbedoSpectrum::sample, "wavelengths"_a)
        .def("eval_at", &astroray::RGBAlbedoSpectrum::evalAt, "lambda"_a)
        .def("coeffs", [](const astroray::RGBAlbedoSpectrum& s) {
            auto c = s.coeffs();
            return std::vector<float>(c.begin(), c.end());
        });

    py::class_<astroray::RGBUnboundedSpectrum>(m, "RGBUnboundedSpectrum")
        .def(py::init<>())
        .def(py::init([](const std::array<float, 3>& rgb) {
            return astroray::RGBUnboundedSpectrum(rgb);
        }), "rgb"_a)
        .def("sample",  &astroray::RGBUnboundedSpectrum::sample,  "wavelengths"_a)
        .def("eval_at", &astroray::RGBUnboundedSpectrum::evalAt, "lambda"_a)
        .def_property_readonly("scale", &astroray::RGBUnboundedSpectrum::scale);

    py::class_<astroray::RGBIlluminantSpectrum>(m, "RGBIlluminantSpectrum")
        .def(py::init<>())
        .def(py::init([](const std::array<float, 3>& rgb) {
            return astroray::RGBIlluminantSpectrum(rgb);
        }), "rgb"_a)
        .def("sample",  &astroray::RGBIlluminantSpectrum::sample,  "wavelengths"_a)
        .def("eval_at", &astroray::RGBIlluminantSpectrum::evalAt, "lambda"_a)
        .def_property_readonly("scale", &astroray::RGBIlluminantSpectrum::scale);

    m.def("rgb_to_spectrum",
          [](const std::array<float, 3>& rgb,
             const std::vector<float>& wavelengths) {
              astroray::RGBAlbedoSpectrum rsp(rgb);
              std::vector<float> out;
              out.reserve(wavelengths.size());
              for (float lam : wavelengths) out.push_back(rsp.evalAt(lam));
              return out;
          },
          "rgb"_a, "wavelengths"_a,
          "Upsample an sRGB colour to reflectance samples at the given "
          "wavelengths via the Jakob-Hanika 2019 LUT.");

    m.def("sample_d65", &astroray::sampleD65, "lambda"_a);
    m.def("cie_cmf_1964_10deg", &astroray::cieCmf1964_10deg, "lambda"_a);
    m.def("spectrum_lut_path", &astroray::spectrumLutPath,
          "Absolute path of the Jakob-Hanika sRGB coefficient LUT in use.");

    m.attr("kSpectrumSamples") = astroray::kSpectrumSamples;
    m.attr("kLambdaMin")       = astroray::kLambdaMin;
    m.attr("kLambdaMax")       = astroray::kLambdaMax;

    // -----------------------------------------------------------------------
    // pkg20: ReSTIR reservoir test helper (Reservoir<float>).
    // Exposed only for unit testing; not part of the production API.
    // -----------------------------------------------------------------------
    struct FloatReservoir {
        astroray::restir::Reservoir<float, std::mt19937> res;
        std::mt19937 rng;
        explicit FloatReservoir(uint32_t seed = 42) : rng(seed) {}
        void   update(float x, float w)                           { res.update(x, w, rng); }
        void   merge(FloatReservoir& other, float target_pdf)     { res.merge(other.res, target_pdf, rng); }
        void   reset()                                            { res.reset(); }
        void   finalizeWeight(float p_hat)                        { res.finalizeWeight(p_hat); }
        float  wSum()   const { return res.w_sum; }
        int    M()      const { return res.M; }
        float  W()      const { return res.W; }
        float  y()      const { return res.y; }
    };

    py::class_<FloatReservoir>(m, "FloatReservoir",
            "Test helper: Reservoir<float> with an internal seeded RNG. "
            "Not for production use.")
        .def(py::init<uint32_t>(), "seed"_a = 42)
        .def("update",          &FloatReservoir::update,          "x"_a, "w"_a)
        .def("merge",           &FloatReservoir::merge,           "other"_a, "target_pdf"_a)
        .def("reset",           &FloatReservoir::reset)
        .def("finalize_weight", &FloatReservoir::finalizeWeight,  "p_hat"_a)
        .def_property_readonly("w_sum", &FloatReservoir::wSum)
        .def_property_readonly("M",     &FloatReservoir::M)
        .def_property_readonly("W",     &FloatReservoir::W)
        .def_property_readonly("y",     &FloatReservoir::y);

    // -----------------------------------------------------------------------
    // pkg21: ReSTIR light candidate test helper.
    // Exposed only for unit testing; not part of the production API.
    // -----------------------------------------------------------------------
    struct ReSTIRCandidateHelper {
        astroray::restir::ReSTIRCandidate c;

        ReSTIRCandidateHelper(
            std::array<float,3> pos, std::array<float,3> nrm,
            std::array<float,3> em, float pdf, float dist)
        {
            c.position  = Vec3(pos[0], pos[1], pos[2]);
            c.normal    = Vec3(nrm[0], nrm[1], nrm[2]);
            c.emission  = Vec3(em[0],  em[1],  em[2]);
            c.pdf       = pdf;
            c.distance  = dist;
        }

        bool isValid() const { return c.isValid(); }

        float targetLuminance(const astroray::SampledWavelengths& lambdas) const {
            return c.targetLuminance(lambdas);
        }

        float targetLuminanceRGB() const {
            return c.targetLuminanceRGB();
        }
    };

    py::class_<ReSTIRCandidateHelper>(m, "ReSTIRCandidateHelper",
            "Test helper: ReSTIRCandidate constructed from raw values. "
            "Not for production use.")
        .def(py::init<std::array<float,3>, std::array<float,3>,
                      std::array<float,3>, float, float>(),
             "position"_a, "normal"_a, "emission"_a, "pdf"_a, "distance"_a)
        .def("is_valid",             &ReSTIRCandidateHelper::isValid)
        .def("target_luminance",     &ReSTIRCandidateHelper::targetLuminance, "lambdas"_a)
        .def("target_luminance_rgb", &ReSTIRCandidateHelper::targetLuminanceRGB);

    // -----------------------------------------------------------------------
    // pkg23: ReSTIR frame-state test helper.
    // Exposed only for unit testing; not part of the production API.
    // -----------------------------------------------------------------------
    struct FrameStateHelper {
        astroray::restir::FrameState fs;

        void resize(int w, int h)  { fs.resize(w, h); }
        void advanceFrame()        { fs.advanceFrame(); }
        int  frameIndex()  const   { return fs.frameIndex; }
        int  width()       const   { return fs.current.width; }
        int  height()      const   { return fs.current.height; }
        bool inBounds(int x, int y) const { return fs.current.inBounds(x, y); }

        // Write test data into the previous buffer.
        void setPrevPixel(int x, int y,
                          float nx, float ny, float nz,
                          float depth, bool valid) {
            auto& h   = fs.previous.meta(x, y);
            h.normal  = Vec3(nx, ny, nz);
            h.depth   = depth;
            h.valid   = valid;
        }

        bool isTemporallyValid(int px, int py,
                               float nx, float ny, float nz, float depth,
                               float normalThresh = 0.9f,
                               float depthThresh  = 0.1f) const {
            return astroray::restir::isTemporallyValid(
                fs.previous, px, py, Vec3(nx, ny, nz), depth,
                normalThresh, depthThresh);
        }

        // Returns list of (x, y, valid) tuples.
        std::vector<std::tuple<int,int,bool>> selectNeighbors(
                int cx, int cy, int radius, int maxNeighbors, uint32_t seed) {
            std::mt19937 gen(seed);
            std::vector<astroray::restir::SpatialNeighbor> buf(maxNeighbors);
            int n = astroray::restir::selectSpatialNeighbors(
                cx, cy, width(), height(), radius, maxNeighbors, gen, buf.data());
            std::vector<std::tuple<int,int,bool>> out;
            out.reserve(n);
            for (int i = 0; i < n; ++i)
                out.emplace_back(buf[i].x, buf[i].y, buf[i].valid);
            return out;
        }
    };

    py::class_<FrameStateHelper>(m, "FrameStateHelper",
            "Test helper: ReSTIR FrameState with temporal/spatial utilities. "
            "Not for production use.")
        .def(py::init<>())
        .def("resize",          &FrameStateHelper::resize,          "width"_a, "height"_a)
        .def("advance_frame",   &FrameStateHelper::advanceFrame)
        .def("set_prev_pixel",  &FrameStateHelper::setPrevPixel,
             "x"_a, "y"_a, "nx"_a, "ny"_a, "nz"_a, "depth"_a, "valid"_a)
        .def("is_temporally_valid", &FrameStateHelper::isTemporallyValid,
             "px"_a, "py"_a, "nx"_a, "ny"_a, "nz"_a, "depth"_a,
             "normal_threshold"_a = 0.9f, "depth_threshold"_a = 0.1f)
        .def("select_neighbors", &FrameStateHelper::selectNeighbors,
             "cx"_a, "cy"_a, "radius"_a, "max_neighbors"_a, "seed"_a)
        .def_property_readonly("frame_index", &FrameStateHelper::frameIndex)
        .def_property_readonly("width",       &FrameStateHelper::width)
        .def_property_readonly("height",      &FrameStateHelper::height)
        .def("in_bounds", &FrameStateHelper::inBounds, "x"_a, "y"_a);

    // -----------------------------------------------------------------------
    // pkg56 Phase A: viewport-sync per-stage timing ring buffer.
    //
    // Pure measurement, no behaviour change. Python timers in
    // blender_addon/__init__.py wrap each stage of `_sync_viewport_scene`
    // and the render dispatch, push the elapsed ms via
    // `astroray.record_viewport_stage(stage, ms)`, and call
    // `astroray.viewport_perf_frame_complete()` once the frame finishes.
    // `astroray.viewport_perf_stats()` returns the rolling per-stage means
    // over the last N completed frames (default N=100). The render-stats
    // overlay reads it for live display.
    //
    // This is the "before" baseline number Phase C drives below 5 ms.
    // -----------------------------------------------------------------------
    m.def("record_viewport_stage",
          [](const std::string& stage, double ms) {
              int i = viewport_perf_stage_index(stage);
              if (i < 0) {
                  throw std::invalid_argument(
                      "record_viewport_stage: unknown stage '" + stage +
                      "'. Expected one of: geometry, materials, lights, "
                      "environment, render.");
              }
              auto& ring = g_viewport_perf_ring;
              std::lock_guard<std::mutex> g(ring.mtx);
              ring.current[static_cast<size_t>(i)] += ms;
          },
          "stage"_a, "ms"_a,
          "pkg56-A: accumulate elapsed ms into the in-flight frame's "
          "stage bucket. Stage must be one of: geometry, materials, "
          "lights, environment, render.");

    m.def("viewport_perf_frame_complete",
          []() {
              auto& ring = g_viewport_perf_ring;
              std::lock_guard<std::mutex> g(ring.mtx);
              ring.frames[ring.head] = ring.current;
              ring.current = {};
              ring.head = (ring.head + 1) % ViewportPerfRing::kCapacity;
              if (ring.size < ViewportPerfRing::kCapacity) ring.size++;
          },
          "pkg56-A: close the in-flight frame and push its per-stage "
          "totals into the ring buffer (capacity 100 frames).");

    m.def("viewport_perf_stats",
          []() {
              auto& ring = g_viewport_perf_ring;
              std::lock_guard<std::mutex> g(ring.mtx);
              py::dict out;
              std::array<double, ViewportPerfRing::kStages> sums{};
              for (size_t f = 0; f < ring.size; ++f) {
                  for (size_t s = 0; s < ViewportPerfRing::kStages; ++s) {
                      sums[s] += ring.frames[f][s];
                  }
              }
              double total = 0.0;
              for (size_t s = 0; s < ViewportPerfRing::kStages; ++s) {
                  double mean = (ring.size > 0)
                      ? sums[s] / static_cast<double>(ring.size)
                      : 0.0;
                  out[kViewportPerfStageNames[s]] = mean;
                  total += mean;
              }
              out["total"] = total;
              out["frames"] = static_cast<int>(ring.size);
              return out;
          },
          "pkg56-A: per-stage mean ms over the last N completed frames "
          "(N≤100). Returns dict with keys 'geometry', 'materials', "
          "'lights', 'environment', 'render', 'total', 'frames'.");

    // -----------------------------------------------------------------------
    // pkg55 Phase B' Session 2b: reference path tracers for CPU wavefront.
    // Exposed for trip-wire / equivalence tests. Not part of the production API.
    // -----------------------------------------------------------------------
    m.def("reference_pt_production_render",
          [](PyRenderer& r, int samples, int max_depth, uint64_t seed,
             bool record_snapshots) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }
              auto result = astroray::cpu_wavefront::reference_pt_production_render(
                  r.getRenderer(), *cam, samples, max_depth, seed, record_snapshots);
              // Return RGB buffer as numpy array (height, width, 3).
              py::array_t<float> arr({cam->height, cam->width, 3});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(result.rgb.begin(), result.rgb.end(), ptr);
              return arr;
          },
          "renderer"_a, "samples"_a, "max_depth"_a, "seed"_a,
          "record_snapshots"_a = false,
          "pkg55-B' Session 2b: production-side reference PT (tile-shared RNG). "
          "Trip-wire oracle for production drift. Lambertian-Cornell only.");

    m.def("reference_pt_wavefront_render",
          [](PyRenderer& r, int samples, int max_depth, uint64_t seed,
             bool record_snapshots) -> py::object {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }
              auto result = astroray::cpu_wavefront::reference_pt_wavefront_render(
                  r.getRenderer(), *cam, samples, max_depth, seed, record_snapshots);

              if (!record_snapshots) {
                  // Return RGB buffer only as numpy array (height, width, 3).
                  py::array_t<float> arr({cam->height, cam->width, 3});
                  auto buf = arr.request();
                  float* ptr = static_cast<float*>(buf.ptr);
                  std::copy(result.rgb.begin(), result.rgb.end(), ptr);
                  return py::object(std::move(arr));
              } else {
                  // Return dict with RGB and snapshots.
                  py::dict d;

                  // RGB image
                  py::array_t<float> rgb_arr({cam->height, cam->width, 3});
                  auto rgb_buf = rgb_arr.request();
                  float* rgb_ptr = static_cast<float*>(rgb_buf.ptr);
                  std::copy(result.rgb.begin(), result.rgb.end(), rgb_ptr);
                  d["rgb"] = rgb_arr;

                  // Snapshots as list of dicts
                  py::list snapshot_list;
                  for (const auto& snap : result.snapshots) {
                      py::dict snap_dict;
                      snap_dict["pixel_index"] = snap.pixel_index;
                      snap_dict["sample_index"] = snap.sample_index;
                      snap_dict["bounce"] = snap.bounce;
                      snap_dict["stage"] = static_cast<int>(snap.stage);

                      snap_dict["ray_origin"] = py::array_t<float>({3}, snap.ray_origin);
                      snap_dict["ray_direction"] = py::array_t<float>({3}, snap.ray_direction);
                      snap_dict["throughput"] = py::array_t<float>({4}, snap.throughput);
                      snap_dict["lambdas"] = py::array_t<float>({4}, snap.lambdas);

                      snap_dict["hit_valid"] = snap.hit_valid;
                      snap_dict["hit_t"] = snap.hit_t;
                      snap_dict["hit_point"] = py::array_t<float>({3}, snap.hit_point);
                      snap_dict["hit_normal"] = py::array_t<float>({3}, snap.hit_normal);
                      snap_dict["hit_material_id"] = snap.hit_material_id;

                      snap_dict["bsdf_pdf"] = snap.bsdf_pdf;
                      snap_dict["bsdf_is_delta"] = snap.bsdf_is_delta;

                      snap_dict["nee_contribution"] = py::array_t<float>({4}, snap.nee_contribution);
                      snap_dict["nee_light_pdf"] = snap.nee_light_pdf;
                      snap_dict["nee_bsdf_pdf_at_dir"] = snap.nee_bsdf_pdf_at_dir;
                      snap_dict["nee_mis_weight"] = snap.nee_mis_weight;

                      snap_dict["rr_prob"] = snap.rr_prob;
                      snap_dict["rr_survived"] = snap.rr_survived;

                      snapshot_list.append(snap_dict);
                  }
                  d["snapshots"] = snapshot_list;

                  return py::object(std::move(d));
              }
          },
          "renderer"_a, "samples"_a, "max_depth"_a, "seed"_a,
          "record_snapshots"_a = false,
          "pkg55-B' Session 2b/N+3: wavefront-side reference PT (per-path RNG). "
          "Diff oracle for CPU wavefront. Returns RGB array if record_snapshots=False, "
          "or dict with 'rgb' and 'snapshots' if record_snapshots=True. Lambertian-Cornell only.");

    m.def("cpu_wavefront_render",
          [](PyRenderer& r, int samples, int max_depth, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }
              auto rgb = astroray::cpu_wavefront::cpu_wavefront_render(
                  r.getRenderer(), *cam, samples, max_depth, seed, nullptr);
              // Return RGB buffer as numpy array (height, width, 3).
              py::array_t<float> arr({cam->height, cam->width, 3});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(rgb.begin(), rgb.end(), ptr);
              return arr;
          },
          "renderer"_a, "samples"_a, "max_depth"_a, "seed"_a,
          "pkg55-B' Session 2c: CPU wavefront skeleton (SoA stages). "
          "Callable driver, not a registered plugin. Lambertian-Cornell only.");

    m.def("cpu_wavefront_snapshot_diff",
          [](PyRenderer& r, int samples, int max_depth, uint64_t seed) -> py::dict {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }

              // Render reference with snapshots.
              auto ref_result = astroray::cpu_wavefront::reference_pt_wavefront_render(
                  r.getRenderer(), *cam, samples, max_depth, seed, true);

              // Render wavefront with snapshots.
              astroray::cpu_wavefront::VectorSink wf_sink;
              auto wf_rgb = astroray::cpu_wavefront::cpu_wavefront_render(
                  r.getRenderer(), *cam, samples, max_depth, seed, &wf_sink);

              // Compare snapshot streams.
              auto diff = astroray::cpu_wavefront::compare_snapshot_streams(
                  ref_result.snapshots, wf_sink.snapshots(), 0.0f);

              // Package results.
              py::dict result;
              result["bit_identical"] = diff.bit_identical;
              result["max_abs_diff"] = diff.max_abs_diff;
              result["total_diverging_fields"] = diff.total_diverging_fields;
              result["report"] = astroray::cpu_wavefront::format_diff_report(diff);

              // Return RGB images for sanity check.
              py::array_t<float> ref_arr({cam->height, cam->width, 3});
              auto ref_buf = ref_arr.request();
              float* ref_ptr = static_cast<float*>(ref_buf.ptr);
              std::copy(ref_result.rgb.begin(), ref_result.rgb.end(), ref_ptr);
              result["ref_image"] = ref_arr;

              py::array_t<float> wf_arr({cam->height, cam->width, 3});
              auto wf_buf = wf_arr.request();
              float* wf_ptr = static_cast<float*>(wf_buf.ptr);
              std::copy(wf_rgb.begin(), wf_rgb.end(), wf_ptr);
              result["wf_image"] = wf_arr;

              return result;
          },
          "renderer"_a, "samples"_a, "max_depth"_a, "seed"_a,
          "pkg55-B' Session 2c: Compare snapshot streams for bit-identity gate. "
          "Returns dict with: bit_identical (bool), max_abs_diff (float), "
          "total_diverging_fields (int), report (str), ref_image (array), wf_image (array).");

#ifdef ASTRORAY_WAVEFRONT_CUDA_N3
    // pkg55-B' Session N+3: GPU wavefront PostInit snapshot for CPU↔GPU diff harness.
    m.def("cuda_wavefront_snapshot_post_init",
          [](PyRenderer& r, int width, int height, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }

              // Run GPU stage_init and download PostInit snapshot.
              // Returns flat array: (num_paths, 22) with fields per path:
              //   [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: lambdas,
              //   [10..13]: throughput, [14..16]: pixel/sample/bounce,
              //   [17..21]: rng (pixel, sample, dimension, seed_lo, seed_hi).
              auto snapshot = astroray::wavefront::cuda_wavefront_snapshot_post_init(
                  *cam, width, height, seed);

              int total_paths = width * height;
              py::array_t<float> arr({total_paths, 22});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(snapshot.begin(), snapshot.end(), ptr);
              return arr;
          },
          "renderer"_a, "width"_a, "height"_a, "seed"_a,
          "pkg55-B' Session N+3: Run GPU stage_init and download PostInit snapshot. "
          "Returns (num_paths, 22) array for CPU↔GPU diff harness. "
          "Fields: ray_origin (3), ray_direction (3), lambdas (4), throughput (4), "
          "pixel_index, sample_index, bounce, rng state (5).");

    // pkg55-B' Session N+3 part 2: GPU wavefront PostIntersect snapshot for CPU↔GPU diff harness.
    m.def("cuda_wavefront_snapshot_post_intersect",
          [](PyRenderer& r, int width, int height, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }

              // Run GPU stage_init + stage_intersect and download PostIntersect snapshot.
              // Returns flat array: (num_paths, 23) with fields per path:
              //   [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: lambdas,
              //   [10..13]: throughput, [14]: hit_valid, [15]: hit_t,
              //   [16..18]: hit_point, [19..21]: hit_normal, [22]: hit_material_id.
              auto snapshot = astroray::wavefront::cuda_wavefront_snapshot_post_intersect(
                  r.getRenderer(), *cam, width, height, seed);

              int total_paths = width * height;
              py::array_t<float> arr({total_paths, 23});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(snapshot.begin(), snapshot.end(), ptr);
              return arr;
          },
          "renderer"_a, "width"_a, "height"_a, "seed"_a,
          "pkg55-B' Session N+3 part 2: Run GPU stage_init + stage_intersect and download PostIntersect snapshot. "
          "Returns (num_paths, 23) array for CPU↔GPU diff harness. "
          "Fields: ray_origin (3), ray_direction (3), lambdas (4), throughput (4), "
          "hit_valid, hit_t, hit_point (3), hit_normal (3), hit_material_id.");

    // pkg55-B' Session N+3 part 2: GPU wavefront PostShade snapshot for CPU↔GPU diff harness.
    m.def("cuda_wavefront_snapshot_post_shade",
          [](PyRenderer& r, int width, int height, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }

              // Run GPU stage_init + stage_intersect + stage_shade_lambertian and download PostShade snapshot.
              // Returns flat array: (num_paths, 16) with fields per path:
              //   [0..2]: ray_origin (next bounce), [3..5]: ray_direction (next bounce),
              //   [6..9]: throughput (updated), [10..13]: lambdas,
              //   [14]: bsdf_pdf, [15]: bsdf_is_delta.
              auto snapshot = astroray::wavefront::cuda_wavefront_snapshot_post_shade(
                  r.getRenderer(), *cam, width, height, seed);

              int total_paths = width * height;
              py::array_t<float> arr({total_paths, 16});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(snapshot.begin(), snapshot.end(), ptr);
              return arr;
          },
          "renderer"_a, "width"_a, "height"_a, "seed"_a,
          "pkg55-B' Session N+3 part 2: Run GPU stage_init + stage_intersect + stage_shade_lambertian and download PostShade snapshot. "
          "Returns (num_paths, 16) array for CPU↔GPU diff harness. "
          "Fields: ray_origin (3), ray_direction (3), throughput (4), lambdas (4), "
          "bsdf_pdf, bsdf_is_delta.");

    // pkg55-B' Session N+4: GPU wavefront PostLightSample snapshot for CPU↔GPU diff harness.
    m.def("cuda_wavefront_snapshot_post_light_sample",
          [](PyRenderer& r, int width, int height, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }

              // Run GPU stage_init + stage_intersect + stage_shade_lambertian + stage_light_sample
              // and download PostLightSample snapshot.
              // Returns flat array: (num_paths, 21) with fields per path:
              //   [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: throughput,
              //   [10..13]: lambdas, [14..17]: nee_contribution (TODO),
              //   [18]: nee_light_pdf (TODO), [19]: nee_bsdf_pdf_at_dir (TODO),
              //   [20]: nee_mis_weight (TODO).
              auto snapshot = astroray::wavefront::cuda_wavefront_snapshot_post_light_sample(
                  r.getRenderer(), *cam, width, height, seed);

              int total_paths = width * height;
              py::array_t<float> arr({total_paths, 21});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(snapshot.begin(), snapshot.end(), ptr);
              return arr;
          },
          "renderer"_a, "width"_a, "height"_a, "seed"_a,
          "pkg55-B' Session N+4: Run GPU stage_init + stage_intersect + stage_shade_lambertian + stage_light_sample and download PostLightSample snapshot. "
          "Returns (num_paths, 21) array for CPU↔GPU diff harness. "
          "Fields: ray_origin (3), ray_direction (3), throughput (4), lambdas (4), "
          "nee_contribution (4), nee_light_pdf, nee_bsdf_pdf_at_dir, nee_mis_weight.");

    // pkg55-B' Session N+4: GPU wavefront PostRR snapshot for CPU↔GPU diff harness.
    m.def("cuda_wavefront_snapshot_post_rr",
          [](PyRenderer& r, int width, int height, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }

              // Run GPU stage_init + stage_intersect + stage_shade_lambertian + stage_light_sample + stage_russian_roulette
              // and download PostRR snapshot.
              // Returns flat array: (num_paths, 16) with fields per path:
              //   [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: throughput (scaled),
              //   [10..13]: lambdas, [14]: rr_prob (TODO), [15]: rr_survived (TODO).
              auto snapshot = astroray::wavefront::cuda_wavefront_snapshot_post_rr(
                  r.getRenderer(), *cam, width, height, seed);

              int total_paths = width * height;
              py::array_t<float> arr({total_paths, 16});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(snapshot.begin(), snapshot.end(), ptr);
              return arr;
          },
          "renderer"_a, "width"_a, "height"_a, "seed"_a,
          "pkg55-B' Session N+4: Run GPU stage_init + stage_intersect + stage_shade_lambertian + stage_light_sample + stage_russian_roulette and download PostRR snapshot. "
          "Returns (num_paths, 16) array for CPU↔GPU diff harness. "
          "Fields: ray_origin (3), ray_direction (3), throughput (4), lambdas (4), "
          "rr_prob, rr_survived.");

    m.def("cuda_wavefront_snapshot_post_nee_mis",
          [](PyRenderer& r, int width, int height, uint64_t seed) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }
              // pkg55-C2: run stage_init + the PRODUCTION intersect+shade
              // (deferred NEE parking) for one bounce and download the
              // shade-time MIS pdfs (path_light_pdf, path_mis_pdf, path_mis_weight).
              auto snapshot = astroray::wavefront::cuda_wavefront_snapshot_post_nee_mis(
                  r.getRenderer(), *cam, width, height, seed);

              int total_paths = width * height;
              py::array_t<float> arr({total_paths, 3});
              auto buf = arr.request();
              float* ptr = static_cast<float*>(buf.ptr);
              std::copy(snapshot.begin(), snapshot.end(), ptr);
              return arr;
          },
          "renderer"_a, "width"_a, "height"_a, "seed"_a,
          "pkg55-C2 MIS audit: run GPU stage_init + production intersect+shade "
          "(deferred NEE) and download the shade-time MIS pdfs. Returns "
          "(num_paths, 3): [path_light_pdf, path_mis_pdf, path_mis_weight]. "
          "path_light_pdf==0 marks a slot where no NEE fired.");

    m.def("cuda_wavefront_render",
          [](PyRenderer& r, int samples, int max_depth, uint64_t seed,
             float lambda_min = 380.0f, float lambda_max = 780.0f,
             bool use_luminance_output = false, bool enable_nee = true) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }
              int width = cam->width;
              int height = cam->height;
              auto rgb = astroray::wavefront::cuda_wavefront_render(
                  r.getRenderer(), *cam, width, height, samples, max_depth, seed,
                  lambda_min, lambda_max, use_luminance_output, enable_nee);
              py::array_t<float> arr({height, width, 3});
              auto buf = arr.request();
              std::copy(rgb.begin(), rgb.end(), static_cast<float*>(buf.ptr));
              return arr;
          },
          "renderer"_a, "samples"_a, "max_depth"_a, "seed"_a,
          "lambda_min"_a = 380.0f, "lambda_max"_a = 780.0f,
          "use_luminance_output"_a = false, "enable_nee"_a = true,
          "pkg55-C3: end-to-end GPU wavefront render with spectral-band control. "
          "Returns (height, width, 3) linear-sRGB image. lambda_min/max control "
          "the spectral sampling band; use_luminance_output selects luminance-avg RR "
          "and Rayleigh sky for non-visible bands; enable_nee gates NEE sampling "
          "(false = naive multiwavelength mode).");
#endif  // ASTRORAY_WAVEFRONT_CUDA_N3

    m.def("viewport_perf_reset",
          []() {
              auto& ring = g_viewport_perf_ring;
              std::lock_guard<std::mutex> g(ring.mtx);
              ring.frames = {};
              ring.current = {};
              ring.head = 0;
              ring.size = 0;
          },
          "pkg56-A: clear the viewport perf ring buffer and "
          "in-flight accumulator.");

    // pkg64-gpu Phase 1 probe helper — builds the BK7-sphere SMS acceptance
    // scene (mirroring test_sms_caustic_validation.py geometry) for the
    // device probe harness to run against.
    m.def("build_bk7_sms_acceptance_scene", [](PyRenderer& r) {
        // Floor quad (two triangles) with lambertian grey.
        py::dict floor_params;
        auto floor = r.createMaterial("lambertian",
            std::vector<float>{0.78f, 0.78f, 0.78f},
            floor_params);
        r.addTriangle(
            std::vector<float>{-2.4f, -1.2f, -2.2f},
            std::vector<float>{ 2.4f, -1.2f, -2.2f},
            std::vector<float>{ 2.4f, -1.2f,  1.6f},
            floor);
        r.addTriangle(
            std::vector<float>{-2.4f, -1.2f, -2.2f},
            std::vector<float>{ 2.4f, -1.2f,  1.6f},
            std::vector<float>{-2.4f, -1.2f,  1.6f},
            floor);
        // Point light (sphere).
        py::dict light_params;
        light_params["intensity"] = 14.0f;
        auto light = r.createMaterial("light",
            std::vector<float>{1.0f, 1.0f, 1.0f},
            light_params);
        r.addSphere(std::vector<float>{0.0f, 1.6f, 1.0f}, 0.22f, light);
        // BK7 glass sphere (the caster).
        py::dict glass_params;
        glass_params["ior"] = 1.52f;
        auto glass = r.createMaterial("dielectric",
            std::vector<float>{1.0f, 1.0f, 1.0f},
            glass_params);
        r.addSphere(std::vector<float>{0.0f, -0.4f, 0.15f}, 0.7f, glass);
        // Camera.
        r.setupCamera(
            std::vector<float>{0.0f, 0.0f, 4.2f},
            std::vector<float>{0.0f, -0.05f, 0.0f},
            std::vector<float>{0.0f, 1.0f, 0.0f},
            38.0f, 64.0f / 64.0f, 0.0f, 4.2f, 64, 64);
        r.setBackgroundColor(std::vector<float>{0.01f, 0.012f, 0.018f});
    }, "renderer"_a,
    "pkg64-gpu Phase 1 probe: build the BK7-sphere SMS acceptance scene "
    "(mirroring test_sms_caustic_validation.py). Caller must flag the BK7 "
    "sphere as a caustic caster (r.set_object_caustic_caster(r.scene_object_count()-1, True)) "
    "before calling uploadScene + render with ASTRORAY_PKG64_GPU_SMS_PROBE set.");

    m.attr("__version__") = "3.0.0";
#ifndef ASTRORAY_BUILD_ID
#  define ASTRORAY_BUILD_ID "dev"
#endif
    m.attr("__build__") = ASTRORAY_BUILD_ID;
    m.attr("__features__") = py::dict(
        "nee"_a=true, "mis"_a=true, "disney_brdf"_a=true, "sah_bvh"_a=true,
        "adaptive_sampling"_a=true, "volumes"_a=true, "textures"_a=true, "subsurface"_a=true,
        "gr_black_holes"_a=true,
        "spectral_gpu_materials"_a=true,
#ifdef ASTRORAY_OIDN_ENABLED
        "oidn_denoiser"_a=true,
#else
        "oidn_denoiser"_a=false,
#endif
#ifdef ASTRORAY_OPTIX_ENABLED
        "optix_denoiser"_a=true,
#else
        "optix_denoiser"_a=false,
#endif
#ifdef ASTRORAY_CUDA_ENABLED
        "cuda"_a=true,
#else
        "cuda"_a=false,
#endif
#ifdef ASTRORAY_WAVEFRONT_CUDA_N3
        "wavefront_cuda"_a=true,
#else
        "wavefront_cuda"_a=false,
#endif
        // pkg147: whether this .pyd was compiled with OpenMP linked in.
        // blender_addon's _check_build_integrity() refuses to register when
        // true — see CMakeLists.txt's ASTRORAY_OPENMP_ENABLED comment for the
        // GIL-deadlock mechanism this guards against.
#ifdef ASTRORAY_OPENMP_ENABLED
        "openmp"_a=true
#else
        "openmp"_a=false
#endif
    );

    // pkg186 — backend-aware capability truth for the GPU (CUDA/wavefront)
    // render path. `__features__` above advertises what the build supports on
    // ANY backend (it is what the addon Diagnostics/Preferences panels display),
    // but the addon defaults to GPU and several of those capabilities are
    // CPU-only there — the GPU path silently flattens (procedural) textures,
    // has no adaptive sampler, and has no GR black-hole kernels. (World-volume
    // absorption is NO LONGER dropped: pkg199 Stage 1 renders the homogeneous
    // world volume on the GPU wavefront at CPU parity — volumes flips true.)
    // Advertising
    // them `true` verbatim told the user "textures: yes" while the active GPU
    // backend dropped them (the pkg171 silent-lie class, applied to the feature
    // dict instead of the integrator). This companion dict reports per-capability
    // truth for the GPU backend; the panels cross-reference it and label any
    // capability that is on in `__features__` but off here as "CPU only". The
    // keys mirror `__features__`; a capability absent here inherits its
    // `__features__` value (treated as backend-agnostic).
    //
    // textures: FALSE — the pkg186 image-texture slice makes image textures
    // render on GPU, but procedural texture nodes still flatten to base albedo,
    // so full GPU texture parity is NOT reached; the flag stays false until the
    // procedural follow-up closes the gap (spec: "until this package closes the
    // gap"). Honest under-claim beats the prior silent over-claim.
    m.attr("__gpu_features__") = py::dict(
        "nee"_a=true, "mis"_a=true, "disney_brdf"_a=true, "sah_bvh"_a=true,
        "adaptive_sampling"_a=false,   // CPU-only sampler
        // pkg199 Stage 1: the GPU wavefront now renders the HOMOGENEOUS WORLD
        // VOLUME (Beer-Lambert absorption) at parity with the CPU spectral
        // tracer — set_world_volume fog darkens/desaturates with distance on GPU
        // exactly as on CPU. Scope is deliberately homogeneous-world-absorption
        // ONLY: no in-scatter/HG phase (worldVolumeAnisotropy inert — Stage 2),
        // no heterogeneous/object volumes, no add_volume scattering. The bool
        // reflects "the GPU backend supports the world-volume capability at CPU
        // parity", which Stage 1 delivers; the Stage-2 scattering work is a
        // separate future capability, not a gap within this one.
        "volumes"_a=true,
        "textures"_a=false,            // see note above (image slice partial)
        "subsurface"_a=true,           // GPU closure-graph diffuse SSS mix
        "gr_black_holes"_a=false,      // CPU-only GR integrators
        "spectral_gpu_materials"_a=true
    );

    // pkg87a — Cryptomatte infrastructure bindings
    m.def("crypto_hash_name", &crypto_hash_name, "name"_a,
          "Hash a name string to a Cryptomatte float ID (MurmurHash3 seed 0 + hash_to_float)");
    m.def("crypto_insert",
          [](py::list ranks, int depth, float id, float weight) {
              // Convert Python list to C array for mutation
              if (ranks.size() != static_cast<size_t>(depth * 2)) {
                  throw std::runtime_error("ranks list must have length depth*2");
              }
              std::vector<float> buffer(depth * 2);
              for (size_t i = 0; i < buffer.size(); ++i) {
                  buffer[i] = ranks[i].cast<float>();
              }
              crypto_insert(buffer.data(), depth, id, weight);
              // Write back to Python list
              for (size_t i = 0; i < buffer.size(); ++i) {
                  ranks[i] = buffer[i];
              }
          },
          "ranks"_a, "depth"_a, "id"_a, "weight"_a,
          "Insert (id, weight) into a ranked histogram (in-place mutation)");
    m.def("crypto_sort_ranks",
          [](py::list ranks, int depth) {
              // Convert Python list to C array for mutation
              if (ranks.size() != static_cast<size_t>(depth * 2)) {
                  throw std::runtime_error("ranks list must have length depth*2");
              }
              std::vector<float> buffer(depth * 2);
              for (size_t i = 0; i < buffer.size(); ++i) {
                  buffer[i] = ranks[i].cast<float>();
              }
              crypto_sort_ranks(buffer.data(), depth);
              // Write back to Python list
              for (size_t i = 0; i < buffer.size(); ++i) {
                  ranks[i] = buffer[i];
              }
          },
          "ranks"_a, "depth"_a,
          "Sort ranked histogram by weight descending (in-place mutation)");

    // pkg87d — Cryptomatte hash function (for test verification)
    m.def("crypto_hash_name", &crypto_hash_name, "name"_a,
          "Hash a name string to a Cryptomatte float ID (MurmurHash3 + uint32_to_float32)");
}
