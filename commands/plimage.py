import os
import requests
import datetime
from io import BytesIO

IMAGES_DIR = os.path.expanduser("/storage/emulated/0/DCIM/генератор_изображений")
CHAT_API_URL = "https://ai-maker-b5v5.onrender.com/api/messages"  # Уточните endpoint

def run(args):
    if not args:
        return "Использование: /image <описание>"

    prompt = " ".join(args)
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024&nologo=true"

    try:
        # Скачиваем изображение в память
        resp = requests.get(url)
        resp.raise_for_status()

        # Создаём папку локально
        os.makedirs(IMAGES_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"img_{timestamp}.jpg"
        filepath = os.path.join(IMAGES_DIR, filename)

        # Сохраняем локально
        with open(filepath, "wb") as f:
            f.write(resp.content)

        # Отправляем изображение в чат
        chat_response = requests.post(
            CHAT_API_URL,
            files={
                "image": (filename, BytesIO(resp.content), "image/jpeg")
            },
            data={
                "prompt": prompt,
                "message": f"Сгенерировано изображение по запросу: {prompt}"
            }
        )
        
        if chat_response.status_code == 200:
            return f"Изображение сохранено локально и отправлено в чат: {filepath}"
        else:
            return f"Изображение сохранено локально, но ошибка отправки в чат: {chat_response.status_code}"
            
    except Exception as e:
        return f"Ошибка: {e}"