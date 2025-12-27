#pragma once

#include "raytracer.h"
#include <string>
#include <unordered_map>

// ============================================================================
// BLENDER INTEGRATION LAYER
// ============================================================================

namespace BlenderBridge {

// Blender scene data structures (simplified for demonstration)
struct BlenderVertex {
    float co[3];      // Vertex coordinates
    float no[3];      // Vertex normal
    float uv[2];      // UV coordinates
};

struct BlenderFace {
    int v[3];         // Vertex indices
    int mat_index;    // Material index
};

struct BlenderMesh {
    std::vector<BlenderVertex> vertices;
    std::vector<BlenderFace> faces;
    std::string name;
};

struct BlenderCamera {
    float location[3];
    float rotation[3];  // Euler angles
    float fov;          // Field of view in degrees
    float aperture;
    float focus_distance;
};

struct BlenderMaterial {
    std::string name;
    std::string type;  // "diffuse", "metal", "glass", "emission"
    float color[3];
    float roughness;
    float metallic;
    float ior;
    float emission_strength;
};

struct BlenderScene {
    std::vector<BlenderMesh> meshes;
    std::vector<BlenderMaterial> materials;
    BlenderCamera camera;
    int width, height;
    int samples;
    int max_depth;
};

// ============================================================================
// SCENE CONVERTER
// ============================================================================

class SceneConverter {
    std::unordered_map<std::string, std::shared_ptr<Material>> materialCache;
    
    std::shared_ptr<Material> convertMaterial(const BlenderMaterial& bMat) {
        // Check cache
        auto it = materialCache.find(bMat.name);
        if (it != materialCache.end()) return it->second;
        
        Vec3 color(bMat.color[0], bMat.color[1], bMat.color[2]);
        std::shared_ptr<Material> material;
        
        if (bMat.type == "emission") {
            material = std::make_shared<DiffuseLight>(color, bMat.emission_strength);
        } else if (bMat.type == "glass") {
            material = std::make_shared<Dielectric>(bMat.ior);
        } else if (bMat.type == "metal" || bMat.metallic > 0.5f) {
            material = std::make_shared<Metal>(color, bMat.roughness);
        } else {
            material = std::make_shared<Lambertian>(color);
        }
        
        materialCache[bMat.name] = material;
        return material;
    }
    
    Vec3 eulerToDirection(float rx, float ry, float rz) {
        // Convert Euler angles to direction vector (Blender's coordinate system)
        float cx = std::cos(rx), sx = std::sin(rx);
        float cy = std::cos(ry), sy = std::sin(ry);
        float cz = std::cos(rz), sz = std::sin(rz);
        
        return Vec3(
            -sy,
            sx * cy,
            -cx * cy
        );
    }
    
public:
    void convertScene(const BlenderScene& bScene, Renderer& renderer, Camera& camera) {
        materialCache.clear();
        
        // Convert meshes
        for (const auto& bMesh : bScene.meshes) {
            for (const auto& face : bMesh.faces) {
                const auto& v0 = bMesh.vertices[face.v[0]];
                const auto& v1 = bMesh.vertices[face.v[1]];
                const auto& v2 = bMesh.vertices[face.v[2]];
                
                Vec3 p0(v0.co[0], v0.co[1], v0.co[2]);
                Vec3 p1(v1.co[0], v1.co[1], v1.co[2]);
                Vec3 p2(v2.co[0], v2.co[1], v2.co[2]);
                
                auto material = convertMaterial(bScene.materials[face.mat_index]);
                auto triangle = std::make_shared<Triangle>(p0, p1, p2, material);
                renderer.addObject(triangle);
            }
        }
        
        // Convert camera
        Vec3 lookFrom(bScene.camera.location[0], 
                     bScene.camera.location[1], 
                     bScene.camera.location[2]);
        
        Vec3 direction = eulerToDirection(bScene.camera.rotation[0],
                                         bScene.camera.rotation[1],
                                         bScene.camera.rotation[2]);
        
        Vec3 lookAt = lookFrom + direction;
        Vec3 vup(0, 0, 1);  // Blender uses Z-up
        
        float aspectRatio = float(bScene.width) / float(bScene.height);
        
        camera = Camera(lookFrom, lookAt, vup, bScene.camera.fov, aspectRatio,
                       bScene.camera.aperture, bScene.camera.focus_distance,
                       bScene.width, bScene.height);
    }
};

// ============================================================================
// RENDER MANAGER
// ============================================================================

class RenderManager {
    Renderer renderer;
    Camera camera;
    SceneConverter converter;
    
    std::atomic<bool> isRendering{false};
    std::atomic<bool> shouldCancel{false};
    std::atomic<float> progress{0.0f};
    
public:
    struct RenderSettings {
        int samplesPerPixel = 64;
        int maxDepth = 8;
        bool useGPU = false;
        std::string outputPath;
    };
    
    void loadScene(const BlenderScene& bScene) {
        converter.convertScene(bScene, renderer, camera);
    }
    
    void startRender(const RenderSettings& settings) {
        if (isRendering) return;
        
        isRendering = true;
        shouldCancel = false;
        progress = 0.0f;
        
        auto progressCallback = [this](float p) {
            progress = p;
        };
        
        renderer.render(camera, settings.samplesPerPixel, settings.maxDepth, progressCallback);
        
        isRendering = false;
    }
    
    void cancelRender() {
        shouldCancel = true;
    }
    
    float getProgress() const {
        return progress;
    }
    
    bool isCurrentlyRendering() const {
        return isRendering;
    }
    
    const std::vector<Vec3>& getPixels() const {
        return camera.pixels;
    }
    
    void exportImage(const std::string& filepath) {
        // Convert to 8-bit RGB and save
        // This would integrate with Blender's image saving functions
        // For standalone use, implement your own image export
    }
};

// ============================================================================
// PYTHON BINDING HELPERS (for Blender's Python API)
// ============================================================================

class PythonBindings {
public:
    static void registerRenderer() {
        // This would use pybind11 or similar to expose the renderer to Python
        // Example structure:
        /*
        py::class_<RenderManager>(m, "RenderManager")
            .def(py::init<>())
            .def("load_scene", &RenderManager::loadScene)
            .def("start_render", &RenderManager::startRender)
            .def("cancel_render", &RenderManager::cancelRender)
            .def("get_progress", &RenderManager::getProgress)
            .def("is_rendering", &RenderManager::isCurrentlyRendering)
            .def("export_image", &RenderManager::exportImage);
        */
    }
};

// ============================================================================
// BLENDER ADDON INTERFACE
// ============================================================================

// Example Python code for the Blender addon:
/*
bl_info = {
    "name": "Custom Raytracer",
    "category": "Render",
    "blender": (4, 5, 0),
}

import bpy

class CustomRaytracerRenderEngine(bpy.types.RenderEngine):
    bl_idname = "CUSTOM_RAYTRACER"
    bl_label = "Custom Raytracer"
    bl_use_preview = True
    
    def render(self, depsgraph):
        scene = depsgraph.scene
        
        # Convert Blender scene to our format
        renderer_scene = self.convert_blender_scene(scene)
        
        # Create render manager
        manager = RenderManager()
        manager.load_scene(renderer_scene)
        
        # Render with progress updates
        settings = RenderManager.RenderSettings()
        settings.samplesPerPixel = scene.cycles.samples
        settings.maxDepth = scene.cycles.max_bounces
        
        def update_progress():
            while manager.is_rendering():
                self.update_progress(manager.get_progress())
                time.sleep(0.1)
        
        thread = threading.Thread(target=update_progress)
        thread.start()
        
        manager.start_render(settings)
        thread.join()
        
        # Get rendered pixels and update Blender image
        pixels = manager.get_pixels()
        result = self.begin_result(0, 0, scene.render.resolution_x, 
                                   scene.render.resolution_y)
        layer = result.layers[0].passes["Combined"]
        layer.rect = pixels
        self.end_result(result)

def register():
    bpy.utils.register_class(CustomRaytracerRenderEngine)

def unregister():
    bpy.utils.unregister_class(CustomRaytracerRenderEngine)
*/

} // namespace BlenderBridge