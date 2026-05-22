// EXR writer for Cryptomatte passes
// Thin wrapper around OpenEXR — scoped to Cryptomatte needs.

#include "exr_writer.h"

#ifdef ASTRORAY_EXR_ENABLED  // defined by CMake when OpenEXR is found

#include <OpenEXR/ImfOutputFile.h>
#include <OpenEXR/ImfChannelList.h>
#include <OpenEXR/ImfFrameBuffer.h>
#include <OpenEXR/ImfHeader.h>
#include <OpenEXR/ImfStringAttribute.h>
#include <stdexcept>

namespace astroray {

void writeExr(const std::string& filepath,
              int width, int height,
              const std::vector<ExrChannel>& channels,
              const std::map<std::string, std::string>& header) {
    try {
        // Create EXR header
        Imf::Header exrHeader(width, height);

        // Add channels to header
        for (const auto& ch : channels) {
            exrHeader.channels().insert(ch.name.c_str(), Imf::Channel(Imf::FLOAT));
        }

        // Add string attributes to header
        for (const auto& [key, value] : header) {
            exrHeader.insert(key.c_str(), Imf::StringAttribute(value));
        }

        // Create output file
        Imf::OutputFile file(filepath.c_str(), exrHeader);

        // Build framebuffer
        Imf::FrameBuffer framebuffer;
        for (const auto& ch : channels) {
            framebuffer.insert(ch.name.c_str(),
                               Imf::Slice(Imf::FLOAT,
                                          (char*)ch.data,
                                          sizeof(float),
                                          sizeof(float) * width));
        }

        file.setFrameBuffer(framebuffer);
        file.writePixels(height);

    } catch (const std::exception& e) {
        throw std::runtime_error("Failed to write EXR: " + std::string(e.what()));
    }
}

} // namespace astroray

#else  // !ASTRORAY_EXR_ENABLED

namespace astroray {

void writeExr(const std::string&, int, int,
              const std::vector<ExrChannel>&,
              const std::map<std::string, std::string>&) {
    throw std::runtime_error("EXR writer not available — OpenEXR not found at build time");
}

} // namespace astroray

#endif  // ASTRORAY_EXR_ENABLED
