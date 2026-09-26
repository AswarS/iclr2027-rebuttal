"""LLM client — uses requests to call DeepSeek-compatible API."""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import os
import logging
import time
import asyncio

import requests

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "inner-deepseek_v4")
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 8192)

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass


class LocalClient(LLMClient):
    """HTTP client for DeepSeek / local models via /v1/chat/completions."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY", "not-needed")
        self.base_url = config.get("base_url", "http://116.198.70.68:8081").rstrip("/")
        self.timeout = config.get("timeout", 300)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

    def _call_api(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Send request to /v1/chat/completions and return content."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }
        r = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"] or ""

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Async chat with retry on errors."""
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(self._call_api, messages, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    delay = 2 ** (attempt + 1)
                    logger.warning(f"LLM call failed ({e}), retrying in {delay}s...")
                    await asyncio.sleep(delay)
        raise last_exc

    def chat_sync(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Synchronous chat with retry."""
        max_retries = 3
        last_exc = None
        for attempt in range(max_retries):
            try:
                return self._call_api(messages, **kwargs)
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
