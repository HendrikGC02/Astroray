#include "raytracer.h"
#include "advanced_features.h"
#include "astroray/register.h"
#include "stb_image_write.h"
#include <iostream>
#include <fstream>
#include <chrono>
#include <iomanip>
#include <algorithm>
#include <cmath>

static inline float toDisplay(float linear) {
    return std::pow(std::clamp(linear, 0.0f, 1.0f), 1.0f / 2.2f);
}

void writePPM(const std::string& filename, const Camera& cam) {
    std::ofstream file(filename, std::ios::binary);
    file << "P6\n" << cam.width << " " << cam.height << "\n255\n";
    for (int y = 0; y < cam.height; ++y) {
        for (int x = 0; x < cam.width; ++x) {
            Vec3 color = cam.pixels[y * cam.width + x];
            unsigned char pixel[3] = {
                static_cast<unsigned char>(255.99f * toDisplay(color.x)),
                static_cast<unsigned char>(255.99f * toDisplay(color.y)),
                static_cast<unsigned char>(255.99f * toDisplay(color.z))
            };
            file.write(reinterpret_cast<char*>(pixel), 3);
        }
    }
    std::cout << "\nImage saved to " << filename << std::endl;
}

bool writePNG(const std::string& filename, const Camera& cam) {
    std::vector<unsigned char> pixels(cam.width * cam.height * 3);
    int idx = 0;
    for (int y = 0; y < cam.height; ++y) {
        for (int x = 0; x < cam.width; ++x) {
            Vec3 color = cam.pixels[y * cam.width + x];
            pixels[idx++] = static_cast<unsigned char>(255.99f * toDisplay(color.x));
            pixels[idx++] = static_cast<unsigned char>(255.99f * toDisplay(color.y));
            pixels[idx++] = static_cast<unsigned char>(255.99f * toDisplay(color.z));
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

static std::shared_ptr<Material> makeM(const std::string& type, astroray::ParamDict p) {
    return astroray::MaterialRegistry::instance().create(type, p);
}

void buildCornellBox(Renderer& renderer) {
    auto red   = std::make_shared<Lambertian>(Vec3(0.65f, 0.05f, 0.05f));
    auto green = std::make_shared<Lambertian>(Vec3(0.12f, 0.45f, 0.15f));
    auto white = std::make_shared<Lambertian>(Vec3(0.73f, 0.73f, 0.73f));
    astroray::ParamDict lp; lp.set("albedo", Vec3(1.0f, 0.9f, 0.8f)); lp.set("intensity", 15.0f);
    auto light = makeM("light", lp);

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
    astroray::ParamDict dp; dp.set("ior", 1.5f);
    renderer.addObject(std::make_shared<Sphere>(Vec3(-0.7f,-1.3f,-0.5f), 0.7f, makeM("dielectric", dp)));
    astroray::ParamDict disp; disp.set("albedo", Vec3(0.9f,0.8f,0.7f)); disp.set("metallic", 0.5f); disp.set("roughness", 0.3f); disp.set("clearcoat", 0.5f); disp.set("clearcoat_gloss", 0.9f);
    renderer.addObject(std::make_shared<Sphere>(Vec3(0.8f,-1.5f,0.3f), 0.5f, makeM("disney", disp)));
    astroray::ParamDict mp; mp.set("albedo", Vec3(0.9f)); mp.set("roughness", 0.1f);
    renderer.addObject(std::make_shared<Sphere>(Vec3(0,-1.5f,-1.2f), 0.5f, makeM("metal", mp)));
}

void buildMaterialTest(Renderer& renderer) {
    auto checker = std::make_shared<CheckerTexture>(Vec3(0.2f), Vec3(0.9f), 10);
    auto ground = std::make_shared<TexturedLambertian>(checker);
    renderer.addObject(std::make_shared<Triangle>(Vec3(-10,0,-10), Vec3(10,0,-10), Vec3(10,0,10), ground));
    renderer.addObject(std::make_shared<Triangle>(Vec3(-10,0,-10), Vec3(10,0,10), Vec3(-10,0,10), ground));

    for (int i = 0; i < 5; ++i) {
        for (int j = 0; j < 5; ++j) {
            astroray::ParamDict p; p.set("albedo", Vec3(0.7f,0.5f,0.3f)); p.set("metallic", float(i)/4); p.set("roughness", float(j)/4);
            renderer.addObject(std::make_shared<Sphere>(Vec3((i-2)*2.2f, 0.5f, (j-2)*2.2f), 0.5f, makeM("disney", p)));
        }
    }
    astroray::ParamDict l1; l1.set("albedo", Vec3(1,0.9f,0.8f)); l1.set("intensity", 5.0f);
    renderer.addObject(std::make_shared<Sphere>(Vec3(-5,8,5), 2.0f, makeM("light", l1)));
    astroray::ParamDict l2; l2.set("albedo", Vec3(0.8f,0.9f,1)); l2.set("intensity", 3.0f);
    renderer.addObject(std::make_shared<Sphere>(Vec3(5,6,-5), 1.5f, makeM("light", l2)));
}

int main(int argc, char* argv[]) {
    int scene = 1, width = 800, height = 600, samples = 64, depth = 8;
    std::string output = "output.ppm";
    std::string envmap = "";

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--scene" && i+1 < argc) scene = std::atoi(argv[++i]);
        else if (arg == "--width" && i+1 < argc) width = std::atoi(argv[++i]);
        else if (arg == "--height" && i+1 < argc) height = std::atoi(argv[++i]);
        else if (arg == "--samples" && i+1 < argc) samples = std::atoi(argv[++i]);
        else if (arg == "--depth" && i+1 < argc) depth = std::atoi(argv[++i]);
        else if (arg == "--output" && i+1 < argc) output = argv[++i];
        else if (arg == "--envmap" && i+1 < argc) envmap = argv[++i];
        else if (arg == "--help") {
            std::cout << "Usage: " << argv[0] << " [--scene 1|2] [--width N] [--height N] [--samples N] [--depth N] [--output file] [--envmap FILE]" << std::endl;
            std::cout.flush();
            return 0;
        }
    }

    std::cout << "Custom Raytracer v3.0\n=====================\n";
    std::cout << "Resolution: " << width << "x" << height << ", Samples: " << samples << "\n";

    Renderer renderer;
    if (scene == 1) { std::cout << "Scene: Cornell Box\n"; buildCornellBox(renderer); }
    else { std::cout << "Scene: Material Test\n"; buildMaterialTest(renderer); }

    if (!envmap.empty()) {
        auto env = std::make_shared<EnvironmentMap>();
        if (env->load(envmap)) {
            renderer.setEnvironmentMap(env);
            printf("Using environment map: %s\n", envmap.c_str());
        } else {
            printf("Warning: Failed to load environment map: %s\n", envmap.c_str());
        }
    }
    
    Vec3 lookFrom, lookAt; float vfov, focusDist;
    if (scene == 1) { lookFrom = Vec3(0,0,5.5f); lookAt = Vec3(0,0,0); vfov = 38; focusDist = 5.5f; }
    else { lookFrom = Vec3(0,8,15); lookAt = Vec3(0,1,0); vfov = 25; focusDist = 15; }
    
    Camera camera(lookFrom, lookAt, Vec3(0,1,0), vfov, float(width)/height, 0.01f, focusDist, width, height);
    
    std::cout << "\nRendering...\n";
    auto start = std::chrono::high_resolution_clock::now();
    int lastPct = -1;
    renderer.render(camera, samples, depth, nullptr, true);
    
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
