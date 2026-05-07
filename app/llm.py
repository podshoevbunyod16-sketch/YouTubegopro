import requests
from app.providers import PROVIDERS, current_provider, current_model
from app.config import ADMIN_SESSION_KEY  # не используется, но для совместимости

system_prompt = "Ты полезный и дружелюбный ассистент на русском языке. Отвечай кратко и по делу."
contents = []   # история сообщений

def ensure_system_prompt():
    global contents, system_prompt
    if not contents:
        contents.insert(0, {"role": "system", "content": system_prompt})
        return
    if contents[0].get("role") == "system":
        contents[0]["content"] = system_prompt
    else:
        contents.insert(0, {"role": "system", "content": system_prompt})

def update_system_prompt(new_prompt):
    global system_prompt, contents
    system_prompt = new_prompt
    ensure_system_prompt()

def ask_llm(prompt, sys_prompt=None, temperature=0.7, max_tokens=3000, provider_key=None, model_id=None):
    pk = provider_key or current_provider
    mid = model_id or current_model
    if pk not in PROVIDERS:
        return f"Ошибка: провайдер {pk} не найден"
    provider = PROVIDERS[pk]
    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": mid,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        resp = requests.post(provider["url"], json=payload, headers=provider["headers"], timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Ошибка LLM: {e}"