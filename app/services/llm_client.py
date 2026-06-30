"""OpenAI-compatible async client wrapper for natural-language tasks."""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.exceptions import KinovaError

logger = logging.getLogger(__name__)


class LLMError(KinovaError):
    """Raised when the LLM provider returns an error or an unparseable response."""

    def __init__(self, message: str):
        super().__init__(message, status_code=503)


class LLMClient:
    """Thin async wrapper around an OpenAI-compatible chat completion API."""

    def __init__(
        self,
        base_url: str = settings.llm_base_url,
        api_key: str | None = settings.llm_api_key,
        model: str = settings.llm_model,
        timeout: float = settings.llm_request_timeout,
        max_tokens: int = settings.llm_max_tokens,
        temperature: float = settings.llm_temperature,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "not-set",
            timeout=timeout,
        )

    async def chat_completion(
        self,
        system_message: str,
        user_message: str,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return the parsed JSON content of the first completion choice."""
        if not self._client.api_key or self._client.api_key == "not-set":
            raise LLMError("LLM_API_KEY is not configured")

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        extra: dict[str, Any] = {}
        if response_format:
            extra["response_format"] = response_format

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                **extra,
            )
        except Exception as exc:
            logger.exception("LLM request failed")
            raise LLMError(f"LLM request failed: {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise LLMError("LLM returned empty content")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("LLM response is not valid JSON: %s", content)
            raise LLMError(f"LLM response is not valid JSON: {exc}") from exc

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
