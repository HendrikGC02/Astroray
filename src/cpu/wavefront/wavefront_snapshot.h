// pkg55 Phase B' — CPU wavefront per-stage snapshot schema.
//
// Authoritative design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §7.
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
//
// Both reference path tracers (reference_pt_production, reference_pt_wavefront)
// and the CPU wavefront driver emit WavefrontSnapshot records at each stage
// boundary when a SnapshotSink is attached. The Session 2c per-stage diff
// harness compares snapshot streams element-by-element to localize divergence.
//
// This is the instrument that lets us pinpoint divergence to a single field
// at a single stage — without it, "the wavefront doesn't match" is unactionable.
//
// Cite: Cycles intern/cycles/device/cuda/queue.cpp paranoid-debug pattern
// (Apache-2.0) — kernel queues with debug builds dump per-launch state for
// the same purpose.
//
// Session 2a defines the schema only. Sessions 2b/2c fill the emit calls.
//
// Schema discipline (design doc §8.4):
//   - Fields are append-only. Never reordered, never renamed.
//   - SnapshotStage enum values are append-only; existing values are frozen.

#ifndef ASTRORAY_CPU_WAVEFRONT_SNAPSHOT_H
#define ASTRORAY_CPU_WAVEFRONT_SNAPSHOT_H

#include <cstdint>
#include <vector>

namespace astroray {
namespace cpu_wavefront {

enum class SnapshotStage : uint8_t {
    PostInit         = 0,  // primary ray generated, RNG seeded, lambda picked, throughput=1
    PostIntersect    = 1,  // BVH hit record written (or miss flag)
    PostShade        = 2,  // outgoing ray + updated throughput (after BSDF sample)
    PostLightSample  = 3,  // NEE shadow ray + light radiance + MIS weight
    PostRR           = 4,  // Russian roulette decision recorded
};

struct WavefrontSnapshot {
    // Identity (always present).
    int           pixel_index;
    int           sample_index;
    int           bounce;
    SnapshotStage stage;

    // Ray state (post-init / post-shade).
    float ray_origin[3];
    float ray_direction[3];

    // Per-path spectral carriers (always present).
    float throughput[4];   // SampledSpectrum (kSpectrumSamples = 4)
    float lambdas[4];      // SampledWavelengths

    // Hit record (post-intersect onward).
    int   hit_valid;       // 0 = miss
    float hit_t;
    float hit_point[3];
    float hit_normal[3];
    int   hit_material_id; // -1 if no material

    // Shade output (post-shade only).
    float bsdf_pdf;
    int   bsdf_is_delta;

    // NEE (post-light-sample only).
    float nee_contribution[4];   // weighted L * f for this sample
    float nee_light_pdf;
    float nee_bsdf_pdf_at_dir;
    float nee_mis_weight;

    // RR (post-rr only).
    float rr_prob;
    int   rr_survived;
};

// Snapshot sink abstraction. Sessions 2b/2c will pass a concrete sink
// (VectorSink or a callback adaptor) into the reference PTs and the CPU
// wavefront driver. nullptr sink == record nothing (production path).
class SnapshotSink {
public:
    virtual ~SnapshotSink() = default;
    virtual void record(const WavefrontSnapshot& s) = 0;
};

// Concrete sink: accumulates into a vector. The diff harness pulls the
// vector out at end of render. Per-thread instances avoid lock contention;
// the driver is responsible for thread-local instantiation when parallelized.
class VectorSink : public SnapshotSink {
public:
    void record(const WavefrontSnapshot& s) override { snapshots_.push_back(s); }
    const std::vector<WavefrontSnapshot>& snapshots() const { return snapshots_; }
    void clear() { snapshots_.clear(); }
    void reserve(std::size_t n) { snapshots_.reserve(n); }

private:
    std::vector<WavefrontSnapshot> snapshots_;
};

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_SNAPSHOT_H
