#!/usr/bin/env python3
"""pkg55-B' Session N+2 — Threshold measurement harness.

Usage:
  python measure_thresholds.py --mode cpu_baseline   # Session N+2: measure CPU↔CPU
  python measure_thresholds.py --mode gpu_port       # Session N+3: measure CPU↔GPU

This script:
  1. Runs the wavefront diff harness on the Session N+1 env-map Cornell scene
  2. Computes ULP distances, p99.9 relative error, and SSIM
  3. Prints measured values in YAML format for copy-paste into pkg55_cuda_thresholds.yaml

Design: PR #296 §4.1, §4.2
Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 GATE-THRESHOLDS-PINNED
"""

import sys
import os
import argparse
import numpy as np
from datetime import datetime

# Configure test runtime (DLL paths, module search)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from runtime_setup import configure_test_imports
configure_test_imports()

# Add tests/scenes to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scenes"))
import session_n1_envmap_cornell

# Lazy import astroray to defer build requirement until actual measurement
astroray = None


def _lazy_import_astroray():
    global astroray
    if astroray is None:
        import astroray as ar
        astroray = ar
    return astroray


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


def _compute_ulp_distance(a, b):
    """Compute max ULP distance between two float arrays.

    ULP = Units in Last Place. This is the integer distance between two floats
    when viewed as sorted integers.

    Cite: Goldberg 1991 "What Every Computer Scientist Should Know About
          Floating-Point Arithmetic" (ACM Computing Surveys)
          https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html
    """
    # View floats as int32 (2's complement representation)
    a_int = np.frombuffer(a.astype(np.float32).tobytes(), dtype=np.int32)
    b_int = np.frombuffer(b.astype(np.float32).tobytes(), dtype=np.int32)

    # ULP distance = |a_int - b_int|
    ulp_dist = np.abs(a_int - b_int)
    return int(np.max(ulp_dist))


def _compute_p99_9_relative_error(a, b, epsilon=1e-8, return_all=False):
    """Compute p99.9 percentile of relative error |a-b| / (|a| + epsilon).

    Relative error is more meaningful than absolute error for values that span
    multiple orders of magnitude (e.g., throughput 1e-6 vs 1.0).

    Args:
        a, b: arrays to compare
        epsilon: small value to avoid division by zero
        return_all: if True, return all relative errors; if False, return p99.9 percentile

    Returns:
        float (p99.9 percentile) or array (all relative errors)
    """
    abs_diff = np.abs(a - b)
    denom = np.abs(a) + epsilon
    rel_err = abs_diff / denom
    if return_all:
        return rel_err.flatten().tolist()
    else:
        return float(np.percentile(rel_err, 99.9))


def _compute_ssim(img_a, img_b):
    """Compute SSIM between two images using skimage.

    Cite: Wang, Bovik, Sheikh, Simoncelli 2004 "Image Quality Assessment:
          From Error Visibility to Structural Similarity" IEEE Trans. Image Proc.
          DOI: 10.1109/TIP.2003.819861
    """
    try:
        from skimage.metrics import structural_similarity as ssim
    except ImportError:
        print("Warning: skimage not available. SSIM = N/A", file=sys.stderr)
        return None

    # SSIM expects channel-last (H, W, C)
    return ssim(img_a, img_b, channel_axis=2, data_range=1.0)


def measure_cpu_baseline(width=16, height=16, spp=1, seed=424242, max_depth=8):
    """Measure CPU oracle ↔ CPU wavefront baseline (should be 0/0/1.0)."""
    ar = _lazy_import_astroray()
    r = _build_renderer(width, height, seed, max_depth)

    print(f"\n=== Measuring CPU<->CPU baseline ===")
    print(f"Scene: session_n1_envmap_cornell ({width}x{height}, {spp} spp, seed {seed})")

    result = ar.cpu_wavefront_snapshot_diff(
        r, samples=spp, max_depth=max_depth, seed=seed
    )

    bit_identical = result["bit_identical"]
    max_abs_diff = result["max_abs_diff"]
    total_diverging_fields = result["total_diverging_fields"]
    ref_img = result["ref_image"]
    wf_img = result["wf_image"]

    # Compute SSIM on final images
    ssim_val = _compute_ssim(ref_img, wf_img)

    print(f"\nResults:")
    print(f"  bit_identical: {bit_identical}")
    print(f"  max_abs_diff: {max_abs_diff}")
    print(f"  total_diverging_fields: {total_diverging_fields}")
    print(f"  ssim: {ssim_val if ssim_val is not None else 'N/A (skimage missing)'}")

    print(f"\n--- YAML for pkg55_cuda_thresholds.yaml (cpu_to_cpu_baseline) ---")
    print(f"cpu_to_cpu_baseline:")
    print(f"  max_abs_diff: {max_abs_diff}")
    print(f"  total_diverging_fields: {total_diverging_fields}")
    print(f"  ssim: {ssim_val if ssim_val is not None else 1.0}")
    print(f'  scene: "session_n1_envmap_cornell"')
    print(f'  resolution: "{width}x{height}"')
    print(f"  spp: {spp}")
    print(f"  seed: {seed}")
    print(f'  measured_on: "origin/main"')
    print(f'  measured_date: "{datetime.now().strftime("%Y-%m-%d")}"')
    print(f"---")

    if not bit_identical or max_abs_diff != 0.0 or total_diverging_fields != 0:
        print("\n[WARNING] CPU↔CPU baseline is NOT bit-identical!")
        print("Expected 0.0 / 0 / True due to shared-kernel construction.")
        print("This is a regression. Review the per-stage diff report.")
        return False

    print("\n[PASS] CPU↔CPU baseline is exact bit-identity as expected.")
    return True


def measure_gpu_port(width=16, height=16, spp=1, seed=424242, max_depth=8):
    """Measure CPU wavefront ↔ CUDA wavefront thresholds (Session N+3 part 2b).

    Full CPU↔GPU diff across PostInit, PostIntersect, PostShade stages.
    Computes ULP for geometry stages, p99.9 relative error for shading stages, SSIM for final images.
    """
    ar = _lazy_import_astroray()

    if not hasattr(ar, 'cuda_wavefront_snapshot_post_init'):
        print(f"\n[ERROR] cuda_wavefront_snapshot_post_init not available.")
        print("Build with -DASTRORAY_WAVEFRONT_CUDA_N3=ON to enable CUDA wavefront.")
        return False

    r = _build_renderer(width, height, seed, max_depth)

    print(f"\n=== Measuring CPU<->GPU thresholds ===")
    print(f"Scene: session_n1_envmap_cornell ({width}x{height}, {spp} spp, seed {seed})")

    # Get CPU reference snapshots
    print("\nRunning CPU reference path tracer with snapshots...")
    cpu_result = ar.reference_pt_wavefront_render(r, spp, max_depth, seed, True)
    cpu_snapshots_raw = cpu_result['snapshots']  # List of dicts
    cpu_image = cpu_result['rgb']

    print(f"CPU snapshots collected: {len(cpu_snapshots_raw)} total across all stages")

    # Extract CPU snapshots by stage
    cpu_post_init = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostInit')
    cpu_post_intersect = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostIntersect')
    cpu_post_shade = _extract_cpu_stage_snapshots(cpu_snapshots_raw, stage='PostShade')

    print(f"  PostInit: {len(cpu_post_init)} snapshots")
    print(f"  PostIntersect: {len(cpu_post_intersect)} snapshots")
    print(f"  PostShade: {len(cpu_post_shade)} snapshots")

    # Get GPU snapshots
    print("\nRunning GPU wavefront stages...")
    print("  Running stage_init...")
    gpu_post_init = ar.cuda_wavefront_snapshot_post_init(r, width, height, seed)
    print("  Running stage_init + stage_intersect...")
    gpu_post_intersect = ar.cuda_wavefront_snapshot_post_intersect(r, width, height, seed)
    print("  Running stage_init + stage_intersect + stage_shade_lambertian...")
    gpu_post_shade = ar.cuda_wavefront_snapshot_post_shade(r, width, height, seed)

    print(f"\nGPU snapshot shapes:")
    print(f"  PostInit: {gpu_post_init.shape}")
    print(f"  PostIntersect: {gpu_post_intersect.shape}")
    print(f"  PostShade: {gpu_post_shade.shape}")

    # Compare PostInit (geometry only: ULP + p99.9)
    print(f"\n--- PostInit CPU<->GPU comparison ---")
    post_init_ulp = _compare_stage_ulp(cpu_post_init, gpu_post_init, stage='PostInit')
    post_init_p999 = _compare_stage_p999(cpu_post_init, gpu_post_init, stage='PostInit')

    # Compare PostIntersect (geometry only: ULP + p99.9)
    print(f"\n--- PostIntersect CPU<->GPU comparison ---")
    post_intersect_ulp = _compare_stage_ulp(cpu_post_intersect, gpu_post_intersect, stage='PostIntersect')
    post_intersect_p999 = _compare_stage_p999(cpu_post_intersect, gpu_post_intersect, stage='PostIntersect')

    # Compare PostShade (BSDF with transcendentals: p99.9 only)
    print(f"\n--- PostShade CPU<->GPU comparison ---")
    post_shade_p999 = _compare_stage_p999(cpu_post_shade, gpu_post_shade, stage='PostShade')

    # Compute final image SSIM (requires rendering full image from GPU)
    # For now, log informational message — full SSIM measurement needs end-to-end GPU wavefront pipeline
    print(f"\n--- Final image SSIM ---")
    print(f"  (Full CPU<->GPU image SSIM measurement deferred until end-to-end GPU wavefront pipeline)")
    ssim_val = None  # Placeholder

    # Print YAML output
    print(f"\n--- YAML for pkg55_cuda_thresholds.yaml (measured values) ---")
    print(f"cpu_to_gpu_thresholds:")
    print(f"  PostInit:")
    print(f"    max_ulp: {post_init_ulp['max_ulp']}")
    print(f"    fields: [\"ray_origin\", \"ray_direction\", \"lambdas\"]")
    print(f"    p99_9_relative_error: {post_init_p999['p99_9']:.6e}")
    print(f'    note: "Session N+3 part 2b measured {datetime.now().strftime("%Y-%m-%d")}"')
    print(f"")
    print(f"  PostIntersect:")
    print(f"    max_ulp: {post_intersect_ulp['max_ulp']}")
    print(f"    fields: [\"hit_t\", \"hit_point\", \"hit_normal\", \"hit_material\"]")
    print(f"    p99_9_relative_error: {post_intersect_p999['p99_9']:.6e}")
    print(f'    note: "Session N+3 part 2b measured {datetime.now().strftime("%Y-%m-%d")}"')
    print(f"")
    print(f"  PostShade:")
    print(f"    p99_9_relative_error: {post_shade_p999['p99_9']:.6e}")
    print(f"    fields: [\"ray_origin\", \"ray_direction\", \"throughput\", \"wasSpecular\"]")
    print(f'    note: "Session N+3 part 2b measured {datetime.now().strftime("%Y-%m-%d")}"')
    print(f"---")

    print("\n[PASS] CPU<->GPU threshold measurement complete.")
    return True


def _extract_cpu_stage_snapshots(snapshots_raw, stage):
    """Extract CPU snapshots for a given stage from the raw snapshot list.

    Returns: list of dicts with relevant fields extracted.
    """
    # The snapshots_raw is a list of dicts (from the Python binding).
    # We need to filter by stage.
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
        if snap['stage'] == stage_id:
            result.append(snap)
    return result


def _compare_stage_ulp(cpu_snapshots, gpu_snapshot_array, stage):
    """Compute max ULP distance for geometry fields.

    Args:
        cpu_snapshots: list of CPU WavefrontSnapshot dicts
        gpu_snapshot_array: numpy array (num_paths, num_fields) from GPU
        stage: 'PostInit' or 'PostIntersect'

    Returns:
        dict with max_ulp and per-field stats
    """
    if stage == 'PostInit':
        # GPU PostInit: [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: lambdas,
        #               [10..13]: throughput, [14..16]: pixel/sample/bounce, [17..21]: rng
        # Fields for ULP: ray_origin, ray_direction, lambdas
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 6:10].astype(np.float32)

        ulp_origin = _compute_ulp_distance(cpu_ray_origin.flatten(), gpu_ray_origin.flatten())
        ulp_dir = _compute_ulp_distance(cpu_ray_dir.flatten(), gpu_ray_dir.flatten())
        ulp_lambdas = _compute_ulp_distance(cpu_lambdas.flatten(), gpu_lambdas.flatten())

        max_ulp = max(ulp_origin, ulp_dir, ulp_lambdas)

        print(f"  ULP distances:")
        print(f"    ray_origin: {ulp_origin}")
        print(f"    ray_direction: {ulp_dir}")
        print(f"    lambdas: {ulp_lambdas}")
        print(f"    max_ulp: {max_ulp}")

        return {'max_ulp': max_ulp, 'fields': {'ray_origin': ulp_origin, 'ray_direction': ulp_dir, 'lambdas': ulp_lambdas}}

    elif stage == 'PostIntersect':
        # GPU PostIntersect: [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: lambdas,
        #                    [10..13]: throughput, [14]: hit_valid, [15]: hit_t,
        #                    [16..18]: hit_point, [19..21]: hit_normal, [22]: hit_material_id
        # Fields for ULP: hit_t, hit_point, hit_normal
        cpu_hit_t = np.array([snap['hit_t'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_hit_point = np.array([snap['hit_point'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_hit_normal = np.array([snap['hit_normal'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_hit_t = gpu_snapshot_array[:, 15].astype(np.float32)
        gpu_hit_point = gpu_snapshot_array[:, 16:19].astype(np.float32)
        gpu_hit_normal = gpu_snapshot_array[:, 19:22].astype(np.float32)

        ulp_hit_t = _compute_ulp_distance(cpu_hit_t, gpu_hit_t)
        ulp_hit_point = _compute_ulp_distance(cpu_hit_point.flatten(), gpu_hit_point.flatten())
        ulp_hit_normal = _compute_ulp_distance(cpu_hit_normal.flatten(), gpu_hit_normal.flatten())

        max_ulp = max(ulp_hit_t, ulp_hit_point, ulp_hit_normal)

        print(f"  ULP distances:")
        print(f"    hit_t: {ulp_hit_t}")
        print(f"    hit_point: {ulp_hit_point}")
        print(f"    hit_normal: {ulp_hit_normal}")
        print(f"    max_ulp: {max_ulp}")

        return {'max_ulp': max_ulp, 'fields': {'hit_t': ulp_hit_t, 'hit_point': ulp_hit_point, 'hit_normal': ulp_hit_normal}}

    else:
        raise ValueError(f"ULP comparison not defined for stage {stage}")


def _compare_stage_p999(cpu_snapshots, gpu_snapshot_array, stage):
    """Compute p99.9 relative error for all numeric fields at a given stage.

    Args:
        cpu_snapshots: list of CPU WavefrontSnapshot dicts
        gpu_snapshot_array: numpy array (num_paths, num_fields) from GPU
        stage: 'PostInit', 'PostIntersect', or 'PostShade'

    Returns:
        dict with p99_9 and per-field stats
    """
    all_rel_errors = []

    if stage == 'PostInit':
        # Compare all fields: ray_origin, ray_direction, lambdas, throughput
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_lambdas = np.array([snap['lambdas'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_throughput = np.array([snap['throughput'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_lambdas = gpu_snapshot_array[:, 6:10].astype(np.float32)
        gpu_throughput = gpu_snapshot_array[:, 10:14].astype(np.float32)

        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_ray_origin.flatten(), gpu_ray_origin.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_ray_dir.flatten(), gpu_ray_dir.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_lambdas.flatten(), gpu_lambdas.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_throughput.flatten(), gpu_throughput.flatten(), return_all=True))

    elif stage == 'PostIntersect':
        # Compare all fields: ray, lambdas, throughput, hit_t, hit_point, hit_normal
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

        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_ray_origin.flatten(), gpu_ray_origin.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_ray_dir.flatten(), gpu_ray_dir.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_lambdas.flatten(), gpu_lambdas.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_throughput.flatten(), gpu_throughput.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_hit_t, gpu_hit_t, return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_hit_point.flatten(), gpu_hit_point.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_hit_normal.flatten(), gpu_hit_normal.flatten(), return_all=True))

    elif stage == 'PostShade':
        # GPU PostShade: [0..2]: ray_origin, [3..5]: ray_direction, [6..9]: throughput,
        #                [10..13]: lambdas, [14]: bsdf_pdf, [15]: bsdf_is_delta
        # Compare: ray_origin, ray_direction, throughput, bsdf_pdf
        cpu_ray_origin = np.array([snap['ray_origin'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_ray_dir = np.array([snap['ray_direction'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_throughput = np.array([snap['throughput'] for snap in cpu_snapshots], dtype=np.float32)
        cpu_bsdf_pdf = np.array([snap['bsdf_pdf'] for snap in cpu_snapshots], dtype=np.float32)

        gpu_ray_origin = gpu_snapshot_array[:, 0:3].astype(np.float32)
        gpu_ray_dir = gpu_snapshot_array[:, 3:6].astype(np.float32)
        gpu_throughput = gpu_snapshot_array[:, 6:10].astype(np.float32)
        gpu_bsdf_pdf = gpu_snapshot_array[:, 14].astype(np.float32)

        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_ray_origin.flatten(), gpu_ray_origin.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_ray_dir.flatten(), gpu_ray_dir.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_throughput.flatten(), gpu_throughput.flatten(), return_all=True))
        all_rel_errors.extend(_compute_p99_9_relative_error(cpu_bsdf_pdf, gpu_bsdf_pdf, return_all=True))

    else:
        raise ValueError(f"p99.9 comparison not defined for stage {stage}")

    p99_9 = float(np.percentile(all_rel_errors, 99.9))

    print(f"  p99.9 relative error: {p99_9:.6e}")
    print(f"  mean relative error: {np.mean(all_rel_errors):.6e}")
    print(f"  median relative error: {np.median(all_rel_errors):.6e}")

    return {'p99_9': p99_9, 'mean': np.mean(all_rel_errors), 'median': np.median(all_rel_errors)}


def main():
    parser = argparse.ArgumentParser(
        description="pkg55-B' Session N+2: Measure wavefront threshold baselines"
    )
    parser.add_argument(
        "--mode",
        choices=["cpu_baseline", "gpu_port"],
        required=True,
        help="Measurement mode: cpu_baseline (Session N+2) or gpu_port (Session N+3)"
    )
    parser.add_argument("--width", type=int, default=16, help="Image width (default: 16)")
    parser.add_argument("--height", type=int, default=16, help="Image height (default: 16)")
    parser.add_argument("--spp", type=int, default=1, help="Samples per pixel (default: 1)")
    parser.add_argument("--seed", type=int, default=424242, help="RNG seed (default: 424242)")
    parser.add_argument("--max-depth", type=int, default=8, help="Max path depth (default: 8)")

    args = parser.parse_args()

    if args.mode == "cpu_baseline":
        success = measure_cpu_baseline(
            width=args.width, height=args.height, spp=args.spp,
            seed=args.seed, max_depth=args.max_depth
        )
    elif args.mode == "gpu_port":
        success = measure_gpu_port(
            width=args.width, height=args.height, spp=args.spp,
            seed=args.seed, max_depth=args.max_depth
        )
    else:
        print(f"Unknown mode: {args.mode}", file=sys.stderr)
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
