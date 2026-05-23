# pkg76-followup-classroom-fidelity — Classroom .blend import fidelity audit

**Pillar:** 0 (infrastructure / verification)
**Track:** A
**Status:** open
**Estimated effort:** 1–2 days
**Depends on:** pkg100 (.blend importer dynamic-attr fix, shipped Round 12), pkg76 CSV (PR #357, open)
**Reference research:** Cycles `intern/cycles/blender/sync.cpp`, `intern/cycles/blender/mesh.cpp`, `intern/cycles/blender/material.cpp` (Apache-2.0) — the reference shader graph + mesh + material walk that Astroray's `tools/blend_import/` mirrors at parity-scope.

---

## Why this package exists

PR #357 (pkg76 CSV) ran the parity harness for Classroom + Junkshop + BMW27 on RTX 5070 Ti. Result on 2026-05-24:

| Scene | SPP | SSIM vs Cycles-CPU EXR | Status |
|-------|-----|------------------------|--------|
| Junkshop | 240 | **0.972** | PASS (≥0.85 gate) |
| Classroom | 300 | **0.470** | FAIL (well below gate) |
| BMW27 | 1024 | — (crash) | Importer gap (`poly_offset_indices`; see pkg76-followup-bmw27) |

**Classroom is the focus of THIS package.** The render completes (0.90 s / 951 MB peak) but the resulting image diverges structurally from the Cycles-CPU reference well beyond the per-scene 0.85 gate. The render is not crashing or NaN-laden — the result is *plausible-looking* but doesn't match. That signals an import-fidelity gap (material, lighting, or geometry semantics) rather than a render bug.

The 0.85 gate already accounts for parity-scope import limitations (shader-graph + procedural-texture fidelity loss). 0.47 is far enough below that the gap is likely concrete and identifiable — not a calibration issue.

---

## Goal

**Before:** Classroom imports, renders, but SSIM 0.47 vs Cycles-CPU EXR. The discrepancy is unattributed.

**After:**
- A visual diff (side-by-side or per-pixel delta map) localizing the divergence (materials? lights? geometry? texture? camera?).
- A short audit document at `.astroray_plan/docs/pkg76-classroom-fidelity-audit.md` listing each identified gap with a Cycles source-file reference + a triage classification:
  - **(a) Fixable in parity scope** — concrete importer change that closes the gap (small to medium effort).
  - **(b) Out-of-parity-scope** — needs a feature beyond what pkg76 specifies (file a separate package).
  - **(c) Already known limit** — documented in pkg76 spec § parity-scope import (no action).
- For each (a) gap, either ship the fix as a follow-up commit in this package OR file a separate follow-up package if the fix is non-trivial.
- Re-run the Classroom parity row and measure the new SSIM.

**Acceptance:**
- Audit document committed with at least 3 itemized gaps + classifications.
- At least one (a) gap closed and re-measured in the parity CSV.
- Either: Classroom SSIM ≥0.85 (the gate), OR: explicit documentation that the remaining (a)+(b) gaps explain the residual divergence and the gate is unreachable at parity scope (in which case, file a `pkg76-classroom-scope-expansion` follow-up).

---

## Specification

### 1. Visual diff

Run both renders side by side (Cycles-CPU reference EXR + astroray-GPU render). Tools:
- `python tools/image_diff.py` if present, or use a quick Python script with `cv2.absdiff` + colormap.
- Save the diff PNG to `test_results/pkg76-classroom-diff.png`.
- Read it via Claude's multimodal capability to identify what's different (lighting brightness? texture? specular highlights? wall color?).

### 2. Import audit — read both sides

For each suspected divergence axis, compare what Astroray imported vs what Cycles parses:
- **Materials**: dump Astroray's material list (use Python bindings or a small dump tool) and grep the .blend SDNA for `Material` blocks. Confirm albedo, metallic, roughness, IOR, transmission carry over.
- **Lights**: dump scene lights; check type (point/sun/spot/area), color, energy, direction. Classroom has a window + ceiling lights — common gap point.
- **World**: `ShaderNodeBackground` color + strength. If the `.blend` uses node-tree-driven world (use_nodes=True), Astroray might fall back to a default.
- **Camera**: focal length, sensor size, world transform. Subtle camera drift produces SSIM-killing pixel shift.
- **Geometry**: vertex count, polygon count vs Cycles. Catches subdivision-surface or modifier-stack gaps.

### 3. Classify + report

For each gap found, write to `pkg76-classroom-fidelity-audit.md`:
```markdown
### Gap N: <name>
- **Symptom:** what looks different in the diff
- **Astroray imported:** <value>
- **Cycles parses:** <value>
- **Cycles reference:** `intern/cycles/blender/<file>.cpp:<line>` describing the parse
- **Classification:** (a) fixable in scope / (b) out-of-scope / (c) known limit
- **Proposed fix:** (one-liner per (a) gap)
```

### 4. Close the cheapest (a) gap

Pick the highest-impact + lowest-cost (a) gap. Implement the fix in `tools/blend_import/`. Re-run the Classroom parity. Append the new measurement row to `benchmarks/cycles-parity/2026-05-24-pkg76-csv-astroray-gpu.csv` (or a dated successor).

If the SSIM jumps over 0.85, this package CLOSES the Classroom gate.
If not, document the residual divergence — the remaining (a)+(b) gaps tell us how much more work is needed.

---

## Tests

- The audit document IS the deliverable test artifact.
- The parity-row re-measurement is the quantitative test.
- No unit tests required — this is an investigative + targeted-fix package.

---

## Acceptance criteria

- [ ] `test_results/pkg76-classroom-diff.png` committed (visual diff between Astroray-GPU and Cycles-CPU reference).
- [ ] `.astroray_plan/docs/pkg76-classroom-fidelity-audit.md` committed with ≥3 itemized gaps + Cycles citations + classifications.
- [ ] At least one (a) gap closed in `tools/blend_import/` with a commit citing the Cycles reference.
- [ ] New Classroom parity row measured + appended to the parity CSV.
- [ ] Either: Classroom SSIM ≥0.85 (gate closed), OR: explicit residual-gap documentation in the audit doc explaining what's still missing.
- [ ] No regression on Junkshop SSIM (re-measure to confirm).

---

## Non-goals

- Full shader-graph import (general `ShaderNodeTree` evaluation) — that's a much larger pkg57 follow-up.
- Procedural-texture-driven materials — Classroom may use these; document as (b) out-of-scope.
- Hair / particles / volumetrics (if Classroom has any) — Astroray doesn't import these; out-of-scope.
- Subdivision-surface evaluation — if Classroom uses subsurf modifiers, evaluate at viewport quality; full Catmull-Clark is a separate package.

---

## References

- pkg76 spec: `.astroray_plan/packages/pkg76-blend-importer-parity-scope.md` (the parity-scope contract this follow-up extends).
- PR #357: the CSV row that surfaced the 0.47 SSIM measurement.
- Cycles `intern/cycles/blender/sync.cpp` — scene-walk entry point (Apache-2.0).
- Cycles `intern/cycles/blender/mesh.cpp` — mesh import (Apache-2.0).
- Cycles `intern/cycles/blender/material.cpp` — material import + node-graph walk (Apache-2.0).
- Blender 4.x Mesh Module docs — for layout-storage-version differences (also referenced by pkg76-followup-bmw27).
- Classroom .blend — `benchmarks/cycles-parity/blends/classroom.blend` (or wherever pkg76 caches it).

---

## Filed by

team-lead overnight run, 2026-05-24, after PR #357 surfaced the Classroom 0.47 SSIM measurement. Filed alongside `pkg76-followup-bmw27-poly-offset-indices` (the importer crash for the third scene).
