# Opus 5 mistake log — session 2026-09-19 night → 2026-09-20

Owner request: track every mistake made by Opus 5 agents this session, the lead included. Each row: who, what, how it was caught, impact, fix. Critic = deepseek-v4.1-flash review of Opus 5 output.

| # | who | mistake | caught by | impact | fix |
|---|---|---|---|---|---|
| 1 | lead | Ran the 2026-09-15 owner `gh` block verbatim, including three tracking comments ("owning spec is pkg274") on #722/#723/#724, which #830 had already closed. Should have pruned stale lines first. | lead, reviewing the run output | 3 redundant comments on closed issues | none needed; prune stale lines before running an old command block |
