# pkg177 — DCC-integration generalization: architecture tradeoff study + owner decision record

**Pillar:** Integration Milestone (Blender/DCC integration — see ROADMAP "Integration Milestone")
**Track:** A (research/decision package — no production code; a small spike is allowed only if the study needs a measured fact)
**Status:** open — dispatchable in parallel with pkg175 (explicitly parallel-safe: touches no addon/engine code)
**Estimated effort:** S–M (the research base already exists: `.astroray_plan/docs/dcc-integration-research-2026-08.md`; this package deepens it into a decision document + records the owner's ratification)
**Depends on:** none. Cross-links: pkg176 (its Route-2 session-boundary design rule is this study's near-term consequence), pkg119 (parity measurement is per-DCC by construction — the study must say what generalizes).

## Charter

Blender is the FIRST integration target, not the only one (owner directive
2026-08-03). Other engines integrate into many DCCs via known, published
routes. This package turns the 2026-08-03 research note into a decision
document laying out the REAL tradeoff axes — per the repo design rule, NOT
an artificial N-option ballot (`design_no_forced_options`) — and gets an
owner ratification recorded, so later integration work has a charter
instead of an implicit assumption.

**The routes the study must treat honestly** (from the research note; deepen,
verify against current releases, correct if reality moved):

1. **Blender `RenderEngine` native plugin** (current path) — highest
   Blender fidelity; the ONLY route that fully serves the
   Cycles-settings-as-steering-wheel goal; per-DCC cost multiplies.
2. **Renderer-agnostic session layer + thin per-DCC adapters** (the
   V-Ray-AppSDK / Cycles `session/` shape) — the pybind surface is already
   most of this; the open question is how hard to formalize the boundary
   and when (simplicity tax: not before a second consumer).
3. **USD/Hydra render delegate (`hdAstroray`)** — the industry multi-DCC
   route (hdPrman/Arnold/V-Ray/Karma; Blender hosts delegates natively via
   `bpy.types.HydraRenderEngine`); one delegate reaches
   Houdini/Solaris/Katana/Maya/usdview/Omniverse; but the
   MaterialX/USD boundary erases Cycles-native settings/nodes (the
   steering wheel), hdCycles itself is experimental, USD is a heavy
   dependency on our MinGW/CUDA toolchain, and our spectral/GR
   differentiators have no MaterialX vocabulary.

**Tradeoff axes to make explicit** (at minimum): host fidelity vs host
count; where the material/settings translation happens and what it erases;
dependency and toolchain weight; maintenance surface per additional DCC;
which route the astro-viz audience actually needs (Houdini/Solaris is the
realistic second host; is there a real user for it yet?); what each route
demands of the engine core NOW vs later.

## Deliverables

- [ ] Decision document (extend the existing research note or a sibling
      doc) with: the axes above populated with verified facts (versions,
      links, license notes), the architect recommendation, and explicit
      falsifiable claims (e.g. "Hydra loses `scene.cycles` fidelity" —
      show the mechanism, not vibes).
- [ ] A concrete near-term consequence list for pkg176 (the session-
      boundary rule) — what the addon refactor must NOT foreclose, stated
      as at most a handful of hard rules, no speculative API design.
- [ ] **Owner decision recorded** in this spec's Status line: which route
      is charter for the milestone, and the trigger condition for
      revisiting (e.g. "first real Houdini user" or "paper needs Solaris
      renders").
- [ ] If (and only if) the owner picks a route needing new code beyond
      pkg176's discipline, file the follow-up package spec(s) — filing,
      not implementing.

## Non-goals

- No Hydra delegate implementation, no USD dependency added, no C API
  authored. This package produces a decision, not code.
- Does not block pkg175/pkg176 — they proceed on the recommendation
  (Route 1 + Route-2 discipline) and this study can only refine, not
  reverse, work already consistent with all three routes.

## Provenance

Filed by the architect 2026-08-03 under the owner's integration directive
("GENERALIZE: Blender is the first target, not the only one — research the
known solutions and lay out the real tradeoff axes"). Research base:
`.astroray_plan/docs/dcc-integration-research-2026-08.md` (grounded via
web research on Blender 5.x extension/RenderEngine state and the Hydra
delegate ecosystem, 2026-08-03).
