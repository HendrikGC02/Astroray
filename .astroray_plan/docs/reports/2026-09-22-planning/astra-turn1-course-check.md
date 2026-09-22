**Strategically on course; formal thaw is not yet justified.** The main drift is accepting “implemented” as “validated,” while expanding the next stage before measuring the current exit gate.



Read-only review at `604b03f0`; two Luna fact-checks used. No renders rerun. Current GitHub counts below rely on your supplied audit.



1. **Corrections that change the plan**



   - **pkg107 is already implemented.** The constructor accepts `r_obs_M`, the Python binding forwards it, and both GR bank scenes use `20.0`. Replace “cheapest package to thaw” with status reconciliation and verification; do not implement it again. [Constructor](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/include/astroray/black_hole.h:212), [binding](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/module/blender_module.cpp:1530).

   - **pkg259 is asset-complete, not gate-instrument-complete.** Its status says done, but Phase 4 explicitly retains the harness integration and absent `coverage_report.py`. Stage 0a finishes an existing commitment. [Spec](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/packages/pkg259-cycles-feature-coverage-reference-scenes.md:218).

   - **The corpus switch is already approved.** The owner selected gallery/workshop/terrace-with-hair, with weights equal to distinct scenes per socket, capped at three. Pin the corresponding assets and verify the required hair content; no new decision about abandoning the original trio is needed. [Owner answers](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/docs/reference-corpus-design-2026-09.md:989).

   - **“GR still renders correctly” exceeds the evidence.** Stable SSIM failures and matching pHash support visual stability. They do not establish scientific correctness. The spectral disk path evaluates Planck emission at the sampled wavelength, multiplies by `g⁴`, and clamps emission to 20; wavelength shifting is not apparent there. Audit this against invariant spectral transfer before accepting spectra or fluxes. This is a specific concern, not a claim that geodesics regressed. [Code](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/include/astroray/black_hole.h:145), [ipole transfer formulation](https://academic.oup.com/mnras/article/475/1/43/4712230).



2. **Stage-plan critique: retain the stages, tighten their exits**



   - **Stage 0a first:** publish one acceptance manifest containing scene hashes, backend/build identity, settings, metrics, thresholds and evidence paths. Then fix measured failures. The “3–4 sessions” estimate is unsupported until coverage and latency are actually scored.

   - **Coverage needs an independent denominator.** Implement `Σwᵢsᵢ/Σwᵢ`, with `wᵢ=min(distinct scenes,3)` and the ratified support scores. Inspect actual exercised sockets; counting only manifest entries already classified SUPPORTED would make the measurement circular. A placard documenting a missing feature does not demonstrate an emitted runtime warning. Report CPU/GPU differences and silent drops separately.

   - **Gate (e) requires independent triage.** Closing #721 is insufficient if wrong-image or silently ignored-setting defects remain under other labels. #859, #846, #845 and the volume defects need assessment under the published severity rubric before anyone declares zero high-severity bugs. [Gate definition](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md:82).

   - **Stage 0c:** #849 is a proposed solution, not itself an acceptance requirement. Require event→first **correct** presented frame, cancellation and stale-frame exclusion across both scenes and edit types. Tick gaps and owner navigation approval supplement those measurements.

   - **Stage 0e should start early.** Measure equal-time error and time-to-target-error alongside equal-spp noise. Separate export/upload, tracing, presentation and denoise costs. First test whether the known light-tree regression justifies a temporary default rollback; postpone new samplers until attribution.

   - **Gate (d):** distinguish adaptive efficiency from denoise quality. At equal maximum spp, adaptive sampling need not reduce noise everywhere. Specify the comparison budget, verify sample-count effects, and check convergence against an independent reference.

   - **Stage 1 needs one bounded groundwork lane.** Recommend CPU GR reference/transfer/performance diagnosis, with a fixed stop at an evidence report and scoped follow-ups. Spec amendments can proceed alongside it; a GPU GR implementation cannot silently enter through “decide GPU leg.”

   - **Move scientific validation into each package.** Stage 4 should extend validation to research use cases, not supply the first independent oracle.

   - **Stage 5 is appropriately conditional.** Keep Hydra/USD waiting for a second real caller.



   **Actually blocks thaw:** all six gate rows, credible measurement, and defects meeting their severity/corpus requirements. **Can slide:** general speed parity, a GR showcase, a GPU GR port, broad #849 work beyond the measured need, and coverage features outside the frozen corpus that neither violate severity rules nor prevent 95%. Fixing #823 is necessary for credible coverage; implementing every unsupported node is not.



   Cornell-bank diagnosis remains necessary baseline hygiene. Requiring every historical astrophysics image to become green is an additional thaw condition unless explicitly adopted.



3. **Amendments to the package table**



   | Package | Recommendation |

   |---|---|

   | **45** | Keep; strengthen the physical data contract substantially. |

   | **46 + #144** | One coordinated spec on existing volume transport; stage emission first, dust scattering separately. |

   | **48** | Retire bespoke `DensityGrid` duplication; retain narrowly needed ingest adapters. |

   | **49** | Retarget output after 48; require conservation and resolution-convergence evidence. |

   | **50** | Keep, but strengthen the lensing model and validation—not merely CPU/GPU placement. |

   | **51 + 133** | One coherent design, separate bounded implementation packages. |

   | **107** | Reconcile status and verify existing behavior. |

   | **New work** | Bound HMXB Phase 1 now; retain cluster lensing and grating as deferred candidates. |



   Specific amendments:



   - **pkg45:** the current table contains discrete, line-integrated emissivities, despite calling them `jν`. Specify integrated-line versus per-wavelength quantities, units, solid-angle normalization, air/vacuum wavelengths, abundance/ionizing-spectrum assumptions and interpolation validity. CIE 1931 is an observer response, not the physical emissivity grid. [Table contract](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/packages/pkg45-cloudy-tables.md:74).

   - **pkg46:** reuse volume traversal and accumulation, but Planck emission does not automatically provide an atomic-line estimator. Current proposals are uniform or visible-luminance-oriented; narrow lines need an explicitly unbiased, efficient sampling strategy and energy-conservation tests. An op-VM opcode is optional until a concrete shader-graph caller requires it. [Sampler](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/src/spectrum.cpp:146), [volume emission](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/include/astroray/volume_emission.h:56).

   - **pkg48/49:** VDB is a representation choice, not proof of scientifically faithful conversion. Preserve units, transforms, temperature/ionization fields and provenance; measure resampling losses. Existing bindings already accept dense NumPy density/temperature arrays, so a separate engine reader needs a demonstrated gap. [Bindings](/C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/module/blender_module.cpp:2046).

   - **pkg51/133:** reverse the conceptual dependency: trustworthy spectral output → response-weighted accumulation → chromatic optics → detector statistics. pkg243 provenance is necessary but insufficient for photon counts: add physical normalization, collecting area, pixel solid angle, exposure and photon-energy conversion. SRF-weighted radiance alone is not a count model. [Mitsuba film semantics](https://mitsuba.readthedocs.io/en/stable/src/generated/plugins_films.html).

   - Preserve enough spectral information for wavelength-dependent PSFs; one broadband image generally cannot recover spatially varying spectral effects afterward. [STPSF weighting](https://stpsf.readthedocs.io/en/latest/usage.html).

   - Do not commit full grating or cluster implementations merely because a target document mentions them. Neither blocks the owner’s two first-stage science tracks.



4. **Dependency order and first measurable science outputs**



   - **Nebula:** `pkg251 → pkg243` for trustworthy output; alongside this, rewrite the pkg45/46 data-and-sampling contract → generate validated line tables → integrate emission into existing volumes → Blender end-to-end quantitative render. Full simulation ingest and telescope noise are unnecessary prerequisites.

   - **First nebula deliverable:** a dust-free, Case-B hydrogen slab with a line-spectrum figure and rendered integrated **Hα/Hβ ≈ 2.86**, at `Tₑ=10⁴ K`, `nₑ=100 cm⁻³`. Propose a 2% renderer agreement target against the pinned table, with statistical uncertainty and linear scaling with path length. This validates relative line transport, not absolute calibration. [Published Case-B reference](https://www.aanda.org/articles/aa/pdf/2021/10/aa40890-21.pdf).

   - **Lensing/HMXB:** verify existing observer geometry and GR transfer first; then branch into **pkg50 weak-field lensing** and **Kerr/HMXB work**. Weak lensing is not a prerequisite for a binary-system scene. Bound HMXB Phase 1 to prescribed orbital geometry and an explicit emission model; avoid adding a hydrodynamics solver.

   - **First lensing deliverable:** a deflection-versus-impact-parameter figure demonstrating **`αbc²/(GM) → 4`** in the weak-field limit, with a proposed ≤1% numerical error over a declared validity range. Include image geometry and surface-brightness checks. This is more diagnostic than showcase similarity and has an independent published target. [Lensing equations](https://link.springer.com/article/10.12942/lrr-1998-12).

   - Specify HMXB’s first observable—such as a normalized orbital light curve—before choosing X-ray microphysics. “HMXB system” alone is not an implementable package.



5. **Top five risks and the next owner decision**



   - **False green:** stale package status, incomplete instruments and label-dependent triage hide remaining work.

   - **Biased coverage:** a corpus authored around supported features overstates daily usability.

   - **Spectral/science mismatch:** line sampling, GR frequency transfer, normalization and clamps can preserve attractive images while corrupting observables.

   - **Unattributed performance:** the reported 10× GR slowdown needs matched builds/settings/hardware; README timing is insufficient.

   - **Scope expansion:** two science tracks plus instruments, ingest, GPU GR, cluster lensing and gratings can overwhelm one hardware-verification lane.



   **Next owner decision:** explicitly ratify whether the current nine-scene corpus replaces the original “~50 scenes” coverage population. Recommend accepting a frozen, reviewed representative corpus with disclosed omissions and independent usage checks; do not treat nine files as automatically equivalent to the original requirement.



VERDICT: ON-COURSE — Preserve the two-track science destination, but finish credible integration measurements and validate spectral physics before expanding implementation scope.

