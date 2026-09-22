The direction is sound, but the plan needs another revision before it becomes a dispatch contract. The main weaknesses are ambiguous exits, insufficiently independent science checks, and an instrument pipeline that could discard spectral information too early.



This was read-only. The project-index command was attempted first but unavailable because the sandbox has no registered Python; I checked the named planning documents and package files directly.



**1. Make the stage exits executable**



Stage 0 has a defensible overall exit, provided “GREEN” imports the complete ratified gate. The abbreviated scoreboard must not lose viewport p99, repetitions, cancellation thresholds, native-panel activation, or the four mandatory shader families.



Several corrections are needed:



- **0a is instrumentation completion, not gate completion.** Its exit should permit measured RED results. Require reproducible commands, validated instruments and evidence for every row; unavailable measurements remain UNMEASURED.

- **“CPU-only lane” describes implementation, not acceptance.** GPU parity, real viewport presentation and clean-machine installation need separately assigned execution slots.

- **Move #823 before the coverage measurement.** It currently appears both as 0a’s prerequisite and in the later 0d batch.

- **Replace “each issue’s measured number inside its gate.”** Every issue needs a named observable, fixture, threshold and evidence owner before dispatch. “No new xfails” alone does not establish correctness.

- **Gate (d) needs an accuracy safeguard.** Lower variance can result from blurring or bias. Compare against a converged reference at a fixed budget, with detail preservation and mean-error checks.

- **Triage the live issue population at acceptance**, not a permanently frozen “33 issues.”

- **Keep reference-bank repair separate from gate redefinition.** Re-baselining needs attribution and independent approval; passing newly captured references cannot validate the change that produced them.



Stage 1 mixes three exits: spec approval, an audit report and implemented band output. Specify each separately. Limit “every Pillar 4 spec” to the named amendment set, and make pkg251/pkg243 acceptance explicit prerequisites for quantitative Stage 2 output.



Pkg280 also needs a sharper boundary: disk transfer, volumetric ADAF/synchrotron transfer, clamp removal, performance attribution and external-code comparison are substantial together. Define a mandatory analytic validation core and one compatible reference comparison; the report must distinguish validated paths from unresolved follow-ups. A report’s existence cannot authorize use of an unresolved path.



Stage 2 needs numerical geometry, brightness and eclipse gates; “showcase render” also needs the required qualitative inspection. Stage 3 needs ensemble statistical tests, not one plausible noisy image. Stage 4 has no exit at all: define a bounded validation matrix and reproducible figure bundle. Stage 5 can remain an explicitly unscheduled conditional branch.



**2. The first science numbers are appropriate—with tighter definitions**



**Case-B Hα/Hβ:** retain this target. Approximately 2.86 is appropriate at the stated temperature and density, but pin the actual emissivity-table version and row rather than treating the rounded value as universal. Storey–Hummer provides the underlying temperature/density-dependent recombination data. [Storey & Hummer, 1995](https://academic.oup.com/mnras/article/272/1/41/967214)



Specify **integrated energy radiance**, not photon counts, RGB values or spectral peak heights. Case B requires the appropriate Lyman trapping assumptions while the measured Balmer lines remain optically thin. Path-length scaling applies within that regime.



A 2% implementation tolerance is reasonable as a proposed engineering budget, not an asserted atomic-data uncertainty. Require repeated seeds and a confidence interval contained within the tolerance. Crucially, add an independent single-line normalization check against \(I_{\rm line}=j_{\rm line}L\), with the solid-angle convention explicit. A common missing \(4\pi\), density factor or normalization can cancel perfectly in Hα/Hβ.



**Weak-field deflection:** retain \(Q=\alpha bc^2/(GM)\to4\), with \(\alpha\) in radians and \(b\) the asymptotic impact parameter. Define 1% as \(|Q/4-1|\le0.01\).



For Schwarzschild propagation,



\[

\alpha=4r_g/b+(15\pi/4)(r_g/b)^2+\cdots,\qquad r_g=GM/c^2.

\]



The second-order correction alone consumes approximately \(2.945\,r_g/b\) of the relative budget. Thus \(b=100r_g\) is unsuitable for a 1% first-order gate; a proposed lower bound around \(1000r_g\) leaves approximately 0.3% for that correction, with finite-distance and numerical errors budgeted separately. [Jia, 2020](https://link.springer.com/article/10.1140/epjc/s10052-020-7796-y)



The present pkg50 describes analytic image remapping. Testing its inserted \(4GM/(bc^2)\) formula against itself is circular. Validate rendered image positions, magnification/Jacobian behaviour and surface brightness independently; use geodesic deflections if the claim is validation of GR propagation.



**HMXB eclipse:** good first geometry deliverable, but the pasted Stage 2 never actually specifies the requested ±2%. Add it.



For a deliberately simple circular, edge-on orbit, spherical opaque donor and point emitter, geometry gives



\[

f_{\rm eclipse}=\arcsin(R_\star/a)/\pi.

\]



For example, \(R_\star/a=0.5\) gives \(f=1/6\). Define 2% as **relative error in eclipse duration fraction**, not ±0.02 of an orbit. Require phase-resolution convergence, ingress/egress location, eclipse depth and a non-eclipsing control. An extended emitter needs its own contact definitions.



This validates prescribed occultation geometry; it does not yet validate an HMXB spectrum or observed system. No universal HMXB eclipse fraction exists.



**3. Missing contracts—and work to cut**



The most important missing bridge is **relative output → physically normalized emission → detected counts**. Pkg243 explicitly promises relative quantities. Stage 3 must name the package that establishes physical normalization, scene-length units and observer solid angle; exposure and collecting area cannot calibrate an arbitrary scalar.



The chromatic instrument ordering also needs correction. Conceptually, the expected electron image is



\[

\mu_e(x)=tA\Omega_{\rm pix}\int

[I_\lambda*P_\lambda](x)\,

T(\lambda)QE(\lambda)\frac{\lambda}{hc}\,d\lambda.

\]



This assumes spectral radiance and separates throughput from QE. Preserve sufficiently fine spectral information until after wavelength-dependent PSF application. A broad SRF-integrated image generally cannot receive the correct chromatic PSF afterward. Test spectral-bin convergence and distinguish incident photons, detected electrons and ADU.



For pkg280, explicitly distinguish frequency and wavelength densities. From invariant \(I_\nu/\nu^3\), with \(g=\nu_{\rm obs}/\nu_{\rm em}\),



\[

I_{\lambda,\rm obs}(\lambda)=g^5I_{\lambda,\rm em}(g\lambda).

\]



That is the derived wavelength-domain transformation; blindly applying \(g^3\) to \(B_\lambda\) remains wrong. Add monochromatic-shift and bolometric-scaling tests, and separately validate volumetric emission/absorption conventions. External comparison must use matching physical models and normalization. [ipole’s transport formulation and validation](https://arxiv.org/abs/1712.03057)



Cut mandatory GR-performance recovery from the science correctness exit; retain bounded attribution. Remove the apparent pkg50→pkg279 dependency unless prescribed eclipse geometry actually consumes lensing. Keep sky, grating, cluster lensing and Hydra deferred. Replace “every rewrite has a literature number” with “every rewrite has an independent reference observable”—conversion tooling needs conservation and convergence, not an invented astronomical target.



**4. Pkg278 remains gameable**



Keep the ratified weight, but define the index and support verdict precisely:



\[

S_b=\frac{\sum_i \min(n_i,3)s_{i,b}}{\sum_i\min(n_i,3)}.

\]



Here \(i\) is a canonical socket identity and \(b\) a backend. Require each backend to pass; averaging CPU and GPU can conceal missing GPU support.



The following rules close the largest loopholes:



- Freeze scene hashes, exercised uses, socket identities, weights and exclusions **before** scoring.

- Derive exercised uses independently from Blender/Cycles reachability and controlled perturbations. An Astroray-dropped use must remain in the denominator.

- A socket’s full-support claim must cover its frozen exercised variants; one working constant input cannot validate arbitrary linked programs.

- Award 0.5 only for a functioning, bounded approximation with a user-visible, attributable warning. “Ignored, but warned” earns zero.

- Missing evidence is not SUPPORTED; missing corpus assets invalidate the run.

- Zero silent drops is a separate Boolean requirement, never merely a reported diagnostic.

- Preserve mandatory Principled-advanced, Metallic, Sky and Displacement checks even if corpus weighting would hide them.



Nine curated scenes remain vulnerable to selection bias despite perfect counting. Until owner ratification, publish that score provisionally. If the original ~50-scene population was never frozen, report its score as **undefined**; “score both” cannot manufacture a denominator.



**5. Exact Terra review queue**



I recommend **12 substantive spec reviews**, each answering one controlling question:



| Spec | ONE question |

|---|---|

| pkg45 | Does the data contract preserve independently checkable integrated emissivity across units, interpolation and spectral support? |

| pkg46 | Can Blender reproduce independent line normalization and Case-B ratios without narrow-line sampling bias? |

| pkg48 | Does conversion preserve field meaning, units and transforms with quantified resampling loss? |

| pkg49 | Does SPH deposition conserve mass and converge under the declared kernel and boundary policy? |

| pkg50 | Does an independent observable validate the chosen lens model rather than repeat its implementation formula? |

| pkg51 | Does the instrument design preserve chromatic spatial information through physically normalized detector statistics? |

| pkg133 | Does SRF sampling remain unbiased while retaining everything pkg51 needs before spectral integration? |

| pkg243 | Is the exported quantity mathematically defined and preserved independently of display processing? |

| pkg251 | Do all callers deliver the same explicit band/output contract to the intended backend? |

| pkg278 | Can any gate become GREEN through omitted evidence, denominator changes or unsupported support claims? |

| pkg279 | Does a Blender-driven light curve recover independently specified eclipse geometry within an unambiguous error budget? |

| pkg280 | Does the evidence establish correct transfer conventions for every path released for science use? |



Add **two reconciliation-only checks**: pkg107—does its done status identify implementation evidence and remaining verification ownership? pkg259—does Phase 4 transfer completely to pkg278 without duplicate completion claims?



One live drafting discrepancy already needs correction: pkg133 currently says “superseded—merged into pkg51,” whereas the supplied disposition explicitly retains separate implementations. Terra should resolve that against the approved plan.



VERDICT: REVISE — Preserve the two-track sequence, but make exits executable, science checks independent, coverage scoring omission-resistant, and spectral-to-detector ownership explicit before dispatch.

