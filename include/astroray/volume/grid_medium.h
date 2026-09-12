// pkg267 — GridMedium: heterogeneous-volume grid representation backed by a
// vendored NanoVDB sparse grid (Apache-2.0; Museth 2021), plus a coarse majorant
// grid for delta/ratio tracking (pkg268/pkg269).
//
// DESIGN: this public header is deliberately NanoVDB-free. NanoVDB.h is enormous
// and must not leak into the widely-included raytracer.h, so every NanoVDB type
// is hidden behind a PIMPL and all NanoVDB code lives in the single TU
// src/volume/grid_medium.cpp. Point/majorant queries are therefore out-of-line
// calls — acceptable for the CPU correctness oracle (pkg268); the GPU stage
// (pkg269) reads the device NanoVDB grid directly.
//
// Research/citations: .astroray_plan/docs/pkg267-nanovdb-majorant-research.md.

#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <vector>

#include "astroray/volume/majorant_grid.h"

namespace astroray {
namespace volume {

// Grid transfer contract (addon -> engine). One attribute's dense payload over
// the ACTIVE-voxel bounding box of the source .vdb grid. C-order, x fastest:
// data[(z*dim[1] + y)*dim[0] + x] * components + c. v1 is dense-over-active-bbox
// (memory ceiling: dim[0]*dim[1]*dim[2]*components*4 bytes; a 512^3 scalar block
// is 512 MB — fine for the CPU oracle, sparse upload is a pkg269/pkg272 concern).
struct DenseGrid {
    std::vector<float> data;
    int dim[3] = {0, 0, 0};      // nx, ny, nz
    int bboxMin[3] = {0, 0, 0};  // index-space origin of the dense block
    int components = 1;          // 1 = scalar (density/temperature), 3 = vec3 (color/velocity)
};

// 4x4 row-major affine (matches Blender object.matrix_world / openvdb transform).
using Mat4 = std::array<float, 16>;

class GridMedium {
public:
    GridMedium();
    ~GridMedium();
    GridMedium(GridMedium&&) noexcept;
    GridMedium& operator=(GridMedium&&) noexcept;
    GridMedium(const GridMedium&) = delete;
    GridMedium& operator=(const GridMedium&) = delete;

    // Build the density NanoVDB grid + the majorant grid, and store the
    // index->object and object->world transforms. Background (0) voxels are
    // skipped when filling the sparse NanoVDB grid. `supervoxel` is the majorant
    // supervoxel edge in fine voxels (tunable; <=0 => default 16).
    void setDensity(const DenseGrid& density, const Mat4& indexToObject,
                    const Mat4& objectToWorld, int supervoxel = 0);

    // Passthrough attribute handles consumed later (pkg270). Stored, not built.
    void setTemperature(const DenseGrid& g);
    void setColor(const DenseGrid& g);
    void setVelocity(const DenseGrid& g);

    bool valid() const;

    // --- queries in index (voxel) space, absolute ijk ---
    // Nearest-voxel density lookup (0 outside the active block). Nearest (not
    // trilinear) in v1: the majorant then bounds the sampled σ_t exactly, which
    // keeps delta tracking unbiased. Trilinear is a later quality item.
    float densityIndex(float ix, float iy, float iz) const;

    // --- queries in world space ---
    float densityWorld(float wx, float wy, float wz) const;

    // Transforms (row-major 4x4).
    Mat4 indexToWorld() const;
    Mat4 worldToIndex() const;

    // World-space AABB of the active voxel block: {minx,miny,minz,maxx,maxy,maxz}.
    std::array<float, 6> worldAABB() const;

    std::array<int, 3> dims() const;
    std::array<int, 3> bboxMin() const;

    // Majorant grid (index space). The transport (pkg268) transforms the world
    // ray into index space (worldToIndex: origin via the full affine, direction
    // via the linear part only, NOT renormalised — t is preserved) and drives a
    // DDAMajorantIterator over this grid.
    const MajorantGrid& majorant() const;
    int supervoxelRes(int axis) const;
    // Max density within the supervoxel covering a world point (for tests).
    float majorantDensityWorld(float wx, float wy, float wz) const;

    // Transform a world point/direction into index space. Point uses the full
    // affine; direction uses the linear (upper-left 3x3) part only (t preserved).
    std::array<float, 3> worldPointToIndex(float wx, float wy, float wz) const;
    std::array<float, 3> worldDirToIndex(float dx, float dy, float dz) const;

    // --- passthrough accessors (pkg270) ---
    bool hasTemperature() const;
    float temperatureIndex(float ix, float iy, float iz) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace volume
}  // namespace astroray
