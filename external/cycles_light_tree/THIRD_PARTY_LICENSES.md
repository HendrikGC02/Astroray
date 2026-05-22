# Third-Party Licenses — Cycles Light Tree

## Blender Cycles Light Tree

**License:** Apache-2.0  
**Copyright:** 2011-2022 Blender Foundation  
**Upstream repository:** https://github.com/blender/blender  
**Upstream commit:** e52e5eb06f6b24055f0e7508bc7d7278e139ba0f (2026-05-22)

### Files Mirrored

All files are mirrored from `intern/cycles/` in the Blender repository:

- `scene/light_tree.h` → `external/cycles_light_tree/scene/light_tree.h`
- `scene/light_tree.cpp` → `external/cycles_light_tree/scene/light_tree.cpp`
- `kernel/light/tree.h` → `external/cycles_light_tree/kernel/light/tree.h`

Each file preserves its original Apache-2.0 license header (`SPDX-FileCopyrightText: 2011-2022 Blender Foundation` and `SPDX-License-Identifier: Apache-2.0`).

### Algorithm Reference

**Paper:** Alejandro Conty Estevez & Christopher Kulla, "Importance Sampling of Many Lights with Adaptive Tree Splitting", Proc. ACM Comput. Graph. Interact. Tech. 1(2): 25:1-25:17 (2018), DOI [10.1145/3233305](https://dl.acm.org/doi/10.1145/3233305).

The Conty 2018 importance metric combines cluster energy, inverse-squared distance, and orientation cone bounding to guide probabilistic tree traversal. The Cycles implementation (Apache-2.0) is the canonical open-source reference we mirror for pkg86.

### License Compatibility

Apache-2.0 is compatible with Astroray's MIT license (CLAUDE.md §6). The Apache-2.0 license allows redistribution and modification under the terms of the Apache License 2.0. Astroray's use of these sources complies with Apache-2.0 requirements by:

1. Preserving original copyright notices and license headers in all mirrored files.
2. Recording this attribution in `external/cycles_light_tree/THIRD_PARTY_LICENSES.md`.
3. Citing the source in Astroray's C++ implementation at every call site that mirrors Cycles functions.

Full Apache-2.0 license text: https://www.apache.org/licenses/LICENSE-2.0
