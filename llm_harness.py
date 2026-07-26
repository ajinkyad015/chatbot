import os
import time
from dataclasses import dataclass
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors
load_dotenv()


MODEL = "gemini-3.5-flash"
TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 1


client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
    http_options=types.HttpOptions(
        timeout=TIMEOUT_SECONDS * 1000
    )
)


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
    pass

async def generate(messages: list[dict[str, str]]) -> LLMResult:
    start = time.perf_counter()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response =  await client.aio.models.generate_content(
                model=MODEL,
                contents=[
                    types.Content(
                        role="model" if message["role"] == "assistant" else "user",
                        parts=[
                            types.Part.from_text(
                                text=message["content"]
                            )
                        ],
                    )
                    for message in messages
                ],
                config=types.GenerateContentConfig(
                    system_instruction="You are a concise, helpful assistant."
                )
            )

            latency = time.perf_counter() - start
            usage = response.usage_metadata

            return LLMResult(
                text=response.text,
                model=MODEL,
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
                raise LLMError(
                    "Invalid LLM request."
                ) from e

            # Transient failures: retry may succeed.
            retryable = status == 408 or status == 429 or status >= 500

            if not retryable:
                raise LLMError(
                    f"LLM request failed with status {status}."
                ) from e

            if attempt == MAX_ATTEMPTS:
                raise LLMError(
                    f"LLM request failed after {attempt} attempts: {e}"
                ) from e

            wait_seconds = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))

            print(
                f"[LLM] Attempt {attempt} failed "
                f"(status {status}). Retrying in {wait_seconds}s..."
            )

            await asyncio.sleep(wait_seconds)

        except (TimeoutError, ConnectionError) as e:
            if attempt == MAX_ATTEMPTS:
                raise LLMError(
                    f"LLM connection/timeout failure after {attempt} attempts."
                ) from e

            wait_seconds = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))

            print(
                f"[LLM] Attempt {attempt} failed "
                f"(connection/timeout). Retrying in {wait_seconds}s..."
            )

            time.sleep(wait_seconds)

        except Exception as e:
            raise LLMError(
                f"Unexpected LLM provider error: {e}"
            ) from e