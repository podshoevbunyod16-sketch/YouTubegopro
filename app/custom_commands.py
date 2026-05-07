import os
import json
import requests
from app.llm import contents, ensure_system_prompt, system_prompt
from app.providers import PROVIDERS, current_provider, current_model
from app.plugins import plugins

CUSTOM_COMMANDS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "custom_commands.json")
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