#include "raytracer.h"
#include "advanced_features.h"
#include "blender_integration.h"
#include <iostream>
#include <fstream>
#include <chrono>
#include <iomanip>

// ============================================================================
// IMAGE OUTPUT
// ============================================================================

class ImageWriter {
public:
    // Write PPM format (simple, no dependencies)
    static void writePPM(const std::string& filename, const Camera& cam) {
        std::ofstream file(filename);
        file << "P3\n" << cam.width << " " << cam.height << "\n255\n";
        
        for (int y = cam.height - 1; y >= 0; --y) {
            for (int x = 0; x < cam.width; ++x) {
                Vec3 color = cam.pixels[y * cam.width + x];
                int ir = static_cast<int>(255.99f * color.x);
                int ig = static_cast<int>(255.99f * color.y);
                int ib = static_cast<int>(255.99f * color.z);
                file << ir << " " << ig << " " << ib << "\n";
            }
        }
        
        file.close();
        std::cout << "\nImage saved to " << filename << std::endl;
    }
    
    // Write binary PPM (faster)
    static void writePPMBinary(const std::string& filename, const Camera& cam) {
        std::ofstream file(filename, std::ios::binary);
        file << "P6\n" << cam.width << " " << cam.height << "\n255\n";
        
        for (int y = cam.height - 1; y >= 0; --y) {
            for (int x = 0; x < cam.width; ++x) {
                Vec3 color = cam.pixels[y * cam.width + x];
                unsigned char pixel[3] = {
                    static_cast<unsigned char>(255.99f * color.x),
                    static_cast<unsigned char>(255.99f * color.y),
                    static_cast<unsigned char>(255.99f * color.z)
                };
                file.write(reinterpret_cast<char*>(pixel), 3);
            }
        }
        
        file.close();
        std::cout << "\nImage saved to " << filename << std::endl;
    }
    
    // Write auxiliary buffers for denoising
    static void writeAuxiliaryBuffers(const std::string& prefix, const Camera& cam) {
        // Write albedo buffer
        std::ofstream albedoFile(prefix + "_albedo.ppm", std::ios::binary);
        albedoFile << "P6\n" << cam.width << " " << cam.height << "\n255\n";
        
        for (int y = cam.height - 1; y >= 0; --y) {
            for (int x = 0; x < cam.width; ++x) {
                Vec3 albedo = cam.albedoBuffer[y * cam.width + x];
                unsigned char pixel[3] = {
                    static_cast<unsigned char>(std::clamp(albedo.x * 255.99f, 0.0f, 255.0f)),
                    static_cast<unsigned char>(std::clamp(albedo.y * 255.99f, 0.0f, 255.0f)),
                    static_cast<unsigned char>(std::clamp(albedo.z * 255.99f, 0.0f, 255.0f))
                };
                albedoFile.write(reinterpret_cast<char*>(pixel), 3);
            }
        }
        albedoFile.close();
        
        // Write normal buffer
        std::ofstream normalFile(prefix + "_normal.ppm", std::ios::binary);
        normalFile << "P6\n" << cam.width << " " << cam.height << "\n255\n";
        
        for (int y = cam.height - 1; y >= 0; --y) {
            for (int x = 0; x < cam.width; ++x) {
                Vec3 normal = cam.normalBuffer[y * cam.width + x];
                unsigned char pixel[3] = {
                    static_cast<unsigned char>(std::clamp(normal.x * 255.99f, 0.0f, 255.0f)),
                    static_cast<unsigned char>(std::clamp(normal.y * 255.99f, 0.0f, 255.0f)),
                    static_cast<unsigned char>(std::clamp(normal.z * 255.99f, 0.0f, 255.0f))
                };
                normalFile.write(reinterpret_cast<char*>(pixel), 3);
            }
        }
        normalFile.close();
        
        std::cout << "Auxiliary buffers saved: " << prefix << "_albedo.ppm, " 
                  << prefix << "_normal.ppm" << std::endl;
    }
};

// ============================================================================
// SCENE BUILDER
// ============================================================================

class SceneBuilder {
public:
    // Advanced Cornell Box with Disney materials
    static void buildAdvancedCornellBox(Renderer& renderer) {
        // Walls with proper materials
        auto red = std::make_shared<Lambertian>(Vec3(0.65f, 0.05f, 0.05f));
        auto green = std::make_shared<Lambertian>(Vec3(0.12f, 0.45f, 0.15f));
        auto white = std::make_shared<Lambertian>(Vec3(0.73f, 0.73f, 0.73f));
        auto light = std::make_shared<DiffuseLight>(Vec3(1.0f, 0.9f, 0.8f), 15.0f);
        
        // Floor (white)
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, -2, -2), Vec3(2, -2, -2), Vec3(2, -2, 2), white));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, -2, -2), Vec3(2, -2, 2), Vec3(-2, -2, 2), white));
        
        // Ceiling (white)
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, 2, -2), Vec3(-2, 2, 2), Vec3(2, 2, 2), white));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, 2, -2), Vec3(2, 2, 2), Vec3(2, 2, -2), white));
        
        // Back wall (white)
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, -2, -2), Vec3(-2, 2, -2), Vec3(2, 2, -2), white));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, -2, -2), Vec3(2, 2, -2), Vec3(2, -2, -2), white));
        
        // Left wall (red)
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, -2, -2), Vec3(-2, -2, 2), Vec3(-2, 2, 2), red));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-2, -2, -2), Vec3(-2, 2, 2), Vec3(-2, 2, -2), red));
        
        // Right wall (green)
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(2, -2, -2), Vec3(2, 2, -2), Vec3(2, 2, 2), green));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(2, -2, -2), Vec3(2, 2, 2), Vec3(2, -2, 2), green));
        
        // Area light on ceiling
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-0.5f, 1.98f, -0.5f), Vec3(0.5f, 1.98f, -0.5f), 
            Vec3(0.5f, 1.98f, 0.5f), light));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-0.5f, 1.98f, -0.5f), Vec3(0.5f, 1.98f, 0.5f), 
            Vec3(-0.5f, 1.98f, 0.5f), light));
        
        // Advanced materials showcase
        
        // Glass sphere with dispersion
        auto glass = std::make_shared<Dielectric>(1.5f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(-0.7f, -1.3f, -0.5f), 0.7f, glass));
        
        // Disney BRDF sphere
        auto disney = std::make_shared<DisneyBRDF>(Vec3(0.9f, 0.8f, 0.7f), 0.5f, 0.3f);
        disney->setClearcoat(0.5f, 0.9f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(0.8f, -1.5f, 0.3f), 0.5f, disney));
        
        // Subsurface scattering box
        auto sss = std::make_shared<SubsurfaceMaterial>(
            Vec3(0.9f, 0.6f, 0.5f), Vec3(1.0f, 0.2f, 0.1f), 0.5f);
        auto box = std::make_shared<Sphere>(Vec3(0, -1.5f, -1.2f), 0.5f, sss);
        auto rotatedBox = std::make_shared<RotateY>(box, 45);
        renderer.addObject(rotatedBox);
    }
    
    // Material test scene with Disney BRDF variations
    static void buildMaterialTestScene(Renderer& renderer) {
        // Ground plane with checkerboard
        auto checker = std::make_shared<CheckerTexture>(
            Vec3(0.2f, 0.2f, 0.2f), Vec3(0.9f, 0.9f, 0.9f), 10);
        auto ground = std::make_shared<TexturedLambertian>(checker);
        
        float size = 10.0f;
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-size, 0, -size), Vec3(size, 0, -size), Vec3(size, 0, size), ground));
        renderer.addObject(std::make_shared<Triangle>(
            Vec3(-size, 0, -size), Vec3(size, 0, size), Vec3(-size, 0, size), ground));
        
        // Array of Disney BRDF spheres with varying parameters
        int numSpheres = 5;
        for (int i = 0; i < numSpheres; ++i) {
            for (int j = 0; j < numSpheres; ++j) {
                float metallic = float(i) / (numSpheres - 1);
                float roughness = float(j) / (numSpheres - 1);
                
                auto mat = std::make_shared<DisneyBRDF>(
                    Vec3(0.7f, 0.5f, 0.3f), metallic, roughness);
                
                if (i == 2 && j == 2) {
                    mat->setClearcoat(1.0f, 0.1f);
                }
                
                Vec3 pos(
                    (i - numSpheres/2.0f) * 2.2f,
                    0.5f,
                    (j - numSpheres/2.0f) * 2.2f
                );
                
                renderer.addObject(std::make_shared<Sphere>(pos, 0.5f, mat));
            }
        }
        
        // Light sources
        auto light1 = std::make_shared<DiffuseLight>(Vec3(1.0f, 0.9f, 0.8f), 5.0f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(-5, 8, 5), 2.0f, light1));
        
        auto light2 = std::make_shared<DiffuseLight>(Vec3(0.8f, 0.9f, 1.0f), 3.0f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(5, 6, -5), 1.5f, light2));
    }
    
    // Complex scene with volumes and textures
    static void buildComplexScene(Renderer& renderer) {
        // Textured ground
        auto marble = std::make_shared<MarbleTexture>(0.1f);
        auto ground = std::make_shared<TexturedLambertian>(marble);
        
        renderer.addObject(std::make_shared<Sphere>(Vec3(0, -1000, 0), 1000, ground));
        
        // Main objects
        auto glass = std::make_shared<DisneyBRDF>(Vec3(1, 1, 1), 0, 0, 1, 1.5f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(0, 1, 0), 1.0f, glass));
        
        auto metal = std::make_shared<DisneyBRDF>(Vec3(0.7f, 0.6f, 0.5f), 1, 0.1f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(-3, 1, 0), 1.0f, metal));
        
        auto disney = std::make_shared<DisneyBRDF>(Vec3(0.4f, 0.8f, 0.4f), 0.2f, 0.5f);
        disney->setAnisotropic(0.5f, 0.25f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(3, 1, 0), 1.0f, disney));
        
        // Volume
        auto volumeBoundary = std::make_shared<Sphere>(Vec3(0, 1, -3), 1.5f, 
            std::make_shared<Lambertian>(Vec3(1, 1, 1)));
        auto volume = std::make_shared<ConstantMedium>(
            volumeBoundary, 0.5f, Vec3(0.5f, 0.7f, 1.0f), 0.3f);
        renderer.addObject(volume);
        
        // Many small spheres
        std::mt19937 gen(42);
        std::uniform_real_distribution<float> dist(0, 1);
        
        for (int a = -5; a < 5; a++) {
            for (int b = -5; b < 5; b++) {
                float chooseMat = dist(gen);
                Vec3 center(a + 0.9f * dist(gen), 0.2f, b + 0.9f * dist(gen));
                
                if ((center - Vec3(4, 0.2f, 0)).length() > 0.9f) {
                    std::shared_ptr<Material> material;
                    
                    if (chooseMat < 0.6f) {
                        // Disney BRDF with random parameters
                        Vec3 albedo(dist(gen), dist(gen), dist(gen));
                        float metallic = dist(gen);
                        float roughness = dist(gen);
                        material = std::make_shared<DisneyBRDF>(albedo, metallic, roughness);
                    } else if (chooseMat < 0.8f) {
                        // Glass
                        material = std::make_shared<Dielectric>(1.5f);
                    } else {
                        // Emissive
                        Vec3 color(dist(gen), dist(gen), dist(gen));
                        material = std::make_shared<DiffuseLight>(color, 2.0f);
                    }
                    
                    renderer.addObject(std::make_shared<Sphere>(center, 0.2f, material));
                }
            }
        }
        
        // Sun light
        auto sunLight = std::make_shared<DiffuseLight>(Vec3(1.0f, 0.95f, 0.8f), 3.0f);
        renderer.addObject(std::make_shared<Sphere>(Vec3(10, 10, 10), 3.0f, sunLight));
    }
};

// ============================================================================
// MAIN
// ============================================================================

void printUsage(const char* programName) {
    std::cout << "Usage: " << programName << " [options]\n"
              << "Options:\n"
              << "  --scene <n>       Scene (1=Cornell, 2=Materials, 3=Complex)\n"
              << "  --width <n>       Image width (default: 800)\n"
              << "  --height <n>      Image height (default: 600)\n"
              << "  --samples <n>     Max samples per pixel (default: 64)\n"
              << "  --adaptive        Use adaptive sampling (default: true)\n"
              << "  --depth <n>       Maximum ray depth (default: 50)\n"
              << "  --output <file>   Output filename (default: output.ppm)\n"
              << "  --denoise-buffers Write auxiliary buffers for denoising\n"
              << "  --help            Show this help\n";
}

int main(int argc, char* argv[]) {
    // Default settings
    int sceneChoice = 1;
    int width = 800;
    int height = 600;
    int samplesPerPixel = 64;
    int maxDepth = 50;
    bool useAdaptive = true;
    bool writeDenoiseBuffers = false;
    std::string outputFile = "output.ppm";
    
    // Parse command line arguments
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--help") {
            printUsage(argv[0]);
            return 0;
        } else if (arg == "--scene" && i + 1 < argc) {
            sceneChoice = std::atoi(argv[++i]);
        } else if (arg == "--width" && i + 1 < argc) {
            width = std::atoi(argv[++i]);
        } else if (arg == "--height" && i + 1 < argc) {
            height = std::atoi(argv[++i]);
        } else if (arg == "--samples" && i + 1 < argc) {
            samplesPerPixel = std::atoi(argv[++i]);
        } else if (arg == "--depth" && i + 1 < argc) {
            maxDepth = std::atoi(argv[++i]);
        } else if (arg == "--adaptive") {
            useAdaptive = true;
        } else if (arg == "--no-adaptive") {
            useAdaptive = false;
        } else if (arg == "--denoise-buffers") {
            writeDenoiseBuffers = true;
        } else if (arg == "--output" && i + 1 < argc) {
            outputFile = argv[++i];
        }
    }
    
    std::cout << "Advanced Path Tracer with NEE and MIS\n";
    std::cout << "=====================================\n";
    std::cout << "Resolution: " << width << "x" << height << "\n";
    std::cout << "Max samples per pixel: " << samplesPerPixel << "\n";
    std::cout << "Adaptive sampling: " << (useAdaptive ? "ON" : "OFF") << "\n";
    std::cout << "Max depth: " << maxDepth << "\n";
    std::cout << "Output: " << outputFile << "\n\n";
    
    // Create renderer and scene
    Renderer renderer;
    
    std::cout << "Building scene..." << std::endl;
    switch (sceneChoice) {
        case 1:
            std::cout << "Scene: Advanced Cornell Box\n";
            SceneBuilder::buildAdvancedCornellBox(renderer);
            break;
        case 2:
            std::cout << "Scene: Material Test\n";
            SceneBuilder::buildMaterialTestScene(renderer);
            break;
        case 3:
            std::cout << "Scene: Complex Scene\n";
            SceneBuilder::buildComplexScene(renderer);
            break;
        default:
            std::cout << "Unknown scene, using Cornell Box\n";
            SceneBuilder::buildAdvancedCornellBox(renderer);
    }
    
    // Setup camera
    Vec3 lookFrom, lookAt;
    float vfov, aperture = 0.01f, focusDist;
    
    if (sceneChoice == 1) {
        // Cornell Box camera
        lookFrom = Vec3(0, 0, 5.5f);
        lookAt = Vec3(0, 0, 0);
        vfov = 38.0f;
        focusDist = 5.5f;
    } else if (sceneChoice == 2) {
        // Material test camera
        lookFrom = Vec3(0, 8, 15);
        lookAt = Vec3(0, 1, 0);
        vfov = 25.0f;
        focusDist = 15.0f;
    } else {
        // Complex scene camera
        lookFrom = Vec3(13, 2, 3);
        lookAt = Vec3(0, 0.5f, 0);
        vfov = 20.0f;
        focusDist = 10.0f;
        aperture = 0.05f;
    }
    
    float aspectRatio = float(width) / float(height);
    Camera camera(lookFrom, lookAt, Vec3(0, 1, 0), vfov, aspectRatio, 
                  aperture, focusDist, width, height);
    
    // Render with progress callback
    std::cout << "\nRendering with Next Event Estimation and MIS..." << std::endl;
    auto startTime = std::chrono::high_resolution_clock::now();
    
    int lastPercent = -1;
    auto progressCallback = [&](float progress) {
        int percent = static_cast<int>(progress * 100);
        if (percent != lastPercent && percent % 5 == 0) {
            lastPercent = percent;
            std::cout << "\rProgress: " << std::setw(3) << percent << "%" << std::flush;
        }
    };
    
    renderer.render(camera, samplesPerPixel, maxDepth, progressCallback, useAdaptive);
    
    auto endTime = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::seconds>(endTime - startTime);
    
    std::cout << "\n\nRender completed in " << duration.count() << " seconds" << std::endl;
    
    // Save image
    std::cout << "Saving image..." << std::endl;
    ImageWriter::writePPMBinary(outputFile, camera);
    
    // Save auxiliary buffers if requested
    if (writeDenoiseBuffers) {
        std::string prefix = outputFile.substr(0, outputFile.find_last_of('.'));
        ImageWriter::writeAuxiliaryBuffers(prefix, camera);
    }
    
    std::cout << "\nDone!" << std::endl;
    std::cout << "\nRenderer features:" << std::endl;
    std::cout << "  ✓ Next Event Estimation (NEE)" << std::endl;
    std::cout << "  ✓ Multiple Importance Sampling (MIS)" << std::endl;
    std::cout << "  ✓ SAH-based BVH construction" << std::endl;
    std::cout << "  ✓ Complete Disney BRDF" << std::endl;
    std::cout << "  ✓ Adaptive sampling" << std::endl;
    std::cout << "  ✓ Russian roulette" << std::endl;
    std::cout << "  ✓ Volumetric rendering" << std::endl;
    std::cout << "  ✓ Texture mapping" << std::endl;
    
    return 0;
}