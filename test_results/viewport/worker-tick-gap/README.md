# Viewport worker UI responsiveness (ON vs OFF)
Main-thread tick-gap p95 for settle / continuous (storm) / orbit patterns on a 2100x1221 and a 2112x829 region;
band = 33 ms budget.
Verdict: the off-thread worker meets the budget for settle (17-21 ms vs 185-280 ms OFF) and big-scene orbit
(13.4 ms); the storm rows (175-197 ms) failed until the #721 fix (see material-storm-commit); metal orbit 76.9 ms fails.
Provenance: pkg266 section 9, Batch M (PR #819 / #817), RTX 5070 Ti, 2026-09-19.
