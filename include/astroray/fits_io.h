#pragma once
#include <vector>
#include <string>
#include <stdexcept>

// FITS file reader wrapper around cfitsio (NASA/HEASARC, public domain).
// Reference: cfitsio User's Guide v4.6 https://heasarc.gsfc.nasa.gov/fitsio/
// FITS Standard 4.0: https://fits.gsfc.nasa.gov/standard40/fits_standard40aa-le.pdf
//
// This wrapper provides RAII-safe access to FITS IMAGE HDUs and isolates the
// plugin code from cfitsio's C API.

#ifdef ASTRORAY_FITS_ENABLED

// Forward-declare cfitsio types to avoid leaking <fitsio.h> into plugin headers.
struct fitsfile;

namespace astroray {

class FITSFile {
public:
    // Open FITS file at given path. Throws std::runtime_error on failure.
    // Reference: cfitsio §5.3 fits_open_file()
    static FITSFile open(const std::string& path);

    // Close file. Called automatically by destructor (RAII).
    ~FITSFile();

    // Not copyable (owns fitsfile* resource).
    FITSFile(const FITSFile&) = delete;
    FITSFile& operator=(const FITSFile&) = delete;

    // Movable.
    FITSFile(FITSFile&& other) noexcept;
    FITSFile& operator=(FITSFile&& other) noexcept;

    // Number of axes (NAXIS keyword): 2 for images, 3 for data cubes.
    // Reference: cfitsio §5.6.2 fits_get_img_dim()
    int naxis() const;

    // Image shape [ny, nx] for 2D or [nz, ny, nx] for 3D.
    // FITS stores dimensions in Fortran order (fastest-varying first);
    // returned order matches C convention (slowest first).
    // Reference: cfitsio §5.6.2 fits_get_img_size()
    std::vector<long> shape() const;

    // Read header keyword as string. Returns empty string if not found.
    // Reference: cfitsio §5.7.1 fits_read_key()
    std::string header(const std::string& key) const;

    // Read entire image as float32. BSCALE/BZERO applied automatically by cfitsio.
    // Data returned in C order (slowest dimension first). For a 2D image [ny,nx],
    // pixel (i,j) is at data[i*nx + j]. For 3D [nz,ny,nx], pixel (k,i,j) is at
    // data[k*ny*nx + i*nx + j].
    // Reference: cfitsio §5.6.1 fits_read_pix() with datatype=TFLOAT
    std::vector<float> readFloat() const;

    // Move to HDU by 1-based index. Default is 1 (primary HDU).
    // Reference: cfitsio §5.5.2 fits_movabs_hdu()
    void moveToHDU(int hduIndex);

private:
    explicit FITSFile(fitsfile* fptr);
    fitsfile* fptr_ = nullptr;
};

} // namespace astroray

#endif // ASTRORAY_FITS_ENABLED
