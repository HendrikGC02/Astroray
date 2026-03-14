#include "raytracer.h"
#include "advanced_features.h"
#include "stb_image_write.h"
#include <iostream>
#include <fstream>
#include <chrono>
#include <iomanip>

void writePPM(const std::string& filename, const Camera& cam) {
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
    std::cout << "\nImage saved to " << filename << std::endl;
}

bool writePNG(const std::string& filename, const Camera& cam) {
    std::vector<unsigned char> pixels(cam.width * cam.height * 3);
    int idx = 0;
    for (int y = cam.height - 1; y >= 0; --y) {
        for (int x = 0; x < cam.width; ++x) {
            Vec3 color = cam.pixels[y * cam.width + x];
            pixels[idx++] = static_cast<unsigned char>(255.99f * color.x);
            pixels[idx++] = static_cast<unsigned char>(255.99f * color.y);
            pixels[idx++] = static_cast<unsigned char>(255.99f * color.z);
        }
    }
    int success = stbi_write_png(filename.c_str(), cam.width, cam.height, 3, pixels.data(), cam.width * 3);
    if (success) {
        std::cout << "\nImage saved to " << filename << std::endl;
    } else {
        std::cerr << "\nFailed to save PNG image\n";
    }
    return success != 0;
}

void buildCornellBox(Renderer& renderer) {
    auto red = std::make_shared<Lambertian>(Vec3(0.65f, 0.05f, 0.05f));
    auto green = std::make_shared<Lambertian>(Vec3(0.12f, 0.45f, 0.15f));
    auto white = std::make_shared<Lambertian>(Vec3(0.73f, 0.73f, 0.73f));
    auto light = std::make_shared<DiffuseLight>(Vec3(1.0f, 0.9f, 0.8f), 15.0f);
    
    // Floor/Ceiling/Walls
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(2,-2,-2), Vec3(2,-2,2), white));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(2,-2,2), Vec3(-2,-2,2), white));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,2,-2), Vec3(-2,2,2), Vec3(2,2,2), white));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,2,-2), Vec3(2,2,2), Vec3(2,2,-2), white));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(-2,2,-2), Vec3(2,2,-2), white));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(2,2,-2), Vec3(2,-2,-2), white));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(-2,-2,2), Vec3(-2,2,2), red));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(-2,2,2), Vec3(-2,2,-2), red));
    renderer.addObject(std::make_shared<Triangle>(Vec3(2,-2,-2), Vec3(2,2,-2), Vec3(2,2,2), green));
    renderer.addObject(std::make_shared<Triangle>(Vec3(2,-2,-2), Vec3(2,2,2), Vec3(2,-2,2), green));
    
    // Light
    renderer.addObject(std::make_shared<Triangle>(Vec3(-0.5f,1.98f,-0.5f), Vec3(0.5f,1.98f,-0.5f), Vec3(0.5f,1.98f,0.5f), light));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-0.5f,1.98f,-0.5f), Vec3(0.5f,1.98f,0.5f), Vec3(-0.5f,1.98f,0.5f), light));
    
    // Objects
    renderer.addObject(std::make_shared<Sphere>(Vec3(-0.7f,-1.3f,-0.5f), 0.7f, std::make_shared<Dielectric>(1.5f)));
    auto disney = std::make_shared<DisneyBRDF>(Vec3(0.9f,0.8f,0.7f), 0.5f, 0.3f);
    disney->setClearcoat(0.5f, 0.9f);
    renderer.addObject(std::make_shared<Sphere>(Vec3(0.8f,-1.5f,0.3f), 0.5f, disney));
    renderer.addObject(std::make_shared<Sphere>(Vec3(0,-1.5f,-1.2f), 0.5f, std::make_shared<Metal>(Vec3(0.9f), 0.1f)));
}

void buildMaterialTest(Renderer& renderer) {
    auto checker = std::make_shared<CheckerTexture>(Vec3(0.2f), Vec3(0.9f), 10);
    auto ground = std::make_shared<TexturedLambertian>(checker);
    renderer.addObject(std::make_shared<Triangle>(Vec3(-10,0,-10), Vec3(10,0,-10), Vec3(10,0,10), ground));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-10,0,-10), Vec3(10,0,10), Vec3(-10,0,10), ground));
    
    for (int i = 0; i < 5; ++i) {
        for (int j = 0; j < 5; ++j) {
            auto mat = std::make_shared<DisneyBRDF>(Vec3(0.7f,0.5f,0.3f), float(i)/4, float(j)/4);
            renderer.addObject(std::make_shared<Sphere>(Vec3((i-2)*2.2f, 0.5f, (j-2)*2.2f), 0.5f, mat));
        }
    }
    renderer.addObject(std::make_shared<Sphere>(Vec3(-5,8,5), 2.0f, std::make_shared<DiffuseLight>(Vec3(1,0.9f,0.8f), 5)));
    renderer.addObject(std::make_shared<Sphere>(Vec3(5,6,-5), 1.5f, std::make_shared<DiffuseLight>(Vec3(0.8f,0.9f,1), 3)));
}

int main(int argc, char* argv[]) {
    int scene = 1, width = 800, height = 600, samples = 64, depth = 50;
    std::string output = "output.ppm";
    
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--scene" && i+1 < argc) scene = std::atoi(argv[++i]);
        else if (arg == "--width" && i+1 < argc) width = std::atoi(argv[++i]);
        else if (arg == "--height" && i+1 < argc) height = std::atoi(argv[++i]);
        else if (arg == "--samples" && i+1 < argc) samples = std::atoi(argv[++i]);
        else if (arg == "--depth" && i+1 < argc) depth = std::atoi(argv[++i]);
        else if (arg == "--output" && i+1 < argc) output = argv[++i];
        else if (arg == "--help") {
            std::cout << "Usage: " << argv[0] << " [--scene 1|2] [--width N] [--height N] [--samples N] [--depth N] [--output file]\n";
            return 0;
        }
    }
    
    std::cout << "Custom Raytracer v3.0\n=====================\n";
    std::cout << "Resolution: " << width << "x" << height << ", Samples: " << samples << "\n";
    
    Renderer renderer;
    if (scene == 1) { std::cout << "Scene: Cornell Box\n"; buildCornellBox(renderer); }
    else { std::cout << "Scene: Material Test\n"; buildMaterialTest(renderer); }
    
    Vec3 lookFrom, lookAt; float vfov, focusDist;
    if (scene == 1) { lookFrom = Vec3(0,0,5.5f); lookAt = Vec3(0,0,0); vfov = 38; focusDist = 5.5f; }
    else { lookFrom = Vec3(0,8,15); lookAt = Vec3(0,1,0); vfov = 25; focusDist = 15; }
    
    Camera camera(lookFrom, lookAt, Vec3(0,1,0), vfov, float(width)/height, 0.01f, focusDist, width, height);
    
    std::cout << "\nRendering...\n";
    auto start = std::chrono::high_resolution_clock::now();
    int lastPct = -1;
    renderer.render(camera, samples, depth, [&](float p) {
        int pct = int(p * 100);
        if (pct != lastPct && pct % 5 == 0) { lastPct = pct; std::cout << "\rProgress: " << pct << "%" << std::flush; }
    }, true);
    
    auto dur = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::high_resolution_clock::now() - start);
    std::cout << "\n\nCompleted in " << dur.count() << "s\n";
    
    // Determine output format from file extension
    size_t extPos = output.rfind('.');
    std::string ext = (extPos != std::string::npos) ? output.substr(extPos + 1) : "";
    
    if (ext == "png") {
        writePNG(output, camera);
    } else {
        writePPM(output, camera);
    }
    return 0;
}