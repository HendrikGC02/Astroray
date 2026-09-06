# pkg135 — Demand-loaded sparse textures (NVIDIA OptiX Toolkit DemandLoading model)

**Pillar:** 1 (CUDA device infrastructure)
**Track:** A (host-side page-request servicing is CPU-gated; the sparse-texture device path is verified on RTX)
**Codex-paste-ready:** no (CUDA virtual-memory / sparse-texture APIs + a device request list + inter-launch host servicing — research-grade device work)
**Status:** superseded — conditional trigger (VRAM overflow on real astro scenes) never fired in 5 months; refile if it does (2026-09-07 backlog triage)
**Estimated effort:** M–L (2–4 sessions per the research doc — CUDA virtual-memory APIs)
**Depends on:** none hard. Second tier above **pkg132** (host-mapped fallback): pkg132 is the cheap whole-buffer spill that should ship first; pkg135 is page-granularity texture streaming that only earns its cost once whole-buffer spill is insufficient. **Phase-0 task:** verify the OTK `LICENSE.txt` is BSD-3 against the actual repo before any code is mirrored (research-doc flags it as README-asserted, not fetched).

---

## Goal

**Before:** Textures (including large FITS-derived cubes and high-res env maps) must
fit in VRAM in full. A scene whose texture working set exceeds VRAM cannot render,
even if any single frame only touches a fraction of the texels.

**After:** Port NVIDIA OptiX Toolkit's **DemandLoading** model (BSD-3 per README —
verify at phase 0): CUDA **sparse textures** launch with unresolved pages; kernels
record page requests in a device-side request list; the host services requests
between launches and re-launches. Only the texels a frame actually samples are
resident — the texture working set decouples from total texture size. The
sparse-texture + request-list machinery is CUDA-level and works **without OptiX**
(the demand-loaded *geometry* half is OptiX-tied and explicitly **not** ported).

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §4
(priority 2). Mechanism:

- **Sparse (tiled) textures:** back each demand-loaded texture with CUDA sparse
  texture memory so pages can be mapped/unmapped independently.
- **Device request list:** on a sample of an unresolved page, the kernel appends the
  page id to a device-side request buffer (atomic append) instead of stalling.
- **Inter-launch servicing:** after a launch, the host reads the request list, loads
  the requested pages (from the FITS cube / texture source) into sparse-texture
  backing, and re-launches; the previously-requested samples now resolve.
- **Portability:** all of the above is CUDA virtual-memory / sparse-texture API — no
  OptiX dependency. Demand-loaded geometry (OTK's other half) is OptiX-tied and out
  of scope.

Astroray integration point: the texture atlas / sampling path in
`src/gpu/scene_upload.cu` and the FITS source in `src/io/fits_io.cpp`.

---

## Implementation plan (only when the conditional trigger fires)

- **Phase 0 — license + trigger.** Fetch OTK `LICENSE.txt`, confirm BSD-3. Confirm a
  real scene overflows VRAM textures under pkg132's whole-buffer fallback (i.e.
  whole-texture spill is too slow / too large). Only then proceed.
- **A. Sparse-texture backing + request list.** Wrap demand-loaded textures in CUDA
  sparse memory; add the device request buffer + atomic-append on unresolved sample.
- **B. Host page servicer + re-launch loop.** Read the request list between launches,
  page in from the texture/FITS source, re-launch until resolved.
- **C. Overflow gate.** A scene whose texture working set exceeds a synthetic VRAM
  cap renders correctly (matches the fully-resident reference within noise) with a
  bounded resident page budget.

---

## Acceptance criteria

- [ ] Phase-0 license verification recorded (OTK `LICENSE.txt` == BSD-3) **and** an
      observed-overflow trigger documented before any implementation.
- [ ] Sparse-texture backing + device request list (atomic append on unresolved page).
- [ ] Host services requests between launches; re-launch loop converges (all sampled
      pages resolve).
- [ ] Overflow scene renders correctly within a bounded resident page budget (image
      == fully-resident reference within noise).
- [ ] No OptiX dependency introduced; pure-CUDA sparse-texture path only.
- [ ] No regression when textures fit (demand path is a no-op / off).

---

## Non-goals

- **Not demand-loaded geometry.** OTK's geometry demand loading is OptiX-tied —
  explicitly excluded.
- **Not whole-buffer host mapping.** That is pkg132 (the prerequisite cheaper tier);
  pkg135 is page-granularity texture streaming.
- **Not a pre-emptive build.** Conditional package — no implementation until overflow
  is observed in practice.

---

## Algorithm sourcing (CLAUDE.md §6)

- **NVIDIA OptiX Toolkit — DemandLoading** `github.com/NVIDIA/optix-toolkit` —
  **BSD-3-Clause (per README; `LICENSE.txt` VERIFY at phase 0)**. CUDA sparse
  textures + device request list + inter-launch host servicing; the sparse-texture /
  request-list machinery is CUDA-level (no OptiX). Demand-loaded geometry is OptiX-
  tied and out of scope.
- **Garanzha et al.**, "Out-of-core GPU ray tracing of complex scenes" (2011) —
  foundational out-of-core reference.
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §4
  priority 2 + adoption rank 7 ("only when texture overflow is observed").

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §4, adoption rank 7). Owner
goal: render texture-heavy astrophysical scenes (large FITS cubes) that exceed VRAM.
**Conditional** — dormant until overflow is observed; pkg132 is the first line of
defense.

---

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: still-open (dormant/conditional) — not implemented and intentionally not queued; activates only if texture overflow is actually observed on real astro scenes (never triggered). Only the spec-filing PR #492 exists. **CONDITIONAL**: this package activates **only when texture overflow is actually observed** on real astrophysical scenes (large FITS cubes). Until then it stays filed-but-dormant. Do not implement pre-emptively.

- [ ] Phase 0 — OTK license verification + observed-overflow trigger.
- [ ] A — sparse-texture backing + device request list.
- [ ] B — host page servicer + re-launch loop.
- [ ] C — overflow gate within a bounded resident page budget.

---

## Lessons

*(Fill in after the package is done.)*
