# Overnight standup — 2026-07-25 (23:00 → 2026-07-26 morning)

Follows `.astroray_plan/docs/standup/2026-07-25-dayrun.md`. First run after
pkg55 closed: both megakernels are gone (PR #524) and the wavefront is the only
GPU path. Owner-ordered queue was pkg157 → pkg155 → pkg153, with pkg150/156/158
and the newly-unblocked pkg120 / pkg88-B+D as slots freed. Implementer cap 2,
parallel lanes constrained to non-overlapping file domains.

**Running lanes:** Lane A = pkg157 (wavefront `stage_advance.cu` domain),
Lane B = pkg88-B (addon `blender_addon/` domain). Team-lead held the GPU lane
itself, since subagents on this machine cannot initialise vcvars and therefore
cannot build CUDA.

## Shipped

| PR | What | Gate |
|---|---|---|
| **#526** | `feat(pkg157)`: firefly clamps ported into the wavefront — merged as `b6c3ffb` | CI all-pass + HW PASS bound to head `0651007` |

**Open at hand-off:** **#525** (pkg88-B addon motion bake) — two independent
different-model sign-offs plus my own real-Blender PASS, CI still running at
hand-off; merge it if green. **#527** (pkg160) — deliberately incomplete and
**blocked on an owner decision**, see below; do not merge as-is.

## Headline: two investigations closed, one new defect found, two pre-existing bugs surfaced

pkg155 and the metal finding are both measurement results, not fixes — by design;
the standing rule is that honest FAILs and measured attributions beat forced
merges. What was not planned is that **three separate bugs surfaced from tests
that were passing**, and every one of them was caught by a gate that introduced
some kind of *independence*:

- **a different model** — the Sonnet 5 reviewer found pkg88-B's wrong-pose bug
  that all 13 of the PR's own tests passed through;
- **a real host** — headless Blender found that enabling motion blur has been
  failing outright since pkg88-A shipped, invisible to every suite that mocks
  `bpy`;
- **two compiled binaries** — the cross-binary no-op gate is the only way to test
  pkg157's contract, and CI's actual compiler exposed a phantom overload that had
  been sitting in the wavefront header unnoticed.

A fourth was self-inflicted and caught the same way: pkg157 had a test passing
*vacuously* because its clamp threshold could never bind. The lesson worth
carrying: on this project a green suite is weak evidence unless something in the
loop is independent of whoever wrote the code.

## Major finding (NEW, unowned before tonight): plain `metal` is ~3.5× too dark on the GPU

Measured @ `727a211`, RTX 5070 Ti, under the serialized GPU lock. Per-material
patches on `disney_contact_sheet` (512², 512 spp, seed 424242, **linear** output):

| material | R | G | B |
|---|---|---|---|
| **metal** | **0.2787** | **0.2857** | **0.3159** |
| dielectric | 0.9987 | 0.9998 | 0.9999 |
| diffuse_light | 0.9987 | 1.0007 | 1.0005 |
| closure_matte | 0.9657 | 1.0059 | 0.9970 |

- **Structural, not sampler noise.** Flat across 32 → 2048 spp (64× range) with
  no √SPP decrease, per memory `mc-noise-vs-deterministic`.
- **Not a firefly artifact.** Clipping the CPU patch at p99 moves the ratio by
  0.0002 (0.2787 → 0.2785). The *median* ratio is 0.141 — the typical metal
  pixel is ~7× darker on GPU, and `gpu_max` (0.34) never approaches `cpu_max`
  (0.82–1.14).
- **Visually confirmed**, not inferred from numbers: the gold metal sphere is
  bright warm gold on CPU and dark muted olive on GPU. Side-by-side PNGs in the
  report.
- **Why it was invisible:** existing GPU/CPU parity bands are `[0.4, 2.5]`
  (pkg123, gpu_caustic), `[0.5, 2.0]` (pkg64), `[0.5, 1.5]` (pkg115),
  `[0.7, 1.1]`. A 0.279 would fail the loosest of those — but that band is on
  *Disney* metal. **Plain `metal` has no GPU/CPU parity gate at all.** A 3.5×
  defect has been shipping invisibly on what is now our only GPU path.
- Earlier in the night I reported this as a broad 8–25% divergence across many
  scenes. That framing was wrong and is superseded: the per-material breakdown
  shows it is this one defect, showing up in each scene in proportion to how
  much metal that scene contains.

### Mechanism convicted in code — filed as pkg160 (`eaf395d`, `8d8f704`)

This did not stay a measurement. The architect diffed the twins and found a
**categorical omission**, and I verified it line by line:

- CPU `MetalPlugin::eval` / `evalSpectral` (`plugins/materials/metal.cpp:54-58`,
  `:85-89`) returns `singleScatter + multiScatter`, where
  `multiScatter = albedo * ggxMultiScatterCompensation(NdotV, NdotL, roughness)
  * roughness*(2-roughness) * 1.3`.
- GPU `gpu_metal_eval` (`include/astroray/gpu_materials.h:230`) returns
  **`singleScatter` only**. The multiscatter term was never mirrored.
- Its own comment claims *"matches CPU"* — true only for the ≤0.1 near-delta
  mirror shortcut, and **false for the rough path**. The contact-sheet metal is
  roughness 0.15, just above that threshold, which is exactly why this surfaced.

The mechanism predicts all three of my robustness observations, which is the
real reason to believe it: the omitted term is nearly view-independent, so for
rough metal it dominates while single-scatter is a thin lobe. That gives a
median worse than the mean (typical pixels are almost entirely the missing term;
highlight pixels have single-scatter on both paths), a `gpu_max` that never
reaches `cpu_max` (no multiscatter floor), and total insensitivity to p99
clipping (the deficit is in the bulk, not the tail).

**Filed as pkg160, deliberately NOT folded into pkg158.** pkg152/158 are *Disney*
metal (`gpu_disney_eval`) and are a reconciliation of two disagreeing numbers;
pkg160 is *plain* `metal` (`gpu_metal_eval`, a separate function) and is an
omission, not a reconciliation. Folding would have made pkg158 "reconcile" three
numbers from two code paths. pkg158 instead got a scope fence so both metal dumps
run in one GPU-lock session on the shared harness.

**Implementation hazard I recorded on the spec (`8d8f704`):** the fix is not a
copy-paste. The CPU term uses `raytracer.h`'s *runtime-computed*
`GGXEnergyCompensationLUT` (indexed `E[roughness*RES+mu]`, read as
`lookupE(mu, roughness)`), while the GPU only has the *file-loaded*
`DisneyEnergyCompensationTables` (read as `sample2D(roughness, mu)` — the
opposite index convention, and different data provenance). I verified
`gpu_ggx_sample2D` matches `sample2D` exactly, so there is **no** transposition
bug — the two conventions belong to two self-consistent but distinct table
systems. The hazard is swapping one lookup for the other and assuming parity;
the spec now requires dumping both tables over a shared grid and comparing
first, and escalating rather than silently picking one if they disagree. It also
records that this term's null-table fallback must be **0.0**, not the 1.0 used by
the existing *multiplicative* helpers — the term is additive, so an identity
fallback would inject a full-strength albedo term whenever tables fail to load.

## pkg160 Step 0 — the fix is BLOCKED, and the reason is worse than the bug

The pkg160 spec required dumping both GGX energy-compensation table systems and
comparing them *before* mirroring anything, because the CPU metal term uses
`raytracer.h`'s runtime-computed LUT while the GPU only has the shipped
Cycles-derived tables. The implementer did that and **stopped**, correctly, rather
than choosing between two fixes. Branch `pkg160-gpu-metal-multiscatter`, commit
`c375540` — no PR yet, deliberately.

**They disagree catastrophically.** Both sides compiled from the real repo code
(no transcription), and the shipped side independently re-derived in NumPy straight
from `ggx_E.bin` (agrees to 5e-7, so this is not a lookup-convention mistake):

| roughness | runtime LUT `E` | shipped `ggx_E.bin` | ratio |
|---|---|---|---|
| 0.05 | 0.001399 | 0.999975 | **715×** |
| **0.15** (the contact-sheet metal) | **0.040669** | **0.998543** | **24.6×** |
| 0.30 | 0.353788 | 0.974699 | 2.76× |
| 0.90 | 0.457155 | 0.535442 | 1.17× |

Downstream, in the `Fms` the metal term actually multiplies, that becomes **1030×**
at roughness 0.15 (0.307206 vs 2.98e-4).

**The CPU LUT is the wrong one.** `GGXEnergyCompensationLUT`'s constructor
(`raytracer.h:306-331`) estimates `E` with 256 **uniform-hemisphere** samples per
cell. That cannot resolve a narrow GGX lobe, so `E → 0` as roughness → 0 — the
exact opposite of the truth, since a smooth conductor's directional albedo → 1
(which is what the converged Cycles table correctly reports: 0.999975 at
roughness 0.05). And because `Fms = (1-Ewo)(1-Ewi) / (π·max(1-Eavg, 1e-4))`,
driving `E → 0` pushes `Fms → 1/π = 0.3183`, its **ceiling**, precisely where
multiple scattering should vanish. Measured `Fms` at roughness 0.15 is 0.3072 —
**96.5% of the maximum.**

**So the CPU has been adding a large spurious ambient floor to every rough metal:**
`albedo × 0.3072 × 0.2775 × 1.3 = 0.111 × albedo` at roughness 0.15,
nearly view-independent and **cosine-free** (it carries no `NdotL`, unlike
everything else `eval()` returns). That floor is the bulk of the CPU's metal
radiance at this roughness — which is exactly why the measured median GPU/CPU
ratio was 0.141.

**This reframes the whole package.** The conviction stands — `gpu_metal_eval`
really does omit a term `MetalPlugin` really does add, and they really are
3.5×/7× apart. What changes is *which side is wrong*. Mirroring the CPU term
using the GPU's (correct) tables closes only ~1% of the gap at roughness 0.15
(0.0291 → 0.0328 single-bounce eval ratio) and cannot reach the proposed
`[0.95, 1.05]` band; it only converges near roughness 0.9. **Making the GPU match
today's CPU would mean propagating a physically wrong ambient floor onto the GPU.**

**The two options, measured rather than argued:**

- **Option B — mirror using the GPU's existing (correct) tables.** Measured dead:
  cosine-weighted-hemisphere integration of the full eval at the contact-sheet
  config gives a GPU/CPU ratio of **0.0291 today → 0.0328 mirrored**. It closes
  ~1% of the gap and only converges near roughness 0.9.
- **Option A — upload the runtime LUT to the GPU.** Exact by construction, because
  it makes the GPU use the same table the CPU does. But it needs
  `gpu_ggx_tables.cuh`/`.cu` plus a `raytracer.h` include in a `.cu`, and **it
  canonicalises the artifact** — it would propagate the spurious ambient floor onto
  the GPU in the name of parity. Defensible as "parity now, physics later via
  pkg129", but not a call to make silently. (Folding it into the existing
  `uploadGgxTables()` body keeps it clear of the other wavefront lane.)

**Two spec corrections the implementer pushed back on, both of which I accept:**

1. **`gpu_materials.h:1155` is NOT falsified**, contrary to what the pkg160 spec
   claimed. Its "correct for MetalPlugin" assertion is explicitly scoped to the
   `roughness <= 0.1` shortcut, and for that branch it is true. Only `:230` was
   wrong, and only that one was corrected. (That claim originated in my own
   hand-off note; the implementer was right to check rather than inherit it.)
2. **Why nothing caught this:**
   `tests/wavefront_diff/test_cpu_wavefront_metal_bit_identity.py` compares **CPU
   wavefront against CPU reference** — both call `MetalPlugin`, so they are
   bit-identical *by construction* and structurally blind to `gpu_metal_eval`.
   Any real gate here has to be GPU-vs-CPU.

Also established: `gpu_metal_sample` inherits the fix free (it calls
`gpu_metal_eval`), and `gpu_metal_pdf` must **not** gain the term — neither side
folds multiscatter into the pdf, so adding it to the GPU pdf would break the very
parity this package exists to create.

**Landed in PR #527** (open, deliberately incomplete): Step-0 instrumentation, the
pin test `tests/test_pkg160_ggx_table_systems.py`, and the corrected `:230`
comment. **Deliberately NOT landed:** the mirror and the plain-metal parity gate —
landing the gate alone would make the suite knowingly red on a defect nobody is
cleared to fix. **Unverified:** no GPU touched, no PASS asserted, and the new
`test_helpers_module.cpp` dumper was only `-fsyntax-only`'d, never MSVC-linked. I
started that build at finalize time; result in the report if it completed.

**This needs an owner decision — see Action items.**

## pkg155 — Phase 1 complete: ~5× confirmed, shade stage convicted

Commits `b5d9e57` + `7af0e25`. Full write-up:
`.astroray_plan/docs/pkg155-phase1-profile-findings.md`.

**Metric correction first.** The spec's headline (megakernel mean ms per
*launch*, 19.92 → 113.03) cannot be reproduced or continued: #524 deleted the
kernel, and per-launch means are not comparable between a megakernel (1
launch/render) and the wavefront (~344 launches/render). Switched to total GPU
kernel time per render. **The regression survives the corrected metric:**

| scene | Phase-A MK 2026-05-17 | final MK 2026-07-25 | wavefront tonight | factor vs May |
|---|---|---|---|---|
| cornell_diffuse | 20.29 ms | 113.03 ms | 98.25 ms | **4.84×** |
| cornell_glass | 21.87 ms | 134.60 ms | 122.69 ms | **5.61×** |

The wavefront sits just below the final megakernel, which confirms the
measurement and rules out the wavefront switch as the cause — the megakernel had
already regressed to 113 ms before it was deleted.

**Attribution — the shade stage, exactly where the owner said to probe first:**

| stage | share (diffuse / glass) | regs/thread | blocks/SM |
|---|---|---|---|
| `shade_bucketed` | **43.8% / 52.4%** | **221** | **1** |
| `intersect_queued` | 19.8% / 17.4% | 128 | 2 |
| `regen` | 19.0% / 16.0% | 102 | 2 |
| `shadow` | 17.4% / 14.2% | 106 | 2 |

Shade is the only stage that fails to reach 2 blocks/SM. At 256 threads/block
against a 65,536-register SM file, 221 regs needs 56,576 regs/block → 1 block.
**Recovery target is ≤128 regs/thread; shade is 93 registers over the line.**

## pkg153 + pkg155 Phase 2 — combined bisect protocol filed

Commit `727a211`, doc
`.astroray_plan/docs/pkg153-pkg155-combined-bisect-protocol-2026-07-25.md`.
The architect's own observation was that the two packages were bisecting the same
`#481 → #524` window on a single GPU — pure duplication of the scarcest
resource. One build per bisect point now yields four signals: shade-path
regs/thread (primary, compile-time), total GPU ms/render, R-channel env ratio +
emitters→matte discriminator, and the tables-loaded checksum. #523 remains a
compounding anchor, never an origin candidate.

Two useful properties fell out: the register bisect is **compile-only**, so most
of it can run off the GPU lock and leave the GPU free for verification; and the
shade-stage dispersion tail (26× spread between mean and max launch) is an
occupancy-*independent* lever that must be measured separately, so a register
win isn't misread as also fixing the tail.

## Infrastructure fixed tonight (commit `473c25b`)

- **Agent model tiers moved off Opus 4.8** (owner request): architect →
  `claude-fable-5`; package-implementer, pr-reviewer, gate-failure-reviewer,
  cpp-abi-guard, cycles-parity-reviewer → `claude-opus-5`; hardware-verifier and
  docs-updater stay `claude-sonnet-5`. package-implementer was deliberately
  promoted to Opus 5 to attack the recurring ships-without-building /
  invented-API failure mode recorded in memory.
  - **Consequence documented:** because package-implementer is now Opus 5, the
    orchestrator's "different-model SIGN-OFF" rail is only satisfiable with an
    *explicit* model override on the reviewing Agent call. Passing none inherits
    Opus 5 and silently defeats the rail. Written into
    `roadmap-orchestrator/SKILL.md` as a new Model tiers section.
- **`configure_and_build.bat` now builds `astroray_test_helpers`** (owner
  pre-approved). Without it, `test_pkg92_wavefront_rng.py` and
  `test_pkg92_practrand_gate.py` fail with a spurious `ModuleNotFoundError` that
  reads as a code regression. Found by the PR #524 verifier.
- **`scripts/build/build_cuda_worktree.bat` — two fixes.** It now passes
  `--config Release` (a no-op under its own NMake generator, but essential when
  `build_cuda/` was previously configured by `configure_and_build.bat`'s Visual
  Studio multi-config generator, where an un-`--config`'d build silently
  resolves to Debug and dies on `/RTC1` + `/O2`, D8016). Same test-helpers target
  added. Both footguns hit the pkg152 verifier on 2026-07-25.
- **`team-overnight/SKILL.md` topology rewritten.** `TeamCreate` no longer
  exists in this harness and `Agent`'s `team_name` is documented as
  "Deprecated; ignored — single implicit team". Persistent teammates are now
  spawned via `Agent(name=…)` and addressed via `SendMessage`. Memory
  `agent-team-spawn-requirement` updated; the old rule was actively misleading.
- **Salvaged the PR #523 RTX hardware-verification appendix** into the pkg152
  spec — it was sitting uncommitted in the pkg152 worktree and would have been
  destroyed by worktree GC.

## Specs updated / filed (architect, commits `e107057` + `727a211`)

- **pkg120** two-sided MIS — stale "blocked on pkg55 Phase C" marker cleared;
  the blocker dissolved with #524. Now dispatchable.
- **pkg88** Phases B and D marked dispatchable; Phase D reworded for a
  wavefront-only world (the megakernel oracle it referenced no longer exists).
- **pkg150** — precondition-now-met note (#519, #521, #522 all on main).
- **pkg159 NEW** — wavefront cryptomatte port. GPU cryptomatte lived only in the
  deleted `path_trace` megakernel, so it is currently CPU-only and was owned by
  nobody: a real capability regression from #524 that nobody had filed. Spec
  pins three things so it isn't mis-implemented as a copy-paste: atomics are
  now required (the megakernel was 1 thread/pixel and race-free; the wavefront
  is not), an ID-encoding fix (the megakernel used an implicit `float=uint32`
  conversion rather than `hash_to_float`, so its IDs never matched the CPU/EXR
  manifest), and first-hit-only semantics per the CPU oracle. Cites Friedman &
  Jones 2015 (Psyop) and Cycles `cryptomatte_passes.h`.

## PR #526 (pkg157) — HW PASS; the code was right, three of its own tests were not

Built the branch at `0cd285f` (fresh `.pyd` 01:10, `astroray.__file__` confirmed in the
worktree's `build_cuda/Release`, no shadow) and ran the gate on the RTX 5070 Ti.
**7 passed, 2 failed — and both failures are test defects, not code defects.**

**The clamps demonstrably work.** Sweep on `diffuse_light_cornell`, 120², 64 spp,
seed 424242, linear:

| config | max | p99.5 | mean | max |Δ| vs base |
|---|---|---|---|---|
| clamps off | 1.7580 | 0.5914 | 0.20141 | 0.00000 |
| **clampIndirect=10** | 1.7580 | 0.5914 | 0.20141 | **0.00000** |
| clampIndirect=1 | 1.7580 | 0.5909 | 0.20061 | 0.14764 |
| clampIndirect=0.1 | 1.7387 | 0.5751 | 0.18768 | 0.20867 |
| clampDirect=1 | 1.5044 | 0.5882 | 0.20120 | 0.30666 |
| clampDirect=0.1 | 0.5879 | 0.3602 | 0.15186 | 1.43117 |

Failure 1 (`clamp_direct_and_indirect_controls`) used `clampIndirect=10` — but **the
scene's maximum radiance is 1.758, so a clamp at 10 cannot bind.** It is a
mathematical no-op regardless of whether the port works. The test inherited #515's
headline number, which was measured on a bright-sun scene with a far larger dynamic
range. At 1 and 0.1 both clamps bite cleanly and monotonically.

**Failure 2 (`clamp_zero_is_noop`) asserts something unachievable.** It demands
byte-identity between explicit `set_clamp_*(0)` and the unset default. I tested the
premise: same seed, same config, no clamp calls, three consecutive wavefront renders
→ **not bit-identical to itself**, 29/27648 elements differing at 1.19e-07. Atomic
accumulation ordering varies between launches, so byte-identity can never hold on
this path, with or without pkg157.

**This means the pkg157 spec's own contract item 2 is unachievable as written** — it
says clamps-off must render "BYTE-IDENTICAL". That wording needs amending to the
project's 1e-5 wavefront MC convention. Flagged for the owner rather than quietly
weakened.

**Gate 3 verified properly, cross-binary** — the test the implementer could not run,
because it needs two compiled binaries. Rendered the same scene with the **pre**-pkg157
binary (main checkout, built 21:28 @ `9fa91c8`) and the **post** binary, in separate
processes:

- image sums **identical to 6 dp** (22315.917969 both)
- max abs diff 4.77e-07, **2.48e-07 relative to peak — ~40× tighter than the 1e-5
  convention**, and consistent with the measured noise floor

**Final gate at `0651007`: 8 passed, 1 skipped — HW PASS.**

The one skip took three rounds and is worth recording, because the answer turned out to
be a property of the *scene library*, not of the code. The test asserts pkg144 contract
item 3 — "clampIndirect suppresses fireflies without energy loss". Round 1 used #515's
literal `clampIndirect=10` (cannot bind, peak is 1.758). Round 2 used 0.5× peak (clips
real signal: 4.166% mean shift). Round 3 used p99.9 (clips nothing: `max|Δ|` 4.77e-07 on
a p99.9 of 13.68 against a peak of 13.75). Rather than let a fourth round happen I
measured the tail-heaviness of the whole scene library:

| scene | peak/p99.9 @ 16 spp | @ 64 spp |
|---|---|---|
| diffuse_light_cornell | 1.82× | 1.53× |
| thin_glass_cornell | 1.66× | 1.52× |
| disney_cornell | 1.66× | 1.52× |
| dielectric_cornell | 1.40× | 1.13× |
| metal_cornell | 1.07× | 1.04× |

**Not one scene in the suite has a firefly tail** — a real firefly population would show
a ratio in the tens or hundreds. There is nothing to suppress, so no threshold can
satisfy both halves of the claim: high enough to clip only outliers ⇒ clips nothing; low
enough to bite ⇒ removes real signal. The test is now `pytest.mark.skip` with that table
as its reason — **skip, not xfail**, because the code is not expected to fail and an
xfail would imply otherwise. **pkg161 filed** to build a firefly-bearing gate scene,
validated by measurement (`peak/p99.9 ≳ 10×`) rather than by eye, with un-skipping this
gate in its definition of done. That gap is wider than pkg157: pkg144 item 3 is
undemonstrable for the same reason, and future clamping / denoising / adaptive-sampling /
RR work has no scene to show an effect on.

**Verdict: HW PASS.** No-op guarantee and bounce classification both verified on
hardware; the residual is a missing test scene, not a defect.
Numbers: `test_results/overnight_report_2026-07-25/pkg157_hw_numbers.json`.

## PR #525 (pkg88-B) — BLOCKED by independent review, and rightly so

The different-model pre-merge review rail earned its keep tonight. A Sonnet 5
reviewer (deliberately a different model from the Opus 5 implementer) found a
real correctness bug that **all 13 of the PR's own tests passed straight
through**. I verified it independently from the diff before acting.

**The bug:** `convert_scene` computes `t_start` and `t_end` correctly
(`blender_addon/__init__.py:1663-1671`), but only `t_end` is ever snapshotted
(`:1712`). `convert_objects` then feeds the object's *current* pose
(`obj_instance.matrix_world`, `:3778`) as `positions_start`. The renderer treats
those two arrays as endpoints of a linear blend over the ray's `time ∈ [0,1]`
(`shapes.h:154-174` against `raytracer.h:1922-1949`), so `positions_start` must
be the pose at `t_start`.

| shutter position | effect |
|---|---|
| **CENTER** (the default) | object sweeps only the back half of the shutter arc — measured 34 lit columns `[29,62]` vs 55 `[7,61]` for the correct arc, 61.8% width and asymmetric |
| **END** | `t_end == frame`, so the snapshot is bit-identical to the current pose, `_matrices_differ` is always False, and **object motion blur is silently disabled entirely** |
| START | correct, but only coincidentally (`t_start == frame`) |

**Why the tests missed it** — worth internalising, because this is a test-design
failure more than a coding one: one test stubs out `convert_objects` entirely so
it never sees `positions_start`; the other hand-constructs
`matrix_start = identity()` / `matrix_end = translate(1.2)` and so bypasses the
real `t_start` arithmetic it was supposed to be checking. Both tests would pass
against a completely broken implementation. The fix request requires a test that
drives the real `convert_scene → convert_objects` path and is parameterised over
all three shutter positions, since a CENTER-only test would still let the END
no-op ship.

**Fixed at `9f233fe`, and the fix came with unusually good evidence.** The implementer
snapshots `t_start` as well and feeds it as `positions_start`, mirroring the camera
path's two `_get_camera_transform_at_time` calls; `_matrices_differ` now compares the
two boundary poses. Measured streak width, lit columns:

| shutter position | correct | pre-fix | |
|---|---|---|---|
| START | 49 | 49 | correct only coincidentally |
| CENTER | 49 | **30** | half arc |
| END | 49 | **13** | 13 **is** the static silhouette — total silent no-op, confirmed |

Two things it did that are worth repeating as practice: it **reintroduced the bug into
a copy of the source and re-ran the new tests** to prove they actually catch it (4
failed, reporting the exact 30- and 13-column values) — and that exercise immediately
exposed that its own `width > 30` threshold cleared the buggy CENTER value by *one
column*, so it retuned to `> 40` on measured evidence. A regression test that has never
failed is not evidence.

New `test_end_to_end_shutter_position_streaks` drives the real
`convert_scene → convert_objects` pipeline against the compiled renderer, parameterised
over all three positions, and pins centres at END 48.0 < CENTER 68.0 < START 89.0 with
zero width spread. 19 own tests + 74 neighbours green, foreground.

**Open judgment call, decided:** shading normals still derive from the current-frame
matrix. The renderer stores one non-interpolated normal set per triangle, so there is no
fully correct option — and for CENTER (the default) `frame` *is* the shutter midpoint,
making current-frame the best available single sample. Left as-is deliberately; the
tradeoff is being recorded in the pkg88 spec so it isn't re-derived later. Interpolating
normals would need a renderer-side second normal set, out of Phase B scope.

**Independent re-review: SIGN-OFF**, with the strongest evidence of the night. The
reviewer ran the *new* tests against the *old* pre-fix code in a scratch tree and got
`10 failed, 9 passed`, reproducing the exact `CENTER: streak only 30 columns wide` and
`END: streak only 13 columns wide` failures independently — proving the new tests are
genuine regression guards rather than merely different. Post-fix all three positions
measure `width=49` with correctly ordered, evenly spaced centres (END 48.0 < CENTER 68.0
< START 89.0). All `convert_objects` call sites re-checked after the second signature
change; instancing, frame restoration, `id()` caching and `ADDON_FILES` all still clean.

## And then the real-Blender check found a blocker nobody had hit

Both the implementer and the reviewer named the same residual gap: their end-to-end test
mocks `bpy`, so a real depsgraph re-cook under `frame_set` was never exercised. Memory
says Blender 5.1 is installed locally and these checks are mine to run, so I wrote a
headless harness and ran it.

**It fails immediately, on every shutter position, with
`RuntimeError: Camera not set up`.**

`convert_scene` executes in this order: `renderer.clear()` → `set_camera_motion_blur(…)`
→ `setup_camera(…)`. And I confirmed on the real engine that **`clear()` wipes the
camera**:

```
setup_camera(...)   -> set_camera_motion_blur OK
clear()             -> set_camera_motion_blur RAISED "Camera not set up"
```

So with `use_motion_blur = True`, `convert_scene` raises before it ever reaches
`setup_camera`. **Enabling motion blur in the Blender addon fails the render outright.**

**This is pre-existing and is NOT pkg88-B's doing.** The same ordering is on `origin/main`
(`clear()` 1620, `set_camera_motion_blur` 1676, `setup_camera` 1689) — meaning **pkg88-A's
camera motion blur has been broken in real Blender since it shipped.** No test caught it
because every motion-blur suite mocks `bpy` and stubs `setup_camera`, so none of them
model `clear()`'s side effect on camera state.

I have asked the implementer to fix it inside #525 anyway, because object motion blur
cannot be switched on without `use_motion_blur = True`, so merging as-is would ship a
feature that fails on first use — fixing it is what makes the deliverable reachable, not
scope creep. The harness is to be promoted into `scripts/verify_pkg88b_blender.py`
alongside the existing `verify_pkg114_*_blender.py` scripts; a real-Blender check living
only in a scratchpad protects nobody.

**PR held, not merged.**

## Latent landmine found by pkg157's CI failure: a phantom overload in the wavefront header

PR #526's `cuda-syntax-check` failed with *"no instance of overloaded function
`launchStageShadeBucketed` matches the argument list"*. My local Release+CUDA
build reproduced it independently and showed more than CI did — nvcc named
**two** candidate declarations, neither matching the definition:

| where | tail of parameter list |
|---|---|
| `gpu_wavefront_snapshot.cu:93` (local re-decl) | `… bool, bool, GPhotonGrid, bool, float)` — photon params, **no clamps** |
| `gpu_wavefront_state.h:333` (header) | `… bool, bool, float, float)` — clamps, **no photon params** |
| `stage_advance.cu:1231` (definition) | `… bool enableNEE, float clampDirect, float clampIndirect, GPhotonGrid, bool, float)` — **both** |

Checking `origin/main` shows **the header declaration was already wrong before
pkg157 touched it** — on main it ends at `bool enableNEE);` with no photon
parameters, while the definition has had them all along. So
`gpu_wavefront_state.h` has been declaring a **phantom overload that no
definition matches**, and the local re-declaration in the snapshot TU exists
because it is the *correct* one, shadowing the broken header for that
translation unit. It compiled on main only because every real call matched the
local decl and nothing ever called the phantom.

pkg157 added the clamps to the header and the definition but not the third
copy, so the call site matched neither and the latent inconsistency finally
surfaced. Notably the implementer's call-site sweep was not wrong so much as
aimed at the wrong target: it searched for *call sites*, and the trap was a
*duplicate declaration*.

I authorised fixing the root cause rather than just unblocking — correct the
header to match the definition and delete the redundant local re-declaration
(the file already includes the header) — so the next signature change touches
two places instead of three. Flagged in the PR as a deliberate call, not scope
creep, and the implementer is re-sweeping for the same pattern on the other
changed launchers.

The re-sweep I asked for then found **two more** stale private re-declarations
in the same file (`launchStageIntersectQueued` at `:74`,
`launchStageShadeNeeMis` at `:117`) which would have failed at *link* time
rather than compile time. All three are now deleted and the header is the single
source of truth. Of 12 symbols carrying the duplicate-declaration pattern, 8
pkg157-touched launchers now agree and 2 apparent mismatches were false
positives (a default argument and parameter naming).

**One real mismatch remains and was deliberately NOT fixed:** `launchStageInit`
has the identical defect — the header declares 6 parameters
(`…, uint64_t seed, int sample_index = 0`) while the definition in
`stage_init.cu` takes 8 (`+ lambdaMin, lambdaMax`), and all 6 call sites pass 8.
Its private re-declaration is therefore **load-bearing**; deleting it breaks the
build. It has been left in place with an inline comment saying exactly that.
Correcting the header there means removing or relocating a default argument,
which is behaviour-affecting — correctly deferred rather than done blind at
02:00. **This wants a follow-up ticket** (see Action items).

**Process note:** CI caught the original failure and the implementer could not
have, because subagents on this machine cannot build CUDA. That division of
labour worked exactly as intended tonight — but it means "implementer says the
sweep is clean" is never evidence of compilability here.

## Structural constraint discovered (drove tonight's lane plan)

**Four specs all edit `src/gpu/wavefront/stage_advance.cu`** — pkg157, pkg156,
pkg159 and pkg120. They cannot run as parallel implementer worktrees without
guaranteed merge conflicts. They must serialize through a single wavefront lane.
This is worth carrying into every future dispatch plan; it is not a
tonight-only fact.

## Action items for owner

**Decisions I need from you (ranked):**

1. **pkg160 / PR #527 — the decision I most need, and it is not the one I expected
   to be asking.** The GPU metal deficit is real (3.5× mean / 7× median, on the
   only GPU path we ship, ungated). But Step 0 found that **the CPU side is the
   physically wrong one at low roughness**: `GGXEnergyCompensationLUT` estimates
   `E` with 256 uniform-hemisphere samples, cannot resolve a narrow GGX lobe, and
   so drives `Fms` to 96.5% of its mathematical ceiling exactly where multiple
   scattering should vanish — adding a cosine-free `albedo × 0.111` ambient floor
   to every rough metal. Three ways forward:
   - **Option A** (upload the runtime LUT to the GPU): exact parity by
     construction, but propagates the artifact onto the GPU.
   - **Option B** (mirror using the GPU's correct Cycles tables): measured to close
     only ~1% of the gap; effectively dead.
   - **Option C** (fix the CPU LUT): makes the CPU *dimmer* on every rough metal,
     changing the canonical reference and every image that depends on it.

   I did not pick. Parity and physics point in opposite directions here, and which
   one you want is a project-direction call, not an implementation detail.
   **PR #527 is open with the measurement and the pin test only** — no mirror, no
   gate, nothing that presumes an answer.
2. **Approve tightening the GPU/CPU parity bands.** Current bands are `[0.4, 2.5]`,
   `[0.5, 2.0]`, `[0.5, 1.5]`, `[0.7, 1.1]`. Bands that admit a 25% error are not
   gates. Tightening will turn several currently-green tests red — that is the
   point, and it needs your sign-off rather than a silent re-pin.
3. **pkg157 spec: two contract clauses are unsatisfiable and need amending.**
   - Item 2 demands clamps-off be **"BYTE-IDENTICAL"**. The wavefront is not
     bit-identical to *itself* (atomic accumulation ordering), so this can never
     hold. Should read: agreement within the 1e-5 wavefront MC convention. The
     PR measures 2.48e-07, ~40× inside that.
   - Item 3 demands `clampIndirect=10 → <0.02% delta`. **No scene in the library
     has a firefly tail** (peak/p99.9 = 1.04–1.82× across five scenes), so this is
     not demonstrable anywhere. pkg161 is filed to build a scene that makes it
     testable; until then the clause should be scene-relative or deferred.
4. **`build_cuda_worktree.bat` pins CUDA v12.6 while `CUDA_PATH`/`PATH` resolve to
   v12.8.** Worktree and main-checkout builds therefore use different compilers,
   and register allocation is compiler-version sensitive. I deliberately did NOT
   change this — swapping toolkits mid-investigation would forge phantom register
   jumps in exactly the pkg155 numbers above. Needs a standalone decision.

**Bugs found that nobody owned:**

5. **Blender motion blur is broken and has been since pkg88-A shipped.**
   `convert_scene` runs `clear()` → `set_camera_motion_blur()` → `setup_camera()`,
   and `clear()` wipes the camera, so enabling motion blur raises
   `RuntimeError: Camera not set up` and the render fails. Pre-existing on `main`.
   Fix routed into PR #525 because pkg88-B's feature is unreachable without it.
   **This is the strongest argument for real-host integration tests I can offer:**
   every motion-blur suite mocks `bpy` and stubs `setup_camera`, so none of them
   could ever have caught it.
6. **A phantom overload in `gpu_wavefront_state.h`**, also pre-existing: the header
   declared a `launchStageShadeBucketed` signature no definition matched, masked by
   a private duplicate declaration. Fixed in #526, along with two more of the same
   pattern. **One remains and is load-bearing** — `launchStageInit`'s header
   declares 6 params against a definition taking 8. Correcting it requires
   removing or relocating a default argument, which is behaviour-affecting; left
   alone with an inline comment. **Wants its own ticket.**

**Informational:**

7. **Orphaned worktree directories.** Seven merged worktrees were unregistered from
   git cleanly (`git worktree list` shows only `main`), but their directories could
   not be deleted — OneDrive holds file locks and recursive force-delete is blocked
   in this session. Dead weight on disk only, no correctness impact.
8. **Task Scheduler orchestrator task** left **Disabled**, as instructed.
9. **Morning HTML report:**
   `test_results/overnight_report_2026-07-25/overnight_report_2026-07-26.html`.
