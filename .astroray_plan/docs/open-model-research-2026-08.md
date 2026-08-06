# Open-model delegation research — 2026-08-06

Condensed findings from three Sonnet-5 research passes (agentic patterns,
model roster, latency levers) that back the `delegate` skill and tier config.
Full context: session journal 2026-08-06. Refresh cadence: re-rank the roster
when a tier's primary underperforms twice, or quarterly.

## Tier picks (evidence-ranked, verified against opencode-go roster)

| Tier | Primary | Runner-up | Basis |
|------|---------|-----------|-------|
| grunt | ~~deepseek-v4-flash~~ → qwen3.6-plus (flash paid needs China-hosting opt-in, 403 as of 2026-08-06) | kimi-k2.6 | Flash: 79.0% SWE-bench V, $0.14/$0.28/M, 121 tok/s. Qwen3.6-plus: reliable tool-calling, 1M ctx |
| implement | kimi-k2.7-code | deepseek-v4-pro | K2.6 predecessor: 96.6% tool-call success, 1000+ calls/13h session **in opencode specifically**; K2.7 GA in GitHub Copilot. V4-Pro: 80.6% SWE-bench V (vendor-claimed, unverified) |
| verify | glm-5.1 | qwen3.6-plus | Top open-weight SWE-Bench Pro at release, MIT, structured-output reputation; different lineage than implement tier (uncorrelated blind spots) |

Notable: glm-5.2 = strongest open model for long agent loops (dark horse for
implement). kimi-k3 / qwen3.8-max too new, no independent numbers. minimax-m2.7
has a documented tool-call format bug — avoid for multi-step work.
gpt-5.6-luna/grok-4.5 (closed, in roster): 2–5x cost of open picks for
equal-or-worse coding; grok-4.5 plausible as escalation only.

Free tier: deepseek-v4-flash-free > north-mini-code-free (Cohere, RLVR-trained
for SWE) > nemotron-3-ultra-free. big-pickle = stealth model, unknown
provenance. **Free endpoints may train on submitted data — docs/public content
only, never src/.**

## opencode integration facts (v1.18.14, verified locally where noted)

- `opencode run -m <provider/model> --format json` — JSONL events:
  `step_start`, `text`, `tool_use` (completion-only), `step_finish`
  (carries `part.reason` "stop"|"tool-calls", `part.tokens`, `part.cost`),
  `error`. Verified locally 2026-08-06.
- **Exit codes unreliable** (upstream #14551/#2489: exit 0 after mid-session
  error). Verified partially: launch failures DO exit 1 locally, but
  incomplete sessions end exit 0 with `reason:"tool-calls"` — the
  `no_clean_finish` case delegate.py flags. Never gate on exit code.
- Writes outside the project root (`--dir`) silently error the write tool —
  keep worker outputs inside the project/worktree. Verified locally.
- Custom agents: `.opencode/agents/<name>.md`, YAML frontmatter
  (`permission:` allow/ask/deny; bash glob maps). Upstream #6396: deny rules
  **ignored via SDK/serve path** — permission enforcement is only trusted on
  the CLI `run` path we use.
- `opencode serve` = headless REST (OpenAPI at /doc, session create/prompt
  async/SSE) — option for a future pooled dispatcher; CLI-per-task is fine at
  current volume.
- Windows failure classes: stuck "Loading plugins" hang, unnoticed process
  completion. delegate.py's hard timeout covers both.

## Verification asymmetry (design basis)

Literature is unambiguous: verification is cheaper than generation
(weak-to-strong supervision). Correct shape: **cheap model generates, Claude +
deterministic gates verify.** Never expect a cheap model to self-verify.
Hallucination rates: ~5% commercial vs ~22% open-source models (576k-sample
study) → build-gate verification is mandatory, not optional, for open-model
diffs. Cascade economics: if escalation-to-Claude exceeds ~30-40% on a task
class, delegation of that class is net-negative — track it.

## Latency lever ranking (from repo-grounded research pass)

1. NMake → Ninja generator (ninja already installed; NMake is fully serial)
2. Local-dev CUDA arch: single native arch vs the 3-arch 75;86;89 list
   (sm_120 native needs the CUDA 12.8 toolchain; build_cuda.bat pins 12.6)
3. sccache (MSVC+nvcc) shared across worktrees; /Z7 not /Zi
4. Shared FETCHCONTENT_BASE_DIR across worktrees (warm once, serially)
5. CI: concurrency cancel-in-progress (free), docs path-skip via job-level
   `if:` (56% of recent runs were docs-only × ~17 min), pip cache, cache
   PractRand build, parallelize the 25 serial nvcc syntax-check calls
6. pytest: CPU/GPU marker split + xdist for CPU-only (GPU stays serial per
   cuda_verifier_concurrency); pytest-testmon does NOT see .pyd changes — use
   a src→test path map instead; `--lf --ff` for fix loops
