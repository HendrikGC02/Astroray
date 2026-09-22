- **Lines 133–146:** The line proposal has no defined renderer-wide sampling hook; existing hero wavelengths are chosen before a ray identifies a medium, so per-medium/per-voxel mixture weights cannot supply a correct global PDF. Fix: specify a scene-level line proposal, selection probabilities, per-lane PDF replacement, and bounded-band profile renormalisation.

- **Lines 174–179, 185–202:** No acceptance test requires an actual Blender export/F12 render, nor defines how the named preset is selected or how per-line raw outputs are isolated. Fix: require a headless Blender CPU slab fixture using the preset, saved raw Hα/Hβ channels, and external comparison to `I=jL`.

- **Lines 7, 84–88:** The spec says pkg243 is consumed but “not blocked,” contradicting Stage 1c’s mandatory length/emissivity-to-radiance contract before every quantitative Stage 2 result. Fix: make pkg251→pkg243 Phase 1 an explicit blocking prerequisite for all ratio and absolute-normalisation gates.

- **Lines 158–160:** The hard-coded line list disagrees with pkg45’s eight-entry contract (it adds Hγ and omits [SII] 673.1). Fix: load line identities, air wavelengths, and units exclusively from pkg45 metadata; reject schema mismatch.

NO — Blender cannot yet be shown to reproduce independently normalised Case-B lines without narrow-line sampling bias under this specification.

VERDICT: REVISE - define the global unbiased sampler and mandatory Blender quantitative path, then align prerequisites and metadata.
