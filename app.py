from dotenv import load_dotenv

load_dotenv()

from llm_harness import generate, LLMError


while True:
    user_input = input("You: ")

    if user_input.lower() in ("exit", "quit"):
        break

    try:
        result = generate(user_input)

        print()
        print("AI:", result.text)
        print()
        print(f"Model: {result.model}")
        print(f"Latency: {result.latency:.2f}s")
        print(f"Input tokens: {result.input_tokens}")
        print(f"Output tokens: {result.output_tokens}")
        print(f"Attempts: {result.attempts}")
        print()

    except LLMError as e:
        print(f"[LLM error] {e}")