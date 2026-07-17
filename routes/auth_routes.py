"""Auth routes — register, login, me"""

from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from database import get_db

auth_bp = Blueprint("auth", __name__)

VALID_ROLES = {"client", "agent", "admin", "technician"}


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name    = (data.get("name")    or "").strip()
    email   = (data.get("email")   or "").strip().lower()
    password= (data.get("password")or "").strip()
    company = (data.get("company") or "").strip()
    phone   = (data.get("phone")   or "").strip()
    role    = (data.get("role")    or "client").strip().lower()

    if not name or not email or not password:
        return jsonify(error="Name, email and password are required."), 400
    if role not in VALID_ROLES:
        role = "client"
    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters."), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO users (name, email, password, role, company, phone) VALUES (%s,%s,%s,%s,%s,%s)",
            (name, email, generate_password_hash(password), role, company, phone),
        )
        db.commit()
    except Exception:
        db.rollback()
        return jsonify(error="Email already registered."), 409
    finally:
        cur.close()
        db.close()

    return jsonify(message="Account created. Please log in."), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify(error="Email and password required."), 400

    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    cur.close()
    db.close()

    if not user or not check_password_hash(user["password"], password):
        return jsonify(error="Invalid credentials."), 401

    token = create_access_token(identity=str(user["id"]))
    return jsonify(
        token=token,
        user=dict(id=user["id"], name=user["name"],
                  email=user["email"], role=user["role"],
                  company=user["company"])
    )


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id,name,email,role,company,phone,created_at FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    cur.close()
    db.close()
    if not user:
        return jsonify(error="User not found."), 404
    return jsonify(dict(user))
