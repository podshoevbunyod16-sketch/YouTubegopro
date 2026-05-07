import os
import sys
import json
import requests
import subprocess
import tempfile
import base64
import re
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

# ---------- Конфиг ----------
CODE_PROVIDER = "cerebras"
CODE_MODEL_DEFAULT = "qwen3.6-plus-480b"

IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations")
IMAGE_SIZE_DEFAULT = os.getenv("IMAGE_SIZE", "1024x1024")
IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "generated_images")
os.makedirs(IMAGE_FOLDER, exist_ok=True)

current_provider = "groq"
current_model = "openai/gpt-oss-120b"

system_prompt = "Ты полезный и дружелюбный ассистент на русском языке. Отвечай кратко и по делу."
contents = []
plugins = {}

# ---------- Админ ----------
ADMIN_CREDENTIALS = {
    "admin": os.getenv("ADMIN_CODE", "admin123"),
    "user": os.getenv("USER_CODE", "user123")
}
ADMIN_SESSION_KEY = os.getenv("SESSION_SECRET", "ai-assistant-secret-key-2024")

# ---------- Кастомные команды ----------
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

# ---------- Плагины ----------
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

# ---------- Flask ----------
app = Flask(__name__)
app.secret_key = ADMIN_SESSION_KEY

# ---------- Декораторы ----------
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


# ---------- Поиск ----------
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


# ---------- System prompt ----------
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


# ---------- Определение языка ----------
def detect_language(query):
    q_lower = query.lower()
    q_clean = re.sub(r'[^\w\s]', ' ', q_lower)
    words = set(q_clean.split())

    lang_map = {
        "python": (".py", "Python"), "пайтон": (".py", "Python"), "питон": (".py", "Python"),
        "javascript": (".js", "JavaScript"), "js": (".js", "JavaScript"), "джс": (".js", "JavaScript"),
        "typescript": (".ts", "TypeScript"), "ts": (".ts", "TypeScript"), "тайпскрипт": (".ts", "TypeScript"),
        "html": (".html", "HTML"), "хтмл": (".html", "HTML"),
        "css": (".css", "CSS"), "цсс": (".css", "CSS"),
        "rust": (".rs", "Rust"), "раст": (".rs", "Rust"),
        "golang": (".go", "Go"), "go": (".go", "Go"),
        "c++": (".cpp", "C++"), "cpp": (".cpp", "C++"), "cplusplus": (".cpp", "C++"),
        "c": (".c", "C"), "си": (".c", "C"),
        "c#": (".cs", "C#"), "csharp": (".cs", "C#"), "си шарп": (".cs", "C#"),
        "java": (".java", "Java"), "джава": (".java", "Java"),
        "kotlin": (".kt", "Kotlin"),
        "swift": (".swift", "Swift"),
        "php": (".php", "PHP"),
        "ruby": (".rb", "Ruby"), "руби": (".rb", "Ruby"),
        "bash": (".sh", "Bash"), "shell": (".sh", "Shell"), "шелл": (".sh", "Shell"),
        "sql": (".sql", "SQL"),
        "json": (".json", "JSON"),
        "yaml": (".yaml", "YAML"), "yml": (".yaml", "YAML"),
        "xml": (".xml", "XML"),
        "markdown": (".md", "Markdown"), "md": (".md", "Markdown"),
        "dockerfile": (".dockerfile", "Dockerfile"),
        "lua": (".lua", "Lua"),
        "perl": (".pl", "Perl"),
        "r": (".r", "R"),
        "matlab": (".m", "MATLAB"),
        "scala": (".scala", "Scala"),
        "dart": (".dart", "Dart"),
        "flutter": (".dart", "Flutter"),
        "react": (".jsx", "React"), "jsx": (".jsx", "JSX"), "tsx": (".tsx", "TSX"),
        "vue": (".vue", "Vue"),
        "angular": (".ts", "Angular"),
        "svelte": (".svelte", "Svelte"),
        "solidity": (".sol", "Solidity"), "sol": (".sol", "Solidity"),
        "graphql": (".graphql", "GraphQL"), "gql": (".graphql", "GraphQL"),
        "terraform": (".tf", "Terraform"), "tf": (".tf", "Terraform"),
        "cmake": (".cmake", "CMake"),
        "makefile": (".mk", "Makefile"), "make": (".mk", "Makefile"),
        "gradle": (".gradle", "Gradle"),
        "powershell": (".ps1", "PowerShell"), "ps": (".ps1", "PowerShell"),
        "objective-c": (".m", "Objective-C"), "objc": (".m", "Objective-C"),
        "haskell": (".hs", "Haskell"),
        "erlang": (".erl", "Erlang"),
        "elixir": (".ex", "Elixir"),
        "clojure": (".clj", "Clojure"),
        "lisp": (".lisp", "Lisp"),
        "fortran": (".f90", "Fortran"),
        "cobol": (".cob", "COBOL"),
        "pascal": (".pas", "Pascal"),
        "delphi": (".pas", "Delphi"),
        "ada": (".adb", "Ada"),
        "prolog": (".pl", "Prolog"),
        "smalltalk": (".st", "Smalltalk"),
        "groovy": (".groovy", "Groovy"),
        "julia": (".jl", "Julia"),
        "f#": (".fs", "F#"), "fsharp": (".fs", "F#"),
        "vb": (".vb", "VB.NET"), "vbnet": (".vb", "VB.NET"), "visual basic": (".vb", "VB.NET"),
        "actionscript": (".as", "ActionScript"),
        "coldfusion": (".cfm", "ColdFusion"),
        "tcl": (".tcl", "Tcl"),
        "scheme": (".scm", "Scheme"),
        "ocaml": (".ml", "OCaml"),
        "elm": (".elm", "Elm"),
        "crystal": (".cr", "Crystal"),
        "nim": (".nim", "Nim"),
        "zig": (".zig", "Zig"),
        "vyper": (".vy", "Vyper"),
        "move": (".move", "Move"),
        "cairo": (".cairo", "Cairo"),
        "wasm": (".wat", "WebAssembly"), "webassembly": (".wat", "WebAssembly"),
        "prisma": (".prisma", "Prisma"),
        "ansible": (".yml", "Ansible"),
        "puppet": (".pp", "Puppet"),
        "nix": (".nix", "Nix"),
        "awk": (".awk", "AWK"),
        "sed": (".sed", "Sed"),
        "m4": (".m4", "M4"),
        "meson": (".meson", "Meson"),
        "bazel": (".bzl", "Bazel"),
        "sbt": (".sbt", "SBT"),
        "leiningen": (".clj", "Leiningen"),
        "deps": (".edn", "Deps"),
    }

    for word in words:
        if word in lang_map:
            return lang_map[word]

    for phrase, (ext, name) in lang_map.items():
        if " " in phrase and phrase in q_lower:
            return (ext, name)

    match = re.search(r'на\s+(?:языке\s+)?(\w+)', q_lower)
    if match:
        w = match.group(1)
        if w in lang_map:
            return lang_map[w]

    return (".py", "Python")


# ---------- LLM helper ----------
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
        try:
            resp = requests.post(
                PROVIDERS[current_provider]["url"],
                json={"model": current_model, "messages": contents, "temperature": 0.7, "max_tokens": 3000},
                headers=PROVIDERS[current_provider]["headers"]
            )
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


# ---------- Генерация изображений ----------
def generate_image(prompt, width=1024, height=1024, seed=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_prompt = secure_filename(prompt[:50])
    filename = f"img_{timestamp}_{safe_prompt}.png"
    filepath = os.path.join(IMAGE_FOLDER, filename)

    if IMAGE_PROVIDER == "pollinations":
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"
        if seed:
            url += f"&seed={seed}"
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)

    elif IMAGE_PROVIDER == "huggingface":
        api_key = os.getenv("HF_API_KEY")
        if not api_key:
            raise ValueError("HF_API_KEY не задан в .env")
        api_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"inputs": prompt}
        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)

    elif IMAGE_PROVIDER == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY не задан в .env")
        url = "https://api.openai.com/v1/images/generations"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "dall-e-3", "prompt": prompt, "n": 1, "size": IMAGE_SIZE_DEFAULT}
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        image_url = data["data"][0]["url"]
        img_resp = requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(img_resp.content)
    else:
        raise ValueError(f"Неизвестный IMAGE_PROVIDER: {IMAGE_PROVIDER}")

    with open(filepath, "rb") as img_file:
        img_base64 = base64.b64encode(img_file.read()).decode("utf-8")

    return {
        "filepath": filepath,
        "filename": filename,
        "image_base64": img_base64,
        "image_url": f"/image_view?file={filename}",
        "download_url": f"/download_image?file={filename}",
        "width": width,
        "height": height
    }


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
    return jsonify({
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
    })


# ---------- Chat API ----------

@app.route("/models_list")
def models_list():
    providers_list = []
    for provider_key, provider_data in PROVIDERS.items():
  