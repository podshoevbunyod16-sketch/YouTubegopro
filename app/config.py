import os

# Загрузка .env
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

ADMIN_SESSION_KEY = os.getenv("SESSION_SECRET", "ai-assistant-secret-key-2024")

ADMIN_CREDENTIALS = {
    "admin": os.getenv("ADMIN_CODE", "admin123"),
    "user": os.getenv("USER_CODE", "user123")
}

# Папки для генерации кода и изображений
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
IMAGE_FOLDER = os.path.join(BASE_DIR, "generated_images")
os.makedirs(IMAGE_FOLDER, exist_ok=True)

CODE_FOLDER = os.path.join(BASE_DIR, "generated_codes")
os.makedirs(CODE_FOLDER, exist_ok=True)

# Настройки изображений
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations")
IMAGE_SIZE_DEFAULT = os.getenv("IMAGE_SIZE", "1024x1024")