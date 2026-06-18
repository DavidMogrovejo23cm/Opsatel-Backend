import os
import anthropic

api_key = os.getenv("ANTHROPIC_API_KEY", "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")
client = anthropic.Anthropic(api_key=api_key)

models_to_test = [
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
    "claude-3-opus-latest",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307"
]

print(f"Testing API key: {api_key[:15]}...")

for model in models_to_test:
    try:
        print(f"Testing model: {model}...")
        response = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )
        print(f"SUCCESS with {model}: {response.content[0].text.strip()}")
        break
    except Exception as e:
        print(f"FAILED with {model}: {e}")
