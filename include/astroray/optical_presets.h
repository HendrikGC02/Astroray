#pragma once

#include "raytracer.h"

#include <string>
#include <vector>

namespace astroray {

struct OpticalGlassPreset {
    const char* name;
    float ior;
    Vec3 sellmeierB;
    Vec3 sellmeierC;
    Vec3 transmissionTint;
    bool hasSellmeier;
};

inline const std::vector<OpticalGlassPreset>& opticalGlassPresets() {
    static const std::vector<OpticalGlassPreset> presets = {
        {"bk7", 1.5168f,
            {1.03961212f, 0.231792344f, 1.01046945f},
            {0.00600069867f, 0.0200179144f, 103.560653f},
            {1.0f, 1.0f, 1.0f}, true},
        {"fused_silica", 1.4585f,
            {0.6961663f, 0.4079426f, 0.8974794f},
            {0.0046791f, 0.0135121f, 97.9340f},
            {1.0f, 1.0f, 1.0f}, true},
        {"flint_sf11", 1.7847f,
            {1.73759695f, 0.313747346f, 1.89878101f},
            {0.013188707f, 0.0623068142f, 155.23629f},
            {1.0f, 1.0f, 1.0f}, true},
        {"diamond", 2.417f,
            {0.3306f, 4.3356f, 0.0f},
            {0.0175f, 0.1060f, 0.0f},
            {1.0f, 1.0f, 1.0f}, true},
        {"water", 1.333f,
            {0.0f, 0.0f, 0.0f},
            {0.0f, 0.0f, 0.0f},
            {0.88f, 0.97f, 1.0f}, false},
        {"ice", 1.309f,
            {0.0f, 0.0f, 0.0f},
            {0.0f, 0.0f, 0.0f},
            {0.92f, 0.98f, 1.0f}, false},
        {"sapphire", 1.77f,
            {0.0f, 0.0f, 0.0f},
            {0.0f, 0.0f, 0.0f},
            {0.62f, 0.76f, 1.0f}, false},
        {"ruby", 1.77f,
            {0.0f, 0.0f, 0.0f},
            {0.0f, 0.0f, 0.0f},
            {1.0f, 0.12f, 0.18f}, false},
        {"emerald", 1.58f,
            {0.0f, 0.0f, 0.0f},
            {0.0f, 0.0f, 0.0f},
            {0.10f, 0.92f, 0.45f}, false},
    };
    return presets;
}

inline const OpticalGlassPreset* findOpticalGlassPreset(const std::string& name) {
    for (const auto& preset : opticalGlassPresets()) {
        if (name == preset.name) return &preset;
    }
    return nullptr;
}

inline std::vector<std::string> opticalGlassPresetNames() {
    std::vector<std::string> names;
    names.reserve(opticalGlassPresets().size());
    for (const auto& preset : opticalGlassPresets()) names.emplace_back(preset.name);
    return names;
}

} // namespace astroray
