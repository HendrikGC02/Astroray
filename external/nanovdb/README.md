# Vendored NanoVDB subset

Source: https://github.com/AcademySoftwareFoundation/openvdb
Release tag: **v12.0.0**
Subtree: `nanovdb/nanovdb/` (upstream path), vendored here under
`external/nanovdb/nanovdb/` so that `#include <nanovdb/...>` resolves when
`external/nanovdb` is on the include path.

License: Apache-2.0 (see `LICENSE`). Every header retains its original
`SPDX-License-Identifier: Apache-2.0` banner and is **unmodified**.

## Why a subset

The full OpenVDB library (MPL-2.0 + Boost/TBB/Blosc) is intentionally NOT
linked. NanoVDB is header-only and provides a native grid *builder*
(`nanovdb::tools::build::Grid` + `nanovdb::tools::createNanoGrid`) that lets the
engine build a sparse grid directly from dense arrays handed over by the Blender
addon — no `.vdb` file reader and no OpenVDB dependency. The OpenVDB-import code
path inside `tools/CreateNanoGrid.h` is guarded by `NANOVDB_USE_OPENVDB`, which
Astroray never defines.

## Vendored files (21)

Obtained by a breadth-first download over the `#include <nanovdb/...>` closure of
the seed headers `tools/CreateNanoGrid.h`, `tools/GridBuilder.h`, `HostBuffer.h`,
`GridHandle.h`, `NodeManager.h`:

```
nanovdb/GridHandle.h
nanovdb/HostBuffer.h
nanovdb/NanoVDB.h
nanovdb/NodeManager.h
nanovdb/cuda/DeviceBuffer.h          (guarded by __CUDACC__)
nanovdb/cuda/GridHandle.cuh          (guarded by __CUDACC__)
nanovdb/cuda/NodeManager.cuh         (guarded by __CUDACC__)
nanovdb/math/DitherLUT.h
nanovdb/math/Math.h
nanovdb/tools/CreateNanoGrid.h
nanovdb/tools/GridBuilder.h
nanovdb/tools/GridChecksum.h
nanovdb/tools/GridStats.h
nanovdb/tools/cuda/GridChecksum.cuh  (guarded by __CUDACC__)
nanovdb/util/ForEach.h
nanovdb/util/Invoke.h
nanovdb/util/PrefixSum.h
nanovdb/util/Range.h
nanovdb/util/Reduce.h
nanovdb/util/Util.h
nanovdb/util/cuda/Util.h             (CUDA helpers)
```

The `cuda/*.cuh` headers are included only under `#if defined(__CUDACC__)`; the
host-only CPU TU that consumes NanoVDB in this package
(`src/volume/grid_medium.cpp`) never triggers them. They are vendored so the
closure is complete for the later GPU stage (pkg269).

## How to re-vendor / bump the tag

Re-run the BFS downloader against a new tag (base URL
`.../openvdb/<tag>/nanovdb/nanovdb`), seeding from the headers above, and refresh
`LICENSE` and this file's tag line. Keep every SPDX header intact.
</content>
