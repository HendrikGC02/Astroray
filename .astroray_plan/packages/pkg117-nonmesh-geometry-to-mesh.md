# pkg117 — Render non-MESH geometry (curve/text/metaball/surface) via evaluated `to_mesh()`

**Pillar:** 5 (addon) + geometry
**Track:** A
**Codex-paste-ready:** no (addon change + RTX visual verify)
**Status:** open — proposed 2026-05-30.
**Depends on:** none. Complements pkg112 (reuses the triangle-upload path).
**Estimated effort:** S–M

---

## Goal

**Before:** `convert_objects` skips everything that isn't a mesh —
`if obj.type != 'MESH': continue` (`blender_addon/__init__.py:3431`). Curves,
text, metaballs, and surface objects — which Blender evaluates to renderable
geometry and shows in the viewport — **silently don't render**. Cycles and EEVEE
render them.

**After:** For evaluated objects that can produce a mesh, `convert_objects`
obtains a temporary mesh via the evaluated object's `to_mesh()`, triangulates and
uploads it like a mesh, then frees it with `to_mesh_clear()`. Curves/text/
metaball/surface render and match the viewport; plain meshes are unchanged.

---

## References

### Internal
- `blender_addon/__init__.py:3355-3434` — the `convert_objects` instance loop and
  the `obj.type != 'MESH'` gate at `:3431`. The existing per-tri upload (or the
  pkg112 bulk path) is reused for the produced mesh.

### External
- Blender `bpy.types.Object.to_mesh()` / `to_mesh_clear()` and the requirement
  that the object be **evaluated** (from the depsgraph) for modifiers/curve
  resolution to apply (docs.blender.org).
- Cycles `intern/cycles/blender/mesh.cpp` `BlenderSync::sync_mesh` uses
  `b_ob.to_mesh()` for non-mesh types (Apache-2.0) — the reference behavior.

CLAUDE.md §6: N/A (Blender API usage, no novel algorithm).

---

## Approach

Replace the hard `continue` with:

- `MESH` → `mesh = obj.data` (unchanged).
- `CURVE`, `SURFACE`, `FONT`, `META` → `mesh = obj.to_mesh()` on the
  **evaluated** object; guard `None`; reuse the triangle upload; `finally:
  obj.to_mesh_clear()`.

Notes: objects in `depsgraph.object_instances` are already evaluated. Metaballs
polygonize only on the evaluated **basis** object — the non-basis members return
`None` from `to_mesh()`; skip those gracefully.

---

## Acceptance criteria

- [ ] A scene with a beveled curve, a text object, and a metaball renders
      non-empty and matches the viewport (RTX `/verify`, paired stills).
- [ ] Plain-mesh scenes are **pixel-identical** to before (no regression).
- [ ] Stub test asserts a `CURVE` object routes through `to_mesh()` (mockable
      via the existing addon stub pattern), and `to_mesh_clear()` is called.

## Hard non-goals

- Not hair/curves-as-strands (separate). Not volume objects. Not grease pencil.
  Not particle systems. Just static `to_mesh()`-able object types.

---

## Provenance

Blender-integration parity report 2026-05-30, rabbit-hole #1; owner: *"write the
spec for it."*
