#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include <pybind11/functional.h>
#include "raytracer.h"
#include "advanced_features.h"

namespace py = pybind11;
using namespace pybind11::literals;

// ============================================================================
// TEXTURE MANAGEMENT
// ============================================================================

class TextureManager {
    std::unordered_map<std::string, std::shared_ptr<ImageTexture>> imageTextures;
    std::unordered_map<std::string, std::shared_ptr<Texture>> proceduralTextures;
    
public:
    void loadImageTexture(const std::string& name, py::array_t<float> imageData,
                         int width, int height) {
        auto tex = std::make_shared<ImageTexture>();
        
        // Convert numpy array to internal format
        auto buf = imageData.request();
        float* ptr = static_cast<float*>(buf.ptr);
        
        std::vector<Vec3> data(width * height);
        for (int i = 0; i < width * height; i++) {
            data[i] = Vec3(ptr[i*3], ptr[i*3+1], ptr[i*3+2]);
        }
        
        // Store in texture (would need to add method to set data directly)
        imageTextures[name] = tex;
    }
    
    void createProceduralTexture(const std::string& name, const std::string& type,
                                const std::vector<float>& params) {
        if (type == "checker") {
            Vec3 color1(params[0], params[1], params[2]);
            Vec3 color2(params[3], params[4], params[5]);
            float scale = params.size() > 6 ? params[6] : 10.0f;
            proceduralTextures[name] = std::make_shared<CheckerTexture>(color1, color2, scale);
        } else if (type == "noise") {
            float scale = params.size() > 0 ? params[0] : 1.0f;
            proceduralTextures[name] = std::make_shared<NoiseTexture>(scale);
        } else if (type == "marble") {
            float scale = params.size() > 0 ? params[0] : 1.0f;
            proceduralTextures[name] = std::make_shared<MarbleTexture>(scale);
        } else if (type == "wood") {
            float scale = params.size() > 0 ? params[0] : 1.0f;
            proceduralTextures[name] = std::make_shared<WoodTexture>(scale);
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

// ============================================================================
// ENHANCED PYTHON RENDERER
// ============================================================================

class PyRenderer {
    Renderer renderer;
    std::shared_ptr<Camera> camera;
    TextureManager textureManager;
    std::unordered_map<int, std::shared_ptr<Material>> materials;
    int nextMaterialId = 0;
    bool useAdaptiveSampling = true;
    
public:
    // Texture management
    void loadTexture(const std::string& name, py::array_t<float> imageData,
                    int width, int height) {
        textureManager.loadImageTexture(name, imageData, width, height);
    }
    
    void createProceduralTexture(const std::string& name, const std::string& type,
                                const std::vector<float>& params) {
        textureManager.createProceduralTexture(name, type, params);
    }
    
    // Material creation with full Disney BRDF support
    int createMaterial(const std::string& type,
                      const std::vector<float>& baseColor,
                      py::dict params) {
        Vec3 color(baseColor[0], baseColor[1], baseColor[2]);
        std::shared_ptr<Material> mat;
        
        if (type == "disney") {
            float metallic = params.contains("metallic") ? 
                params["metallic"].cast<float>() : 0.0f;
            float roughness = params.contains("roughness") ? 
                params["roughness"].cast<float>() : 0.5f;
            float transmission = params.contains("transmission") ? 
                params["transmission"].cast<float>() : 0.0f;
            float ior = params.contains("ior") ? 
                params["ior"].cast<float>() : 1.5f;
            
            auto disney = std::make_shared<DisneyBRDF>(color, metallic, roughness, 
                                                       transmission, ior);
            
            if (params.contains("anisotropic")) {
                float aniso = params["anisotropic"].cast<float>();
                float rotation = params.contains("anisotropic_rotation") ? 
                    params["anisotropic_rotation"].cast<float>() : 0.0f;
                disney->setAnisotropic(aniso, rotation);
            }
            
            if (params.contains("clearcoat")) {
                float coat = params["clearcoat"].cast<float>();
                float gloss = params.contains("clearcoat_gloss") ? 
                    params["clearcoat_gloss"].cast<float>() : 1.0f;
                disney->setClearcoat(coat, gloss);
            }
            
            if (params.contains("sheen")) {
                float sheen = params["sheen"].cast<float>();
                float tint = params.contains("sheen_tint") ? 
                    params["sheen_tint"].cast<float>() : 0.5f;
                disney->setSheen(sheen, tint);
            }
            
            if (params.contains("subsurface")) {
                disney->setSubsurface(params["subsurface"].cast<float>());
            }
            
            mat = disney;
        } else if (type == "lambertian" || type == "diffuse") {
            if (params.contains("texture")) {
                auto tex = textureManager.getTexture(params["texture"].cast<std::string>());
                if (tex) {
                    mat = std::make_shared<TexturedLambertian>(tex);
                } else {
                    mat = std::make_shared<Lambertian>(color);
                }
            } else {
                mat = std::make_shared<Lambertian>(color);
            }
        } else if (type == "metal") {
            float roughness = params.contains("roughness") ? 
                params["roughness"].cast<float>() : 0.1f;
            mat = std::make_shared<Metal>(color, roughness);
        } else if (type == "glass" || type == "dielectric") {
            float ior = params.contains("ior") ? 
                params["ior"].cast<float>() : 1.5f;
            mat = std::make_shared<Dielectric>(ior);
        } else if (type == "light" || type == "emission") {
            float intensity = params.contains("intensity") ? 
                params["intensity"].cast<float>() : 1.0f;
            mat = std::make_shared<DiffuseLight>(color, intensity);
        } else if (type == "subsurface") {
            Vec3 scatter(1.0f, 0.2f, 0.1f);
            if (params.contains("scatter_distance")) {
                auto sd = params["scatter_distance"].cast<std::vector<float>>();
                scatter = Vec3(sd[0], sd[1], sd[2]);
            }
            float scale = params.contains("scale") ? 
                params["scale"].cast<float>() : 1.0f;
            mat = std::make_shared<SubsurfaceMaterial>(color, scatter, scale);
        } else {
            // Default to Lambertian
            mat = std::make_shared<Lambertian>(color);
        }
        
        int id = nextMaterialId++;
        materials[id] = mat;
        return id;
    }
    
    // Add objects with material IDs
    void addSphere(const std::vector<float>& center, float radius, int materialId) {
        Vec3 pos(center[0], center[1], center[2]);
        auto mat = materials[materialId];
        if (!mat) {
            mat = std::make_shared<Lambertian>(Vec3(0.5f));
        }
        renderer.addObject(std::make_shared<Sphere>(pos, radius, mat));
    }
    
    void addTriangle(const std::vector<float>& v0,
                    const std::vector<float>& v1,
                    const std::vector<float>& v2,
                    int materialId,
                    const std::vector<float>& uv0 = {},
                    const std::vector<float>& uv1 = {},
                    const std::vector<float>& uv2 = {}) {
        Vec3 p0(v0[0], v0[1], v0[2]);
        Vec3 p1(v1[0], v1[1], v1[2]);
        Vec3 p2(v2[0], v2[1], v2[2]);
        
        auto mat = materials[materialId];
        if (!mat) {
            mat = std::make_shared<Lambertian>(Vec3(0.5f));
        }
        
        if (!uv0.empty() && !uv1.empty() && !uv2.empty()) {
            Vec2 t0(uv0[0], uv0[1]);
            Vec2 t1(uv1[0], uv1[1]);
            Vec2 t2(uv2[0], uv2[1]);
            renderer.addObject(std::make_shared<Triangle>(p0, p1, p2, t0, t1, t2, mat));
        } else {
            renderer.addObject(std::make_shared<Triangle>(p0, p1, p2, mat));
        }
    }
    
    // Add mesh from file
    void addMesh(const std::string& filename, int materialId,
                const std::vector<float>& position = {0, 0, 0},
                const std::vector<float>& scale = {1, 1, 1},
                float rotationY = 0) {
        auto mat = materials[materialId];
        if (!mat) {
            mat = std::make_shared<Lambertian>(Vec3(0.5f));
        }
        
        auto mesh = std::make_shared<Mesh>(mat);
        if (mesh->loadOBJ(filename)) {
            std::shared_ptr<Hittable> obj = mesh;
            
            // Apply transformations
            if (scale[0] != 1 || scale[1] != 1 || scale[2] != 1) {
                obj = std::make_shared<Scale>(obj, Vec3(scale[0], scale[1], scale[2]));
            }
            if (rotationY != 0) {
                obj = std::make_shared<RotateY>(obj, rotationY);
            }
            if (position[0] != 0 || position[1] != 0 || position[2] != 0) {
                obj = std::make_shared<Translate>(obj, Vec3(position[0], position[1], position[2]));
            }
            
            renderer.addObject(obj);
        }
    }
    
    // Add volume
    void addVolume(const std::vector<float>& center, float radius,
                  float density, const std::vector<float>& color,
                  float anisotropy = 0) {
        Vec3 pos(center[0], center[1], center[2]);
        Vec3 col(color[0], color[1], color[2]);
        
        auto boundary = std::make_shared<Sphere>(pos, radius,
            std::make_shared<Lambertian>(Vec3(1, 1, 1)));
        auto volume = std::make_shared<ConstantMedium>(boundary, density, col, anisotropy);
        renderer.addObject(volume);
    }
    
    // Camera setup
    void setupCamera(const std::vector<float>& lookFrom,
                    const std::vector<float>& lookAt,
                    const std::vector<float>& vup,
                    float vfov, float aspectRatio,
                    float aperture, float focusDist,
                    int width, int height) {
        Vec3 from(lookFrom[0], lookFrom[1], lookFrom[2]);
        Vec3 at(lookAt[0], lookAt[1], lookAt[2]);
        Vec3 up(vup[0], vup[1], vup[2]);
        
        camera = std::make_shared<Camera>(from, at, up, vfov, aspectRatio,
                                         aperture, focusDist, width, height);
    }
    
    // Rendering controls
    void setAdaptiveSampling(bool enable) {
        useAdaptiveSampling = enable;
    }
    
    // Main render function with progress callback
    py::array_t<float> render(int samplesPerPixel, int maxDepth,
                             py::object progressCallback = py::none()) {
        if (!camera) {
            throw std::runtime_error("Camera not set up");
        }
        
        // Create C++ callback wrapper if Python callback provided
        std::function<void(float)> callback = nullptr;
        if (!progressCallback.is_none()) {
            callback = [&progressCallback](float progress) {
                py::gil_scoped_acquire acquire;
                progressCallback(progress);
            };
        }
        
        // Render
        renderer.render(*camera, samplesPerPixel, maxDepth, callback, useAdaptiveSampling);
        
        // Convert to numpy array
        size_t size = camera->pixels.size();
        auto result = py::array_t<float>(size * 3);
        auto buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        
        for (size_t i = 0; i < size; i++) {
            ptr[i * 3 + 0] = camera->pixels[i].x;
            ptr[i * 3 + 1] = camera->pixels[i].y;
            ptr[i * 3 + 2] = camera->pixels[i].z;
        }
        
        result.resize({camera->height, camera->width, 3});
        return result;
    }
    
    // Get auxiliary buffers for denoising
    py::array_t<float> getAlbedoBuffer() {
        if (!camera) {
            throw std::runtime_error("Camera not set up");
        }
        
        size_t size = camera->albedoBuffer.size();
        auto result = py::array_t<float>(size * 3);
        auto buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        
        for (size_t i = 0; i < size; i++) {
            ptr[i * 3 + 0] = camera->albedoBuffer[i].x;
            ptr[i * 3 + 1] = camera->albedoBuffer[i].y;
            ptr[i * 3 + 2] = camera->albedoBuffer[i].z;
        }
        
        result.resize({camera->height, camera->width, 3});
        return result;
    }
    
    py::array_t<float> getNormalBuffer() {
        if (!camera) {
            throw std::runtime_error("Camera not set up");
        }
        
        size_t size = camera->normalBuffer.size();
        auto result = py::array_t<float>(size * 3);
        auto buf = result.request();
        float* ptr = static_cast<float*>(buf.ptr);
        
        for (size_t i = 0; i < size; i++) {
            ptr[i * 3 + 0] = camera->normalBuffer[i].x;
            ptr[i * 3 + 1] = camera->normalBuffer[i].y;
            ptr[i * 3 + 2] = camera->normalBuffer[i].z;
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

// ============================================================================
// PYTHON MODULE DEFINITION
// ============================================================================

PYBIND11_MODULE(raytracer_blender, m) {
    m.doc() = "Advanced Path Tracer for Blender - NEE, MIS, Disney BRDF";
    
    py::class_<PyRenderer>(m, "Renderer")
        .def(py::init<>())
        
        // Texture management
        .def("load_texture", &PyRenderer::loadTexture,
             py::arg("name"), py::arg("image_data"),
             py::arg("width"), py::arg("height"),
             "Load an image texture")
        .def("create_procedural_texture", &PyRenderer::createProceduralTexture,
             py::arg("name"), py::arg("type"), py::arg("params"),
             "Create a procedural texture (checker, noise, marble, wood)")
        
        // Material creation
        .def("create_material", &PyRenderer::createMaterial,
             py::arg("type"), py::arg("base_color"), py::arg("params"),
             "Create a material with full Disney BRDF support")
        
        // Object creation
        .def("add_sphere", &PyRenderer::addSphere,
             py::arg("center"), py::arg("radius"), py::arg("material_id"),
             "Add a sphere to the scene")
        .def("add_triangle", &PyRenderer::addTriangle,
             py::arg("v0"), py::arg("v1"), py::arg("v2"),
             py::arg("material_id"),
             py::arg("uv0") = std::vector<float>(),
             py::arg("uv1") = std::vector<float>(),
             py::arg("uv2") = std::vector<float>(),
             "Add a triangle with optional UV coordinates")
        .def("add_mesh", &PyRenderer::addMesh,
             py::arg("filename"), py::arg("material_id"),
             py::arg("position") = std::vector<float>{0, 0, 0},
             py::arg("scale") = std::vector<float>{1, 1, 1},
             py::arg("rotation_y") = 0.0f,
             "Load and add a mesh from OBJ file")
        .def("add_volume", &PyRenderer::addVolume,
             py::arg("center"), py::arg("radius"),
             py::arg("density"), py::arg("color"),
             py::arg("anisotropy") = 0.0f,
             "Add a volumetric medium")
        
        // Camera setup
        .def("setup_camera", &PyRenderer::setupCamera,
             py::arg("look_from"), py::arg("look_at"), py::arg("vup"),
             py::arg("vfov"), py::arg("aspect_ratio"),
             py::arg("aperture"), py::arg("focus_dist"),
             py::arg("width"), py::arg("height"),
             "Setup the camera")
        
        // Rendering
        .def("set_adaptive_sampling", &PyRenderer::setAdaptiveSampling,
             py::arg("enable"),
             "Enable or disable adaptive sampling")
        .def("render", &PyRenderer::render,
             py::arg("samples_per_pixel"), py::arg("max_depth"),
             py::arg("progress_callback") = py::none(),
             "Render the scene with NEE and MIS")
        
        // Auxiliary buffers
        .def("get_albedo_buffer", &PyRenderer::getAlbedoBuffer,
             "Get albedo buffer for denoising")
        .def("get_normal_buffer", &PyRenderer::getNormalBuffer,
             "Get normal buffer for denoising")
        
        // Utility
        .def("clear", &PyRenderer::clear,
             "Clear the scene")
        .def("get_width", &PyRenderer::getWidth)
        .def("get_height", &PyRenderer::getHeight);
    
    m.attr("__version__") = "3.0.0";
    m.attr("__features__") = py::dict(
        "nee"_a=true,
        "mis"_a=true,
        "disney_brdf"_a=true,
        "sah_bvh"_a=true,
        "adaptive_sampling"_a=true,
        "volumes"_a=true,
        "textures"_a=true,
        "subsurface"_a=true
    );
}