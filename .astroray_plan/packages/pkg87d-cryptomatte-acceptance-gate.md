# pkg87d — Cryptomatte Acceptance Gate (IoU + EXR Manifest)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 3–5 days
**Depends on:** pkg87c part 1 (PR #345, in flight — pass-plugin
normalisation + Blender pass registration + Python bindings landed
without the IoU gate / manifest)
**Reference research:** `.astroray_plan/docs/cryptomatte-research.md`
(Psyop v1.2.0 §3 manifest, Cycles `Film::update_passes` manifest
construction, Apache-2.0). Reference; do not duplicate.

---

## Why this package exists

pkg87c was originally scoped to ship Blender integration **and** the
Psyop IoU ≥ 0.95 roundtrip acceptance gate in one PR. The implementer
shipped the correct mechanical work (sort + normalise + bindings + pass
registration + integration test) but deferred the three load-bearing
acceptance items:

1. **Psyop IoU ≥ 0.95 roundtrip gate** — needs an isolated
   ground-truth render harness (re-render each named object/material in
   isolation, IoU vs compositor-reconstructed mask).
2. **EXR manifest header** — `cryptomatte/<hash7>/{name,hash,conversion,manifest}`
   entries per Psyop §3 so Blender's stock Cryptomatte node auto-picks
   names from the EXR (without this, the compositor node lists no names
   and acceptance criterion #1 cannot be exercised).
3. **Manifest JSON round-trip** — `manifest[name] == crypto_hash_name(name)`
   for every entry.

Filed as a follow-up rather than re-opening pkg87c because pkg87c part
1's shipped slice is independently valuable + correct (sort/normalise
math matches Cycles, bindings are wired end-to-end, Σw≈1 invariant
asserted in test), and the deferred items are infrastructure work that
benefits from a clean scope.

---

## Goal

**Before:** pkg87c part 1 (PR #345) merged. Pass plugin normalises +
sorts. Blender addon registers passes + packs RenderResult layers.
Python bindings `set_object_name`/`set_material_name`/
`set_cryptomatte_enabled`/`set_cryptomatte_depth` exist. Integration
test asserts buffer shape + per-pixel Σw≈1. **Nothing emits the
manifest or runs the IoU gate.**

**After:**

- The EXR writer (pkg87a's `exr_writer`) emits the
  `cryptomatte/<hash7>/{name,hash,conversion,manifest}` header entries
  per Psyop §3 with `conversion == "uint32_to_float32"` and
  `hash == "MurmurHash3_32"`.
- A C++ name→hash registry tracks every `setObjectName` /
  `setMaterialName` call so the manifest JSON can be emitted at render
  end.
- A test harness in `tests/test_cryptomatte_pass.py`:
  - Renders the `cryptomatte_3_objects.py` scene (shipped in pkg87c
    part 1) at 64 spp.
  - Re-renders each name in isolation (everything else hidden) to
    produce a ground-truth mask.
  - Reconstructs the compositor mask via the Psyop matte-extraction
    algorithm (research note §"Mask reconstruction").
  - Asserts `IoU(ground-truth, reconstructed) >= 0.95` per name.
- A manifest round-trip test asserts `manifest[name] ==
  crypto_hash_name(name)` for every shipped name.

---

## Specification

1. **C++ name registry**
   - `include/astroray/cryptomatte.h` — add a thread-safe
     `crypto_name_registry` (singleton or attached to `Renderer`) that
     records every `setObjectName`/`setMaterialName` call.
   - At render end, the registry serialises to JSON:
     `{ "name1": "<hash_hex>", "name2": "<hash_hex>", ... }`.

2. **EXR manifest emission**
   - `plugins/passes/exr_writer.cpp` (pkg87a) — extend to write the
     four Psyop header entries:
     - `cryptomatte/<hash7>/name` = typename ("CryptoObject" /
       "CryptoMaterial")
     - `cryptomatte/<hash7>/hash` = `"MurmurHash3_32"`
     - `cryptomatte/<hash7>/conversion` = `"uint32_to_float32"`
     - `cryptomatte/<hash7>/manifest` = JSON string from the registry
   - `hash7` is the first 7 hex chars of `crypto_hash_name(typename)`
     per Psyop spec §3.

3. **IoU test harness**
   - `tests/test_cryptomatte_pass.py` — a single pytest that:
     - Imports `cryptomatte_3_objects.py` scene
     - Renders the full scene at 64 spp; captures the crypto buffers
     - For each named object/material:
       - Hides everything else; re-renders the same view at 64 spp;
         captures a binary visibility mask
       - Reconstructs the matte via the Psyop algorithm:
         `mask[x,y] = sum( weight | hash == target_hash )`
       - Computes `IoU = |mask ∩ ground-truth| / |mask ∪ ground-truth|`
       - Asserts `IoU >= 0.95`

4. **Manifest round-trip test**
   - In the same test file, parse the emitted manifest JSON; for every
     entry assert `crypto_hash_name(name) == manifest[name]`.

5. **Blender node smoke test (manual, document only)**
   - Open the emitted EXR in Blender's compositor; confirm the stock
     Cryptomatte node lists all six names (`cube_red/green/blue` +
     `mat_red/green/blue`) in its picker. Pass: visual confirmation
     screenshot in `.astroray_plan/docs/pkg87d-blender-screenshot.png`.

---

## Acceptance criteria (closes pkg87c's deferred set)

- [ ] EXR manifest header present with all four Psyop §3 entries.
- [ ] Manifest JSON parses; round-trip identity holds for every name.
- [ ] `IoU >= 0.95` for all six names on `cryptomatte_3_objects.py` at
      64 spp.
- [ ] Blender compositor opens the EXR and lists all six names in the
      Cryptomatte node picker (manual; screenshot).
- [ ] No regression on `tests/test_cryptomatte_blender_integration.py`
      (the pkg87c part 1 invariant test must still pass).

---

## Non-goals

- Do **not** touch the pkg87c part 1 pass-plugin normalisation/sort
  logic — that's been independently reviewed and is correct.
- Do **not** change the Python binding surface; the name registry hooks
  into the existing `setObjectName`/`setMaterialName` already wired.
- Do **not** add per-render-engine manifest customisation; Psyop §3 is
  the canonical schema.

---

## References

- Psyop Cryptomatte Specification v1.2.0 §3 — manifest schema (BSD-3-Clause)
- Cycles `intern/cycles/scene/film.cpp` `Film::update_passes` manifest construction (Apache-2.0)
- Friedman & Jones, SIGGRAPH 2015 — matte extraction algorithm
- Research notes: `.astroray_plan/docs/cryptomatte-research.md`
