# pkg205 — UnicodeEncodeError console test hygiene (cp1252 print() glyphs)

**Pillar:** Infrastructure / test hygiene
**Track:** A (small local fix — no engine code, no GPU, no physics)
**Status:** open (filed 2026-08-19).
**Estimated effort:** XS.
**Depends on:** nothing.

## Goal

Three pre-existing test failures throw `UnicodeEncodeError` when they `print()`
non-ASCII glyphs (π / ✓ / λ and similar) under the default Windows console
encoding (cp1252). This is a **test-harness output bug, not an engine defect**:
the assertions themselves are fine; the test crashes in the diagnostic `print()`
before it can pass. Make the affected tests pass under a cp1252 console.

## Specification

1. **Identify the exact failing tests first.** Run the suite under a cp1252
   console (the default Windows shell — do NOT pre-set `PYTHONIOENCODING=utf-8`,
   that would mask the bug) and capture the three tests whose failure traceback
   ends in `UnicodeEncodeError` from a `print()` / `sys.stdout.write`. Record the
   three test node-ids in the PR before touching anything. (Known candidate
   modules containing non-ASCII `print()` glyphs, to be confirmed, not assumed:
   `tests/test_pkg182_conductor_spectral_native.py`,
   `tests/test_blender_parity_matrix.py`, `tests/test_cryptomatte_pass.py`,
   `tests/statistical/test_disney_diffuse_pdf.py` — verify which three actually
   raise `UnicodeEncodeError`; only touch the ones that do.)

2. **Fix surgically, one of two ways per test (implementer's choice, minimal
   diff — CLAUDE.md §3):**
   - **Preferred where the glyph is cosmetic:** replace the offending non-ASCII
     glyph in the `print()` string with an ASCII equivalent (`pi`, `[OK]`,
     `lambda`, `<=`, `->`, etc.). No global state, no side effects.
   - **Where the glyph is load-bearing to the message:** guard the module with
     `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at import time
     (Python 3.7+; wrap in a `try/except AttributeError` for safety). Do this
     only in the specific failing module(s), not repo-wide.
   Do NOT add a repo-wide `conftest.py` stdout override — keep the blast radius
   to the three affected tests (memory / CLAUDE.md §3 surgical changes).

3. **Do not change any assertion, tolerance, or engine behaviour.** This is a
   `print()`-encoding fix only.

## Acceptance

- [ ] The three previously-`UnicodeEncodeError` tests are named in the PR and now
  **PASS** when run under the default cp1252 Windows console (show the
  before/after run output; the "before" must show the `UnicodeEncodeError`).
- [ ] No other test's pass/fail status changes (`pytest` on the affected files +
  a representative broader run; diff the pass count).
- [ ] The diff touches only test files, only `print()`/output lines. No engine
  code, no `.pyd` rebuild, no GPU leg required (CI-gate only).
- [ ] CI green on all matrix jobs (`gh run view` on HEAD).

## Non-goals

- **No repo-wide console/encoding refactor**, no `conftest.py` global override,
  no `.gitattributes`/locale changes.
- **No fixing of any genuinely-failing assertion** — if any of the three tests
  fails for a reason OTHER than a `print()` `UnicodeEncodeError`, leave it,
  report it, and file it separately (it is out of scope for this hygiene chip).

## Provenance

Filed by the architect 2026-08-19 from STATUS.md (2026-08-14 → 08-15 closeout,
"Known-issue hygiene item") and NEXT_STAGE_REPORT §2 item 9. Pure open-model
grunt-work candidate per CLAUDE.md §5 cost routing: bounded, self-verifying,
no HW, behind the pytest + CI gate.
