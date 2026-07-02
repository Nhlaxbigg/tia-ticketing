"""Ticket routes — CRUD + assignment + status change"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import get_db, next_ticket_no

ticket_bp = Blueprint("tickets", __name__)

CATEGORIES     = {"cloud", "network_security", "voip", "it_support", "hardware", "general"}
PRIORITIES     = {"low", "medium", "high", "critical"}
STATUSES       = {"open", "in_progress", "pending", "resolved", "closed"}
REQ_LEVELS     = {"Level 1", "Level 2", "Level 3", "Level 4"}
SUPPORT_TYPES  = {"remote", "onsite", "remote_onsite"}


def _ticket_dict(row):
    return dict(row)


@ticket_bp.route("", methods=["GET"])
@jwt_required()
def list_tickets():
    uid  = int(get_jwt_identity())
    db   = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()

    status   = request.args.get("status",   "")
    priority = request.args.get("priority", "")
    category = request.args.get("category", "")
    search   = request.args.get("q",        "")
    page     = max(1, int(request.args.get("page", 1)))
    per_page = 20

    base_q = """
        SELECT t.*, 
               u1.name as creator_name, u1.email as creator_email,
               u2.name as assignee_name
        FROM tickets t
        JOIN users u1 ON t.created_by = u1.id
        LEFT JOIN users u2 ON t.assigned_to = u2.id
        WHERE 1=1
    """
    params = []

    if user["role"] == "client":
        base_q += " AND t.created_by = ?"
        params.append(uid)
    else:
        # Internal staff roles can see the shared ticket workspace and updates
        base_q += ""

    if status   and status   in STATUSES:   base_q += " AND t.status = ?";   params.append(status)
    if priority and priority in PRIORITIES: base_q += " AND t.priority = ?"; params.append(priority)
    if category and category in CATEGORIES: base_q += " AND t.category = ?"; params.append(category)
    if search:
        base_q += " AND (t.title LIKE ? OR t.ticket_no LIKE ? OR t.description LIKE ?)"
        s = f"%{search}%"
        params += [s, s, s]

    total = db.execute(f"SELECT COUNT(*) as c FROM ({base_q})", params).fetchone()["c"]
    base_q += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]

    rows = db.execute(base_q, params).fetchall()
    db.close()
    return jsonify(
        tickets=[dict(r) for r in rows],
        total=total, page=page, per_page=per_page,
        pages=(total + per_page - 1) // per_page
    )


@ticket_bp.route("", methods=["POST"])
@jwt_required()
def create_ticket():
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    title         = (data.get("title")         or "").strip()
    description   = (data.get("description")   or "").strip()
    category      = (data.get("category")      or "general").strip().lower()
    priority      = (data.get("priority")      or "medium").strip().lower()
    request_level = (data.get("request_level") or "Level 1").strip()
    support_type  = (data.get("support_type")  or "remote").strip().lower()

    if not title or not description:
        return jsonify(error="Title and description are required."), 400
    if category      not in CATEGORIES:    category      = "general"
    if priority      not in PRIORITIES:    priority      = "medium"
    if request_level not in REQ_LEVELS:    request_level = "Level 1"
    if support_type  not in SUPPORT_TYPES: support_type  = "remote"

    ticket_no = next_ticket_no()
    db = get_db()
    cur = db.execute(
        """INSERT INTO tickets
               (ticket_no, title, description, category, priority,
                request_level, support_type, status, created_by)
           VALUES (?,?,?,?,?,?,?,'open',?)""",
        (ticket_no, title, description, category, priority,
         request_level, support_type, uid)
    )
    ticket_id = cur.lastrowid
    db.commit()

    # Notify all admins/agents/technicians
    agents = db.execute("SELECT id FROM users WHERE role IN ('admin','agent','technician')").fetchall()
    for a in agents:
        db.execute(
            "INSERT INTO notifications (user_id, message, link) VALUES (?,?,?)",
            (a["id"], f"New ticket {ticket_no}: {title}", f"/ticket/{ticket_id}")
        )
    db.commit()

    ticket = db.execute(
        """SELECT t.*, u1.name as creator_name
           FROM tickets t JOIN users u1 ON t.created_by=u1.id
           WHERE t.id=?""", (ticket_id,)
    ).fetchone()
    db.close()
    return jsonify(dict(ticket)), 201


@ticket_bp.route("/<int:ticket_id>", methods=["GET"])
@jwt_required()
def get_ticket(ticket_id):
    uid = int(get_jwt_identity())
    db  = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()

    ticket = db.execute(
        """SELECT t.*,
                  u1.name  as creator_name,  u1.email as creator_email,
                  u1.company as creator_company, u1.phone as creator_phone,
                  u2.name  as assignee_name, u2.email as assignee_email
           FROM tickets t
           JOIN users u1 ON t.created_by = u1.id
           LEFT JOIN users u2 ON t.assigned_to = u2.id
           WHERE t.id = ?""", (ticket_id,)
    ).fetchone()

    if not ticket:
        db.close(); return jsonify(error="Ticket not found."), 404
    if user["role"] == "client" and ticket["created_by"] != uid:
        db.close(); return jsonify(error="Access denied."), 403

    comments = db.execute(
        """SELECT c.*, u.name as author_name, u.role as author_role
           FROM comments c JOIN users u ON c.user_id = u.id
           WHERE c.ticket_id = ?
           ORDER BY c.created_at ASC""", (ticket_id,)
    ).fetchall()

    # Mark notifications read
    db.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=? AND link=?",
        (uid, f"/ticket/{ticket_id}")
    )
    db.commit()
    db.close()

    result = dict(ticket)
    result["comments"] = [dict(c) for c in comments
                          if not c["is_internal"] or user["role"] in ("admin","agent","technician")]
    return jsonify(result)


@ticket_bp.route("/<int:ticket_id>", methods=["PUT"])
@jwt_required()
def update_ticket(ticket_id):
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    db   = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    t    = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()

    if not t:
        db.close(); return jsonify(error="Ticket not found."), 404

    if user["role"] == "client" and t["created_by"] != uid:
        db.close(); return jsonify(error="Access denied."), 403

    fields, params = [], []

    # Clients can only update title/description on open tickets
    if user["role"] == "client":
        if t["status"] not in ("open", "pending"):
            db.close(); return jsonify(error="Cannot edit a ticket that is in progress or closed."), 403
        for f in ("title", "description"):
            if f in data:
                fields.append(f"{f} = ?"); params.append(data[f])
    else:
        for f in ("title", "description", "priority", "category",
                  "work_implemented", "start_time", "end_time",
                  "hours_worked", "invoice_no"):
            if f in data:
                fields.append(f"{f} = ?"); params.append(data[f])
        if "request_level" in data and data["request_level"] in REQ_LEVELS:
            fields.append("request_level = ?"); params.append(data["request_level"])
        if "support_type" in data and data["support_type"] in SUPPORT_TYPES:
            fields.append("support_type = ?"); params.append(data["support_type"])
        if "status" in data and data["status"] in STATUSES:
            fields.append("status = ?"); params.append(data["status"])
        if "assigned_to" in data and user["role"] in ("admin", "agent", "technician"):
            fields.append("assigned_to = ?"); params.append(data["assigned_to"])

    if fields:
        fields.append("updated_at = datetime('now')")
        params.append(ticket_id)
        db.execute(f"UPDATE tickets SET {', '.join(fields)} WHERE id=?", params)
        db.commit()

    # Notify ticket creator if status changed
    if "status" in data and t["created_by"] != uid:
        db.execute(
            "INSERT INTO notifications (user_id, message, link) VALUES (?,?,?)",
            (t["created_by"], f"Ticket {t['ticket_no']} status changed to {data['status']}", f"/ticket/{ticket_id}")
        )
        db.commit()

    # Notify new assignee if assignment changed
    if "assigned_to" in data and data["assigned_to"] and data["assigned_to"] != t["assigned_to"] and data["assigned_to"] != uid:
        db.execute(
            "INSERT INTO notifications (user_id, message, link) VALUES (?,?,?)",
            (data["assigned_to"], f"You have been assigned ticket {t['ticket_no']}", f"/ticket/{ticket_id}")
        )
        db.commit()

    updated = db.execute(
        """SELECT t.*, u1.name as creator_name, u2.name as assignee_name
           FROM tickets t JOIN users u1 ON t.created_by=u1.id
           LEFT JOIN users u2 ON t.assigned_to=u2.id
           WHERE t.id=?""", (ticket_id,)
    ).fetchone()
    db.close()
    return jsonify(dict(updated))


@ticket_bp.route("/<int:ticket_id>", methods=["DELETE"])
@jwt_required()
def delete_ticket(ticket_id):
    uid  = int(get_jwt_identity())
    db   = get_db()
    user = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    if user["role"] not in ("admin",):
        db.close(); return jsonify(error="Admins only."), 403
    db.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
    db.commit()
    db.close()
    return jsonify(message="Ticket deleted.")
