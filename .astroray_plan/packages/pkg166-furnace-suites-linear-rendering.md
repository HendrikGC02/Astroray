# pkg166 — furnace/energy suites render gamma and are structurally blind to energy GAIN: convert to linear + upper bounds + a naming guard

**Pillar:** 3 (test hygiene / energy conservation gating)
**Track:** A (CPU-gated on CI; any GPU-leg re-pins RTX-verified at closeout)
**Status:** done (PR #538, 2026-08-02) — all *furnace*/*energy* in-process render tests converted to linear with floor+ceiling pairs; autouse naming guard + negative self-test landed; 315 passed / 5 xfailed on the converted suites; 1.5x BSDF mutation caught by the white-metal furnace case (1.156 > 1.02). REAL FINDING surfaced: Disney glass transmission furnace creates energy (CPU 1.10–1.78, GPU rough up to 2.30, gamma hid it) — those 3 cases xfail'd against the conserving band, NOT pinned in; needs an architect-filed follow-up (Disney glass transmission energy gain, CPU+GPU).
**Estimated effort:** S–M (the conversion is mechanical; the work is re-pinning 278 param-case expected values on linear output and justifying each shift)
**Depends on:** nothing open. Motivated by PR #534's full HW sweep (2026-08-02) and memory `gamma-furnace-cannot-detect-energy-gain` (pkg160, 2026-07-26).

**Origin:** PR #534 full hardware sweep (team-lead, 2026-08-02). pkg120 —
which ADDS energy by restoring the two-sided MIS term — sailed through every
shipped furnace/energy suite green; only pkg120's own purpose-built linear gate
actually measured the gain. That is the exact failure mode that kept pkg160's
energy-creating conductor invisible: `render_image()` defaults to
`apply_gamma=True`, which clamps to [0, 1], so a gamma-rendered furnace reads
**max exactly 1.000000** while the linear truth was 4.139 with 18,338 of 27,648
pixels above 1.0 (pkg160 HW record). A gamma furnace can only ever catch energy
LOSS, never GAIN — structurally, not statistically.

---

## Affected suites (the known set — sweep for stragglers, don't trust this list as exhaustive)

- `test_dielectric_glass_furnace`
- `test_disney_rough_glass_furnace`
- `test_disney_energy_conservation`

Together 278 param cases as of PR #534's sweep. **Also grep the whole test tree**
for any other test matching `*furnace*` or `*energy*` that renders through
`render_image()`/`render()` without an explicit `apply_gamma=False` — the guard
in item 3 below defines the final authoritative set.

## Deliverables

1. **Convert the suites to linear rendering** (`apply_gamma=False` explicit,
   never default-relied) **and assert an UPPER bound as well as a floor** on
   every furnace/energy case. A furnace test that only asserts `>= floor` is
   still half-blind even in linear; the pair is the contract
   (memory `gamma-furnace-cannot-detect-energy-gain` records both halves).
2. **Re-pin expected values on linear output.** They WILL shift — that is the
   work, not a surprise. Rules for the re-pin:
   - Each shifted pin gets a one-line justification in the test (old gamma
     value → new linear value, and why the delta is the gamma transfer, not a
     behaviour change).
   - Re-pin against the CURRENT main build only; if any case reads > 1.0 in
     linear where physics says it must not, that is a REAL finding — stop, file
     it (do not pin an energy gain into the expected values), and mark the case
     xfail pointing at the filed package. Do NOT widen a band to make a gain
     pass.
   - CPU cases re-pin on CI; any GPU-leg cases re-pin from an RTX run at
     closeout (CI has no GPU — memory `ci_has_no_gpu_runtime_blindspot`).
3. **Naming guard:** a small pytest-level check (conftest helper or
   collection-time assert — smallest thing that works, simplicity tax applies)
   that any test whose name matches `*furnace*` or `*energy*` renders linear.
   Implementation freedom: an explicit marker + assert, or a fixture that
   inspects the call — but it must FAIL loudly at test time when a future
   furnace test renders gamma, not merely document the convention. Add one
   negative self-test proving the guard fires.
4. **Doc note:** one short paragraph in the testing conventions doc (wherever
   furnace-test guidance lives; create a `## Furnace/energy tests` section in
   `AGENTS.md` or the test README if none exists) stating the rule and citing
   the pkg160 4.139-reads-as-1.000000 record.

## Acceptance

- All converted suites green on CI in linear with floor+ceiling pairs; no case
  passes via a widened band (diff review — every band change carries its
  justification line).
- The naming guard demonstrably fires on a deliberately-gamma furnace test
  (negative self-test) and is silent on the full suite.
- A deliberate energy-gain mutation (e.g. locally scaling a BSDF return by
  1.5× in a scratch build) is caught by at least one converted furnace case —
  run once as evidence in the PR, not committed as a test.

## Non-goals

- Changing any renderer/gamma behaviour — `render_image()`'s default stays;
  this package touches tests and the guard only.
- Re-opening pkg120 or pkg160 — both shipped correct linear gates of their own;
  this package generalizes their lesson.
- Project-wide parity-band tightening (separate open owner decision).

## Provenance

Filed by the architect 2026-08-02 at team-lead request, from PR #534's full HW
sweep finding. Canonical failure record: memory
`gamma-furnace-cannot-detect-energy-gain` (pkg160, PR #527, 2026-07-26).
