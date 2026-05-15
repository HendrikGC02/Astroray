// pkg55 Phase B' Session 2c — Snapshot stream comparison implementation.

#include "snapshot_diff.h"
#include <cmath>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <map>

namespace astroray {
namespace cpu_wavefront {

namespace {

// Compare a single float field, return diff if exceeds tolerance.
inline bool field_differs(float expected, float actual, float tolerance, float& out_abs_diff) {
    out_abs_diff = std::fabs(expected - actual);
    return out_abs_diff > tolerance;
}

// Compare a Vec3-like field (3 floats).
inline bool vec3_differs(const float expected[3], const float actual[3], float tolerance,
                         std::vector<FieldDiff>& out_diffs, const std::string& base_name, int slot) {
    bool any_diff = false;
    for (int i = 0; i < 3; ++i) {
        float abs_diff;
        if (field_differs(expected[i], actual[i], tolerance, abs_diff)) {
            FieldDiff fd;
            fd.field_name = base_name + "[" + std::to_string(i) + "]";
            fd.expected = expected[i];
            fd.actual = actual[i];
            fd.abs_diff = abs_diff;
            fd.slot_index = slot;
            out_diffs.push_back(fd);
            any_diff = true;
        }
    }
    return any_diff;
}

// Compare a SampledSpectrum-like field (4 floats).
inline bool spectrum_differs(const float expected[4], const float actual[4], float tolerance,
                              std::vector<FieldDiff>& out_diffs, const std::string& base_name, int slot) {
    bool any_diff = false;
    for (int i = 0; i < 4; ++i) {
        float abs_diff;
        if (field_differs(expected[i], actual[i], tolerance, abs_diff)) {
            FieldDiff fd;
            fd.field_name = base_name + "[" + std::to_string(i) + "]";
            fd.expected = expected[i];
            fd.actual = actual[i];
            fd.abs_diff = abs_diff;
            fd.slot_index = slot;
            out_diffs.push_back(fd);
            any_diff = true;
        }
    }
    return any_diff;
}

// Compare a single scalar field.
inline void check_scalar(float expected, float actual, float tolerance,
                         std::vector<FieldDiff>& out_diffs, const std::string& field_name, int slot) {
    float abs_diff;
    if (field_differs(expected, actual, tolerance, abs_diff)) {
        FieldDiff fd;
        fd.field_name = field_name;
        fd.expected = expected;
        fd.actual = actual;
        fd.abs_diff = abs_diff;
        fd.slot_index = slot;
        out_diffs.push_back(fd);
    }
}

// Compare a single int field (cast to float for diff reporting).
inline void check_int(int expected, int actual,
                      std::vector<FieldDiff>& out_diffs, const std::string& field_name, int slot) {
    if (expected != actual) {
        FieldDiff fd;
        fd.field_name = field_name;
        fd.expected = static_cast<float>(expected);
        fd.actual = static_cast<float>(actual);
        fd.abs_diff = static_cast<float>(std::abs(expected - actual));
        fd.slot_index = slot;
        out_diffs.push_back(fd);
    }
}

// Compare two snapshots field-by-field.
void compare_snapshots(const WavefrontSnapshot& ref, const WavefrontSnapshot& act, float tolerance,
                       std::vector<FieldDiff>& out_diffs, int slot_index) {
    // Identity fields (must always match).
    check_int(ref.pixel_index, act.pixel_index, out_diffs, "pixel_index", slot_index);
    check_int(ref.sample_index, act.sample_index, out_diffs, "sample_index", slot_index);
    check_int(ref.bounce, act.bounce, out_diffs, "bounce", slot_index);
    check_int(static_cast<int>(ref.stage), static_cast<int>(act.stage), out_diffs, "stage", slot_index);

    // Ray state.
    vec3_differs(ref.ray_origin, act.ray_origin, tolerance, out_diffs, "ray_origin", slot_index);
    vec3_differs(ref.ray_direction, act.ray_direction, tolerance, out_diffs, "ray_direction", slot_index);

    // Spectral carriers.
    spectrum_differs(ref.throughput, act.throughput, tolerance, out_diffs, "throughput", slot_index);
    spectrum_differs(ref.lambdas, act.lambdas, tolerance, out_diffs, "lambdas", slot_index);

    // Hit record (relevant post-intersect onward).
    if (ref.stage >= SnapshotStage::PostIntersect) {
        check_int(ref.hit_valid, act.hit_valid, out_diffs, "hit_valid", slot_index);
        check_scalar(ref.hit_t, act.hit_t, tolerance, out_diffs, "hit_t", slot_index);
        vec3_differs(ref.hit_point, act.hit_point, tolerance, out_diffs, "hit_point", slot_index);
        vec3_differs(ref.hit_normal, act.hit_normal, tolerance, out_diffs, "hit_normal", slot_index);
        check_int(ref.hit_material_id, act.hit_material_id, out_diffs, "hit_material_id", slot_index);
    }

    // Shade output (relevant post-shade onward).
    if (ref.stage >= SnapshotStage::PostShade) {
        check_scalar(ref.bsdf_pdf, act.bsdf_pdf, tolerance, out_diffs, "bsdf_pdf", slot_index);
        check_int(ref.bsdf_is_delta, act.bsdf_is_delta, out_diffs, "bsdf_is_delta", slot_index);
    }

    // NEE (relevant post-light-sample only).
    if (ref.stage >= SnapshotStage::PostLightSample) {
        spectrum_differs(ref.nee_contribution, act.nee_contribution, tolerance, out_diffs, "nee_contribution", slot_index);
        check_scalar(ref.nee_light_pdf, act.nee_light_pdf, tolerance, out_diffs, "nee_light_pdf", slot_index);
        check_scalar(ref.nee_bsdf_pdf_at_dir, act.nee_bsdf_pdf_at_dir, tolerance, out_diffs, "nee_bsdf_pdf_at_dir", slot_index);
        check_scalar(ref.nee_mis_weight, act.nee_mis_weight, tolerance, out_diffs, "nee_mis_weight", slot_index);
    }

    // RR (relevant post-rr only).
    if (ref.stage >= SnapshotStage::PostRR) {
        check_scalar(ref.rr_prob, act.rr_prob, tolerance, out_diffs, "rr_prob", slot_index);
        check_int(ref.rr_survived, act.rr_survived, out_diffs, "rr_survived", slot_index);
    }
}

}  // anonymous namespace

SnapshotStreamDiff compare_snapshot_streams(
        const std::vector<WavefrontSnapshot>& reference,
        const std::vector<WavefrontSnapshot>& actual,
        float tolerance) {
    SnapshotStreamDiff result;
    result.max_abs_diff = 0.0f;
    result.total_diverging_fields = 0;
    result.bit_identical = true;

    // Sort comparator: (pixel_index, sample_index, bounce, stage).
    // This ensures snapshots are compared in the same logical order regardless
    // of emission order (reference_pt_wavefront emits per-path, cpu_wavefront
    // emits per-stage-per-bounce).
    auto snapshot_order = [](const WavefrontSnapshot& a, const WavefrontSnapshot& b) {
        if (a.pixel_index != b.pixel_index) return a.pixel_index < b.pixel_index;
        if (a.sample_index != b.sample_index) return a.sample_index < b.sample_index;
        if (a.bounce != b.bounce) return a.bounce < b.bounce;
        return static_cast<int>(a.stage) < static_cast<int>(b.stage);
    };

    // Copy and sort both streams.
    std::vector<WavefrontSnapshot> ref_sorted = reference;
    std::vector<WavefrontSnapshot> act_sorted = actual;
    std::sort(ref_sorted.begin(), ref_sorted.end(), snapshot_order);
    std::sort(act_sorted.begin(), act_sorted.end(), snapshot_order);

    // Group sorted snapshots by stage.
    std::map<SnapshotStage, std::vector<const WavefrontSnapshot*>> ref_by_stage;
    std::map<SnapshotStage, std::vector<const WavefrontSnapshot*>> act_by_stage;

    for (const auto& s : ref_sorted) {
        ref_by_stage[s.stage].push_back(&s);
    }
    for (const auto& s : act_sorted) {
        act_by_stage[s.stage].push_back(&s);
    }

    // Compare each stage.
    const SnapshotStage all_stages[] = {
        SnapshotStage::PostInit,
        SnapshotStage::PostIntersect,
        SnapshotStage::PostShade,
        SnapshotStage::PostLightSample,
        SnapshotStage::PostRR
    };

    for (SnapshotStage stage : all_stages) {
        StageDiff sd;
        sd.stage = stage;
        sd.num_snapshots_expected = static_cast<int>(ref_by_stage[stage].size());
        sd.num_snapshots_actual = static_cast<int>(act_by_stage[stage].size());

        // Count mismatch.
        if (sd.num_snapshots_expected != sd.num_snapshots_actual) {
            result.bit_identical = false;
            // Report as a synthetic diff.
            FieldDiff fd;
            fd.field_name = "snapshot_count";
            fd.expected = static_cast<float>(sd.num_snapshots_expected);
            fd.actual = static_cast<float>(sd.num_snapshots_actual);
            fd.abs_diff = std::fabs(fd.expected - fd.actual);
            fd.slot_index = -1;
            sd.diverging_fields.push_back(fd);
            result.max_abs_diff = std::max(result.max_abs_diff, fd.abs_diff);
            result.stages.push_back(sd);
            continue;
        }

        // Compare snapshots slot-by-slot.
        const auto& ref_snaps = ref_by_stage[stage];
        const auto& act_snaps = act_by_stage[stage];
        for (size_t i = 0; i < ref_snaps.size(); ++i) {
            std::vector<FieldDiff> diffs;
            compare_snapshots(*ref_snaps[i], *act_snaps[i], tolerance, diffs, static_cast<int>(i));
            for (const auto& fd : diffs) {
                result.max_abs_diff = std::max(result.max_abs_diff, fd.abs_diff);
                result.bit_identical = false;
            }
            sd.diverging_fields.insert(sd.diverging_fields.end(), diffs.begin(), diffs.end());
        }

        result.total_diverging_fields += static_cast<int>(sd.diverging_fields.size());
        result.stages.push_back(sd);
    }

    return result;
}

std::string format_stage_diff(const StageDiff& diff) {
    std::ostringstream oss;
    const char* stage_names[] = {"PostInit", "PostIntersect", "PostShade", "PostLightSample", "PostRR"};
    oss << "Stage " << stage_names[static_cast<int>(diff.stage)];
    oss << " (" << diff.num_snapshots_expected << " expected, " << diff.num_snapshots_actual << " actual)";

    if (diff.diverging_fields.empty()) {
        oss << ": BIT-IDENTICAL";
    } else {
        // Find max divergence in this stage.
        float stage_max_diff = 0.0f;
        const FieldDiff* max_field = nullptr;
        for (const auto& fd : diff.diverging_fields) {
            if (fd.abs_diff > stage_max_diff) {
                stage_max_diff = fd.abs_diff;
                max_field = &fd;
            }
        }

        oss << ": " << diff.diverging_fields.size() << " diverging field(s), "
            << "max |diff|=" << std::scientific << std::setprecision(6) << stage_max_diff << "\n";

        // Report maximum divergence field first if > 1e-6 (non-ULP).
        if (max_field && stage_max_diff > 1e-6) {
            oss << "  [MAX] [slot " << max_field->slot_index << "] " << max_field->field_name
                << ": expected=" << std::scientific << std::setprecision(6) << max_field->expected
                << ", actual=" << max_field->actual
                << ", |diff|=" << max_field->abs_diff << "\n";
        }

        // Report first 5 divergences.
        int count = std::min(5, static_cast<int>(diff.diverging_fields.size()));
        for (int i = 0; i < count; ++i) {
            const auto& fd = diff.diverging_fields[i];
            oss << "  [slot " << fd.slot_index << "] " << fd.field_name
                << ": expected=" << std::scientific << std::setprecision(6) << fd.expected
                << ", actual=" << fd.actual
                << ", |diff|=" << fd.abs_diff << "\n";
        }
        if (diff.diverging_fields.size() > 5) {
            oss << "  ... (" << (diff.diverging_fields.size() - 5) << " more)\n";
        }
    }
    return oss.str();
}

std::string format_diff_report(const SnapshotStreamDiff& diff) {
    std::ostringstream oss;
    oss << "[pkg55-Session2c snapshot-stream diff]\n";
    oss << "Bit-identical: " << (diff.bit_identical ? "YES" : "NO") << "\n";
    oss << "Max abs diff: " << std::scientific << std::setprecision(6) << diff.max_abs_diff << "\n";
    oss << "Total diverging fields: " << diff.total_diverging_fields << "\n";
    oss << "\nPer-stage breakdown:\n";
    for (const auto& sd : diff.stages) {
        oss << format_stage_diff(sd) << "\n";
    }
    return oss.str();
}

}  // namespace cpu_wavefront
}  // namespace astroray
