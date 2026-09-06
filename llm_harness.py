import asyncio
import os
import time
from dataclasses import dataclass

from google import genai
from google.genai import errors, types

from config import GEMINI_API_KEY, GEMINI_MODEL
from logging_config import logger

LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "10"))
LLM_MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
LLM_BASE_BACKOFF_SECONDS = float(os.getenv("LLM_BASE_BACKOFF_SECONDS", "1.0"))


@dataclass
class LLMResult:
    text: str
    model: str
    latency: float
    input_tokens: int
    output_tokens: int
    attempts: int


class LLMError(Exception):
    """Error exposed by the LLM harness to the application."""


def _create_client():
    if not GEMINI_API_KEY:
        raise LLMError(
            "GEMINI_API_KEY is not configured. "
            "Copy .env.example to .env and set a valid key."
        )

    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            timeout=LLM_TIMEOUT_SECONDS * 1000
        ),
    )


async def generate(messages: list[dict[str, str]]) -> LLMResult:
    start = time.perf_counter()
    client = _create_client()

    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        try:
            response = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Content(
                        role="model"
                        if message["role"] == "assistant"
                        else "user",
                        parts=[
                            types.Part.from_text(
                                text=message["content"]
                            )
                        ],
                    )
                    for message in messages
                ],
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You are a concise, helpful assistant."
                    )
                ),
            )

            latency = time.perf_counter() - start
            usage = response.usage_metadata

            return LLMResult(
                text=response.text,
                model=GEMINI_MODEL,
                latency=latency,
                input_tokens=usage.prompt_token_count or 0,
                output_tokens=usage.candidates_token_count or 0,
                attempts=attempt,
            )

        except errors.APIError as e:
            status = e.code

            # Permanent failures: retrying the same request will not fix them.
            if status in (401, 403):
                raise LLMError(
                    "Authentication/configuration error. Check your API key."
                ) from e

            if status == 400:
                raise LLMError("Invalid LLM request.") from e

            # Transient failures: retry may succeed.
            retryable = status == 408 or status == 429 or status >= 500

            if not retryable:
                raise LLMError(
                    f"LLM request failed with status {status}."
                ) from e

            if attempt == LLM_MAX_ATTEMPTS:
                raise LLMError(
                    f"LLM request failed after {attempt} attempts: {e}"
                ) from e

            wait_seconds = LLM_BASE_BACKOFF_SECONDS * (
                2 ** (attempt - 1)
            )

            logger.warning(
                "LLM attempt failed; retrying",
                extra={
                    "event_data": {
                        "event": "llm_retry",
                        "attempt": attempt,
                        "provider_status": status,
                        "retry_in_seconds": wait_seconds,
                    }
                },
            )

            await asyncio.sleep(wait_seconds)

        except (TimeoutError, ConnectionError) as e:
            if attempt == LLM_MAX_ATTEMPTS:
                raise LLMError(
                    f"LLM connection/timeout failure after {attempt} attempts."
                ) from e

            wait_seconds = LLM_BASE_BACKOFF_SECONDS * (
                2 ** (attempt - 1)
            )

            logger.warning(
                "LLM connection/timeout failure",
                extra={
                    "event_data": {
                        "event": "llm_connection_timeout",
                        "attempt": attempt,
                        "retry_in_seconds": wait_seconds,
                    }
                },
            )

            await asyncio.sleep(wait_seconds)

        except Exception as e:
            raise LLMError(
                f"Unexpected LLM provider error: {e}"
            ) from e
