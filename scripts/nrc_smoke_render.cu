// scripts/nrc_smoke_render.cu — pkg26 NRC prototype harness.
//
// Renders N_FRAMES frames of a Cornell box where secondary bounces beyond
// the primary hit are handled by NeuralCache.  During the warmup period a
// random half of pixels trace a full secondary path and supply the result
// as a training target; the other half query the cache.  After warmup all
// pixels query the cache.
//
// Writes nrc_frame001.ppm and nrc_frame050.ppm, then prints a learning-curve
// comparison of mean luminance.
//
// Build: cmake -DASTRORAY_TINY_CUDA_NN=ON  (no production target depends on this)

#include "neural_cache.h"
#include "raytracer.h"         // Renderer, Camera, Lambertian, BVHAccel, etc.
#include "astroray/shapes.h"   // Triangle

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cfloat>
#include <vector>
#include <random>
#include <algorithm>
#include <cstring>

// ---------------------------------------------------------------------------
// Render parameters
// ---------------------------------------------------------------------------
static constexpr int   WIDTH         = 256;
static constexpr int   HEIGHT        = 256;
static constexpr int   N_PIXELS      = WIDTH * HEIGHT;
static constexpr int   N_FRAMES      = 50;
static constexpr int   WARMUP_FRAMES = 16;
static constexpr int   MAX_DEPTH     = 5;   // secondary path max bounces

// Scene AABB for position feature normalization.
static constexpr float AABB_LO  = -2.2f;
static constexpr float AABB_HI  =  2.2f;
static constexpr float AABB_SZ  = AABB_HI - AABB_LO;

// ---------------------------------------------------------------------------
// Simple emissive material defined inline so the harness doesn't need to
// link astroray_plugins (the DiffuseLightPlugin lives in the plugin object lib).
// ---------------------------------------------------------------------------
class HarnessLight : public Material {
    Vec3 color_;   // pre-multiplied by intensity
public:
    explicit HarnessLight(const Vec3& c) : color_(c) {}

    Vec3 emitted(const HitRecord& rec) const override {
        return rec.frontFace ? color_ : Vec3(0);
    }
    // Pure-virtual evalSpectral — return 0 (lights don't scatter).
    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }
    bool isEmissive() const override { return true; }
    Vec3 getEmission() const override { return color_; }
};

// ---------------------------------------------------------------------------
// Build Cornell box using existing Renderer + Camera infrastructure.
// Walls: Lambertian (red/green/white). Light: HarnessLight.
// No complex spheres — keeps NEE (Lambertian assumption) exact.
// ---------------------------------------------------------------------------
static void buildCornellBox(Renderer& r) {
    auto red   = std::make_shared<Lambertian>(Vec3(0.65f, 0.05f, 0.05f));
    auto green = std::make_shared<Lambertian>(Vec3(0.12f, 0.45f, 0.15f));
    auto white = std::make_shared<Lambertian>(Vec3(0.73f, 0.73f, 0.73f));
    auto light = std::make_shared<HarnessLight>(Vec3(1.0f, 0.9f, 0.8f) * 15.0f);

    // Floor (y = -2)
    r.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(2,-2,-2), Vec3(2,-2,2), white));
    r.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(2,-2,2), Vec3(-2,-2,2), white));
    // Ceiling (y = 2)
    r.addObject(std::make_shared<Triangle>(Vec3(-2,2,-2), Vec3(-2,2,2), Vec3(2,2,2), white));
    r.addObject(std::make_shared<Triangle>(Vec3(-2,2,-2), Vec3(2,2,2), Vec3(2,2,-2), white));
    // Back wall (z = -2)
    r.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(-2,2,-2), Vec3(2,2,-2), white));
    r.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(2,2,-2), Vec3(2,-2,-2), white));
    // Left wall (x = -2, red)
    r.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(-2,-2,2), Vec3(-2,2,2), red));
    r.addObject(std::make_shared<Triangle>(Vec3(-2,-2,-2), Vec3(-2,2,2), Vec3(-2,2,-2), red));
    // Right wall (x = 2, green)
    r.addObject(std::make_shared<Triangle>(Vec3(2,-2,-2), Vec3(2,2,-2), Vec3(2,2,2), green));
    r.addObject(std::make_shared<Triangle>(Vec3(2,-2,-2), Vec3(2,2,2), Vec3(2,-2,2), green));
    // Ceiling area light (small quad near y = 2)
    r.addObject(std::make_shared<Triangle>(Vec3(-0.5f,1.98f,-0.5f), Vec3(0.5f,1.98f,-0.5f), Vec3(0.5f,1.98f,0.5f), light));
    r.addObject(std::make_shared<Triangle>(Vec3(-0.5f,1.98f,-0.5f), Vec3(0.5f,1.98f,0.5f), Vec3(-0.5f,1.98f,0.5f), light));
}

// ---------------------------------------------------------------------------
// Build the NRC input feature vector from a surface hit.
// All components are normalized to approximately [0,1].
// ---------------------------------------------------------------------------
static void buildFeature(float* feat,
                          const Vec3& pos,
                          const Vec3& view_dir,   // unit, pointing toward camera
                          const Vec3& normal,
                          float roughness,
                          const Vec3& albedo) {
    // [0-2] position normalized to [0,1]
    feat[0] = (pos.x - AABB_LO) / AABB_SZ;
    feat[1] = (pos.y - AABB_LO) / AABB_SZ;
    feat[2] = (pos.z - AABB_LO) / AABB_SZ;

    // [3-4] view direction: (θ/π, φ/2π)
    Vec3 vd = view_dir.normalized();
    feat[3] = std::acos(std::max(-1.0f, std::min(1.0f, vd.y))) / (float)M_PI;
    feat[4] = (std::atan2(vd.z, vd.x) + (float)M_PI) / (2.0f * (float)M_PI);

    // [5-6] surface normal: (θ/π, φ/2π)
    Vec3 n = normal.normalized();
    feat[5] = std::acos(std::max(-1.0f, std::min(1.0f, n.y))) / (float)M_PI;
    feat[6] = (std::atan2(n.z, n.x) + (float)M_PI) / (2.0f * (float)M_PI);

    // [7] roughness
    feat[7] = roughness;

    // [8-10] albedo
    feat[8]  = albedo.x;
    feat[9]  = albedo.y;
    feat[10] = albedo.z;

    // [11-15] padding
    for (int i = 11; i < 16; ++i) feat[i] = 0.0f;
}

// ---------------------------------------------------------------------------
// Iterative path tracer used for training targets.
// Uses Lambertian BSDF assumption for NEE (appropriate for the all-Lambertian
// Cornell box).  Russian roulette after bounce 3.
// ---------------------------------------------------------------------------
static Vec3 tracePath(const BVHAccel& bvh, const LightList& lights,
                       const Ray& initial_ray, std::mt19937& gen,
                       int max_depth) {
    Vec3 color(0), throughput(1);
    Ray  ray = initial_ray;
    std::uniform_real_distribution<float> u01(0.0f, 1.0f);

    for (int depth = 0; depth < max_depth; ++depth) {
        HitRecord rec;
        if (!bvh.hit(ray, 0.001f, 1e30f, rec)) break;      // dark background
        if (!rec.material) break;

        // Emission: hit a light, accumulate and stop.
        Vec3 Le = rec.material->emitted(rec);
        if (Le.x + Le.y + Le.z > 0.0f) { color += throughput * Le; break; }

        Vec3 wo = -ray.direction.normalized();

        // NEE — direct lighting.  Lambertian BSDF: f(wo,wi) = albedo/PI.
        if (!lights.empty()) {
            LightSample ls = lights.sample(rec.point, gen);
            if (ls.pdf > 0.0f) {
                Vec3 wi = (ls.position - rec.point).normalized();
                float cosN = wi.dot(rec.normal);
                if (cosN > 0.0f) {
                    HitRecord shad;
                    bool occ = bvh.hit(Ray(rec.point, wi), 0.001f,
                                       ls.distance - 0.001f, shad);
                    if (!occ) {
                        Vec3 alb = rec.material->getAlbedo();
                        color += throughput * alb * (cosN / (float)M_PI)
                               * ls.emission / ls.pdf;
                    }
                }
            }
        }

        // Russian roulette.
        if (depth >= 3) {
            float p = std::min(0.95f, (throughput.x + throughput.y + throughput.z) / 3.0f);
            if (u01(gen) > p) break;
            throughput = throughput * (1.0f / p);
        }

        // Scatter: BSDF sample for the next bounce.
        BSDFSample bs = rec.material->sample(rec, wo, gen);
        if (bs.pdf <= 0.0f) break;
        // bs.f already includes cos(θ): throughput *= f·cos / pdf.
        throughput = throughput * Vec3(bs.f.x / bs.pdf,
                                       bs.f.y / bs.pdf,
                                       bs.f.z / bs.pdf);
        ray = Ray(rec.point, bs.wi);
    }
    return color;
}

// ---------------------------------------------------------------------------
// Simple gamma-corrected PPM write (P6 binary).
// ---------------------------------------------------------------------------
static float toSRGB(float v) {
    return std::pow(std::min(1.0f, std::max(0.0f, v)), 1.0f / 2.2f);
}

static void writePPM(const char* path, const std::vector<Vec3>& pix, int w, int h) {
    FILE* f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "Cannot write %s\n", path); return; }
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int y = h - 1; y >= 0; --y) {
        for (int x = 0; x < w; ++x) {
            const Vec3& c = pix[y * w + x];
            uint8_t rgb[3] = {
                (uint8_t)(toSRGB(c.x) * 255.0f + 0.5f),
                (uint8_t)(toSRGB(c.y) * 255.0f + 0.5f),
                (uint8_t)(toSRGB(c.z) * 255.0f + 0.5f)
            };
            fwrite(rgb, 1, 3, f);
        }
    }
    fclose(f);
    printf("  wrote %s\n", path);
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int main() {
    // ---- CUDA device check ------------------------------------------------
    int n_dev = 0;
    cudaGetDeviceCount(&n_dev);
    if (n_dev == 0) { fprintf(stderr, "FAIL: no CUDA devices\n"); return 1; }

    cudaDeviceProp prop{};
    cudaGetDeviceProperties(&prop, 0);
    printf("Device: %s (sm_%d%d, %.0f MiB)\n",
           prop.name, prop.major, prop.minor,
           (double)prop.totalGlobalMem / (1 << 20));

    if (prop.major < 7) {
        fprintf(stderr, "SKIP: NeuralCache requires sm_70+ (tensor cores)\n");
        return 0;
    }

    // ---- Scene setup -------------------------------------------------------
    Renderer renderer;
    buildCornellBox(renderer);
    renderer.buildAcceleration();

    const BVHAccel& bvh    = *renderer.getBVH();
    const LightList& lights = renderer.getLights();

    // Camera matches main.cpp Cornell box: lookFrom=(0,0,5.5), vfov=38°.
    Camera cam(Vec3(0,0,5.5f), Vec3(0,0,0), Vec3(0,1,0),
               38.0f, (float)WIDTH / HEIGHT, 0.0f, 5.5f, WIDTH, HEIGHT);

    // ---- NeuralCache -------------------------------------------------------
    NeuralCache nrc;
    printf("NeuralCache created. N_IN=%u N_OUT=%u BATCH_ALIGN=%u\n",
           NeuralCache::N_IN, NeuralCache::N_OUT, NeuralCache::BATCH_ALIGN);

    // ---- Render loop -------------------------------------------------------
    std::mt19937 rng(42u);
    std::uniform_real_distribution<float> u01(0.0f, 1.0f);

    std::vector<Vec3> framebuf(N_PIXELS);
    float mean_lum_f1 = 0.0f, mean_lum_fN = 0.0f;

    for (int frame = 1; frame <= N_FRAMES; ++frame) {
        const bool do_train = (frame <= WARMUP_FRAMES);

        // Per-frame accumulators for the tcnn batch calls.
        std::vector<float> train_feat;          // [n_train × N_IN]
        std::vector<float> train_tgt;           // [n_train × 3]
        std::vector<float> inf_feat;            // [n_inf   × N_IN]
        std::vector<int>   inf_idx;             // pixel indices for inference

        // Per-pixel primary-hit data (needed to combine direct + indirect).
        std::vector<Vec3>  direct_buf(N_PIXELS, Vec3(0));

        // ------------------------------------------------------------------
        // Primary ray pass: compute direct lighting and decide train/infer.
        // ------------------------------------------------------------------
        for (int py = 0; py < HEIGHT; ++py) {
            for (int px = 0; px < WIDTH; ++px) {
                const int idx = py * WIDTH + px;

                // Stratified sub-pixel jitter.
                float u = (px + u01(rng)) / (float)WIDTH;
                float v = (py + u01(rng)) / (float)HEIGHT;
                Ray ray = cam.getRay(u, v, rng);

                // Primary intersection.
                HitRecord rec;
                if (!bvh.hit(ray, 0.001f, 1e30f, rec) || !rec.material) {
                    framebuf[idx] = Vec3(0);
                    continue;
                }

                // Direct emission (camera hit a light).
                Vec3 Le = rec.material->emitted(rec);
                if (Le.x + Le.y + Le.z > 0.0f) {
                    framebuf[idx] = Le;
                    continue;
                }

                Vec3 wo = -ray.direction.normalized();

                // NEE — direct lighting (Lambertian BSDF, exact for this scene).
                Vec3 direct(0);
                if (!lights.empty()) {
                    LightSample ls = lights.sample(rec.point, rng);
                    if (ls.pdf > 0.0f) {
                        Vec3 wi = (ls.position - rec.point).normalized();
                        float cosN = wi.dot(rec.normal);
                        if (cosN > 0.0f) {
                            HitRecord shad;
                            bool occ = bvh.hit(Ray(rec.point, wi), 0.001f,
                                               ls.distance - 0.001f, shad);
                            if (!occ) {
                                Vec3 alb = rec.material->getAlbedo();
                                direct = alb * (cosN / (float)M_PI)
                                       * ls.emission / ls.pdf;
                            }
                        }
                    }
                }
                direct_buf[idx] = direct;

                // Build 16-float feature vector for this hit point.
                float feat[NeuralCache::N_IN];
                Vec3  alb = rec.material->getAlbedo();
                buildFeature(feat, rec.point, wo, rec.normal,
                             1.0f /* roughness — Lambertian */, alb);

                // ----- Assign to training or inference -----
                if (do_train && (u01(rng) < 0.5f)) {
                    // Training pixel: sample BSDF, trace secondary path.
                    BSDFSample bs = rec.material->sample(rec, wo, rng);
                    if (bs.pdf > 0.0f) {
                        Vec3 w = Vec3(bs.f.x / bs.pdf,
                                      bs.f.y / bs.pdf,
                                      bs.f.z / bs.pdf);
                        Vec3 L_sec = tracePath(bvh, lights,
                                               Ray(rec.point, bs.wi),
                                               rng, MAX_DEPTH);
                        Vec3 target = w * L_sec;
                        // Clamp to suppress fireflies in training targets.
                        target.x = std::min(target.x, 10.0f);
                        target.y = std::min(target.y, 10.0f);
                        target.z = std::min(target.z, 10.0f);
                        // Store for batch training.
                        for (int f = 0; f < (int)NeuralCache::N_IN; ++f)
                            train_feat.push_back(feat[f]);
                        train_tgt.push_back(target.x);
                        train_tgt.push_back(target.y);
                        train_tgt.push_back(target.z);
                        // Use the traced value as this pixel's indirect.
                        framebuf[idx] = direct + target;
                    } else {
                        framebuf[idx] = direct;
                    }
                } else {
                    // Inference pixel: queue for NRC batch query.
                    inf_idx.push_back(idx);
                    for (int f = 0; f < (int)NeuralCache::N_IN; ++f)
                        inf_feat.push_back(feat[f]);
                    // framebuf[idx] filled after query below.
                }
            }
        }

        // ------------------------------------------------------------------
        // Batch NRC inference for all queued inference pixels.
        // ------------------------------------------------------------------
        if (!inf_idx.empty()) {
            uint32_t n_inf  = (uint32_t)inf_idx.size();
            uint32_t n_pad  = NeuralCache::roundUp(n_inf);
            inf_feat.resize((size_t)n_pad * NeuralCache::N_IN, 0.0f);
            std::vector<Vec3> predicted = nrc.query(n_pad, inf_feat);

            for (uint32_t i = 0; i < n_inf; ++i) {
                int pidx = inf_idx[i];
                Vec3 L_ind = predicted[i];
                // Clamp NRC output — untrained network can produce large values.
                L_ind.x = std::min(L_ind.x, 5.0f);
                L_ind.y = std::min(L_ind.y, 5.0f);
                L_ind.z = std::min(L_ind.z, 5.0f);
                framebuf[pidx] = direct_buf[pidx] + L_ind;
            }
        }

        // ------------------------------------------------------------------
        // Training step: one Adam update on the whole frame's training batch.
        // ------------------------------------------------------------------
        if (do_train && !train_feat.empty()) {
            uint32_t n_tr  = (uint32_t)(train_feat.size() / NeuralCache::N_IN);
            uint32_t n_pad = NeuralCache::roundUp(n_tr);
            train_feat.resize((size_t)n_pad * NeuralCache::N_IN, 0.0f);
            train_tgt.resize((size_t)n_pad * 3, 0.0f);
            nrc.trainStep(n_pad, train_feat, train_tgt);
        }

        // ------------------------------------------------------------------
        // Per-frame stats and CUDA sync check.
        // ------------------------------------------------------------------
        float mean_lum = 0.0f;
        for (const Vec3& c : framebuf) mean_lum += luminance(c);
        mean_lum /= N_PIXELS;

        cudaError_t err = cudaDeviceSynchronize();
        const char* err_str = (err == cudaSuccess) ? "OK" : cudaGetErrorString(err);

        printf("Frame %2d/%d | lum=%.4f | train=%u inf=%u | CUDA:%s\n",
               frame, N_FRAMES, mean_lum,
               (uint32_t)(train_feat.size() / NeuralCache::N_IN),
               (uint32_t)inf_idx.size(),
               err_str);

        if (err != cudaSuccess) {
            fprintf(stderr, "CUDA error after frame %d — aborting.\n", frame);
            return 1;
        }

        // Save frames 1 and N_FRAMES.
        if (frame == 1) {
            mean_lum_f1 = mean_lum;
            writePPM("nrc_frame001.ppm", framebuf, WIDTH, HEIGHT);
        }
        if (frame == N_FRAMES) {
            mean_lum_fN = mean_lum;
            writePPM("nrc_frame050.ppm", framebuf, WIDTH, HEIGHT);
        }
    }

    // ---- Learning-curve summary -------------------------------------------
    printf("\n===== NRC Learning Curve =====\n");
    printf("Frame  1 mean luminance : %.4f  (untrained cache)\n", mean_lum_f1);
    printf("Frame 50 mean luminance : %.4f  (post-warmup cache)\n", mean_lum_fN);
    float delta = mean_lum_fN - mean_lum_f1;
    printf("Delta                   : %+.4f  (%s)\n",
           delta,
           delta >= 0.0f ? "PASS — cache contributes indirect illumination"
                         : "WARN — luminance did not increase");
    printf("==============================\n");

    return 0;
}
