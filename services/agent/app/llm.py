"""Provider-pluggable LLM layer.

Primary: OpenAI (OPENAI_API_KEY, LLM_MODEL default gpt-4o-mini).
Optional alternatives via env: NEBIUS_API_KEY, FIREWORKS_API_KEY
(OpenAI-compatible endpoints). If NO key is set, mode = "fallback":
callers must supply a grounded extractive/template fallback and
generation builds artifacts ONLY from fetched evidence.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("prism.llm")

PROVIDERS = [
    # (env key, provider name, base_url env / default base_url)
    ("OPENAI_API_KEY", "openai", None),
    ("NEBIUS_API_KEY", "nebius", "https://api.tokenfactory.nebius.com/v1"),
    ("FIREWORKS_API_KEY", "fireworks", "https://api.fireworks.ai/inference/v1"),
]


class LLMService:
    def __init__(self) -> None:
        self.provider = "fallback"
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self.calls = 0
        self._client = None
        for env_key, name, default_base in PROVIDERS:
            key = os.environ.get(env_key)
            if key:
                self.provider = name
                try:
                    from langchain_openai import ChatOpenAI

                    base = os.environ.get(f"{name.upper()}_BASE_URL", default_base)
                    kwargs = {"model": self.model, "api_key": key, "temperature": 0.4}
                    if base:
                        kwargs["base_url"] = base
                    self._client = ChatOpenAI(**kwargs)
                except Exception as exc:  # pragma: no cover
                    log.warning("LLM client init failed (%s): %s — using fallback", name, exc)
                    self.provider = "fallback"
                    self._client = None
                break
        log.info("LLM mode: provider=%s model=%s", self.provider, self.model)
        print(f"[prism] LLM mode: provider={self.provider} model={self.model}", flush=True)

    @property
    def mode(self) -> str:
        return self.provider

    def generate(self, system: str, user: str, fallback: str) -> str:
        """Return LLM text, or the grounded fallback string when key-free / on error."""
        if self._client is None:
            return fallback
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            resp = self._client.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            self.calls += 1
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            return text.strip() or fallback
        except Exception as exc:
            log.warning("LLM call failed, using grounded fallback: %s", exc)
            return fallback


_llm: LLMService | None = None


def get_llm() -> LLMService:
    global _llm
    if _llm is None:
        _llm = LLMService()
    return _llm


def reset_llm() -> LLMService:
    global _llm
    _llm = LLMService()
    return _llm
