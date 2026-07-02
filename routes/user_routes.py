"""User management routes (admin only for most)"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash
from database import get_db

user_bp = Blueprint("users", __name__)


@user_bp.route("", methods=["GET"])
@jwt_required()
def list_users():
    uid  = int(get_jwt_identity())
    db   = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    if user["role"] not in ("admin", "agent", "technician"):
        db.close(); return jsonify(error="Access denied."), 403

    role   = request.args.get("role", "")
    search = request.args.get("q", "")
    q = "SELECT id,name,email,role,company,phone,created_at FROM users WHERE 1=1"
    params = []
    if role:   q += " AND role=?";                    params.append(role)
    if search: q += " AND (name LIKE ? OR email LIKE ?)"; params += [f"%{search}%", f"%{search}%"]
    q += " ORDER BY created_at DESC"
    rows = db.execute(q, params).fetchall()
    db.close()
    return jsonify(users=[dict(r) for r in rows])


@user_bp.route("/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    uid  = int(get_jwt_identity())
    db   = get_db()
    me   = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    if me["role"] not in ("admin",) and uid != user_id:
        db.close(); return jsonify(error="Access denied."), 403
    user = db.execute(
        "SELECT id,name,email,role,company,phone,created_at FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    if not user: return jsonify(error="User not found."), 404
    return jsonify(dict(user))


@user_bp.route("/<int:user_id>", methods=["PUT"])
@jwt_required()
def update_user(user_id):
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    db   = get_db()
    me   = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()

    if me["role"] not in ("admin",) and uid != user_id:
        db.close(); return jsonify(error="Access denied."), 403

    fields, params = [], []
    for f in ("name", "company", "phone"):
        if f in data:
            fields.append(f"{f}=?"); params.append(data[f])
    if "role" in data and me["role"] == "admin":
        fields.append("role=?"); params.append(data["role"])
    if "password" in data:
        if len(data["password"]) < 8:
            db.close(); return jsonify(error="Password must be ≥ 8 characters."), 400
        fields.append("password=?"); params.append(generate_password_hash(data["password"]))

    if fields:
        params.append(user_id)
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", params)
        db.commit()

    user = db.execute(
        "SELECT id,name,email,role,company,phone,created_at FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    return jsonify(dict(user))


@user_bp.route("/<int:user_id>", methods=["DELETE"])
@jwt_required()
def delete_user(user_id):
    uid  = int(get_jwt_identity())
    db   = get_db()
    me   = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    if me["role"] != "admin":
        db.close(); return jsonify(error="Admins only."), 403
    if uid == user_id:
        db.close(); return jsonify(error="Cannot delete yourself."), 400
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    db.close()
    return jsonify(message="User deleted.")


@user_bp.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    uid = int(get_jwt_identity())
    db  = get_db()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (uid,)
    ).fetchall()
    db.close()
    return jsonify(notifications=[dict(r) for r in rows])


@user_bp.route("/notifications/read", methods=["POST"])
@jwt_required()
def mark_notifications_read():
    uid = int(get_jwt_identity())
    db  = get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (uid,))
    db.commit()
    db.close()
    return jsonify(message="All marked as read.")
