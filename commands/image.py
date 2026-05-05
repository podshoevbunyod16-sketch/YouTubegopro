import os
import requests
import datetime

IMAGES_DIR = os.path.expanduser("/storage/emulated/0/DCIM/генератор_изображений")

def run(args):
    if not args:
        return "Использование: /image <описание>"

    prompt = " ".join(args)
    # Формируем URL для генерации (Pollinations.ai)
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=1024&height=1024&nologo=true"

    try:
        # Скачиваем изображение
        resp = requests.get(url)
        resp.raise_for_status()

        # Создаём папку, если её нет
        os.makedirs(IMAGES_DIR, exist_ok=True)

        # Генерируем имя файла с временной меткой
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"img_{timestamp}.jpg"
        filepath = os.path.join(IMAGES_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(resp.content)

        return f"Изображение сохранено: {filepath}"
    except Exception as e:
        return f"Ошибка при генерации: {e}"