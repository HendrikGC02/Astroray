"""pkg109 — world-space photon-map kd-tree: numeric-core prototype.

Validates the balanced kd-tree build + k-nearest-neighbour query + Jensen 1996
density (irradiance) estimate in float64 vs a brute-force reference, BEFORE the
C++ port (CLAUDE.md §6 discipline; the same Python-first validation caught every
bug in pkg106).

References (cited in the C++ header too):
  - Jensen, "Global Illumination using Photon Maps", EGWR 1996. The surface
    radiance/irradiance estimate E(x) = (1 / (pi r^2)) * sum_p Phi_p over the k
    nearest photons, r = distance to the farthest of the k.
  - Jensen, "Realistic Image Synthesis Using Photon Mapping", 2001 — the
    balanced kd-tree (median split on the largest-extent axis) + locate_photons
    k-NN with a bounded max-heap and plane-distance pruning.
  - Balanced-median in-place layout mirrors pbrt-v3's photon kd-tree / nth_element
    partitioning (BSD).

The kd-tree here is written to port DIRECTLY to C++: an in-place reordered photon
array + a per-node split axis, with implicit subtree ranges (root = mid of the
range, children = the two halves), so the query recursion recomputes `mid` exactly
as the build did — no child pointers needed.
"""

import numpy as np

# --------------------------------------------------------------------------- #
# Balanced kd-tree (3D), in-place, implicit subtree ranges.
# --------------------------------------------------------------------------- #


class PhotonMap:
    def __init__(self, positions):
        # positions: (N,3) float64. Reordered in place during build.
        self.pos = np.asarray(positions, dtype=np.float64).copy()
        self.n = self.pos.shape[0]
        # axis[i] = split axis chosen at the node whose subtree-root index is i.
        self.axis = np.full(self.n, -1, dtype=np.int32)
        # payload index that travels with each position (so callers can recover
        # the original photon after the in-place reorder).
        self.idx = np.arange(self.n, dtype=np.int64)
        if self.n > 0:
            self._build(0, self.n - 1)

    def _build(self, lo, hi):
        if lo > hi:
            return
        sub = self.pos[lo : hi + 1]
        extent = sub.max(axis=0) - sub.min(axis=0)
        axis = int(np.argmax(extent))
        mid = (lo + hi) // 2
        # Partition [lo,hi] so that element `mid` is the median along `axis`
        # (np.argpartition gives the same selection nth_element would in C++).
        order = np.argpartition(self.pos[lo : hi + 1, axis], mid - lo)
        self.pos[lo : hi + 1] = self.pos[lo : hi + 1][order]
        self.idx[lo : hi + 1] = self.idx[lo : hi + 1][order]
        self.axis[mid] = axis
        self._build(lo, mid - 1)
        self._build(mid + 1, hi)

    def knn(self, q, k):
        """Return (indices_into_reordered_array, squared_dists) of the k nearest
        photons to q, sorted by distance. Mirrors the C++ bounded-max-heap query.
        """
        q = np.asarray(q, dtype=np.float64)
        # bounded max-heap as parallel arrays; we keep it simple in the prototype
        # (the C++ uses a real binary max-heap of size k).
        heap_d2 = []  # squared distances
        heap_i = []   # node indices

        def consider(i):
            d2 = float(np.sum((self.pos[i] - q) ** 2))
            if len(heap_d2) < k:
                heap_d2.append(d2)
                heap_i.append(i)
            elif d2 < max(heap_d2):
                j = int(np.argmax(heap_d2))
                heap_d2[j] = d2
                heap_i[j] = i

        def worst():
            return max(heap_d2) if heap_d2 else np.inf

        def search(lo, hi):
            if lo > hi:
                return
            mid = (lo + hi) // 2
            axis = self.axis[mid]
            consider(mid)
            delta = q[axis] - self.pos[mid][axis]
            if delta < 0.0:
                near, far = (lo, mid - 1), (mid + 1, hi)
            else:
                near, far = (mid + 1, hi), (lo, mid - 1)
            search(*near)
            if len(heap_d2) < k or delta * delta < worst():
                search(*far)

        search(0, self.n - 1)
        d2 = np.array(heap_d2)
        ii = np.array(heap_i)
        srt = np.argsort(d2)
        return ii[srt], d2[srt]

    def irradiance(self, q, k, powers):
        """Jensen 1996 density estimate at q: E = (sum_p Phi_p) / (pi r^2),
        r^2 = farthest of the k nearest. `powers` is per-photon flux aligned to the
        REORDERED array (use self.idx to map from original)."""
        ii, d2 = self.knn(q, k)
        if ii.size == 0:
            return 0.0
        r2 = float(d2[-1])
        if r2 <= 0.0:
            return 0.0
        return float(np.sum(powers[ii])) / (np.pi * r2)


# --------------------------------------------------------------------------- #
# Brute-force reference (the pytest oracle).
# --------------------------------------------------------------------------- #


def brute_knn(positions, q, k):
    d2 = np.sum((positions - q) ** 2, axis=1)
    order = np.argsort(d2, kind="stable")[:k]
    return order, d2[order]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def main():
    rng = np.random.default_rng(20260529)
    n = 4000
    k = 20
    positions = rng.uniform(-5.0, 5.0, size=(n, 3))

    pm = PhotonMap(positions)

    # 1) k-NN set correctness vs brute force.
    max_radius_err = 0.0
    set_mismatch = 0
    n_queries = 300
    for _ in range(n_queries):
        q = rng.uniform(-6.0, 6.0, size=3)
        ii, d2 = pm.knn(q, k)
        # map reordered -> original photon ids
        kd_ids = set(int(pm.idx[i]) for i in ii)
        bf_ids_order, bf_d2 = brute_knn(positions, q, k)
        bf_ids = set(int(j) for j in bf_ids_order)
        if kd_ids != bf_ids:
            set_mismatch += 1
        # enclosing radius must match the k-th brute distance
        max_radius_err = max(max_radius_err, abs(float(d2[-1]) - float(bf_d2[-1])))

    print(f"[knn] queries={n_queries} k={k} set_mismatches={set_mismatch} "
          f"max_radius_err={max_radius_err:.3e}")
    assert set_mismatch == 0, "kd-tree k-NN set must match brute force exactly"
    assert max_radius_err < 1e-9, "enclosing radius must match brute force"

    # 2) Density estimate: uniform photons on a unit-flux plane.  With N photons
    # spread over area A and unit power each, the true areal flux density is N/A.
    # Jensen's estimate at an interior point should converge to that density.
    side = 4.0
    npl = 40000
    plane = np.zeros((npl, 3))
    plane[:, 0] = rng.uniform(-side / 2, side / 2, size=npl)
    plane[:, 2] = rng.uniform(-side / 2, side / 2, size=npl)
    powers_plane = np.full(npl, 1.0)
    pmp = PhotonMap(plane)
    # remap powers to the reordered array
    powers_reordered = np.empty(npl)
    powers_reordered[np.arange(npl)] = powers_plane[pmp.idx]
    true_density = npl / (side * side)
    est = [pmp.irradiance(np.array([x, 0.0, 0.0]), 200, powers_reordered)
           for x in (-1.0, 0.0, 1.0)]
    mean_est = float(np.mean(est))
    rel_err = abs(mean_est - true_density) / true_density
    print(f"[density] true={true_density:.2f} est={mean_est:.2f} "
          f"rel_err={rel_err:.3%}")
    assert rel_err < 0.10, "density estimate must converge to true areal density"

    print("OK — pkg109 photon-map numeric core validated vs brute force.")


if __name__ == "__main__":
    main()
