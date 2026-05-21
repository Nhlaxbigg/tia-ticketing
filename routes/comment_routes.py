"""Comment routes"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import get_db

comment_bp = Blueprint("comments", __name__)


@comment_bp.route("/<int:ticket_id>", methods=["POST"])
@jwt_required()
def add_comment(ticket_id):
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()

    if not body:
        return jsonify(error="Comment body is required."), 400

    db   = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    t    = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()

    if not t:
        db.close(); return jsonify(error="Ticket not found."), 404
    if user["role"] == "client" and t["created_by"] != uid:
        db.close(); return jsonify(error="Access denied."), 403

    is_internal = int(bool(data.get("is_internal"))) if user["role"] in ("admin","agent") else 0

    cur = db.execute(
        "INSERT INTO comments (ticket_id, user_id, body, is_internal) VALUES (?,?,?,?)",
        (ticket_id, uid, body, is_internal)
    )
    comment_id = cur.lastrowid

    # Update ticket updated_at
    db.execute("UPDATE tickets SET updated_at=datetime('now') WHERE id=?", (ticket_id,))

    # Notify other party
    notify_uid = t["created_by"] if uid != t["created_by"] else (t["assigned_to"] or None)
    if notify_uid and notify_uid != uid:
        db.execute(
            "INSERT INTO notifications (user_id, message, link) VALUES (?,?,?)",
            (notify_uid, f"New reply on ticket {t['ticket_no']}", f"/ticket/{ticket_id}")
        )

    db.commit()
    comment = db.execute(
        "SELECT c.*, u.name as author_name, u.role as author_role FROM comments c JOIN users u ON c.user_id=u.id WHERE c.id=?",
        (comment_id,)
    ).fetchone()
    db.close()
    return jsonify(dict(comment)), 201
