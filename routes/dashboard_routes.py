"""Dashboard statistics"""

from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import get_db
from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("", methods=["GET"])
@jwt_required()
def stats():
    uid = int(get_jwt_identity())
    db  = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()

    base = "SELECT * FROM tickets"
    if user["role"] == "client":
        rows = db.execute(base + " WHERE created_by=?", (uid,)).fetchall()
    elif user["role"] == "agent":
        rows = db.execute(base + " WHERE assigned_to=? OR status='open'", (uid,)).fetchall()
    else:
        rows = db.execute(base).fetchall()

    tickets = [dict(r) for r in rows]

    by_status   = {}
    by_priority = {}
    by_category = {}
    for t in tickets:
        by_status[t["status"]]     = by_status.get(t["status"],    0) + 1
        by_priority[t["priority"]] = by_priority.get(t["priority"],0) + 1
        by_category[t["category"]] = by_category.get(t["category"],0) + 1

    # Recent 5 tickets
    recent = db.execute(
        """SELECT t.id, t.ticket_no, t.title, t.status, t.priority, t.created_at,
                  u.name as creator_name
           FROM tickets t JOIN users u ON t.created_by=u.id
           {}
           ORDER BY t.created_at DESC LIMIT 5""".format(
               "WHERE t.created_by=?" if user["role"] == "client"
               else "WHERE t.assigned_to=? OR t.status='open'" if user["role"] == "agent"
               else ""
           ),
        (uid,) if user["role"] in ("client","agent") else ()
    ).fetchall()

    total_users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"] if user["role"] == "admin" else None

    db.close()
    return jsonify(
        total=len(tickets),
        by_status=by_status,
        by_priority=by_priority,
        by_category=by_category,
        recent=[dict(r) for r in recent],
        total_users=total_users,
    )
