#!/usr/bin/env bash
# Start a local OpenAI-compatible llama.cpp server for Astroray agent work.
#
# Run from WSL:
#   bash scripts/start_local_agent_server.sh
#   bash scripts/start_local_agent_server.sh --model qwen35-35b-q3
#
# The defaults are conservative for a 16GB RTX 5070 Ti. Use larger models for
# planning/prototyping, and keep frontier Codex/Claude in the review loop for
# renderer invariants.

set -euo pipefail

HOST="127.0.0.1"
PORT="8080"
CTX_SIZE=""
GPU_LAYERS="99"
MODEL_PROFILE="qwen25-coder-14b-q5"
LLAMA_BIN="${LLAMA_SERVER:-$HOME/.local/bin/llama-server}"
LLAMA_LIB_DIR="${LLAMA_LIB_DIR:-$HOME/.local/lib}"
API_KEY="${OPENAI_API_KEY:-dummy}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: bash scripts/start_local_agent_server.sh [options]

Options:
  --model NAME       Model profile or path. Profiles:
                       qwen25-coder-14b-q5  (default, safest)
                       qwen35-35b-q3        (larger reasoning/prototype model)
                       qwen3-coder-30b-q4   (coding model; uses CPU MoE offload)
  --host HOST        Bind host (default: 127.0.0.1)
  --port PORT        Bind port (default: 8080)
  --ctx-size N       Context size (default: profile-specific or 32768)
  --gpu-layers N     GPU layer offload count (default: 99)
  --dry-run          Print the command without starting the server
  -h, --help         Show this help

Client config:
  OPENAI_API_BASE=http://127.0.0.1:8080/v1
  OPENAI_API_KEY=dummy
  model name can be any non-empty value accepted by the client.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL_PROFILE="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --ctx-size) CTX_SIZE="$2"; shift 2 ;;
    --gpu-layers) GPU_LAYERS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

EXTRA_ARGS=()
case "$MODEL_PROFILE" in
  qwen25-coder-14b-q5)
    MODEL_PATH="$HOME/.models/qwen2.5-coder-14b-instruct-q5_k_m.gguf"
    CTX_SIZE="${CTX_SIZE:-32768}"
    ;;
  qwen35-35b-q3)
    MODEL_PATH="$HOME/.models/Qwen3.5-35B-A3B-Q3_K_S.gguf"
    CTX_SIZE="${CTX_SIZE:-16384}"
    ;;
  qwen3-coder-30b-q4)
    MODEL_PATH="$HOME/.models/qwen3-coder-30b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
    # The Q4 file is larger than 16GB before context. Keep some MoE weights on
    # CPU so the server can run on a 16GB card.
    EXTRA_ARGS+=(--n-cpu-moe 16)
    CTX_SIZE="${CTX_SIZE:-16384}"
    ;;
  /*|~/*|.*)
    MODEL_PATH="$MODEL_PROFILE"
    ;;
  *)
    echo "Unknown model profile: $MODEL_PROFILE" >&2
    usage
    exit 2
    ;;
esac

MODEL_PATH="${MODEL_PATH/#\~/$HOME}"
if [[ ! -x "$LLAMA_BIN" ]]; then
  echo "llama-server not executable: $LLAMA_BIN" >&2
  exit 1
fi
if [[ ! -f "$MODEL_PATH" ]]; then
  echo "Model file not found: $MODEL_PATH" >&2
  exit 1
fi

export LD_LIBRARY_PATH="$LLAMA_LIB_DIR:${LD_LIBRARY_PATH:-}"

CMD=(
  "$LLAMA_BIN"
  --model "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --api-key "$API_KEY"
  --ctx-size "$CTX_SIZE"
  --n-gpu-layers "$GPU_LAYERS"
  --flash-attn on
  --cache-type-k q8_0
  --cache-type-v q4_0
  --jinja
  "${EXTRA_ARGS[@]}"
)

echo "Starting llama.cpp server"
echo "  model: $MODEL_PROFILE"
echo "  file:  $MODEL_PATH"
echo "  url:   http://$HOST:$PORT/v1"
echo "  ctx:   $CTX_SIZE"
echo

if [[ "$DRY_RUN" == 1 ]]; then
  printf '%q ' "${CMD[@]}"
  echo
  exit 0
fi

exec "${CMD[@]}"
