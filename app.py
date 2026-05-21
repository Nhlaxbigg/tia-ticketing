"""
TIA-Solutions Ticketing System — Main Flask Application
"""

import os
import secrets
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from database import init_db
from routes.auth_routes import auth_bp
from routes.ticket_routes import ticket_bp
from routes.user_routes import user_bp
from routes.comment_routes import comment_bp
from routes.dashboard_routes import dashboard_bp

BASE_DIR = os.path.dirname(__file__)

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    template_folder=os.path.join(BASE_DIR, "templates"),
)

# ── Configuration ──────────────────────────────────────────────────────────────
# In production set JWT_SECRET env var to a strong random string
_default_secret = os.path.join(BASE_DIR, ".secret_key")
if not os.path.exists(_default_secret):
    with open(_default_secret, "w") as f:
        f.write(secrets.token_hex(48))
with open(_default_secret) as f:
    _file_secret = f.read().strip()

app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", _file_secret)
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 86400  # 24 hours
app.config["PROPAGATE_EXCEPTIONS"] = True

CORS(app, resources={r"/api/*": {"origins": "*"}})
jwt = JWTManager(app)

# ── Blueprints ─────────────────────────────────────────────────────────────────
app.register_blueprint(auth_bp,      url_prefix="/api/auth")
app.register_blueprint(ticket_bp,    url_prefix="/api/tickets")
app.register_blueprint(user_bp,      url_prefix="/api/users")
app.register_blueprint(comment_bp,   url_prefix="/api/comments")
app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")


# ── Serve SPA ──────────────────────────────────────────────────────────────────
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path):
    static_file = os.path.join(BASE_DIR, "static", path)
    if path and os.path.exists(static_file):
        return send_from_directory(os.path.join(BASE_DIR, "static"), path)
    return send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")


# ── Initialise DB on startup (works for both gunicorn and dev server) ──────────
with app.app_context():
    init_db()


if __name__ == "__main__":
    init_db()
    print("✅  TIA Ticketing System started at http://localhost:8080")
    print("   Default admin  → admin@tia-solutions.co.za / Admin@1234")
    print("   Default agent  → agent@tia-solutions.co.za / Agent@1234")
    app.run(debug=True, port=8080)
