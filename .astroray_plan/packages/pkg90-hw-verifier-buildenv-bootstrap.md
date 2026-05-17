# pkg90 — Hardware-verifier build-env bootstrap (MSVC + worktree-parameterized CUDA build)

**Pillar:** 5
**Track:** A (engine/build-script plumbing — no GPU correctness change, no physics, no CUDA kernel change; only how the existing CUDA build is invoked)
**Codex-paste-ready:** yes
**Status:** ready
**Estimated effort:** ~½ day (~4 h)
**Depends on:** roadmap-orchestrator design spec (2026-05-16) — the engine/skill whose HW gate this unblocks; no code overlap with pkg97 (close-out GC) or pkg98 (review gate), but same SKILL.md Safety-rails surface — if any are in flight, rebase, do not blind-merge-resolve.

---

## Goal

**Before:** The orchestrator's local hardware gate (design spec §2a,
SKILL Step 2.3) is **structurally unable to run unattended** on this
Windows box. PR #318 (pkg55-S8) is CI-green + `MERGEABLE` but
permanently `hw_blocked_buildenv`: it can never get the
head-SHA-bound hardware `PASS` that dual-gate auto-merge requires, so
it stalls forever awaiting a manual owner RTX run. This defeats the
entire "survives terminal close; runs unattended" design goal
(design spec §3). It is **structural, not incidental** — it recurs on
every HW-gated PR (memory `hw-verifier-msvc-env-blocker`).

Two independent root causes, both established 2026-05-17 on the
#318 HW gate:

1. **No MSVC toolchain in the verifier's shell.** The
   `hardware-verifier` agent has only Bash/Read/Grep/Glob. Its Bash
   shell has `nvcc` on PATH but **no `cl.exe`**
   (`VCINSTALLDIR`/`VSCMD_VER` empty) → nvcc dies with
   `Cannot find compiler 'cl.exe' in PATH`. The harness `PowerShell`
   tool *also* lacks MSVC env. MSVC is only reachable from a
   "Developer PowerShell for VS 2022" or after `call vcvars64.bat`.
   `run_clean_build.ps1` does **not** init vcvars (it assumes a dev
   shell). The verifier therefore cannot perform Step 1 (clean
   rebuild) at all.

2. **The CUDA build is pinned to `main`, not the PR worktree.**
   `build_cuda_run.bat` *does* `call vcvars64.bat`, but line 3
   hardcodes `cd /d "…/Astroray_repo/Astroray"` — the **main
   checkout**. Running it to verify a PR builds `main`, not the
   branch (an invalid gate **and** worktree contamination — memory
   `parallel_agent_worktree_contamination`). Worse, the verifier's
   `cmake … --target clean` deletes the *worktree* `.pyd` before the
   rebuild it then cannot perform, leaving the worktree build dir
   empty.

**After:** The hardware-verifier is **build-env self-sufficient**.
On any HW-gated PR the verifier (a) bootstraps the MSVC toolchain
itself (locate via `vswhere`, `call vcvars64.bat` / `VsDevCmd`,
so `cl.exe`+`nvcc` are on PATH in *its own* shell), and (b) builds
the **PR's worktree** at the **PR's head SHA**, never `main`. A
HW-gated PR is built + rendered + recorded **with zero owner
intervention**; the #318 scenario reproduces and passes
automatically.

---

## Context — why this matters now

The orchestrator is the project's autonomous advance engine. CI
(no GPU — memory `ci_has_no_gpu_runtime_blindspot`) is currently the
*only* gate that actually runs; the hardware gate — the load-bearing
half of the dual gate, the only thing that catches GPU-correctness
CI cannot — is a permanent no-op. Every HW-gated PR re-dispatches
`hardware-verifier`, which hits the same wall and produces no
PASS/FAIL; the re-dispatch is a no-op loop and auto-merge can never
fire (memory `hw-verifier-msvc-env-blocker`: *"Do NOT keep
re-dispatching `hardware-verifier` expecting a different result. The
fix needs owner-level infra."*). This package is that owner-level
infra, scoped to the **minimum** that makes the existing verifier
self-sufficient (CLAUDE.md §2/§3) — **not** a CI/build-system
rework.

This is build-script/agent-prompt plumbing only — no GPU correctness
change, no physics, no CUDA kernel change (only *how* the existing
CUDA build is invoked and *where*). It does not contend for the
serialized GPU slot during its own implementation (its tests are
mocked — see Acceptance), and it is the prerequisite that makes
every *other* HW-gated package's gate function.

---

## Reference

### Internal

- Memory `hw-verifier-msvc-env-blocker` — the authoritative
  problem statement: no `cl.exe` in Bash/PowerShell tool shells;
  `run_clean_build.ps1` assumes a dev shell;
  `build_cuda_run.bat` line 3 hardcodes the main checkout;
  the verifier's `--target clean` empties the worktree build dir.
  The two fix options it names: (a) a vcvars-init +
  **worktree-parameterized** build wrapper the verifier can invoke
  (this package), or (b) the orchestrator builds it itself. This
  package implements (a) — least invasive, keeps the verifier the
  single owner of build+test.
- [`.astroray_plan/docs/2026-05-16-roadmap-orchestrator-design.md`](../docs/2026-05-16-roadmap-orchestrator-design.md)
  — §2a Hardware gate (strictly serialized, asynchronous across
  ticks; build the `.pyd` on the RTX with `pkg-ship` Step-0
  stale-`.pyd` hygiene against **that PR's branch worktree**),
  §5 safety rails (exactly one CUDA job at a time; per-package
  isolated worktree, never `main`; `--dry-run` zero side effects),
  §6 (HW result bound to PR number + head SHA).
- [`.claude/skills/roadmap-orchestrator/SKILL.md`](../../.claude/skills/roadmap-orchestrator/SKILL.md)
  — Step 2.3 hardware gate (the `verify` / `hardware-verifier`
  dispatch path; "builds the `.pyd` on the RTX with `pkg-ship`
  Step-0 hygiene and runs the package acceptance render/test";
  "Exactly one GPU/CUDA job ever").
- [`.claude/agents/hardware-verifier.md`](../../.claude/agents/hardware-verifier.md)
  — the 5-step workflow this package amends: Step 1 *Clean rebuild*
  (currently `cmake --build --preset windows-tcnn-vs-release` else
  "open a Developer Command Prompt … `cmake --build build_cuda
  --config Release -j`" — an instruction the agent has no tool to
  satisfy) and Step 2 *stale-`.pyd` smoke-check* (the Step-0
  hygiene that MUST be preserved).
- [`.claude/skills/verify/SKILL.md`](../../.claude/skills/verify/SKILL.md)
  — `/verify <pkg>` pre-spawn: finds the PR, reads the spec for the
  newest binding + acceptance gates, passes PR number + spec path +
  binding to the verifier. The place the **target worktree path +
  head SHA** must additionally be resolved and passed.
- `build_cuda_run.bat` (repo root) — the main-pinned wrapper:
  `call vcvars64.bat` (good — keep) then `cd /d "…/Astroray"`
  (the defect — must be parameterized) then `cmake --build
  build_cuda --target astroray`.
- `run_clean_build.ps1` (repo root) — does **not** init vcvars;
  `cmake --build build_cuda --config Release -j` then echoes
  `BUILD_EXIT_CODE` / `BUILD_ELAPSED_SECONDS`. The verifier-facing
  build entry that must gain vcvars bootstrap + worktree
  parameterization while keeping its existing exit-code contract.
- [`.claude/skills/pkg-ship/SKILL.md`](../../.claude/skills/pkg-ship/SKILL.md)
  — Step 0 stale-`.pyd` hygiene + `astroray.__file__` canonical-
  path check (CLAUDE.md "Build & Verification"). **Must be
  preserved unchanged** by this package — the bootstrap runs
  *before* it, never replaces it.
- Memory `cuda_verifier_concurrency` — exactly one CUDA-executing
  job at a time on this RTX; the single-GPU-lock serialization
  (`.orchestrator.gpu.lock`) MUST be preserved. This package does
  **not** add parallelism; it only fixes the env+path of the one
  serialized job.
- Memory `stale_pyd_locations` — multiple `astroray.pyd` shadow the
  canonical `build_cuda/Release/`; the OneDrive read-only/locked-dir
  footgun. The bootstrap must build into and verify the **worktree's
  own** `build_cuda/Release/` (`astroray.__file__`), never a shadow
  or the main checkout's.
- Memory `incremental-build-signature-staleness` — a worktree build
  dir carried/copied from elsewhere can link stale `.obj` against
  new headers; the bootstrap must guarantee the worktree build is
  the head-SHA tree's, not a stale carryover.
- Memory `parallel_agent_worktree_contamination` — why building the
  PR's *own* isolated worktree (never `main`) is non-negotiable.
- [`.astroray_plan/packages/pkg97-orchestrator-merged-worktree-autogc.md`](pkg97-orchestrator-merged-worktree-autogc.md),
  [`pkg98-orchestrator-independent-review-gate.md`](pkg98-orchestrator-independent-review-gate.md)
  — sibling orchestrator-infra specs; structural template for this
  spec; same SKILL.md Safety-rails surface, **no code overlap**
  (pkg97 = close-out GC; pkg98 = review gate; pkg90 = HW build env).
  If concurrently in flight, the SKILL.md edits are in different
  blocks — rebase, do not blind merge-resolve.

### External (read for understanding only — no code mirrored)

- `vswhere.exe` — Microsoft's official VS locator, shipped at
  `%ProgramFiles(x86)%\Microsoft Visual
  Studio\Installer\vswhere.exe`. Authoritative way to discover the
  VS/BuildTools install path without hardcoding a version
  (the current `build_cuda_run.bat` hardcodes the 2022 BuildTools
  path — fragile across machines/upgrades). Used read-only to
  locate `VC\Auxiliary\Build\vcvars64.bat` /
  `Common7\Tools\VsDevCmd.bat`.
- `vcvars64.bat` / `VsDevCmd.bat -arch=amd64` — Microsoft's
  documented MSVC environment initialisers. The bootstrap *calls*
  these (does not reimplement them) — exactly what the existing
  `build_cuda_run.bat` already does, generalised to be
  vswhere-discovered and worktree-parameterized.

---

## Specification

### Phase 0 — locate the exact build invocation path (~½ h)

Read-only mapping. Confirm and record file:line of:

1. The verifier's build step that fails: `hardware-verifier.md`
   Step 1 (the `cmake --build --preset …` / "Developer Command
   Prompt" fallback the agent cannot satisfy) and Step 2 (the
   stale-`.pyd` smoke-check that MUST be preserved).
2. Where `/verify` (`verify/SKILL.md`) resolves what to pass to the
   verifier, and where the orchestrator SKILL Step 2.3 dispatches
   the `verify`/`hardware-verifier` job for `plan.hw_dispatch` —
   i.e. the two call sites that must start passing **target
   worktree path + head SHA**.
3. The current build scripts' contracts: `build_cuda_run.bat`
   (the `vcvars64.bat` call to keep; the hardcoded `cd` to fix;
   the `cmake --build build_cuda --target astroray` line) and
   `run_clean_build.ps1` (its `BUILD_EXIT_CODE` /
   `BUILD_ELAPSED_SECONDS` stdout contract that downstream parsing
   may depend on — preserve it).

Record each in the PR description. **No behaviour change in
Phase 0.**

### Phase 1 — vcvars bootstrap (locate + init MSVC, version-agnostic)

Add a single, well-scoped build wrapper the verifier invokes
(extend `build_cuda_run.bat`, or add a thin sibling it delegates
to — Phase-0 decides which is least invasive; do **not** add a new
parallel build system). It MUST, in order:

1. **Locate MSVC via `vswhere`** at the documented Installer path,
   querying for a C++ toolset
   (`-products * -requires
   Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property
   installationPath`). Derive `vcvars64.bat` (or
   `VsDevCmd.bat -arch=amd64`) from the returned `installationPath`.
   Do **not** hardcode the 2022 BuildTools path (the current
   `build_cuda_run.bat` does — fragile; replace it with the
   vswhere-discovered path, falling back to the existing hardcoded
   path only if vswhere is absent so behaviour never regresses on
   the current box).
2. **`call` the discovered `vcvars64.bat`** so `cl.exe` and `nvcc`
   are on PATH **in the build process's own environment**. Verify
   by asserting `cl` and `nvcc` resolve (e.g. `where cl`,
   `where nvcc`) before proceeding; if either is missing after the
   call, **fail fast with a clear diagnostic** ("MSVC bootstrap
   failed: cl.exe not on PATH after vcvars64") — never proceed to a
   build that will die mid-`nvcc` with the cryptic
   `Cannot find compiler 'cl.exe'`.
3. Be **idempotent / re-entrant**: if `cl.exe` is *already*
   resolvable (the verifier is run from an already-dev shell), the
   bootstrap is a no-op fast-path, not a double-init.

Self-bootstrap-from-Bash requirement: the `hardware-verifier` has
only the Bash tool. The verifier MUST be able to trigger the whole
build by invoking this wrapper from Bash (e.g.
`cmd /c build_cuda_run.bat <worktree> <sha>` or
`powershell -File <wrapper>.ps1 -Worktree <path> -Sha <sha>`),
because env set by `call vcvars64.bat` does **not** persist back
into the Bash tool's shell across tool calls. The bootstrap +
vcvars + cmake build MUST therefore all happen **inside one child
process invocation** so the MSVC env is live for the `nvcc`/`cl`
build within that single process. The verifier prompt states this
explicitly with the concrete one-line invocation.

### Phase 2 — worktree + head-SHA parameterization (un-pin from `main`)

The wrapper MUST take the **target worktree path** and **expected
head SHA** as parameters (positional or named — Phase-0 picks the
convention matching the existing scripts):

1. Replace the hardcoded
   `cd /d "…/Astroray_repo/Astroray"` (`build_cuda_run.bat` line 3)
   with `cd /d "<target-worktree>"`. The build operates on the
   **PR's worktree**, never the main checkout.
2. **Assert the worktree is at the expected head SHA** before
   building: `git -C "<target-worktree>" rev-parse HEAD` MUST equal
   the passed SHA; mismatch → **fail fast** ("worktree HEAD <a> ≠
   expected PR head <b> — refusing to build a stale/contaminated
   tree"). This binds the build to the SHA the HW result will be
   recorded against (design spec §6) and is the structural guard
   against the memory `parallel_agent_worktree_contamination` /
   `incremental-build-signature-staleness` traps.
3. Build into and import from the **worktree's own**
   `build_cuda/Release/`. The wrapper does not touch the main
   checkout's build dir. Preserve `run_clean_build.ps1`'s
   `BUILD_EXIT_CODE` / `BUILD_ELAPSED_SECONDS` stdout contract if
   that path is the one extended.
4. Thread the parameters through the dispatch chain: orchestrator
   SKILL Step 2.3 already looks up the PR's `headRefOid` and knows
   the PR's branch worktree — it MUST pass **worktree path + head
   SHA** into the `verify`/`hardware-verifier` dispatch;
   `verify/SKILL.md` MUST forward them; `hardware-verifier.md`
   Step 1 MUST invoke the wrapper with them. Update all three
   call sites consistently (call-site sweep — see Acceptance).

### Phase 3 — preserve Step-0 hygiene + GPU serialization (regression fences)

These are **not new behaviour** — they are invariants this package
must **not** break, called out so they are explicitly tested:

1. **`pkg-ship` Step-0 stale-`.pyd` hygiene is preserved
   verbatim.** The bootstrap runs *before* the existing stale-`.pyd`
   scan + `astroray.__file__` canonical-path check
   (`hardware-verifier.md` Step 2); it does not replace, skip, or
   weaken it. After the worktree build, the verifier still asserts
   the freshly built `.pyd` is the one imported
   (`astroray.__file__` resolves into the **worktree's**
   `build_cuda/Release/`, not a repo-root shadow or the main
   checkout — memory `stale_pyd_locations`). The wrapper must not
   delete the worktree `.pyd` *before* it can rebuild it (the
   exact #318 `--target clean`-then-can't-build failure): clean
   only when the rebuild will actually run, or build then verify
   freshness by mtime/binding.
2. **Single-CUDA-job serialization is preserved.** This package
   changes only *how/where* the one serialized CUDA job is built —
   it does **not** introduce a second concurrent CUDA job and does
   **not** alter `.orchestrator.gpu.lock` acquisition/hold/release
   (design spec §2a/§5, memory `cuda_verifier_concurrency`). The
   wrapper itself acquires no GPU lock (the orchestrator owns it);
   the build+render still happens entirely within the single
   GPU-lock-held window.

### Files to modify

| File | Change |
|---|---|
| `build_cuda_run.bat` (or a thin sibling wrapper it delegates to — Phase-0 decides) | vswhere-discover + `call vcvars64.bat` (fallback to current hardcoded path if vswhere absent — no regression on this box); take **`<target-worktree>` + `<expected-head-sha>`** params; replace the hardcoded `cd`; assert worktree HEAD == expected SHA (fail fast on mismatch); assert `cl`+`nvcc` on PATH after vcvars (fail fast); idempotent if already a dev shell; build into the worktree's own `build_cuda`. |
| `run_clean_build.ps1` | If this is the verifier-facing build entry (Phase-0): add the same vcvars bootstrap + worktree/SHA parameters; **preserve** the existing `BUILD_EXIT_CODE` / `BUILD_ELAPSED_SECONDS` stdout contract. If `build_cuda_run.bat` is the chosen entry, leave this file untouched. |
| `.claude/agents/hardware-verifier.md` | Step 1: replace the unsatisfiable "open a Developer Command Prompt" fallback with the concrete one-line Bash invocation of the bootstrap wrapper, passing the target worktree path + expected head SHA (a single child-process call so the MSVC env is live for that build). Add a one-line fail-fast note (cl/nvcc/SHA assertion). **Do not** alter Step 2 (stale-`.pyd` smoke-check), Step 4 (visual inspection) or the Hard rules. |
| `.claude/skills/verify/SKILL.md` | Pre-spawn: in addition to PR number + spec path + newest binding, resolve and pass the **PR's branch worktree path + head SHA** (`gh pr view --json headRefOid`; the branch's registered worktree) to `hardware-verifier`. |
| `.claude/skills/roadmap-orchestrator/SKILL.md` | Step 2.3: where it dispatches `verify`/`hardware-verifier` for `plan.hw_dispatch`, pass the PR's worktree path + the `headRefOid` it already looks up. Safety-rails block: add one line — *"the HW build runs the PR's own worktree at its head SHA via the vcvars-bootstrapping wrapper; never `main`; Step-0 stale-`.pyd` hygiene and single-CUDA-job serialization are unchanged."* No change to GPU-lock logic. |
| `tests/test_hw_verifier_buildenv.py` *(new)* | Unit tests with **mocked** `vswhere`/`cmd`/`git`/filesystem (no real MSVC, no real CUDA build, no GPU, no network) for every branch in Acceptance criteria. |

### Acceptance criteria

- [ ] **Primary (reproduces #318 passing automatically):** the
      pkg55-S8 / #318 scenario — a CI-green, `MERGEABLE`, HW-gated
      PR previously stuck `hw_blocked_buildenv` — is **built +
      rendered + recorded `PASS`/`FAIL` with zero owner
      intervention** end-to-end (the dispatched `hardware-verifier`
      now self-bootstraps MSVC, builds the PR's worktree at its head
      SHA, and produces a head-SHA-bound result the dual gate can
      consume).
- [ ] **vcvars bootstrap (mocked):** with `cl.exe` *not* on the
      simulated PATH, the wrapper locates MSVC via vswhere, `call`s
      vcvars64, and `cl`+`nvcc` resolve afterward; the build
      proceeds. With vswhere absent, it falls back to the existing
      hardcoded path (no regression on the current box).
- [ ] **Fail-fast on missing toolchain:** if `cl.exe` is still not
      resolvable after the vcvars call, the wrapper exits non-zero
      with the explicit "MSVC bootstrap failed" diagnostic — it does
      **not** start a build that dies mid-`nvcc`.
- [ ] **Idempotent:** invoked from an already-dev shell (cl.exe
      already on PATH), the bootstrap is a no-op fast-path; the
      build still runs once.
- [ ] **Worktree parameterization:** the wrapper builds the
      **passed worktree path**, never the hardcoded main checkout;
      a test asserts the build `cwd`/target is the worktree, not
      `…/Astroray_repo/Astroray`.
- [ ] **Head-SHA bind / contamination guard:** if the worktree's
      `git rev-parse HEAD` ≠ the expected passed SHA, the wrapper
      fails fast and does **not** build (no stale/contaminated-tree
      gate). Mirrors design spec §6 (result bound to head SHA).
- [ ] **Step-0 hygiene preserved:** the stale-`.pyd` scan +
      `astroray.__file__` canonical-path check
      (`hardware-verifier.md` Step 2) still runs and still resolves
      into the **worktree's** `build_cuda/Release/`; the wrapper
      does not delete the worktree `.pyd` before it can rebuild it
      (regression guard on the exact #318 `--target clean` failure).
- [ ] **GPU serialization preserved:** no second concurrent CUDA
      job is introduced; `.orchestrator.gpu.lock`
      acquire/hold/release is unchanged (assert: this package adds
      no GPU-lock code and no parallel CUDA dispatch — memory
      `cuda_verifier_concurrency`).
- [ ] **Call-site sweep:** the wrapper's new parameter signature
      and the worktree-path/head-SHA threading are grepped
      repo-wide; `verify/SKILL.md`, `roadmap-orchestrator/SKILL.md`
      Step 2.3, and `hardware-verifier.md` Step 1 are all consistent
      (no caller invokes the wrapper with the old main-pinned
      zero-arg form).
- [ ] `--dry-run` of the orchestrator still performs **zero** side
      effects — no build, no GPU work, no MSVC bootstrap, no file
      write (regression guard on design spec §5; the bootstrap is
      live-path only, inside the GPU-lock-held HW job).
- [ ] Existing orchestrator + verifier-adjacent test suite stays
      green (`pytest tests/test_orchestrator*.py` and the new
      `tests/test_hw_verifier_buildenv.py`).

### Hard non-goals

- **No CI/build-system rework.** vswhere-discovery + vcvars init +
  worktree/SHA params on the *existing* build path — nothing more.
  No new CMake presets, no new build generator, no Linux/CI build
  change (CI has no GPU and is out of scope — memory
  `ci_has_no_gpu_runtime_blindspot`).
- **No second CUDA job / no parallelism.** Exactly one
  CUDA-executing job at a time stays the invariant; this package
  only fixes the env+path of that one job (memory
  `cuda_verifier_concurrency`). No change to `.orchestrator.gpu.lock`
  logic.
- **No change to `pkg-ship` Step-0 hygiene.** The stale-`.pyd`
  scan + `astroray.__file__` canonical-path check is preserved
  verbatim; the bootstrap runs *before* it, never replaces it.
- **No "orchestrator builds it itself" path** (memory
  `hw-verifier-msvc-env-blocker` option (b)). This package
  implements option (a) — the verifier stays the single owner of
  build+test; option (b) is explicitly out of scope.
- **No move of the GPU lock or async read-back model.** Design
  spec §2a's serialized, asynchronous-across-ticks HW gate is
  unchanged; only the build invocation it runs is fixed.
- **No new persisted state.** No new lock/state files; the HW
  result is still recorded by the existing `record_hw_result`
  ledger path keyed by PR + head SHA (design spec §6).
- **No owner-side automation / scheduler change.** The fix lives
  inside the existing bounded-tick HW-gate dispatch, not a separate
  cron.
- **No reimplementation of `vcvars64.bat`/`VsDevCmd.bat`.** They
  are *called*, not re-derived (CLAUDE.md §6 — borrow, don't
  invent; these are Microsoft's documented initialisers).

---

## Why this matters

This package is the difference between an orchestrator whose dual
gate actually runs and one whose load-bearing half — the empirical
RTX gate that catches the GPU-correctness CI structurally cannot
(memory `ci_has_no_gpu_runtime_blindspot`) — is a permanent no-op.
Today **every** HW-gated PR (#318 and every successor) stalls
forever awaiting a manual owner RTX run, so the "runs unattended"
design goal is unmet by construction. It encodes two permanent
invariants the verifier was missing: *the verifier bootstraps its
own MSVC toolchain* (no more "cl.exe not found" dead loop), and
*the HW build is always the PR's own worktree at its own head SHA,
never `main`* (no more invalid-gate / contamination trap). It is
deliberately minimal — it makes the **existing** verifier
self-sufficient and changes nothing about the serialized GPU model
or Step-0 hygiene it depends on.

---

## Lessons (filled in on completion)
