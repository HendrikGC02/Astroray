#pragma once

#include <array>
#include <string>

namespace astroray {

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
