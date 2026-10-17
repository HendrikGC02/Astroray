# Anthropic agentic-coding practices, distilled for Astroray (research note, 2026-10-18)

Scope: most recent official Anthropic guidance (2026) on agentic coding, Claude Code multi-agent work,
prompt caching, model selection, CLAUDE.md/memory, and cost control. Compiled by a research
subagent on 2026-10-18 from primary sources fetched that day. No repo files were edited.

Source legend. Docs pages are live (undated); the Claude Code changelog excerpt covered only
v2.1.293 to v2.1.302 and carried no dates. Engineering-blog dates are as listed on
anthropic.com/engineering. "Bundled skill" means the local `claude-api` skill reference that ships
with the Claude Code build in use (2.1.299); it mirrors Anthropic's API docs but is secondary.
Anything not confirmed on a primary page is marked UNVERIFIED.

---

## Rules for Astroray (15)

1. Pick the cache TTL by the start-to-start gap between requests sharing a prefix: under 5 min keep the 5-minute default, 5 to 60 min use the 1-hour TTL (write 2x, read 0.05x base on Opus/Sonnet 5.5). [Prompt caching API](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Claude Code caching](https://code.claude.com/docs/en/prompt-caching)
2. Set `promptCacheTtl: "1h"` and `subagentPromptCacheTtl: "1h"` (or `CLAUDE_CODE_PROMPT_CACHE_TTL=1h` / `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h`) for overnight orchestrators, because subagents, workflows, teammates, forks and compaction get 5 minutes by default, and API-key sessions get 5 minutes for the main conversation too. [Claude Code caching: choose the TTL](https://code.claude.com/docs/en/prompt-caching#choose-the-ttl-yourself)
3. Never switch model, change top-level effort, toggle MCP servers/tools, or edit the system prompt mid-session; each invalidates the whole cache, so use a subagent for a different model and per-message effort (beta) for effort changes on 5.5-generation models. [Claude Code caching](https://code.claude.com/docs/en/prompt-caching#actions-that-invalidate-the-cache), [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
4. Pin effort explicitly on every agent: Opus 5.5 and Haiku 5.5 default to `medium`, Sonnet 5.5 to `high` on the API, and Anthropic's own March to April 2026 quality regression was a silently changed effort default. [Models overview](https://platform.claude.com/docs/en/models/overview), [April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem)
5. Start Opus 5.5 at `medium` (it matches Opus 5 at `high` on coding), Sonnet 5.5 at `medium` for well-specified agentic coding, Haiku 5.5 at `medium`, and reserve `xhigh`/`max` for measured gains; use `low` for simple subagents. [Prompting Opus 5.5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5), [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
6. Treat "start with Opus 5.5, move to Fable 5.1 only if evals at xhigh/max still fall short" as Anthropic's own tiering; a Fable advisor bought +1.7 points for ~2.1x cost in their coding test, which supports our Fable-subagent ban. [Choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model), [Optimizing cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)
7. Update the cheap-summariser tier from Haiku 4.5 to Haiku 5.5 ($0.10/$0.50 per MTok at 100K prompts or less, 1M context, explicitly listed for sub-agent tasks), but cap each call's prompt at 100K tokens because longer prompts bill 5x. [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5)
8. Use an orchestrator-plus-cheap-workers pattern only for genuinely independent fan-out (many files, beyond one context); for a dependent chain, the single stronger model at lower effort beat the delegated setup in every measured case. [Optimizing cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)
9. Brief every non-fork subagent as a stranger: it sees only its system prompt, your delegation message, CLAUDE.md and git status, so state objective, output format, tools/sources, and task boundaries every time. [Subagents](https://code.claude.com/docs/en/sub-agents), [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
10. Verify with a different, fresh-context agent that sees only the diff and the criteria, require evidence (test output, command and result, screenshot), and tell the reviewer to flag only correctness or stated-requirement gaps. [Best practices](https://code.claude.com/docs/en/best-practices)
11. For unattended runs, give a checkable end state (a `/goal` condition or Stop hook), treat a text-only end of turn as a report not completion, keep a task checklist file, and cap automatic continuations at two or three. [Prompting Opus 5.5: unattended runs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5#unattended-agentic-runs), [/goal](https://code.claude.com/docs/en/goal)
12. Persist state across sessions in files (JSON feature list with a `passes` flag, progress log, per-session git commits, a start-up smoke script) rather than relying on compaction. [Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), [Harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps)
13. Use hooks, not CLAUDE.md prose, for anything that must always happen (block, validate, re-inject context after compaction); CLAUDE.md is advisory and hooks are deterministic. [Memory](https://code.claude.com/docs/en/memory), [Hooks guide](https://code.claude.com/docs/en/hooks-guide)
14. Keep CLAUDE.md under 200 lines and move rarely needed procedure into path-scoped `.claude/rules/*.md` or skills; `@imports` organise but do not reduce context cost. [Memory: write effective instructions](https://code.claude.com/docs/en/memory)
15. Watch spend where it actually leaks: idle gaps past the cache TTL, agent-team teammates (about 7x tokens), parallel sessions (N agents = N-times quota burn), workflow fan-outs, and scheduled tasks that resend full context; check `/usage` "Prompt cache (main)" and the OTel 5m/1h cache-write split. [Costs](https://code.claude.com/docs/en/costs), [Changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)

---

## 1. Prompt caching: 5-minute vs 1-hour TTL

### What it is (primary: Claude API prompt-caching page)
- Default lifetime is 5 minutes; "The cache is refreshed for no additional cost each time the cached content is used."
- The lifetime is measured from the start of the request that writes or reads the entry, not from the end of its response. A 4-minute generation leaves about 1 minute for the next request to start.
- 1-hour option: `"cache_control": {"type": "ephemeral", "ttl": "1h"}`. Latency is the same for both TTLs. Cache hits are not deducted against your rate limit.
- Longer TTL entries must come before shorter ones in the prompt (a 1h entry before any 5m entry). Max 4 breakpoints; automatic caching (top-level `cache_control`) uses one slot. An explicit marker on the last block with a different TTL than the top-level field returns a 400.
- Prefix match is exact and 100 percent identical. Changes to tool definitions invalidate everything; changes to `tool_choice`, images, thinking config or `output_config.effort` invalidate message blocks. Lookback is at most 20 blocks per breakpoint.
- Concurrent requests: an entry only becomes available after the first response begins (relevant to parallel fan-out; Claude Code staggers workflow siblings by up to 5 s, `CLAUDE_CODE_WORKFLOW_PREFIX_STAGGER_MS`).
- Pre-warming: `max_tokens: 0` with a breakpoint on the shared prefix bills a cache write; re-warm at least every 5 min for 5m TTL, else use 1h.

### Minimum cacheable tokens (per model)
- 512: Fable 5.1, Mythos 5.1, Opus 5.5, Opus 5, Sonnet 5.5, Fable 5, Mythos 5, Haiku 5.5.
- 1,024: Opus 4.8, Sonnet 5, Sonnet 4.6/4.5, Opus 4.1/4, Sonnet 4.
- 2,048: Opus 4.7, Mythos Preview, Haiku 3.5. 4,096: Opus 4.6/4.5, Haiku 4.5.
- Below the minimum the request is processed uncached with no error; check that `cache_creation_input_tokens` and `cache_read_input_tokens` are not both 0.

### Pricing multipliers (primary: Pricing page; per MTok)
| Model | Base in | 5m write (1.25x) | 1h write (2x) | Read/refresh | Output |
|---|---|---|---|---|---|
| Fable 5.1 | $10 | $12.50 | $20 | $0.25 (0.025x) | $50 |
| Opus 5.5 | $4 | $5 | $8 | $0.20 (0.05x) | $20 |
| Sonnet 5.5 | $2 | $2.50 | $4 | $0.10 (0.05x) | $10 |
| Haiku 5.5 (<=100K prompt) | $0.10 | $0.125 | $0.20 | $0.01 (0.1x) | $0.50 |
| Haiku 5.5 (>100K prompt) | $0.50 | $0.625 | $1 | $0.05 | $2.50 |
| Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | $5 |
Batch API is 50 percent off and stacks with caching. Fast mode (Opus 5.5) is $8/$40 and stacks with cache multipliers.

### When the 1-hour TTL pays off (arithmetic from the multipliers; my derivation)
- Break-even for a prefix reused within TTL: 5m needs 2 requests; 1h needs 3 (the bundled skill states the same). If requests are less than 5 min apart the 1h TTL buys nothing but the doubled write price.
- The real win is idle gaps. On Opus 5.5 with a 300k-token context: re-writing after an expired 5m cache costs about $1.50, a 1h write costs about $2.40 once, and a cache read costs about $0.06. The 1h premium over a 5m write is $0.90 per write event; each avoided cold restart saves about $1.44. So 1h wins if you would otherwise suffer roughly one or more cold restarts per cache-write event (ratio about 0.63).
- Astroray cases that fit: an orchestrator waiting on CUDA builds, a hardware-verifier lane, a lead polling lanes, an architect run with long web research, any session idle 6 to 60 minutes between turns. Cases that do not fit: tight tool loops under 5 min apart, short one-shot subagents (they die before reuse; 5m write is cheaper).
- Fable 5.1 nuance (bundled skill, UNVERIFIED on the live page because the live prompt-caching page was truncated at 100k characters in my fetch): with reads at 0.025x, a keep-alive request (`max_tokens: 0`, re-sent just before 5 min) can beat the 1h TTL unless pauses approach an hour. We do not run Fable lanes, so this is informational.

### How it is enabled
Claude Code (primary: code.claude.com/docs/en/prompt-caching):
- Claude Code decides TTL per request in two buckets: "main conversation" (interactive turns, `-p` runs, Agent SDK turns) and "everything else" (subagents, workflows, in-process teammates, forks, compaction, session titles).
- Defaults: Claude subscription within plan usage gets 1h for the main conversation only; usage credits, API key, or cloud provider get 5m for both buckets. The "everything else" bucket is 5m everywhere (apart from a few server-controlled helper requests).
- Controls (each accepts `5m` or `1h`; need v2.1.242+): `promptCacheTtl` setting or `CLAUDE_CODE_PROMPT_CACHE_TTL` for the main bucket; `subagentPromptCacheTtl` or `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` for everything else.
- Precedence: `FORCE_PROMPT_CACHING_5M=1` (both buckets, wins) > bucket env var > bucket setting > subagent frontmatter `experimental: cacheTtl: 1h` (v2.1.248+, ignored while on usage credits) > `ENABLE_PROMPT_CACHING_1H=1` (both buckets) > bucket default.
- Verify: `claude -p "hello" --output-format json` and read `usage.cache_creation.ephemeral_1h_input_tokens` vs `ephemeral_5m_input_tokens`. OTel exports `cache_creation_5m_tokens` and `cache_creation_1h_tokens` (changelog 2.1.300). `/usage` shows a "Prompt cache (main)" line with hit share, misses, likely cause, warm/cold and TTL (v2.1.251+; likely-cause text v2.1.260+).
- Disable switches: `DISABLE_PROMPT_CACHING` (and `_HAIKU`, `_SONNET`, `_OPUS`, `_FABLE`). Leave caching on.
- Through an LLM gateway, forward the `anthropic-beta` header unchanged; 1h is not available via the Claude apps gateway.
- Idle compaction (changelog 2.1.299, toggle in `/config` from 2.1.302; `"idleCompaction": false` to disable; `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`): a 200K+ token conversation idle about 54 minutes is compacted just before its 1h cache expires. Know this before an overnight run: a quiet orchestrator can be compacted on its own.
- `/loop` interval design: a fixed `*/5` loop is scheduled 4m45s apart on purpose to stay inside the 5m cache.

Agent SDK / API:
- Per-block `cache_control: {"type":"ephemeral","ttl":"1h"}` or the top-level `cache_control` field (automatic placement). Agent-loop pattern from the bundled skill: one explicit breakpoint on the static system prefix plus top-level automatic caching for the conversation tail; if on 1h, put `ttl:"1h"` on both (1h entries must precede 5m entries).
- SDK callers: Claude Code docs point to agent-sdk cost-tracking and "improve prompt caching across users and machines" (moves auto-memory path out of the system prompt). I did not open those pages (UNVERIFIED details).

### Cache-keeping design rules (primary: Claude Code caching page; Anthropic blog "Prompt caching is everything")
- Order: static system prompt/tools, then CLAUDE.md, then session context, then conversation. A timestamp in the static prefix or reordered tools breaks it.
- Do not change tools mid-session (plan mode is implemented as tools that are always present; MCP tools are deferred).
- Put updates in messages (`<system-reminder>`), not system-prompt edits.
- Do not switch models mid-session: "switching to a cheaper model can cost more than staying put." Use a subagent with a hand-off message.
- Fork side operations (compaction, summarization) from the parent's exact prefix. Monitor hit rate "like uptime".
- Cache scope in Claude Code is effectively machine plus directory (the system prompt embeds auto-memory paths and cwd). Two sessions in different worktrees do not share cache; parallel sessions in the same directory do.
- Things that keep the cache: editing CLAUDE.md mid-session (but the edit does not apply until `/clear`, `/compact` or restart), permission-mode change, output-style change (since 2.1.251), skills/commands, `/recap`, `/rewind`. Things that break it: `/model` switch (including `opusplan` plan-mode toggles and skill frontmatter `model:`), effort change on pre-5.5 models, turning on fast mode (one-time), MCP/plugin tool changes without tool search, compaction, image batches dropped, Claude Code upgrade.
- Advisor tool toggling is an exception that keeps the cache.

Sources: [API prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Claude Code prompt caching](https://code.claude.com/docs/en/prompt-caching), [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Prompt caching is everything](https://claude.dev/blog/lessons-from-building-claude-code-prompt-caching-is-everything/) (redirected from claude.com/blog), bundled claude-api `shared/prompt-caching.md`.

---

## 2. Model selection for the Claude 5 family

### Specs (primary: models overview, 2026-10)
| | Fable 5.1 | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|---|
| Anthropic's blurb | demanding reasoning, long-horizon agentic | long-running agentic coding and knowledge work | best combination of speed and intelligence | high-volume, latency-sensitive: classification, extraction, routing |
| Latency | Slower | Moderate | Fast | Fastest |
| Price in/out per MTok | $10 / $50 | $4 / $20 | $2 / $10 | $0.10 / $0.50 (<=100K) |
| Default effort (API) | high | medium | high | medium |
| Context / max output | 1M / 128K | 1M / 128K | 1M / 128K | 1M / 128K |
| Thinking | always on | always on | adaptive (`between_tools` to minimise) | adaptive |
| Cache read multiplier | 0.025x | 0.05x | 0.05x | 0.1x |
| Min cacheable | 512 | 512 | 512 | 512 |
| Fast mode | no | yes ($8/$40) | no | no |
| Retirement | not before 2027-09-01 | not before 2027-09-22 | not before 2027-09-28 | not before 2027-10-07 |
Cost ratios (input / output): Fable 5.1 is 2.5x Opus 5.5, 5x Sonnet 5.5, 100x Haiku 5.5. Opus 5.5 is 2x Sonnet 5.5, 40x Haiku 5.5. Same 1M window everywhere at flat per-token pricing (Haiku 5.5 reprices above 100K). Tokenizer is about 30 percent more tokens than pre-4.7 models for the same text.
Claude Code defaults: `opus` alias resolves to Opus 5.5, `sonnet` to Sonnet 5.5, `haiku` to Haiku 5.5 on the Anthropic API (Haiku 5.5 became the default Haiku in v2.1.293). Fable is never a default; you must select it. Claude Code's model-config page lists default effort `medium` on Opus 5.5, Sonnet 5.5 and Haiku 5.5, while the API default for Sonnet 5.5 is `high`; this is a minor discrepancy between two primary pages, so pin it.

### Anthropic's stated guidance
- "Most workloads start with Claude Opus 5.5." Fable 5.1 "for demanding reasoning and long-horizon agentic work, or when your evals on Claude Opus 5.5 at higher effort still fall short." (Models overview, Choosing a model.)
- Selection matrix: highest capability = Fable 5.1 (agent sessions that run for hours, deep research); complex agentic coding = Opus 5.5 (multihour autonomous coding, large refactors); everyday coding/agents = Sonnet 5.5; lowest latency/price = Haiku 5.5, including "sub-agent tasks".
- Effort first: "Tuning effort is often a better lever than switching models." Two start strategies (efficiency-first with Haiku, capability-first with Opus 5.5) and "evaluate on your own prompts" are both stated.
- Opus 5.5 at default `medium` "matched or beat" Opus 5 at `high` on agentic coding tasks, in fewer steps and tokens; on several coding evals `low` comes close at much lower cost. It also tends to think more per turn at a given level than Opus 5, especially at `xhigh`/`max`.
- Sonnet 5.5: for agentic coding and multistep tool use start at `medium` for well-specified tasks, `high` for harder or longer ones; `xhigh`/`max` only where evals show a gain; levels were recalibrated vs Sonnet 5.
- Haiku 5.5: start at `medium` including agentic coding; `low` for chat/short tool tasks, but in long agent prompts it is more likely to skip a search, stop early or skip a check at `low`; use `high` for strict instruction following; compare `xhigh`/`max` against Sonnet 5.5 before paying for them. No server-side refusal fallback on Haiku 5.5.
- Effort table lists `low` for "Simpler tasks ... such as subagents" and `xhigh` for long-running agentic/coding work over 30 minutes.

### Measured multi-model strategies (primary: Optimizing for cost and intelligence; all figures Anthropic-internal and directional)
- Advisor (cheap executor consults a frontier model): Opus 5.5 at `high` plus Fable 5.1 advisor scored 90.1 percent, +1.7 points (edge of noise), at about 2.1x cost, ~1.4 consults per attempt; the gain "lands about on Claude Opus 5.5's own effort curve". Advice: "Build a pairing only if it beats the single model's whole curve of score against spend." Lowering effort can collapse the consult rate.
- Orchestrator (frontier plans, cheaper workers do bulk): saved money only for (a) routine work with a long cost tail and (b) work larger than one context window, with earlier-generation workers; it scored 10 to 12 points lower. For a dependent chain or work that fits one context, "the orchestrator's model alone at lower effort came out ahead in every case measured."
- Multi-agent research system (Jun 2025 post, still the canonical briefing reference): agents use about 4x chat tokens, multi-agent about 15x; token usage explained about 80 percent of BrowseComp variance; multi-agent suits high-value, parallelisable work and is a poor fit for most coding tasks where agents share context.

### Pinning model and effort on a subagent (primary: sub-agents page, model-config page)
- `.claude/agents/*.md` frontmatter: `model:` accepts `sonnet`, `opus`, `haiku`, `fable`, a full ID (e.g. `claude-opus-5-5`), or `inherit`. `effort:` accepts `low|medium|high|xhigh|max`. Other fields: `tools`/`disallowedTools`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory` (`user|project|local`), `background`, `isolation: worktree`, `omitClaudeMd`, `autoCompactWindow` (v2.1.296+), `experimental.cacheTtl`.
- Resolution order for the model: (1) per-invocation `model` parameter on the Agent tool call, (2) frontmatter, (3) `CLAUDE_CODE_SUBAGENT_MODEL`, (4) main conversation model. Before v2.1.251 the env var came first. Force one model on all subagents with `CLAUDE_CODE_SUBAGENT_MODEL` plus `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (v2.1.257+); a separate `CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL` sets workflow agents (v2.1.296+). Per-invocation `effort` parameter exists from v2.1.292; `CLAUDE_CODE_EFFORT_LEVEL` overrides frontmatter and parameter.
- Org `availableModels` allowlists silently substitute a permitted model (warning only in interactive sessions); there is a `deniedModels` key (v2.1.283+).
- Built-ins: Explore inherits the main model (with a Fable main model it uses Opus); override by defining your own `Explore` agent with `model: haiku`. Plan inherits; statusline-setup uses Sonnet; claude-code-guide uses Haiku.
- Model pins: aliases move; pin with full IDs or `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL`. Our agent files already use full IDs (`claude-opus-5-5`, `claude-sonnet-5-5`); none sets `effort:`.
- Plan-mode warning: `opusplan` flips model on every plan-mode toggle, which resets the cache each time.
- Thinking cannot be turned off on Opus 5.5, Sonnet 5.5, Haiku 5.5 or Fable models in Claude Code (use effort). Forced `tool_choice` returns 400 on Opus 5.5/Sonnet 5.5/Fable 5.1 (API-level, relevant only if we call the API directly).
- 1M context is the default on these models (`CLAUDE_CODE_DISABLE_1M_CONTEXT=1` to cap at 200K). Auto-compact window is tunable 100K to 1M: `/autocompact 300k`, `autoCompactWindow` setting, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, and per-subagent `autoCompactWindow`.

Sources: [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), [Choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model), [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), [Effort](https://platform.claude.com/docs/en/build-with-claude/effort), [Opus 5.5 what's new](https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5), [Sonnet 5.5 what's new](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5), [Haiku 5.5 what's new](https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5), [Claude Code model config](https://code.claude.com/docs/en/model-config), [Subagents](https://code.claude.com/docs/en/sub-agents).

---

## 3. Subagents, agent teams, workflows: best practice

### Choosing the mechanism (primary: code.claude.com/docs/en/agents, agent-teams, workflows)
| Mechanism | Plan held by | Use when | Cost note |
|---|---|---|---|
| Subagents | Claude, turn by turn | A side task would flood main context with logs/search results | results summarised back; each has own requests |
| Fork (`/subtask`) | Claude | Subagent needs the whole conversation; first request reads parent's cache | cache-friendly |
| Agent view / background sessions (`claude agents`, `claude --bg`, research preview) | you | Independent tasks, hand off and check back; survive terminal close | "ten agents ... uses quota roughly ten times as fast" |
| Agent teams (experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) | lead agent | Teammates must talk to each other (competing-hypotheses debugging, parallel module ownership) | about 7x tokens (plan-mode teammates); teammates' cache TTL is 5 min unless `subagentPromptCacheTtl` |
| Dynamic workflows (`/workflows`, `ultracode`) | a JS script | Dozens to hundreds of agents; audits, 500-file migrations, adversarial cross-checking | script holds intermediate results; up to 16 concurrent agents, 1,000 per run; `Large workflow` warning at >25 agents or 1.5M tokens |
| `/batch` | skill | split a change into 5 to 30 worktree-isolated subagents | |
- Stay in the main conversation for iterative back-and-forth, shared-context phases, small targeted edits, or when latency matters; a non-fork subagent starts cold.
- Agent teams: "start with 3-5 teammates", aim for 5 to 6 tasks per teammate, each teammate owns a distinct file set, "Letting a team run unattended for too long increases the risk of wasted effort." Not for sequential tasks or same-file edits. Teammates do not inherit lead history; the spawn prompt is all they get. Hooks `TeammateIdle`, `TaskCreated`, `TaskCompleted` (exit 2 sends feedback). Limitations: no resume of in-process teammates, one team per session, no nested teams, task status can lag.
- IMPORTANT local interaction: `.claude/settings.json` in this repo sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Per the agent-teams page, with this on, any subagent Claude names launches as a teammate with no confirmation, which can silently multiply tokens when we only wanted a subagent. Setting it to `0` reverts named subagents to ordinary subagents without a restart.
- Limits: 20 concurrent subagents by default (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`); nesting up to 3 layers (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`); combined subagent descriptions over about 15K tokens trigger a startup warning (keep descriptions short; put detail in the body).

### Briefing subagents
- A non-fork subagent sees "its own system prompt, the delegation message, CLAUDE.md files, and git status, but not your conversation history." So the delegation message must be self-contained. Set `omitClaudeMd` for pure-grunt agents that should not load our large CLAUDE.md.
- From the multi-agent research system: give "an objective, an output format, guidance on tools and sources, and clear task boundaries"; short briefs cause duplicated and gapped work; put explicit effort-scaling rules in the prompt (1 agent with 3 to 10 tool calls for simple lookups, 2 to 4 agents for comparisons, 10+ for complex work); start searches broad then narrow; let subagents write large outputs to files and return lightweight references.
- Opus 5.5 pays close attention to elapsed time; adding `elapsed 340s / 1200s` to harness messages or one sentence "Time matters here..." made small agent teams finish sooner with comparable quality (Anthropic evals). Budgets are advisory; keep a hard timeout.
- Fable-era guidance in the bundled skill: "Give the reason, not just the request" and state the full task spec up front; (carry-over for Opus 5.5 UNVERIFIED, the source section was written for Fable 5.1).

### Context isolation and keeping the orchestrator small
- "Context window is the most important resource to manage"; performance degrades as it fills. Delegate research and verbose operations (tests, docs fetch, logs) to subagents and keep only the summary. `/clear` between unrelated tasks; after two failed corrections, `/clear` and rewrite the prompt.
- Cheap pre-digestion: hooks can filter output before Claude sees it (grep for ERROR from a 10,000-line log; failure-only test output), and skills carry domain knowledge so Claude does not explore. Row summaries in agent view already use a Haiku-class model. The C-compiler project: keep test output to a few lines, put "ERROR" and the reason on one line, precompute summary statistics, log detail to files.
- Many subagents returning detailed results "can consume significant context"; ask for compact structured returns.

### When to parallelise
- Good: many independent failing tests/files, multi-angle research and review, competing hypotheses.
- Bad: one giant coupled task. In the C compiler build, 16 agents hit the same Linux-kernel bug and overwrote each other until a known-good oracle (GCC) let each agent fix different files. Lock tasks via files in a shared directory plus git sync; expect frequent merge conflicts.
- Each parallel agent multiplies quota burn ("ten agents ... roughly ten times"). Worktrees isolate edits; `isolation: worktree` on a subagent does it per call, and background sessions move into `.claude/worktrees/` before editing.

### Verification by evidence; avoiding anchoring
- "Give Claude a way to verify its work ... It's the difference between a session you watch and one you walk away from." Have Claude show evidence (test output, the command and result, a screenshot); "Reviewing evidence is faster than re-running the verification yourself".
- Escalation ladder from the best-practices page: prompt-level check, `/goal` condition (a separate evaluator re-checks after each turn), a Stop hook as a deterministic gate, or a fresh-model verifier subagent / workflow that tries to refute findings.
- Fresh context beats self-review: "A fresh context improves code review since Claude won't be biased toward code it just wrote." A standalone evaluator is more tractable to make skeptical than a generator is to make self-critical (harness-design post), but out of the box evaluators "talk themselves into approving the work", so read evaluator logs and tune; give few-shot score examples.
- Anchoring: sequential investigation "suffers from anchoring"; multiple independent investigators trying to disprove each other converge better (agent teams page). Give the verifier the diff and criteria, not the author's conclusion (matches our "give it the code, not your conclusion" rule).
- A reviewer asked to find gaps will find some; tell it to report only gaps that affect correctness or stated requirements, or you get over-engineering.
- With autonomous loops the verifier must be near-perfect: "easy to see tests pass and assume the job is done" (C-compiler post). Add a `--fast` deterministic sample mode because Claude has no sense of time; grade outcomes (final state) not paths; isolate trials, because leftover state inflated scores in Anthropic's own evals (Demystifying evals, Jan 2026). Read transcripts: failures should look fair.

### Plan first, handoff files, long sessions
- Official four-phase flow: Explore, Plan, Implement, Commit; skip planning if the diff fits in one sentence. For large features have Claude interview you and write a spec file, then execute in a fresh session. Best specs are self-contained, name files/interfaces, state out-of-scope, end with an end-to-end verification step.
- Long-running harness (Nov 2025 post): an initializer session creates `init.sh`, a progress log and a feature list (JSON, each feature starts `passes:false`; JSON chosen because models overwrite it less than Markdown); every coding session starts by reading git log, progress file, and running a basic end-to-end check; one feature per session; descriptive commit per session. Failure modes and fixes tabulated there (premature "done", dirty environment, untested features).
- Reset vs compaction (Mar 2026 post): a context reset with a structured handoff file gives a clean slate; compaction preserves continuity but does not cure a model wrapping up early as context fills. Resets were essential for Sonnet 4.5 "context anxiety" and became unnecessary with Opus 4.5/4.6: "Each harness component reflects an assumption about what the model can't do alone"; re-test assumptions with each model release, remove components one at a time.
- Sprint contract: generator and evaluator agree what "done" means before each unit of work. Cost reality check: full harness v1 on Opus 4.5 was about 6 h and $200 (20x solo); v2 on Opus 4.6 about 3 h 50 m and $125.
- Multi-agent post: save the plan to external memory so it survives context truncation; checkpoint and resume rather than restart; hand off completed phases to fresh subagents.
- Managed Agents post (Apr 2026): treat the session log as durable context outside the harness so a crashed harness resumes from the last event; the same idea applies to our handoff files. Our existing rule "retire lanes above about 300k tokens with a handoff file" matches this guidance.

### Hooks for guardrails (primary: hooks guide)
- Hooks are deterministic; CLAUDE.md is advisory ("Claude treats them as context, not enforced configuration"). To block an action regardless of what Claude decides use a PreToolUse hook.
- Events relevant to overnight work: `PreToolUse`, `PostToolUse`, `Stop` and `SubagentStop` (exit 2 or JSON `reason` keeps Claude working; blocked at most 8 consecutive times with no tool call in between, so check `stop_hook_active`), `SessionStart` with `compact` matcher (re-inject critical context after compaction), `PreCompact`/`PostCompact`, `PreModelSwitch` (block or confirm cache-busting model switches), `TaskCreated`/`TaskCompleted`/`TeammateIdle`, `WorktreeCreate`.
- `onFailure: "block"` (v2.1.295) makes a failing command/HTTP hook block the action; the default is a non-blocking error. Prompt/agent hooks judge with a model; v2.1.294 improved Stop-hook judging. Plugin hook `agent.spawn` can rewrite workflow-agent prompt and model (v2.1.300).
- Our hooks are PowerShell scripts; a hook that errors out silently does not block unless `onFailure: "block"` is set. UNVERIFIED whether our hooks rely on exit codes alone.

Sources: [Best practices](https://code.claude.com/docs/en/best-practices), [Agents overview](https://code.claude.com/docs/en/agents), [Subagents](https://code.claude.com/docs/en/sub-agents), [Agent teams](https://code.claude.com/docs/en/agent-teams), [Workflows](https://code.claude.com/docs/en/workflows), [Hooks guide](https://code.claude.com/docs/en/hooks-guide), [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system), [Effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps), [Building a C compiler](https://www.anthropic.com/engineering/building-c-compiler), [Managed Agents](https://www.anthropic.com/engineering/managed-agents), [Demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

---

## 4. CLAUDE.md, memory, and 2026 features for autonomous runs

### CLAUDE.md best practice (primary: memory page, best-practices page)
- Include: commands Claude cannot guess, style rules that differ from defaults, test runners, repo etiquette, project-specific architecture decisions, environment quirks, non-obvious gotchas. Exclude: anything derivable from code, standard conventions, long API docs (link instead), frequently changing info, file-by-file descriptions, self-evident advice.
- Test for every line: "Would removing this cause Claude to make mistakes?" If not, cut. "Bloated CLAUDE.md files cause Claude to ignore your actual instructions." Emphasis ("IMPORTANT") on one or two lines only. Concrete and verifiable wording beats vague.
- Size: "target under 200 lines per CLAUDE.md file." Imports (`@path`, depth 4) "organize a long file but don't reduce its context cost, because imported files also load at launch." HTML block comments are stripped before injection (free maintainer notes).
- Locations and order (broad to specific, concatenated, not overriding): managed policy, `~/.claude/CLAUDE.md`, project `./CLAUDE.md` or `./.claude/CLAUDE.md`, `CLAUDE.local.md`; subdirectory CLAUDE.md files load on demand when Claude touches files there (also via Bash `cat/head/tail/sed -n/grep` since 2.1.293).
- `.claude/rules/*.md` exists: all `.md` files are discovered recursively; files without `paths:` frontmatter load at launch like CLAUDE.md; files with `paths:` globs (brace expansion allowed) load only when Claude reads/writes/edits a matching file. `~/.claude/rules/` for personal rules; symlinks supported (external symlink targets need approval). `paths` is the only frontmatter field read. Use rules for part-of-codebase instructions and skills for multi-step procedures that matter only sometimes.
- `/doctor prompt-audit` (v2.1.283+) audits CLAUDE.md, rules, skills, commands and subagents for instructions written for older models, stale references and contradictions; it proposes edits and changes nothing until asked. `/init` generates a starter; `CLAUDE_CODE_NEW_INIT=1` gives a multi-phase flow.
- Compaction guidance can live in CLAUDE.md ("When compacting, always preserve the full list of modified files and any test commands").
- AGENTS.md: Claude Code reads it only if no CLAUDE.md exists in or above the working dir, unless a CLAUDE.md `@imports` it or `/config` "Project instructions" is set to `claude-md-and-agents-md`.
- Auto memory: Claude-written notes, loaded each session as the first 200 lines or 25KB of `MEMORY.md`, shared across worktrees of a repo; subagents can have their own memory (`memory:` frontmatter, recommended default scope `project`).

### Memory best practices (derived)
- Keep the MEMORY.md index within 200 lines/25KB (ours is 150 lines, 19.4 KB, so it is close on bytes; each long line costs context every session). Entries beyond the cap are silently not loaded.
- Treat memory and CLAUDE.md as context, not enforcement; put must-always rules in hooks.
- Edits mid-session do not apply until `/clear`, `/compact` or restart (cache-friendly but surprising).

### New in Claude Code that matter for an overnight run
- `/goal <condition>`: a small fast model checks the condition after every turn; stops when met, judged impossible, or on an error you must fix (auth failure, exhausted credit, context overflow that compaction could not clear, model unavailable). Condition up to 4,000 chars; include a turn/time clause ("or stop after 20 turns"). Works with `claude -p`. The evaluator only sees what Claude surfaced in the transcript, so require visible proof ("`npm test` exits 0"). It is a session-scoped Stop hook. Background work defers evaluation; idle check-ins at 30 min, doubling, max 3 idle check-ins between prompts (`CLAUDE_CODE_GOAL_CHECKIN_MINUTES`, 0 disables).
- Scheduling: `/loop` and cron tools are session-scoped (session must be open and idle), 50 tasks per session, recurring tasks expire after 7 days, jitter up to 30 min on hourly tasks, no catch-up of missed fires, minimum 1 min. For durable unattended scheduling use cloud Routines (min interval 1 h), Desktop scheduled tasks, or GitHub Actions. Our roadmap orchestrator uses a Windows Task for durability, consistent with this. Schedule fires resend full context each time (a cost leak when the cache is cold). `ScheduleWakeup` self-paced loops choose 1 to 60 min delays; a missed reschedule falls back to about 20 min.
- Background agents / agent view (`claude --bg`, `claude agents`, `/bg`, research preview): a supervisor process runs sessions without a terminal; idle unattached sessions are stopped after about an hour (conversation kept on disk, pin with Ctrl+T); local only, stops at machine shutdown; each session isolated in a worktree; `auto` and `bypassPermissions` honoured only from managed settings, `--settings` or `~/.claude/settings.json`.
- Auto mode (v2.1.283+ built-in starting mode in interactive sessions): a classifier reviews actions and blocks scope escalation, unknown infrastructure, hostile-content-driven actions; with `-p` it does not abort the run when the classifier repeatedly blocks (see permission-modes page, not read). Combine with `dontAsk` plus `--allowedTools` for fan-out scripts.
- Dynamic workflows and `ultracode` (`/effort ultracode` or keyword): see Section 3. Runs resume in-session; usage-limit hits pause (interactive claude.ai sessions) instead of failing; stalled agents auto-restart up to 5 times (`stallMs`); `meta` block must be a plain literal; `Date.now()`/`Math.random()` throw in scripts. Pass timestamps via `args`.
- Effort control: `/effort`, `--effort`, `CLAUDE_CODE_EFFORT_LEVEL`, frontmatter `effort`, per-invocation `effort` (2.1.292+). On Opus 5.5/Sonnet 5.5/Haiku 5.5/Fable 5.1 with an API key or subscription, changing effort keeps the cache (not on Bedrock/Vertex/gateway/HIPAA/`DISABLE_EXPERIMENTAL_BETAS`).
- Fast mode: Opus 5.5 (and Opus 5, 4.8) only, "up to 2.5x" faster at $8/$40 (2x); subscription users pay via usage credits only; turning it on mid-conversation re-bills the whole context uncached once; Anthropic says standard mode is better for "Long autonomous tasks where speed matters less". Not for overnight runs.
- 1M context: default on current models, flat pricing (Haiku 5.5 excepted); still manage context, because performance degrades as it fills. Tune `autoCompactWindow` (e.g. 300k) per model and per subagent.
- Other: `PreModelSwitch` hook, `/usage` plan-usage attribution by skill/subagent/MCP and flags for long context and cache misses, `--max-budget-usd` (hard budget in `-p` runs), `modelPricing` managed setting, `/rewind`, `/btw`, `/subtask` forks (fork mode default; forks run in background), subagent `maxTurns`. Agent SDK: built-in; see agent-sdk pages (not read).

Unattended-run prompt guidance for Opus 5.5 (primary: Prompting Opus 5.5): the model posts progress updates and some updates end the turn with text, so an unattended loop that treats `end_turn` as finished will stop early. Fixes in order: checklist the model updates; if a turn ends with open items and no stated blocker, send a short continuation message naming them; or run a smaller-model completion check each turn (= `/goal`); stop after two or three automatic continuations; do not treat a turn as done while a background command or subagent is still running. The page also supplies a ready-made system-prompt paragraph naming four early-stop patterns; it must be present from the first request of a session (adding it later edits the system prompt, which invalidates the cache and preserved thinking) and it keeps confirmation for risky actions. The paragraph is long; see the source rather than paste it here.

Sources: [Memory](https://code.claude.com/docs/en/memory), [Best practices](https://code.claude.com/docs/en/best-practices), [Goal](https://code.claude.com/docs/en/goal), [Scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks), [Agent view](https://code.claude.com/docs/en/agent-view), [Fast mode](https://code.claude.com/docs/en/fast-mode), [Model config](https://code.claude.com/docs/en/model-config), [Workflows](https://code.claude.com/docs/en/workflows), [Changelog v2.1.293-2.1.302](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md), [Prompting Opus 5.5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5).

---

## 5. Cost control for long autonomous sessions

Anthropic's own list (Claude Code costs page) plus related guidance:
1. Cache is the main lever; see Section 1. Idle gaps past the TTL are the commonest hidden cost ("your first message after a break longer than the cache lifetime misses the cache and reprocesses your full context"). Resume of an old session is expensive for the same reason.
2. Match model to job: "Sonnet handles most coding tasks well ... Reserve Opus for complex architectural decisions"; `model: haiku` for simple subagents; `CLAUDE_CODE_SUBAGENT_MODEL` for blanket defaults. A switch to Opus also applies to subagents that inherit.
3. Effort: lower for simple tasks (`/effort`); you cannot turn thinking off on the 5.5 models, so effort is the only dial. Thinking is billed as output.
4. Context: `/clear` between tasks, custom compact instructions, keep CLAUDE.md under 200 lines, move specialised procedure to skills, prefer CLI tools over MCP (MCP tool defs are deferred by default), preprocess output with hooks.
5. Parallelism multiplies cost: teams about 7x, N parallel sessions about N-times, every workflow agent has its own requests. Keep teams small, shut teammates down when finished, keep spawn prompts focused, size workflows with `workflowSizeGuideline` (`small` under 5 agents, default `medium` under 10), run a workflow on a small slice first, stop it from `/workflows`.
6. Why usage climbs in long sessions (costs page): long context re-read on every request, cache misses after breaks, scheduled tasks firing into an idle session, cross-session messages, goal check-ins, subagents/workflows/teammates, compaction (a large request itself). `/usage` flags behaviours at 10 percent or more of usage (long context, cache misses).
7. Hard limits: `--max-budget-usd` (print mode), task budgets on the API (`task_budget`, advisory token ceiling, min 20,000, beta `task-budgets-2026-03-13`; supported on Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1 per bundled skill; UNVERIFIED on the live page), workspace spend limits in the Console, usage-credit spend limits on plans, per-user OTel metrics (cache read/creation counters).
8. Batch API is 50 percent off for non-latency-sensitive API work; not available for Claude Code sessions.
9. Cost-per-completed-task is the right metric, not per request (bundled cost-optimization guide).
10. Reference costs for planning: Anthropic's long-running harness runs cost $125 to $200 for 4 to 6 hours of Opus 4.5/4.6 work; their C-compiler project cost just under $20,000 across about 2,000 sessions; enterprise average about $13 per developer-day. Order of magnitude only.
11. Reliability lessons from Anthropic's April 2026 postmortem: a default-effort change, an idle-session thinking-cleanup bug that fired every turn (forgetfulness plus cache misses draining limits; fixed v2.1.101), and a verbosity cap in the system prompt each degraded quality. For us: pin effort and model explicitly, and start a fresh session if a long one becomes forgetful or repetitive.

---

## What changed vs our current CLAUDE.md section 5 model policy

Current policy (from CLAUDE.md section 5, 2026-09-22 to 2026-09-29 revisions): Opus 5.5 = judgment tier; Fable subagents banned; Haiku 4.5 summarises short files; Sonnet 5.5 = workhorse for well-scoped tasks; DeepSeek V4.1 Flash is the implement and grunt primary via opencode; Codex Terra/Luna reviews (note memory says Codex quota exhausted until 2026-11-04, so Claude reviewers cover); Astra only in fenced sessions.

| Item | Our policy | Anthropic guidance (2026-10) | Diff / action |
|---|---|---|---|
| Judgment tier | Opus 5.5 | "Most workloads start with Claude Opus 5.5"; default model in Claude Code | Aligned. |
| Fable subagents | Banned (architect/planning runs may use Fable per owner 09-25/27 memory) | Fable 5.1: highest capability, 2.5x Opus price, slower; use when Opus 5.5 evals at xhigh/max fall short. A Fable advisor gave +1.7 pts for ~2.1x cost | Ban is defensible on cost and agrees with Anthropic's own data; keep as owner policy. Note `fable` is a valid `model:` value and Fable cache reads are cheapest (0.025x), so any future exception should be per-run and still lean on `high` not `xhigh`/`max`. |
| Cheap summariser | Haiku 4.5 | Haiku 5.5 is the current Haiku (default alias since v2.1.293): 1M context vs 200K, $0.10/$0.50 vs $1/$5, adaptive thinking, listed for sub-agent tasks | UPDATE. Replace Haiku 4.5 with Haiku 5.5 (`claude-haiku-5-5`). Caveats: prompts over 100K tokens cost 5x (keep each call under 100K); about 30 percent more tokens for the same text; at `low` effort it may skip checks in long agent prompts, so use `medium`; no server-side refusal fallback. Whether it beats our DeepSeek Flash lane on price for file-sifting is UNVERIFIED (no DeepSeek price in scope). |
| Workhorse | Sonnet 5.5 | "Best combination of speed and intelligence"; start `medium` for well-specified agentic coding, `high` for harder | Aligned; add the effort default. Cache read already 0.05x. |
| Effort | not specified anywhere (grep of CLAUDE.md, AGENTS.md, tiers.json: no hits) | Effort is "often a better lever than switching models"; defaults differ by model; Anthropic's own regression came from a changed default | ADD an effort column to the tiers table; add `effort:` to every `.claude/agents/*.md` (none sets it today). Suggested starting points (to be validated by our evals, not Anthropic prescriptions): Opus 5.5 reviewers `medium`/`high`, package-implementer `medium`, Sonnet 5.5 verifiers `medium`, Haiku 5.5 summarisers `medium`, simple grunt `low`. |
| Cache TTL | not specified; no `promptCacheTtl` / TTL env var in `.claude/settings.json` | 5m default for API-key and for all subagents/workflows/teammates; 1h pays for 5 to 60 min gaps | ADD rule and set `promptCacheTtl: "1h"` and `subagentPromptCacheTtl: "1h"` for orchestrator/overnight runs (project or env). Verify via `usage.cache_creation` that 1h writes appear. Auth type of the overnight runs (subscription vs API key vs credits) is UNVERIFIED and decides whether main bucket already gets 1h. |
| Agent teams | settings enable `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` repo-wide | Named subagents then launch as teammates (about 7x tokens), teams are experimental with resume limits | DECIDE: either keep teams on only inside the `team-overnight` skill (set the env var there) or set `0` for normal sessions. The docs also say start with 3 to 5 teammates and use Sonnet for teammates. |
| Delegation pattern | Orchestrator on Claude judgment tier, fan out to cheap lanes | Orchestrator pays only for independent fan-out beyond one context; dependent chains do better on the single stronger model at lower effort | Keep fan-out for independent packages; for dependent chains prefer one lane at lower effort over lead plus workers. |
| Verification | evidence-verified, blind reviewers | Fresh-context reviewer, evidence not assertions, tell reviewer to flag only correctness gaps, deterministic Stop hooks / `/goal` for completion | Aligned; add the "flag only correctness or stated-requirement gaps" line to reviewer briefs, and consider `/goal` or Stop hook as the completion gate for unattended lanes. |
| Context hygiene | lanes retire at about 300k tokens | 1M window default but performance degrades as context fills; `autoCompactWindow` tunable | Aligned; consider `autoCompactWindow` ~300k on long lanes and per subagent. |
| CLAUDE.md structure | 177 lines, single file, no `.claude/rules/` dir, no `@imports`; AGENTS.md (255 lines) referenced in prose only | Under 200 lines; path-scoped rules; AGENTS.md is NOT auto-read when CLAUDE.md exists | CLAUDE.md is under the line target but dense. Candidates to move to path-scoped rules or skills: "Build & Verification", "PR & Git Workflow", "Design & Co-design", section 5c. Run `/doctor prompt-audit` (v2.1.283+) to find stale and contradictory lines. Add `@AGENTS.md` (or set Project instructions to `claude-md-and-agents-md`) if the "shared repo invariants" in AGENTS.md must be in every session's context; otherwise confirm lanes read it deliberately. Note that imported text still costs context. |
| Memory index | 150 lines, 19.4 KB | Loads first 200 lines or 25KB | OK; headroom is bytes (about 5.6 KB left), so consolidate before adding more. |
| Hooks | PowerShell hooks on PreToolUse/Stop/SessionStart | Hooks are the deterministic layer; `onFailure: "block"`, `SessionStart` `compact` matcher, `PreModelSwitch`, Stop block cap of 8 | Consider a `compact` SessionStart hook to re-inject the handoff-file path, and `PreModelSwitch` to stop accidental cache-busting `/model` flips in long orchestrator sessions. |
| Model IDs | full IDs in agent files | Aliases track newest; pin with IDs | Aligned. Note the `haiku` alias now means Haiku 5.5, so any use of the alias changes meaning silently. |
| Idle compaction | not mentioned | New default (v2.1.299): 200K+ idle about 54 min compacted pre-expiry | Be aware; disable with `idleCompaction: false` if a lane needs its exact transcript, or leave on to save a cold restart. |

---

## UNVERIFIED / not read

- Live prompt-caching API page text beyond character 100,000 (my fetch truncated). The Fable 5.1 keep-alive-versus-1h cost comparison comes from the bundled skill, not the live page.
- Claude Code changelog beyond v2.1.293 to v2.1.302 (no dates in the excerpt); the full changelog is over 1 MB.
- Agent SDK pages (cost tracking, system-prompt modification for cross-user cache sharing), permission-modes, auto-mode config, routines, the hooks reference, the "Prompting Claude Haiku 5.5" and "Prompting Sonnet 5.5" pages (only the what's-new pages were read), the task-budgets page (support list taken from the bundled skill).
- `claude.com/blog` "Prompt caching is everything" is undated in my fetch; I report its rules as given.
- Anthropic does not publish a per-role subagent model table; the role mapping in the diff table (for example Opus reviewers at `medium`/`high`) is my recommendation, not an Anthropic statement. The sub-agents page itself says its per-role suggestions are the fetcher's own, not documented guidance.
- Whether our overnight runs bill via subscription, usage credits or API key (decides the main-bucket TTL default).
- DeepSeek V4.1 Flash pricing and quality relative to Haiku 5.5 (outside Anthropic sources).
- The text of the four-pattern anti-early-stop system prompt is reproduced only by reference; read the source before adopting.
