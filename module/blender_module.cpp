#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <pybind11/functional.h>
#include "raytracer.h"
#include "advanced_features.h"

namespace py = pybind11;
using namespace pybind11::literals;

class TextureManager {
    std::unordered_map<std::string, std::shared_ptr<ImageTexture>> imageTextures;
    std::unordered_map<std::string, std::shared_ptr<Texture>> proceduralTextures;
public:
    void loadImageTexture(const std::string& name, py::array_t<float> imageData, int width, int height) {
        auto buf = imageData.request();
        float* ptr = static_cast<float*>(buf.ptr);
        std::vector<Vec3> data(width * height);
        for (int i = 0; i < width * height; i++)
            data[i] = Vec3(ptr[i*3], ptr[i*3+1], ptr[i*3+2]);
        auto tex = std::make_shared<ImageTexture>();
        tex->setData(data, width, height);
        imageTextures[name] = tex;
    }
    void createProceduralTexture(const std::string& name, const std::string& type, const std::vector<float>& params) {
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
        }
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
public:
    void loadTexture(const std::string& name, py::array_t<float> imageData, int width, int height) {
        textureManager.loadImageTexture(name, imageData, width, height);
    }
    void createProceduralTexture(const std::string& name, const std::string& type, const std::vector<float>& params) {
        textureManager.createProceduralTexture(name, type, params);
    }
    
    int createMaterial(const std::string& type, const std::vector<float>& baseColor, py::dict params) {
        Vec3 color(baseColor[0], baseColor[1], baseColor[2]);
        std::shared_ptr<Material> mat;
        
        auto getFloat = [&](const char* key, float def) { return params.contains(key) ? params[key].cast<float>() : def; };
        
        if (type == "disney") {
            float metallic = getFloat("metallic", 0);
            float roughness = getFloat("roughness", 0.5f);
            float transmission = getFloat("transmission", 0);
            float ior = getFloat("ior", 1.5f);
            auto disney = std::make_shared<DisneyBRDF>(color, metallic, roughness, transmission, ior);
            if (params.contains("anisotropic")) disney->setAnisotropic(getFloat("anisotropic", 0), getFloat("anisotropic_rotation", 0));
            if (params.contains("clearcoat")) disney->setClearcoat(getFloat("clearcoat", 0), getFloat("clearcoat_gloss", 1));
            if (params.contains("sheen")) disney->setSheen(getFloat("sheen", 0), getFloat("sheen_tint", 0.5f));
            if (params.contains("subsurface")) disney->setSubsurface(getFloat("subsurface", 0));
            mat = disney;
        } else if (type == "lambertian" || type == "diffuse") {
            if (params.contains("texture")) {
                auto tex = textureManager.getTexture(params["texture"].cast<std::string>());
                if (tex) {
                    mat = std::make_shared<TexturedLambertian>(tex);
                } else {
                    mat = std::make_shared<Lambertian>(color);
                }
            } else mat = std::make_shared<Lambertian>(color);
        } else if (type == "metal") {
            mat = std::make_shared<Metal>(color, getFloat("roughness", 0.1f));
        } else if (type == "glass" || type == "dielectric") {
            mat = std::make_shared<Dielectric>(getFloat("ior", 1.5f));
        } else if (type == "light" || type == "emission") {
            mat = std::make_shared<DiffuseLight>(color, getFloat("intensity", 1.0f));
        } else if (type == "subsurface") {
            Vec3 scatter(1, 0.2f, 0.1f);
            if (params.contains("scatter_distance")) {
                auto sd = params["scatter_distance"].cast<std::vector<float>>();
                scatter = Vec3(sd[0], sd[1], sd[2]);
            }
            mat = std::make_shared<SubsurfaceMaterial>(color, scatter, getFloat("scale", 1));
        } else mat = std::make_shared<Lambertian>(color);
        
        int id = nextMaterialId++;
        materials[id] = mat;
        return id;
    }
    
    void addSphere(const std::vector<float>& center, float radius, int materialId) {
        Vec3 pos(center[0], center[1], center[2]);
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        renderer.addObject(std::make_shared<Sphere>(pos, radius, mat));
    }
    
    void addTriangle(const std::vector<float>& v0, const std::vector<float>& v1, const std::vector<float>& v2,
                    int materialId, const std::vector<float>& uv0 = {}, const std::vector<float>& uv1 = {},
                    const std::vector<float>& uv2 = {}) {
        Vec3 p0(v0[0], v0[1], v0[2]), p1(v1[0], v1[1], v1[2]), p2(v2[0], v2[1], v2[2]);
        auto mat = materials.count(materialId) ? materials[materialId] : std::make_shared<Lambertian>(Vec3(0.5f));
        if (!uv0.empty() && !uv1.empty() && !uv2.empty()) {
            renderer.addObject(std::make_shared<Triangle>(p0, p1, p2, Vec2(uv0[0], uv0[1]),
                Vec2(uv1[0], uv1[1]), Vec2(uv2[0], uv2[1]), mat));
        } else renderer.addObject(std::make_shared<Triangle>(p0, p1, p2, mat));
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
    
    void addVolume(const std::vector<float>& center, float radius, float density,
                  const std::vector<float>& color, float anisotropy = 0) {
        auto boundary = std::make_shared<Sphere>(Vec3(center[0], center[1], center[2]), radius,
            std::make_shared<Lambertian>(Vec3(1)));
        renderer.addObject(std::make_shared<ConstantMedium>(boundary, density,
            Vec3(color[0], color[1], color[2]), anisotropy));
    }
    
    void setupCamera(const std::vector<float>& lookFrom, const std::vector<float>& lookAt,
                    const std::vector<float>& vup, float vfov, float aspectRatio,
                    float aperture, float focusDist, int width, int height) {
        camera = std::make_shared<Camera>(
            Vec3(lookFrom[0], lookFrom[1], lookFrom[2]),
            Vec3(lookAt[0], lookAt[1], lookAt[2]),
            Vec3(vup[0], vup[1], vup[2]),
            vfov, aspectRatio, aperture, focusDist, width, height);
    }
    
    void setAdaptiveSampling(bool enable) { useAdaptiveSampling = enable; }
    
    py::array_t<float> render(int samplesPerPixel, int maxDepth, py::object progressCallback = py::none()) {
        if (!camera) throw std::runtime_error("Camera not set up");
        std::function<void(float)> callback = nullptr;
        if (!progressCallback.is_none()) {
            callback = [&progressCallback](float progress) {
                py::gil_scoped_acquire acquire;
                progressCallback(progress);
            };
        }
        renderer.render(*camera, samplesPerPixel, maxDepth, callback, useAdaptiveSampling);
        size_t size = camera->pixels.size();
        auto result = py::array_t<float>(size * 3);
        auto buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        for (size_t i = 0; i < size; i++) {
            ptr[i*3] = camera->pixels[i].x;
            ptr[i*3+1] = camera->pixels[i].y;
            ptr[i*3+2] = camera->pixels[i].z;
        }
        result.resize({camera->height, camera->width, 3});
        return result;
    }
    
    py::array_t<float> getAlbedoBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");
        size_t size = camera->albedoBuffer.size();
        auto result = py::array_t<float>(size * 3);
        float* ptr = static_cast<float*>(result.request().ptr);
        for (size_t i = 0; i < size; i++) {
            ptr[i*3] = camera->albedoBuffer[i].x;
            ptr[i*3+1] = camera->albedoBuffer[i].y;
            ptr[i*3+2] = camera->albedoBuffer[i].z;
        }
        result.resize({camera->height, camera->width, 3});
        return result;
    }
    
    py::array_t<float> getNormalBuffer() {
        if (!camera) throw std::runtime_error("Camera not set up");
        size_t size = camera->normalBuffer.size();
        auto result = py::array_t<float>(size * 3);
        float* ptr = static_cast<float*>(result.request().ptr);
        for (size_t i = 0; i < size; i++) {
            ptr[i*3] = camera->normalBuffer[i].x;
            ptr[i*3+1] = camera->normalBuffer[i].y;
            ptr[i*3+2] = camera->normalBuffer[i].z;
        }
        result.resize({camera->height, camera->width, 3});
        return result;
    }
    
    void clear() {
        renderer = Renderer();
        camera.reset();
        materials.clear();
        nextMaterialId = 0;
        textureManager = TextureManager();
    }
    int getWidth() const { return camera ? camera->width : 0; }
    int getHeight() const { return camera ? camera->height : 0; }
};

PYBIND11_MODULE(astroray, m) {
    m.doc() = "Astroray - Physically Based Path Tracer";
    py::class_<PyRenderer>(m, "Renderer")
        .def(py::init<>())
        .def("load_texture", &PyRenderer::loadTexture, "name"_a, "image_data"_a, "width"_a, "height"_a)
        .def("create_procedural_texture", &PyRenderer::createProceduralTexture, "name"_a, "type"_a, "params"_a)
        .def("create_material", &PyRenderer::createMaterial, "type"_a, "base_color"_a, "params"_a)
        .def("add_sphere", &PyRenderer::addSphere, "center"_a, "radius"_a, "material_id"_a)
        .def("add_triangle", &PyRenderer::addTriangle, "v0"_a, "v1"_a, "v2"_a, "material_id"_a,
             "uv0"_a = std::vector<float>(), "uv1"_a = std::vector<float>(), "uv2"_a = std::vector<float>())
        .def("add_mesh", &PyRenderer::addMesh, "filename"_a, "material_id"_a,
             "position"_a = std::vector<float>{0,0,0}, "scale"_a = std::vector<float>{1,1,1}, "rotation_y"_a = 0.0f)
        .def("add_volume", &PyRenderer::addVolume, "center"_a, "radius"_a, "density"_a, "color"_a, "anisotropy"_a = 0.0f)
        .def("setup_camera", &PyRenderer::setupCamera, "look_from"_a, "look_at"_a, "vup"_a, "vfov"_a,
             "aspect_ratio"_a, "aperture"_a, "focus_dist"_a, "width"_a, "height"_a)
        .def("set_adaptive_sampling", &PyRenderer::setAdaptiveSampling, "enable"_a)
        .def("render", &PyRenderer::render, "samples_per_pixel"_a, "max_depth"_a, "progress_callback"_a = py::none())
        .def("get_albedo_buffer", &PyRenderer::getAlbedoBuffer)
        .def("get_normal_buffer", &PyRenderer::getNormalBuffer)
        .def("clear", &PyRenderer::clear)
        .def("get_width", &PyRenderer::getWidth)
        .def("get_height", &PyRenderer::getHeight);
    m.attr("__version__") = "3.0.0";
    m.attr("__features__") = py::dict("nee"_a=true, "mis"_a=true, "disney_brdf"_a=true, "sah_bvh"_a=true,
        "adaptive_sampling"_a=true, "volumes"_a=true, "textures"_a=true, "subsurface"_a=true);
}