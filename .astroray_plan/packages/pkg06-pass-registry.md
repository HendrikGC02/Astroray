# pkg06 — Pass registry

**Pillar:** 1  
**Track:** A  
**Status:** open  
**Estimated effort:** 1 session (~3 h)  
**Depends on:** pkg05

---

## Goal

Before: the pass/AOV buffer system is ad-hoc — OIDN is wired in as a
special case in the render loop and individual passes (depth, normal,
albedo) are hardcoded. After: `include/astroray/pass.h` defines a
`Pass` base class; each pass lives in `plugins/passes/` and registers
via `ASTRORAY_REGISTER_PASS`. The OIDN denoiser becomes
`plugins/passes/oidn_denoiser.cpp`. `Renderer::render` calls
`pass->execute(framebuffer)` for each active pass after path tracing
is done. New passes (OptiX denoiser, spectral AOVs) drop in as single
files.

This closes out Pillar 1. After this package the registry is
complete.

---

## Context

Passes are post-processing steps that read and/or write to named
buffers in the framebuffer. They run sequentially after the
integrator. The existing OIDN integration is the motivating example
— right now adding OIDN required editing the core render loop. As a
plugin it is trivially optional and replaceable.

The `Pass` interface is simpler than `Integrator` — it does not need
per-frame setup or `sample()`. It just takes a framebuffer and
transforms it.

---

## Reference

- Design doc: `docs/plugin-architecture.md §Migration order` (step 6)
- Production polish context: `docs/production.md §5.2, §5.3`
- Current OIDN integration: search `src/renderer.cpp` for `oidn`

---

## Prerequisites

- [ ] pkg05 is done: `Integrator` interface exists, path tracer is a
      plugin.
- [ ] All 66+ existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/pass.h` | `Pass` base class and `Framebuffer` forward declaration |
| `plugins/passes/oidn_denoiser.cpp` | OIDN denoiser as a pass plugin |
| `plugins/passes/depth_aov.cpp` | Depth buffer AOV pass |
| `plugins/passes/normal_aov.cpp` | Normal buffer AOV pass |
| `plugins/passes/albedo_aov.cpp` | Albedo buffer AOV pass |
| `tests/test_pass_plugins.py` | Tests: register, list names, execute on a dummy framebuffer |

### Files to modify

| File | What changes |
|---|---|
| `src/renderer.cpp` | Replace ad-hoc OIDN call + hardcoded AOV passes with a `vector<shared_ptr<Pass>>` loop |
| `src/renderer.cpp` | `PyRenderer` exposes `add_pass(name)` and `clear_passes()` |
| `blender_addon/__init__.py` | Denoising checkbox becomes `add_pass("oidn_denoiser")` |

### Pass base class

```cpp
// include/astroray/pass.h
#pragma once
#include "astroray/param_dict.h"

class Framebuffer;

class Pass {
public:
    virtual ~Pass() = default;

    // Called once after all pixels are accumulated. Reads and/or
    // writes named buffers in fb.
    virtual void execute(Framebuffer& fb) = 0;

    // Display name for Blender UI.
    virtual std::string name() const = 0;
};
```

No `beginFrame`/`endFrame` on passes — they are post-process only.
If a pass needs per-frame data (e.g., motion vectors), it reads them
from the framebuffer as a named buffer written during integration.

### Framebuffer

`Framebuffer` must expose at minimum:

```cpp
class Framebuffer {
public:
    // Named floating-point buffer access.
    float*       buffer(const std::string& name);       // write
    const float* buffer(const std::string& name) const; // read
    bool         hasBuffer(const std::string& name) const;
    int width() const;
    int height() const;
};
```

If `Framebuffer` already exists in `raytracer.h` with a different
interface, extend it rather than replacing it. If it does not exist as
a separate class, extract the relevant state from `Renderer` into one.

### OIDN denoiser plugin

```cpp
class OIDNDenoiser : public Pass {
public:
    explicit OIDNDenoiser(const ParamDict& p)
        : quality_(p.getString("quality", "high")) {}

    void execute(Framebuffer& fb) override;
    std::string name() const override { return "OIDN Denoiser"; }

private:
    std::string quality_;
};

ASTRORAY_REGISTER_PASS("oidn_denoiser", OIDNDenoiser)
```

`execute()` calls the existing OIDN API on `fb.buffer("color")` using
`fb.buffer("albedo")` and `fb.buffer("normal")` as auxiliary buffers
if available. If those buffers are absent, runs colour-only denoising.

### Renderer pass loop

```cpp
// After all pixels accumulated:
for (auto& pass : passes_) {
    pass->execute(framebuffer_);
}
```

Default passes for a new render: none. `PyRenderer::add_pass("oidn_denoiser")`
is how Python/Blender enables denoising.

---

## Acceptance criteria

- [ ] `include/astroray/pass.h` exists with the `Pass` interface.
- [ ] Five plugin files exist in `plugins/passes/`, each with one
      `ASTRORAY_REGISTER_PASS` call.
- [ ] OIDN denoising still works end-to-end: render a scene with OIDN
      enabled via `add_pass("oidn_denoiser")`, confirm visual output is
      denoised.
- [ ] `tests/test_pass_plugins.py` passes: list registered pass names,
      construct a dummy pass, execute on a blank framebuffer without
      crash.
- [ ] All 66+ existing tests pass.
- [ ] No hardcoded OIDN call remains in `Renderer::render`.
- [ ] A future pass (e.g., OptiX denoiser, bloom) can be added by
      creating one file in `plugins/passes/`.

---

## Non-goals

- Do not implement the OptiX denoiser. It is `pkg51` in Pillar 5.
- Do not implement spectral AOV passes. Those are Pillar 2 work.
- Do not add temporal accumulation or motion-vector passes. Pillar 5.
- Do not add OpenEXR output here. That is `pkg52`.

---

## Progress

- [ ] Write `include/astroray/pass.h`
- [ ] Extend/create `Framebuffer` with named buffer API
- [ ] Create `plugins/passes/oidn_denoiser.cpp`
- [ ] Create depth, normal, albedo AOV passes
- [ ] Update `Renderer::render` pass loop
- [ ] Add `PyRenderer::add_pass` and `clear_passes`
- [ ] Update Blender addon
- [ ] Write `tests/test_pass_plugins.py`
- [ ] OIDN end-to-end test
- [ ] Full test suite green

---

## Lessons

*(Fill in after done.)*
