# Pillar 5: Production Polish

**Status:** Ongoing
**Depends on:** Pillars 1, 3
**Tracks:** A (core UX), B (self-contained), D (docs/tests), E (coordination)
**Duration:** ongoing, opportunistic

## Scope

This pillar is a bucket, not a sequence. Work packages run in the
background on tracks B (cloud Copilot for self-contained features) and
D (Ralph loop for test coverage and docs). Pick from it when other
tracks are blocked or during wind-down of a major pillar.

## Work categories

### 5.1 Multi-GPU scaling

For the eventual 4× RTX 6000 target. Deferred until the single-GPU CUDA
path has the full feature set.

- Tile-based distribution with work-stealing (research report §5).
- Each GPU gets a full scene copy (48 GB each, plenty for most scenes).
- Adaptive tile sizing for black-hole-style non-uniform cost.
- Host-side combiner produces the final image.

Deferred until Pillar 4 ships and a second machine is online. Packages
created then.

### 5.2 Denoiser improvements

OIDN 2.x is already integrated. When OIDN 3.0 lands:
- Temporal denoising for animation
- AOV denoising (separate passes each get denoised with guidance)
- Optional per-wavelength spectral denoising if OIDN exposes it

Future package name TBD (the old placeholder `pkg50-oidn3-upgrade.md`
collided with the Pillar 4 package sequence and should not be reused).

### 5.3 OptiX denoiser option

Alternative to OIDN on NVIDIA hardware. Faster (100–200 ms per frame),
supports temporal denoising. Plugin-worthy because:
- Users with NVIDIA hardware want the option
- Does not replace OIDN (cross-platform)

Plugin: `plugins/passes/optix_denoiser.cpp`. Cloud-agent feasible.
Future package name TBD (do not reuse the old `pkg51-*` placeholder;
`pkg51` now belongs to synthetic telescope observations).

### 5.4 Output formats

Current output: PNG, PPM. Add:
- **OpenEXR** (HDR, multi-layer for AOVs) — essential for compositing
- JPEG XL (nice-to-have, future)
- Multi-pass EXR matching Cycles output layout

OpenEXR is non-negotiable; the rest are nice-to-have. Future package name
TBD; the old `pkg52-openexr-output.md` placeholder is obsolete because
`pkg52` now tracks the persistent viewport session.

### 5.5 Blender viewport rendering

Astroray now has a viewport preview foundation. `pkg52` added a persistent
viewport renderer, camera-state hashing, progressive preview accumulation, and
CAMERA-view zoom/pan projection so viewport navigation changes re-render and
converge toward the preview sample target. `pkg62` added a viewport pass
selector and optional viewport OIDN toggle.

- Triggered by Blender's `view_draw()` callback.
- Progressive rendering: start with 1 spp, accumulate as user stops
  moving.
- Integrates naturally with ReSTIR DI (low-spp, low-noise).

Current package: `pkg52-persistent-viewport-session.md`.

### 5.6 Motion blur (camera + object)

Standard stochastic temporal sampling: each ray samples a time in
[shutter_open, shutter_close]; camera + object transforms interpolated.

- Camera motion: interpolate camera matrix per ray.
- Object motion: store two transforms, interpolate per ray.
- Shutter curve: box, triangle, user-defined.

Future package name TBD; `pkg54` now tracks GPU multi-wavelength rendering.

### 5.7 Hair/curves rendering

Cycles has native hair BSDF + curve primitives. For Astroray the MVP
is converting curves to small triangles at export time — visually
similar, much simpler than native curve intersection. Native curves
can come later as a plugin.

Package `pkg55-curve-primitives.md`.

### 5.8 Documentation

Existing `docs/` is mostly agent-context. Users need:
- Proper user guide (how to use Astroray from Blender)
- Plugin authoring guide (how to add a material, shape, integrator)
- Rendered gallery with scene files
- Scientific accuracy notes (what's physically correct vs approximated)

Future package names TBD. The old `pkg61-plugin-guide.md` and
`pkg62-gallery.md` placeholders collided with the Cycles-parity series.

### 5.9 Example scenes

A `samples/scenes/` directory with:
- Cornell box (exists)
- Simple spectral dispersion prism
- HII region visualization
- Kerr black hole with relativistic jet
- Multi-material production scene
- Neutron star magnetosphere

Each scene = a .blend file + a Python script that reproduces it from
scratch. Package `pkg63-example-scenes.md`.

### 5.10 Test coverage

Current: 435 collected tests as of 2026-05-09 on the Codex workstation
(`pytest --collect-only -q`). Target: keep expanding coverage
around every plugin and every integrator. Continuous Ralph-loop work.

Specific gaps:
- GPU vs CPU equivalence for every material and integrator
- Spectral regression/reference checks for every material under a white
  illuminant; the legacy RGB renderer path was deleted in pkg14
- Multi-GPU correctness (when we have it)
- Plugin registration correctness (regex-scan that every `.cpp` under
  `plugins/` has an `ASTRORAY_REGISTER_*` call)
- Render-output triage for suspicious PNGs before promoting observations
  into hard assertions

Future package name TBD; `pkg64` now tracks spectral caustics research.

## Tracks

- **Track B (Copilot cloud)** gets self-contained items: OpenEXR,
  OptiX denoiser, motion blur, hair, example scenes.
- **Track D (Ralph loop)** gets test expansion, doc sweeps, lint
  cleanup, CHANGELOG updates.
- **Track A (Claude Code)** gets the big refactors: viewport render,
  multi-GPU.

## Acceptance criteria

No concrete "done" — ongoing polish. Rough bar per item:

- [ ] Multi-GPU renders produce identical results to single-GPU within
      noise.
- [ ] OIDN 3 upgrade closes feature parity with OptiX denoiser.
- [ ] OpenEXR output passes a round-trip integrity test.
- [ ] Blender viewport render responds within 100 ms of scene edits.
- [ ] User guide complete enough that a new user can install Astroray
      and render a working scene without reading the source.
- [ ] Plugin guide includes a minimum working example of each plugin
      category.
