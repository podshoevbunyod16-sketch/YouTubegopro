import os
import requests
import base64
import json

def run(args):
    if not args:
        return "Использование: /analyze <путь/к/файлу> или /analyze <URL>"

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Ошибка: GEMINI_API_KEY не найден в .env"

    source = args[0]
    try:
        # Определяем, URL это или локальный файл
        if source.startswith("http://") or source.startswith("https://"):
            # Скачиваем изображение
            img_resp = requests.get(source)
            img_resp.raise_for_status()
            image_data = img_resp.content
        else:
            # Локальный файл
            path = os.path.expanduser(source)
            if not os.path.exists(path):
                return f"Файл не найден: {path}"
            with open(path, "rb") as f:
                image_data = f.read()

        # Кодируем в base64
        b64_image = base64.b64encode(image_data).decode("utf-8")

        # Формируем запрос к Gemini Vision
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Опиши это изображение максимально подробно: что на нём, какие объекты, цвета, настроение, возможный контекст."},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1000}
        }

        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        description = data["candidates"][0]["content"]["parts"][0]["text"]
        return description
    except Exception as e:
        return f"Ошибка анализа: {e}"