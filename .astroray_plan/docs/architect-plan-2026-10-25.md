# Architect plan 2026-10-25: Stage 0 closeout + the Spectra competitive read

In-session architect round (Fable 5.1 lead; owner 2026-10-24 "do an architect round with Fable"). Previous plan:
`architect-plan-2026-10-18.md`. Inputs: `research/spectra-website-2026-10-25.md`,
`research/spectra-blenderartists-thread-2026-10-25.md`, `research/spectra-web-and-comparables-2026-10-25.md`,
`rendering-advances-research-2026-10.md` (candidate table), `stage0-gate-scoring-2026-10-18.md`.

## 1. State (main `2c65ea87`, 2026-10-25)

| Row | Status | Measured | Next mover |
|---|---|---|---|
| (a) latency | GREEN | p95 62.9 / p99 100.6 ms (10-18) | none |
| (b) coverage | RED (first formal score 10-25, PR #1169) | nine_scene 0.00213; owner population 0/474 (no witness) | freeze pkg323 witnesses on candidate_v2; #1167; owner b1 sign-off |
| (c) trio | GREEN | Welch-1b 0 rejected tiles (10-18) | none |
| (d) native panels | GREEN (committed) | — | none |
| (e) triage | **GREEN** (10-25, committed) | 69 open, 0 high, all ratings independent | keep the live list clean |
| (f) clean install | waits on the second PC | — | owner |
| (g) node score | RED | CPU 2/8, GPU 2/8, **0 silent pairs** on `88d2026+20261024T142646Z` (#1148 merged 10-25) | #1004/#1005 (PR pending), #995, #993, #1038 |

Landed since 10-18: #1139 pkg321, #1143 (#1120), #1144 (#1124), #1146 (#1137), #1147 tooling, #1149 Voronoi 3D
(58/58 Cycles-exact). #1148 merged 2026-10-25 (main 88d2026d). Open: #1151 (#1125, CI), #1150 and #1152 filed from the #1125 GPU legs.
Lanes: `lane-i1004` (#1004 then #1005, Opus) running; `lane-i1125` done, `BUILD REQUEST ce06265d` (GPU tests pending).
Tooling: `opencode/deepseek-v4.1-flash-free` is the grunt/implement/vision primary (free, no rate-limit cost, takes
images); vision verdicts on position/size must be confirmed numerically (memory `vision-model-hallucinates-pixel-shifts`).

## 2. The Spectra read (two products, not one)

The owner's two links describe **different engines** that share a name:

| | spectra-render.com (Valor Cat Studios, LA) | Blender Artists thread (Farras Aris, solo, Indonesia) |
|---|---|---|
| Stack | Vulkan KHR RT, proprietary core + GPL-3 shell, Blender 5.1+, Win/Linux/macOS (MoltenVK) | Rust + Vulkan RT + Slang, out-of-process daemon + IPC, Windows only, Blender 4.0-5.2 |
| Spectral | 4 hero wavelengths 380-780 nm + full Stokes polarization; wave-optics "beams" (double slit) | continuous spectrum, Cauchy glass node with priority nesting, thin-film node, blackbody, car-paint flakes; an RGB fast mode |
| Transport | "ReSTIR-WO (patent pending)", DLSS-RR / OIDN; no caustic technique named | "ReSTIR BDPT" + photon caustics (4M photons, 8 caustic bounces), OIDN; Dielectric Graceful Exit at the bounce cap |
| Evidence | 9 stills + 6 viewport clips, no numbers, closed beta, no price | 23 images, one timing (1000² < 8 s on a 3080 Mobile, spp unstated), one 64-spp shader-ball sheet vs Cycles: ~12/21 rows differ or fail (bump, Voronoi, XYZ/vector math, RGB Curves, Sheen) |
| Market signal | none outside the vendor page | 24 posts, 930 views; users ask for easy materials/presets, easy SSS, soft lamp edges, bloom/CA, a test build, and "is it free" |

What this means for Astroray (facts over claims):
- **Astroray already matches or leads** on the measurable claims: spectral transport with hero-wavelength stratification,
  Cycles-socket dispersion (pkg207), Principled thin film (APPROXIMATED), blackbody lamps/volumes, OIDN, ReSTIR-DI shipped
  on CPU+GPU, and above all **measured Cycles node parity** (737-row matrix, witnesses, production corpus) where the thread
  product publishes a 9/21 sheet. Neither competitor publishes a parity instrument; that is our moat and we should show it.
- **Astroray lags** on: (1) a *showcase* of what spectral buys you (their galleries sell dispersion fire, thin-film rings,
  caustic colour; our README gallery is Cornell/material zoo), (2) the Glass BSDF thin-film sockets (#1136, reported drop),
  (3) the bounce-cap behaviour (black dead spots in thick glass at low transmission depth; Spectra's "graceful exit" is a
  cheap, user-visible win), (4) viewport "edit without recompile" messaging (we pass gate (a) at 63 ms p95; owner's 3-5 fps
  feedback was fixed by #850/#819 but never re-demoed), (5) presets/material library (owner theme, nothing filed).
- **Not worth chasing now:** wave optics (double slit), Stokes polarization (only Mitsuba does it; astro GR transfer is the
  real future use, research row 13), ReSTIR BDPT/PT offline (research row 9 keeps ReSTIR PT viewport-only and flagged),
  DLSS-RR (NVIDIA-only, licence), patent-pending anything.
- **Scenes to copy** (recipes in the two research notes): thin-film ladder, prism fan, brilliant diamond, soap bubble + glass
  block, absorbing glass cube caustic, iridescent bunny, tumbler bounce-cap A/B, shader-ball node bench, Classroom (CC0).

## 3. New packages (filed this round)

| Pkg | Name | Why | Size / tier |
|---|---|---|---|
| **pkg324** | Spectral showcase corpus v1 | Copy the nine scenes above as Cycles-node `.blend`s + a runner that renders CPU/GPU/Cycles contact sheets with analytic checks where they exist (Airy thin film, prism deviation); feeds README, the owner's demos and gate-style parity | M; Sonnet lane builds scenes (Blender headless), Flash grunt for sheets/docs, vision tier first-pass |
| **pkg325** | Dielectric bounce-cap passthrough | At the transmission/total bounce cap inside a dielectric, continue as a null pass-through instead of terminating black; **off by default** (Cycles parity), exposed in the Astroray panel; CPU + GPU; tumbler 4/8/12-bounce A/B | S-M; Sonnet lane; GPU via lead |
| **pkg326** | Glass BSDF thin film (#1136) | Route the Glass BSDF Thin Film Thickness/IOR sockets through the Principled thin-film path; removes a reported drop and lets the showcase use the Glass node | S; Sonnet lane |

Filed as follow-ups, not packages yet: material preset library v0 (owner theme "native UI + assets"; needs an owner
decision on scope), a "parity moat" README section (publish the matrix + production score numbers next to the gallery).

## 4. Waves (lane cap 2 + lead; one heavy lead job at a time)

| Wave | Lane A | Lane B | Lead |
|---|---|---|---|
| W1 (now) | `lane-i1004` #1004 → #1005 (Opus) | `lane-i1125` → build ce06265d, GPU tests, PR | merge #1148, re-run (g) (2 min legs), review/merge #1125 |
| W2 | pkg324 showcase corpus (Sonnet) | pkg325 bounce-cap passthrough (Sonnet) | builds on request; vision pass on pkg324 sheets |
| W3 | #995 shader_stack nested Mix Shader (Opus) | pkg326 Glass thin film (Sonnet) | (g) re-run after #1004/#1005 |
| W4 | item 8 gate (b) re-freeze (Sonnet; after #1148) | pkg306 Phase 0 ablation (Opus diagnosis, Flash grid) | M8 closeout sweep, run-report, STATUS |

Reserve: #993 wood Roughness chain over VM_MAX_SLOTS, #1038 light_path GPU residual, #875 viewport in-place transform.

## 5. Owner questions

1. pkg325 default: keep OFF (Cycles parity, physics over look) and expose a checkbox, or ON like Redshift/Spectra?
2. pkg324 publishing: may the showcase renders go into the README (and which licence note for Classroom CC0 / Junk Shop
   CC-BY if used)?
3. Material preset library: in scope for Stage 0 or after exit?
4. Still open from 10-18: evidence storage (git/LFS/local), gate (f) second PC, (b) b1 sign-off.
