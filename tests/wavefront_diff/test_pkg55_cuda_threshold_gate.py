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
    cpu_post_light_sample = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostLightSample')
    cpu_post_rr = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostRR')

    # Get GPU snapshots
    gpu_post_init = ar.cuda_wavefront_snapshot_post_init(r, WIDTH, HEIGHT, SEED)
    gpu_post_intersect = ar.cuda_wavefront_snapshot_post_intersect(r, WIDTH, HEIGHT, SEED)
    gpu_post_shade = ar.cuda_wavefront_snapshot_post_shade(r, WIDTH, HEIGHT, SEED)
    gpu_post_light_sample = ar.cuda_wavefront_snapshot_post_light_sample(r, WIDTH, HEIGHT, SEED)
    gpu_post_rr = ar.cuda_wavefront_snapshot_post_rr(r, WIDTH, HEIGHT, SEED)

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

    # Gate 4: PostLightSample p99.9 on common fields (ray state, throughput, lambdas).
    # For Session N+4, NEE-specific fields (nee_contribution, nee_light_pdf, etc.) are
    # TODO placeholders (0.0) and not compared. We only verify the geometric/spectral
    # state that flows through the stage. CPU emits one PostLightSample row per
    # NEE-attempted path (subset of shaded paths); subset GPU rows to that same
    # pixel index list. GPU emits a row per launch-grid pixel like PostShade.
    #
    # Session N+4 part 2 aligned CPU/GPU snapshot semantics: both now capture the
    # shading point (CPU: rec.point, GPU: hitBufs.hit_point_*) in the ray_origin
    # field, bringing p99.9 down from 1e8 to ~2e-6.
    cpu_light_sample_pixels = np.array(
        [snap['pixel_index'] for snap in cpu_post_light_sample], dtype=np.int32)
    gpu_post_light_sample_common = gpu_post_light_sample[cpu_light_sample_pixels]
    post_light_sample_p999 = _compute_stage_p999(cpu_post_light_sample, gpu_post_light_sample_common, stage='PostLightSample')

    assert post_light_sample_p999 <= gpu_thresholds["PostLightSample"]["p99_9_relative_error"], (
        f"PostLightSample p99.9 gate FAILED: measured {post_light_sample_p999:.6e}, threshold {gpu_thresholds['PostLightSample']['p99_9_relative_error']:.6e}"
    )

    # Gate 5: PostRR p99.9 on common fields. Session N+4 part 2 semantics-alignment
    # same as PostLightSample (CPU: rec.point, GPU: hitBufs.hit_point_*).
    if len(cpu_post_rr) > 0:
        cpu_rr_pixels = np.array(
            [snap['pixel_index'] for snap in cpu_post_rr], dtype=np.int32)
        gpu_post_rr_common = gpu_post_rr[cpu_rr_pixels]
        post_rr_p999 = _compute_stage_p999(cpu_post_rr, gpu_post_rr_common, stage='PostRR')

        assert post_rr_p999 <= gpu_thresholds["PostRR"]["p99_9_relative_error"], (
            f"PostRR p99.9 gate FAILED: measured {post_rr_p999:.6e}, threshold {gpu_thresholds['PostRR']['p99_9_relative_error']:.6e}"
        )
    else:
        # No bounce-0 PostRR rows on this scene (RR depth threshold not reached at
        # bounce 0). The gate is structurally inactive here; not an error.
        post_rr_p999 = 0.0

    # ASCII-safe print: cp1252 Windows consoles can't encode the bidi arrow.
    print(f"\n[pkg55-Session-N+3+N+4 CPU<->GPU threshold gate] PASS:")
    print(f"  PostInit:        ULP={post_init_ulp}, p99.9={post_init_p999:.6e}")
    print(f"  PostIntersect:   ULP={post_intersect_ulp}, p99.9={post_intersect_p999:.6e}")
    print(f"  PostShade:       p99.9={post_shade_p999:.6e}")
    print(f"  PostLightSample: p99.9={post_light_sample_p999:.6e}")
    print(f"  PostRR:          p99.9={post_rr_p999:.6e}")


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
        # pkg238: the PostInit ULP gate covers ONLY the geometry fields
        # (ray_origin, ray_direction). The `lambdas` field is intentionally
        # excluded from the ULP bound and instead governed by the PostInit
        # p99.9 relative-error bound (see _compute_stage_p999, which already
        # includes lambdas). Since pkg206 the default wavelength sampler is
        # `sampleImportance`, which inverts a logistic CDF with std::log/exp
        # (CPU, spectrum.cpp) vs logf/expf (GPU, stage_init.cu). Device
        # transcendentals are not IEEE-correctly-rounded, so lambdas drifts
        # ~13 ULP by design while geometry stays ~1-2 ULP — a tight geometry
        # ULP bound is meaningless for a transcendental field. This mirrors
        # PostShade, which already carries no max_ulp and uses p99.9 for the
        # same reason. See pkg238 and pkg55_cuda_thresholds.yaml PostInit note.
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)

        ulp_origin = _compute_ulp_distance(cpu_ray_origin.flatten(), gpu_ray_origin.flatten())
        ulp_dir = _compute_ulp_distance(cpu_ray_dir.flatten(), gpu_ray_dir.flatten())

        return max(ulp_origin, ulp_dir)

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
        # PostShade compares only ray_origin (== rec.point from PostIntersect,
        # bounded by the PostIntersect ULP gate) and lambdas (unchanged since
        # PostInit). We intentionally do NOT compare ray_direction, throughput,
        # or bsdf_pdf at this stage: spec §4.2 design decision #2 says CPU
        # uses mt19937 seeded from a PCG32 dimension for BSDF sampling while
        # GPU uses PCG32 directly. Those produce independent MC samples even
        # at matched dimensions, so post-BSDF ray_direction and throughput
        # diverge by uniform-sample variance (~1.0 absolute), not numerical
        # drift. Asserting bounded p99.9 on those is comparing apples to
        # oranges — variance, not error. The final-image SSIM gate
        # (final_image: ssim_visible ≥ 0.985) catches whole-program
        # correctness; this per-stage gate validates only that the values
        # which SHOULD be deterministic-given-the-stage actually are.
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 10:14].astype(np.float32)

        all_rel_errors.append(rel_err_p999(cpu_ray_origin, gpu_ray_origin))
        all_rel_errors.append(rel_err_p999(cpu_lambdas, gpu_lambdas))

    elif stage == 'PostLightSample':
        # PostLightSample (Session N+4): same exclusion rationale as PostShade —
        # ray_direction + throughput at this stage carry independent MC noise from
        # PostShade's BSDF sampling (spec §4.2 design decision #2: CPU mt19937 vs
        # GPU PCG32 produce different uniform samples even at matched dimensions).
        # The fields that ARE deterministic-given-the-stage: ray_origin (== shading
        # point from PostIntersect) and lambdas (unchanged since PostInit). NEE-
        # specific fields (nee_contribution, nee_light_pdf, nee_bsdf_pdf_at_dir,
        # nee_mis_weight) are TODO placeholders (0.0) on GPU and not compared.
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 10:14].astype(np.float32)

        all_rel_errors.append(rel_err_p999(cpu_ray_origin, gpu_ray_origin))
        all_rel_errors.append(rel_err_p999(cpu_lambdas, gpu_lambdas))

    elif stage == 'PostRR':
        # PostRR (Session N+4): same exclusion rationale as PostShade / PostLightSample.
        # ray_direction + throughput carry independent MC noise from PostShade's BSDF
        # sampling. Compare only deterministic-given-the-stage fields: ray_origin
        # (== shading point from PostIntersect) and lambdas (unchanged since PostInit).
        # RR-specific fields (rr_prob, rr_survived) are TODO placeholders on GPU.
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 10:14].astype(np.float32)

        all_rel_errors.append(rel_err_p999(cpu_ray_origin, gpu_ray_origin))
        all_rel_errors.append(rel_err_p999(cpu_lambdas, gpu_lambdas))

    else:
        raise ValueError(f"p99.9 comparison not defined for stage {stage}")

    return max(all_rel_errors)


def _power_heuristic(a, b):
    """Veach 1997 power heuristic with Astroray's 1e-8 div-guard.

    Identical formula + epsilon to the wavefront (gpu_nee.cuh:27-29,
    stage_advance.cu:346) and the CPU reference (path_kernel.cpp:244-245).
    """
    return (a * a) / (a * a + b * b + 1e-8)


def test_post_nee_mis_gate():
    """pkg55-C2 PostNEE_MIS gate — audit the wavefront's shade-time MIS.

    Two-tier, mirroring the merged PostShade convention:

      Tier 1 (exact) — CPU-wavefront <-> CPU-reference: the shade-time MIS
        triple (nee_light_pdf, nee_bsdf_pdf_at_dir, nee_mis_weight) is
        bit-identical by shared-kernel construction (advance_one_bounce),
        compared field-for-field by snapshot_diff.cpp:123-128 at tolerance 0.

      Tier 2 (formula parity) — the power-heuristic identity holds on BOTH
        sides with the identical formula + 1e-8 guard:
          |wt - power_heuristic(lightPdf, bsdfPdf)| <= power_heuristic_tol.
        This is the deterministic-given-stage MIS invariant. Raw MIS pdf
        VALUES are NOT compared CPU<->GPU: the template-RNG arc + the
        multi-emitter measurement scene make CPU (mt19937 substream) and GPU
        (direct PCG32) draw different light samples, so the pdfs differ by
        Monte-Carlo variance, not error (same rationale the PostShade gate
        gives for excluding bsdf_pdf). Whole-program correctness of the
        sampled values is gated by the final-image SSIM gate.

    See .astroray_plan/docs/pkg55-c2-mis-audit-research.md for the full audit.
    """
    import numpy as np
    ar = _lazy_import_astroray()
    thresholds = _load_thresholds()
    tol = thresholds["cpu_to_gpu_thresholds"]["PostNEE_MIS"]["power_heuristic_tol"]

    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 1
    MAX_DEPTH = 8

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    # --- Tier 1a: CPU-wavefront <-> CPU-reference exact bit-identity (incl. the
    # MIS triple, which snapshot_diff.cpp compares at PostLightSample). ---
    diff = ar.cpu_wavefront_snapshot_diff(r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED)
    assert diff["total_diverging_fields"] == 0 and diff["max_abs_diff"] == 0.0, (
        "PostNEE_MIS tier-1 FAILED: CPU-wavefront and CPU-reference diverge on the "
        f"MIS triple (or any field): {diff['total_diverging_fields']} fields, "
        f"max |diff|={diff['max_abs_diff']}.\n{diff['report']}"
    )

    # --- Tier 1b: the CPU reference itself satisfies the power-heuristic identity. ---
    cpu = ar.reference_pt_wavefront_render(r, SPP, MAX_DEPTH, SEED, True)
    cpu_ls = [s for s in cpu["snapshots"]
              if s["stage"] == 3 and s["bounce"] == 0]  # PostLightSample, bounce 0
    assert len(cpu_ls) > 0, (
        "PostNEE_MIS: no NEE fired on the CPU reference — the scene must exercise "
        "NEE for this gate to be meaningful. Investigate the scene/light setup."
    )
    cpu_lp = np.array([s["nee_light_pdf"] for s in cpu_ls], dtype=np.float64)
    cpu_bp = np.array([s["nee_bsdf_pdf_at_dir"] for s in cpu_ls], dtype=np.float64)
    cpu_wt = np.array([s["nee_mis_weight"] for s in cpu_ls], dtype=np.float64)
    cpu_resid = np.max(np.abs(cpu_wt - _power_heuristic(cpu_lp, cpu_bp)))
    assert cpu_resid <= tol, (
        f"PostNEE_MIS tier-1b FAILED: CPU nee_mis_weight is not the power heuristic "
        f"of (nee_light_pdf, nee_bsdf_pdf_at_dir); max residual {cpu_resid:.3e} > {tol:.3e}."
    )
    assert np.all(cpu_lp > 0.0), "CPU nee_light_pdf must be > 0 wherever NEE fired."
    assert np.all((cpu_wt >= 0.0) & (cpu_wt <= 1.0)), "CPU MIS weight out of [0,1]."

    # --- Tier 2: GPU formula parity (skips without CUDA). ---
    if not hasattr(ar, 'cuda_wavefront_snapshot_post_nee_mis'):
        pytest.skip("CUDA wavefront not available. Build with -DASTRORAY_WAVEFRONT_CUDA_N3=ON.")

    gpu = np.asarray(
        ar.cuda_wavefront_snapshot_post_nee_mis(r, WIDTH, HEIGHT, SEED),
        dtype=np.float64).reshape(-1, 3)
    fired = gpu[:, 0] > 0.0  # path_light_pdf sentinel: 0 => no NEE at this slot
    n_fired = int(fired.sum())
    assert n_fired > 0, (
        "PostNEE_MIS: no NEE fired on the GPU wavefront (all path_light_pdf==0). "
        "The instrumented shade kernel did not record any MIS sample."
    )
    g_lp = gpu[fired, 0]
    g_bp = gpu[fired, 1]
    g_wt = gpu[fired, 2]
    gpu_resid = float(np.max(np.abs(g_wt - _power_heuristic(g_lp, g_bp))))
    assert gpu_resid <= tol, (
        f"PostNEE_MIS tier-2 FAILED: GPU path_mis_weight is not the power heuristic "
        f"of (path_light_pdf, path_mis_pdf); max residual {gpu_resid:.3e} > {tol:.3e}. "
        f"The kernel is not applying Veach 1997 to the pdfs it captured."
    )
    assert np.all(g_lp > 0.0), "GPU path_light_pdf must be > 0 wherever NEE fired."
    assert np.all(g_bp >= 0.0), "GPU path_mis_pdf (BSDF pdf) must be >= 0."
    assert np.all((g_wt >= 0.0) & (g_wt <= 1.0)), "GPU MIS weight out of [0,1]."

    # ASCII-safe print (cp1252 Windows consoles).
    print(f"\n[pkg55-C2 PostNEE_MIS gate] PASS:")
    print(f"  Tier 1  CPU-wf<->CPU-ref exact: 0 diverging fields")
    print(f"  Tier 1b CPU power-heuristic identity: max residual {cpu_resid:.3e} "
          f"over {len(cpu_ls)} NEE rows")
    print(f"  Tier 2  GPU power-heuristic identity: max residual {gpu_resid:.3e} "
          f"over {n_fired} NEE rows (tol {tol:.3e})")


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
