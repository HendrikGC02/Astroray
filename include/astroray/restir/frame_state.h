#pragma once

// ReSTIR frame-state skeleton (pkg23).
//
// Defines the data structures and helper algorithms needed to implement
// temporal and spatial reservoir reuse. No actual reuse is performed yet;
// this header makes the design concrete and testable so that pkg24 can add
// and validate the passes without redesigning the types.
//
// Execution model (one frame):
//   1. beginFrame  — advance frame index, swap current/previous buffers, resize.
//   2. sampleFull  — per-pixel initial candidate generation (pkg22). The
//                    reservoir produced here will be stored in current[] by pkg24.
//   3. (pkg24)     — temporal reuse pass: merge previous[] reservoirs into current[].
//   4. (pkg24)     — spatial  reuse pass: merge neighbour current[] reservoirs.
//   5. endFrame    — finalize / post-process (placeholder).
//
// CPU/GPU boundary:
//   Everything here is CPU-side. When CUDA kernels are added, the same flat
//   pixel-indexed layout is reused; AoS layout will be split to SoA for
//   coalesced access at that point. Do not change field order until then.

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

#include "astroray/restir/reservoir.h"
#include "astroray/restir/light_sample.h"

namespace astroray::restir {

// Per-pixel metadata required for temporal validity checks.
// Stored alongside each reservoir so we can detect geometry changes between frames.
struct PixelHistory {
    Vec3  normal{0.0f, 0.0f, 1.0f};  // world-space surface normal at this pixel
    float depth = 0.0f;               // view-space depth (positive, 0 = sky)
    bool  valid = false;              // false when the pixel missed all geometry
};

// Flat, pixel-indexed buffer of reservoirs plus per-pixel history metadata.
// Indexing: pixel (x, y) maps to index y * width + x.
struct ReservoirBuffer {
    std::vector<Reservoir<ReSTIRCandidate>> reservoirs;
    std::vector<PixelHistory>               history;
    int width  = 0;
    int height = 0;

    void resize(int w, int h) {
        width  = w;
        height = h;
        reservoirs.assign(static_cast<size_t>(w * h), Reservoir<ReSTIRCandidate>{});
        history.assign(static_cast<size_t>(w * h), PixelHistory{});
    }

    Reservoir<ReSTIRCandidate>&       at(int x, int y)       { return reservoirs[y * width + x]; }
    const Reservoir<ReSTIRCandidate>& at(int x, int y) const { return reservoirs[y * width + x]; }

    PixelHistory&       meta(int x, int y)       { return history[y * width + x]; }
    const PixelHistory& meta(int x, int y) const { return history[y * width + x]; }

    bool inBounds(int x, int y) const {
        return x >= 0 && x < width && y >= 0 && y < height;
    }

    void clear() {
        std::fill(reservoirs.begin(), reservoirs.end(), Reservoir<ReSTIRCandidate>{});
        std::fill(history.begin(),    history.end(),    PixelHistory{});
    }
};

// Temporal validity gate.
//
// Returns true iff the previous-frame reservoir at (px, py) can safely be
// merged into the current frame's reservoir at the same (reprojected) position.
// A pixel is invalid when:
//   - it is out of bounds in the previous buffer
//   - it had no geometry hit (PixelHistory::valid == false)
//   - the surface normals diverge (dot < normalThreshold, default cos ≈ 26°)
//   - the depths differ by more than depthThreshold relative to the larger depth
//
// Bias note: passing this gate does not guarantee that the previous reservoir's
// selected candidate is still visible at the current shading point. A full
// unbiased implementation adds a shadow-ray check (bias correction) before merging;
// that is deferred to pkg24 validation.
inline bool isTemporallyValid(
    const ReservoirBuffer& prev,
    int   px, int py,
    const Vec3& currentNormal, float currentDepth,
    float normalThreshold = 0.9f,
    float depthThreshold  = 0.1f)
{
    if (!prev.inBounds(px, py)) return false;
    const PixelHistory& h = prev.meta(px, py);
    if (!h.valid) return false;

    // Normal similarity (both vectors assumed unit-length).
    float ndot = currentNormal.x * h.normal.x
               + currentNormal.y * h.normal.y
               + currentNormal.z * h.normal.z;
    if (ndot < normalThreshold) return false;

    // Relative depth similarity.
    float maxD = h.depth > currentDepth ? h.depth : currentDepth;
    if (maxD > 1e-4f && std::abs(currentDepth - h.depth) / maxD > depthThreshold)
        return false;

    return true;
}

// Single spatial-reuse candidate: a screen-space neighbour pixel.
struct SpatialNeighbor {
    int  x, y;
    bool valid;  // false when (x, y) is outside [0, width) × [0, height)
};

// Fill out[0..maxNeighbors) with random neighbours of (cx, cy) drawn uniformly
// from a (2*radius+1) × (2*radius+1) window, excluding (cx, cy) itself.
// Each entry has valid=false when the sampled position is out of bounds.
// Always writes exactly maxNeighbors entries; returns maxNeighbors.
inline int selectSpatialNeighbors(
    int cx, int cy,
    int width, int height,
    int radius, int maxNeighbors,
    std::mt19937& gen,
    SpatialNeighbor* out)
{
    std::uniform_int_distribution<int> dX(-radius, radius);
    std::uniform_int_distribution<int> dY(-radius, radius);
    for (int i = 0; i < maxNeighbors; ++i) {
        int nx = cx + dX(gen);
        int ny = cy + dY(gen);
        out[i] = { nx, ny, nx >= 0 && nx < width && ny >= 0 && ny < height };
    }
    return maxNeighbors;
}

// Double-buffered frame state owned by the ReSTIR integrator.
//
// Usage:
//   beginFrame:  frameState.resize(w, h); frameState.advanceFrame();
//   sampleFull:  write initial reservoir to frameState.current.at(px, py)  [pkg24]
//   (pkg24):     temporal pass — isTemporallyValid + merge previous → current
//   (pkg24):     spatial  pass — selectSpatialNeighbors + merge neighbours → current
//   endFrame:    (placeholder for post-processing / denoiser hand-off)
struct FrameState {
    ReservoirBuffer current;
    ReservoirBuffer previous;
    int             frameIndex = 0;

    // Ensure both buffers match the current render resolution.
    void resize(int w, int h) {
        current.resize(w, h);
        previous.resize(w, h);
    }

    // Swap current ↔ previous, clear the new current buffer, advance the frame counter.
    // Call once at the start of each frame (in beginFrame) so that the previous
    // buffer always holds the last fully-written frame's reservoirs.
    void advanceFrame() {
        std::swap(current, previous);
        current.clear();
        ++frameIndex;
    }
};

} // namespace astroray::restir
