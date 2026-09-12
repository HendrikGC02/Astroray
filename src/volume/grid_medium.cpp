// pkg267 — GridMedium implementation. This is the ONLY translation unit that
// includes NanoVDB.h (kept out of raytracer.h via the PIMPL in grid_medium.h).
//
// NanoVDB host grid build: Museth 2021; reference impl
// nanovdb::tools::build::Grid + nanovdb::tools::createNanoGrid (Apache-2.0,
// vendored external/nanovdb, tag v12.0.0). No OpenVDB (NANOVDB_USE_OPENVDB
// undefined) so the `.vdb` file path is gated out — the Blender addon decodes
// grids and hands us dense arrays. Research:
// .astroray_plan/docs/pkg267-nanovdb-majorant-research.md.

#include "astroray/volume/grid_medium.h"

#include <algorithm>
#include <cmath>

// NanoVDB pulls in <nanovdb/...>; external/nanovdb is on this TU's include path.
#include <nanovdb/tools/CreateNanoGrid.h>  // -> build::Grid, createNanoGrid, GridBuilder.h

namespace astroray {
namespace volume {

namespace {

// Row-major 4x4 helpers (index = row*4 + col). Point transform is p' = M·[p,1];
// direction uses the upper-left 3x3 (no translation).
Mat4 matMul(const Mat4& a, const Mat4& b) {
    Mat4 r{};
    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j) {
            float s = 0.0f;
            for (int k = 0; k < 4; ++k) s += a[i * 4 + k] * b[k * 4 + j];
            r[i * 4 + j] = s;
        }
    return r;
}

void xformPoint(const Mat4& m, float x, float y, float z, float out[3]) {
    out[0] = m[0] * x + m[1] * y + m[2] * z + m[3];
    out[1] = m[4] * x + m[5] * y + m[6] * z + m[7];
    out[2] = m[8] * x + m[9] * y + m[10] * z + m[11];
}

void xformDir(const Mat4& m, float x, float y, float z, float out[3]) {
    out[0] = m[0] * x + m[1] * y + m[2] * z;
    out[1] = m[4] * x + m[5] * y + m[6] * z;
    out[2] = m[8] * x + m[9] * y + m[10] * z;
}

// General 4x4 inverse (cofactor expansion). Identity fallback if singular.
Mat4 matInverse(const Mat4& m) {
    Mat4 inv{};
    const float* a = m.data();
    inv[0] = a[5]*a[10]*a[15] - a[5]*a[11]*a[14] - a[9]*a[6]*a[15] + a[9]*a[7]*a[14] + a[13]*a[6]*a[11] - a[13]*a[7]*a[10];
    inv[4] = -a[4]*a[10]*a[15] + a[4]*a[11]*a[14] + a[8]*a[6]*a[15] - a[8]*a[7]*a[14] - a[12]*a[6]*a[11] + a[12]*a[7]*a[10];
    inv[8] = a[4]*a[9]*a[15] - a[4]*a[11]*a[13] - a[8]*a[5]*a[15] + a[8]*a[7]*a[13] + a[12]*a[5]*a[11] - a[12]*a[7]*a[9];
    inv[12] = -a[4]*a[9]*a[14] + a[4]*a[10]*a[13] + a[8]*a[5]*a[14] - a[8]*a[6]*a[13] - a[12]*a[5]*a[10] + a[12]*a[6]*a[9];
    inv[1] = -a[1]*a[10]*a[15] + a[1]*a[11]*a[14] + a[9]*a[2]*a[15] - a[9]*a[3]*a[14] - a[13]*a[2]*a[11] + a[13]*a[3]*a[10];
    inv[5] = a[0]*a[10]*a[15] - a[0]*a[11]*a[14] - a[8]*a[2]*a[15] + a[8]*a[3]*a[14] + a[12]*a[2]*a[11] - a[12]*a[3]*a[10];
    inv[9] = -a[0]*a[9]*a[15] + a[0]*a[11]*a[13] + a[8]*a[1]*a[15] - a[8]*a[3]*a[13] - a[12]*a[1]*a[11] + a[12]*a[3]*a[9];
    inv[13] = a[0]*a[9]*a[14] - a[0]*a[10]*a[13] - a[8]*a[1]*a[14] + a[8]*a[2]*a[13] + a[12]*a[1]*a[10] - a[12]*a[2]*a[9];
    inv[2] = a[1]*a[6]*a[15] - a[1]*a[7]*a[14] - a[5]*a[2]*a[15] + a[5]*a[3]*a[14] + a[13]*a[2]*a[7] - a[13]*a[3]*a[6];
    inv[6] = -a[0]*a[6]*a[15] + a[0]*a[7]*a[14] + a[4]*a[2]*a[15] - a[4]*a[3]*a[14] - a[12]*a[2]*a[7] + a[12]*a[3]*a[6];
    inv[10] = a[0]*a[5]*a[15] - a[0]*a[7]*a[13] - a[4]*a[1]*a[15] + a[4]*a[3]*a[13] + a[12]*a[1]*a[7] - a[12]*a[3]*a[5];
    inv[14] = -a[0]*a[5]*a[14] + a[0]*a[6]*a[13] + a[4]*a[1]*a[14] - a[4]*a[2]*a[13] - a[12]*a[1]*a[6] + a[12]*a[2]*a[5];
    inv[3] = -a[1]*a[6]*a[11] + a[1]*a[7]*a[10] + a[5]*a[2]*a[11] - a[5]*a[3]*a[10] - a[9]*a[2]*a[7] + a[9]*a[3]*a[6];
    inv[7] = a[0]*a[6]*a[11] - a[0]*a[7]*a[10] - a[4]*a[2]*a[11] + a[4]*a[3]*a[10] + a[8]*a[2]*a[7] - a[8]*a[3]*a[6];
    inv[11] = -a[0]*a[5]*a[11] + a[0]*a[7]*a[9] + a[4]*a[1]*a[11] - a[4]*a[3]*a[9] - a[8]*a[1]*a[7] + a[8]*a[3]*a[5];
    inv[15] = a[0]*a[5]*a[10] - a[0]*a[6]*a[9] - a[4]*a[1]*a[10] + a[4]*a[2]*a[9] + a[8]*a[1]*a[6] - a[8]*a[2]*a[5];
    float det = a[0]*inv[0] + a[1]*inv[4] + a[2]*inv[8] + a[3]*inv[12];
    if (std::abs(det) < 1e-20f) {
        Mat4 id{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        return id;
    }
    float invDet = 1.0f / det;
    for (int i = 0; i < 16; ++i) inv[i] *= invDet;
    return inv;
}

}  // namespace

struct GridMedium::Impl {
    bool valid = false;
    int dim[3] = {0, 0, 0};
    int bboxMin[3] = {0, 0, 0};
    Mat4 idxToWorld{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
    Mat4 worldToIdx{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};

    nanovdb::GridHandle<nanovdb::HostBuffer> densityHandle;
    const nanovdb::FloatGrid* densityGrid = nullptr;

    MajorantGrid majorant;

    // passthrough handles (pkg270)
    DenseGrid temperature;
    bool hasTemp = false;
};

GridMedium::GridMedium() : impl_(std::make_unique<Impl>()) {}
GridMedium::~GridMedium() = default;
GridMedium::GridMedium(GridMedium&&) noexcept = default;
GridMedium& GridMedium::operator=(GridMedium&&) noexcept = default;

void GridMedium::setDensity(const DenseGrid& d, const Mat4& indexToObject,
                            const Mat4& objectToWorld, int supervoxel) {
    Impl& im = *impl_;
    for (int a = 0; a < 3; ++a) { im.dim[a] = d.dim[a]; im.bboxMin[a] = d.bboxMin[a]; }
    im.idxToWorld = matMul(objectToWorld, indexToObject);
    im.worldToIdx = matInverse(im.idxToWorld);

    // --- build the sparse NanoVDB density grid (skip background voxels) ---
    nanovdb::tools::build::Grid<float> build(0.0f, "density");
    auto acc = build.getAccessor();
    const int nx = d.dim[0], ny = d.dim[1], nz = d.dim[2];
    for (int z = 0; z < nz; ++z)
        for (int y = 0; y < ny; ++y)
            for (int x = 0; x < nx; ++x) {
                float v = d.data[size_t((z * ny + y) * nx + x)];
                if (v != 0.0f)
                    acc.setValue(nanovdb::Coord(im.bboxMin[0] + x, im.bboxMin[1] + y,
                                                im.bboxMin[2] + z), v);
            }
    im.densityHandle = nanovdb::tools::createNanoGrid(build);
    im.densityGrid = im.densityHandle.grid<float>();

    // --- coarse majorant grid (per-supervoxel max density) ---
    int S = supervoxel > 0 ? supervoxel : 16;  // tunable supervoxel edge (pbrt heuristic)
    int res[3];
    for (int a = 0; a < 3; ++a) {
        int r = (d.dim[a] + S - 1) / S;
        res[a] = std::clamp(r, 1, 128);
    }
    im.majorant = MajorantGrid(d.dim, d.bboxMin, res);
    for (int z = 0; z < nz; ++z)
        for (int y = 0; y < ny; ++y)
            for (int x = 0; x < nx; ++x) {
                float v = d.data[size_t((z * ny + y) * nx + x)];
                if (v <= 0.0f) continue;
                int sv[3];
                im.majorant.supervoxelOf(float(im.bboxMin[0] + x) + 0.5f,
                                         float(im.bboxMin[1] + y) + 0.5f,
                                         float(im.bboxMin[2] + z) + 0.5f, sv);
                im.majorant.accumulateMax(sv[0], sv[1], sv[2], v);
            }
    im.valid = true;
}

void GridMedium::setTemperature(const DenseGrid& g) { impl_->temperature = g; impl_->hasTemp = true; }
void GridMedium::setColor(const DenseGrid&) { /* pkg270 passthrough */ }
void GridMedium::setVelocity(const DenseGrid&) { /* pkg270/pkg272 passthrough */ }

bool GridMedium::valid() const { return impl_->valid; }

float GridMedium::densityIndex(float ix, float iy, float iz) const {
    if (!impl_->densityGrid) return 0.0f;
    // Nearest voxel (see header note): a per-thread accessor (ReadAccessor is not
    // thread-safe across threads, so create one per query — the integrator is
    // multithreaded).
    auto racc = impl_->densityGrid->getAccessor();
    nanovdb::Coord c(int(std::lround(ix)), int(std::lround(iy)), int(std::lround(iz)));
    return racc.getValue(c);
}

std::array<float, 3> GridMedium::worldPointToIndex(float wx, float wy, float wz) const {
    float o[3]; xformPoint(impl_->worldToIdx, wx, wy, wz, o);
    return {o[0], o[1], o[2]};
}
std::array<float, 3> GridMedium::worldDirToIndex(float dx, float dy, float dz) const {
    float o[3]; xformDir(impl_->worldToIdx, dx, dy, dz, o);
    return {o[0], o[1], o[2]};
}

float GridMedium::densityWorld(float wx, float wy, float wz) const {
    auto p = worldPointToIndex(wx, wy, wz);
    return densityIndex(p[0], p[1], p[2]);
}

Mat4 GridMedium::indexToWorld() const { return impl_->idxToWorld; }
Mat4 GridMedium::worldToIndex() const { return impl_->worldToIdx; }

std::array<float, 6> GridMedium::worldAABB() const {
    const Impl& im = *impl_;
    float mn[3] = {1e30f, 1e30f, 1e30f}, mx[3] = {-1e30f, -1e30f, -1e30f};
    float i0[3] = {float(im.bboxMin[0]), float(im.bboxMin[1]), float(im.bboxMin[2])};
    float i1[3] = {float(im.bboxMin[0] + im.dim[0]), float(im.bboxMin[1] + im.dim[1]),
                   float(im.bboxMin[2] + im.dim[2])};
    for (int cx = 0; cx < 2; ++cx)
        for (int cy = 0; cy < 2; ++cy)
            for (int cz = 0; cz < 2; ++cz) {
                float w[3];
                xformPoint(im.idxToWorld, cx ? i1[0] : i0[0], cy ? i1[1] : i0[1],
                           cz ? i1[2] : i0[2], w);
                for (int a = 0; a < 3; ++a) { mn[a] = std::min(mn[a], w[a]); mx[a] = std::max(mx[a], w[a]); }
            }
    return {mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]};
}

std::array<int, 3> GridMedium::dims() const { return {impl_->dim[0], impl_->dim[1], impl_->dim[2]}; }
std::array<int, 3> GridMedium::bboxMin() const { return {impl_->bboxMin[0], impl_->bboxMin[1], impl_->bboxMin[2]}; }

const MajorantGrid& GridMedium::majorant() const { return impl_->majorant; }
int GridMedium::supervoxelRes(int axis) const { return impl_->majorant.res(axis); }

float GridMedium::majorantDensityWorld(float wx, float wy, float wz) const {
    auto p = worldPointToIndex(wx, wy, wz);
    int sv[3];
    impl_->majorant.supervoxelOf(p[0], p[1], p[2], sv);
    return impl_->majorant.lookup(sv[0], sv[1], sv[2]);
}

bool GridMedium::hasTemperature() const { return impl_->hasTemp; }
float GridMedium::temperatureIndex(float ix, float iy, float iz) const {
    const DenseGrid& g = impl_->temperature;
    if (!impl_->hasTemp) return 0.0f;
    int x = int(std::lround(ix)) - g.bboxMin[0];
    int y = int(std::lround(iy)) - g.bboxMin[1];
    int z = int(std::lround(iz)) - g.bboxMin[2];
    if (x < 0 || y < 0 || z < 0 || x >= g.dim[0] || y >= g.dim[1] || z >= g.dim[2]) return 0.0f;
    return g.data[size_t((z * g.dim[1] + y) * g.dim[0] + x)];
}

}  // namespace volume
}  // namespace astroray
