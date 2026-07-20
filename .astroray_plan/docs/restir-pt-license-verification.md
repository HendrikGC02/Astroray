# ReSTIR_PT reference-repo license verification (pre-C6 gate)

**Date:** 2026-07-20
**Verified by:** architect agent (overnight strategy review)
**Why:** `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` §5 requires the
license of `github.com/DQLin/ReSTIR_PT` to be verified and the result saved to
this docs folder **before Session C6 writes reservoir code** (CLAUDE.md §6).

## Result: BSD-3-Clause — CLEARED for mirroring

- **Repo:** `https://github.com/DQLin/ReSTIR_PT` — reference implementation of
  **GRIS / ReSTIR PT** (Lin, Kettunen, Bitterli, Pantaleoni, Yuksel, Wyman,
  "Generalized Resampled Importance Sampling: Foundations of ReSTIR," ACM ToG
  41(4), SIGGRAPH 2022, DOI 10.1145/3528223.3530158), implemented as the
  `ReSTIRPTPass` render pass on Falcor 4.4.
- **License file:** `LICENSE.md` at repo root (fetched raw from
  `raw.githubusercontent.com/DQLin/ReSTIR_PT/master/LICENSE.md`, 2026-07-20).
  Standard **BSD 3-Clause** text; copyright holder is **NVIDIA CORPORATION**
  (first line verbatim: "Copyright (c) 2020, NVIDIA CORPORATION. All rights
  reserved."), with the standard three BSD conditions (notice retention,
  binary-redistribution notice, no-endorsement) and liability disclaimer.
- **Verdict:** BSD-3-Clause is on the CLAUDE.md §6 allow-list. Session C6 MAY
  read and mirror ReSTIR_PT code with attribution ("DQLin/ReSTIR_PT
  `<file>` (BSD-3-Clause)") in comments at the port site.

## Standing constraints (unchanged)

- **NVIDIA RTXDI remains DISQUALIFIED** (proprietary, `RTXDI LICENSE.txt §4(e)`,
  verified 2026-07 research sweep). Do not read or mirror RTXDI regardless of
  the ReSTIR_PT clearance — they are different repos under different licenses.
- Per the Phase C plan §5, the **primary generator for C6 is still our own CPU
  ReSTIR-DI code** (`plugins/integrators/restir_di.cpp`,
  `include/astroray/restir/reservoir.h`) refactored `__host__ __device__` under
  the one-generator rule; ReSTIR_PT is the *permitted reference* for reservoir
  SoA/reuse-stage structure, and GRIS is the citation. Scope stays Bitterli-2020
  ReSTIR DI — no path-space GRIS in Phase C.
- Note ReSTIR_PT is Falcor-based (Slang shaders); expect to consult its
  reservoir/reuse logic for structure, not to transplant Falcor code verbatim.
