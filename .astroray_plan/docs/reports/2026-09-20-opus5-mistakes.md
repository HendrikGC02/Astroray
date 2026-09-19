# Opus 5 mistake log — session 2026-09-19 night → 2026-09-20

Owner request: track every mistake made by Opus 5 agents this session, the lead included. Each row: who, what, how it was caught, impact, fix. Critic = deepseek-v4.1-flash review of Opus 5 output.

| # | who | mistake | caught by | impact | fix |
|---|---|---|---|---|---|
| 1 | lead | Ran the 2026-09-15 owner `gh` block verbatim, including three tracking comments ("owning spec is pkg274") on #722/#723/#724, which #830 had already closed. Should have pruned stale lines first. | lead, reviewing the run output | 3 redundant comments on closed issues | none needed; prune stale lines before running an old command block |
| 2 | batchT lane | A bash heredoc ate backslashes in its patch script; the script aborted, the generator ran unpatched and rewrote three data files with CRLF. | lane, self-caught (diff check) | none shipped; files reverted, edits redone with Edit | known trap (memory `bash-heredoc-backslash-mangling`) — use Edit or os.path.join |
| 3 | lead | Wrote a Python helper through a bash heredoc with a `'\'` literal; the heredoc mangled it (SyntaxError) — the same trap just logged for batchT. | lead, immediate SyntaxError | none; rewritten with Write | write helper files with Write, never through a heredoc |
| 4 | lead | Started a cold CUDA build in the batchP/batchQ worktrees while telling the lanes to start work there; batchP committed engine changes mid-build, so the .pyd was mixed-state. | lead, on build completion | one wasted build (~28 min lock time) | lanes must not touch src/include/module/CMake while a build of their worktree runs (now in every build message) |
| 5 | batchP lane | Passed the new `light_frame` argument on every light, breaking the 7-argument test mocks in `test_pkg213_*`. | lane, call-site sweep | none shipped; fixed in 627bfe67 | call-site sweep before commit (CLAUDE.md) |
| 6 | batchP lane | First numpy IES reference was 1.8 % off at the 360° seam (missed Cycles' float32 wrap check). | lane, A/B vs Cycles | none shipped | — |
| 7 | batchP lane | Commit d601937b message claims both backends match the checker formula at 97–99 %; GPU is 94.8 %. | lane, self-caught | wrong number in a commit message (PR body correct) | — |
| 8 | batchP lane | Wrote a spec Status value that failed `project_index.py lint`. | lane, lint | none shipped | — |
