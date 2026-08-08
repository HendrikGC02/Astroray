# pkg178 — Native Cycles Principled BSDF ("principled" material): faithful port incl. Thin Film + Thin Wall

**Pillar:** 2 (materials) + Integration Milestone (it exists FOR Blender parity)
**Track:** A (core BSDF + GPU closure work + RTX-verified Cycles parity — last-line-of-defense judgment; bounded sub-tasks delegated per the cost-routing policy)
**Status:** in progress — Stage 0 + Stage 1 (CPU core-lobe scaffold) done pending review (PR #566, 2026-08-08; CPU furnace Lambert 0.991 / EON 0.988 / metallic 0.930–0.939 / glass 0.951–0.990, chi² 14/14 clean lobes + glass-chi² xfail matching disney; GPU/parity DEFERRED to lead). Stage 2 (GPU closure-graph twin of the core lobes) DRAFTED (PR #567, 2026-08-08 — monolithic GCLOSURE_PRINCIPLED closure + on-device gpu_principled_* mirror; closure cap stays 8, no new GMaterialType; CUDA build + cuobjdump REG/STACK + GPU parity/furnace + non-principled perf gate DEFERRED to the building lead). Stages 3–5 gated on the prior stage's acceptance. Stage 3 (advanced layers) IN PROGRESS on branch `pkg178-stage3` (2026-08-09): Coat (GGX dielectric + coat_ior + coat_tint Beer absorption + directional-albedo layering), Sheen (Zeltner 2022 LTC microfiber, verbatim Apache-2.0 32×32 table `include/astroray/sheen_ltc_table.h`), approximate Subsurface (D2=a, diffusion-style Lambert stand-in + random-walk seam to bssrdf_random_walk.h), and Emission-inside-node — all implemented CPU + GPU-twin. CPU gates GREEN: 13/13 furnace/emission/coat-tint/registry (test_principled_bsdf.py) + 29 passed / 1 known-glass-xfail chi² incl. 5 new Stage-3 sampler gates (coat/sheen/subsurface). Enabling binding fix in module/blender_module.cpp::createMaterial (list→Vec3 params were silently dropped — blocked coat_tint/sheen_tint/emission_color AND Stage-1 specular_tint). DEFERRED TO LEAD: CUDA build + cuobjdump REG/STACK (kMaxPrincipledLobes 4→7 grows on-stack live state), GPU furnace/parity per lobe, on-RTX render verify. SURFACED FORKS (spec doesn't pre-decide): Anisotropy (faithful aniso GGX requires replacing the merged/validated isotropic Smith-G — re-opens Stage-1/2 byte-twin acceptance) and Alpha transparent lobe (entangled with the shared one-sample-MIS/delta-glass W-normalization). GPU emission needs scene_upload GAreaLight extraction to learn the closure-graph path
**Estimated effort:** XL, staged across multiple rounds (each stage is its own PR set)
**Depends on / composes with:** `disney.cpp` (the closest analog and the thing this eventually supersedes in the addon path — NOT deleted), `energy_compensation.h` (pkg60/151/160/163 Cycles-table lineage — reuse, do not fork), pkg163 spectral per-λ discipline, pkg149 VNDF, pkg176 (native settings/steering-wheel — Stage 5 rides its translation layer), pkg119-B differential harness (PR #550) + pkg104 reference bank + pkg71 cycles-parity benches (verification layer), pkg129-narrowed (rough-metal live-Cycles A/B composes with Stage 1), pkg174 (register-pressure ceiling — Stage 2's hard constraint; its per-material-kernel-dispatch DESIGN doc `.astroray_plan/docs/pkg174-per-material-kernel-dispatch-design.md` is Stage 2's candidate vehicle), **pkg128 (thin-film iridescence — pre-existing open spec: Stage 4 adopts its per-λ Belcour-Barla design and builds the shared thin-film Fresnel utility; pkg128's residual charter narrows to standalone Glass/Metallic nodes + showcase, riding that utility)**.
**Research note (read first):** `.astroray_plan/docs/cycles-principled-port-research-2026-08.md` — reference pin (Cycles main / Blender 5.2-era), full parameter + closure-stack breakdown, Astroray extension-point analysis, swarm assessment, citations.

## Goal (owner request, 2026-08-08 — provenance)

*"A 'copy' of the Principled BSDF that Cycles has as its primary shader,
available natively in Astroray. [...] because they [Principled and Disney]
are fundamentally different they will never quite match. For true parity
with Cycles, a faithful Principled BSDF port is the way to go — the LATEST
updated version that includes the thin translucent / thin-film material."*

Deliverable: a new `"principled"` material plugin whose closure stack,
layering math, Fresnel models, and energy compensation mirror Cycles main
(Blender 5.2-era) — Base/Metallic/Roughness, IOR-based Specular,
Transmission, Coat (ior+tint), Sheen (LTC microfiber), EON diffuse
roughness, Emission/Alpha, Anisotropy, **Thin Film iridescence**
(dielectric 4.2 + conductor 5.0, Belcour-Barla) and **Thin Wall**
translucency (5.2) — CPU + GPU, driven from the Blender addon in place of
the current Principled→Disney approximation (behind a flag first).
Subsurface is in scope with an explicit approximation decision (D2 below).

**Architect's framing:** this is the right call, not just transcription —
the Disney↔Principled mismatch is structural (layering weights, Fresnel
models, coat absorption, missing lobes), so per-bug parity patches on
Disney converge slowly. A faithful port with Cycles as reference kills the
whole class. The plugin architecture DOES make the CPU side clean; the GPU
closure layer is the honest cost (core edits + register-pressure risk —
see Feasibility).

## Reference & license (CLAUDE.md §6 — no invention)

Canonical structure: Cycles `src/kernel/svm/closure.h`
(`CLOSURE_BSDF_PRINCIPLED_ID` — closure assembly + `closure_layering_weight`
chain) and `src/kernel/closure/{bsdf_microfacet,bsdf_util,bsdf_sheen,
bsdf_oren_nayar,bssrdf}.h` (Apache-2.0 / BSD-3-Clause — compatible; cite
per-function in code exactly as `disney.cpp`/`energy_compensation.h`
already do). Papers: Belcour-Barla 2017 (thin film), Zeltner/Burley/Chiang
2022 (sheen LTC), Kulla & Conty 2017 (multiscatter), OpenPBR/EON (diffuse
roughness). Full list in the research note. **Borrow Cycles' math verbatim
wherever possible; every non-trivial formula carries a citation.**

## Staged specification

**Stage 0 — closure/parameter mapping table (blocking, cheap, owner-review
artifact — pkg176 Stage-0 discipline).** A checked-in table
`docs/blender_parity/pkg178_stage0_closure_map.md` + machine-readable twin:
every Cycles Principled input and every closure in the stack → its Astroray
realization — `DIRECT` (existing closure/table reused), `NEW-CLOSURE`
(exact port), `APPROXIMATED` (state the delta + the gate band it implies),
or `DEFERRED` (with owning follow-up). Includes the lobe-interface contract
the Stage-1 scaffold will expose (the seam the parallel lobe agents code
against) and the per-lobe acceptance-gate matrix. No silent mapping
decisions; the table encodes owner decisions D1–D3.

**Stage 1 — CPU core lobes (`plugins/materials/principled.cpp`).**
Scaffold: ParamDict surface (Cycles socket names), closure-stack assembly
in Cycles' order, `closure_layering_weight` chain, coat/metallic/
transmission weight attenuation, one-sample-MIS lobe selection with
matched eval/pdf normalization (the pkg170 lesson, in from day one).
Lobes: diffuse (Lambert + EON at `diffuse_roughness>0`), specular GGX with
generalized-Schlick Fresnel (`specular_ior_level`/`specular_tint`),
metallic F82-tint conductor, transmission rough glass — all reusing
`energy_compensation.h` tables and VNDF sampling. **Spectrally NATIVE
from day one**: `evalSpectral` (the interface's one pure virtual) and
`sampleSpectral` evaluate per-λ; do NOT copy Disney's
upsample-the-RGB-eval shortcut (`disney.cpp:700-706` — the pkg118/163/168
bug-class source; upsample reflectance colours only, scalars per-λ).
Registration `ASTRORAY_REGISTER_MATERIAL("principled", ...)`; zero core
edits expected on this stage (CMake auto-globs plugins; add the name to
`tests/test_material_plugins.py:20`). Binding gotcha: `createMaterial`
swallows ctor exceptions into a silent legacy fallback — a
registry-name-resolves test is mandatory.

**Stage 2 — GPU twin (closure-graph extension).** Lower via
`GMAT_CLOSURE_GRAPH` (the `scene_upload.cu:108-148` preferred path), NOT a
new `GMaterialType` — the enum route carries known silent traps
(`G_WF_NUM_MAT_TYPES=7` clamp at `stage_advance.cu:1034-1036`, duplicated
at `gpu_wavefront_snapshot.cu:1412`; `photon_caustic.cu:116` transmissive
list). Extend `MaterialClosureType`/`GMaterialClosure` (+ params),
`scene_upload.cu`, and `gpu_materials.h` eval/sample/pdf/spectral for the
Stage-1 lobe set; closure caps (`material_closure.h:40` +
`G_MAX_MATERIAL_CLOSURES`) 8→10 in lockstep if the audit confirms need.
**Register-pressure protocol is part of acceptance:** `cuobjdump`
per-kernel REG **and STACK** before/after (new arms inline into
`gpu_material_sample_spectral` and grow spill/STACK, not REG — a REG-only
check is blind); wavefront perf gate unchanged on non-principled scenes
(hard); principled scenes get their own measured budget. Stage 2 opens
with a sizing decision: absorb the closures into the existing bucketed
shade kernel vs land pkg174's designed `template<int MatType>` per-bucket
dispatch as the isolation vehicle; if neither fits without re-spending
pkg174's recovered ceiling, that fork goes to the owner (D4), never
silently.

**Stage 3 — advanced layers.** Coat (GGX + `coat_ior`, `coat_tint` Beer
absorption `tint^(1/cosθ_refracted)`, `coat_normal_offset`); Sheen LTC
(port Cycles' LTC table — table-shipping precedent: `gpu_ggx_tables.cu`);
anisotropy + rotation/tangent; emission + alpha inside the node (retiring
the addon's promote-to-light heuristic for the flagged path); subsurface
per decision D2. CPU+GPU per lobe (each lobe lands with both legs + its
parity gate; Stage-2's register protocol applies to every GPU merge).

**Stage 4 — Thin Film + Thin Wall.** Thin film: build the Belcour-Barla
Airy-reflectance Fresnel layer ONCE as a shared utility **per pkg128's
pre-existing design** — per sampled λ on the spectral core (no RGB
sensitivity fit needed there; simpler than Cycles' own path), with the RGB
legs mirroring Cycles' CIE-sensitivity-LUT per-channel evaluation for
like-for-like parity gates. Apply to the specular/transmission dielectric
closures AND the conductor closure (5.0 semantics), with backface film-IOR
adjustment. pkg128's residual charter (standalone Glass/Metallic nodes +
spectral showcase) rides the same utility — coordinate, don't duplicate.
Thin wall: combined-R+T thin-glass closure (seed from existing
`thin_glass.cpp` + `MaterialClosureType::ThinGlass`, reconciled against
Cycles `bsdf_thin_glass_setup`) + thin-subsurface (diffuse+translucent).
Oracle needs Blender 5.2 (D1).

**Stage 5 — addon switch (flag, not replace).** Route
`ShaderNodeBsdfPrincipled` → `'principled'` behind an addon option
(default OFF until the Stage-5 parity matrix is green; flip-default is an
owner sign-off). **BOTH translation paths switch together** via one
flag-aware helper replacing the three `'disney'` literals: the live
spec-based path (`_principled_shader_spec:3055` /
`_create_material_from_shader_spec:3237,:3241`) and the semi-orphaned
`convert_principled_bsdf_v2:3437`. Full socket map incl. renamed-input
fallbacks; alpha routes through a real transparent lobe on the flagged
path (retiring the `transmission=max(transmission,1-alpha)` conflation —
the convicted BSDF_TRANSPARENT bug family); `shader_blending.py` learns
the new spec kind; Disney path preserved byte-identical as fallback.
Per-render one-line report of any still-approximated socket (pkg119-C
policy). `coverage_matrix.json` cells for newly-honoured sockets flip
DROPPED-SILENT→SUPPORTED so the pkg119-B harness picks them up; the A/B is
one harness sweep flag-off vs flag-on, diffing `triage_report.json`.

## Verification plan (every stage; Cycles is the oracle)

- **Feature-matrix image-plane parity** via the pkg119-B differential
  harness + pkg104 reference-bank metrics: one scene pair per feature axis
  (metallic sweep, roughness sweep, IOR/specular level, transmission,
  coat w/ tint, sheen, diffuse roughness, anisotropy, thin-film thickness
  sweep 100–3000nm × film IOR, thin-wall glass + translucent, alpha,
  emission) + curated composites. **Linear output, floor AND ceiling
  bands (pkg166), per-channel mean-ratio gates not SSIM (independent RNG
  streams)** — target band `[0.95,1.05]` per lit region, documented
  exceptions only via the Stage-0 `APPROXIMATED` table.
- **Furnace/energy conservation** per lobe and stacked, CPU+GPU, linear
  with upper bounds (energy gain must be detectable).
- **Sampler correctness:** chi² (pkg121 harness) for each new sampled lobe.
- **CPU↔GPU parity** per lobe on landing (the pkg119b runbook build).
- **Perf:** wavefront gate green on non-principled scenes at every GPU
  merge; `cuobjdump` reg/spill deltas recorded in each PR.
- Render-level suites, not just consistency gates (memory
  `pr-named-tests-insufficient`); implementer test lists are a floor.

## Acceptance (package-level)

- [ ] Stage-0 table checked in + owner-ratified (D1–D3 encoded).
- [ ] `"principled"` renders the full feature matrix within parity bands
      vs Cycles main on BOTH legs (CPU + GPU wavefront), linear
      floor+ceiling, on RTX hardware — not "it compiles".
- [ ] Thin Film: hue trajectory vs thickness sweep matches Cycles within
      the Stage-0-declared band (visual + per-channel ratio); conductor
      + dielectric both covered. Thin Wall: paper/leaf/window-sheet trio
      matches Blender 5.2 Cycles.
- [ ] Addon flag routes Principled nodes to the native material; Disney
      path intact; zero silently-dropped sockets on the flagged path
      (report line per pkg119-C).
- [ ] No wavefront perf regression on non-principled scenes; register
      report attached to every GPU-stage PR.
- [ ] Every ported formula cites its Cycles file/function or paper.

## Non-goals

- Deleting/deprecating `disney.cpp` (default flip is a later owner call).
- Hair/toon/ray-portal/volume closures; OSL.
- Full random-walk BSSRDF parity if D2 selects the approximation path
  (then a named follow-up owns it).
- The textured-base-color→lambertian downgrade wart
  (`__init__.py:3425`) — adjacent, surfaced for a follow-up package; the
  native material SHOULD accept a base-color texture but the socket→
  texture plumbing beyond what Disney's path has today is not this
  package's scope.
- Matching Cycles' internal RNG/noise (expectation parity only).

## Owner decisions needed (blocking the stages named)

- **D1 (Stage 4):** install Blender 5.2 LTS alongside 5.1 as the parity
  oracle (5.1 lacks Thin Wall; 5.0+ needed for conductor thin film).
  Recommended: yes, keep 5.1 for existing refbank baselines until
  re-blessed.
- **D2 (Stage 3):** subsurface scope — (a) approximate SSS (existing
  diffusion-style plugin lineage, wider declared band vs Cycles
  random-walk) with full random-walk BSSRDF as a follow-up package, or
  (b) full random-walk in-scope now (adds a volume-walk subsystem to both
  integrator legs; significant scope growth). Architect recommends (a).
  **OWNER DECISION (2026-08-08): (a)+parallel** — ship Principled parity with
  approximate SSS now while a parallel agent builds full random-walk BSSRDF;
  converge when it lands.
  **Parallel-track update (2026-08-08):** the full random-walk BSSRDF
  follow-up is prototyped on branch `bssrdf-random-walk-cpu` (PR #565, MERGED)
  — a CPU, transport-correct random walk (Cycles parameter mapping +
  channel-MIS walk, verified furnace-clean 1.0000) with a clean
  geometry-agnostic interface (`include/astroray/bssrdf_random_walk.h`) Stage 3
  can adopt when D2 converges. Key seam: it is NOT a `Material::eval` closure —
  the integrator needs an "intersect within this object only" query. Research +
  interface + integration seam:
  `.astroray_plan/docs/bssrdf-random-walk-research.md`. Dwivedi zero-variance
  guiding partially prototyped (gray-valid; full per-channel joint scheme
  deferred). GPU port DEFERRED.
- **D3 (Stage 5):** confirm flag-first (default OFF) rollout, default
  flip only after the parity matrix is green. Architect recommends yes.
- **D4 (Stage 2, conditional):** IF the new closures cannot fit the
  existing shade kernels' register budget even bucketed, the
  ceiling/bucketing tradeoff comes back as a fork — not decided silently.

## Feasibility & decomposition (summary; full analysis in research note §2–3)

CPU: clean plugin add (new file + macro, zero core edits). GPU: core edits
to `material_closure.h`/`gpu_types.h`/`gpu_materials.h`/`scene_upload.cu`
are unavoidable (closure enum is not pluggable) — contained but shared, and
carry the register-pressure risk above. Swarm: serial spine (Stage 0 table
+ Stage 1 scaffold) THEN 3–4 parallel lobe implementers (metal/transmission/
coat/sheen/EON/thin-film as independent units against the scaffold's lobe
contract) + delegate-tier grunt (table conversion, scene-pair generation);
all GPU merges serialize through the building/verifying lead (subagents
cannot build CUDA on this machine). A "large swarm" is not realistic; a
disciplined 4–6-agent pipeline is.

## Provenance

Filed by the architect 2026-08-08 from the owner's verbatim request (native
Cycles Principled copy, latest version incl. thin translucent/thin film).
Research note: `.astroray_plan/docs/cycles-principled-port-research-2026-08.md`.
