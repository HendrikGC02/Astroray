# pkg207 — Addon dispersion socket probe-name fix (Blender 5.3 round-trip)

**Pillar:** 5
**Track:** A (small local addon fix — pure Python, no engine code, no GPU, no HW).
**Status:** open (filed 2026-08-19).
**Estimated effort:** XS.
**Depends on:** nothing.

## Goal

The addon's forward-compat dispersion probe reads the WRONG socket names, so
dispersion will NOT round-trip even on the Blender 5.3 build it was written to
support. `blender_addon/__init__.py:3454-3455`:

```python
put_float('dispersion_scale', 'Dispersion Scale', 'Dispersion')
put_float('dispersion_abbe',  'Dispersion Abbe Number')
```

The merged Cycles PR (#162041, commit `f15daf81bf7c…`) named the sockets
**`Transmission Dispersion Scale`** and **`Transmission Dispersion Abbe Number`**
(source: `node_shader_bsdf_principled.cc`,
`.add_input<decl::Float>("Transmission Dispersion Scale"_ustr)`). `put_float`
does an exact `node.inputs.get(name)` match, so the current probe returns `None`
on a real 5.3 build — the comment's promise ("start round-tripping automatically
the day that PR ships") does not hold.

## Specification

1. Update the two `put_float` socket-name arguments to the **merged** names:
   `'Transmission Dispersion Scale'` and `'Transmission Dispersion Abbe Number'`.

2. **Keep the old short forms as fallbacks**, do not just replace — an
   in-development/older experimental build (or a future rename) may still use the
   short name. Probe the full merged name first, fall back to the short form.
   If `put_float`/`node.inputs.get` only accepts a single exact name, extend the
   helper minimally to try a name list (first match wins), or add a second guarded
   `put_float` call for the fallback. Keep the change surgical (CLAUDE.md §3) — do
   not refactor the wider `put_float` machinery.

3. Refresh the stale comment at `:3448-3449` to name the merged sockets and the
   merge commit, and drop the "unmerged PR" framing (it merged 2026-08-18).

## Acceptance

- [ ] With a Principled node that exposes `Transmission Dispersion Scale` /
  `Transmission Dispersion Abbe Number`, the probe reads both values into the
  material (verify headlessly by constructing a mock node whose `inputs` contains
  those named sockets — real Blender 5.3 is not installed, so a `unittest.mock` /
  fixture node with a `.get(name)` that returns the merged-named sockets is the
  acceptance harness; a fixture with the SHORT names must still round-trip via the
  fallback).
- [ ] No behavioural change on Blender 5.1/5.2 (the sockets are absent there; the
  probe returns `None` for both and the material is unaffected — assert this too).
- [ ] Diff touches only `blender_addon/__init__.py` (+ its unit test); no engine
  code, no `.pyd` rebuild, no GPU leg. CI-gate only.
- [ ] CI green on all matrix jobs (`gh run view` on HEAD).

## Non-goals

- **No dispersion feature work** — this only fixes the addon read path so the
  existing pkg187 native-Cauchy dispersion receives the two values.
- **No new UI**, no change to how the values are consumed downstream.

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`.astroray_plan/docs/reports/2026-08-19-cycles-dispersion-research.html` §6.1,
ranked recommendation #1 — "Actionable discrepancy #1"). Grounded in live code:
`blender_addon/__init__.py:3448-3455`. Open-model IMPLEMENT-tier, CI-gate only.
