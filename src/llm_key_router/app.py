from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import __version__
except Exception:
    __version__ = "0.2.0"


def utc_day() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def now() -> float:
    return time.time()


def jdumps(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_env(path: Path) -> Dict[str, str]:
    vals: Dict[str, str] = {}
    if not path.exists():
        return vals
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{n}: expected KEY=value")
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            raise ValueError(f"{path}:{n}: empty key")
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        vals[k] = v
    return vals


def secret(env_name: Optional[str], env_file: Dict[str, str]) -> Optional[str]:
    if not env_name:
        return None
    return os.environ.get(env_name) or env_file.get(env_name)


def short(x: Any, limit: int = 800) -> str:
    s = x if isinstance(x, str) else repr(x)
    return s[:limit] + ("...<truncated>" if len(s) > limit else "")


@dataclass
class Credential:
    provider: str
    label: str
    api_key: Optional[str]
    api_key_env: Optional[str]


@dataclass
class UpstreamResult:
    ok: bool
    status: int
    headers: Dict[str, str]
    body: bytes
    provider: str
    credential_label: str
    actual_model: str
    error_type: str = ""
    error_message: str = ""
    upstream_provider: str = ""
    retry_after_seconds: int = 0


def classify_http_error(status: int, body: bytes, headers: Dict[str, str]) -> Tuple[str, str, str, int]:
    raw = body.decode("utf-8", errors="replace") if body else ""
    retry_after = 0
    if headers.get("Retry-After"):
        try: retry_after = int(float(headers["Retry-After"]))
        except Exception: pass
    upstream_provider = ""
    try:
        data = json.loads(raw)
        err = data.get("error", {}) if isinstance(data, dict) else {}
        meta = err.get("metadata", {}) if isinstance(err, dict) else {}
        upstream_provider = str(meta.get("provider_name") or "")
        ra = meta.get("retry_after_seconds")
        if ra is not None:
            retry_after = max(retry_after, int(float(ra)))
    except Exception:
        pass
    if status in (401, 403): return "key_auth_error", short(raw), upstream_provider, retry_after
    if status == 402: return "account_quota_or_payment_error", short(raw), upstream_provider, retry_after
    if status == 429: return "model_or_provider_rate_limited", short(raw), upstream_provider, retry_after or 15
    if status in (408, 425, 500, 502, 503, 504): return "model_or_provider_unavailable", short(raw), upstream_provider, retry_after or 30
    return "upstream_http_error", short(raw), upstream_provider, retry_after


class State:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _empty(self) -> Dict[str, Any]:
        return {"state_version": 2, "utc_day": utc_day(), "providers": {}, "model_blocks": {}, "last_saved_epoch": 0}

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists(): return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.path.rename(self.path.with_suffix(self.path.suffix + f".corrupt.{int(now())}"))
            return self._empty()
        if data.get("utc_day") != utc_day():
            data["utc_day"] = utc_day()
            data["model_blocks"] = {}
            for p in data.get("providers", {}).values():
                for c in p.get("credentials", {}).values():
                    c["requests_today"] = c["success_today"] = c["failure_today"] = 0
                    if c.get("blocked_reason") in ("model_or_provider_rate_limited", "model_or_provider_unavailable", "network_error"):
                        c["blocked_until_epoch"] = 0; c["blocked_reason"] = ""
        return data

    def save(self) -> None:
        self.data["last_saved_epoch"] = int(now())
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def provider(self, name: str) -> Dict[str, Any]:
        return self.data.setdefault("providers", {}).setdefault(name, {"credentials": {}, "cursor": 0})

    def cursor(self, provider: str) -> int:
        return int(self.provider(provider).get("cursor", 0) or 0)

    def set_cursor(self, provider: str, val: int) -> None:
        self.provider(provider)["cursor"] = int(val)

    def cred(self, provider: str, label: str) -> Dict[str, Any]:
        return self.provider(provider).setdefault("credentials", {}).setdefault(label, {
            "requests_today": 0, "success_today": 0, "failure_today": 0,
            "total_requests": 0, "total_success": 0, "total_failure": 0,
            "blocked_until_epoch": 0, "blocked_reason": "", "last_status": None,
            "last_error_type": "", "last_error": "", "last_used_epoch": 0,
        })

    def daily_count(self, provider: str, label: str) -> int:
        return int(self.cred(provider, label).get("requests_today", 0) or 0)

    def credential_blocked(self, provider: str, label: str) -> bool:
        return float(self.cred(provider, label).get("blocked_until_epoch", 0) or 0) > now()

    def inc_request(self, provider: str, label: str) -> None:
        s = self.cred(provider, label)
        s["requests_today"] += 1; s["total_requests"] += 1; s["last_used_epoch"] = int(now())

    def success(self, provider: str, label: str, status: int) -> None:
        s = self.cred(provider, label)
        s["success_today"] += 1; s["total_success"] += 1; s["last_status"] = status
        s["last_error"] = ""; s["last_error_type"] = ""

    def failure(self, provider: str, label: str, status: int, error_type: str, message: str, block_seconds: int = 0) -> None:
        s = self.cred(provider, label)
        s["failure_today"] += 1; s["total_failure"] += 1; s["last_status"] = status
        s["last_error_type"] = error_type; s["last_error"] = message[:800]
        if block_seconds > 0:
            s["blocked_until_epoch"] = int(now()) + int(block_seconds); s["blocked_reason"] = error_type

    def model_key(self, provider: str, model: str, upstream: str = "") -> str:
        return f"{provider}::{model}::{upstream or 'unknown'}"

    def model_blocked(self, provider: str, model: str, upstream: str = "") -> bool:
        b = self.data.setdefault("model_blocks", {}).get(self.model_key(provider, model, upstream))
        return bool(b and float(b.get("blocked_until_epoch", 0) or 0) > now())

    def block_model(self, provider: str, model: str, seconds: int, reason: str, upstream: str = "") -> None:
        if seconds <= 0: return
        self.data.setdefault("model_blocks", {})[self.model_key(provider, model, upstream)] = {
            "provider": provider, "model": model, "upstream_provider": upstream, "reason": reason,
            "blocked_until_epoch": int(now()) + int(seconds),
        }


class Router:
    def __init__(self, config_path: Path, secrets_path: Path, state_path: Path):
        self.config_path = config_path; self.secrets_path = secrets_path; self.state_path = state_path
        self.config = load_json(config_path); self.env = parse_env(secrets_path); self.state = State(state_path)

    def providers(self) -> Dict[str, Any]: return self.config.get("providers", {})
    def routes(self) -> Dict[str, Any]: return self.config.get("routes", {})

    def models_payload(self) -> Dict[str, Any]:
        return {"object": "list", "data": [{"id": a, "object": "model", "created": 0, "owned_by": "llm-key-router"} for a in sorted(self.routes())]}

    def resolve(self, model: str) -> Dict[str, Any]:
        if model in self.routes(): return self.routes()[model]
        default = self.config.get("default_route")
        if self.config.get("allow_unknown_model_fallback") and default in self.routes(): return self.routes()[default]
        raise KeyError(f"Unknown model alias: {model}")

    def credentials(self, provider_name: str, cfg: Dict[str, Any]) -> List[Credential]:
        if cfg.get("auth") == "none": return [Credential(provider_name, "no_auth", None, None)]
        out: List[Credential] = []
        for item in cfg.get("credentials", []):
            if not item.get("enabled", True): continue
            label = item.get("label"); env_name = item.get("api_key_env")
            if not label: continue
            key = secret(env_name, self.env)
            if not key: continue
            if self.state.credential_blocked(provider_name, label): continue
            cap = int(cfg.get("daily_request_cap_per_credential", 0) or 0)
            if cap > 0 and self.state.daily_count(provider_name, label) >= cap: continue
            out.append(Credential(provider_name, label, key, env_name))
        if cfg.get("credential_strategy", "round_robin") == "round_robin" and out:
            cur = self.state.cursor(provider_name); idx = cur % len(out); self.state.set_cursor(provider_name, cur + 1)
            out = out[idx:] + out[:idx]
        return out

    def route_chat(self, body: Dict[str, Any]) -> UpstreamResult:
        requested = str(body.get("model") or self.config.get("default_route"))
        route = self.resolve(requested)
        errors: List[str] = []; types: List[str] = []
        for target in route.get("targets", []):
            provider_name = target["provider"]; pcfg = self.providers().get(provider_name)
            if not pcfg or not pcfg.get("enabled", True):
                errors.append(f"{provider_name}: disabled_or_missing"); continue
            model = target.get("model"); models = target.get("models")
            if model and self.state.model_blocked(provider_name, model):
                errors.append(f"{provider_name}/{model}: model_temporarily_blocked"); continue
            creds = self.credentials(provider_name, pcfg)[:max(1, int(target.get("credential_attempts", pcfg.get("attempts_per_provider", 1))))]
            if not creds:
                errors.append(f"{provider_name}: no_eligible_credentials"); continue
            for cred in creds:
                req_body = copy.deepcopy(body)
                actual_model = str(model or ",".join(models or []))
                if models:
                    req_body.pop("model", None); req_body["models"] = models
                    pref = req_body.setdefault("provider", {})
                    pref["allow_fallbacks"] = target.get("allow_fallbacks", True)
                    if target.get("provider_sort"): pref["sort"] = target["provider_sort"]
                else:
                    req_body["model"] = model
                if self.config.get("force_non_streaming", True): req_body["stream"] = False
                self.state.inc_request(provider_name, cred.label)
                result = self.forward(provider_name, pcfg, cred, req_body, actual_model)
                if result.ok:
                    self.state.success(provider_name, cred.label, result.status); self.state.save(); return result
                types.append(result.error_type)
                errors.append(f"{provider_name}/{cred.label}/{actual_model}: HTTP {result.status} {result.error_type} {result.error_message[:500]}")
                self.record_failure(provider_name, pcfg, cred.label, actual_model, result)
        status, etype = self.collapse(types)
        return UpstreamResult(False, status, {"Content-Type": "application/json"}, jdumps({"error": {"message": "No configured upstream completed the request.", "type": etype, "details": errors[-20:]}}), "none", "none", requested, etype, "; ".join(errors[-5:]))

    def forward(self, provider: str, pcfg: Dict[str, Any], cred: Credential, body: Dict[str, Any], actual_model: str) -> UpstreamResult:
        if pcfg.get("type") == "ollama_native": return self.forward_ollama(provider, pcfg, cred, body, actual_model)
        return self.forward_openai_compatible(provider, pcfg, cred, body, actual_model)

    def forward_openai_compatible(self, provider: str, pcfg: Dict[str, Any], cred: Credential, body: Dict[str, Any], actual_model: str) -> UpstreamResult:
        url = str(pcfg["base_url"]).rstrip("/") + pcfg.get("chat_completions_path", "/chat/completions")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if pcfg.get("auth", "bearer") != "none": headers["Authorization"] = "Bearer " + str(cred.api_key)
        headers.update({str(k): str(v) for k, v in pcfg.get("extra_headers", {}).items()})
        req = urllib.request.Request(url, data=jdumps(body), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=float(pcfg.get("timeout_seconds", 180))) as r:
                return UpstreamResult(200 <= r.status < 300, r.status, dict(r.headers.items()), r.read(), provider, cred.label, actual_model)
        except urllib.error.HTTPError as e:
            raw = e.read(); h = dict(e.headers.items()) if e.headers else {}; et, msg, up, ra = classify_http_error(e.code, raw, h)
            return UpstreamResult(False, e.code, h, raw, provider, cred.label, actual_model, et, msg, up, ra)
        except Exception as e:
            return UpstreamResult(False, 599, {}, b"", provider, cred.label, actual_model, "network_error", short(e), "", int(pcfg.get("network_failure_block_seconds", 15)))

    def forward_ollama(self, provider: str, pcfg: Dict[str, Any], cred: Credential, body: Dict[str, Any], actual_model: str) -> UpstreamResult:
        url = str(pcfg["base_url"]).rstrip("/") + pcfg.get("chat_path", "/api/chat")
        obody = {"model": actual_model, "messages": body.get("messages", []), "stream": False}
        opts = {}
        if "temperature" in body: opts["temperature"] = body["temperature"]
        if "top_p" in body: opts["top_p"] = body["top_p"]
        if "max_tokens" in body: opts["num_predict"] = body["max_tokens"]
        if opts: obody["options"] = opts
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if pcfg.get("auth", "bearer") != "none": headers["Authorization"] = "Bearer " + str(cred.api_key)
        req = urllib.request.Request(url, data=jdumps(obody), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=float(pcfg.get("timeout_seconds", 180))) as r:
                raw = r.read(); data = json.loads(raw.decode("utf-8")); msg = data.get("message", {})
                mapped = {"id": f"llm-key-router-ollama-{int(now())}", "object": "chat.completion", "created": int(now()), "model": actual_model, "choices": [{"index": 0, "message": {"role": msg.get("role", "assistant"), "content": msg.get("content", "")}, "finish_reason": data.get("done_reason") or "stop"}], "usage": {"prompt_tokens": data.get("prompt_eval_count", 0) or 0, "completion_tokens": data.get("eval_count", 0) or 0, "total_tokens": (data.get("prompt_eval_count", 0) or 0) + (data.get("eval_count", 0) or 0)}}
                return UpstreamResult(True, r.status, {"Content-Type": "application/json"}, jdumps(mapped), provider, cred.label, actual_model)
        except urllib.error.HTTPError as e:
            raw = e.read(); h = dict(e.headers.items()) if e.headers else {}; et, msg, up, ra = classify_http_error(e.code, raw, h)
            return UpstreamResult(False, e.code, h, raw, provider, cred.label, actual_model, et, msg, up, ra)
        except Exception as e:
            return UpstreamResult(False, 599, {}, b"", provider, cred.label, actual_model, "network_error", short(e), "", int(pcfg.get("network_failure_block_seconds", 15)))

    def record_failure(self, provider: str, pcfg: Dict[str, Any], label: str, model: str, r: UpstreamResult) -> None:
        if r.error_type in ("key_auth_error", "account_quota_or_payment_error"):
            self.state.failure(provider, label, r.status, r.error_type, r.error_message, 86400)
        elif r.error_type in ("model_or_provider_rate_limited", "model_or_provider_unavailable"):
            self.state.failure(provider, label, r.status, r.error_type, r.error_message, 0)
            self.state.block_model(provider, model, min(max(r.retry_after_seconds or int(pcfg.get("model_failure_block_seconds", 30)), 1), int(pcfg.get("max_model_block_seconds", 300))), r.error_type, r.upstream_provider)
        else:
            self.state.failure(provider, label, r.status, r.error_type, r.error_message, int(pcfg.get("network_failure_block_seconds", 15)))
        self.state.save()

    def collapse(self, types: List[str]) -> Tuple[int, str]:
        if not types: return 503, "no_eligible_upstream"
        if all(t == "model_or_provider_rate_limited" for t in types): return 429, "all_models_or_providers_rate_limited"
        if all(t == "key_auth_error" for t in types): return 401, "all_credentials_auth_failed"
        if all(t == "account_quota_or_payment_error" for t in types): return 402, "all_accounts_quota_or_payment_failed"
        if "model_or_provider_rate_limited" in types: return 429, "some_models_or_providers_rate_limited"
        return 503, "all_upstreams_failed"


def make_handler(router: Router):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"LLMKeyRouter/{__version__}"
        def log_message(self, fmt: str, *args: Any) -> None:
            if router.config.get("log_requests", True): sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))
        def send_json(self, status: int, obj: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> None:
            self.send_bytes(status, jdumps(obj), "application/json", headers)
        def send_bytes(self, status: int, data: bytes, ctype: str, headers: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
            for k, v in (headers or {}).items():
                if k.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}: self.send_header(k, str(v))
            self.end_headers(); self.wfile.write(data)
        def do_OPTIONS(self) -> None:
            self.send_response(204); self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1"); self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS"); self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type"); self.end_headers()
        def do_GET(self) -> None:
            if self.path == "/health": return self.send_json(200, {"ok": True, "service": "llm-key-router", "version": __version__, "aliases": sorted(router.routes()), "secrets_file_exists": router.secrets_path.exists()})
            if self.path == "/v1/models": return self.send_json(200, router.models_payload())
            return self.send_json(404, {"error": {"message": "Not found", "type": "not_found"}})
        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions": return self.send_json(404, {"error": {"message": "Use POST /v1/chat/completions", "type": "not_found"}})
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0: return self.send_json(400, {"error": {"message": "Missing body", "type": "bad_request"}})
                if length > int(router.config.get("max_request_body_bytes", 20_000_000)): return self.send_json(413, {"error": {"message": "Request too large", "type": "request_too_large"}})
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                result = router.route_chat(body)
                headers = {"X-LLM-Key-Router-Provider": result.provider, "X-LLM-Key-Router-Credential": result.credential_label, "X-LLM-Key-Router-Model": result.actual_model, "X-LLM-Key-Router-Error-Type": result.error_type}
                ctype = result.headers.get("Content-Type") or result.headers.get("content-type") or "application/json"
                return self.send_bytes(result.status, result.body, ctype, headers)
            except json.JSONDecodeError: return self.send_json(400, {"error": {"message": "Invalid JSON", "type": "bad_request"}})
            except KeyError as e: return self.send_json(400, {"error": {"message": str(e), "type": "unknown_model_alias"}})
            except Exception as e: return self.send_json(500, {"error": {"message": short(e), "type": "router_internal_error"}})
    return Handler


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="LLM Key Router")
    p.add_argument("--config", default="config.json"); p.add_argument("--secrets", default="secrets.env"); p.add_argument("--state", default="state/router_state.json"); p.add_argument("--host"); p.add_argument("--port", type=int)
    args = p.parse_args(argv)
    router = Router(Path(args.config).resolve(), Path(args.secrets).resolve(), Path(args.state).resolve())
    host = args.host or router.config.get("server", {}).get("host", "127.0.0.1"); port = args.port or int(router.config.get("server", {}).get("port", 8080))
    httpd = ThreadingHTTPServer((host, port), make_handler(router))
    print(f"[llm-key-router] listening on http://{host}:{port}"); print(f"[llm-key-router] config: {router.config_path}"); print(f"[llm-key-router] secrets file exists: {router.secrets_path.exists()}"); print(f"[llm-key-router] aliases: {', '.join(sorted(router.routes()))}"); print("[llm-key-router] raw API keys are never printed")
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\n[llm-key-router] stopped")
    finally: httpd.server_close()
    return 0
