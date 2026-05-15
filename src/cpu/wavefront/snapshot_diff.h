// pkg55 Phase B' Session 2c — Snapshot stream comparison for bit-identity gate.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Session 2c close gate".
// Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §9.
//
// Compares two snapshot streams slot-by-slot, field-by-field, and reports
// the first diverging field (if any) at each stage boundary. This is the
// authoritative implementation of the Session 2c bit-identity gate.

#ifndef ASTRORAY_CPU_WAVEFRONT_SNAPSHOT_DIFF_H
#define ASTRORAY_CPU_WAVEFRONT_SNAPSHOT_DIFF_H

#include "wavefront_snapshot.h"
#include "reference_pt_production.h"  // for ReferencePTResult
#include <vector>
#include <string>
#include <cstdint>

namespace astroray {
namespace cpu_wavefront {

// Per-field diff result for a single snapshot.
struct FieldDiff {
    std::string field_name;
    float expected;  // reference value
    float actual;    // wavefront value
    float abs_diff;
    int slot_index;  // which path in the stream
};

// Per-stage diff summary.
struct StageDiff {
    SnapshotStage stage;
    int num_snapshots_expected;
    int num_snapshots_actual;
    std::vector<FieldDiff> diverging_fields;  // empty if bit-identical
};

// Full diff result across all stages.
struct SnapshotStreamDiff {
    std::vector<StageDiff> stages;
    float max_abs_diff;  // global maximum across all fields
    int total_diverging_fields;  // count across all stages
    bool bit_identical;  // true iff max_abs_diff == 0
};

// Compare two snapshot streams field-by-field.
// Returns detailed diff statistics for the Session 2c gate.
//
// Tolerance: exact equality (0.0f) for bit-identity; caller can apply
// a ULP tolerance if the spec gate evolves to permit it.
SnapshotStreamDiff compare_snapshot_streams(
    const std::vector<WavefrontSnapshot>& reference,
    const std::vector<WavefrontSnapshot>& actual,
    float tolerance = 0.0f);

// Helper: format StageDiff as human-readable string.
std::string format_stage_diff(const StageDiff& diff);

// Helper: format full SnapshotStreamDiff as human-readable report.
std::string format_diff_report(const SnapshotStreamDiff& diff);

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_SNAPSHOT_DIFF_H
