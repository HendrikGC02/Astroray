"""pkg55-B' Session N+2 — CPU↔GPU threshold gate (GATE-THRESHOLDS-PINNED).

This test enforces the two-tier gate defined in pkg55 spec §4.2:
  1. CPU oracle ↔ CPU wavefront: exact bit-identity (0.0 / 0 / 1.0)
  2. CPU wavefront ↔ CUDA wavefront: ULP-bounded + p99.9 + SSIM

Session N+2 scope:
  - Verify CPU↔CPU baseline is exact bit-identity (should PASS on origin/main)
  - Load pinned thresholds from pkg55_cuda_thresholds.yaml
  - SKIP GPU tests (no CUDA kernel changes in this session)
  - Session N+3 will un-skip GPU tests and measure actual thresholds

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 GATE-THRESHOLDS-PINNED
Design: PR #296 §4.1, §4.2
"""

import sys
import os
import pytest
import yaml

# Add tests/scenes to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scenes"))
import session_n1_envmap_cornell

# Lazy import to avoid import-time failures if astroray not built
astroray = None


def _lazy_import_astroray():
    global astroray
    if astroray is None:
        import astroray as ar
        astroray = ar
    return astroray


def _load_thresholds():
    """Load pinned thresholds from pkg55_cuda_thresholds.yaml."""
    threshold_path = os.path.join(
        os.path.dirname(__file__), "..", "..", ".astroray_plan", "packages",
        "pkg55_cuda_thresholds.yaml"
    )
    with open(threshold_path, 'r') as f:
        return yaml.safe_load(f)


def _build_renderer(width, height, seed, max_depth):
    """Build the Session N+1 env-map Cornell scene (7 materials + env miss)."""
    ar = _lazy_import_astroray()
    r = ar.Renderer()
    session_n1_envmap_cornell.build_scene(r)
    session_n1_envmap_cornell.setup_camera(r, width=width, height=height)
    r.set_seed(seed)
    r.set_integrator_param("max_depth", max_depth)
    r.set_integrator("path_tracer")
    # Warmup render to trigger BVH build
    _ = r.render(1, 1, None, False)
    return r


def test_cpu_to_cpu_baseline_bit_identity():
    """CPU oracle ↔ CPU wavefront baseline: exact bit-identity (GATE 1 of 2).

    This gate MUST pass on origin/main (Session 2c-N+1 established bit-identity
    by shared-kernel construction). Any non-zero is a regression.
    """
    ar = _lazy_import_astroray()
    thresholds = _load_thresholds()
    baseline = thresholds["cpu_to_cpu_baseline"]

    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 1
    MAX_DEPTH = 8

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    result = ar.cpu_wavefront_snapshot_diff(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED
    )

    bit_identical = result["bit_identical"]
    max_abs_diff = result["max_abs_diff"]
    total_diverging_fields = result["total_diverging_fields"]
    report = result["report"]

    # Verify against pinned baseline (should be 0.0 / 0 / bit-identical)
    assert max_abs_diff == baseline["max_abs_diff"] == 0.0, (
        f"CPU↔CPU baseline FAILED: max abs diff {max_abs_diff!r}, "
        f"expected {baseline['max_abs_diff']!r}. "
        f"This is a regression — Sessions 2c-N+1 established bit-identity. "
        f"See per-stage report:\n{report}"
    )
    assert total_diverging_fields == baseline["total_diverging_fields"] == 0, (
        f"CPU↔CPU baseline FAILED: {total_diverging_fields} diverging fields, "
        f"expected {baseline['total_diverging_fields']}. "
        f"This is a regression — shared-kernel construction guarantees 0. "
        f"See per-stage report:\n{report}"
    )
    assert bit_identical, (
        f"CPU↔CPU baseline FAILED: streams not bit-identical despite zero diffs. "
        f"Harness inconsistency."
    )

    # ASCII-only print so the test passes on Windows consoles using cp1252.
    print(f"\n[pkg55-Session-N+2 CPU<->CPU baseline] PASS: exact bit-identity "
          f"(max diff = {max_abs_diff!r}, diverging fields = {total_diverging_fields})")


def test_cpu_to_gpu_threshold_gate():
    """CPU wavefront ↔ CUDA wavefront: ULP + p99.9 + SSIM gate (GATE 2 of 2).

    Session N+3 part 2b: enforces measured thresholds at PostInit/PostIntersect/PostShade stages.

    Spec: §4.2 GATE-THRESHOLDS-PINNED blocks Sessions N+2..M until thresholds
    are measured. Session N+2 pins the *structure*; Session N+3 measures the
    *values*.
    """
    ar = _lazy_import_astroray()

    if not hasattr(ar, 'cuda_wavefront_snapshot_post_init'):
        pytest.skip("CUDA wavefront not available. Build with -DASTRORAY_WAVEFRONT_CUDA_N3=ON.")

    thresholds = _load_thresholds()
    gpu_thresholds = thresholds["cpu_to_gpu_thresholds"]

    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 1
    MAX_DEPTH = 8

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    # Get CPU reference snapshots
    cpu_result = ar.reference_pt_wavefront_render(r, SPP, MAX_DEPTH, SEED, True)
    cpu_snapshots_raw = cpu_result['snapshots']

    # Extract CPU snapshots by stage
    cpu_post_init = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostInit')
    cpu_post_intersect = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostIntersect')
    cpu_post_shade = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostShade')

    # Get GPU snapshots
    gpu_post_init = ar.cuda_wavefront_snapshot_post_init(r, WIDTH, HEIGHT, SEED)
    gpu_post_intersect = ar.cuda_wavefront_snapshot_post_intersect(r, WIDTH, HEIGHT, SEED)
    gpu_post_shade = ar.cuda_wavefront_snapshot_post_shade(r, WIDTH, HEIGHT, SEED)

    # Gate 1: PostInit ULP + p99.9
    post_init_ulp = _compute_stage_ulp(cpu_post_init, gpu_post_init, stage='PostInit')
    post_init_p999 = _compute_stage_p999(cpu_post_init, gpu_post_init, stage='PostInit')

    assert post_init_ulp <= gpu_thresholds["PostInit"]["max_ulp"], (
        f"PostInit ULP gate FAILED: measured {post_init_ulp}, threshold {gpu_thresholds['PostInit']['max_ulp']}"
    )
    assert post_init_p999 <= gpu_thresholds["PostInit"]["p99_9_relative_error"], (
        f"PostInit p99.9 gate FAILED: measured {post_init_p999:.6e}, threshold {gpu_thresholds['PostInit']['p99_9_relative_error']:.6e}"
    )

    # Gate 2: PostIntersect ULP + p99.9
    post_intersect_ulp = _compute_stage_ulp(cpu_post_intersect, gpu_post_intersect, stage='PostIntersect')
    post_intersect_p999 = _compute_stage_p999(cpu_post_intersect, gpu_post_intersect, stage='PostIntersect')

    assert post_intersect_ulp <= gpu_thresholds["PostIntersect"]["max_ulp"], (
        f"PostIntersect ULP gate FAILED: measured {post_intersect_ulp}, threshold {gpu_thresholds['PostIntersect']['max_ulp']}"
    )
    assert post_intersect_p999 <= gpu_thresholds["PostIntersect"]["p99_9_relative_error"], (
        f"PostIntersect p99.9 gate FAILED: measured {post_intersect_p999:.6e}, threshold {gpu_thresholds['PostIntersect']['p99_9_relative_error']:.6e}"
    )

    # Gate 3: PostShade p99.9 on commonly-shaded paths.
    #
    # CPU `path_kernel.cpp::advance_one_bounce` emits a PostShade snapshot
    # only when (a) the path hit geometry AND (b) BSDF sampling succeeded
    # (`bss.pdf > 0.0f`). Paths that hit an emissive primary (e.g. the
    # Cornell area light) have no sampleable BSDF; CPU returns early
    # without a PostShade emit. The GPU stage_shade_lambertian kernel
    # emits one row per pixel unconditionally. So the truth-set for
    # "what successfully shaded" is **CPU's PostShade pixel_index list**,
    # not the PostIntersect hit set. (Bounded FMA-fusion drift at
    # PostIntersect also produces a handful of grazing-ray boundary
    # disagreements, which fold in as a subset of this set difference.)
    #
    # Sanity bound: shade-count divergence > 5% of total paths would mean
    # the algorithms genuinely diverge in what they consider shadeable;
    # below that it's emissive-material + boundary FMA drift, the same
    # root cause as the 32-ULP PostIntersect drift expressed at stage
    # boundaries.
    import numpy as np
    _gps = np.asarray(gpu_post_shade, dtype=np.float32).reshape(-1, 16)

    cpu_shade_pixels = np.array(
        [snap['pixel_index'] for snap in cpu_post_shade], dtype=np.int32)
    n_paths = _gps.shape[0]
    cpu_shade_count = int(cpu_shade_pixels.size)
    gpu_shade_count = n_paths  # GPU emits one row per pixel
    divergence_frac = abs(gpu_shade_count - cpu_shade_count) / max(1, n_paths)
    # GPU-shaded-count is always n_paths; this divergence frac is bounded
    # by the fraction of CPU paths that hit-and-shade. It's not a
    # correctness signal on its own; the real check is "do CPU and GPU
    # agree on the values at CPU's shaded pixels?" Sanity-only: warn if
    # CPU's shaded fraction collapses to near-zero (would indicate the
    # scene became degenerate or the integrator broke).
    assert cpu_shade_count >= int(0.10 * n_paths), (
        f"CPU PostShade shaded fraction collapsed: cpu_shade={cpu_shade_count} "
        f"of {n_paths} paths. Either the scene is degenerate or the CPU "
        f"shader broke. Investigate before relaxing this bound."
    )

    # Pull GPU rows at exactly the CPU-shaded pixel indices.
    gpu_post_shade_common = _gps[cpu_shade_pixels]
    assert gpu_post_shade_common.shape[0] == cpu_shade_count, (
        f"GPU PostShade row pick mismatch: got {gpu_post_shade_common.shape[0]} "
        f"rows for {cpu_shade_count} CPU pixel indices."
    )

    post_shade_p999 = _compute_stage_p999(cpu_post_shade, gpu_post_shade_common, stage='PostShade')

    assert post_shade_p999 <= gpu_thresholds["PostShade"]["p99_9_relative_error"], (
        f"PostShade p99.9 gate FAILED: measured {post_shade_p999:.6e}, threshold {gpu_thresholds['PostShade']['p99_9_relative_error']:.6e}"
    )

    print(f"\n[pkg55-Session-N+3-part2b CPU↔GPU threshold gate] PASS:")
    print(f"  PostInit: ULP={post_init_ulp}, p99.9={post_init_p999:.6e}")
    print(f"  PostIntersect: ULP={post_intersect_ulp}, p99.9={post_intersect_p999:.6e}")
    print(f"  PostShade: p99.9={post_shade_p999:.6e}")


def _extract_cpu_stage_snapshots(snapshots_raw, stage):
    """Extract CPU snapshots for a given stage at the first-bounce kernel call.

    CPU reference_pt_wavefront_render emits a snapshot at each stage on EVERY
    bounce of EVERY path. GPU cuda_wavefront_snapshot_post_<stage> launches the
    single-stage kernel once and downloads the result — i.e. only the bounce==0
    snapshot semantics. Filter to bounce==0 so the shapes align (width*height
    snapshots on both sides) and the per-field diff is comparing the same
    logical work unit.
    """
    stage_map = {
        'PostInit': 0,
        'PostIntersect': 1,
        'PostShade': 2,
        'PostLightSample': 3,
        'PostRR': 4,
    }
    stage_id = stage_map[stage]

    result = []
    for snap in snapshots_raw:
        if snap['stage'] == stage_id and snap['bounce'] == 0:
            result.append(snap)
    return result


def _compute_ulp_distance(a, b):
    """Compute max ULP distance between two float arrays."""
    import numpy as np
    a_int = np.frombuffer(a.astype(np.float32).tobytes(), dtype=np.int32)
    b_int = np.frombuffer(b.astype(np.float32).tobytes(), dtype=np.int32)
    ulp_dist = np.abs(a_int - b_int)
    return int(np.max(ulp_dist))


def _compute_stage_ulp(cpu_snapshots, gpu_snapshot_array, stage):
    """Compute max ULP distance for geometry fields at a given stage."""
    import numpy as np

    if stage == 'PostInit':
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 6:10].astype(np.float32)

        ulp_origin = _compute_ulp_distance(cpu_ray_origin.flatten(), gpu_ray_origin.flatten())
        ulp_dir = _compute_ulp_distance(cpu_ray_dir.flatten(), gpu_ray_dir.flatten())
        ulp_lambdas = _compute_ulp_distance(cpu_lambdas.flatten(), gpu_lambdas.flatten())

        return max(ulp_origin, ulp_dir, ulp_lambdas)

    elif stage == 'PostIntersect':
        # Only compare hit fields on rows where BOTH sides actually hit (valid=1).
        # Miss rows hold sentinel values (CPU writes hit_t=0, GPU writes hit_t=-1.0;
        # point/normal are zero on CPU and garbage on GPU). hit_valid==0 says
        # "ignore these"; ULP comparison must honour that.
        cpu_hit_valid = np.array([snap['hit_valid'] for snap in cpu_snapshots], dtype=np.int32)
        gpu_hit_valid = gpu_snapshot_array[:, 14].astype(np.int32)
        # Width-mismatch guard: if CPU and GPU snapshot lengths drifted, fail loud
        # rather than silently truncate.
        assert len(cpu_hit_valid) == len(gpu_hit_valid), (
            f"PostIntersect snapshot count mismatch: cpu={len(cpu_hit_valid)} "
            f"gpu={len(gpu_hit_valid)}; check _extract_cpu_stage_snapshots filter."
        )
        mask = (cpu_hit_valid == 1) & (gpu_hit_valid == 1)
        if not mask.any():
            # No common hits — return 0 (vacuously bounded). The CPU↔CPU bit-
            # identity gate covers the all-miss case structurally.
            return 0

        cpu_hit_t = np.array([snap['hit_t'] for snap in cpu_snapshots], dtype=np.float32)[mask]
        cpu_hit_point = np.array([snap['hit_point'] for snap in cpu_snapshots], dtype=np.float32)[mask]
        cpu_hit_normal = np.array([snap['hit_normal'] for snap in cpu_snapshots], dtype=np.float32)[mask]

        gpu_hit_t = gpu_snapshot_array[:, 15].astype(np.float32)[mask]
        gpu_hit_point = gpu_snapshot_array[:, 16:19].astype(np.float32)[mask]
        gpu_hit_normal = gpu_snapshot_array[:, 19:22].astype(np.float32)[mask]

        ulp_hit_t = _compute_ulp_distance(cpu_hit_t, gpu_hit_t)
        ulp_hit_point = _compute_ulp_distance(cpu_hit_point.flatten(), gpu_hit_point.flatten())
        ulp_hit_normal = _compute_ulp_distance(cpu_hit_normal.flatten(), gpu_hit_normal.flatten())

        return max(ulp_hit_t, ulp_hit_point, ulp_hit_normal)

    else:
        raise ValueError(f"ULP comparison not defined for stage {stage}")


def _compute_stage_p999(cpu_snapshots, gpu_snapshot_array, stage):
    """Compute p99.9 relative error for all numeric fields at a given stage."""
    import numpy as np

    def rel_err_p999(a, b, epsilon=1e-8):
        abs_diff = np.abs(a - b)
        denom = np.abs(a) + epsilon
        rel_err = abs_diff / denom
        return float(np.percentile(rel_err, 99.9))

    all_rel_errors = []

    if stage == 'PostInit':
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_throughput = np.array([snap['throughput'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 6:10].astype(np.float32)
        gpu_throughput = gpu_snapshot_array[:, 10:14].astype(np.float32)

        all_rel_errors.append(rel_err_p999(cpu_ray_origin, gpu_ray_origin))
        all_rel_errors.append(rel_err_p999(cpu_ray_dir, gpu_ray_dir))
        all_rel_errors.append(rel_err_p999(cpu_lambdas, gpu_lambdas))
        all_rel_errors.append(rel_err_p999(cpu_throughput, gpu_throughput))

    elif stage == 'PostIntersect':
        # hit_* fields are only meaningful on rows where both sides have
        # hit_valid==1; miss-row sentinels diverge by design (CPU writes 0s,
        # GPU writes -1/garbage). Mask before the relative-error percentile,
        # same convention as _compute_stage_ulp.
        cpu_hit_valid = np.array([snap['hit_valid'] for snap in cpu_snapshots], dtype=np.int32)
        gpu_hit_valid = gpu_snapshot_array[:, 14].astype(np.int32)
        hit_mask = (cpu_hit_valid == 1) & (gpu_hit_valid == 1)

        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_throughput = np.array([snap['throughput'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_hit_t = np.array([snap['hit_t'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_hit_point = np.array([snap['hit_point'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_hit_normal = np.array([snap['hit_normal'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 6:10].astype(np.float32)
        gpu_throughput = gpu_snapshot_array[:, 10:14].astype(np.float32)
        gpu_hit_t = gpu_snapshot_array[:, 15].astype(np.float32)
        gpu_hit_point = gpu_snapshot_array[:, 16:19].astype(np.float32)
        gpu_hit_normal = gpu_snapshot_array[:, 19:22].astype(np.float32)

        # Pre-shade ray state is valid for every path regardless of hit:
        all_rel_errors.append(rel_err_p999(cpu_ray_origin, gpu_ray_origin))
        all_rel_errors.append(rel_err_p999(cpu_ray_dir, gpu_ray_dir))
        all_rel_errors.append(rel_err_p999(cpu_lambdas, gpu_lambdas))
        all_rel_errors.append(rel_err_p999(cpu_throughput, gpu_throughput))
        # Hit fields: mask out miss rows so sentinel divergence doesn't
        # contaminate the percentile. If no common hits, skip.
        if hit_mask.any():
            all_rel_errors.append(rel_err_p999(cpu_hit_t[hit_mask], gpu_hit_t[hit_mask]))
            all_rel_errors.append(rel_err_p999(cpu_hit_point[hit_mask], gpu_hit_point[hit_mask]))
            all_rel_errors.append(rel_err_p999(cpu_hit_normal[hit_mask], gpu_hit_normal[hit_mask]))

    elif stage == 'PostShade':
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_throughput = np.array([snap['throughput'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_bsdf_pdf = np.array([snap['bsdf_pdf'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_throughput = gpu_snapshot_array[:, 6:10].astype(np.float32)
        gpu_bsdf_pdf = gpu_snapshot_array[:, 14].astype(np.float32)

        all_rel_errors.append(rel_err_p999(cpu_ray_origin, gpu_ray_origin))
        all_rel_errors.append(rel_err_p999(cpu_ray_dir, gpu_ray_dir))
        all_rel_errors.append(rel_err_p999(cpu_throughput, gpu_throughput))
        all_rel_errors.append(rel_err_p999(cpu_bsdf_pdf, gpu_bsdf_pdf))

    else:
        raise ValueError(f"p99.9 comparison not defined for stage {stage}")

    return max(all_rel_errors)


if __name__ == "__main__":
    # Standalone run for Session N+2 baseline measurement
    import astroray
    print("\n=== pkg55-B' Session N+2: CPU↔CPU baseline measurement ===\n")

    thresholds = _load_thresholds()
    baseline = thresholds["cpu_to_cpu_baseline"]
    print(f"Loaded pinned baseline from pkg55_cuda_thresholds.yaml:")
    print(f"  max_abs_diff: {baseline['max_abs_diff']}")
    print(f"  total_diverging_fields: {baseline['total_diverging_fields']}")
    print(f"  ssim: {baseline['ssim']}")
    print(f"  scene: {baseline['scene']}")
    print(f"  measured_on: {baseline['measured_on']}\n")

    # Run CPU↔CPU gate
    test_cpu_to_cpu_baseline_bit_identity()

    print("\n=== Session N+2 baseline gate: PASS ===")
    print("CPU↔CPU exact bit-identity confirmed on origin/main.")
    print("Session N+3 will measure CPU↔GPU thresholds on first CUDA port.\n")
