# pkg183 — Guard against stale-object incremental builds (ABI-mixed binaries)

**Pillar:** 5 (build infrastructure / verification integrity)
**Track:** A
**Status:** proposed (filed 2026-08-12 after the hygiene run burned ~3 hours
on phantom crashes caused by this)
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
