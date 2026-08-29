# pkg134 — Light Path Expressions (OSL `liboslexec` LPE automata port)

**Pillar:** 5 (production polish / AOV routing)
**Track:** A (host-side DFA compile + AOV routing is CPU-gated; wavefront path-state transitions verified on RTX)
**Codex-paste-ready:** no (OSL automata port + a new uint16 path-state SoA field carried through every wavefront stage + per-event transition logic — cross-cutting)
**Status:** still-open — never implemented; no LPE/light-path-expression automata in the repo, only the spec-filing PR #492.
**Estimated effort:** M–L (2–4 sessions per the research doc — OSL automata port, DFA upload, path-state field, AOV routing)
**Depends on:** **pkg130** (light groups) — pkg130's emission-mechanism group ids are the alphabet-extension labels this package's LPE grammar matches on. Composes after pkg55 Phase C (path-state field added once, to the single surviving wavefront SoA). Land order: pkg130 → pkg134.

---

## Goal

**Before:** Astroray can (after pkg130) separate contributions by emitter **group**,
but cannot select paths by their **interaction history** — "caustics only"
(`C<.D><.S>+L`), "diffuse-then-glossy", "direct vs. indirect", or black-hole
photon-ring subimages. There is no path-grammar AOV mechanism.

**After:** Port OSL's renderer-agnostic **Light Path Expression** subsystem (BSD-3,
verified): user LPEs (Heckbert `L(S|D)*E` grammar) compile **host-side** to a DFA;
each wavefront path carries one `uint16` DFA state in the SoA; every scatter /
emission event advances `state = dfa[state][event]` (one table lookup per bounce —
divergence-free); contributions at accepting states route to the mapped AOV. Two
Astroray-unique alphabet extensions: **emission-mechanism** event labels (from
pkg130's group ids) and a **photon-ring winding-number counter** (n=0/1/2 black-hole
subimages) as an extra path-state integer.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §2
(tier 2). Grammar: events `C/L/O/B`, interactions `R/T/V`, scattering modes
`D/G/S/s`, event tokens `<TypeMode'label'>`, regex operators `. [] [^] * + ? {n,m}`.

- **Host DFA compile:** port OSL `lpeparse` (parser) + `lpexp` (AST) + `automata`
  (NFA build → subset-construction to DFA) + `accum` (DFA-state-driven AOV
  accumulator). This subsystem is deliberately renderer-agnostic (no OSL shading
  dependency), so it ports as self-contained C++. Upload the DFA table to constant
  memory.
- **Path-state field:** add a `uint16` DFA state to the wavefront path-state SoA
  (`src/gpu/wavefront/wavefront_state.cu`), initialized at camera and advanced at
  each scatter/emission event in `stage_advance.cu`. Cost is one `dfa[state][event]`
  lookup per bounce.
- **AOV routing:** at accepting states, route the path contribution to the LPE's
  mapped output layer (reuse pkg130's per-layer framebuffer/EXR machinery).

**Astroray-unique alphabet (the journal angle):** (1) emission-mechanism labels —
attach pkg130's `disk_thermal` / `jet_synchrotron` / `starfield` / `envmap` ids as
LPE label tokens, so an LPE can select "lensed starlight that scattered off the
disk". (2) **Photon-ring winding number** — a trivial extra path-state integer
counting equatorial-plane crossings, giving the n=0/1/2 black-hole subimages as
separable layers. This is a path-state counter, **not** an LPE grammar feature.

---

## Implementation plan

- **A. Host LPE compiler.** Port OSL `lpeparse`/`lpexp`/`automata`/`accum` as
  self-contained C++; unit-test against OSL's `accum_test.cpp` cases; compile user
  LPE strings → DFA table.
- **B. Wavefront path-state transitions.** Add the `uint16` DFA-state SoA field;
  advance per event in the wavefront (and CPU mirror); route accepting-state
  contributions to LPE-mapped layers.
- **C. Astroray alphabet extensions.** Wire pkg130 emission-mechanism labels into the
  event alphabet; add the photon-ring winding-number counter + a canned
  "photon-ring n=0/1/2" LPE preset. Gate on a caustic LPE (`C<.D><.S>+L`) and the
  photon-ring decomposition on a black-hole scene.

---

## Acceptance criteria

- [ ] Host-side LPE parser + NFA→DFA compile ported from OSL; passes the OSL
      `accum_test` grammar cases.
- [ ] `uint16` DFA-state SoA field advanced per event on the wavefront (one lookup
      per bounce) and mirrored on CPU; CPU↔GPU wavefront-diff parity holds.
- [ ] A caustics LPE (`C<.D><.S>+L`) produces a caustics-only AOV that matches the
      photon-caustic pass qualitatively.
- [ ] Emission-mechanism labels (from pkg130) usable as LPE label tokens.
- [ ] Photon-ring winding-number counter yields separable n=0/1/2 subimage layers on
      a black-hole reference scene.
- [ ] Default render (no LPEs defined) is unchanged and pays no measurable per-bounce
      cost beyond the single state lookup.

---

## Non-goals

- **Not the membership light-group tier.** That is pkg130 (its prerequisite); pkg134
  is the path-grammar tier that consumes pkg130's ids.
- **Not OSL shading.** Only the LPE subsystem (parse/automata/accum) is ported — no
  OSL shader execution.
- **Not appleseed-style full path recording.** Per-pixel light-path inspection
  (appleseed `lightpathstream`) is a separate debugging feature — reference only.

---

## Algorithm sourcing (CLAUDE.md §6)

- **OpenShadingLanguage**
  `github.com/AcademySoftwareFoundation/OpenShadingLanguage` — **BSD-3-Clause
  (verified — `LICENSE.md`)**. `src/liboslexec/lpeparse.{cpp,h}` (~464 lines),
  `lpexp.{cpp,h}` (~220), `automata.{cpp,h}` (NFA→DFA subset construction, ~661),
  `accum.{cpp,h}` (~244), test `accum_test.cpp`. Renderer-agnostic by design.
- **Heckbert**, "Adaptive Radiosity Textures for Bidirectional Ray Tracing",
  SIGGRAPH 1990, DOI 10.1145/97879.97895 — the `L(S|D)*E` path-regex notation.
- **OSL Light Path Expressions** wiki (AcademySoftwareFoundation/OpenShadingLanguage)
  — the grammar spec. Arnold / RenderMan document the same grammar (proprietary —
  **semantics reference only**).
- **appleseed** `github.com/appleseedhq/appleseed` — MIT (*verify-at-port*).
  `lightpathstream.{cpp,h}` — complementary path recording, **reference only**.
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §2
  (tier 2) + adoption rank 6.

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §2, adoption rank 6: "after
light groups, before article figures"). Owner goal: path-grammar AOV separation
(caustics-only, direct/indirect) plus the Astroray-unique photon-ring subimage
decomposition for the journal.

---

## Progress

- [ ] A — host LPE compiler ported (parse/automata/accum); OSL test cases pass.
- [ ] B — wavefront `uint16` DFA-state field + per-event transitions + AOV routing.
- [ ] C — emission-mechanism labels + photon-ring winding-number counter + presets.

---

## Lessons

*(Fill in after the package is done.)*
