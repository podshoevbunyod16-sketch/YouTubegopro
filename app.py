from app import create_app

app = create_app()

if __name__ == "__main__":
    print("=" * 50)
    print("AI Assistant Server запущен")
    print("Frontend: http://localhost:5000")
    print("Admin:    http://localhost:5000/admin/login")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)