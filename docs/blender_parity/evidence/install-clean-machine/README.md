# Gate (f) clean-machine evidence

This directory holds the hash-locked evidence for the Pillar-4 exit gate (f)
(clean-machine install), produced by `scripts/validate_clean_install.py` on a
host with **no build toolchain and no source checkout**. See
`docs/install-clean-machine.md` for the procedure.

`checks.json` is the capture: the five mandatory checks
(`fresh_profile`, `zip_identity`, `installer_path`, `no_toolchain`,
`f12_exit_zero`), each pointing at an artifact with its SHA-256, plus the
machine-eligibility block.

Status on the developer checkout (2026-09-23): **ineligible** — this machine has
a build toolchain and a source tree, so it cannot produce gate (f) evidence. The
checks are `unmeasured`, not green. The parent orchestration runs the capture on
a clean host and replaces this file with the real evidence.
