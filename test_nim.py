import requests

models_to_test = [
    ("z-ai/glm5", "https://integrate.api.nvidia.com/v1"),
    ("nvidia/llama-3.3-nemotron-super-49b-v1.5", "https://integrate.api.nvidia.com/v1"),
    ("qwen/qwen3.5-397b-a17b", "https://integrate.api.nvidia.com/v1"),
]

for model, base_url in models_to_test:
    try:
        res = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": "Bearer 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", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50},
            timeout=60
        )
        print(f"{model}: {res.status_code}")
    except Exception as e:
        print(f"{model}: TIMEOUT/ERROR - {str(e)[:50]}")