# pkg155 — NEGATIVE RESULT: compiling natively for sm_120 makes the GPU *slower*

**Measured 2026-07-26, RTX 5070 Ti (compute capability 12.0), CUDA 12.8,
`benchmarks/wavefront_baseline.py --spp 64 --max-depth 8`, 256², 1 warmup + 5
measured. Controlled: identical source at `60306a9`, the ONLY difference being
`CMAKE_CUDA_ARCHITECTURES`.**

**This refutes a hypothesis I formed and was about to recommend acting on. Do not
add sm_120 to the architecture list.**

## The hypothesis (wrong)

`CMakeLists.txt:54-55` targets `75;86;89` with the comment *"sm_120 (Blackwell)
requires CUDA 12.8+; CUDA 12.6 targets up to sm_89"*. CUDA 12.8 **is** installed,
so that comment is stale in its premise. `cuobjdump --list-elf -all` confirmed the
shipped module carries SASS for sm_75/86/89 and PTX for the matching virtual
archs, and nothing for sm_120 — so on this GPU **every kernel runs via driver JIT
from compute_89 PTX**.

That is all true. The inference drawn from it — that JIT was causing the register
blow-up (221) and therefore the occupancy collapse behind pkg155's ~5× — is
**false**.

## The measurement

| scene | sm_89 only (JIT to sm_120) | +sm_120 (native AOT) | ratio |
|---|---|---|---|
| cornell_diffuse | 97.84 ms/render | **175.62** | **1.80× SLOWER** |
| cornell_glass | 123.03 ms/render | **206.10** | **1.68× SLOWER** |

Per stage (cornell_diffuse):

| stage | sm_89 regs | sm_120 regs | sm_89 ms | sm_120 ms |
|---|---|---|---|---|
| `shade_bucketed` | 221 | **229** | 239.33 | **603.89** |
| `intersect_queued` | 134 | 136 | 153.18 | 234.98 |
| `regen` | 102 | 100 | 107.35 | 111.99 |
| `shadow` | 106 | 108 | 87.15 | 102.85 |

Every stage got slower. The shade stage got **2.52×** slower.

## What this establishes

1. **The driver's JIT from compute_89 PTX produces materially better Blackwell
   code than CUDA 12.8's offline `ptxas` targeting sm_120.** Counter-intuitive,
   but measured twice on a controlled pair.
2. **The 221-register occupancy problem is intrinsic to the kernel, not a build
   artifact.** Native AOT gives **229** — essentially the same, and still 1 block/SM.
   pkg155 Phase 1's conclusion stands unchanged: recovery has to come from
   reducing the kernel's actual register demand (splitting the bucketed shade
   kernel per material class, `__launch_bounds__`, auditing long-lived per-thread
   state), not from build configuration.
3. **The existing `75;86;89` choice is not merely acceptable — it is currently
   optimal on this hardware.** The comment's "also runs on Blackwell via forward
   compat" is the right call. Leave it alone.

## Two methodological corrections — both mine, both worth keeping

**1. `-Xptxas -v` register counts are worthless under `-rdc=true`.** Compiling
`stage_advance.cu` standalone reported `stageShadeBucketedKernel` at **127
registers for sm_89** and **40 for sm_120**. The real, post-device-link values are
**221** and **229**. With relocatable device code the pre-link numbers are
provisional and can be off by 5×. I flagged this caveat when I took the numbers
and then let them drive a hypothesis anyway — the flag was worth nothing until it
changed my behaviour.

**This kills the "compile-only bisect" plan** for pkg155 Phase 2 / the combined
pkg153 protocol. The register signal cannot be read cheaply at compile time under
rdc; it has to come from the runtime profile, which needs the GPU and the lock.
The protocol doc should be corrected: the bisect is **not** GPU-free, and cannot
be run in parallel with hardware verification.

**2. Do not conclude from a tool invocation the tool told you was incomplete.**
My first `cuobjdump --list-ptx` reported *no PTX at all*, which would have meant
sm_89 SASS somehow executing on Blackwell. cuobjdump's own output said *"You may
try with -all option."* With `-all`, the PTX is there. I nearly reported a much
stranger finding than the real one.

## Provenance

Measured by the team-lead in a throwaway detached worktree
(`Astroray-sm120exp`, never pushed) specifically so the CMakeLists edit needed to
test this would not touch the repo — build-file changes are owner-gated. That
worktree can be deleted; nothing in it should be merged.

Raw profiles: `test_results/overnight_report_2026-07-25/pkg155_sm120.json` and
`pkg155_sm89_current.json`.
