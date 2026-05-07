import os
from flask import Flask

def create_app():
    from app.config import ADMIN_SESSION_KEY
    from app.routes import register_blueprints

    app = Flask(__name__)
    app.secret_key = ADMIN_SESSION_KEY

    # инициализация других модулей, которые требуют app context (не критично)
    from app import custom_commands, plugins, llm, providers
    custom_commands.load_custom_commands()
    plugins.load_plugins()
    llm.ensure_system_prompt()   # установка system prompt в начале истории

    register_blueprints(app)
    return app