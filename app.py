
# Создаю обновлённый app.py с добавленной командой /image для генерации изображений
# Используем Pollinations.ai — бесплатный, без API-ключа, работает с сервера

app_py_with_image = r'''import os
import sys
import json
import requests
import subprocess
import tempfile
import base64
import urllib.parse
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for
from functools import wraps
from werkzeug.utils import secure_filename

# ---------- Загрузка .env ----------
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# ---------- Провайдеры ----------
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

# ---------- Конфиг для генерации кода (всегда Cerebras) ----------
CODE_PROVIDER = "cerebras"
CODE_MODEL_DEFAULT = "qwen3.6-plus-480b"

# ---------- Конфиг для генерации изображений ----------
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations")  # pollinations, huggingface, openai
IMAGE_SIZE_DEFAULT = os.getenv("IMAGE_SIZE", "1024x1024")       # 1024x1024, 512x512, 256x256
IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "generated_images")
os.makedirs(IMAGE_FOLDER, exist_ok=True)

current_provider = "groq"
current_model = "openai/gpt-oss-120b"

system_prompt = "Ты полезный и дружелюбный ассистент на русском языке. Отвечай кратко и по делу."
contents = []  # история сообщений
plugins = {}

# ---------- Админ конфиг ----------
ADMIN_CREDENTIALS = {
    "admin": os.getenv("ADMIN_CODE", "admin123"),
    "user": os.getenv("USER_CODE", "user123")
}
ADMIN_SESSION_KEY = os.getenv("SESSION_SECRET", "ai-assistant-secret-key-2024")

# ---------- Кастомные алиасы ----------
CUSTOM_COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "custom_commands.json")
custom_commands = {}


def load_custom_commands():
    global custom_commands
    if os.path.exists(CUSTOM_COMMANDS_FILE):
        try:
            with open(CUSTOM_COMMANDS_FILE, "r", encoding="utf-8") as f:
                custom_commands = json.load(f)
            print(f"Загружено {len(custom_commands)} пользовательских команд")
        except Exception as e:
            print(f"Ошибка чтения custom_commands.json: {e}")
            custom_commands = {}
    else:
        custom_commands = {}


def save_custom_commands():
    with open(CUSTOM_COMMANDS_FILE, "w", encoding="utf-8") as f:
        json.dump(custom_commands, f, ensure_ascii=False, indent=2)


load_custom_commands()

# ---------- Загрузка плагинов ----------
def load_plugins():
    plugin_dir = os.path.join(os.path.dirname(__file__), "commands")
    if not os.path.isdir(plugin_dir):
        return
    sys.path.insert(0, plugin_dir)
    for fname in os.listdir(plugin_dir):
        if fname.endswith(".py") and not fname.startswith("_"):
            modname = fname[:-3]
            try:
                mod = __import__(modname)
                if hasattr(mod, "run"):
                    plugins[modname] = mod.run
                    print(f"Плагин загружен: {modname}")
            except Exception as e:
                print(f"Ошибка загрузки плагина {modname}: {e}")


load_plugins()

# ---------- Flask app ----------
app = Flask(__name__)
app.secret_key = ADMIN_SESSION_KEY

# ---------- Admin decorators ----------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated


def admin_api_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ---------- DuckDuckGo поиск ----------
def search_web(query):
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1, "t": "termux_assistant"}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        parts = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        for topic in data.get("RelatedTopics", [])[:5]:
            if "Text" in topic:
                parts.append(topic["Text"])
        if not parts:
            return None
        return "Результаты поиска:\n" + "\n".join(f"- {p}" for p in parts)
    except Exception as e:
        print(f"Ошибка поиска: {e}")
        return None


# ---------- System prompt helper ----------
def ensure_system_prompt():
    """Убеждается, что system_prompt присутствует в contents[0]"""
    global contents, system_prompt
    if not contents:
        contents.insert(0, {"role": "system", "content": system_prompt})
        return
    if contents[0].get("role") == "system":
        contents[0]["content"] = system_prompt
    else:
        contents.insert(0, {"role": "system", "content": system_prompt})


def update_system_prompt(new_prompt):
    """Обновляет системный промпт и синхронизирует его в contents"""
    global system_prompt, contents
    system_prompt = new_prompt
    ensure_system_prompt()


# ---------- LLM helper (общий) ----------
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


# ---------- Генерация изображений ----------
def generate_image(prompt, width=1024, height=1024, seed=None):
    """
    Генерирует изображение и возвращает путь к сохранённому файлу.
    Поддерживает: pollinations (бесплатно), huggingface, openai
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prompt = secure_filename(prompt[:50])
    filename = f"img_{timestamp}_{safe_prompt}.png"
    filepath = os.path.join(IMAGE_FOLDER, filename)

    if IMAGE_PROVIDER == "pollinations":
        # Pollinations.ai — бесплатный, без ключа
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
        if seed:
            url += f"&seed={seed}"
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath, filename

    elif IMAGE_PROVIDER == "huggingface":
        # Hugging Face Inference API — нужен HF_API_KEY
        api_key = os.getenv("HF_API_KEY")
        if not api_key:
            raise ValueError("HF_API_KEY не задан в .env")
        # Используем Stable Diffusion через Inference API
        api_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"inputs": prompt}
        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath, filename

    elif IMAGE_PROVIDER == "openai":
        # OpenAI DALL-E — нужен OPENAI_API_KEY
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY не задан в .env")
        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": f"{width}x{height}" if width == height else IMAGE_SIZE_DEFAULT
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        image_url = data["data"][0]["url"]
        # Скачиваем изображение по URL
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(img_resp.content)
        return filepath, filename

    else:
        raise ValueError(f"Неизвестный IMAGE_PROVIDER: {IMAGE_PROVIDER}")


# ---------- Кастомные команды ----------
def exec_custom_command(cmd, args):
    global contents
    if cmd not in custom_commands:
        return None
    cc = custom_commands[cmd]
    if cc["type"] == "plugin":
        plugin_name = cc["plugin"]
        if plugin_name not in plugins:
            return f"Ошибка: плагин {plugin_name} не найден."
        full_args = list(cc.get("args_template", [])) + args
        try:
            result = plugins[plugin_name](full_args)
            return str(result) if result else "OK"
        except Exception as e:
            return f"Ошибка плагина: {e}"
    elif cc["type"] == "llm":
        prompt_template = cc.get("prompt", "{query}")
        query = " ".join(args) if args else ""
        rendered_prompt = prompt_template.replace("{query}", query)
        ensure_system_prompt()
        contents.append({"role": "user", "content": rendered_prompt})
        provider = PROVIDERS[current_provider]
        payload = {
            "model": current_model,
            "messages": contents,
            "temperature": 0.7,
            "max_tokens": 3000,
        }
        try:
            resp = requests.post(provider["url"], json=payload, headers=provider["headers"])
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            contents.append({"role": "assistant", "content": reply})
            if len(contents) > 20:
                contents = contents[-20:]
            return reply
        except Exception as e:
            if contents and contents[-1]["role"] == "user":
                contents.pop()
            return f"Ошибка LLM: {e}"
    else:
        return f"Неизвестный тип алиаса: {cc['type']}"


# ========== ROUTES ==========

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin/login")
def admin_login_page():
    return render_template("admin.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html")


# ---------- Admin API ----------

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    code = data.get("code", "").strip()
    if not username or not code:
        return jsonify({"error": "Введите логин и код"}), 400
    if username not in ADMIN_CREDENTIALS:
        return jsonify({"error": "Неверный логин"}), 401
    if ADMIN_CREDENTIALS[username] != code:
        return jsonify({"error": "Неверный код"}), 401
    session["admin_logged_in"] = True
    session["admin_username"] = username
    session.permanent = True
    return jsonify({"success": True, "username": username, "role": "admin" if username == "admin" else "user"})


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/admin/check")
def admin_check():
    if session.get("admin_logged_in"):
        return jsonify({"logged_in": True, "username": session.get("admin_username"), "role": "admin" if session.get("admin_username") == "admin" else "user"})
    return jsonify({"logged_in": False})


@app.route("/api/admin/stats")
@admin_api_required
def admin_stats():
    return jsonify({
        "models": PROVIDERS,
        "current_provider": current_provider,
        "current_model": current_model,
        "code_provider": CODE_PROVIDER,
        "code_model": CODE_MODEL_DEFAULT,
        "image_provider": IMAGE_PROVIDER,
        "history_messages": len(contents),
        "plugins_loaded": list(plugins.keys()),
        "custom_commands": list(custom_commands.keys()),
        "system_prompt": system_prompt,
        "voice_enabled": os.environ.get("ASSISTANT_VOICE_REPLY", "0") == "1"
    })


@app.route("/api/admin/settings", methods=["POST"])
@admin_api_required
def admin_settings():
    global system_prompt, current_provider, current_model
    data = request.get_json() or {}
    if "system_prompt" in data:
        update_system_prompt(data["system_prompt"])
    if "provider" in data and data["provider"] in PROVIDERS:
        current_provider = data["provider"]
    if "model" in data:
        for prov, pdata in PROVIDERS.items():
            for m in pdata["models"]:
                if m["id"] == data["model"]:
                    current_provider = prov
                    current_model = data["model"]
                    break
    if "voice" in data:
        os.environ["ASSISTANT_VOICE_REPLY"] = "1" if data["voice"] else "0"
    return jsonify({"success": True, "current_provider": current_provider, "current_model": current_model, "system_prompt": system_prompt})


@app.route("/api/admin/history", methods=["GET", "DELETE"])
@admin_api_required
def admin_history():
    global contents
    if request.method == "DELETE":
        contents.clear()
        ensure_system_prompt()
        return jsonify({"success": True, "message": "История очищена"})
    return jsonify({"history": contents})


@app.route("/api/admin/export")
@admin_api_required
def admin_export():
    export_data = {
        "history": contents,
        "settings": {
            "provider": current_provider,
            "model": current_model,
            "code_provider": CODE_PROVIDER,
            "code_model": CODE_MODEL_DEFAULT,
            "image_provider": IMAGE_PROVIDER,
            "system_prompt": system_prompt,
            "voice_enabled": os.environ.get("ASSISTANT_VOICE_REPLY", "0") == "1"
        },
        "custom_commands": custom_commands,
        "plugins": list(plugins.keys())
    }
    return jsonify(export_data)


# ---------- Chat API ----------

@app.route("/models_list")
def models_list():
    providers_list = []
    for provider_key, provider_data in PROVIDERS.items():
        providers_list.append({
            "provider": provider_key,
            "list": provider_data["models"]
        })
    return jsonify({"models": providers_list, "current": current_model})


@app.route("/switch_model")
def switch_model():
    global current_provider, current_model
    model_id = request.args.get("model_id", "")
    for provider_key, provider_data in PROVIDERS.items():
        for model in provider_data["models"]:
            if model["id"] == model_id:
                current_provider = provider_key
                current_model = model_id
                return jsonify({"success": True, "provider": provider_key, "model": model_id})
    return jsonify({"error": "Модель не найдена"}), 400


@app.route("/commands_list")
def commands_list():
    cmds = []
    for name, cc in custom_commands.items():
        cmds.append({"command": f"/{name}", "label": f"{name}"})
    if "monitor" in plugins:
        cmds.append({"command": "/monitor battery", "label": "Батарея"})
        cmds.append({"command": "/monitor memory", "label": "Память"})
    if "services" in plugins:
        cmds.append({"command": "/services weather Москва", "label": "Погода"})
        cmds.append({"command": "/services currency USD RUB", "label": "Валюта"})
        cmds.append({"command": "/services wiki Linux", "label": "Wiki"})
    if "snippet" in plugins:
        cmds.append({"command": "/snippet list", "label": "Сниппеты"})
    if "git" in plugins:
        cmds.append({"command": "/git /sdcard/Documents", "label": "GitHub"})
    if "voice" in plugins:
        cmds.append({"command": "/voice on", "label": "Озвучка вкл"})
        cmds.append({"command": "/voice off", "label": "Озвучка выкл"})
    cmds.append({"command": "/search ", "label": "Поиск в интернете"})
    cmds.extend([
        {"command": "/code ", "label": "Генератор кода (Cerebras)"},
        {"command": "/image ", "label": "Генератор изображений"},
        {"command": "/clear", "label": "Очистить"},
        {"command": "/save", "label": "Сохранить"},
        {"command": "/load", "label": "Загрузить"},
        {"command": "/history", "label": "История"},
        {"command": "/help", "label": "Помощь"},
        {"command": "/alias", "label": "Мои команды"},
    ])
    return jsonify({"commands": cmds})


@app.route("/send", methods=["POST"])
def send():
    global contents
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Пустое сообщение"})

    ensure_system_prompt()
    contents.append({"role": "user", "content": message})
    provider = PROVIDERS[current_provider]
    payload = {
        "model": current_model,
        "messages": contents,
        "temperature": 0.7,
        "max_tokens": 3000,
    }
    try:
        resp = requests.post(provider["url"], json=payload, headers=provider["headers"])
        resp.raise_for_status()
        data_resp = resp.json()
        reply = data_resp["choices"][0]["message"]["content"]
        contents.append({"role": "assistant", "content": reply})
        if len(contents) > 20:
            contents = contents[-20:]
        voice_enabled = os.environ.get("ASSISTANT_VOICE_REPLY", "0") == "1"
        return jsonify({"reply": reply, "voice_enabled": voice_enabled})
    except Exception as e:
        if contents and contents[-1]["role"] == "user":
            contents.pop()
        return jsonify({"error": str(e)})


@app.route("/command", methods=["POST"])
def handle_command():
    global contents, system_prompt
    data = request.get_json()
    cmd_line = data.get("command", "").strip()
    if not cmd_line.startswith("/"):
        return jsonify({"er