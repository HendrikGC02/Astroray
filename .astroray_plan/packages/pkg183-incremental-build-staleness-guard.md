# pkg183 — Guard against stale-object incremental builds (ABI-mixed binaries)

**Pillar:** 5 (build infrastructure / verification integrity)
**Track:** A
**Status:** done (PR #592, 2026-08-12 — items 1–3 implemented:
header-hash stamp + force-clean-on-mismatch, a <5 s host-only ABI canary, AND
a cuobjdump ground-truth CUDA-arch gate (PR #590 scope-add) wired into all
three build wrappers; item 4 evaluated-only, see Lessons)
**Estimated effort:** S–M
**Depends on:** `scripts/build/build_cuda.bat`, `scripts/build/build_cuda_worktree.bat`,
repo-root `build_cuda_worktree.bat`.

## Incident (2026-08-11/12)

During the hygiene run, incremental Ninja builds of `build_cuda/` produced
binaries that access-violated on host-side code (`get_material_backend_capabilities`
on a lambertian — 3-line no-GPU repro) and on every GPU closure-graph render.
The failures were perfectly reproducible, survived reconfigures and arch
switches, and a `git bisect run` "attributed" them to cbbccf5 (PR #574, which
grew `MaterialClosure`/`GTriangle` layouts) with a clean good/bad flip —
all of it wrong. A from-scratch build (`rm -rf build_cuda`) of the SAME tree
passes everything, at both `ASTRORAY_CUDA_ARCHS=89` and `native` (sm_120),
memcheck-clean.

Root cause: stale objects compiled against the pre-#574 struct layouts were
linked together with fresh objects — ABI-mixed binaries. Contributing
factors: the repo lives on OneDrive (mangled mtimes defeat Ninja's
staleness detection), sccache in the loop, and heavy branch-switching across
a layout-changing commit boundary. The `incremental-build-signature-staleness`
memory documented exactly this class; this incident confirms it can also
fabricate a coherent-looking git-bisect result.

Consequences observed before diagnosis: two bogus regression specs filed, an
arch-89 pin applied to both build wrappers (both reverted), and a session-start
"stale .pyd" state on main that may have had the same origin.

### Second incident — stale CUDA arch in the cache (PR #590 verification, 2026-08-12)

The PR #590 hardware verifier found `CMAKE_CUDA_ARCHITECTURES:STRING=52` (stale
Maxwell virtual-PTX) cached in **every** `build_cuda/CMakeCache.txt` inspected —
the main checkout's and every worktree's. Because the root `build_cuda_worktree.bat`
only builds and never reconfigures, the value persists indefinitely. Consequence
already realised: a `cuobjdump` register/stack gate was measured as
`<false,false> STACK 2640` against a stale-arch build when the true sm_120 SASS
number is 3608→3632 — the reading was taken on irrelevant `compute_52` PTX
(JIT'd at runtime), not the sm_120 SASS that actually runs. This directly
invalidates resource-gate readings, i.e. the exact "verification integrity"
pillar this package owns.

Subtlety established while implementing pkg183: the cache line is an
**unreliable** signal. On a Ninja tree configured with `ASTRORAY_CUDA_ARCHS=native`,
CMakeLists' non-cache `set(CMAKE_CUDA_ARCHITECTURES ...)` (CMakeLists.txt:57)
*shadows* the cache — the cache reads `52` yet the built `.pyd` embeds `sm_120`
(confirmed via `cuobjdump --list-elf … → sm_120.cubin`). The stale `52` is only
*live* where `ASTRORAY_CUDA_ARCHS` is unset (the VS-generator worktrees). So the
guard's ground truth must be the **built artifact** (`cuobjdump --list-elf` on
`astroray*.pyd`), not the cache line — that never false-positives on a harmless
shadow and catches every live variant (stale cache, shadowing surprises, wrong
`-D`).

## Work

1. Add a cheap consistency stamp to the build wrappers: after configure,
   record the SHA + a hash of layout-critical headers (`include/astroray/*.h`,
   `include/raytracer.h`) in `build_cuda/.astroray_build_stamp`; on the next
   invocation, if the header-hash changed, run `ninja -t cleandead` AND force
   a full rebuild of targets (or simply wipe) instead of trusting mtimes.
   Simplest robust variant: wipe object dirs whenever the stamp's header-hash
   differs — correctness over speed on this OneDrive tree.
2. Add a post-build smoke check to the wrappers (host-only, <5 s):
   `python -c "import astroray; r=astroray.Renderer(); m=r.create_material('lambertian',[.5,.5,.5],{}); print(r.get_material_backend_capabilities(m))"` —
   this exact call crashed on every contaminated binary this session, making
   it a high-signal canary for ABI mixing.
3. Verifier/implementer dispatch prompts: when a PR touches struct layouts in
   shared headers, require a clean rebuild before hardware verification
   (mirror into both `build_cuda_worktree.bat` copies per the
   `build-cuda-worktree-debug-config` memory).
4. Consider moving build trees off OneDrive (e.g. `%LOCALAPPDATA%\astroray-build`)
   so mtimes are trustworthy — evaluate against the existing sccache setup.

## Implementation notes (items 1–3, 2026-08-12)

- New helper `scripts/build/build_guard.py` (registered in `scripts/README.md`)
  owns three subcommands so the `.bat` files avoid batch-language gymnastics:
  - `check`  — SHA-256 over the layout-critical headers (`include/astroray/*.h`
    + `include/raytracer.h`), compared to `build_cuda/.astroray_build_stamp`;
    prints `WIPE` or `OK`. `WIPE` when the header hash changed **or** a
    configured tree (`CMakeCache.txt` present) has no stamp (predates the guard,
    so it may already be ABI-mixed → force-clean once). A never-configured tree
    prints `OK` (nothing to wipe).
  - `write`  — records `{header_hash, sha}` into the stamp after a successful build.
  - `canary` — reuses `tests/runtime_setup.py` to put the CUDA/OIDN `_deps`
    DLL dirs on the loader path, then runs the exact spec repro
    (`Renderer().get_material_backend_capabilities(create_material('lambertian',…))`).
    Exit 6 on a Python-level failure; a hard access-violation kills the process
    with its own non-zero code, which the wrappers also treat as a canary trip.
  - `arch-verify` — **CUDA-arch gate (PR #590 scope-add):** `cuobjdump --list-elf`
    on the built `astroray*.pyd`; the embedded cubin arch is the ground truth
    (the CMakeCache line is not — it can be a harmless shadow). Expected arch
    auto-detects via `nvidia-smi --query-gpu=compute_cap` (fallback: fail only
    when the ONLY embedded arch is pre-Volta legacy). Exit 7 + loud banner on
    mismatch; missing `cuobjdump`/`nvidia-smi` downgrades to a warning so it can
    never cause a false build failure.
  - `arch-check` — advisory-only pre-build read of the cache arch line; prints a
    heads-up on a legacy-looking value but NEVER gates (deferring to arch-verify).
- Wipe mechanism is `cmake --build <dir> --config Release --target clean`
  (generator-agnostic; removes all objects unconditionally, not mtime-based),
  chosen over `rmdir` so the configure-less root wrapper stays valid.
- Canary failure is a **distinct** exit path (code 6, loud banner) so it is
  never confused with a compile/link failure (code 5); the CUDA-arch gate uses
  code 7. Missing `python` on PATH downgrades the guard to a warning rather than
  failing the build.
- **Not fixed here (deliberate):** the underlying CMakeLists non-cache
  `set(CMAKE_CUDA_ARCHITECTURES …)` at line 57 (which leaves the cache reading
  `52` while the compile is correct) and `configure_and_build.bat` not passing
  `ASTRORAY_CUDA_ARCHS` (which lets VS-generator worktrees compile a *live*
  stale 52). Both are outside pkg183's wrapper-only authorized surface. The
  artifact gate makes the symptom loud and un-missable regardless; a follow-up
  package should FORCE the cache from `ASTRORAY_CUDA_ARCHS` at the CMakeLists
  level so the arch is correct at the source, not just gated post-build.

## Lessons

### Item 4 (move build trees off OneDrive) — evaluate-only assessment

**Recommendation: do NOT move the build tree yet; the pkg183 stamp+canary
already neutralises the failure mode this item targets. Revisit only if the
force-clean-on-mismatch proves too costly in practice.**

Interaction with the existing sccache / `%LOCALAPPDATA%` cache setup:
- Today `SCCACHE_DIR` and `FETCHCONTENT_BASE_DIR` already live under
  `%LOCALAPPDATA%\astroray-cache` (off OneDrive); only the `build_cuda/` object
  tree and the source checkout remain on OneDrive. So the compiler *cache* is
  already immune to OneDrive mtime churn — it is the object tree's mtimes that
  Ninja trusts and OneDrive mangles.
- Moving `build_cuda/` to `%LOCALAPPDATA%\astroray-build\<tree-id>` would make
  Ninja's incremental staleness detection trustworthy again, which is the real
  root cause. `SCCACHE_BASEDIR=%CD%` (the *source* root) is unaffected — sccache
  hashes sources by path relative to the source tree, not the build dir, so
  cross-tree cache hits (host-C/C++ ~98%) are preserved.

Expected win: eliminates the underlying ABI-mixed-binary risk (not just guards
against it), and would let us drop the conservative full-object force-clean —
recovering true incremental builds across layout-changing commits. Marginal
build-time win on top of that is small (objects already write to local disk via
OneDrive's local cache; the pain is correctness, not throughput).

Migration risk (why it is deferred, not done here):
- Every consumer that assumes `build_cuda/` lives *inside* the checkout must be
  updated in lockstep: `tests/runtime_setup.py` build-dir discovery, the
  `.pyd`-mtime canonical-path checks in the rebuild/verify skills, the Blender
  addon staging (`build_blender_addon_cuda/`), CI paths, and the
  `astroray.__file__` stale-`.pyd` guards. Missing one silently reintroduces a
  shadow-`.pyd` class of bug ([[stale_pyd_locations]]).
- Per-worktree build dirs need a stable, collision-free mapping from worktree
  path → build dir (branch names alone collide across re-created worktrees).
- The generator-mismatch and `--config Release` guards already in the wrappers
  assume a per-tree `build_cuda/`; relocating changes their invariants.

This is a genuine follow-up package (S–M), not a rider on pkg183. Filing it
separately keeps the low-risk stamp+canary landable now.
