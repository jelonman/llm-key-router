# LLM Key Router

Local usage-aware LLM gateway for OpenAI-compatible tools.

It exposes a local OpenAI-compatible endpoint and routes requests across user-owned provider keys, models, and local fallbacks while tracking key health, provider/model throttling, and usage state.

```text
client -> http://127.0.0.1:8080/v1/chat/completions -> provider/model/key router
```

## What it is for

- Avoid agent stops caused by one exhausted key, throttled model, or unavailable provider.
- Use a stable local endpoint for tools like Hermes, Continue, Kilo, Codex-style clients, scripts, and local agents.
- Keep provider secrets out of client configs.
- Route between OpenRouter, Ollama Cloud, local Ollama, and local OpenAI-compatible servers.

## What it is not for

- It is not an account creator.
- It is not a payment automator.
- It is not a quota-bypass tool.
- It does not hide abusive usage.
- It does not automate provider dashboards.

## Features

- Local `POST /v1/chat/completions`
- Local `GET /v1/models`
- Local `GET /health`
- Multiple key entries per provider
- Key health checker for OpenRouter
- OpenRouter model discovery
- Optional Ollama Cloud model discovery
- Per-key daily request caps
- Per-model/provider throttling state
- Clear error types
- OpenRouter `models` fallback-list support in route config
- No real keys in logs

## Install from source

```bash
git clone https://github.com/jelonman/llm-key-router.git
cd llm-key-router
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

No runtime third-party dependency is required for the router itself.

## Configure

```bash
cp examples/config.example.json config.json
cp examples/secrets.env.example secrets.env
chmod 600 secrets.env
```

Edit `secrets.env` locally. Do not commit it.

## Run

```bash
python -m llm_key_router --config config.json --secrets secrets.env --state state/router_state.json
```

## Check health

```bash
curl -s http://127.0.0.1:8080/health | python -m json.tool
```

## Call it

```bash
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local" \
  -d '{"model":"or-minimax","messages":[{"role":"user","content":"Reply with ROUTER_OK"}],"stream":false}' | python -m json.tool
```

## Discover models

```bash
python tools/discover_models.py --out state
```

## Check OpenRouter keys

```bash
python tools/check_keys.py --config config.json --secrets secrets.env
```

## Evaluate aliases

```bash
python tools/evaluate_candidates.py --aliases or-minimax or-nemotron or-best-free
```

## Important design choice

The router treats model/provider 429s differently from bad keys. A temporary upstream model/provider throttle should not globally poison a valid credential. Auth failures and quota/payment failures can block a credential; model/provider throttles create model-level temporary blocks.

## License

Apache-2.0.
