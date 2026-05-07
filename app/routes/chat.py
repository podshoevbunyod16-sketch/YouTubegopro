import requests 
import os
import json
import subprocess
from datetime import datetime
from flask import Blueprint, request, jsonify
from app.providers import PROVIDERS, current_provider, current_model, CODE_PROVIDER, CODE_MODEL_DEFAULT
from app.llm import contents, system_prompt, update_system_prompt, ensure_system_prompt, ask_llm
from app.plugins import plugins
from app.custom_commands import exec_custom_command, save_custom_commands, custom_commands
from app.search import search_web
from app.image_gen import generate_image
from app.lang_detect import detect_language
from app.config import CODE_FOLDER

chat_bp = Blueprint("chat", __name__)

@chat_bp.route("/models_list")
def models_list():
    providers_list = []
    for provider_key, provider_data in PROVIDERS.items():
        providers_list.append({
            "provider": provider_key,
            "list": provider_data["models"]
        })
    return jsonify({"models": providers_list, "current": current_model})

@chat_bp.route("/switch_model")
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

@chat_bp.route("/commands_list")
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

@chat_bp.route("/send", methods=["POST"])
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

@chat_bp.route("/command", methods=["POST"])
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
                loaded = json.load(f)
                global contents
                contents = loaded
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

        ext, lang_name = detect_language(query)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"generated_{timestamp}{ext}"
        filepath = os.path.join(CODE_FOLDER, filename)
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