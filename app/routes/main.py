import os
from flask import Blueprint, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from app.config import IMAGE_FOLDER, CODE_FOLDER

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def index():
    return render_template("index.html")

@main_bp.route("/admin")
def admin_dashboard():
    # декоратор admin_required уже не используется, перенаправление на логин
    # здесь просто рендерим шаблон (админ-панель сама проверит сессию через API)
    return render_template("admin.html")

@main_bp.route("/download")
def download_file():
    filename = request.args.get("file", "")
    if not filename:
        return jsonify({"error": "No filename"}), 400

    safe_name = secure_filename(filename)
    filepath = os.path.join(CODE_FOLDER, safe_name)

    if not os.path.abspath(filepath).startswith(os.path.abspath(CODE_FOLDER)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(filepath, as_attachment=True, download_name=safe_name)

@main_bp.route("/download_image")
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

@main_bp.route("/image_view")
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

@main_bp.route("/share_to_chat", methods=["POST"])
def share_to_chat():
    data = request.get_json()
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "No filename"}), 400

    safe_name = secure_filename(filename)
    filepath = os.path.join(CODE_FOLDER, safe_name)

    if not os.path.abspath(filepath).startswith(os.path.abspath(CODE_FOLDER)):
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