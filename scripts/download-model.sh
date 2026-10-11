#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-./models/MiniCPM-o-4_5-gguf}"
MODEL_BASE_URL="${MODEL_BASE_URL:-https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf/resolve/main}"

files=(
  "MiniCPM-o-4_5-Q4_K_M.gguf"
  "audio/MiniCPM-o-4_5-audio-F16.gguf"
  "vision/MiniCPM-o-4_5-vision-F16.gguf"
  "tts/MiniCPM-o-4_5-tts-F16.gguf"
  "tts/MiniCPM-o-4_5-projector-F16.gguf"
  "token2wav-gguf/encoder.gguf"
  "token2wav-gguf/flow_matching.gguf"
  "token2wav-gguf/flow_extra.gguf"
  "token2wav-gguf/hifigan2.gguf"
  "token2wav-gguf/prompt_cache.gguf"
)

mkdir -p "$MODEL_DIR"
for file in "${files[@]}"; do
  destination="$MODEL_DIR/$file"
  mkdir -p "$(dirname "$destination")"
  echo "Downloading $file"
  curl --fail --location --retry 5 --retry-delay 5 --continue-at - \
    --output "$destination" "$MODEL_BASE_URL/$file"
done

echo "Model files are ready in $MODEL_DIR"
