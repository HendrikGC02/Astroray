#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <pybind11/functional.h>
#include <pybind11/operators.h>
#include <array>
#include <cctype>
#include <cmath>
#include <mutex>
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
#include "astroray/restir/reservoir.h"
#include "astroray/restir/light_sample.h"
#include "astroray/restir/frame_state.h"
#include "../src/cpu/wavefront/reference_pt_production.h"
#include "../src/cpu/wavefront/reference_pt_wavefront.h"
#include "../src/cpu/wavefront/cpu_wavefront_driver.h"
#include "../src/cpu/wavefront/snapshot_diff.h"
#include "astroray/sampling/wavefront_rng.h"
#ifdef ASTRORAY_CUDA_ENABLED
#  include "astroray/gpu_renderer.h"
#endif

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

class TextureManager {
    std::unordered_map<std::string, std::shared_ptr<ImageTexture>> imageTextures;
    std::unordered_map<std::string, std::shared_ptr<Texture>> proceduralTextures;
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
            // params: [band_dir, profile, scale, distortion, detail, roughness, lacunarity, r1,g1,b1, r2,g2,b2]
            int bd = params.size() > 0 ? (int)params[0] : 0;
            int pf = params.size() > 1 ? (int)params[1] : 0;
            float sc = params.size() > 2 ? params[2] : 5.0f;
            float dist = params.size() > 3 ? params[3] : 0.0f;
            float det = params.size() > 4 ? params[4] : 2.0f;
            float rough = params.size() > 5 ? params[5] : 0.5f;
            float lac = params.size() > 6 ? params[6] : 2.0f;
            Vec3 c1 = params.size() > 9 ? Vec3(params[7], params[8], params[9]) : Vec3(0);
            Vec3 c2 = params.size() > 12 ? Vec3(params[10], params[11], params[12]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<WaveTexture>(bd, pf, sc, dist, det, rough, lac, c1, c2);
        } else if (type == "magic") {
            // params: [depth, scale, distortion, r1,g1,b1, r2,g2,b2]
            int depth = params.size() > 0 ? (int)params[0] : 2;
            float sc = params.size() > 1 ? params[1] : 5.0f;
            float dist = params.size() > 2 ? params[2] : 1.0f;
            Vec3 c1 = params.size() > 5 ? Vec3(params[3], params[4], params[5]) : Vec3(0);
            Vec3 c2 = params.size() > 8 ? Vec3(params[6], params[7], params[8]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<MagicTexture>(depth, sc, dist, c1, c2);
        } else if (type == "voronoi") {
            // params: [scale, randomness, dist_metric, feature, smoothness, r1,g1,b1, r2,g2,b2]
            float sc = params.size() > 0 ? params[0] : 5.0f;
            float rand = params.size() > 1 ? params[1] : 1.0f;
            int dm = params.size() > 2 ? (int)params[2] : 0;
            int feat = params.size() > 3 ? (int)params[3] : 0;
            float smooth = params.size() > 4 ? params[4] : 1.0f;
            Vec3 c1 = params.size() > 7 ? Vec3(params[5], params[6], params[7]) : Vec3(0);
            Vec3 c2 = params.size() > 10 ? Vec3(params[8], params[9], params[10]) : Vec3(1);
            proceduralTextures[name] = std::make_shared<VoronoiTexture>(sc, rand, dm, feat, smooth, c1, c2);
        } else if (type == "brick") {
            // params: [brick_r,g,b, mortar_r,g,b, brick_w, brick_h, mortar_size, offset, scale]
            Vec3 brick = params.size() > 2 ? Vec3(params[0], params[1], params[2]) : Vec3(0.7f, 0.35f, 0.2f);
            Vec3 mortar = params.size() > 5 ? Vec3(params[3], params[4], params[5]) : Vec3(0.9f);
            float bw = params.size() > 6 ? params[6] : 0.5f;
            float bh = params.size() > 7 ? params[7] : 0.25f;
            float ms = params.size() > 8 ? params[8] : 0.02f;
            float off = params.size() > 9 ? params[9] : 0.5f;
            float sc = params.size() > 10 ? params[10] : 5.0f;
            proceduralTextures[name] = std::make_shared<BrickTexture>(brick, mortar, bw, bh, ms, off, sc);
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
    std::shared_ptr<Texture> getTexture(const std::string& name) {
        auto it1 = imageTextures.find(name);
        if (it1 != imageTextures.end()) return it1->second;
        auto it2 = proceduralTextures.find(name);
        if (it2 != proceduralTextures.end()) return it2->second;
        return nullptr;
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
    std::string integratorName_;
#ifdef ASTRORAY_CUDA_ENABLED
    std::unique_ptr<CUDARenderer> cudaRenderer;
#endif
public:
    void loadTexture(const std::string& name, py::array_t<float> imageData, int width, int height,
                     const std::string& coordMode = "UV") {
        textureManager.loadImageTexture(name, imageData, width, height, coordMode);
    }
    void createProceduralTexture(const std::string& name, const std::string& type, const std::vector<float>& params,
                                 const std::string& coordMode = "UV") {
        textureManager.createProceduralTexture(name, type, params, coordMode);
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

        Vec3 sum(0.0f);
        for (int i = 0; i < samples; ++i) {
            const float u1 = halton(i + 1, 2);
            const float u2 = halton(i + 1, 3);
            const float cosThetaI = u1;
            const float sinThetaI = std::sqrt(std::max(0.0f, 1.0f - cosThetaI * cosThetaI));
            const float phi = 2.0f * float(M_PI) * u2;
            const Vec3 wi = (rec.tangent * (std::cos(phi) * sinThetaI) +
                             rec.bitangent * (std::sin(phi) * sinThetaI) +
                             rec.normal * cosThetaI).normalized();
            sum += it->second->eval(rec, wo, wi);
        }
        const Vec3 reflected = sum * (2.0f * float(M_PI) / float(samples));
        return {reflected.x, reflected.y, reflected.z};
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

    void addMesh(const std::string& filename, int materialId, const std::vector<float>& position = {0,0,0},
                const std::vector<float>& scale = {1,1,1}, float rotationY = 0) {
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        auto mesh = std::make_shared<Mesh>(mat);
        if (mesh->loadOBJ(filename)) {
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

        // pkg43: accretion model selector. Default to NOVIKOV_THORNE for backward compatibility.
        std::string accretion_model = params.contains("accretion_model")
            ? params["accretion_model"].cast<std::string>() : "NOVIKOV_THORNE";

        auto bh = std::make_shared<BlackHole>(
            Vec3(position[0], position[1], position[2]),
            double(mass_solar), double(influence_radius),
            disk_outer, mdot, incl);

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

    void setAdaptiveSampling(bool enable) { useAdaptiveSampling = enable; }

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

    void setWorldMaxBounces(int maxB) {
        renderer.setWorldMaxBounces(maxB);
    }

    void setWorldVolume(float density, const std::vector<float>& color, float anisotropy = 0.0f) {
        renderer.setWorldVolume(density, Vec3(color[0], color[1], color[2]), anisotropy);
    }

    void setUseReflectiveCaustics(bool use) {
        renderer.setUseReflectiveCaustics(use);
    }

    void setUseRefractiveCaustics(bool use) {
        renderer.setUseRefractiveCaustics(use);
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
                              int volumeBounces = -1, int transparentBounces = -1) {
        if (!camera) throw std::runtime_error("Camera not set up");

#ifdef ASTRORAY_CUDA_ENABLED
        if (useGPU && cudaRenderer && cudaRenderer->isAvailable()) {
            // GPU path: build BVH on CPU (needed for upload), then render on GPU
            renderer.buildAcceleration();
            cudaRenderer->uploadScene(renderer, *camera);
            if (envMap && envMap->loaded())
                cudaRenderer->uploadEnvironmentMap(*envMap);
            // pkg85-D: route spectral integrators to the multiwavelength kernel.
            // CPU path_tracer uses SpectralPathTracer (spectral path → XYZ → sRGB),
            // so GPU must do the same via multiwavelength_kernel.cu. The legacy RGB
            // path_trace_kernel.cu (used pre-pkg14) is no longer accurate for HDRI
            // env-map rendering because it converts env RGB → spectral → RGB via
            // RGBIlluminantSpectrum, which is lossy compared to the CPU's direct
            // RGBIlluminantSpectrum spectral atlas sampling.
            if (integratorName_ == "path_tracer" ||
                integratorName_ == "multiwavelength_path_tracer") {
                // pkg54: spectral-band megakernel. Resolve params from the
                // same ParamDict used to construct the CPU integrator.
                float lmin = integratorParams_.getFloat("lambda_min", 380.0f);
                float lmax = integratorParams_.getFloat("lambda_max", 780.0f);
                std::string mode = integratorParams_.getString("output_mode", "");
                bool useLum;
                if (mode.empty())
                    useLum = !(lmin >= 379.5f && lmax <= 780.5f);
                else
                    useLum = (mode == "luminance");
                // The GPU megakernel mirrors whichever CPU integrator the
                // name selects: `path_tracer` -> Renderer::pathTraceSpectral
                // (area-light NEE + MIS); `multiwavelength_path_tracer` ->
                // the naive no-NEE MultiwavelengthPathTracer. The two share
                // the kernel, so NEE must be gated by integrator identity.
                bool enableNEE = (integratorName_ == "path_tracer");
                cudaRenderer->renderMultiwavelength(
                    camera->pixels,
                    camera->width, camera->height, renderer.getSeed(),
                    samplesPerPixel, maxDepth,
                    lmin, lmax, useLum, enableNEE);
            } else {
                cudaRenderer->render(camera->pixels,
                                     camera->width, camera->height, renderer.getSeed(),
                                     samplesPerPixel, maxDepth);
            }
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

    py::array_t<float> getCryptomatteObjectBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 4};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->cryptomatteObjectBuffer.size();
        for (size_t i = 0; i < size; ++i) {
            ptr[i*4] = camera->cryptomatteObjectBuffer[i].x;
            ptr[i*4+1] = camera->cryptomatteObjectBuffer[i].y;
            ptr[i*4+2] = camera->cryptomatteObjectBuffer[i].z;
            ptr[i*4+3] = camera->cryptomatteObjectCoverageBuffer[i];
        }
        return result;
    }

    py::array_t<float> getCryptomatteMaterialBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");

        py::ssize_t shape[3] = {static_cast<py::ssize_t>(camera->height), static_cast<py::ssize_t>(camera->width), 4};
        auto result = py::array_t<float>(shape);
        py::buffer_info buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        size_t size = camera->cryptomatteMaterialBuffer.size();
        for (size_t i = 0; i < size; ++i) {
            ptr[i*4] = camera->cryptomatteMaterialBuffer[i].x;
            ptr[i*4+1] = camera->cryptomatteMaterialBuffer[i].y;
            ptr[i*4+2] = camera->cryptomatteMaterialBuffer[i].z;
            ptr[i*4+3] = camera->cryptomatteMaterialCoverageBuffer[i];
        }
        return result;
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
        if (key == "cryptomatte_object" || key == "cryptomatte_material") {
            const std::vector<Vec3>* vecBuffer = (key == "cryptomatte_object")
                ? &camera->cryptomatteObjectBuffer
                : &camera->cryptomatteMaterialBuffer;
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

    // pkg39: multi-wavelength rendering helpers
    void setWavelengthRange(float lambdaMin, float lambdaMax) {
        integratorParams_.set("lambda_min", lambdaMin);
        integratorParams_.set("lambda_max", lambdaMax);
    }

    void setOutputMode(const std::string& mode) {
        integratorParams_.set("output_mode", mode);
    }

    void setMaterialSpectralProfile(int materialId, const std::string& profileName) {
        auto it = materials.find(materialId);
        if (it == materials.end()) return;
        auto& db = astroray::SpectralProfileDatabase::instance();
        const auto* profile = db.get(profileName);
        if (profile) it->second->setSpectralProfile(profile);
    }

    void clearMaterialSpectralProfile(int materialId) {
        auto it = materials.find(materialId);
        if (it != materials.end()) it->second->setSpectralProfile(nullptr);
    }

    void setIntegrator(const std::string& name) {
        if (name == "auto" || name == "default" || name.empty()) {
            renderer.setIntegrator(nullptr);
            integratorName_.clear();
            return;
        }
        auto integrator = astroray::IntegratorRegistry::instance().create(name, integratorParams_);
        renderer.setIntegrator(integrator);
        integratorName_ = name;
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

        // Use a fully isolated temporary renderer and CUDA context to avoid
        // leaving dangling GPU pointers. This ensures the main renderer's state
        // (this->renderer, this->cudaRenderer) is never polluted with throwaway
        // geometry that gets cleared before the GPU pointers are freed.
        Renderer tempRenderer;
        auto tempCudaRenderer = std::make_unique<CUDARenderer>();

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
        tempCudaRenderer->uploadScene(tempRenderer, *cam);

        // Launch the kernel. This is where the 12s JIT + context init happens.
        // The JIT cache is process-wide, so triggering it here warms the cache
        // for this->cudaRenderer as well.
        tempCudaRenderer->render(cam->pixels, 1, 1, tempRenderer.getSeed(), 1, 1);

        // tempRenderer and tempCudaRenderer are automatically destroyed at scope
        // exit via RAII, freeing all GPU resources cleanly. No dangling pointers.
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
        integratorName_.clear();
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
        .def("set_texture_uv_transform", &PyRenderer::setTextureUVTransform,
             "name"_a, "scale_x"_a, "scale_y"_a, "offset_x"_a, "offset_y"_a,
             "rotation"_a = 0.0f,
             "Apply scale + Z-rotation + offset (UV-space) to a texture; "
             "baked from a Blender Mapping node. Order matches Blender Point "
             "mapping: scale → rotate → translate. Rotation is in radians.")
        .def("set_texture_uv_layer", &PyRenderer::setTextureUVLayerName,
             "name"_a, "layer_name"_a)
        .def("create_material", &PyRenderer::createMaterial, "type"_a, "base_color"_a, "params"_a)
        .def("eval_material", &PyRenderer::evalMaterial,
             "material_id"_a, "wo"_a, "wi"_a,
             "normal"_a = std::vector<float>{0.0f, 1.0f, 0.0f})
        .def("integrate_material_reflectance", &PyRenderer::integrateMaterialReflectance,
             "material_id"_a, "cos_theta_o"_a, "samples"_a = 4096,
             "Halton hemisphere integration of material eval(), used for BRDF conservation tests.")
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
        .def("add_triangle", &PyRenderer::addTriangle, "v0"_a, "v1"_a, "v2"_a, "material_id"_a,
             "uv0"_a = std::vector<float>(), "uv1"_a = std::vector<float>(), "uv2"_a = std::vector<float>(),
             "n0"_a = std::vector<float>(), "n1"_a = std::vector<float>(), "n2"_a = std::vector<float>(),
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_triangle_layers", &PyRenderer::addTriangleLayers,
             "v0"_a, "v1"_a, "v2"_a, "material_id"_a, "uv_layers"_a,
             "n0"_a = std::vector<float>(), "n1"_a = std::vector<float>(), "n2"_a = std::vector<float>(),
             "object_pass_index"_a = 0, "material_pass_index"_a = 0)
        .def("add_mesh", &PyRenderer::addMesh, "filename"_a, "material_id"_a,
             "position"_a = std::vector<float>{0,0,0}, "scale"_a = std::vector<float>{1,1,1}, "rotation_y"_a = 0.0f)
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
        .def("set_world_max_bounces", &PyRenderer::setWorldMaxBounces, "max_bounces"_a)
        .def("set_world_volume", &PyRenderer::setWorldVolume,
             "density"_a, "color"_a, "anisotropy"_a = 0.0f)
        .def("set_use_reflective_caustics", &PyRenderer::setUseReflectiveCaustics, "use"_a)
        .def("set_use_refractive_caustics", &PyRenderer::setUseRefractiveCaustics, "use"_a)
        .def("set_object_caustic_caster", &PyRenderer::setObjectCausticCaster,
             "object_id"_a, "enabled"_a,
             "pkg64 Phase 3 — flag an object (by addObject order) as a "
             "caustic caster. Default path_tracer attempts SMS connections "
             "through flagged objects when use_refractive_caustics=True.")
        .def("caustic_caster_count", &PyRenderer::getCausticCasterCount)
        .def("scene_object_count", &PyRenderer::getSceneObjectCount)
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
             "volume_bounces"_a = -1, "transparent_bounces"_a = -1)
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
        .def("get_scene_stats", &PyRenderer::getSceneStats,
             "pkg56 Phase B: cheap CPU-side counters (objects, materials, "
             "BVH node count, lights, env_loaded) used by partial-state "
             "tests to assert that an upload_materials() / "
             "upload_lights() / upload_environment() call did not touch "
             "the geometry/BVH state.")
        .def("_gpu_profile_lookup", &PyRenderer::gpuProfileLookup,
             "profile_index"_a, "lambda_nm"_a,
             "Return device-side reflectance for an uploaded spectral profile slot.")
        .def("get_material_backend_capabilities",
             &PyRenderer::getMaterialBackendCapabilities, "material_id"_a)
        .def("get_material_closure_graph",
             &PyRenderer::getMaterialClosureGraph, "material_id"_a)
        .def_property_readonly("gpu_available",   &PyRenderer::getGPUAvailable)
        .def_property_readonly("gpu_device_name", &PyRenderer::getGPUDeviceName)
        .def("sample_texture", &PyRenderer::sampleTexture,
             "type"_a, "params"_a, "u"_a = 0.5f, "v"_a = 0.5f)
        .def("set_integrator", &PyRenderer::setIntegrator, "name"_a)
        .def("get_integrator_stats", &PyRenderer::getIntegratorStats,
             "Return optional diagnostic counters from the active integrator.")
        .def("set_integrator_param", &PyRenderer::setIntegratorParam,
             "key"_a, "value"_a,
             "Set an integer parameter passed to the integrator constructor.")
        // pkg39: multi-wavelength rendering
        .def("set_wavelength_range", &PyRenderer::setWavelengthRange,
             "lambda_min"_a, "lambda_max"_a,
             "Set wavelength band (nm) for the next set_integrator() call.")
        .def("set_output_mode", &PyRenderer::setOutputMode, "mode"_a,
             "Output mode: 'xyz' (visible) or 'luminance' (IR/UV).")
        .def("set_material_spectral_profile", &PyRenderer::setMaterialSpectralProfile,
             "material_id"_a, "profile_name"_a,
             "Attach a spectral profile to a material for outside-visible rendering.")
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
    }, "Return names of all loaded spectral profiles.");
    m.def("spectral_profile_reflectance", [](const std::string& name, float lambda_nm) -> float {
        const auto* p = astroray::SpectralProfileDatabase::instance().get(name);
        if (!p) return 0.0f;
        return p->reflectance(lambda_nm);
    }, "name"_a, "lambda_nm"_a, "Sample reflectance of a named profile at lambda_nm.");

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
        astroray::restir::Reservoir<float> res;
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
             bool record_snapshots) -> py::array_t<float> {
              auto cam = r.getCamera();
              if (!cam) {
                  throw std::runtime_error("Camera not set up. Call setup_camera() first.");
              }
              auto result = astroray::cpu_wavefront::reference_pt_wavefront_render(
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
          "pkg55-B' Session 2b: wavefront-side reference PT (per-path RNG). "
          "Diff oracle for CPU wavefront. Lambertian-Cornell only.");

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
        "cuda"_a=true
#else
        "cuda"_a=false
#endif
    );
}
