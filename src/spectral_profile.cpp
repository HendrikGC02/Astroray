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
    // File-loaded profiles take precedence; runtime profiles register under
    // distinct __blend__/... names (Stage C), so collisions are not expected.
    auto it = index_.find(name);
    if (it != index_.end()) return &profiles_[it->second];
    auto rit = runtimeIndex_.find(name);
    if (rit != runtimeIndex_.end()) return &runtimeProfiles_[rit->second];
    return nullptr;
}

const SpectralProfile* SpectralProfileDatabase::registerProfile(
        const std::string& name, float lambda_min_nm, float lambda_step_nm,
        const std::vector<float>& values) {
    if (values.empty() || lambda_step_nm <= 0.0f) return nullptr;

    auto rit = runtimeIndex_.find(name);
    if (rit != runtimeIndex_.end()) {
        // Overwrite in place: keep the deque slot address stable so any cached
        // SpectralProfile* held by a material stays valid; only the underlying
        // sample buffer moves, and the view is rebuilt over it.
        int ri = rit->second;
        runtimeStorage_[ri] = values;
        runtimeProfiles_[ri] = SpectralProfile(
            runtimeStorage_[ri].data(), static_cast<int>(values.size()),
            lambda_min_nm, lambda_step_nm);
        return &runtimeProfiles_[ri];
    }

    // New slot: deque push_back never invalidates existing element addresses.
    runtimeStorage_.push_back(values);
    int ri = static_cast<int>(runtimeStorage_.size()) - 1;
    runtimeProfiles_.emplace_back(
        runtimeStorage_[ri].data(), static_cast<int>(values.size()),
        lambda_min_nm, lambda_step_nm);
    runtimeIndex_[name] = ri;
    return &runtimeProfiles_[ri];
}

std::vector<std::string> SpectralProfileDatabase::names() const {
    std::vector<std::string> all = names_;              // file order first
    all.reserve(names_.size() + runtimeIndex_.size());
    // Append runtime names in registration order (deque index order).
    std::vector<std::string> runtimeOrdered(runtimeIndex_.size());
    for (const auto& kv : runtimeIndex_) runtimeOrdered[kv.second] = kv.first;
    for (auto& n : runtimeOrdered) all.push_back(std::move(n));
    return all;
}

} // namespace astroray
