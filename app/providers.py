import os

PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "headers": {
            "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
            "Content-Type": "application/json"
        },
        "models": [
            {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B"},
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B"},
            {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout"},
            {"id": "qwen/qwen3-32b", "name": "Qwen 3 32B"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B"},
            {"id": "groq/compound", "name": "Compound (автопоиск)"},
            {"id": "groq/compound-mini", "name": "Compound Mini (быстрый)"}
        ]
    },
    "cerebras": {
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "headers": {
            "Authorization": f"Bearer {os.getenv('CEREBRAS_API_KEY')}",
            "Content-Type": "application/json"
        },
        "models": [
            {"id": "qwen3.6-plus-480b", "name": "Qwen3.6-Plus-480B (SWE-bench 71.2%)"},
            {"id": "llama-3.1-70b", "name": "Llama 3.1 70B"},
            {"id": "llama-3.3-70b", "name": "Llama 3.3 70B"},
            {"id": "llama-3.1-8b", "name": "Llama 3.1 8B"},
            {"id": "qwen3-32b", "name": "Qwen 3 32B"},
        ]
    }
}

CODE_PROVIDER = "cerebras"
CODE_MODEL_DEFAULT = "qwen3.6-plus-480b"

# Текущие настройки (глобальные)
current_provider = "groq"
current_model = "openai/gpt-oss-120b"