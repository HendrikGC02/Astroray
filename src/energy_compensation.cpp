#include "astroray/energy_compensation.h"

#include <algorithm>
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
    loaded_ = load();
}

bool DisneyEnergyCompensationTables::load() {
    dataDirectory_ = resolveDataDirectory().string();
    const std::filesystem::path dir =
        std::filesystem::path(dataDirectory_) / "disney_compensation";

    return readFloatTable(dir / "ggx_E.bin", ggxE_) &&
           readFloatTable(dir / "ggx_Eavg.bin", ggxEavg_) &&
           readFloatTable(dir / "sheen_E.bin", sheenE_) &&
           readFloatTable(dir / "clearcoat_E.bin", clearcoatE_);
}

float DisneyEnergyCompensationTables::sample2D(
        const std::array<float, kGgxSize * kGgxSize>& table,
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

float DisneyEnergyCompensationTables::sample1D(
        const std::array<float, kGgxSize>& table, int size, float x) const {
    x = std::clamp(x, 0.0f, 1.0f);
    const float fx = x * float(size - 1);
    const int x0 = std::clamp(static_cast<int>(fx), 0, size - 1);
    const int x1 = std::min(x0 + 1, size - 1);
    const float t = fx - float(x0);
    return table[x0] * (1.0f - t) + table[x1] * t;
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

} // namespace astroray
