// EXR writer for Cryptomatte passes
// Scoped to Cryptomatte needs — not a general AOV writer.

#pragma once

#include <string>
#include <vector>
#include <map>

namespace astroray {

// Single channel specification
struct ExrChannel {
    std::string name;          // e.g. "CryptoObject00.R"
    const float* data;         // pointer to pixel data (row-major, width*height floats)
};

// Write multi-channel float32 EXR with string header attributes
// width, height: image dimensions
// channels: vector of named channels (each points to width*height floats)
// header: string key-value pairs to write as EXR header attributes
void writeExr(const std::string& filepath,
              int width, int height,
              const std::vector<ExrChannel>& channels,
              const std::map<std::string, std::string>& header);

} // namespace astroray
