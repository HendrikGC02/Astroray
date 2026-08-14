"""pkg198 Stage 2 — GPU wavefront light-path render-pass mirror.

Mirrors the Stage-1 CPU classification (test_pkg198_lightpath_passes.py) on the
GPU wavefront so the passes agree CPU<->GPU on the default backend. Gates:

  1. GPU sum-to-beauty: Σ(GPU light-path passes) == GPU beauty (energy closure of
     the partition on the wavefront), per-channel mean-ratio + pixelwise rel-L1.
  2. CPU<->GPU per-pass parity: each light-path pass agrees in aggregate (per-
     channel mean-ratio) within the MC + classification-edge band. Independent RNG
     streams, so this is a mean-ratio gate (NOT SSIM / not pixelwise) per
     [[ssim-wrong-gate-for-independent-rng]].
  3. Fleet inertness: with passes OFF the GPU beauty is byte-identical to a passes-
     ON beauty (the partition must not perturb the beauty math).

The register HARD gate (fleet shade kernel 254/3352/1700, intersect<false> 127/616)
is a cuobjdump check run at build time, reported in the PR — not a pytest gate.

Design/citations: Cycles kernel/film/light_passes.h + integrator/shade_surface.h
(Apache-2.0); see .astroray_plan/docs/pkg198-lightpath-pass-classification-research.md
and the pkg198 spec Stage-2 section.
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

LIGHT_PATH_PASSES = [
    "diffuse_direct", "diffuse_indirect",
    "glossy_direct", "glossy_indirect",
    "transmission_direct", "transmission_indirect",
    "emission", "environment",
]


def _has_cuda_gpu(renderer):
    return (
        bool(astroray.__features__.get("cuda", False))
        and bool(getattr(renderer, "gpu_available", False))
    )


def _camera(r, w=64, h=64):
    r.setup_camera(
        look_from=[0, 0, 6], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=6.0,
        width=w, height=h,
    )


def _build_all_lobe(r):
    """The Stage-1 all-lobe scene: diffuse floor + metal + glass + emitter +
    a directly-visible non-black background."""
    _camera(r)
    r.set_background_color([0.10, 0.12, 0.18])
    diffuse = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    metal = r.create_material("metal", [0.9, 0.9, 0.9], {"roughness": 0.15})
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    emit = r.create_material("light", [1.0, 0.9, 0.7], {"intensity": 6.0})
    r.add_sphere([0, -1001.2, 0], 1000.0, diffuse)   # floor
    r.add_sphere([-1.4, -0.3, 0.2], 0.9, metal)
    r.add_sphere([1.4, -0.3, 0.4], 0.9, glass)
    r.add_sphere([0.0, 1.5, -0.5], 0.5, emit)
    r.add_point_light([3, 4, 3], {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}, 60.0)


def _sum_passes(r):
    total = None
    for name in LIGHT_PATH_PASSES:
        buf = np.array(r.get_render_pass_buffer(name), dtype=np.float64)
        total = buf if total is None else total + buf
    return total


def _skip_if_no_gpu():
    probe = astroray.Renderer()
    if not _has_cuda_gpu(probe):
        pytest.skip("CUDA GPU not available")


def test_gpu_sum_to_beauty(test_results_dir):
    """Gate 1: Σ(GPU passes) == GPU beauty (partition energy closure), LINEAR."""
    _skip_if_no_gpu()
    r = astroray.Renderer()
    r.set_use_gpu(True)
    r.set_gpu_light_path_passes(True)
    _build_all_lobe(r)
    r.set_seed(1234)
    beauty = np.array(
        r.render(samples_per_pixel=128, max_depth=6, apply_gamma=False),
        dtype=np.float64,
    )
    passes_sum = _sum_passes(r)

    beauty_mean = beauty.reshape(-1, 3).mean(axis=0)
    passes_mean = passes_sum.reshape(-1, 3).mean(axis=0)
    ratio = passes_mean / np.maximum(beauty_mean, 1e-6)
    denom = np.maximum(np.abs(beauty).sum(), 1e-6)
    rel_l1 = np.abs(passes_sum - beauty).sum() / denom
    print(f"[pkg198-s2] GPU sum-to-beauty per-channel ratio = {ratio}, rel_L1 = {rel_l1:.5f}")
    # Slightly looser than the CPU Stage-1 gate: the GPU per-pixel XYZ atomic adds
    # accumulate in a different order than the single-threaded CPU sum (~2e-7 float
    # floor) and the deferred-NEE clamp split resolves in a separate kernel.
    assert np.allclose(ratio, 1.0, atol=0.03), f"GPU per-channel ratio off: {ratio}"
    assert rel_l1 < 0.03, f"GPU pixelwise rel-L1 too high: {rel_l1:.5f}"


def test_gpu_fleet_inert_beauty(test_results_dir):
    """Gate 3: passes ON vs OFF leave the GPU beauty unchanged (the partition must
    not perturb the beauty math). Same seed → the wavefront is deterministic given
    the seed, so this is a tight bound (only the pass-write side effects differ)."""
    _skip_if_no_gpu()

    def _beauty(passes_on):
        r = astroray.Renderer()
        r.set_use_gpu(True)
        r.set_gpu_light_path_passes(passes_on)
        _build_all_lobe(r)
        r.set_seed(777)
        return np.array(
            r.render(samples_per_pixel=64, max_depth=6, apply_gamma=False),
            dtype=np.float64,
        )

    off = _beauty(False)
    on = _beauty(True)
    max_abs = float(np.abs(on - off).max())
    print(f"[pkg198-s2] passes ON vs OFF beauty max abs diff = {max_abs:.3e}")
    # The classification lock is a pure side-effect store (no RNG draw, no beauty
    # math), so the beauty must match to the float floor.
    assert max_abs < 1e-4, f"passes toggled the beauty: max abs diff {max_abs:.3e}"


def test_cpu_gpu_pass_parity(test_results_dir):
    """Gate 2: each light-path pass agrees CPU<->GPU in aggregate (per-channel
    mean-ratio). Independent RNG streams → mean-ratio, not pixelwise/SSIM."""
    _skip_if_no_gpu()
    spp, depth = 160, 6

    cpu = astroray.Renderer()
    _build_all_lobe(cpu)
    cpu.set_seed(20)
    cpu.render(samples_per_pixel=spp, max_depth=depth, apply_gamma=False)
    cpu_pass = {n: np.array(cpu.get_render_pass_buffer(n), dtype=np.float64)
                for n in LIGHT_PATH_PASSES}

    gpu = astroray.Renderer()
    gpu.set_use_gpu(True)
    gpu.set_gpu_light_path_passes(True)
    _build_all_lobe(gpu)
    gpu.set_seed(20)
    gpu.render(samples_per_pixel=spp, max_depth=depth, apply_gamma=False)
    gpu_pass = {n: np.array(gpu.get_render_pass_buffer(n), dtype=np.float64)
                for n in LIGHT_PATH_PASSES}

    # Compare only passes that carry meaningful energy on the CPU reference; a pass
    # that is ~zero on both (e.g. transmission_direct — NEE never fires through a
    # delta lobe) trivially matches and is reported but not ratio-gated.
    failures = []
    for n in LIGHT_PATH_PASSES:
        c = cpu_pass[n].reshape(-1, 3).mean(axis=0)
        g = gpu_pass[n].reshape(-1, 3).mean(axis=0)
        cmag = float(np.linalg.norm(c))
        gmag = float(np.linalg.norm(g))
        print(f"[pkg198-s2] pass {n:22s} CPU mean={c} GPU mean={g}")
        if cmag < 1e-4 and gmag < 1e-4:
            continue  # both empty — nothing to compare
        ratio = (gmag + 1e-8) / (cmag + 1e-8)
        # Aggregate mean-ratio band: MC noise at this spp + the documented
        # classification edge cases (rough-glass direct NEE, volume split) admit a
        # wider band than the CPU sum-to-beauty invariant.
        if not (0.75 < ratio < 1.33):
            failures.append((n, ratio, c.tolist(), g.tolist()))
    assert not failures, "CPU<->GPU per-pass parity out of band:\n" + \
        "\n".join(f"  {n}: ratio={r:.3f} cpu={c} gpu={g}" for n, r, c, g in failures)
