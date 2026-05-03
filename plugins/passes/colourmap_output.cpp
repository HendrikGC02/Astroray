#include "astroray/register.h"
#include "astroray/pass.h"
#include "astroray/param_dict.h"
#include "raytracer.h"
#include <cmath>
#include <algorithm>

// pkg39: ColourmapOutput pass.
//
// Reads the "color" buffer produced by the multiwavelength_path_tracer, extracts
// luminance (mean of RGB channels, which equals the band luminance stored as
// neutral grey by the integrator), and maps it through a named colourmap.
//
// Supported colourmaps (param "colourmap"):
//   "grayscale"      — linear grey (default)
//   "hot"            — black → red → yellow → white (thermal look)
//   "inferno"        — perceptually-uniform dark-to-bright (scientific)
//   "viridis"        — perceptually-uniform purple-to-yellow-green (scientific)
//   "ir_false_colour"— warm Kodak Aerochrome-style: dark areas cyan, bright areas red

static Vec3 apply_grayscale(float t) { return Vec3(t, t, t); }

static Vec3 apply_hot(float t) {
    // black(0) → red(1/3) → yellow(2/3) → white(1)
    float r = std::min(1.0f, t * 3.0f);
    float g = std::min(1.0f, std::max(0.0f, t * 3.0f - 1.0f));
    float b = std::min(1.0f, std::max(0.0f, t * 3.0f - 2.0f));
    return Vec3(r, g, b);
}

// Simple piecewise-linear approximation of matplotlib's inferno colourmap.
static Vec3 apply_inferno(float t) {
    static const float r[] = {0.0f, 0.2f, 0.6f, 0.9f, 1.0f, 0.99f};
    static const float g[] = {0.0f, 0.0f, 0.1f, 0.4f, 0.8f, 1.0f };
    static const float b[] = {0.0f, 0.4f, 0.6f, 0.3f, 0.1f, 0.64f};
    int n = 5;
    float ft = t * n;
    int   i  = std::min(n - 1, static_cast<int>(ft));
    float f  = ft - i;
    return Vec3(r[i]*(1-f)+r[i+1]*f, g[i]*(1-f)+g[i+1]*f, b[i]*(1-f)+b[i+1]*f);
}

// Simple piecewise-linear approximation of matplotlib's viridis colourmap.
static Vec3 apply_viridis(float t) {
    static const float r[] = {0.27f, 0.19f, 0.13f, 0.37f, 0.79f, 0.99f};
    static const float g[] = {0.00f, 0.29f, 0.56f, 0.75f, 0.88f, 0.91f};
    static const float b[] = {0.33f, 0.53f, 0.55f, 0.43f, 0.23f, 0.14f};
    int n = 5;
    float ft = t * n;
    int   i  = std::min(n - 1, static_cast<int>(ft));
    float f  = ft - i;
    return Vec3(r[i]*(1-f)+r[i+1]*f, g[i]*(1-f)+g[i+1]*f, b[i]*(1-f)+b[i+1]*f);
}

// Kodak Aerochrome IR film aesthetic: vegetation (bright IR) → vivid red,
// sky/water (dark IR) → dark blue-cyan, mid tones → green.
static Vec3 apply_ir_false_colour(float t) {
    // dark=cyan(0,0.5,0.5) → mid=green(0,0.8,0.1) → bright=red(1,0.1,0.05)
    static const float r[] = {0.0f, 0.0f, 1.0f};
    static const float g[] = {0.5f, 0.8f, 0.1f};
    static const float b[] = {0.5f, 0.1f, 0.05f};
    int n = 2;
    float ft = t * n;
    int   i  = std::min(n - 1, static_cast<int>(ft));
    float f  = ft - i;
    return Vec3(r[i]*(1-f)+r[i+1]*f, g[i]*(1-f)+g[i+1]*f, b[i]*(1-f)+b[i+1]*f);
}

class ColourmapOutput : public Pass {
    std::string colourmap_;
public:
    explicit ColourmapOutput(const astroray::ParamDict& p)
        : colourmap_(p.getString("colourmap", "grayscale")) {}

    std::string name() const override { return "colourmap_output"; }

    void execute(Framebuffer& fb) override {
        float* color = fb.buffer("color");
        if (!color) return;
        int N = fb.width() * fb.height();
        for (int i = 0; i < N; ++i) {
            float* px = color + i * 3;
            // The multiwavelength integrator stored Vec3(L, L, L) in XYZ space.
            // After xyzToLinearSRGB, the result is approximately neutral grey.
            // Recover luminance as the mean of the three channels.
            float L = (px[0] + px[1] + px[2]) / 3.0f;
            L = std::max(0.0f, L);
            // Tone-map: simple Reinhard on the luminance.
            float L_tm = L / (1.0f + L);
            Vec3 mapped;
            if      (colourmap_ == "hot")             mapped = apply_hot(L_tm);
            else if (colourmap_ == "inferno")         mapped = apply_inferno(L_tm);
            else if (colourmap_ == "viridis")         mapped = apply_viridis(L_tm);
            else if (colourmap_ == "ir_false_colour") mapped = apply_ir_false_colour(L_tm);
            else                                       mapped = apply_grayscale(L_tm);
            px[0] = mapped.x;
            px[1] = mapped.y;
            px[2] = mapped.z;
        }
    }
};

ASTRORAY_REGISTER_PASS("colourmap_output", ColourmapOutput)
