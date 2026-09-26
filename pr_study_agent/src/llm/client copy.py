"""LLM client — simplified copy from agent_project, only LocalClient needed."""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import os
import logging
import time

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "deepseek-chat")
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 8192)

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass


class LocalClient(LLMClient):
    """OpenAI-compatible API client for DeepSeek / local models."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY", "not-needed")
        self.base_url = config.get("base_url") or "http://localhost:11434/v1"
        self.timeout = config.get("timeout", 300)
        self._sync_client = None
        self._async_client = None

    def _get_sync_client(self):
        if self._sync_client is None:
            from openai import OpenAI
            import httpx
            self._sync_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=httpx.Timeout(float(self.timeout), connect=10.0),
            )
        return self._sync_client

    def _get_async_client(self):
        if self._async_client is None:
            from openai import AsyncOpenAI
            import httpx
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=httpx.Timeout(float(self.timeout), connect=10.0),
            )
        return self._async_client

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Async chat with retry on connection errors."""
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries):
            try:
                client = self._get_async_client()
                response = await client.chat.completions.create(
                    model=kwargs.get("model", self.model),
                    messages=messages,
                    temperature=kwargs.get("temperature", self.temperature),
                    max_tokens=kwargs.get("max_tokens", self.max_tokens),
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)
                    logger.warning(f"LLM call failed ({e}), retrying in {delay}s...")
                    import asyncio
                    await asyncio.sleep(delay)
        raise last_exc

    def chat_sync(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Synchronous chat with retry."""
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries):
            try:
                client = self._get_sync_client()
                response = client.chat.completions.create(
                    model=kwargs.get("model", self.model),
                    messages=messages,
                    temperature=kwargs.get("temperature", self.temperature),
                    max_tokens=kwargs.get("max_tokens", self.max_tokens),
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)
                    logger.warning(f"LLM call failed ({e}), retrying in {delay}s...")
                    time.sleep(delay)
        raise last_exc


def create_llm_client(config: Dict[str, Any]) -> LLMClient:
    """Factory function to create LLM client."""
    return LocalClient(config)
