"""Multi-provider LLM abstraction — Issue #15.

Supports Anthropic Claude, OpenAI GPT, Google Gemini, and local Ollama models
through a unified :class:`LLMProvider` protocol.  Providers are registered
in a :class:`ProviderRegistry` and can be instantiated from a config dict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LLMMessage:
    """A single message in an LLM conversation.

    Attributes:
        role: Message role — ``"user"``, ``"assistant"``, or ``"system"``.
        content: Text content of the message.
    """

    role: str
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM provider.

    Attributes:
        content: The generated text content.
        model: Model identifier used for generation.
        input_tokens: Number of input (prompt) tokens consumed.
        output_tokens: Number of output (completion) tokens generated.
        tool_calls: Optional list of tool-call dicts returned by the model.
        raw: Raw API response dict for provider-specific fields.
    """

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Total token count (input + output)."""
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM provider implementations must satisfy."""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send a chat-completion request and return a structured response.

        Args:
            messages: List of message dicts with at least ``role`` and ``content``.
            tools: Optional list of tool/function definitions (provider-specific format).

        Returns:
            :class:`LLMResponse` with generated content and token counts.
        """
        ...


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------


class AnthropicProvider:
    """LLM provider for Anthropic Claude models via the Messages API.

    Uses :mod:`httpx` directly (no official SDK dependency).

    Args:
        api_key: Anthropic API key (``sk-ant-...``).
        model: Model identifier.  Defaults to ``"claude-sonnet-4-20250514"``.
        max_tokens: Maximum tokens to generate.
        timeout: HTTP request timeout in seconds.
    """

    _API_URL = "https://api.anthropic.com/v1/messages"
    _API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            headers={
                "x-api-key": api_key,
                "anthropic-version": self._API_VERSION,
                "content-type": "application/json",
            },
            timeout=timeout,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send a request to the Anthropic Messages API.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
                      System messages are extracted and passed separately.
            tools: Optional Anthropic-format tool definitions.

        Returns:
            :class:`LLMResponse` with the assistant reply.

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
        """
        # Separate system prompt from conversation messages
        system_content = ""
        conversation: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content += msg.get("content", "") + "\n"
            else:
                conversation.append(msg)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": conversation,
        }
        if system_content.strip():
            payload["system"] = system_content.strip()
        if tools:
            payload["tools"] = tools

        resp = await self._client.post(self._API_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = ""
        tool_calls: list[dict[str, Any]] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            tool_calls=tool_calls,
            raw=data,
        )

    async def __aenter__(self) -> AnthropicProvider:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# OpenAI (GPT)
# ---------------------------------------------------------------------------


class OpenAIProvider:
    """LLM provider for OpenAI ChatCompletion models.

    Args:
        api_key: OpenAI API key.
        model: Model identifier.  Defaults to ``"gpt-4o"``.
        base_url: API base URL (override for Azure or compatible endpoints).
        max_tokens: Maximum tokens to generate.
        timeout: HTTP request timeout in seconds.
    """

    _DEFAULT_BASE = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        base = (base_url or self._DEFAULT_BASE).rstrip("/")
        self._chat_url = f"{base}/chat/completions"
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send a request to the OpenAI Chat Completions API.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            tools: Optional OpenAI-format function/tool definitions.

        Returns:
            :class:`LLMResponse` with the assistant reply.

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        resp = await self._client.post(self._chat_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = [
            {
                "id": tc.get("id"),
                "type": tc.get("type"),
                "function": tc.get("function", {}),
            }
            for tc in raw_tool_calls
        ]

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            tool_calls=tool_calls,
            raw=data,
        )

    async def __aenter__(self) -> OpenAIProvider:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Ollama (local models)
# ---------------------------------------------------------------------------


class OllamaProvider:
    """LLM provider for locally hosted models via Ollama's REST API.

    Args:
        base_url: Base URL of the Ollama server.  Defaults to
            ``"http://localhost:11434"``.
        model: Model name as registered in Ollama.  Defaults to ``"llama3"``.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout: float = 300.0,
    ) -> None:
        self.model = model
        base = base_url.rstrip("/")
        self._chat_url = f"{base}/api/chat"
        self._client = httpx.AsyncClient(timeout=timeout)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,  # noqa: ARG002
    ) -> LLMResponse:
        """Send a request to Ollama's /api/chat endpoint.

        Note: Ollama does not natively support tool calls in the same format
        as OpenAI — tool definitions are currently ignored.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            tools: Ignored (not supported by Ollama's API).

        Returns:
            :class:`LLMResponse` with the assistant reply.

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        resp = await self._client.post(self._chat_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        message = data.get("message", {})
        content = message.get("content", "")

        # Ollama reports token counts in eval_count / prompt_eval_count
        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            raw=data,
        )

    async def __aenter__(self) -> OllamaProvider:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Gemini (Google)
# ---------------------------------------------------------------------------


class GeminiProvider:
    """LLM provider for Google Gemini models via the Generative Language API.

    Args:
        api_key: Google AI Studio / Vertex AI API key.
        model: Model name.  Defaults to ``"gemini-2.0-flash"``.
        timeout: HTTP request timeout in seconds.
    """

    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,  # noqa: ARG002
    ) -> LLMResponse:
        """Send a request to the Gemini generateContent endpoint.

        Converts the standard message list to Gemini's ``contents`` format.

        Args:
            messages: List of ``{"role": ..., "content": ...}`` dicts.
            tools: Optional tool definitions (ignored in current implementation).

        Returns:
            :class:`LLMResponse` with the model reply.

        Raises:
            httpx.HTTPStatusError: On non-2xx API responses.
        """
        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, str]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": content})
            else:
                gemini_role = "model" if role == "assistant" else "user"
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["system_instruction"] = {"parts": system_parts}

        url = f"{self._BASE}/{self.model}:generateContent?key={self._api_key}"
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        candidate = data.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        content_text = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            content=content_text,
            model=self.model,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            raw=data,
        )

    async def __aenter__(self) -> GeminiProvider:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


class ProviderRegistry:
    """Registry for named LLM provider instances.

    Allows the rest of the application to look up providers by name
    (e.g. ``"claude"``, ``"gpt4o"``, ``"local"``) without hard-coding
    provider classes throughout the codebase.

    Example::

        registry = ProviderRegistry()
        registry.register("claude", AnthropicProvider(api_key="..."))
        registry.register("local", OllamaProvider(model="mistral"))

        provider = registry.get("claude")
        response = await provider.complete([{"role": "user", "content": "Hello"}])
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, name: str, provider: LLMProvider) -> None:
        """Register a provider under the given name.

        Args:
            name: Logical name for this provider (e.g. ``"claude"``).
            provider: An object satisfying the :class:`LLMProvider` protocol.
        """
        self._providers[name] = provider
        logger.debug("Registered LLM provider %r (%s)", name, type(provider).__name__)

    def get(self, name: str) -> LLMProvider:
        """Return the provider registered under *name*.

        Args:
            name: The logical name used when calling :meth:`register`.

        Returns:
            The registered :class:`LLMProvider` instance.

        Raises:
            KeyError: If no provider with *name* is registered.
        """
        if name not in self._providers:
            available = list(self._providers.keys())
            raise KeyError(f"Provider {name!r} not found. Available: {available}")
        return self._providers[name]

    def list_providers(self) -> list[str]:
        """Return the names of all registered providers."""
        return list(self._providers.keys())

    @classmethod
    def from_config(cls, config: Any) -> ProviderRegistry:
        """Build a :class:`ProviderRegistry` from a configuration object or dict.

        Config format example::

            {
                "providers": {
                    "claude": {
                        "type": "anthropic",
                        "api_key": "sk-ant-...",
                        "model": "claude-sonnet-4-20250514"
                    },
                    "gpt4o": {
                        "type": "openai",
                        "api_key": "sk-...",
                        "model": "gpt-4o"
                    },
                    "local": {
                        "type": "ollama",
                        "base_url": "http://localhost:11434",
                        "model": "llama3"
                    },
                    "gemini": {
                        "type": "gemini",
                        "api_key": "AIza...",
                        "model": "gemini-2.0-flash"
                    }
                }
            }

        Args:
            config: A dict-like config object.  Reads ``config["providers"]``
                    (or ``config.providers`` for attribute-style access).

        Returns:
            Populated :class:`ProviderRegistry`.

        Raises:
            ValueError: If an unknown provider ``type`` is specified.
        """
        registry = cls()

        if hasattr(config, "providers"):
            providers_cfg = config.providers
        elif isinstance(config, dict):
            providers_cfg = config.get("providers", {})
        else:
            providers_cfg = {}

        if hasattr(providers_cfg, "items"):
            items = providers_cfg.items()
        else:
            items = []

        for name, cfg in items:

            def _get(key: str, default: str = "") -> str:
                if isinstance(cfg, dict):
                    return cfg.get(key, default)
                return getattr(cfg, key, default)

            provider_type: str = _get("type")

            if provider_type == "anthropic":
                provider: LLMProvider = AnthropicProvider(
                    api_key=_get("api_key"),
                    model=_get("model", "claude-sonnet-4-20250514"),
                )
            elif provider_type == "openai":
                provider = OpenAIProvider(
                    api_key=_get("api_key"),
                    model=_get("model", "gpt-4o"),
                )
            elif provider_type == "ollama":
                provider = OllamaProvider(
                    base_url=_get("base_url", "http://localhost:11434"),
                    model=_get("model", "llama3"),
                )
            elif provider_type == "gemini":
                provider = GeminiProvider(
                    api_key=_get("api_key"),
                    model=_get("model", "gemini-2.0-flash"),
                )
            else:
                raise ValueError(
                    f"Unknown provider type {provider_type!r} for {name!r}. "
                    "Supported: anthropic, openai, ollama, gemini"
                )

            registry.register(name, provider)

        return registry
