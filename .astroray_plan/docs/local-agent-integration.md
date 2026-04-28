# Local Agent Integration Plan

**Status:** proposed  
**Purpose:** let Codex, Claude Code, Cline, and background workers use local
models where that saves paid subscription/API budget, while preserving a clear
quality gate before anything reaches `main`.

## Recommended Architecture

Use **Ollama as the default local runtime** and keep **LM Studio as the GUI
fallback**. Both expose local model servers that current agent tools can use.

```
Codex CLI/App (paid frontier when needed)
        |
        |-- local/offline mode for cheap drafts via Ollama or LM Studio
        |
Cline / Ralph / future queue worker
        |
        |-- Ollama at http://localhost:11434
        |-- model: Qwen3 Coder 30B or best local coding model that fits VRAM/RAM
```

Sources checked on 2026-04-28:

- OpenAI's Codex agent-loop documentation says Codex CLI can use configurable
  Responses API endpoints and, with `--oss`, defaults to a local Ollama/LM
  Studio endpoint for gpt-oss-compatible local runs:
  https://openai.com/index/unrolling-the-codex-agent-loop/
- Cline's local-model documentation recommends LM Studio or Ollama, with Qwen3
  Coder 30B as the primary sub-70B local coding model:
  https://docs.cline.bot/running-models-locally/overview
- Ollama's Cline integration docs specify selecting Ollama as Cline's provider
  and using at least a 32K context window for coding tools:
  https://docs.ollama.com/integrations/cline
- Ollama's Qwen3 Coder library lists `qwen3-coder:30b` as a 30B local tag:
  https://ollama.com/library/qwen3-coder

## Tool Roles

| Tool | Local model role | Paid model role |
|---|---|---|
| Codex | quick local drafts, issue shaping, simple edits | PR-quality changes, review, GitHub operations |
| Claude Code | experimental only through compatible local endpoints | core track-A implementation |
| Cline | main local prototype interface | optional fallback if local model fails |
| Ralph loop | overnight mechanical queue | none by default |

## Setup Steps

1. Install Ollama.
2. Pull one serious coding model and one small fallback:
   ```bash
   ollama pull qwen3-coder:30b
   ollama pull qwen2.5-coder:7b
   ```
3. Confirm the server is running:
   ```bash
   ollama list
   ```
4. Configure Cline:
   - Provider: `Ollama`
   - Base URL: `http://localhost:11434`
   - Context window: at least `32768`
   - Use compact prompts if available
5. Test Codex local mode from a terminal before relying on it for repo work:
   ```bash
   codex --oss
   ```
6. Add a future queue worker only after local Cline/Ollama behavior is stable.

## Guardrails

- Local models may draft code, but a frontier model or human should review any
  change touching `include/raytracer.h`, GR math, spectral conversion, sampling,
  MIS, CMake dependency plumbing, or Blender export behavior.
- Local-model branches use `proto/<topic>` or `ralph/<task>`, not `main`.
- Codex or Claude Code should turn successful prototypes into clean PRs.
- Failed local-model attempts should produce notes, not hidden state. If a task
  fails twice, rewrite the task spec before trying again.

## First Practical Use

Use local models for these near-term tasks:

- generate additional low-risk tests around plugin registry contracts
- inspect rendered PNGs and produce candidate assertions for Codex/Claude review
- draft package specs for Pillar 3 subpackages
- prototype tiny-cuda-nn build wiring in a throwaway branch

Do **not** start local models on ReSTIR correctness, GR dispatch, or spectral
path changes until the task has a tight spec and an owner model for review.
