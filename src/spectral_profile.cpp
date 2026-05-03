#include "astroray/spectral_profile.h"
#include <cstdint>
#include <fstream>
#include <cstring>
#include <stdexcept>

namespace astroray {

SpectralProfileDatabase& SpectralProfileDatabase::instance() {
    static SpectralProfileDatabase db;
    return db;
}

void SpectralProfileDatabase::load(const std::string& path) {
    if (loaded_) return;

    std::ifstream f(path, std::ios::binary);
    if (!f) return;  // silently skip if file not found (profiles not required)

    // Header: 128 bytes
    char magic[4];
    f.read(magic, 4);
    if (std::memcmp(magic, "ASPR", 4) != 0) return;

    uint32_t version, n_mat, n_wl;
    float lmin, lmax, lstep;
    f.read(reinterpret_cast<char*>(&version), 4);
    f.read(reinterpret_cast<char*>(&n_mat),   4);
    f.read(reinterpret_cast<char*>(&n_wl),    4);
    f.read(reinterpret_cast<char*>(&lmin),    4);
    f.read(reinterpret_cast<char*>(&lmax),    4);
    f.read(reinterpret_cast<char*>(&lstep),   4);
    if (version != 1 || n_wl == 0 || n_mat == 0) return;
    f.ignore(100);  // reserved bytes

    // Directory: n_mat × 80 bytes
    struct DirEntry { char name[64]; uint16_t cat; uint16_t flags; uint32_t offset; uint64_t reserved; };
    std::vector<DirEntry> dir(n_mat);
    f.read(reinterpret_cast<char*>(dir.data()), static_cast<std::streamsize>(n_mat * sizeof(DirEntry)));

    // Read all float32 data for each material
    storage_.resize(n_mat * n_wl);
    for (uint32_t m = 0; m < n_mat; ++m) {
        f.seekg(dir[m].offset);
        f.read(reinterpret_cast<char*>(&storage_[m * n_wl]), static_cast<std::streamsize>(n_wl * sizeof(float)));
    }

    names_.reserve(n_mat);
    profiles_.reserve(n_mat);
    for (uint32_t m = 0; m < n_mat; ++m) {
        size_t nlen = 0;
        while (nlen < 64 && dir[m].name[nlen] != '\0') ++nlen;
        std::string name(dir[m].name, nlen);
        names_.push_back(name);
        profiles_.emplace_back(&storage_[m * n_wl], static_cast<int>(n_wl), lmin, lstep);
        index_[name] = static_cast<int>(m);
    }
    loaded_ = true;
}

const SpectralProfile* SpectralProfileDatabase::get(const std::string& name) const {
    auto it = index_.find(name);
    if (it == index_.end()) return nullptr;
    return &profiles_[it->second];
}

} // namespace astroray
