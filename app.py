
# Создаю исправленный монолитный app.py с точным определением языка программирования
# Заменяем блок определения расширения на функцию detect_language

app_py_fixed = r'''import os
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

# ---------- Конфиг для генерации кода (всегда Cerebras) ----------
CODE_PROVIDER = "cerebras"
CODE_MODEL_DEFAULT = "qwen3.6-plus-480b"

# ---------- Конфиг для генерации изображений ----------
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations")
IMAGE_SIZE_DEFAULT = os.getenv("IMAGE_SIZE", "1024x1024")
IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "generated_images")
os.makedirs(IMAGE_FOLDER, exist_ok=True)

current_provider = "groq"
current_model = "openai/gpt-oss-120b"

system_prompt = "Ты полезный и дружелюбный ассистент на русском языке. Отвечай кратко и по делу."
contents = []
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


# ---------- ОПРЕДЕЛЕНИЕ ЯЗЫКА ПРОГРАММИРОВАНИЯ ----------
def detect_language(query):
    """
    Определяет язык программирования из запроса.
    Возвращает (extension, language_name)
    """
    q_lower = query.lower()
    # Убираем знаки препинания, оставляем слова
    q_clean = re.sub(r'[^\w\s]', ' ', q_lower)
    words = set(q_clean.split())

    # Словарь: слово/фраза -> (расширение, название)
    lang_map = {
        # Python
        "python": (".py", "Python"),
        "пайтон": (".py", "Python"),
        "питон": (".py", "Python"),
        # JavaScript
        "javascript": (".js", "JavaScript"),
        "js": (".js", "JavaScript"),
        "джс": (".js", "JavaScript"),
        "node": (".js", "JavaScript"),
        "nodejs": (".js", "JavaScript"),
        # TypeScript
        "typescript": (".ts", "TypeScript"),
        "ts": (".ts", "TypeScript"),
        "тайпскрипт": (".ts", "TypeScript"),
        "тс": (".ts", "TypeScript"),
        # HTML
        "html": (".html", "HTML"),
        "хтмл": (".html", "HTML"),
        # CSS
        "css": (".css", "CSS"),
        "цсс": (".css", "CSS"),
        "scss": (".scss", "SCSS"),
        "sass": (".sass", "Sass"),
        "less": (".less", "Less"),
        # Rust
        "rust": (".rs", "Rust"),
        "раст": (".rs", "Rust"),
        # Go
        "golang": (".go", "Go"),
        "го": (".go", "Go"),
        # C / C++
        "c++": (".cpp", "C++"),
        "cpp": (".cpp", "C++"),
        "cplusplus": (".cpp", "C++"),
        "си++": (".cpp", "C++"),
        "c": (".c", "C"),
        "си": (".c", "C"),
        # C#
        "c#": (".cs", "C#"),
        "csharp": (".cs", "C#"),
        "си шарп": (".cs", "C#"),
        # Java
        "java": (".java", "Java"),
        "джава": (".java", "Java"),
        # Kotlin
        "kotlin": (".kt", "Kotlin"),
        # Swift
        "swift": (".swift", "Swift"),
        # PHP
        "php": (".php", "PHP"),
        # Ruby
        "ruby": (".rb", "Ruby"),
        "руби": (".rb", "Ruby"),
        # Bash / Shell
        "bash": (".sh", "Bash"),
        "shell": (".sh", "Shell"),
        "шелл": (".sh", "Shell"),
        "bashscript": (".sh", "Bash"),
        # PowerShell
        "powershell": (".ps1", "PowerShell"),
        "ps": (".ps1", "PowerShell"),
        # SQL
        "sql": (".sql", "SQL"),
        # JSON
        "json": (".json", "JSON"),
        # YAML
        "yaml": (".yaml", "YAML"),
        "yml": (".yaml", "YAML"),
        # XML
        "xml": (".xml", "XML"),
        # Markdown
        "markdown": (".md", "Markdown"),
        "md": (".md", "Markdown"),
        # Dockerfile
        "dockerfile": (".dockerfile", "Dockerfile"),
        "docker": (".dockerfile", "Dockerfile"),
        # Lua
        "lua": (".lua", "Lua"),
        # Perl
        "perl": (".pl", "Perl"),
        # R
        "r": (".r", "R"),
        # MATLAB
        "matlab": (".m", "MATLAB"),
        # Scala
        "scala": (".scala", "Scala"),
        # Dart
        "dart": (".dart", "Dart"),
        # Flutter
        "flutter": (".dart", "Flutter/Dart"),
        # React
        "react": (".jsx", "React JSX"),
        "jsx": (".jsx", "JSX"),
        "tsx": (".tsx", "TSX"),
        # Vue
        "vue": (".vue", "Vue"),
        # Angular
        "angular": (".ts", "Angular/TypeScript"),
        # Svelte
        "svelte": (".svelte", "Svelte"),
        # Assembly
        "assembly": (".asm", "Assembly"),
        "asm": (".asm", "Assembly"),
        # Haskell
        "haskell": (".hs", "Haskell"),
        # Erlang
        "erlang": (".erl", "Erlang"),
        # Elixir
        "elixir": (".ex", "Elixir"),
        # Clojure
        "clojure": (".clj", "Clojure"),
        # Lisp
        "lisp": (".lisp", "Lisp"),
        # Fortran
        "fortran": (".f90", "Fortran"),
        # COBOL
        "cobol": (".cob", "COBOL"),
        # Pascal
        "pascal": (".pas", "Pascal"),
        # Delphi
        "delphi": (".pas", "Delphi"),
        # Ada
        "ada": (".adb", "Ada"),
        # Prolog
        "prolog": (".pl", "Prolog"),
        # Smalltalk
        "smalltalk": (".st", "Smalltalk"),
        # Objective-C
        "objective-c": (".m", "Objective-C"),
        "objc": (".m", "Objective-C"),
        # Groovy
        "groovy": (".groovy", "Groovy"),
        # Julia
        "julia": (".jl", "Julia"),
        # F#
        "f#": (".fs", "F#"),
        "fsharp": (".fs", "F#"),
        # VB.NET
        "vb": (".vb", "VB.NET"),
        "vbnet": (".vb", "VB.NET"),
        "visual basic": (".vb", "VB.NET"),
        # ActionScript
        "actionscript": (".as", "ActionScript"),
        # ColdFusion
        "coldfusion": (".cfm", "ColdFusion"),
        # Tcl
        "tcl": (".tcl", "Tcl"),
        # Scheme
        "scheme": (".scm", "Scheme"),
        # OCaml
        "ocaml": (".ml", "OCaml"),
        # ReasonML
        "reason": (".re", "ReasonML"),
        # PureScript
        "purescript": (".purs", "PureScript"),
        # Elm
        "elm": (".elm", "Elm"),
        # Crystal
        "crystal": (".cr", "Crystal"),
        # Nim
        "nim": (".nim", "Nim"),
        # V
        "vlang": (".v", "V"),
        "v language": (".v", "V"),
        # Zig
        "zig": (".zig", "Zig"),
        # Carbon
        "carbon": (".carbon", "Carbon"),
        # Solidity
        "solidity": (".sol", "Solidity"),
        "sol": (".sol", "Solidity"),
        # Vyper
        "vyper": (".vy", "Vyper"),
        # Move
        "move": (".move", "Move"),
        # Cairo
        "cairo": (".cairo", "Cairo"),
        # Ink
        "ink": (".ink", "Ink"),
        # WASM
        "wasm": (".wat", "WebAssembly"),
        "webassembly": (".wat", "WebAssembly"),
        # GraphQL
        "graphql": (".graphql", "GraphQL"),
        "gql": (".graphql", "GraphQL"),
        # Prisma
        "prisma": (".prisma", "Prisma"),
        # Terraform
        "terraform": (".tf", "Terraform"),
        "tf": (".tf", "Terraform"),
        # Ansible
        "ansible": (".yml", "Ansible/YAML"),
        # Puppet
        "puppet": (".pp", "Puppet"),
        # Chef
        "chef": (".rb", "Chef/Ruby"),
        # SaltStack
        "saltstack": (".sls", "SaltStack"),
        # Nix
        "nix": (".nix", "Nix"),
        # Guix
        "guix": (".scm", "Guix/Scheme"),
        # Homebrew
        "homebrew": (".rb", "Homebrew/Ruby"),
        # Augeas
        "augeas": (".aug", "Augeas"),
        # AWK
        "awk": (".awk", "AWK"),
        # Sed
        "sed": (".sed", "Sed"),
        # M4
        "m4": (".m4", "M4"),
        # Make
        "makefile": (".mk", "Makefile"),
        "make": (".mk", "Makefile"),
        # CMake
        "cmake": (".cmake", "CMake"),
        # Meson
        "meson": (".meson", "Meson"),
        # Bazel
        "bazel": (".bzl", "Bazel"),
        # Gradle
        "gradle": (".gradle", "Gradle"),
        # SBT
        "sbt": (".sbt", "SBT"),
        # Leiningen
        "leiningen": (".clj", "Leiningen/Clojure"),
        # Boot
        "boot": (".clj", "Boot/Clojure"),
        # Deps
        "deps": (".edn", "Deps/EDN"),
        "tools.deps": (".edn", "Tools.deps/EDN"),
    }

    # 1. Проверяем точное совпадение слов
    for word in words:
        if word in lang_map:
            return lang_map[word]

    # 2. Проверяем фразы с пробелами
    for phrase, (ext, name) in lang_map.items():
        if " " in phrase and phrase in q_lower:
            return (ext, name)

    # 3. Проверяем "на языке X" или "в X"
    lang_patterns = [
        r'на\s+(?:языке\s+)?(\w+)',
        r'в\s+(\w+)',
        r'using\s+(\w+)',
        r'in\s+(\w+)',
    ]
    for pattern in lang_patterns:
        match = re.search(pattern, q_lower)
        if match:
            lang_word = match.group(1)
            if lang_word in lang_map:
                return lang_map[lang_word]

    # По умолчанию Python
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
        return jsonify({"error": "Команда должна начинаться с /"})

    parts = cmd_line[1:].split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].split() if len(parts) > 1 else []

    # Кастомные команды (алиасы)
    custom_result = exec_custom_command(cmd, args)
    if custom_result is not None:
        return jsonify({"result": custom_result})

    # Управление алиасами
    if cmd == "alias":
        if not args:
            if not custom_commands:
                return jsonify({"result": "Нет пользовательских команд. Добавьте через /alias add <имя> plugin <плагин> [аргументы] или /alias add <имя> llm <промпт>."})
            info = "Ваши команды:\n"
            for name, cc in custom_commands.items():
                if cc["type"] == "plugin":
                    info += f"/{name} -> плагин {cc['plugin']} {cc.get('args_template', [])}\n"
                else:
                    info += f"/{name} -> свой промпт\n"
            return jsonify({"result": info})
        subcmd = args[0].lower()
        if subcmd == "add":
            if len(args) < 3:
                return jsonify({"error": "Формат: /alias add <имя> plugin <имя_плагина> [аргументы] или /alias add <имя> llm <промпт>"})
            name = args[1]
            type_ = args[2].lower()
            if type_ not in ("plugin", "llm"):
                return jsonify({"error": "Тип должен быть plugin или llm"})
            if type_ == "plugin":
                if len(args) < 4:
                    return jsonify({"error": "Укажите имя плагина после plugin"})
                plugin_name = args[3]
                preset_args = args[4:] if len(args) > 4 else []
                custom_commands[name] = {"type": "plugin", "plugin": plugin_name, "args_template": preset_args}
            else:
                prompt = " ".join(args[3:]) if len(args) > 3 else "{query}"
                custom_commands[name] = {"type": "llm", "prompt": prompt}
            save_custom_commands()
            return jsonify({"result": f"Команда /{name} добавлена. Перезагрузите страницу для обновления меню."})
        elif subcmd == "remove":
            if len(args) < 2:
                return jsonify({"error": "Укажите имя команды для удаления"})
            name = args[1]
            if name in custom_commands:
                del custom_commands[name]
                save_custom_commands()
                return jsonify({"result": f"Команда /{name} удалена."})
            else:
                return jsonify({"error": f"Команда /{name} не найдена."})
        else:
            return jsonify({"error": "Используйте: /alias [add|remove] <имя> ..."})

    # Плагины
    if cmd in plugins:
        try:
            result = plugins[cmd](args)
            return jsonify({"result": result if result else "OK"})
        except Exception as e:
            return jsonify({"error": str(e)})

    # Встроенные команды
    if cmd == "help":
        return jsonify({"result": "Используйте меню Функции или пишите запросы. /alias для своих команд. /code для генерации кода через Cerebras. /image для генерации изображений."})
    elif cmd == "clear":
        contents.clear()
        ensure_system_prompt()
        return jsonify({"result": "История очищена."})
    elif cmd == "history":
        if not contents:
            return jsonify({"result": "История пуста."})
        hist = "\n\n".join([f"**{msg['role']}**: {msg['content']}" for msg in contents])
        return jsonify({"result": hist})
    elif cmd == "save":
        filename = args[0] if args else "chat_history.json"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(contents, f, ensure_ascii=False, indent=2)
            return jsonify({"result": f"Сохранено в {filename}"})
        except Exception as e:
            return jsonify({"error": str(e)})
    elif cmd == "load":
        filename = args[0] if args else "chat_history.json"
        if not os.path.exists(filename):
            return jsonify({"error": "Файл не найден"})
        try:
            with open(filename, "r", encoding="utf-8") as f:
                contents = json.load(f)
            ensure_system_prompt()
            return jsonify({"result": f"Загружено из {filename}"})
        except Exception as e:
            return jsonify({"error": str(e)})
    elif cmd == "prompt":
        if args:
            update_system_prompt(" ".join(args))
            return jsonify({"result": "Промпт обновлён."})
        else:
            return jsonify({"result": f"Текущий: {system_prompt}"})
    elif cmd == "system":
        command = " ".join(args)
        if not command:
            return jsonify({"error": "Укажите команду"})
        try:
            res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            return jsonify({"result": res.stdout + res.stderr})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Превышено время"})
        except Exception as e:
            return jsonify({"error": str(e)})
    elif cmd == "voice":
        if not args:
            return jsonify({"error": "Используйте /voice on/off"})
        subcmd = args[0].lower()
        if subcmd == "on":
            os.environ["ASSISTANT_VOICE_REPLY"] = "1"
            return jsonify({"result": "Озвучка включена"})
        elif subcmd == "off":
            os.environ["ASSISTANT_VOICE_REPLY"] = "0"
            return jsonify({"result": "Озвучка отключена"})
        else:
            return jsonify({"error": "Неизвестная подкоманда"})
    elif cmd == "search":
        search_query = " ".join(args)
        if not search_query:
            return jsonify({"error": "Укажите запрос"})
        search_context = search_web(search_query)
        ensure_system_prompt()
        if search_context:
            contents.append({"role": "system", "content": f"Контекст из интернета:\n{search_context}"})
            contents.append({"role": "user", "content": f"Ответь на вопрос, используя контекст: {search_query}"})
        else:
            contents.append({"role": "user", "content": search_query})
        provider = PROVIDERS[current_provider]
        payload = {"model": current_model, "messages": contents, "temperature": 0.7, "max_tokens": 3000}
        try:
            resp = requests.post(provider["url"], json=payload, headers=provider["headers"])
            resp.raise_for_status()
            data_resp = resp.json()
            reply = data_resp["choices"][0]["message"]["content"]
            contents.append({"role": "assistant", "content": reply})
            if len(contents) > 20:
                contents = contents[-20:]
            return jsonify({"result": reply, "voice_enabled": os.environ.get("ASSISTANT_VOICE_REPLY", "0") == "1"})
        except Exception as e:
            if contents and contents[-1]["role"] == "user":
                contents.pop()
            if contents and contents[-1]["role"] == "system":
                contents.pop()
            return jsonify({"error": str(e)})

    elif cmd == "code":
        query = " ".join(args)
        if not query:
            return jsonify({"error": "Укажите, какой код нужно создать. Например: /code функция сортировки на Python"})

        ensure_system_prompt()
        contents.append({"role": "user", "content": f"/code {query}"})

        code_sys_prompt = (
            "Ты опытный программист. Пиши только чистый код без лишних пояснений. "
            "Добавь комментарии на русском. Если просят конкретный язык — используй его. "
            "Выводи код в блоке ```язык ... ```"
        )

        generated = ask_llm(
            f"Напиши код: {query}",
            sys_prompt=code_sys_prompt,
            temperature=0.3,
            max_tokens=3000,
            provider_key=CODE_PROVIDER,
            model_id=CODE_MODEL_DEFAULT
        )

        # Извлекаем код из markdown блока
        code = generated
        if "```" in generated:
            parts = generated.split("```")
            for i, p in enumerate(parts):
                if i > 0 and p.strip():
                    lines = p.strip().split("\n")
                    if lines and (lines[0].isalpha() or (" " in lines[0] and len(lines[0]) < 20)):
                        lines = lines[1:]
                    code = "\n".join(lines).strip()
                    break

        # ===== ИСПРАВЛЕННОЕ ОПРЕДЕЛЕНИЕ РАСШИРЕНИЯ =====
        ext, lang_name = detect_language(query)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"generated_{timestamp}{ext}"
        filepath = os.path.join(os.path.dirname(__file__), "generated_codes")
        os.makedirs(filepath, exist_ok=True)
        filepath = os.path.join(filepath, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)

        contents.append({"role": "assistant", "content": generated})
        if len(contents) > 20:
            contents = contents[-20:]

        return jsonify({
            "result": generated,
            "code": code,
            "filename": filename,
            "filepath": filepath,
            "download_url": f"/download?file={filename}",
            "model_used": f"{CODE_PROVIDER}/{CODE_MODEL_DEFAULT}",
            "language": lang_name,
            "extension": ext
        })

    elif cmd == "image":
        query = " ".join(args)
        if not query:
            return jsonify({"error": "Укажите описание изображения. Например: /image кот в космосе"})

        ensure_system_prompt()
        contents.append({"role": "user", "content": f"/image {query}"})

        try:
            # Парсим размер если указан
            width, height = 1024, 1024
            prompt = query
            for word in args:
                if "x" in word and word.replace("x", "").replace("X", "").isdigit():
                    try:
                        w, h = word.lower().split("x")
                        width, height = int(w), int(h)
                        prompt = query.replace(word, "").strip()
                    except:
                        pass
                    break

            result = generate_image(prompt, width=width, height=height)

            contents.append({"role": "assistant", "content": f"[Изображение: {prompt}]"})
            if len(contents) > 20:
                contents = contents[-20:]

            return jsonify({
                "result": f"🎨 Изображение сгенерировано: {prompt}",
                "type": "image",
                "filename": result["filename"],
                "prompt": prompt,
                "image_base64": result["image_base64"],
                "image_url": result["image_url"],
                "download_url": result["download_url"],
                "width": result["width"],
                "height": result["height"]
            })
        except Exception as e:
            return jsonify({"error": f"Ошибка генерации изображения: {e}"})

    else:
        return jsonify({"error": f"Неизвестная команда: /{cmd}"})


# ---------- Download endpoints ----------

@app.route("/download")
def download_file():
    filename = request.args.get("file", "")
    if not filename:
        return jsonify({"error": "No filename"}), 400

    safe_name = secure_filename(filename)
    tmp_dir = os.path.join(os.path.dirname(__file__), "generated_codes")
    filepath = os.path.join(tmp_dir, safe_name)

    if not os.path.abspath(filepath).startswith(os.path.abspath(tmp_dir)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(filepath, as_attachment=True, download_name=safe_name)


@app.route("/download_image")
def download_image():
    filename = request.args.get("file", "")
    if not filename:
        return jsonify({"error": "No filename"}), 400

    safe_name = secure_filename(filename)
    filepath = os.path.join(IMAGE_FOLDER, safe_name)

    if not os.path.abspath(filepath).startswith(os.path.abspath(IMAGE_FOLDER)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(filepath, as_attachment=True, download_name=safe_name)


@app.route("/image_view")
def image_view():
    filename = request.args.get("file", "")
    if not filename:
        return jsonify({"error": "No filename"}), 400

    safe_name = secure_filename(filename)
    filepath = os.path.join(IMAGE_FOLDER, safe_name)

    if not os.path.abspath(filepath).startswith(os.path.abspath(IMAGE_FOLDER)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(filepath, mimetype="image/png")


# ---------- Share file to chat ----------

@app.route("/share_to_chat", methods=["POST"])
def share_to_chat():
    data = request.get_json()
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "No filename"}), 400

    safe_name = secure_filename(filename)
    tmp_dir = os.path.join(os.path.dirname(__file__), "generated_codes")
    filepath = os.path.join(tmp_dir, safe_name)

    if not os.path.abspath(filepath).startswith(os.path.abspath(tmp_dir)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()

    return jsonify({
        "filename": safe_name,
        "code": code,
        "message": f"Файл `{safe_name}` готов к отправке в чат"
    })


if __name__ == "__main__":
    print("=" * 50)
    print("AI Assistant Server запущен")
    print("Frontend: http://localhost:5000")
    print("Admin:    http://localhost:5000/admin/login")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
'''

# Сохраняем файл
output_path = "/mnt/agents/output/app.py"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(app_py_fixed)

print(f"✅ Исправленный app.py сохранён: {output_path}")
print(f"Размер: {len(app_py_fixed)} символов")
print(f"Строк: {app_py_fixed.count(chr(10))}")