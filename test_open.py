import requests

models = [
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free", 
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

for model in models:
    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": "Bearer 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",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://forgetest.dev"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Return only this JSON: {\"test\": true}"}],
                "max_tokens": 50
            },
            timeout=15
        )
        data = res.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"✅ {model}: {res.status_code} — {content[:50]}")
    except Exception as e:
        print(f"❌ {model}: {str(e)[:60]}")