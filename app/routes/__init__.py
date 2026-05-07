from flask import Blueprint, render_template

def register_blueprints(app):
    from app.routes.main import main_bp
    from app.routes.admin_api import admin_api_bp
    from app.routes.chat import chat_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_api_bp)
    app.register_blueprint(chat_bp)

    # дополнительный роут для админ-логина (простая страница)
    @app.route("/admin/login")
    def admin_login_page():
        return render_template("admin.html")