# pkg87c — Cryptomatte Blender Integration + Acceptance

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 1 week
**Depends on:** pkg87b (integrators must be populating the crypto
histograms before the Blender passes and the IoU gate can be exercised);
transitively pkg87a.
**Reference research:** `.astroray_plan/docs/cryptomatte-research.md`
(Psyop spec v1.2.0 BSD-3, Friedman & Jones SIGGRAPH 2015 — channel
naming `<typename>NN.{R,G,B,A}`, EXR header manifest, IoU roundtrip
validation; Cycles `intern/cycles/scene/film.cpp` `Film::update_passes`
manifest construction + Blender D3538 pass registration, Apache-2.0).
Reference it; do not duplicate.

---

## Why this package exists

Third of the three packages replacing the original
`pkg87-cryptomatte.md`. pkg87a built the infrastructure; pkg87b made
every integrator accumulate the per-shade-point histogram. This package
exposes the result to the Blender compositor through standard
Cryptomatte passes + manifest metadata, and proves end-to-end
correctness with the Psyop roundtrip IoU gate. This is the part of the
original spec's Phase 3 plus the acceptance gate, now that it has real
data to validate.

---

## Goal

**Before:** pkg87b is merged. Every integrator fills
`crypto_object` / `crypto_material` per-pixel rank arrays. There is a
pass-plugin skeleton from pkg87a but no normalisation/EXR emission wired
to Blender, no Blender pass registration, and no acceptance gate.

**After:**

- The Cryptomatte pass plugin
  (`plugins/passes/cryptomatte_pass.cpp`, from pkg87a) normalises the
  per-pixel weights (`Σ weight == 1` on hit pixels, `== 0` on sky),
  packs the ranked `(id, weight)` pairs into `CryptoObject00/01/02` and
  `CryptoMaterial00/01/02` channels (depth 6 → 3 RGBA layers ×
  typename, per the Psyop naming convention), and emits the EXR with the
  manifest header via pkg87a's `exr_writer`.
- The Blender addon registers the passes and embeds the manifest so the
  stock Blender / Cycles / Karma Cryptomatte compositor node picks them
  up unchanged.
- Selecting any object or material in the compositor reconstructs its
  mask at **IoU ≥ 0.95** versus a ground-truth isolated render.

---

## Scope

### Pass plugin finalisation (`plugins/passes/cryptomatte_pass.cpp`)

| Behaviour | Contract |
|---|---|
| Normalisation | Per pixel, divide every rank weight by `Σ weight`; leave at 0 when the sum is 0 (sky). Cycles normalises post-accumulation; the Psyop node assumes the normalised sum. |
| Channel packing | depth 6 → layers `00`,`01`,`02`. Each RGBA layer holds 2 pairs: `.R = id(2k)`, `.G = weight(2k)`, `.B = id(2k+1)`, `.A = weight(2k+1)`. Ranks sorted weight-descending (already enforced by `crypto_insert`). |
| Manifest | Build `cryptomatte/<hash7>/{name,hash,conversion,manifest}` header entries via the pkg87a manifest builder. `<hash7>` = first 7 hex digits of `MurmurHash3("CryptoObject")` / `MurmurHash3("CryptoMaterial")`. `conversion = "uint32_to_float32"`, `hash = "MurmurHash3_32"`, `manifest` = JSON `{name: float_id, ...}`. Source the name→hash map built at scene upload (pkg87a). |
| EXR write | Use pkg87a `exr_writer` to write all `CryptoObject*` + `CryptoMaterial*` channels + header into one EXR. Skip gracefully (with a clear message) when OpenEXR was not found at build time. |

### Blender addon (`blender_addon/__init__.py`)

| Change | Contract |
|---|---|
| Pass registration | Register `CryptoObject00/01/02` and `CryptoMaterial00/01/02` via `RenderEngine.add_pass(name=..., channels=4, chan_id="RGBA", layer=view_layer.name)` for depth 6. |
| Name population | When building the scene for the engine, set each object's `Hittable::setName(obj.name)` and each material's `Material::setName(mat.name)` (the C++ setters landed in pkg87a) so the hashes match the names the compositor will look up. |
| RenderResult manifest | In the render-result update path, `foreach_set` each `CryptoObjectNN`/`CryptoMaterialNN` pass from the corresponding crypto buffer, and embed the manifest JSON as the standard Cryptomatte metadata key on the render result so the compositor node auto-populates its picker. |
| UI toggles | Expose `use_pass_cryptomatte_object` and `use_pass_cryptomatte_material` checkboxes under View Layer → Passes, and a `cryptomatte_depth` enum (2/4/6/8/16, default 6) on the scene Astroray settings. Toggling a checkbox adds/removes the passes from `RenderResult.layers[*].passes`. |

### Acceptance harness

- `tests/scenes/cryptomatte_3_objects.py` — three named cubes
  (`cube_red`, `cube_green`, `cube_blue`) with three named materials
  (`mat_red`, `mat_green`, `mat_blue`) on a named plane (`floor`),
  256×256, depth 6, 64 spp.
- A ground-truth harness that re-renders each of the 6 names in
  isolation (other objects hidden) at the same camera + spp and
  thresholds alpha to a binary mask.
- `tests/test_cryptomatte_pass.py` — render the 3-object scene, parse
  the EXR manifest, reconstruct each name's mask by selecting its
  hash-float across the ranks weighted by the rank weights, and assert
  **IoU ≥ 0.95** versus the isolated ground-truth for all 6 names.

---

## Key design decisions

1. **IoU ≥ 0.95 gate, 64 spp acceptance scene.** This is the Psyop
   roundtrip-test metric (spec §6). 0.95 sits below the Cycles internal
   regression bar (~0.97) to leave headroom for low-spp stochasticity;
   acceptance renders at 64 spp.
2. **Default depth 6 (3 layers × 2 typenames).** Matches Cycles
   `u_cryptomatte_depth = 6` and the Psyop default; the depth enum lets
   power users widen it.
3. **Normalisation lives in the pass plugin, not the integrator.**
   Confirmed in pkg87b: integrators accumulate raw weights; this
   package divides by the per-pixel sum at pack time. One normalisation
   site, matching Cycles.
4. **Manifest must round-trip.** Every name in the emitted manifest must
   satisfy `manifest[name] == crypto_hash_name(name)`; the test asserts
   this independently of the IoU gate (catches name/hash desync between
   the Blender setName path and scene-upload hashing).
5. **v1 typenames = `CryptoObject` + `CryptoMaterial` only.** No
   `CryptoAsset` (needs collection-metadata propagation; out of scope,
   future follow-up).

---

## Acceptance criteria

- [ ] Output EXR opens in Blender's compositor; the stock Cryptomatte
      node lists `cube_red/green/blue` (CryptoObject) and
      `mat_red/green/blue` (CryptoMaterial) in its picker, with no
      custom node.
- [ ] For each of the 6 names, the compositor-reconstructed mask has
      **IoU ≥ 0.95** versus a single-object/material ground-truth render
      at identical camera + 64 spp.
- [ ] EXR header contains valid
      `cryptomatte/<hash7>/{name,hash,conversion,manifest}` entries per
      Psyop spec §3; `conversion == "uint32_to_float32"`,
      `hash == "MurmurHash3_32"`.
- [ ] Manifest JSON parses; `manifest[name] == crypto_hash_name(name)`
      for every entry (round-trip integrity).
- [ ] Per-pixel `Σ weight == 1 ± ε` on hit pixels, `== 0` on sky.
- [ ] Blender View Layer → Passes shows `Cryptomatte Object` /
      `Cryptomatte Material` checkboxes; toggling them adds/removes the
      passes from `RenderResult.layers`. The depth enum changes the
      number of registered `NN` layers.
- [ ] No regression in existing AOV/denoiser tests or other Blender
      passes.

---

## Non-goals

- No `CryptoAsset` typename (future follow-up; needs collection
  metadata).
- No motion-blur-aware Cryptomatte (Cycles disables Cryptomatte under
  motion blur; match that).
- Do not change the `Pass` plugin interface (`include/astroray/pass.h`);
  Cryptomatte fits the existing named-buffer pattern.
- Do not re-normalise or re-accumulate in the integrator (that boundary
  was fixed in pkg87b).
- Do not widen `exr_writer` beyond Cryptomatte's needs.

---

## Progress

- [ ] Pass plugin: per-pixel normalisation implemented.
- [ ] Pass plugin: channel packing into `CryptoObject/Material 00/01/02`.
- [ ] Pass plugin: manifest header emitted via pkg87a `exr_writer`.
- [ ] Blender: object/material `setName` wired from depsgraph.
- [ ] Blender: `CryptoObject/Material NN` passes registered.
- [ ] Blender: manifest embedded in RenderResult; node auto-populates.
- [ ] Blender: UI toggles + depth enum.
- [ ] `tests/scenes/cryptomatte_3_objects.py` + ground-truth harness.
- [ ] `tests/test_cryptomatte_pass.py`: IoU ≥ 0.95 for all 6 names.
- [ ] Manifest round-trip test green.
- [ ] PR opened (depends on pkg87b merged). STATUS.md updated.
