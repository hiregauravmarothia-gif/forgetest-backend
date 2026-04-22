import requests

models = [
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash", 
    "gemini/gemini-1.5-flash",
]

for model in models:
    model_name = model.split("/")[1]
    res = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        headers={"Authorization": "Bearer AIzaSyAzHrFXP0pfIuMTazQQtoNU6NL7K5uR1P8", "Content-Type": "application/json"},
        json={"model": model_name, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10},
        timeout=10
    )
    print(f"{model}: {res.status_code}")