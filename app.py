import os
import sys
import json
import requests
import subprocess
from flask import Flask, request, jsonify, render_template

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
            {"id": "groq/compound", "name": "🔍 Compound (автопоиск)"},
            {"id": "groq/compound-mini", "name": "🔍 Compound Mini (быстрый)"}
        ]
    },
    "cerebras": {
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "headers": {
            "Authorization": f"Bearer {os.getenv('CEREBRAS_API_KEY')}",
            "Content-Type": "application/json"
        },
        "models": [
            {"id": "llama-3.3-70b", "name": "Llama 3.3 70B"},
            {"id": "llama-3.1-8b", "name": "Llama 3.1 8B"},
            {"id": "qwen3-32b", "name": "Qwen 3 32B"},
        ]
    }
}

current_provider = "groq"
current_model = "openai/gpt-oss-120b"

system_prompt = "Ты полезный и дружелюбный ассистент на русском языке. Отвечай кратко и по делу."
contents = []  # история сообщений
plugins = {}

# ---------- Кастомные алиасы из файла ----------
CUSTOM_COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "custom_commands.json")
custom_commands = {}

def load_custom_commands():
    global custom_commands
    if os.path.exists(CUSTOM_COMMANDS_FILE):
        try:
            with open(CUSTOM_COMMANDS_FILE, "r", encoding="utf-8") as f:
                custom_commands = json.load(f)
            print(f"Загружено {len(custom_commands)} пользовательских команд из custom_commands.json")
        except Exception as e:
            print(f"Ошибка чтения custom_commands.json: {e}")
            custom_commands = {}
    else:
        custom_commands = {}

def save_custom_commands():
    with open(CUSTOM_COMMANDS_FILE, "w", encoding="utf-8") as f:
        json.dump(custom_commands, f, ensure_ascii=False, indent=2)

load_custom_commands()

# ---------- Загрузка плагинов из папки commands/ ----------
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

app = Flask(__name__)

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

# ---------- Функция выполнения кастомной команды ----------
def exec_custom_command(cmd, args):
    """Возвращает строку ответа или None, если команда не обработана."""
    global contents  # <-- нужно, чтобы LLM‑алиас мог добавлять сообщения в историю
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
        contents.append({"role": "user", "content": rendered_prompt})
        provider = PROVIDERS[current_provider]
        payload = {
            "model": current_model,
            "messages": contents,
            "temperature": 0.7,
            "max_tokens": 6000,
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

# ---------- Маршруты ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/models_list')
def models_list():
    providers_list = []
    for provider_key, provider_data in PROVIDERS.items():
        providers_list.append({
            "provider": provider_key,
            "list": provider_data["models"]
        })
    return jsonify({
        "models": providers_list,
        "current": current_model
    })

@app.route('/switch_model')
def switch_model():
    global current_provider, current_model
    model_id = request.args.get('model_id', '')
    for provider_key, provider_data in PROVIDERS.items():
        for model in provider_data["models"]:
            if model["id"] == model_id:
                current_provider = provider_key
                current_model = model_id
                return jsonify({"success": True, "provider": provider_key, "model": model_id})
    return jsonify({"error": "Модель не найдена"}), 400

@app.route('/commands_list')
def commands_list():
    cmds = []
    for name, cc in custom_commands.items():
        cmds.append({"command": f"/{name}", "label": f"🔹 {name}"})
    if "monitor" in plugins:
        cmds.append({"command": "/monitor battery", "label": "🔋 Батарея"})
        cmds.append({"command": "/monitor memory", "label": "🧠 Память"})
    if "services" in plugins:
        cmds.append({"command": "/services weather Москва", "label": "🌤 Погода"})
        cmds.append({"command": "/services currency USD RUB", "label": "💱 Валюта"})
        cmds.append({"command": "/services wiki Linux", "label": "📚 Wiki"})
    if "snippet" in plugins:
        cmds.append({"command": "/snippet list", "label": "📁 Сниппеты"})
    if "git" in plugins:
        cmds.append({"command": "/git /sdcard/Documents", "label": "📂 GitHub"})
    if "voice" in plugins:
        cmds.append({"command": "/voice on", "label": "🔊 Озвучка вкл"})
        cmds.append({"command": "/voice off", "label": "🔇 Озвучка выкл"})
    cmds.append({"command": "/search ", "label": "🔎 Поиск в интернете"})
    cmds.extend([
        {"command": "/clear", "label": "🗑 Очистить"},
        {"command": "/save", "label": "💾 Сохранить"},
        {"command": "/load", "label": "📂 Загрузить"},
        {"command": "/history", "label": "📋 История"},
        {"command": "/help", "label": "❓ Помощь"},
        {"command": "/alias", "label": "⚙️ Мои команды"},
    ])
    return jsonify({"commands": cmds})

@app.route('/send', methods=['POST'])
def send():
    global contents
    data = request.get_json()
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Пустое сообщение'})

    contents.append({"role": "user", "content": message})
    provider = PROVIDERS[current_provider]
    payload = {
        "model": current_model,
        "messages": contents,
        "temperature": 0.7,
        "max_tokens": 6000,
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
        return jsonify({'reply': reply, 'voice_enabled': voice_enabled})
    except Exception as e:
        if contents and contents[-1]["role"] == "user":
            contents.pop()
        return jsonify({'error': str(e)})

@app.route('/command', methods=['POST'])
def handle_command():
    global contents, system_prompt   # <-- одно объявление в начале
    data = request.get_json()
    cmd_line = data.get('command', '').strip()
    if not cmd_line.startswith('/'):
        return jsonify({'error': 'Команда должна начинаться с /'})

    parts = cmd_line[1:].split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].split() if len(parts) > 1 else []

    # Кастомные команды (алиасы)
    custom_result = exec_custom_command(cmd, args)
    if custom_result is not None:
        return jsonify({'result': custom_result})

    # Управление алиасами
    if cmd == "alias":
        if not args:
            if not custom_commands:
                return jsonify({'result': "Нет пользовательских команд. Добавьте через /alias add <имя> plugin <плагин> [аргументы] или /alias add <имя> llm <промпт>."})
            info = "Ваши команды:\n"
            for name, cc in custom_commands.items():
                if cc["type"] == "plugin":
                    info += f"/{name} → плагин {cc['plugin']} {cc.get('args_template', [])}\n"
                else:
                    info += f"/{name} → свой промпт\n"
            return jsonify({'result': info})
        subcmd = args[0].lower()
        if subcmd == "add":
            if len(args) < 3:
                return jsonify({'error': 'Формат: /alias add <имя> plugin <имя_плагина> [аргументы через пробел] или /alias add <имя> llm <промпт> (промпт можно в кавычках)'})
            name = args[1]
            type_ = args[2].lower()
            if type_ not in ("plugin", "llm"):
                return jsonify({'error': 'Тип должен быть plugin или llm'})
            if type_ == "plugin":
                if len(args) < 4:
                    return jsonify({'error': 'Укажите имя плагина после plugin'})
                plugin_name = args[3]
                preset_args = args[4:] if len(args) > 4 else []
                custom_commands[name] = {"type": "plugin", "plugin": plugin_name, "args_template": preset_args}
            else:  # llm
                prompt = " ".join(args[3:]) if len(args) > 3 else "{query}"
                custom_commands[name] = {"type": "llm", "prompt": prompt}
            save_custom_commands()
            return jsonify({'result': f"Команда /{name} добавлена. Перезагрузите страницу для обновления меню."})
        elif subcmd == "remove":
            if len(args) < 2:
                return jsonify({'error': 'Укажите имя команды для удаления'})
            name = args[1]
            if name in custom_commands:
                del custom_commands[name]
                save_custom_commands()
                return jsonify({'result': f"Команда /{name} удалена."})
            else:
                return jsonify({'error': f"Команда /{name} не найдена."})
        else:
            return jsonify({'error': 'Используйте: /alias [add|remove] <имя> ...'})

    # Плагины из папки commands
    if cmd in plugins:
        try:
            result = plugins[cmd](args)
            return jsonify({'result': result if result else "OK"})
        except Exception as e:
            return jsonify({'error': str(e)})

    # Встроенные команды
    if cmd == "help":
        return jsonify({'result': "⚡ Используйте меню Функции или пишите запросы. /alias для своих команд."})
    elif cmd == "clear":
        contents.clear()
        return jsonify({'result': "История очищена."})
    elif cmd == "history":
        if not contents:
            return jsonify({'result': "История пуста."})
        hist = "\n\n".join([f"**{msg['role']}**: {msg['content']}" for msg in contents])
        return jsonify({'result': hist})
    elif cmd == "save":
        filename = args[0] if args else "chat_history.json"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(contents, f, ensure_ascii=False, indent=2)
            return jsonify({'result': f"Сохранено в {filename}"})
        except Exception as e:
            return jsonify({'error': str(e)})
    elif cmd == "load":
        filename = args[0] if args else "chat_history.json"
        if not os.path.exists(filename):
            return jsonify({'error': "Файл не найден"})
        try:
            with open(filename, "r", encoding="utf-8") as f:
                contents = json.load(f)
            return jsonify({'result': f"Загружено из {filename}"})
        except Exception as e:
            return jsonify({'error': str(e)})
    elif cmd == "prompt":
        if args:
            system_prompt = " ".join(args)
            return jsonify({'result': "Промпт обновлён."})
        else:
            return jsonify({'result': f"Текущий: {system_prompt}"})
    elif cmd == "system":
        command = " ".join(args)
        if not command:
            return jsonify({'error': "Укажите команду"})
        try:
            res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            return jsonify({'result': res.stdout + res.stderr})
        except subprocess.TimeoutExpired:
            return jsonify({'error': "Превышено время"})
        except Exception as e:
            return jsonify({'error': str(e)})
    elif cmd == "voice":
        if not args:
            return jsonify({'error': "Используйте /voice on/off"})
        subcmd = args[0].lower()
        if subcmd == "on":
            os.environ["ASSISTANT_VOICE_REPLY"] = "1"
            return jsonify({'result': "Озвучка включена"})
        elif subcmd == "off":
            os.environ["ASSISTANT_VOICE_REPLY"] = "0"
            return jsonify({'result': "Озвучка отключена"})
        else:
            return jsonify({'error': "Неизвестная подкоманда"})
    elif cmd == "search":
        search_query = " ".join(args)
        if not search_query:
            return jsonify({'error': 'Укажите запрос'})
        search_context = search_web(search_query)
        if search_context:
            contents.append({"role": "system", "content": f"Контекст из интернета:\n{search_context}"})
            contents.append({"role": "user", "content": f"Ответь на вопрос, используя контекст: {search_query}"})
        else:
            contents.append({"role": "user", "content": search_query})
        provider = PROVIDERS[current_provider]
        payload = {"model": current_model, "messages": contents, "temperature": 0.7, "max_tokens": 6000}
        try:
            resp = requests.post(provider["url"], json=payload, headers=provider["headers"])
            resp.raise_for_status()
            data_resp = resp.json()
            reply = data_resp["choices"][0]["message"]["content"]
            contents.append({"role": "assistant", "content": reply})
            if len(contents) > 20:
                contents = contents[-20:]
            return jsonify({'result': reply, 'voice_enabled': os.environ.get("ASSISTANT_VOICE_REPLY", "0") == "1"})
        except Exception as e:
            if contents and contents[-1]["role"] == "user":
                contents.pop()
            if contents and contents[-1]["role"] == "system":
                contents.pop()
            return jsonify({'error': str(e)})
    else:
        return jsonify({'error': f"Неизвестная команда: /{cmd}"})

if __name__ == "__main__":
    print("=" * 40)
    print("Ассистент с пользовательскими командами запущен")
    print("Откройте http://localhost:5000")
    print("=" * 40)
    app.run(host='0.0.0.0', port=5000, debug=False)