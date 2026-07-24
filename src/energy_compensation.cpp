#include "astroray/energy_compensation.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <filesystem>
#include <fstream>

namespace astroray {

namespace {

template <std::size_t N>
bool readFloatTable(const std::filesystem::path& path, std::array<float, N>& out) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return false;
    file.read(reinterpret_cast<char*>(out.data()),
              static_cast<std::streamsize>(out.size() * sizeof(float)));
    return file.good() && file.peek() == std::ifstream::traits_type::eof();
}

std::filesystem::path resolveDataDirectory() {
    if (const char* env = std::getenv("ASTRORAY_DATA_DIR")) {
        if (*env) return std::filesystem::path(env);
    }
#ifdef ASTRORAY_DATA_DIR
    return std::filesystem::path(ASTRORAY_DATA_DIR);
#else
    return std::filesystem::path("data");
#endif
}

} // namespace

const DisneyEnergyCompensationTables& DisneyEnergyCompensationTables::instance() {
    static DisneyEnergyCompensationTables tables;
    return tables;
}

DisneyEnergyCompensationTables::DisneyEnergyCompensationTables() {
    ggxE_.fill(1.0f);
    ggxEavg_.fill(1.0f);
    sheenE_.fill(0.0f);
    clearcoatE_.fill(1.0f);
    ggxGlassE_.fill(1.0f);
    ggxGlassEavg_.fill(1.0f);
    ggxGlassInvE_.fill(1.0f);
    ggxGlassInvEavg_.fill(1.0f);
    loaded_ = load();
}

bool DisneyEnergyCompensationTables::load() {
    dataDirectory_ = resolveDataDirectory().string();
    const std::filesystem::path dir =
        std::filesystem::path(dataDirectory_) / "disney_compensation";

    return readFloatTable(dir / "ggx_E.bin", ggxE_) &&
           readFloatTable(dir / "ggx_Eavg.bin", ggxEavg_) &&
           readFloatTable(dir / "sheen_E.bin", sheenE_) &&
           readFloatTable(dir / "clearcoat_E.bin", clearcoatE_) &&
           readFloatTable(dir / "ggx_glass_E.bin", ggxGlassE_) &&
           readFloatTable(dir / "ggx_glass_Eavg.bin", ggxGlassEavg_) &&
           readFloatTable(dir / "ggx_glass_inv_E.bin", ggxGlassInvE_) &&
           readFloatTable(dir / "ggx_glass_inv_Eavg.bin", ggxGlassInvEavg_);
}

template <std::size_t N>
float DisneyEnergyCompensationTables::sample2D(
        const std::array<float, N>& table,
        int size, float roughness, float mu) const {
    roughness = std::clamp(roughness, 0.0f, 1.0f);
    mu = std::clamp(mu, 0.0f, 1.0f);

    const float x = roughness * float(size - 1);
    const float y = mu * float(size - 1);
    const int x0 = std::clamp(static_cast<int>(x), 0, size - 1);
    const int y0 = std::clamp(static_cast<int>(y), 0, size - 1);
    const int x1 = std::min(x0 + 1, size - 1);
    const int y1 = std::min(y0 + 1, size - 1);
    const float tx = x - float(x0);
    const float ty = y - float(y0);

    const float v00 = table[y0 * size + x0];
    const float v10 = table[y0 * size + x1];
    const float v01 = table[y1 * size + x0];
    const float v11 = table[y1 * size + x1];
    const float vx0 = v00 * (1.0f - tx) + v10 * tx;
    const float vx1 = v01 * (1.0f - tx) + v11 * tx;
    return vx0 * (1.0f - ty) + vx1 * ty;
}

template <std::size_t N>
float DisneyEnergyCompensationTables::sample1D(
        const std::array<float, N>& table, int size, float x) const {
    x = std::clamp(x, 0.0f, 1.0f);
    const float fx = x * float(size - 1);
    const int x0 = std::clamp(static_cast<int>(fx), 0, size - 1);
    const int x1 = std::min(x0 + 1, size - 1);
    const float t = fx - float(x0);
    return table[x0] * (1.0f - t) + table[x1] * t;
}

// pkg151: trilinear lookup mirroring Cycles' lookup_table_read_3D (kernel/
// util/lookup_table.h) — roughness (x) is the fastest-varying axis, then mu
// (y), then z (z), matching the .bin extraction order (no transpose).
template <std::size_t N>
float DisneyEnergyCompensationTables::sample3D(
        const std::array<float, N>& table, int size,
        float roughness, float mu, float z) const {
    roughness = std::clamp(roughness, 0.0f, 1.0f);
    mu = std::clamp(mu, 0.0f, 1.0f);
    z = std::clamp(z, 0.0f, 1.0f);

    const float fx = roughness * float(size - 1);
    const float fy = mu * float(size - 1);
    const float fz = z * float(size - 1);
    const int x0 = std::clamp(static_cast<int>(fx), 0, size - 1);
    const int y0 = std::clamp(static_cast<int>(fy), 0, size - 1);
    const int z0 = std::clamp(static_cast<int>(fz), 0, size - 1);
    const int x1 = std::min(x0 + 1, size - 1);
    const int y1 = std::min(y0 + 1, size - 1);
    const int z1 = std::min(z0 + 1, size - 1);
    const float tx = fx - float(x0);
    const float ty = fy - float(y0);
    const float tz = fz - float(z0);

    auto at = [&](int xi, int yi, int zi) {
        return table[(std::size_t(zi) * size + yi) * size + xi];
    };
    auto lerp = [](float a, float b, float t) { return a * (1.0f - t) + b * t; };

    const float c00 = lerp(at(x0, y0, z0), at(x1, y0, z0), tx);
    const float c10 = lerp(at(x0, y1, z0), at(x1, y1, z0), tx);
    const float c01 = lerp(at(x0, y0, z1), at(x1, y0, z1), tx);
    const float c11 = lerp(at(x0, y1, z1), at(x1, y1, z1), tx);
    const float c0 = lerp(c00, c10, ty);
    const float c1 = lerp(c01, c11, ty);
    return lerp(c0, c1, tz);
}

float DisneyEnergyCompensationTables::ggxE(float roughness, float mu) const {
    return sample2D(ggxE_, kGgxSize, roughness, mu);
}

float DisneyEnergyCompensationTables::ggxEavg(float roughness) const {
    return sample1D(ggxEavg_, kGgxSize, roughness);
}

float DisneyEnergyCompensationTables::sheenAlbedo(float roughness, float mu) const {
    return sample2D(sheenE_, kSheenSize, roughness, mu);
}

float DisneyEnergyCompensationTables::clearcoatE(float mu) const {
    return sample1D(clearcoatE_, kClearcoatSize, mu);
}

namespace {
// Cycles bsdf_microfacet.h microfacet_ggx_preserve_energy glass branch
// (BSD-3-Clause): z = sqrt(|ior-1|/(ior+1)) parameterizes the ior axis so a
// 16-entry table can span both eta and 1/eta.
float glassZFromIOR(float iorEffective) {
    return std::sqrt(std::abs((iorEffective - 1.0f) / (iorEffective + 1.0f)));
}
} // namespace

float DisneyEnergyCompensationTables::ggxGlassE(float roughness, float mu, float ior) const {
    const bool inv = ior < 1.0f;
    const float iorEff = inv ? (1.0f / ior) : ior;
    const float z = glassZFromIOR(iorEff);
    return inv ? sample3D(ggxGlassInvE_, kGlassSize, roughness, mu, z)
               : sample3D(ggxGlassE_, kGlassSize, roughness, mu, z);
}

float DisneyEnergyCompensationTables::ggxGlassEavg(float roughness, float ior) const {
    const bool inv = ior < 1.0f;
    const float iorEff = inv ? (1.0f / ior) : ior;
    const float z = glassZFromIOR(iorEff);
    return inv ? sample2D(ggxGlassInvEavg_, kGlassSize, roughness, z)
               : sample2D(ggxGlassEavg_, kGlassSize, roughness, z);
}

} // namespace astroray
