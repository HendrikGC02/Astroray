# pkg105 — Blender Addon: Black-Hole Object Integration

**Pillar:** 4 (Astrophysics) + Pillar 5 (Production polish) — touches both
**Track:** A (Blender addon Python + C++ binding glue)
**Status:** done (PR #381, 2026-05-28 — r_obs_M + Kerr spin + ADAF params exposed)
**Estimated effort:** 1–2 weeks (~25–50 h)
**Depends on:** pkg40 (Kerr/Schwarzschild metric plugins, done) + pkg44 (ADAF model, done) + pkg103 wiring audit (done)

---

## Goal

**Before:** Astroray has shipped Kerr metric (pkg40), slim-disk + ADAF accretion models (pkg43, pkg44), synchrotron jet (pkg42), and `renderer.add_black_hole(pos, M, influence_radius, params)` as a Python API. The Blender addon has NO way to place or configure a black hole. Users cannot author astrophysics scenes in Blender; they must hand-build them in Python and call the engine directly. This is the gap behind owner observation 2026-05-27: "black hole Blender integration still needs to be done."

**After:** A Blender addon Black Hole object (or marker-empty + custom property panel) that:
1. Places a BH at a specific scene location.
2. Exposes the parameters of `add_black_hole` and the registered accretion models (spin, mass, influence radius, inclination, disk_outer/accretion_rate for thin disk, ADAF on/off + parameters, jet on/off + parameters) as Blender properties on that object.
3. The scene converter (`blender_module.cpp` + `blender_addon/__init__.py::convert_scene`) reads the BH object and calls `renderer.add_black_hole(...)` with the right args.
4. Survives a viewport edit + re-sync without crash, and the BH's geometric influence is visible in the viewport (preview render) without restarting the engine.

---

## Context

Why this matters and why it's separate from pkg43's existing "Blender accretion-model selector" (PR #285):

- pkg43's selector is a **dropdown on a fictional Blender-scene-level property** to pick which accretion model (Novikov-Thorne / Slim Disk / ADAF) gets applied to ANY BH the scene contains — but the scene cannot actually CONTAIN a BH from Blender because there's no BH object type. The dropdown is plumbing for a feature that has no entry point.
- The only way to render a BH today is via Python: `r.add_black_hole(...)`. The addon's `convert_scene` walks `bpy.data.objects` and translates mesh/light/camera; there's no branch for "this is a BH placeholder, emit `add_black_hole`."
- The owner reported (2026-05-27) that the reference-bank Schwarzschild + Kerr scenes had to be Python-authored because the Blender addon route was missing. The bank's `gr-schwarzschild` and `gr-kerr-94-faceon` scenes document this as a known limitation; pkg105 closes it.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/nodes/black_hole_panel.py` (or extend `nodes/__init__.py`) | Custom Blender property group + UI panel for a "Black Hole" empty/marker |
| `tests/test_addon_black_hole_object.py` | pytest using a stub or `bpy` mock: confirm a BH object in the scene triggers `add_black_hole` with the right args |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | `convert_scene` learns to recognize a BH object (by custom property tag) and call `renderer.add_black_hole`. Property update handlers re-sync without full rebuild. |
| `module/blender_module.cpp` | (Only if a new helper is needed; `add_black_hole` is already bound.) |
| `.astroray_plan/docs/STATUS.md` | Closeout note when done. |
| `.astroray_plan/docs/ROADMAP.md` | Add pkg105 to Pillar 4 timeline. |

### Key design decisions

**D1. BH representation in Blender: Empty + custom prop, NOT a mesh.**
Black holes have no geometry to render in Blender's normal sense. An Empty with custom properties + a custom UI panel matches Blender's conventions for "marker objects that the engine interprets" (similar to how lights work).

**D2. Parameter surface: subset of `add_black_hole` + accretion-model params, behind expandable sub-panels.**
Top-level always-visible: position (from object transform), mass (M_sun), influence_radius, spin. Sub-panels per emission model: thin disk (disk_outer, accretion_rate, inclination), ADAF (mdot_edd, T_e, beta_mag, etc.), jet (opening angle, intensity).

**D3. Viewport-preview policy.**
Initial scope: BH renders in F12 (offline render) but viewport preview can show a "placeholder sphere" at the BH location with size = influence_radius. Full GR-aware viewport preview is a separate package (pkg105b or later) and likely depends on pkg55-B' wavefront landing.

**D4. Round-trip with .blend importer (pkg100 path).**
A BH object embedded in a .blend should survive save/load. Since custom properties are part of standard Blender property storage, this should be automatic — but the test should cover it.

---

## Acceptance criteria

- [ ] Adding a BH object via the addon panel + rendering with F12 produces output equivalent to a Python `add_black_hole(...)` call with the same params (within MC noise / SSIM ≥ 0.95).
- [ ] Editing the spin slider in the Blender properties panel re-renders the scene with the new spin value without a full engine restart.
- [ ] BH object survives save+load of the .blend.
- [ ] `tests/test_addon_black_hole_object.py` exercises the convert path with a bpy-stubbed scene.
- [ ] `pkg104/scenes/gr-schwarzschild/` and `gr-kerr-94-faceon/` get an optional "Blender-authored" variant (Phase 2b of pkg104) that loads a .blend file containing the BH; rendering it matches the Python-authored equivalent.

---

## Non-goals

- Not a full viewport-preview GR integration. Placeholder sphere only.
- Not a multi-BH binary integrator (single BH per scene for now).
- Not a Cycles-compatible BH (Cycles doesn't have a BH primitive; Astroray-only).
- Not animatable spin/mass over time (single static frame).
- Not pkg43's accretion-model selector replacement — pkg105 plumbs the entry point pkg43 already targets.

---

## Progress

- [x] Spec drafted 2026-05-27 (this file).
- [ ] Owner approval to schedule.
- [ ] Phase 1: Empty + custom prop + always-visible params (position, mass, spin, influence).
- [ ] Phase 2: Accretion-model sub-panels (thin disk, ADAF, jet).
- [ ] Phase 3: Round-trip and re-sync test coverage.
- [ ] Phase 4: pkg104 BH-scene Blender-authored variants.

---

## Lessons

*(Fill in after the package is done.)*
