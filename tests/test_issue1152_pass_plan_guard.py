"""#1152 - wavefront pass plan vs the 32-bit work counter (host arithmetic).

The CUDA render path cannot run on CI, but its planning math is header-only
(include/astroray/wavefront_pass_plan.h) and exposed through astroray_test_helpers.
"""
import itertools

import pytest

helpers = pytest.importorskip("astroray_test_helpers")
for _name in ("wavefront_pass_depth", "wavefront_plan_pool",
              "wavefront_counter_slack_per_path", "wavefront_max_samples_per_round"):
    assert hasattr(helpers, _name), f"astroray_test_helpers lacks {_name}; rebuild it"

MAX = 0x7FFFFFFF
INT_MAX = 2**31 - 1
MIN_PATHS = 107520 * 16          # RTX 5070 Ti: 70 SMs * 1536 threads * 16
P1080, P4K = 1920 * 1080, 3840 * 2160


def old_pool(pix, spp, max_depth, min_paths=MIN_PATHS):
    """Pre-#1152 wavefrontPoolSize counter step (caller passed max_depth + 2, helper +2)."""
    work = pix * spp
    pool = max(pix, min(min_paths, work))
    if work + pool * (16 + (max_depth + 2) + 2) > MAX:
        pool = pix
    return pool


def plan(pix, spp, pass_depth):
    pool = helpers.wavefront_plan_pool(pix, spp, pass_depth, MIN_PATHS)
    per_round = min(spp, helpers.wavefront_max_samples_per_round(pix, pool, pass_depth))
    return pool, per_round


def fits(pix, pool, per_round, pass_depth):
    return pix * per_round + pool * helpers.wavefront_counter_slack_per_path(pass_depth) <= MAX


@pytest.mark.parametrize("pix,spp", [(P1080, 128), (P4K, 64)])
def test_high_transparent_limit_plans_without_throwing(pix, spp):
    pd = helpers.wavefront_pass_depth(8, True, 1024)
    assert pd == 8 + 2 + 1024 + 1
    pool, per_round = plan(pix, spp, pd)
    old = old_pool(pix, spp, 8)   # what main planned with the true passDepth ignored
    assert pool < pix, "pool must shrink below numPixels when numPixels alone cannot fit"
    assert pool < old
    assert per_round == spp, "one round is enough here"
    assert fits(pix, pool, per_round, pd)
    # main's guard would have thrown at the numPixels pool
    assert pix * spp + pix * (16 + pd + 2) > MAX


def test_transparent_limit_clamps_and_does_not_overflow():
    at_max = helpers.wavefront_pass_depth(8, True, 1024)
    assert helpers.wavefront_pass_depth(8, True, INT_MAX) == at_max
    assert helpers.wavefront_pass_depth(8, True, 5000) == at_max
    assert helpers.wavefront_pass_depth(8, True, -1) == 8 + 2 + 31 + 1   # unlimited -> 31
    assert helpers.wavefront_pass_depth(INT_MAX, True, INT_MAX) == INT_MAX
    pool, per_round = plan(P4K, 64, at_max)
    assert fits(P4K, pool, per_round, at_max)


def test_default_no_alpha_plan_is_unchanged():
    for max_depth in (4, 8, 12, 32):
        pd = helpers.wavefront_pass_depth(max_depth, False, 1024)
        assert pd == max_depth + 2
        # counter margin applied once: identical to old 16 + (max_depth+2) + 2
        assert helpers.wavefront_counter_slack_per_path(pd) == 16 + max_depth + 2 + 2
        for pix, spp in itertools.product((256 * 256, 640 * 480, P1080, P4K), (1, 16, 128, 1024)):
            if pix * spp + pix * (16 + pd + 2) > MAX:
                continue   # main threw here; covered by the chunking test
            want = old_pool(pix, spp, max_depth)
            assert helpers.wavefront_plan_pool(pix, spp, pd, MIN_PATHS) == want
            assert helpers.wavefront_max_samples_per_round(pix, want, pd) >= spp


def test_huge_spp_without_alpha_chunks_instead_of_throwing():
    pd = helpers.wavefront_pass_depth(8, False, -1)
    pool, per_round = plan(P1080, 10000, pd)    # work 2e10 > counter; main threw
    assert pool == P1080
    assert 1 <= per_round < 10000
    assert fits(P1080, pool, per_round, pd)


def test_sweep_always_fits():
    for pix in (1, 4096, 256 * 256, P1080, P4K, 7680 * 4320):
        for spp in (1, 8, 64, 4096):
            for tlim in (-1, 0, 8, 256, 1024, INT_MAX):
                for transparent in (False, True):
                    pd = helpers.wavefront_pass_depth(8, transparent, tlim)
                    pool, per_round = plan(pix, spp, pd)
                    assert 1 <= pool <= max(pix, MIN_PATHS), (pix, spp, tlim)
                    assert per_round >= 1
                    assert fits(pix, pool, per_round, pd), (pix, spp, tlim, transparent)
