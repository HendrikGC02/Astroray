#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <string>

namespace astroray {

// GGX multiple-scattering energy compensation, per-channel.
//
// Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks"
// (ACM SIGGRAPH 2017 Courses, DOI 10.1145/3084873.3084893) Eq. 6-9, in the
// exact form Blender Cycles ships as `microfacet_ggx_preserve_energy`
// (intern/cycles/kernel/closure/bsdf_microfacet.h:389-436, BSD-3-Clause):
//
//     missing_factor = (1 - E) / E
//     energy_scale   = 1 / E
//     Fms            = Fss * Eavg / (1 - Fss * (1 - Eavg))
//     darkening      = (1 + Fms * missing_factor) / energy_scale
//
// Cycles applies `energy_scale` to eval/sample and `darkening` to the closure
// weight; the NET factor on the single-scatter lobe is their product,
// `1 + Fms * (1 - E) / E`, which is what this returns.
//
// `f` is one channel of the lobe's single-scattering Fresnel reflectance
// (Cycles' `Fss`); `E` / `Eavg` are the GGX directional / cosine-averaged
// albedo read from data/disney_compensation/ggx_E{,avg}.bin (extracted from
// Cycles' table_ggx_E / table_ggx_Eavg, intern/cycles/scene/shader.tables,
// Apache-2.0). The result is MULTIPLICATIVE on the single-scatter lobe, so it
// inherits whatever cosine the caller's single-scatter term already carries
// (AGENTS.md: `Material::eval()` returns brdf * NdotL).
//
// pkg160: this is the single host definition. plugins/materials/disney.cpp
// (dielectric/metallic specular lobe) and plugins/materials/metal.cpp
// (conductor lobe) both call it; the device twin is `gpu_ggxDarkeningChannel`
// (include/astroray/gpu_ggx_tables.cuh) and must stay byte-identical to it.
inline float ggxDarkeningChannel(float f, float E, float Eavg) {
    f = std::clamp(f, 0.0f, 0.999f);
    const float missingFactor = (1.0f - E) / E;
    const float denom = std::max(1.0f - f * (1.0f - Eavg), 1e-4f);
    const float Fms = f * Eavg / denom;
    return 1.0f + Fms * missingFactor;
}

class DisneyEnergyCompensationTables {
public:
    static constexpr int kGgxSize = 32;
    static constexpr int kSheenSize = 32;
    static constexpr int kClearcoatSize = 32;
    // pkg151: Cycles' glass (rough dielectric transmission) multi-scatter
    // tables are baked at 16-resolution (table_ggx_glass_E[16*16*16] etc.),
    // NOT kGgxSize=32 — a distinct constant, do not reuse kGgxSize here.
    static constexpr int kGlassSize = 16;

    static const DisneyEnergyCompensationTables& instance();

    bool loaded() const { return loaded_; }
    const std::string& dataDirectory() const { return dataDirectory_; }

    float ggxE(float roughness, float mu) const;
    float ggxEavg(float roughness) const;
    float sheenAlbedo(float roughness, float mu) const;
    float clearcoatE(float mu) const;

    // pkg151: rough-transmission (glass) multi-scatter compensation lookup.
    // Cycles bsdf_microfacet.h microfacet_ggx_preserve_energy glass branch
    // (BSD-3-Clause): the ior axis is remapped to z = sqrt(|ior-1|/(ior+1))
    // and the lookup swaps to the _inv_ tables when ior < 1 (the exit-
    // refraction direction, looked up at ior'=1/ior) — both handled here so
    // callers just pass the raw eta (etap) they already compute.
    float ggxGlassE(float roughness, float mu, float ior) const;
    float ggxGlassEavg(float roughness, float ior) const;

    // Raw table pointers for the GPU upload path (cuda_renderer.cu); host-side
    // only, mirrors the Jakob-Hanika LUT upload convention in
    // src/gpu/gpu_spectral_tables.cu.
    const float* ggxGlassEData() const { return ggxGlassE_.data(); }
    const float* ggxGlassEavgData() const { return ggxGlassEavg_.data(); }
    const float* ggxGlassInvEData() const { return ggxGlassInvE_.data(); }
    const float* ggxGlassInvEavgData() const { return ggxGlassInvEavg_.data(); }

    // pkg152: GPU upload accessors for the reflection-lobe (metal/dielectric-
    // specular) multi-scatter tables, mirroring the pkg151 glass-table
    // accessors above. Back the CPU ggxCompensationFactor/ggxDirectionalAlbedo
    // (spec), sheenAlbedo (sheen), and clearcoatE (clearcoat) lookups used by
    // disney.cpp::eval() -- gpu_disney_eval never applied any of these terms
    // before this package (confirmed absent by grep of gpu_materials.h prior
    // to this change).
    const float* ggxEData() const { return ggxE_.data(); }
    const float* ggxEavgData() const { return ggxEavg_.data(); }
    const float* sheenEData() const { return sheenE_.data(); }
    const float* clearcoatEData() const { return clearcoatE_.data(); }

private:
    DisneyEnergyCompensationTables();

    bool load();

    template <std::size_t N>
    float sample2D(const std::array<float, N>& table, int size, float roughness, float mu) const;
    template <std::size_t N>
    float sample1D(const std::array<float, N>& table, int size, float x) const;
    // pkg151: trilinear lookup for the 16^3 glass E table. `size` is the
    // per-axis resolution (kGlassSize); axis order matches Cycles'
    // lookup_table_read_3D(kg, rough, mu, z, ...): rough fastest-varying (x),
    // then mu (y), then z (z) — the extracted .bin files preserve this order.
    template <std::size_t N>
    float sample3D(const std::array<float, N>& table, int size,
                   float roughness, float mu, float z) const;

    std::array<float, kGgxSize * kGgxSize> ggxE_{};
    std::array<float, kGgxSize> ggxEavg_{};
    std::array<float, kSheenSize * kSheenSize> sheenE_{};
    std::array<float, kClearcoatSize> clearcoatE_{};
    std::array<float, kGlassSize * kGlassSize * kGlassSize> ggxGlassE_{};
    std::array<float, kGlassSize * kGlassSize> ggxGlassEavg_{};
    std::array<float, kGlassSize * kGlassSize * kGlassSize> ggxGlassInvE_{};
    std::array<float, kGlassSize * kGlassSize> ggxGlassInvEavg_{};
    std::string dataDirectory_;
    bool loaded_ = false;
};

} // namespace astroray
