# ASPR Binary Format — Spectral Profile Database

**Magic:** `ASPR`  ("Astroray SPectral Reflectance")  
**Version:** 1  
**File:** `data/spectral_profiles/profiles.bin`

---

## Layout

```
[Header 128 bytes]
[Directory n_materials × 80 bytes]
[Data section: n_materials × n_wavelengths × float32]
```

---

## Header (128 bytes)

| Offset | Type | Field | Value |
|--------|------|-------|-------|
| 0 | char[4] | magic | `ASPR` |
| 4 | uint32 | version | 1 |
| 8 | uint32 | n_materials | number of materials |
| 12 | uint32 | n_wavelengths | 441 |
| 16 | float32 | lambda_min_nm | 300.0 |
| 20 | float32 | lambda_max_nm | 2500.0 |
| 24 | float32 | lambda_step_nm | 5.0 |
| 28 | byte[100] | reserved | zeros |

All multi-byte integers are little-endian.

---

## Material Directory (n_materials × 80 bytes each)

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0 | char[64] | name | null-terminated UTF-8 material name |
| 64 | uint16 | category_id | see Category IDs below |
| 66 | uint16 | flags | reserved, currently 0 |
| 68 | uint32 | data_offset | byte offset into the file where this material's float32 array begins |
| 72 | uint64 | reserved | zeros |

The directory immediately follows the header at byte offset 128.

### Category IDs

| ID | Name |
|----|------|
| 0 | vegetation |
| 1 | earth |
| 2 | building |
| 3 | metal |
| 4 | fabric |
| 5 | paint |
| 6 | human |
| 7 | other |

---

## Data Section

Each material's data is a contiguous array of `n_wavelengths` `float32` values in
little-endian order.  `data_offset` in the directory entry points to the first byte
of this array.

Values represent hemispherical reflectance in `[0, 1]`.  The wavelength for the
i-th value is:

```
lambda_nm = lambda_min_nm + i * lambda_step_nm
```

So index 0 = 300 nm, index 1 = 305 nm, ..., index 440 = 2500 nm.

---

## C++ Loader Sketch (for pkg39)

```cpp
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <string>
#include <fstream>

struct AsprHeader {
    char     magic[4];
    uint32_t version;
    uint32_t n_materials;
    uint32_t n_wavelengths;
    float    lambda_min_nm;
    float    lambda_max_nm;
    float    lambda_step_nm;
    uint8_t  reserved[100];
};
static_assert(sizeof(AsprHeader) == 128);

struct AsprDirEntry {
    char     name[64];
    uint16_t category_id;
    uint16_t flags;
    uint32_t data_offset;
    uint64_t reserved;
};
static_assert(sizeof(AsprDirEntry) == 80);

struct SpectralMaterial {
    std::string              name;
    uint16_t                 category;
    std::vector<float>       reflectance;  // n_wavelengths floats
};

std::vector<SpectralMaterial> load_aspr(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot open " + path);

    AsprHeader hdr;
    f.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    if (std::memcmp(hdr.magic, "ASPR", 4) != 0)
        throw std::runtime_error("Invalid ASPR magic");
    if (hdr.version != 1)
        throw std::runtime_error("Unsupported ASPR version");

    std::vector<AsprDirEntry> dir(hdr.n_materials);
    f.read(reinterpret_cast<char*>(dir.data()),
           hdr.n_materials * sizeof(AsprDirEntry));

    std::vector<SpectralMaterial> out;
    out.reserve(hdr.n_materials);
    for (auto& e : dir) {
        SpectralMaterial m;
        m.name     = e.name;
        m.category = e.category_id;
        m.reflectance.resize(hdr.n_wavelengths);
        f.seekg(e.data_offset);
        f.read(reinterpret_cast<char*>(m.reflectance.data()),
               hdr.n_wavelengths * sizeof(float));
        out.push_back(std::move(m));
    }
    return out;
}

// Query reflectance at an arbitrary wavelength (linear interpolation)
float sample_reflectance(const SpectralMaterial& mat,
                         float lambda_nm,
                         float lambda_min, float lambda_step,
                         int   n_wavelengths)
{
    float t = (lambda_nm - lambda_min) / lambda_step;
    int   i = static_cast<int>(t);
    float f = t - i;
    if (i < 0) return mat.reflectance[0];
    if (i >= n_wavelengths - 1) return mat.reflectance[n_wavelengths - 1];
    return mat.reflectance[i] * (1.0f - f) + mat.reflectance[i + 1] * f;
}
```

---

## Python Reader Sketch

```python
import struct
import numpy as np

def load_aspr(path):
    with open(path, 'rb') as f:
        magic, version, n_mat, n_wl, lmin, lmax, lstep = \
            struct.unpack_from('<4sIIIfff', f.read(128))
        assert magic == b'ASPR' and version == 1

        wl = np.linspace(lmin, lmax, n_wl)  # nm

        materials = []
        dirs = [struct.unpack_from('<64sHHIQ', f.read(80)) for _ in range(n_mat)]

        for (name_b, cat_id, flags, offset, _) in dirs:
            name = name_b.rstrip(b'\x00').decode('utf-8')
            f.seek(offset)
            r = np.frombuffer(f.read(n_wl * 4), dtype='<f4').copy()
            materials.append({'name': name, 'category': cat_id, 'r': r})

    return wl, materials
```
