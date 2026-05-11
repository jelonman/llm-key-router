# Providers

## OpenRouter

Uses `https://openrouter.ai/api/v1`, `/chat/completions`, `/key`, and `/models`.

## Ollama Cloud

Uses `https://ollama.com/api/chat` and `https://ollama.com/api/tags` with Bearer auth.

## Local Ollama

Uses `http://127.0.0.1:11434/api/chat` with `auth: none`.

## Local OpenAI-compatible servers

Use `type: openai_compatible` and `auth: none`.
