// pkg267 — Coarse majorant grid + DDA segment iterator for heterogeneous-volume
// delta/ratio tracking.
//
// Clean-room re-implementation of the pbrt-v4 "DDA Majorant Iterator"
// (pbrt-v4 §11.4.2; reference structure `src/pbrt/media.h` `struct MajorantGrid`
// + `class DDAMajorantIterator`, Apache-2.0). Cited per CLAUDE.md §6; research
// note: .astroray_plan/docs/pkg267-nanovdb-majorant-research.md.
//
// This header is intentionally lightweight (no NanoVDB, no raytracer.h) so it can
// be included by the public `grid_medium.h` and, later, by the CPU integrator and
// the GPU stage without dragging NanoVDB.h into widely-included translation units.
//
// Coordinate convention: the grid lives in the density grid's INDEX space. The
// bounding box is [bboxMin, bboxMin + dim] in voxel units. A ray handed to the
// iterator is the world ray transformed into index space KEEPING its original t
// parameter (origin through the full affine, direction through the linear part
// only, NOT renormalised) — so the `t` values returned by the iterator are the
// same world-space ray parameters the caller samples free flights against. This
// matches pbrt transforming the ray into the medium's local space and preserving
// t (pbrt-v4 §11.4.2).

#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace astroray {
namespace volume {

// Coarse per-supervoxel upper bound on density (σ_t = density · extinction(λ),
// extinction ≥ 0 constant per medium, so max-density is a true σ_t majorant once
// scaled by the caller — pkg268). Values live in the fine grid's index space.
class MajorantGrid {
public:
    MajorantGrid() = default;

    // dim    : fine grid resolution (nx,ny,nz)
    // bboxMin: index-space origin of the fine block
    // res    : supervoxel resolution (each >= 1)
    MajorantGrid(const int dim[3], const int bboxMin[3], const int res[3]) {
        for (int a = 0; a < 3; ++a) {
            dim_[a] = dim[a];
            bboxMin_[a] = bboxMin[a];
            res_[a] = std::max(1, res[a]);
            // index-space bounds of the fine block
            boundsMin_[a] = float(bboxMin[a]);
            boundsMax_[a] = float(bboxMin[a] + dim[a]);
        }
        voxels_.assign(size_t(res_[0]) * res_[1] * res_[2], 0.0f);
    }

    int res(int a) const { return res_[a]; }
    float boundsMin(int a) const { return boundsMin_[a]; }
    float boundsMax(int a) const { return boundsMax_[a]; }

    float lookup(int x, int y, int z) const {
        return voxels_[size_t(x) + res_[0] * (size_t(y) + size_t(res_[1]) * z)];
    }
    void accumulateMax(int x, int y, int z, float v) {
        float& slot = voxels_[size_t(x) + res_[0] * (size_t(y) + size_t(res_[1]) * z)];
        slot = std::max(slot, v);
    }

    // Map a fine index-space coordinate (absolute ijk) to its supervoxel index.
    void supervoxelOf(float ix, float iy, float iz, int out[3]) const {
        const float p[3] = {ix, iy, iz};
        for (int a = 0; a < 3; ++a) {
            float rel = (p[a] - boundsMin_[a]) / (boundsMax_[a] - boundsMin_[a]);
            int s = int(rel * res_[a]);
            out[a] = std::clamp(s, 0, res_[a] - 1);
        }
    }

    float globalMax() const {
        float m = 0.0f;
        for (float v : voxels_) m = std::max(m, v);
        return m;
    }

private:
    int dim_[3] = {0, 0, 0};
    int bboxMin_[3] = {0, 0, 0};
    int res_[3] = {1, 1, 1};
    float boundsMin_[3] = {0, 0, 0};
    float boundsMax_[3] = {0, 0, 0};
    std::vector<float> voxels_;
};

// One homogeneous-majorant segment of a ray: on [tMin,tMax] the density is
// bounded above by `majorant` (scale by extinction(λ) for σ_t).
struct MajorantSegment {
    float tMin;
    float tMax;
    float majorant;
};

// 3D DDA over the majorant grid, clean-room from pbrt-v4 `DDAMajorantIterator`
// (§11.4.2, Apache-2.0). `o`/`d` are the index-space ray (see file header); the
// returned segment t-values equal the caller's world-ray t.
class DDAMajorantIterator {
public:
    DDAMajorantIterator() = default;

    DDAMajorantIterator(const MajorantGrid* grid, const float o[3], const float d[3],
                        float tMin, float tMax)
        : grid_(grid), tMin_(tMin), tMax_(tMax) {
        float diag[3], rayO[3], rayD[3];
        for (int a = 0; a < 3; ++a) {
            diag[a] = grid->boundsMax(a) - grid->boundsMin(a);
            // normalise into [0,1]^3 across the grid (pbrt bounds.Offset)
            rayO[a] = (o[a] - grid->boundsMin(a)) / diag[a];
            rayD[a] = d[a] / diag[a];
        }
        for (int a = 0; a < 3; ++a) {
            float gridIntersect = rayO[a] + tMin * rayD[a];
            voxel_[a] = std::clamp(int(gridIntersect * grid->res(a)), 0, grid->res(a) - 1);
            deltaT_[a] = 1.0f / (std::abs(rayD[a]) * grid->res(a));
            if (rayD[a] == -0.0f) rayD[a] = 0.0f;
            if (rayD[a] >= 0) {
                float nextVoxelPos = float(voxel_[a] + 1) / grid->res(a);
                nextCrossingT_[a] = tMin + (nextVoxelPos - gridIntersect) / rayD[a];
                step_[a] = 1;
                voxelLimit_[a] = grid->res(a);
            } else {
                float nextVoxelPos = float(voxel_[a]) / grid->res(a);
                nextCrossingT_[a] = tMin + (nextVoxelPos - gridIntersect) / rayD[a];
                step_[a] = -1;
                voxelLimit_[a] = -1;
            }
        }
    }

    // Returns false when the ray segment is exhausted.
    bool next(MajorantSegment& seg) {
        if (tMin_ >= tMax_) return false;
        int bits = ((nextCrossingT_[0] < nextCrossingT_[1]) << 2) +
                   ((nextCrossingT_[0] < nextCrossingT_[2]) << 1) +
                   ((nextCrossingT_[1] < nextCrossingT_[2]));
        static const int cmpToAxis[8] = {2, 1, 2, 1, 2, 2, 0, 0};
        int stepAxis = cmpToAxis[bits];
        float tVoxelExit = std::min(tMax_, nextCrossingT_[stepAxis]);

        seg.tMin = tMin_;
        seg.tMax = tVoxelExit;
        seg.majorant = grid_->lookup(voxel_[0], voxel_[1], voxel_[2]);

        tMin_ = tVoxelExit;
        if (nextCrossingT_[stepAxis] > tMax_) tMin_ = tMax_;
        voxel_[stepAxis] += step_[stepAxis];
        if (voxel_[stepAxis] == voxelLimit_[stepAxis]) tMin_ = tMax_;
        nextCrossingT_[stepAxis] += deltaT_[stepAxis];
        return true;
    }

private:
    const MajorantGrid* grid_ = nullptr;
    float tMin_ = 0.0f, tMax_ = -1.0f;
    float nextCrossingT_[3] = {0, 0, 0};
    float deltaT_[3] = {0, 0, 0};
    int step_[3] = {0, 0, 0};
    int voxelLimit_[3] = {0, 0, 0};
    int voxel_[3] = {0, 0, 0};
};

}  // namespace volume
}  // namespace astroray
