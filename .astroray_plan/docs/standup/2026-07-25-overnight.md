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

<!-- STATUS: running — finalize before shutdown -->

## Headline: two investigations closed with hard numbers, one new defect found

Nothing shipped as a *fix* tonight in the GPU lane — by design. pkg155 and the
new metal finding are both measurement results, and the owner's standing rule is
that honest FAILs and measured attributions beat forced merges.

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

**Process note:** CI caught this and the implementer could not have, because
subagents on this machine cannot build CUDA. That division of labour worked
exactly as intended tonight — but it means "implementer says clean" is never
evidence of compilability here.

## Structural constraint discovered (drove tonight's lane plan)

**Four specs all edit `src/gpu/wavefront/stage_advance.cu`** — pkg157, pkg156,
pkg159 and pkg120. They cannot run as parallel implementer worktrees without
guaranteed merge conflicts. They must serialize through a single wavefront lane.
This is worth carrying into every future dispatch plan; it is not a
tonight-only fact.

## Action items for owner

1. **Read the metal finding first** — a 3.5× GPU energy deficit on plain
   `metal`, unguarded by any test, on the only GPU path we ship. It is my
   strongest candidate for the next implementer slot ahead of pkg150.
2. **Approve tightening the GPU/CPU parity bands.** Bands that admit a 25% error
   are not gates. Tightening will turn several currently-green tests red — that
   is the point, and it needs your sign-off rather than a silent re-pin.
3. **`build_cuda_worktree.bat` pins CUDA v12.6 while `CUDA_PATH`/`PATH` resolve
   to v12.8.** Worktree builds and main-checkout builds therefore use different
   compilers, and register allocation is compiler-version sensitive. I did NOT
   change this tonight on purpose — swapping toolkits mid-investigation would
   forge phantom register jumps in exactly the pkg155 numbers above. Needs your
   decision as a standalone change.
4. **Orphaned worktree directories.** Seven merged worktrees were unregistered
   from git cleanly (`git worktree list` shows only `main`), but their
   directories could not be deleted — OneDrive holds file locks, and recursive
   force-delete is blocked in this session. They are dead weight on disk only.
5. **Task Scheduler orchestrator task** left **Disabled**, as instructed.
6. **Morning HTML report:**
   `test_results/overnight_report_2026-07-25/overnight_report_2026-07-26.html`.
