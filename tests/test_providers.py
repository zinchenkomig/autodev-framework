"""Tests for autodev.core.providers — Multi-provider LLM abstraction (Issue #15)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autodev.core.providers import (
    AnthropicProvider,
    GeminiProvider,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    OllamaProvider,
    OpenAIProvider,
    ProviderRegistry,
)

# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------


def test_llm_response_total_tokens() -> None:
    resp = LLMResponse(content="hello", model="gpt-4o", input_tokens=100, output_tokens=50)
    assert resp.total_tokens == 150


def test_llm_response_defaults() -> None:
    resp = LLMResponse(content="test", model="claude")
    assert resp.input_tokens == 0
    assert resp.output_tokens == 0
    assert resp.tool_calls == []
    assert resp.raw == {}


def test_llm_message_fields() -> None:
    msg = LLMMessage(role="user", content="Hello, world!")
    assert msg.role == "user"
    assert msg.content == "Hello, world!"


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_provider_protocol_runtime_check() -> None:
    """All provider classes should satisfy the LLMProvider Protocol at runtime."""
    for cls in (AnthropicProvider, OpenAIProvider, OllamaProvider, GeminiProvider):
        instance = MagicMock(spec=cls)
        assert isinstance(instance, LLMProvider)


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_complete_success() -> None:
    """AnthropicProvider.complete should parse Anthropic Messages API response."""
    fake_response = {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-20250514",
        "content": [{"type": "text", "text": "Hello from Claude!"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = AnthropicProvider(api_key="test-key")
        result = await provider.complete([{"role": "user", "content": "Hi"}])

    assert result.content == "Hello from Claude!"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.model == "claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_anthropic_complete_with_system_message() -> None:
    """System messages should be extracted from the messages list."""
    fake_response = {
        "model": "claude-sonnet-4-20250514",
        "content": [{"type": "text", "text": "OK"}],
        "usage": {"input_tokens": 20, "output_tokens": 3},
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        provider = AnthropicProvider(api_key="test-key")
        await provider.complete(
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ]
        )

    payload = mock_post.call_args[1]["json"]
    assert "system" in payload
    assert payload["system"] == "You are helpful."
    # system message should not appear in messages list
    for msg in payload["messages"]:
        assert msg["role"] != "system"


@pytest.mark.asyncio
async def test_anthropic_complete_tool_calls() -> None:
    """Tool use blocks should be extracted into tool_calls."""
    fake_response = {
        "model": "claude-sonnet-4-20250514",
        "content": [
            {"type": "tool_use", "id": "tc_1", "name": "search", "input": {"q": "python"}},
        ],
        "usage": {"input_tokens": 15, "output_tokens": 10},
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = AnthropicProvider(api_key="test-key")
        result = await provider.complete([{"role": "user", "content": "Search Python"}])

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "search"


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_complete_success() -> None:
    fake_response = {
        "id": "chatcmpl-123",
        "model": "gpt-4o",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hello from GPT!", "tool_calls": None},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4},
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = OpenAIProvider(api_key="sk-test")
        result = await provider.complete([{"role": "user", "content": "Hi"}])

    assert result.content == "Hello from GPT!"
    assert result.input_tokens == 8
    assert result.output_tokens == 4


@pytest.mark.asyncio
async def test_openai_complete_with_tool_calls() -> None:
    fake_response = {
        "model": "gpt-4o",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"London"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 15},
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = OpenAIProvider(api_key="sk-test")
        result = await provider.complete([{"role": "user", "content": "Weather?"}])

    assert result.content == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["function"]["name"] == "get_weather"


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_complete_success() -> None:
    fake_response = {
        "model": "llama3",
        "message": {"role": "assistant", "content": "Hi from Ollama!"},
        "prompt_eval_count": 12,
        "eval_count": 7,
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = OllamaProvider()
        result = await provider.complete([{"role": "user", "content": "Hello"}])

    assert result.content == "Hi from Ollama!"
    assert result.model == "llama3"
    assert result.input_tokens == 12
    assert result.output_tokens == 7


@pytest.mark.asyncio
async def test_ollama_custom_model_and_url() -> None:
    provider = OllamaProvider(base_url="http://my-server:11434", model="mistral")
    assert provider.model == "mistral"
    assert "my-server" in provider._chat_url


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_complete_success() -> None:
    fake_response = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Hello from Gemini!"}],
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6},
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        provider = GeminiProvider(api_key="AIza-test")
        result = await provider.complete([{"role": "user", "content": "Hello"}])

    assert result.content == "Hello from Gemini!"
    assert result.input_tokens == 5
    assert result.output_tokens == 6


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


def test_registry_register_and_get() -> None:
    registry = ProviderRegistry()
    mock_provider = MagicMock(spec=AnthropicProvider)
    registry.register("claude", mock_provider)
    assert registry.get("claude") is mock_provider


def test_registry_get_missing_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(KeyError, match="not found"):
        registry.get("nonexistent")


def test_registry_list_providers() -> None:
    registry = ProviderRegistry()
    registry.register("a", MagicMock())
    registry.register("b", MagicMock())
    assert set(registry.list_providers()) == {"a", "b"}


def test_registry_from_config_anthropic() -> None:
    config = {
        "providers": {
            "claude": {
                "type": "anthropic",
                "api_key": "sk-ant-test",
                "model": "claude-sonnet-4-20250514",
            },
        }
    }
    registry = ProviderRegistry.from_config(config)
    provider = registry.get("claude")
    assert isinstance(provider, AnthropicProvider)


def test_registry_from_config_openai() -> None:
    config = {
        "providers": {
            "gpt": {"type": "openai", "api_key": "sk-openai-test"},
        }
    }
    registry = ProviderRegistry.from_config(config)
    assert isinstance(registry.get("gpt"), OpenAIProvider)


def test_registry_from_config_ollama() -> None:
    config = {
        "providers": {
            "local": {"type": "ollama", "base_url": "http://localhost:11434", "model": "llama3"},
        }
    }
    registry = ProviderRegistry.from_config(config)
    assert isinstance(registry.get("local"), OllamaProvider)


def test_registry_from_config_gemini() -> None:
    config = {
        "providers": {
            "gemini": {"type": "gemini", "api_key": "AIza-test"},
        }
    }
    registry = ProviderRegistry.from_config(config)
    assert isinstance(registry.get("gemini"), GeminiProvider)


def test_registry_from_config_unknown_type_raises() -> None:
    config = {
        "providers": {
            "weird": {"type": "unknown_provider", "api_key": "xxx"},
        }
    }
    with pytest.raises(ValueError, match="Unknown provider type"):
        ProviderRegistry.from_config(config)


def test_registry_from_config_empty() -> None:
    registry = ProviderRegistry.from_config({})
    assert registry.list_providers() == []


def test_registry_overwrite_registration() -> None:
    registry = ProviderRegistry()
    p1 = MagicMock()
    p2 = MagicMock()
    registry.register("model", p1)
    registry.register("model", p2)
    assert registry.get("model") is p2
