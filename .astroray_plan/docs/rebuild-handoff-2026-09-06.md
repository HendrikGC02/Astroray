# Full rebuild and next-agent handoff - 2026-09-06

## Owner milestone and package boundary

The next agent starts with pkg241 and pkg240 for **responsive camera/material
edits, reliable cancellation, and faithful mapped textures**. Use the
[ready-to-paste agent prompt](archive/next-agent-prompt-pkg241-pkg240.md).
Pkg241 owns measured viewport/cancellation behavior; pkg240 owns measured CI
throughput while preserving coverage and trust. Landed pkg230b covers bounded
affine image/program mapping. OPEN pkg242 procedural/default-coordinate parity
and OPEN pkg245 normal/bump provenance retain separate scopes. Do not redispatch
pkg230b/232/236. Pillar 4 stays PAUSED.

## Build and delivery state

Build-start source was main `f30bc5f5e47587e034623f8ea0249da6a2c7b5cd`.
Root evidence directory: `test_results/rebuild-handoff-20260906/`.
The clean all-target build exposed the standalone caller to the deleted
CUDARenderer::render API. Pkg250 repairs only that caller plus focused tests:
PR #716, source `ff2df9912ae79adc484948392091e4ef559d95cc`, merged as
`37f7343de4368ec721e10191f455315378dc5aec` at 03:05:15 UTC. Both push/PR
host and CUDA checks passed. Each host suite: **2176 passed, 283 skipped,
15 xfailed, 4 xpassed** (PR 1601.98s; push 1652.51s). The advisory reference
smoke FAILED in both runs (2/3 gates); pkg249 remains OPEN. Full CI logs are
`pkg250-ci-34006837659.log` and `pkg250-ci-34006829758.log`.
Terra independent architecture, source and completed local runtime SIGN-OFF
passed. No renderer, binding, ABI, CMake or transport algorithm changed.

| Artifact | Configuration | Actual result |
| --- | --- | --- |
| Development engine, all targets | VS2022 Release, CUDA12.8, native sm_120, OpenMP ON | Initial clean build found deleted CLI API; repaired complete ALL_BUILD PASS in 4.30s using unchanged freshly compiled CUDA library |
| CPU-only Blender addon | MinGW Release, CUDA OFF, OpenMP OFF, Python3.13 | Full clean build PASS, 116.75s; isolated Blender smoke PASS, 8.1s; host ABI canary PASS |
| CUDA Blender addon | Ninja/MSVC Release, CUDA12.8, native sm_120, OpenMP OFF, Python3.13 | Full clean build PASS, 1780.92s; isolated Blender smoke PASS, 8.4s; host ABI canary and native-arch check PASS |
| Standalone CUDA/N3 OFF | Separate VS2022 Release target, CUDA12.8/sm_120, Python/OIDN/OptiX OFF | Complete target build PASS; explicit GPU exit2/no image, auto CPU exit0/image |

The original failure remains in `engine-cuda-full-build.log`. The reviewed
pkg250 patch was applied to the named main verification checkout; complete
ALL_BUILD success is in `engine-cuda-repaired-all-targets.log`. The CUDA library
mtime/size was unchanged during the 4.30s host repair build. Actual source patch,
module/executable hashes, commands and timestamps are retained. The main build
kept its existing VS generator; addon builds retain separate OpenMP-OFF modules.
No root/test-directory native shadow was found.

Both builders' pre-staging module probes warned about missing DLL dependencies;
those probes are NOT passes. Their bundled packages subsequently passed actual
isolated Blender registration/render and host canaries. CUDA compiled features
and actual Blender GPU dispatch were independently checked, including native
sm_120 SASS with cuobjdump. Existing compiler warnings remain in full logs.
N3-off linking retained LNK4098 (LIBCMT conflict); runtime gates passed, but the
warning is not claimed resolved or suppressed.

## Artifact identities

- CPU zip: `dist/astroray-4.0.0-cpu.zip`; preserved stage `cpu-addon/` beneath
  the evidence directory. Build ID `f30bc5f+20260906T012037Z`.
- CUDA zip: **`dist/astroray-4.0.0-cuda.zip`**; preserved stage `cuda-addon/`.
  Build ID `f30bc5f+20260906T015107Z`; native SHA256
  `787ac354931940e1d1b34e2be4f2006c8ef7dad96bd368f7a9a4d3c752539151`.
  Compiled features confirm CUDA/wavefront ON, OpenMP OFF, OIDN/OptiX ON.
- Development module: `build_cuda/Release/astroray.cp313-win_amd64.pyd`;
  actual import and build ID `f30bc5f+handoff20260906` verified.
- `cpu-identity.json`, `cuda-identity.json`, `engine-module-identity.json`,
  `standalone-gpu-build-identity.json` and `n3off/pkg250-gate-identity.json`
  retain exact paths/hashes. These IDs describe the builds actually tested;
  later documentation/caller-only commits do not imply recompiled addon code.

## Actual test gates

| Gate | Actual result |
| --- | --- |
| Fresh CPU addon bindings/material/spectral suite | 143 passed, 1 skipped, 8 xfailed, 4 xpassed, 389.22s |
| Final CPU-only standalone suite | 11 passed, 6 documented CUDA-unavailable skips, 7.39s |
| CUDA/N3-on standalone, progressive viewport and wavefront-image suites | 21 passed, 1 expected GPU-available fallback skip, 8.68s |
| CUDA/N3-off standalone suite | 11 passed, 6 documented wavefront-unavailable skips, 6.75s |
| CUDA/N3-on/off host syntax | Both PASS; actual target/link/runtime evidence above is separate |
| Unsupported GPU integrator | light_tracer_caustic correctly rejected, exit2/no image |

The initial GPU run was **19 passed, 1 skipped, 1 failed**: a new exact-gray
luminance assertion made an incorrect color-space assumption. Terra traced the
existing equal-XYZ accumulation followed by XYZ-to-sRGB conversion. The corrected
same-band 900-910nm oracle requires explicit RGB output to be black outside the
CMF domain and band-radiance output to retain signal. It passes without pinning
the existing display tint; pkg251 owns that contract debt. Original failed
`gpu-focused.log`/XML and corrected `gpu-focused-final.log`/XML are both retained.
No transport change or arbitrary threshold relaxation was made for that failure.

## Visual evidence and limits

The real-Blender `coords_shared_programs` chart was rendered on the CPU-only
addon, fresh CUDA addon GPU, and Cycles at 128x128/256spp. Existing 5% RGB ROI
mean-ratio gate: CPU max deviation **1.2964%**, GPU **1.3693%**, both PASS.
Astra inspected `mapped-cpu.png`, `mapped-gpu.png`, `mapped-cycles.png`: rotated
and mirrored placements agree, with expected sampling noise and no visible
corruption. Raw `.npy` arrays are preserved; previews use the canonical sRGB
transform outside Blender because Blender lacked PIL. Actual addon/native paths
and explicit RTX5070Ti GPU dispatch are in the logs. The existing textured
Principled-to-Lambertian approximation warning remains; this is not complete
Principled texture fidelity.

Standalone CPU/GPU Cornell and material scenes are saved at 192x144/256spp,
depth8 as `standalone-{cpu,gpu}-scene{1,2}.png`. Astra inspected Cornell wall
colors, geometry and glossy/transmissive appearance: no new caller regression
was observed. The material scene's checker disappears on GPU: **that visual
parity case is NOT GREEN**. It also reproduces through the unchanged f30bc5f
binding (`checker-binding-{cpu,gpu}.npy/.png`), independently of the CLI repair.
Terra traced CPU implicit fallback UVs versus GPU sampling only real UV layers;
CPU image luminance std is 0.4182 versus GPU 0.0330. Pkg242 now carries this
concrete baseline. Do not generalize the mapped-image/Cornell results to all
procedural texture inputs.

## Installed addon versus rebuilt package

At preflight the owner's live Blender PID36532 loaded the older native module
under `%APPDATA%/Blender Foundation/Blender/5.2/extensions/user_default/astroray/`.
The owner saved/closed Blender and explicitly requested installation. The
canonical transactional installer succeeded in 5.29s; all **42 installed files**
match the verified CUDA stage, including native SHA256 `787ac354...539151`.
An actual Blender smoke imported that installed path and passed in 2.10s with
finite/nonblack output. All **429 profile files outside the addon** remained
byte-identical before/after installation and the final smoke. The earlier
471-file whole-profile check also passed before the authorized addon update.
Evidence: `addon-live-install-identity.json`, `addon-installed-smoke.log` and
`profile-final.json`. The GPU lock was released after all builds/renders. No
Blender process was left running by verification; the updated addon is ready
for the owner to reopen Blender.

## Open work and documentation

Pkg237 HDRI SSIM and pkg238 PostInit ULP remain reproduced local baseline
failures; earlier full local suites were NOT GREEN. Pkg249 retains the
informational Cornell reference-smoke failure (two gates passed, one failed).
Pkg231 owns local CUDA rebuild latency. Pkg240 has baseline measurements only;
no optimization or coverage-parity benefit has shipped.

Two newly filed OPEN scopes preserve discoveries outside the repair:
[pkg251](../packages/pkg251-spectral-band-parameter-reachability.md) for spectral
parameter/output contract and [pkg252](../packages/pkg252-cuda-caller-build-ci-coverage.md)
for measured CUDA caller/target CI coverage. Their implementation gates are
UNRUN and they do not preempt pkg241/240.

README, development/quickstart guides, navigation, live plans and relevant specs
were reconciled with the actual CUDA-default builder, Blender5.2+/Python3.13,
isolated smoke workflow and CLI. Historical performance claims remain dated.
Builder inline usage shipped in PR #715, merge `083c84b`, 02:00:23 UTC.
Executable AST was unchanged after removing docstrings; both host/CUDA CI checks
passed. PR tests: 2173 passed, 277 skipped, 15 xfailed, 4 xpassed in 1334.79s.
Its advisory reference smoke still failed; CI success does not make it pass.

Terra signed off on main-doc content and pkg251/pkg252 filing, then independently
adjudicated the luminance and checker findings. Differential source lint passed
five tools; docs lint passed three, all with zero new findings and none
unavailable/errored. PR #716 is merged after required CI passed. Installation
and profile-preservation verification are complete. This documentation closeout
records the verified handoff; its docs-only CI does not replace native gates.
