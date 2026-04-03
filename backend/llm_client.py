import json
from typing import AsyncGenerator

import httpx


def _normalize_base_url(base_url: str) -> str:
    # Normalize base_url: remove trailing slash, strip /v1 suffix
    base_url = (base_url or "").strip().rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    return base_url


def _extract_openai_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                inner = item.get("content")
                if isinstance(inner, str):
                    parts.append(inner)
        return "".join(parts)
    return ""


def _extract_claude_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


class ClaudeClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self._timeout = httpx.Timeout(connect=30, read=600, write=60, pool=10)
        self._limits = httpx.Limits(max_connections=80, max_keepalive_connections=20, keepalive_expiry=45)
        self._client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout, limits=self._limits)
        return self._client

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async def complete(
        self,
        system: str,
        messages: list,
        max_tokens: int = 8096,
    ) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        client = self._http_client()
        resp = await client.post(
            f"{self.base_url}/v1/messages",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return _extract_claude_text(data.get("content", []))

    async def stream(
        self,
        system: str,
        messages: list,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "stream": True,
        }
        client = self._http_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/v1/messages",
            headers=self._headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text

    async def test_connection(self) -> bool:
        try:
            result = await self.complete(
                system="You are a helpful assistant.",
                messages=[{"role": "user", "content": "Reply with just: ok"}],
                max_tokens=10,
            )
            return bool(result)
        except Exception:
            return False


class OpenAIClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self._timeout = httpx.Timeout(connect=30, read=600, write=60, pool=10)
        self._limits = httpx.Limits(max_connections=80, max_keepalive_connections=20, keepalive_expiry=45)
        self._client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout, limits=self._limits)
        return self._client

    def _headers(self) -> dict:
        return {
            "authorization": f"Bearer {self.api_key}",
            "api-key": self.api_key,   # Azure/OpenAI-compatible gateways
            "x-api-key": self.api_key,  # Some proxy gateways
            "content-type": "application/json",
        }

    @staticmethod
    def _build_messages(system: str, messages: list) -> list:
        result = []
        if system:
            result.append({"role": "system", "content": system})
        result.extend(messages or [])
        return result

    async def complete(
        self,
        system: str,
        messages: list,
        max_tokens: int = 8096,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": self._build_messages(system, messages),
            "max_tokens": max_tokens,
        }
        client = self._http_client()
        resp = await client.post(
            f"{self.base_url}/v1/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return _extract_openai_text(message.get("content"))

    async def stream(
        self,
        system: str,
        messages: list,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        payload = {
            "model": self.model,
            "messages": self._build_messages(system, messages),
            "max_tokens": max_tokens,
            "stream": True,
        }
        client = self._http_client()
        async with client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            headers=self._headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                text = _extract_openai_text(delta.get("content"))
                if text:
                    yield text

    async def test_connection(self) -> bool:
        try:
            result = await self.complete(
                system="You are a helpful assistant.",
                messages=[{"role": "user", "content": "Reply with just: ok"}],
                max_tokens=10,
            )
            return bool(result)
        except Exception:
            return False


def create_client(provider: str, base_url: str, api_key: str, model: str):
    provider = (provider or "claude").strip().lower()
    if provider == "openai":
        return OpenAIClient(base_url=base_url, api_key=api_key, model=model)
    return ClaudeClient(base_url=base_url, api_key=api_key, model=model)


def get_client():
    from .config import load_settings

    cfg = load_settings()
    return create_client(
        provider=cfg.get("provider", "claude"),
        base_url=cfg.get("base_url", ""),
        api_key=cfg.get("api_key", ""),
        model=cfg.get("model", ""),
    )
