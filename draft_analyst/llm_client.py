from abc import ABC, abstractmethod

import anthropic
import openai

from draft_analyst.config import ANTHROPIC_API_KEY, OPENAI_API_KEY


class LLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> dict:
        ...


class AnthropicClient(LLMClient):
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            max_retries=3,
        )

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> dict:
        kwargs = {"model": model, "max_tokens": 4096, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system
        response = self.client.messages.create(**kwargs)
        return {"content": response.content, "stop_reason": response.stop_reason}


class OpenAIClient(LLMClient):
    """Fallback if anthropic is down or you want to compare."""
    def __init__(self):
        self.client = openai.OpenAI(api_key=OPENAI_API_KEY)

    def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> dict:
        msgs = list(messages)
        if system:
            msgs.insert(0, {"role": "system", "content": system})
        kwargs = {"model": model, "messages": msgs}
        if tools:
            kwargs["tools"] = tools
        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        return {"content": msg.content, "stop_reason": response.choices[0].finish_reason}


def get_llm_client(provider: str = "anthropic") -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient()
    elif provider == "openai":
        return OpenAIClient()
    raise ValueError(f"unknown provider: {provider}")
