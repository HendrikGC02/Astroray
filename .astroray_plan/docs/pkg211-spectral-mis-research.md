# pkg211 research note — per-bounce spectral MIS + spectral ray differentials

Web-verified research note (STRICT contract: every factual claim below was
checked by searching the web and fetching the source; each fact carries its
source URL inline). Written for the follow-up Opus agent that will author the
real pkg211 spec. This note deliberately corrects three mis-citations in the
existing `pkg211-*.md` spec (see §0).

Provenance: `.astroray_plan/packages/pkg211-per-bounce-spectral-mis-and-ray-differentials-prototype.md`
+ `include/astroray/spectrum.h` (read in full).

---

## §0 — Corrections to the pkg211 spec (honesty-first)

The spec as filed cites three "per-bounce spectral MIS" sources that, on
verification, are **not** per-bounce spectral MIS. These must be corrected
before any implementation work:

1. **"Petitjean & Bauszat 2018" is actually Petitjean, Bauszat & Eisemann 2018**
   (three authors, not two), and the paper is **spectral *gradient* sampling**
   (gradient-domain, correlated path pairs + spectral shift mapping + 1-D
   screened-Poisson reconstruction) — **not** per-bounce MIS. It is a
   different variance-reduction family entirely (see §2).
   — https://publications.graphics.tudelft.nl/papers/207 (DOI 10.1111/cgf.13474)

2. **"Pediredla et al. 2020, DOI 10.1145/3414685.3417793" is
   "Path tracing estimators for refractive radiative transfer"** (ACM TOG 39(6),
   SIGGRAPH Asia 2020) — about heterogeneous refractive-index media / curved
   light paths (the RRTE), **not** spectral MIS or wavelength sampling. Verified
   via Crossref:
   — https://api.crossref.org/works/10.1145/3414685.3417793
   (title "Path tracing estimators for refractive radiative transfer"; authors
   Pediredla, Chalmiani, Scopelliti, Chamanzar, Narasimhan, Gkioulekas).

3. There is **no canonical "per-bounce spectral MIS" paper** under that name.
   The nearest real prior art is *spectral MIS* (Radziszewski et al. 2009) and
   its per-vertex treatment in Wilkie et al. 2014 (§1, §2). "Re-decide the hero
   wavelength at each dispersive bounce and combine via MIS" is a genuinely
   novel/underspecified proposal — which is exactly why this package is
   prototype-first with a legitimate PARK outcome.

---

## §1 — Wilkie et al. 2014 (the pkg206 baseline)

**Full verified citation:**

> Wilkie, Alexander; Nawaz, Sehera; Droske, Marc; Weidlich, Andrea; Hanika,
> Johannes. "Hero Wavelength Spectral Sampling." *Computer Graphics Forum*
> 33(4), pp. 123–131 (Proceedings of EGSR 2014), July 2014.
> DOI: 10.1111/cgf.12419

- Authors, venue, pages, DOI confirmed by Wiley (publisher record):
  — https://onlinelibrary.wiley.com/doi/10.1111/cgf.12419
- Author affiliations: Wilkie = Charles University Prague + Weta Digital;
  Nawaz/Droske/Weidlich = Weta Digital; Hanika = Karlsruhe Institute of
  Technology + Weta Digital (from the free author PDF):
  — https://cgg.mff.cuni.cz/~wilkie/Website/EGSR_14_files/WNDWH14HWSS.pdf
- Independent author-page confirmation:
  — https://cgg.mff.cuni.cz/publications/hero-wavelength-spectral-sampling

**Mechanism relevant to pkg211** (from the free PDF, §3–§4): one *hero*
wavelength is drawn per path and drives ALL directional sampling; 3 companions
are placed at equidistant offsets (rotation function `r_j(λ)`, eq. 5); the
per-wavelength pdf must be the density evaluated at each lane's own wavelength,
and contributions are combined with **joint MIS weights computed per vertex**
(§3.2 "MIS with shifted techniques", §4.1). The paper explicitly notes (Fig. 6)
that at a **Dirac dispersive interface** the method "falls back to single
wavelength behaviour" — i.e. hero-collapse, which is exactly Astroray's
`terminateSecondary()` path. This is the precise spot per-bounce re-decision
would attack.

---

## §2 — What "per-bounce spectral MIS" would add (honest assessment)

**Claim being evaluated:** instead of committing to one hero for the whole
path and collapsing companions at the first dispersive hit, re-decide /
re-weight the wavelength sample at each dispersive bounce and combine the
per-bounce strategies via MIS, to cut the chromatic fireflies in multi-bounce
dispersive caustics.

**Prior art that actually exists (verified):**

- **Radziszewski, Boryczko & Alda 2009**, "An Improved Technique for Full
  Spectral Rendering", *Journal of WSCG* 17(1), pp. 9–16. The original
  "spectral MIS": each wavelength is a distinct path-sampling strategy, combined
  by MIS; traced a full cluster through wavelength-dependent scattering instead
  of splitting. Verified via author PDF:
  — https://www.researchgate.net/publication/228938842_An_Improved_Technique_for_Full_Spectral_Rendering
  (also cited as `[RBA09]` inside Wilkie 2014's reference list, see §1 PDF).
  Wilkie 2014 explicitly positions hero sampling as "a simplified and optimised
  version of this approach".

- **Evans & McCool 1999**, "Stratified Wavelength Clusters for Efficient
  Spectral Monte Carlo Rendering", *Graphics Interface* 1999 — the precursor:
  propagate a cluster, **split/discard at wavelength-dependent surfaces**.
  Cited in the Petitjean et al. 2018 paper body (`[EM99]`):
  — https://publications.graphics.tudelft.nl/papers/207

- **Wilkie et al. 2014** (§1) — already computes **per-vertex joint MIS weights**
  but keeps the *same* hero across the whole path. So "per-vertex MIS weighting"
  exists; "per-vertex hero *re-selection*" does not.

- **Petitjean, Bauszat & Eisemann 2018** — gradient-domain spectral sampling
  (NOT per-bounce MIS): correlated base/offset path pairs shifted in λ, Poisson
  reconstruction. Reported ~relMSE 1.83 vs 4.82 (equal time) and composes with
  hero sampling (their Fig. 4). This is a *competing* technique, not the
  technique the spec describes.
  — https://publications.graphics.tudelft.nl/papers/207 (DOI 10.1111/cgf.13474)

**Honest conclusion for §2:** There is no published, peer-reviewed technique
matching "re-decide hero per bounce + MIS across bounces". The idea is
plausible but unproven; the closest published mechanisms (Radziszewski 2009
per-strategy MIS, Wilkie 2014 per-vertex weights) already exist and are the
basis of Astroray's current SMS/hero path. **On the spec's own framing
("prototype-first, may PARK"), the expected value here is modest and the
implementation cost is high** — see §5 PARK criterion. Recommendation: treat
this as an exploratory spike, not a committed productionization.

---

## §3 — Spectral ray differentials

**Igehy 1999 (base ray-differential theory) — VERIFIED:**

> Homan Igehy, "Tracing Ray Differentials", *Proceedings of SIGGRAPH '99*
> (26th annual conference), pp. 179–186, 1999. DOI: 10.1145/311535.311555

- Single author, venue, pages, DOI verified via ACM DL + Semantic Scholar:
  — https://dl.acm.org/doi/abs/10.1145/311535.311555
  — https://www.semanticscholar.org/paper/Tracing-ray-differentials-Igehy/727181c82567935fec0c139b484d9744d6ab9bb9
  — Author PDF: https://graphics.stanford.edu/papers/trd_jpg.pdf

**Spectral extension — Elek et al. 2014 — VERIFIED:**

> Oskar Elek, Pablo Bauszat, Tobias Ritschel, Marcus Magnor, Hans-Peter Seidel,
> "Spectral Ray Differentials", *Computer Graphics Forum* 33(4), pp. 113–122
> (Proceedings of EGSR 2014), 2014. DOI: 10.1111/cgf.12418

- Verified via Crossref (exact title/authors/pages/DOI):
  — https://api.crossref.org/works/10.1111/cgf.12418
  (abstract confirms the mechanism: "spectral ray differentials … describe the
  change of light direction with respect to changes in the spectrum … used for
  filtering in the spectral domain"). Also verified in the EGSR 2014 issue TOC:
  — https://diglib7.eg.org/collections/d087170a-aa62-4674-afb8-288e7a1f48c1

**Reference implementation / license for §3:**
- Elek 2014 project page exists (MPI Informatik) with a supplementary
  derivation PDF, but **no public source code was found** (NOT FOUND — likely
  paper-only; math would be ported from the paper):
  — http://people.mpi-inf.mpg.de/~oelek/Papers/SpectralDifferentials/index.html
- Igehy 1999 is paper-only (no code of record).
- The technique relies on tracking `∂direction/∂λ` and `dλ` along the ray and
  filtering in the spectral domain (splatting for GPU photon mapping). Mapping
  onto Astroray would require carrying differential state alongside
  `SampledWavelengths`, which in the register-saturated shade kernel is the
  same cost pressure as per-bounce MIS (§4).

---

## §4 — Astroray integration points (verified against live code)

All line numbers read from the current tree during this session.

- **Hero chosen once at path init, CPU:** `SampledWavelengths::sampleImportance`
  declared at `include/astroray/spectrum.h:115-117`; implemented at
  `src/spectrum.cpp:103-186` (logistic CDF `heroCdf` at `:140`, companions
  `:153`, per-lane pdf `:186`).
- **Hero chosen once at path init, GPU (byte-twin):**
  `sampleImportanceWavelength` at `src/gpu/wavefront/stage_init.cu:166-186`
  (windowed-CDF renormalization at `:170`, per-lane pdf `:186`); called from
  primary-ray gen at `stage_init.cu:278`; pdfs persisted into `PathState` SoA
  (`lambda_pdf_0..3` at `:347-350`).
- **Hero-collapse (the thing per-bounce MIS would replace):**
  `SampledWavelengths::terminateSecondary()` at `src/spectrum.cpp:180-186`
  (zeroes the secondary pdfs so only the hero survives). GPU: pkg189
  `HasDispersion` isolation axis — collapse write-back in
  `src/gpu/wavefront/stage_advance.cu:975-990` and `:1750-1759`; instantiation
  selection `:2547`, `:2606`; launcher `scene_upload.cu:751`.
- **Shade kernel (where a per-bounce re-decision would hook the BSDF draw):**
  `stageShadeBucketedKernel` at `src/gpu/wavefront/stage_advance.cu:2072`.
  The shade fleet is **register-saturated at REG 254 / STACK 3352 /
  CONSTANT[0] 1700** and must stay byte-identical for the non-dispersive
  fleet (`stage_advance.cu:152-186`, `:2547-2680`; memory
  `wavefront-shade-kernels-register-saturated`, PR #620 register probe).
  Template axes already present: `<HasPrincipled, HasPhotons, HasDispersion,
  HasProgram, HasNormalPerturb>` (`stage_advance.cu:2633-2641`). A per-bounce
  spectral re-decision would add a new axis (e.g. `HasSpectralMIS`) with the
  same discipline.
- **SMS / spectral-MIS caustic path:** `src/gpu/photon_caustic.cu:251`
  (spectral caustic weight); `src/gpu/pkg64_sms_probe.cu` (SMS probe).

**Key architectural fact:** the shade kernel already carries per-hit live
state under tight register pressure; the established convention is that any
new per-hit spectral state must NOT leak into the `<…,false>` fleet (must be a
`template<bool>` axis, mirroring `HasDispersion`). Per-bounce MIS is the
*more invasive* candidate precisely because its re-decision logic lives at the
BSDF draw inside the shade kernel; spectral ray differentials are only
marginally cheaper (they add `∂dir/∂λ` + `dλ` live state to the same kernel).

---

## §5 — Stage-1 prototype + measurement plan + PARK criterion

**Recommended prototype (CPU-only, behind a flag/build define):**

1. Add a `SampledWavelengths::resampleHeroPerBounce(u, rec)` method (CPU) that,
   at a dispersive BSDF draw, re-draws the hero from the luminance-weighted
   logistic density and re-weights the per-lane pdfs (Wilkie 2014 §4.1 formula),
   accumulating a per-bounce MIS weight product along the path. Keep it off the
   default path (flag `--spectral-mis-per-bounce`).
2. Do **not** touch the GPU shade kernel in Stage 1 — the register-probe is a
   Stage-2 gate only (§4).

**Scene (must show a win over pkg206, or PARK):**
- The existing dispersive-prism / SMS spectral-caustic scene
  (`tests/test_spectral_prism.py`, the SMS caustic path) — the same scene
  pkg206 re-baselined. Use a multi-bounce dispersive configuration (prism +
  floor bounce feeding the caustic), which is where hero-per-path chromatic
  fireflies dominate.

**Metric (per-channel variance vs spp, LINEAR EXR, seed-pinned):**
- Render LINEAR (`apply_gamma=False`) at a fixed low sample count; compute
  per-channel variance / MSE vs a high-spp reference, and a chromatic-noise
  proxy (e.g. per-pixel hue spread / chroma RMSE, matching pkg206's reported
  "−42% RMSE / −38% chroma" baseline methodology). Plot A/B curves:
  `{pkg206 hero, per-bounce MIS}` on the same seed + scene.
- **Unbiasedness check:** converged (high-spp) per-bounce-MIS render must match
  the pkg206 hero render to within MC noise (per-channel mean-ratio band); this
  is the half-blind trap from the furnace/energy guard (`_linear_render_guard.py`).

**PARK criterion (explicit, measured):**
- PARK if per-bounce MIS does **not** beat pkg206 by a *material* margin —
  suggested bar: < 10% relative reduction in per-channel variance / chroma at
  equal spp on the dispersive-caustic scene, OR any unbiasedness failure. A
  well-argued negative result is a valid Stage-1 closeout (cf. pkg167 Pt. 2).
  Given §2's finding (no published precedent, high invasiveness in the
  REG-254 kernel), the prior probability of PARK is high; the GPU register
  probe is a second, independent PARK gate even if CPU is positive.

**Stage-1 acceptance (mirrors the spec):** `cite-algorithm` note (this file is
the research half); baseline noise-vs-spp curve with `.pyd` mtime stated;
prototype curve on the same scene; GO/PARK with measured delta; if GO → Stage-2
filed with the register-probe gate, else PARK documented in STATUS.md.

---

## §6 — License-compatible reference implementations (summary)

- **Wilkie 2014 / hero MIS baseline:** no official code; free author PDF (CC-by
  venue terms) at https://cgg.mff.cuni.cz/~wilkie/Website/EGSR_14_files/WNDWH14HWSS.pdf .
  License-compatible *code* reference is **Cycles** `sample_wavelength()` /
  `cie_d65_luminance_fit.py` (already cited in pkg206 as Apache-2.0).
- **Radziszewski 2009 / Petitjean 2018:** paper-only; no public reference code
  found for either (NOT FOUND — port math from the paper).
- **Pediredla et al. 2020 (RRTE):** public `MitsubaER` code exists
  (https://github.com/cmd-ci-lab/MitsubaER) but is off-topic for spectral MIS.
- **Mitsuba 3:** BSD-licensed (PyPI "BSD License"; mitsuba3 BSD-3-Clause) and
  the standard license-compatible spectral renderer, but does **not** ship hero
  wavelength sampling by default (open community effort only, discussion #1040):
  — https://github.com/mitsuba-renderer/mitsuba3/discussions/1040
  — https://pypi.org/project/mitsuba/

---

*End of note. Verified-fact URLs are inline throughout. Anything not confirmed
by an actual fetch/search is marked NOT FOUND.*
