import requests
import os
import json
from flask import Blueprint, request, jsonify, session
from app.admin_auth import admin_api_required
from app.config import ADMIN_CREDENTIALS, ADMIN_SESSION_KEY
from app.providers import PROVIDERS, current_provider, current_model, CODE_PROVIDER, CODE_MODEL_DEFAULT
from app.config import IMAGE_PROVIDER, IMAGE_SIZE_DEFAULT
from app.llm import contents, system_prompt, update_system_prompt, ensure_system_prompt
from app.plugins import plugins
from app.custom_commands import custom_commands

admin_api_bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")

@admin_api_bp.route("/login", methods=["POST"])
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

@admin_api_bp.route("/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"success": True})

@admin_api_bp.route("/check")
def admin_check():
    if session.get("admin_logged_in"):
        return jsonify({"logged_in": True, "username": session.get("admin_username"), "role": "admin" if session.get("admin_username") == "admin" else "user"})
    return jsonify({"logged_in": False})

@admin_api_bp.route("/stats")
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

@admin_api_bp.route("/settings", methods=["POST"])
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

@admin_api_bp.route("/history", methods=["GET", "DELETE"])
@admin_api_required
def admin_history():
    global contents
    if request.method == "DELETE":
        contents.clear()
        ensure_system_prompt()
        return jsonify({"success": True, "message": "История очищена"})
    return jsonify({"history": contents})

@admin_api_bp.route("/export")
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