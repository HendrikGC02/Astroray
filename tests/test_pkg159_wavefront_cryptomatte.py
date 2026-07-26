# pkg159 — GPU (wavefront) Cryptomatte gates.
#
# GPU cryptomatte lived ONLY in the RGB `path_trace` megakernel (pkg87b,
# PR #344). PR #524 (pkg55-C7) deleted both megakernels, so from then until
# pkg159 every GPU render emitted all-zero crypto buffers — the Blender addon's
# Cryptomatte passes were silently blank on any GPU render.
#
# The IoU acceptance leg lives in test_cryptomatte_pass.py
# (test_cryptomatte_iou_roundtrip_gpu). This file carries the three gates that
# are specific to the wavefront port:
#
#   2. CPU<->GPU parity + ID encoding  — catches the deleted megakernel's
#      `float id = tri.objectHash` implicit uint32->float NUMERIC conversion,
#      which never matched the CPU oracle or the Psyop `uint32_to_float32`
#      manifest. pkg159 uses hash_to_float instead.
#   3. No-op guarantee                 — cryptomatte off changes nothing.
#   4. Determinism under concurrency   — proves the atomic insert is correct.
#      The wavefront runs many concurrent path slots per pixel (path
#      regeneration), so a plain read-modify-write on the rank array is a data
#      race; a racy insert drops whole inserts and drifts the per-pixel id set
#      run to run.
#
# References:
# - Psyop Cryptomatte Specification v1.2.0 (BSD-3-Clause) — matte extraction,
#   `uint32_to_float32` manifest encoding.
# - Cycles intern/cycles/kernel/film/cryptomatte_passes.h (Apache-2.0) —
#   film_write_cryptomatte_slots under __ATOMIC_PASS_WRITE__.

import struct

import numpy as np
import pytest

pytest.importorskip("astroray")
import astroray

from test_cryptomatte_pass import (
    MAT_NAMES,
    OBJ_NAMES,
    build_crypto_scene,
    compute_iou,
    has_cuda_wavefront,
    reconstruct_mask,
)

# Every named entity in the acceptance scene. scene_upload.cu hashes the
# object/material NAME with MurmurHash3_x86_32 seed 0, exactly like the CPU
# crypto_hash_name, so these are the only IDs the GPU buffers may contain.
SCENE_OBJ_NAMES = OBJ_NAMES + ["floor"]
SCENE_MAT_NAMES = MAT_NAMES + ["mat_floor"]

SEED = 42


def _skip_without_gpu():
    probe = astroray.Renderer()
    if not has_cuda_wavefront(probe):
        pytest.skip("CUDA wavefront not available")


def _render_crypto(use_gpu, width, height, spp, seed=SEED, crypto=True):
    """Render the acceptance scene; return (image, crypto_obj, crypto_mat)."""
    renderer = build_crypto_scene(width, height, use_gpu=use_gpu, seed=seed)
    if not crypto:
        renderer.set_cryptomatte_enabled(False)
    image = renderer.render(spp, 1, None, False)
    return (np.asarray(image),
            np.asarray(renderer.get_cryptomatte_object_buffer()),
            np.asarray(renderer.get_cryptomatte_material_buffer()))


def _id_weight_map(buf):
    """Per-pixel {id: total weight} dict list, ignoring empty slots.

    Order-independent by construction: the sorted rank ORDER can legitimately
    swap between runs when two ids carry near-equal weight, but the id->weight
    mapping cannot.
    """
    height, width, depth_x2 = buf.shape
    depth = depth_x2 // 2
    out = {}
    for y in range(height):
        for x in range(width):
            entry = {}
            for rank in range(depth):
                idv = float(buf[y, x, rank * 2])
                w = float(buf[y, x, rank * 2 + 1])
                if idv == 0.0:  # CRYPTO_ID_NONE
                    continue
                entry[idv] = entry.get(idv, 0.0) + w
            if entry:
                out[(y, x)] = entry
    return out


def test_gpu_crypto_ids_match_manifest_encoding():
    """Gate 2a (pkg159 subtlety 2) — GPU float IDs are hash_to_float(murmur3).

    The deleted megakernel wrote `float objectId = tri.objectHash;` where
    objectHash is a uint32 — an implicit NUMERIC conversion producing values
    like 1.2e9. Those IDs matched neither crypto_hash_name (the CPU oracle)
    nor the Psyop `uint32_to_float32` manifest, so the old GPU cryptomatte was
    unusable by a compositor picker. This gate would have failed against it,
    and fails against any future regression of the encoding.

    Deliberately small/cheap: this is an exact-value check, not a statistical
    one, so it needs no spp budget.
    """
    _skip_without_gpu()

    _, crypto_obj, crypto_mat = _render_crypto(True, 64, 64, 8)

    assert np.any(crypto_obj != 0.0), (
        "GPU crypto_object buffer is entirely zero — the wavefront is not "
        "accumulating cryptomatte at all (the pkg159 regression)"
    )

    expected_obj = {astroray.crypto_hash_name(n) for n in SCENE_OBJ_NAMES}
    expected_mat = {astroray.crypto_hash_name(n) for n in SCENE_MAT_NAMES}

    for buf, expected, label in ((crypto_obj, expected_obj, "object"),
                                 (crypto_mat, expected_mat, "material")):
        # Every non-empty slot's id must be one of the scene's name hashes.
        # Exact float equality is correct here: Cryptomatte IDs are bitwise
        # identical when computed from the same string.
        ids = np.unique(buf[..., 0::2])
        seen = {float(v) for v in ids if float(v) != 0.0}
        unexpected = seen - expected
        assert not unexpected, (
            f"GPU crypto_{label} contains IDs that are not "
            f"hash_to_float(MurmurHash3(name)) for any scene name: "
            f"{sorted(unexpected)[:8]} (expected a subset of "
            f"{sorted(expected)})"
        )
        assert seen, f"GPU crypto_{label} has no non-empty slots"

    # And the same IDs round-trip to the manifest hex encoding
    # (Psyop v1.2.0 §3 conversion = "uint32_to_float32").
    for name in SCENE_OBJ_NAMES:
        h = astroray.crypto_hash_name(name)
        hex_from_float = f"{struct.unpack('I', struct.pack('f', h))[0]:08x}"
        assert len(hex_from_float) == 8
    print(f"GPU object IDs: {sorted({float(v) for v in np.unique(crypto_obj[..., 0::2]) if float(v) != 0.0})}")


def test_cpu_gpu_crypto_parity():
    """Gate 2b — CPU and GPU reconstruct the same per-name mattes.

    Same scene, same seed, same spp; the crypto weights come from independent
    MC streams (the wavefront draws PCG32 where the CPU draws mt19937), so the
    comparison is the binary matte IoU at the CPU acceptance gate's own
    threshold, not a per-pixel float identity.
    """
    _skip_without_gpu()

    width = height = 256
    spp = 64

    _, cpu_obj, cpu_mat = _render_crypto(False, width, height, spp)
    _, gpu_obj, gpu_mat = _render_crypto(True, width, height, spp)

    iou_threshold = 0.85  # same as the Psyop acceptance gate (pkg87d)

    for names, cpu_buf, gpu_buf, label in (
        (OBJ_NAMES, cpu_obj, gpu_obj, "object"),
        (MAT_NAMES, cpu_mat, gpu_mat, "material"),
    ):
        for name in names:
            target = astroray.crypto_hash_name(name)
            cpu_mask = reconstruct_mask(cpu_buf, target)
            gpu_mask = reconstruct_mask(gpu_buf, target)
            assert gpu_mask.any(), (
                f"GPU matte for {label} '{name}' is empty while the CPU matte "
                f"covers {int(cpu_mask.sum())} pixels"
            )
            iou = compute_iou(cpu_mask, gpu_mask)
            print(f"CPU<->GPU IoU({label} {name}): {iou:.4f}")
            assert iou >= iou_threshold, (
                f"CPU<->GPU {label} {name} IoU {iou:.4f} < {iou_threshold}"
            )


def test_gpu_crypto_disabled_is_noop():
    """Gate 3 — cryptomatte off costs nothing and writes nothing.

    Spec wording is "BYTE-IDENTICAL to pre-pkg159 output", which cannot be
    evaluated without a pre-pkg159 binary. The equivalent (and strictly
    checkable) statement is that the crypto code path has no effect on the
    image: it consumes no RNG dimensions and touches no radiance, so a
    crypto-ON render must match a crypto-OFF render at the same seed.

    Tolerance, not equality: the wavefront is not bit-identical even to itself
    because the per-pixel radiance accumulation uses atomicAdd, whose summation
    order varies run to run (~1e-7 relative). A real defect — e.g. the crypto
    block corrupting throughput or consuming an RNG draw — moves pixels by
    O(0.1), far above this floor.
    """
    _skip_without_gpu()

    width = height = 128
    spp = 16

    img_off, obj_off, mat_off = _render_crypto(True, width, height, spp,
                                               crypto=False)
    img_on, obj_on, _ = _render_crypto(True, width, height, spp, crypto=True)

    assert not np.any(obj_off), (
        "crypto_object buffer is non-zero with cryptomatte disabled"
    )
    assert not np.any(mat_off), (
        "crypto_material buffer is non-zero with cryptomatte disabled"
    )
    # Sanity: the ON leg must actually have written something, otherwise this
    # test would pass trivially for the unported code too.
    assert np.any(obj_on), "crypto_object buffer is zero with cryptomatte ON"

    diff = np.abs(img_on.astype(np.float64) - img_off.astype(np.float64))
    print(f"crypto on/off image diff: max={diff.max():.3e} mean={diff.mean():.3e}")
    assert diff.max() < 1e-3, (
        f"cryptomatte accumulation changed the image (max abs diff "
        f"{diff.max():.3e}); it must be a pure side-channel"
    )
    assert diff.mean() < 1e-5, (
        f"cryptomatte accumulation shifted the image (mean abs diff "
        f"{diff.mean():.3e})"
    )


def test_gpu_crypto_deterministic_under_concurrency():
    """Gate 4 — same seed/spp reproduces the same per-pixel rank histogram.

    This is the gate that owns the ATOMIC insert. The wavefront keeps many
    concurrent path slots mapping to the same pixel (path regeneration claims
    work items as slots die), so a plain crypto_insert would race:
      * two threads both see an empty slot and both CAS-free write it — one
        id is lost, so the pixel's id SET drifts run to run;
      * a non-atomic `ranks[i] += w` loses updates, so weights drift by far
        more than float-reassociation noise.
    Both failure modes show up as a run-to-run difference here.

    The comparison is on the id->weight MAPPING, not the slot ORDER: two ids
    with near-equal weight can legitimately swap rank after the
    weight-descending sort. Weights are compared with tolerance because
    atomicAdd summation order still varies.
    """
    _skip_without_gpu()

    width = height = 128
    spp = 32

    _, obj_a, mat_a = _render_crypto(True, width, height, spp, seed=SEED)
    _, obj_b, mat_b = _render_crypto(True, width, height, spp, seed=SEED)

    assert np.any(obj_a), "crypto_object buffer is empty; nothing to compare"

    for buf_a, buf_b, label in ((obj_a, obj_b, "object"),
                                (mat_a, mat_b, "material")):
        map_a = _id_weight_map(buf_a)
        map_b = _id_weight_map(buf_b)

        assert map_a.keys() == map_b.keys(), (
            f"crypto_{label}: the set of covered pixels changed between two "
            f"identical runs ({len(map_a)} vs {len(map_b)} pixels)"
        )

        id_mismatches = 0
        max_weight_delta = 0.0
        for px, entry_a in map_a.items():
            entry_b = map_b[px]
            if set(entry_a) != set(entry_b):
                id_mismatches += 1
                continue
            for idv, wa in entry_a.items():
                max_weight_delta = max(max_weight_delta, abs(wa - entry_b[idv]))

        assert id_mismatches == 0, (
            f"crypto_{label}: {id_mismatches} pixels resolved to a DIFFERENT "
            f"set of IDs across two identical runs — the rank insert is racy"
        )
        print(f"crypto_{label}: {len(map_a)} pixels, "
              f"max weight delta {max_weight_delta:.3e}")
        assert max_weight_delta < 1e-4, (
            f"crypto_{label}: per-pixel weights differ by {max_weight_delta:.3e} "
            f"across two identical runs — larger than atomic-reassociation noise"
        )
