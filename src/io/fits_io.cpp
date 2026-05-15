#include "astroray/fits_io.h"

#ifdef ASTRORAY_FITS_ENABLED

#include <fitsio.h>
#include <cstring>

namespace astroray {

// Helper: throw runtime_error with cfitsio status message.
[[noreturn]] static void throwFITSError(int status, const std::string& context) {
    char err_text[FLEN_STATUS];
    fits_get_errstatus(status, err_text);
    throw std::runtime_error(context + ": " + err_text);
}

FITSFile FITSFile::open(const std::string& path) {
    fitsfile* fptr = nullptr;
    int status = 0;
    // READONLY = 0 per cfitsio documentation §5.3
    fits_open_file(&fptr, path.c_str(), 0 /*READONLY*/, &status);
    if (status != 0) {
        throwFITSError(status, "Failed to open FITS file: " + path);
    }
    return FITSFile(fptr);
}

FITSFile::FITSFile(fitsfile* fptr) : fptr_(fptr) {}

FITSFile::~FITSFile() {
    if (fptr_) {
        int status = 0;
        fits_close_file(fptr_, &status);
        // Destructor must not throw; log error if close fails.
        if (status != 0) {
            // In production, log to stderr or a logger. For now, silent.
        }
    }
}

FITSFile::FITSFile(FITSFile&& other) noexcept : fptr_(other.fptr_) {
    other.fptr_ = nullptr;
}

FITSFile& FITSFile::operator=(FITSFile&& other) noexcept {
    if (this != &other) {
        if (fptr_) {
            int status = 0;
            fits_close_file(fptr_, &status);
        }
        fptr_ = other.fptr_;
        other.fptr_ = nullptr;
    }
    return *this;
}

int FITSFile::naxis() const {
    int n = 0, status = 0;
    fits_get_img_dim(fptr_, &n, &status);
    if (status != 0) {
        throwFITSError(status, "fits_get_img_dim failed");
    }
    return n;
}

std::vector<long> FITSFile::shape() const {
    int n = naxis();
    std::vector<long> naxes(n);
    int status = 0;
    fits_get_img_size(fptr_, n, naxes.data(), &status);
    if (status != 0) {
        throwFITSError(status, "fits_get_img_size failed");
    }
    // cfitsio returns Fortran order (fastest first); reverse to C order (slowest first).
    std::reverse(naxes.begin(), naxes.end());
    return naxes;
}

std::string FITSFile::header(const std::string& key) const {
    char value[FLEN_VALUE];
    int status = 0;
    fits_read_key(fptr_, TSTRING, key.c_str(), value, nullptr, &status);
    if (status == KEY_NO_EXIST) {
        return "";
    }
    if (status != 0) {
        throwFITSError(status, "fits_read_key failed for key: " + key);
    }
    return std::string(value);
}

std::vector<float> FITSFile::readFloat() const {
    auto dims = shape();
    long long nelements = 1;
    for (long d : dims) {
        nelements *= d;
    }

    std::vector<float> data(static_cast<size_t>(nelements));
    int status = 0;
    int anynul = 0;
    // fpixel: 1-based starting pixel (all axes start at 1).
    // TFLOAT = 42 (float datatype constant from cfitsio).
    // cfitsio applies BSCALE/BZERO automatically when reading to float.
    long fpixel[3] = {1, 1, 1};
    fits_read_pix(fptr_, TFLOAT, fpixel, nelements, nullptr, data.data(), &anynul, &status);
    if (status != 0) {
        throwFITSError(status, "fits_read_pix failed");
    }

    // Data now in Fortran order (x varies fastest). Need to transpose to C order.
    // For 2D [ny, nx]: Fortran stores column-major; C expects row-major.
    // For 3D [nz, ny, nx]: similar transposition needed.
    int n = static_cast<int>(dims.size());
    if (n == 2) {
        // 2D transpose: Fortran [nx, ny] → C [ny, nx]
        long nx = dims[1], ny = dims[0];
        std::vector<float> transposed(data.size());
        for (long j = 0; j < ny; ++j) {
            for (long i = 0; i < nx; ++i) {
                transposed[j * nx + i] = data[i * ny + j];
            }
        }
        return transposed;
    } else if (n == 3) {
        // 3D transpose: Fortran [nx, ny, nz] → C [nz, ny, nx]
        long nx = dims[2], ny = dims[1], nz = dims[0];
        std::vector<float> transposed(data.size());
        for (long k = 0; k < nz; ++k) {
            for (long j = 0; j < ny; ++j) {
                for (long i = 0; i < nx; ++i) {
                    transposed[k * ny * nx + j * nx + i] = data[i * ny * nz + j * nz + k];
                }
            }
        }
        return transposed;
    } else {
        // For 1D or higher-dim, return as-is (spec only requires 2D/3D support).
        return data;
    }
}

void FITSFile::moveToHDU(int hduIndex) {
    int hdutype = 0, status = 0;
    fits_movabs_hdu(fptr_, hduIndex, &hdutype, &status);
    if (status != 0) {
        throwFITSError(status, "fits_movabs_hdu failed for index " + std::to_string(hduIndex));
    }
}

} // namespace astroray

#endif // ASTRORAY_FITS_ENABLED
