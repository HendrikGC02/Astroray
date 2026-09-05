# pkg245 — Normal/bump image coordinate provenance

**Pillar:** 5 (Blender integration / shader-node coverage)
**Track:** A
**Status:** OPEN — detailed architect review before implementation
**Estimated effort:** TBD at detailed architecture review
**Depends on:** pkg219a (coordinate/Mapping foundation in [pkg219](pkg219-per-texel-shader-graph.md)),
[pkg223](pkg223-normal-map-node.md) (DONE PR #647),
[pkg223b](pkg223b-bump-node.md) (DONE),
[pkg230b](pkg230b-vector-coordinate-chain.md) (active).
No queue promotion. Pillar 4 remains PAUSED.

## Goal
Close the limited direct-image normal/bump export routing loss. The addon's
normal/bump export captures only the image datablock and never routes the
originating node's Vector socket or named-UV provenance through the existing
image loader, so authored coordinate requests use the loader's default path.
This is static routing evidence; no visual result is claimed here.
Native derivative/tangent-frame correctness is a mandatory
architecture audit, not assumed solved by passing `vector_input`. This package
does not outrank the owner's current sequencing in STATUS/NEXT_STAGE_REPORT/
ROADMAP and does not unpause Pillar 4.

## Evidence (baseline `503ea84`)
- `blender_addon/__init__.py:2899` `get_image_from_socket` resolves a direct `TEX_IMAGE` and returns the image datablock ONLY.
- `get_normal_inputs` (:2911) stores `normal_image`/`bump_image` (:2936/:2943), losing the originating node/Vector socket and UV provenance.
- `_principled_shader_spec` (:3570) calls `load_blender_image` without `vector_input` at :3607/:3612; legacy `convert_principled_bsdf_v2` (:4152) likewise at :4208/:4213.
- `load_blender_image` (:3219) already accepts `vector_input`, resolves coordinate/Mapping/named-UV, and builds the coordinate-aware variant cache — the normal/bump callers never supply it.
- Preserve existing helpers/return consumers/tests/mocks compatibility when retaining provenance; do NOT prescribe a breaking return type.

## Existing coverage and boundary
- pkg223 (DONE PR #647): native normal-map perturbation/TBN. pkg223b (DONE): Bump via UV-aligned surface-gradient; historical acceptance caveats apply. These statuses do not prove the mapped/named-UV export route.
- pkg230b owns the primary affine image/program resolver and child-sampler cache work — exclude here; reuse it once landed.
- [pkg242](pkg242-procedural-mapping-bake-parity.md) owns procedural transformed-p/bake-domain changes, not this direct-image carrier.
- Coordinate with [pkg234](pkg234-image-texture-filtering.md): the bump finite-difference step currently assumes nearest filtering, but no filtering policy is implemented here.

## Native-side evidence for the audit
- `include/advanced_features.h:188` — `Texture::valueOffset` adds du/dv AFTER mapping.
- `plugins/materials/normal_mapped.cpp` — :21 samples the normal texture; :33 uses `rec.uvTangent`/`uvBitangentSign`; :60-66 bump uses the UV frame with post-mapping finite differences.
- `src/gpu/scene_upload.cu:1002-1068` — normal/bump descriptor upload.
- `src/gpu/wavefront/stage_advance.cu:1153-1188`, :1201-1246 — recompute base triangle UV/TBN and apply UV mapping; :1222 explicitly POST-mapping offsets.
- Consequently: named texture-UV layer vs Normal Map node `uv_map`/tangent basis, and transformed bump derivatives, all need audit.

Do NOT assert root cause or full fidelity beyond the routing loss, and do not
blindly rotate normals or change normal strengths.

## Phases
**Phase 0 — baseline + audit:** record direct-image routing baseline and existing
behavior; audit sampling-coordinate vs derivative chain-rule vs tangent
basis/handedness across translation, rotation, mirrors, non-uniform scale, and
degenerate/unsupported spaces. cite-algorithm before ANY numerical change: reuse
the pkg223/223b research notes, verify the pinned Cycles Normal Map and
`svm_node_set_bump` sources/licenses and the Mikkelsen surface-gradient
reference. Document the accepted existing approximation; the architect selects a
bounded supported subset with a VISIBLE unsupported policy BEFORE coding.
Distinguish the UV layer used to sample the image from the Normal Map node's
`uv_map` used for its tangent basis; do not equate these without a Cycles oracle.

**Phase 1 — provenance routing:** retain source/Vector/UV provenance and route it
through the existing loader in BOTH Principled paths (`_principled_shader_spec`
and legacy `convert_principled_bsdf_v2`). Preserve defaults,
normalStrength/bumpStrength/Distance, and the existing normal-chain composition.
Cache-isolate the same image under different coordinate/named-UV/carrier roles,
with invalidation on edits.

**Phase 2 — matched verification:** real, isolated headless-Blender CPU/GPU/Cycles
normal/bump coordinate-effect scenes, fixed-seed linear output, and analytically
known gradient/normal charts. Cover translate/rotate/mirror/non-uniform scale,
named-UV/non-active-UV, one shared image across normal/bump/base-color with
independent maps, mapping edits, and unsupported/degenerate-domain warnings. Pin
numeric tolerances before implementation; compare against the untouched baseline
with meaningful spatial/lighting-direction effects — no scalar-SSIM-only proof.
Saved renders inspected by Astra and required independent Claude.

## Acceptance — all implementation and visual gates UNRUN
- [ ] Focused tests (reuse existing pkg223/223b tests and the canonical Blender harnesses; no new parallel runner) plus — if the engine is touched — fresh native build/module identity, register-fleet identity, caller/binding ABI sweep, full test suite.
- [ ] Phase 0 audit note and bounded supported subset + visible unsupported policy recorded BEFORE any code.
- [ ] Both Principled routes retain source/Vector/named-UV provenance, with compatible helper callers/tests/mocks and isolated cache variants across edits and shared images.
- [ ] Sampling UV, normal tangent-frame semantics, and bump derivative chain rule each satisfy the approved subset or emit an explicit unsupported warning.
- [ ] Phase 2 CPU/GPU/Cycles scenes meet predeclared tolerances and spatial/lighting-direction checks; saved linear renders receive Astra qualitative review and required independent Claude sign-off.
- [ ] Existing defaults, Strength/Distance, and supported normal-chain composition remain compatible; baseline cases without authored coordinate changes remain unchanged where applicable. Any native derivative/basis change needs explicit detailed architecture approval within the bounded subset.
- [ ] Max two isolated implementation worktrees and the project GPU lock; test on an isolated profile only.

## Non-goals
- Arbitrary normal-graph/procedural-texture support; displacement; new normal algorithms or transport physics.
- pkg230b scope expansion (primary affine image/program resolver and child-sampler cache).
- Any inherited claim of full normal/bump coverage.

## Risks
Derivative-basis mismatch, mirrored handedness, wrong UV frame, cache aliasing,
finite-difference/filter interaction. Unsupported domains must be visible, never
silent.

## Scope note
Filing this documents a ROUTING GAP ONLY. It does not mark pkg223/223b invalid,
nor does it complete any implementation gate.
