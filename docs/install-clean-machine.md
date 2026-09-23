# Clean-machine install (Pillar-4 exit gate (f))

Gate (f) is met only by evidence produced on a machine that has **no Astroray
build toolchain and no source checkout**: a fresh Blender profile, the release
ZIP installed through Blender's own extension installer, and one F12 render.

This document is the procedure. The capture/validator is
`scripts/validate_clean_install.py`; its output is
`docs/blender_parity/evidence/install-clean-machine/checks.json`.

## Why the developer checkout cannot produce this evidence

`scripts/validate_clean_install.py` checks the host before trusting any capture:

* `no_toolchain` — no `cl` / `cmake` / `nvcc` / `ninja` / `make` / `gcc` on `PATH`;
* no source-tree fallback — no `CMakeLists.txt`, `src/`, `include/` or `build_cuda/`
  next to the addon (so the addon cannot silently import a local build).

A developer machine fails both, so the validator reports it `ineligible` and the
five checks stay `unmeasured`. That is the correct result here — never a
fabricated clean machine.

## Procedure (clean host)

1. Install Blender (same major version as the pinned oracle, e.g. 5.2).
2. Launch it with a **fresh profile** (a new `BLENDER_USER_CONFIG` directory, or a
   machine that has never had Astroray installed). Confirm no `astroray` addon and
   no Astroray user-preference entry exist.
3. Record the release ZIP and its SHA-256:
   `Get-FileHash dist\astroray-<version>.zip -Algorithm SHA256`.
4. Install the ZIP through **Blender's extension installer**
   (`Edit > Preferences > Add-ons > Install from Disk…` for the ZIP, or
   `blender --command extension install-file <zip>`), not `scripts/dev_addon.ps1`
   and not a source path.
5. Open a scene and press **F12** once; confirm it exits 0 and the PNG is written.
6. Save the five artifacts next to `checks.json` (names fixed by
   `scripts/validate_clean_install.py`):
   * `profile_fresh.json` — profile listing with no `astroray` addon/userpref;
   * `zip_sha256.txt` — the ZIP digest;
   * `installer.log` — extension-installer output showing the installed path;
   * `toolchain_absent.txt` — `where cl`, `where cmake`, `where nvcc` all empty;
   * `f12.png` — the F12 render.
7. Each artifact is a JSON probe with `schema: "pkg278.clean_install_probe.v1"`
   and its matching `check` name. Record the artifact name in `evidence_path`
   and its SHA-256 in `evidence_sha256`; do not add a manual pass flag. The
   validator derives the result: fresh-profile probes record both addon and
   userpref absence; ZIP probes record the captured ZIP digest; installer probes
   name `blender_extension_installer` and reject source paths; host probes list
   toolchain programs and source fallback; F12 probes record exit code zero plus
   image path and SHA-256. Capture and hash the probes in one command, for
   example `python scripts/validate_clean_install.py --zip release.zip --probe
   fresh_profile=profile_fresh.json --probe zip_identity=zip_identity.json
   --probe installer_path=installer.json --probe no_toolchain=host.json --probe
   f12_exit_zero=f12_result.json`.
8. Validate: `python scripts/validate_clean_install.py --validate`.
   Every mandatory check must be GREEN for gate (f) to be green.

## Checks (hash-locked, all mandatory)

| Check | Meaning |
|---|---|
| `fresh_profile` | no prior `astroray` addon or user-preference entry |
| `zip_identity` | installed ZIP SHA-256 equals the recorded build artifact |
| `installer_path` | installed through Blender's extension installer, not `dev_addon.ps1`/source |
| `no_toolchain` | no build toolchain present and no source-tree fallback imported |
| `f12_exit_zero` | F12 exits 0 and writes the pinned PNG |

A missing or hash-mismatched artifact is RED; an unmeasured check is never green.
