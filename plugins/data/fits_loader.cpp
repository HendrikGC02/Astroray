#include "astroray/register.h"
#include "astroray/fits_io.h"
#include "advanced_features.h"
#include <stdexcept>

#ifdef ASTRORAY_FITS_ENABLED

namespace astroray {

// 2D FITS texture loader. Reads a FITS IMAGE HDU and exposes it as a texture.
// Reference: FITS Standard 4.0 §3 (IMAGE extension)
class FITSTexture : public ImageTexture {
public:
    explicit FITSTexture(const ParamDict& p) {
        std::string path = p.getString("path", "");
        if (path.empty()) {
            throw std::runtime_error("FITSTexture: missing 'path' parameter");
        }

        int hduIndex = p.getInt("hdu", 1);  // 1-based, default to primary HDU

        try {
            FITSFile fits = FITSFile::open(path);
            if (hduIndex > 1) {
                fits.moveToHDU(hduIndex);
            }

            int n = fits.naxis();
            if (n != 2) {
                throw std::runtime_error("FITSTexture: expected 2D image (NAXIS=2), got NAXIS=" +
                                         std::to_string(n));
            }

            auto shape = fits.shape();
            int ny = static_cast<int>(shape[0]);
            int nx = static_cast<int>(shape[1]);

            auto raw = fits.readFloat();
            if (raw.size() != static_cast<size_t>(ny * nx)) {
                throw std::runtime_error("FITSTexture: shape mismatch");
            }

            // Convert float data to Vec3 (grayscale → RGB by replication).
            std::vector<Vec3> data(raw.size());
            for (size_t i = 0; i < raw.size(); ++i) {
                float v = raw[i];
                data[i] = Vec3(v, v, v);
            }

            setData(data, nx, ny);
        } catch (const std::exception& e) {
            throw std::runtime_error(std::string("FITSTexture failed to load '") +
                                     path + "': " + e.what());
        }
    }
};

// 3D FITS volume loader (stub for now; full volume rendering in pkg48).
// Reads a FITS data cube (NAXIS=3) and stores the raw grid.
// Reference: FITS Standard 4.0 §3, pillar4-data-io-research.md §2
class FITSVolume {
public:
    explicit FITSVolume(const ParamDict& p) {
        std::string path = p.getString("path", "");
        if (path.empty()) {
            throw std::runtime_error("FITSVolume: missing 'path' parameter");
        }

        int hduIndex = p.getInt("hdu", 1);

        try {
            FITSFile fits = FITSFile::open(path);
            if (hduIndex > 1) {
                fits.moveToHDU(hduIndex);
            }

            int n = fits.naxis();
            if (n != 3) {
                throw std::runtime_error("FITSVolume: expected 3D cube (NAXIS=3), got NAXIS=" +
                                         std::to_string(n));
            }

            auto shape = fits.shape();
            nz_ = static_cast<int>(shape[0]);
            ny_ = static_cast<int>(shape[1]);
            nx_ = static_cast<int>(shape[2]);

            data_ = fits.readFloat();
            if (data_.size() != static_cast<size_t>(nz_ * ny_ * nx_)) {
                throw std::runtime_error("FITSVolume: shape mismatch");
            }

            // Store metadata if available
            objectName_ = fits.header("OBJECT");
        } catch (const std::exception& e) {
            throw std::runtime_error(std::string("FITSVolume failed to load '") +
                                     path + "': " + e.what());
        }
    }

    int nx() const { return nx_; }
    int ny() const { return ny_; }
    int nz() const { return nz_; }
    const std::vector<float>& data() const { return data_; }
    const std::string& objectName() const { return objectName_; }

private:
    int nx_ = 0, ny_ = 0, nz_ = 0;
    std::vector<float> data_;
    std::string objectName_;
};

} // namespace astroray

ASTRORAY_REGISTER_TEXTURE("fits_texture", astroray::FITSTexture)

// FITSVolume is not a Texture, so no ASTRORAY_REGISTER_TEXTURE for it.
// It will be accessed via a Python API function (load_fits_volume) exposed
// in blender_module.cpp.

#endif // ASTRORAY_FITS_ENABLED
