"""LLM client: OpenAI-compatible Chat Completions wrapper used by all agents.

This module talks to any backend that implements the OpenAI Chat Completions
API (OpenAI itself, DeepSeek, Together, vLLM, an Azure-OpenAI gateway, etc.).
Backend selection is purely environment-variable driven so the repository
contains no provider- or institution-specific identifiers.

Required environment variables
------------------------------
``OPENAI_API_KEY`` (or the ``api_key_env`` declared in ``config.yaml`` for a
particular model) — credential passed to the OpenAI SDK.

Optional environment variables
------------------------------
``OPENAI_BASE_URL`` (or the ``base_url_env`` declared in ``config.yaml``) —
endpoint to target. Leave unset to use the OpenAI default endpoint.

Example
-------
    >>> from agents.llm_client import call_llm
    >>> r = call_llm([{"role": "user", "content": "hi"}], model_name="gpt-4o")
    >>> r.text, r.input_tokens, r.output_tokens
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from openai import OpenAI

from agents.config_loader import get as cfg_get


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------
def _model_spec(model_name: str) -> dict:
    """Resolve a model alias against ``config.yaml: models``.

    Falls back to a permissive default that uses the alias as the deployment
    name, so an unknown alias works as long as the configured backend hosts
    that exact model id.
    """
    spec = cfg_get("models", model_name)
    if spec:
        return spec
    return {
        "deployment": model_name,
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
    }


# Backwards-compatible mapping kept for callers that introspect MODEL_LIST.
MODEL_LIST: dict[str, dict] = {
    name: {"deployment_name": (cfg or {}).get("deployment", name)}
    for name, cfg in (cfg_get("models") or {}).items()
}


_clients: dict[str, OpenAI] = {}


def get_client(model_name: str = "gpt-4o") -> tuple[OpenAI, str]:
    """Return ``(OpenAI client, deployment name)`` for ``model_name``."""
    spec = _model_spec(model_name)
    deployment = spec["deployment"]
    cache_key = f"{spec.get('base_url_env', 'OPENAI_BASE_URL')}::{spec.get('api_key_env', 'OPENAI_API_KEY')}"
    if cache_key in _clients:
        return _clients[cache_key], deployment

    api_key = os.environ.get(spec.get("api_key_env", "OPENAI_API_KEY"))
    if not api_key:
        raise RuntimeError(
            f"Environment variable {spec.get('api_key_env', 'OPENAI_API_KEY')!r} is not set; "
            "see config.yaml for how to register API credentials."
        )
    base_url = os.environ.get(spec.get("base_url_env", "OPENAI_BASE_URL"))
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    _clients[cache_key] = client
    return client, deployment


# ---------------------------------------------------------------------------
# Standardised result wrapper
# ---------------------------------------------------------------------------
class LLMResult:
    """Holds the text and token-usage statistics returned by ``call_llm``."""

    def __init__(self, text: str, input_tokens: int, output_tokens: int,
                 elapsed_s: float, raw: Any | None = None) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens
        self.elapsed_s = elapsed_s
        self.raw = raw


# ---------------------------------------------------------------------------
# Chat completion call
# ---------------------------------------------------------------------------
def call_llm(messages, model_name: str = "gpt-4o", temperature: float | None = None,
             max_tokens: int | None = None, reasoning_effort: str = "medium",
             enable_thinking: bool = True) -> LLMResult:
    """Send ``messages`` to the configured backend and return an ``LLMResult``.

    Streaming is the default because long agent rounds otherwise hit upstream
    proxy timeouts; usage statistics are still recovered from the final chunk
    because we request ``stream_options.include_usage``.
    """
    spec = _model_spec(model_name)
    client, deployment = get_client(model_name)
    if temperature is None:
        temperature = cfg_get("llm", "temperature", default=0)

    t0 = time.time()
    kwargs: dict[str, Any] = dict(model=deployment, messages=messages)
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    # OpenAI o-series models reject the temperature parameter.
    if not deployment.lower().startswith("o"):
        kwargs["temperature"] = temperature

    if cfg_get("llm", "stream", default=True):
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

    # Optional reasoning controls (for OpenAI o-series and some compatible APIs).
    reasoning = spec.get("reasoning")
    if reasoning:
        kwargs["reasoning_effort"] = reasoning if reasoning != "auto" else reasoning_effort
    extra_body = spec.get("extra_body")
    if extra_body:
        kwargs["extra_body"] = extra_body
    elif not enable_thinking and "extra_body" not in kwargs:
        # Allow callers to suppress thinking traces on Qwen-style backends.
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    if kwargs.get("stream"):
        stream = client.chat.completions.create(**kwargs)
        text_parts: list[str] = []
        usage_data = None
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text_parts.append(chunk.choices[0].delta.content)
            if chunk.usage:
                usage_data = chunk.usage
        text = "".join(text_parts)
    else:
        completion = client.chat.completions.create(**kwargs)
        text = completion.choices[0].message.content or ""
        usage_data = completion.usage

    elapsed = time.time() - t0
    input_tokens = getattr(usage_data, "prompt_tokens", 0) or 0 if usage_data else 0
    output_tokens = getattr(usage_data, "completion_tokens", 0) or 0 if usage_data else 0
    return LLMResult(text, input_tokens, output_tokens, elapsed)


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------
def extract_json(text: str):
    """Best-effort JSON extraction from an LLM response."""
    try:
        return json.loads(text)
    except Exception:
        pass

    for start_marker in ("```json", "```"):
        if start_marker in text:
            start = text.index(start_marker) + len(start_marker)
            end = text.find("```", start)
            if end == -1:
                continue
            try:
                return json.loads(text[start:end].strip())
            except Exception:
                pass

    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        in_str = False
        escape = False
        for i in range(brace_start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except Exception:
                        break
    return None
