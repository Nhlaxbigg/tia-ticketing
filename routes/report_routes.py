"""Report routes — staff-only reporting views."""

import re
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import get_db

report_bp = Blueprint("reports", __name__)

STAFF_ROLES = ("admin", "agent", "technician")


def parse_hours_worked(text):
    """Parse hours_worked strings into decimal hours. Handles the app's own
    auto-generated format ('2 Hours 30 Minutes', '44 Minutes'), a plain
    number someone typed directly ('2.5'), and anything unparseable safely
    returns 0.0 rather than raising."""
    if not text:
        return 0.0
    text = text.strip()
    if re.match(r'^[0-9]+(\.[0-9]+)?$', text):
        return float(text)
    hours, minutes = 0.0, 0.0
    h_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*Hours?', text, re.IGNORECASE)
    m_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*Minutes?', text, re.IGNORECASE)
    if h_match:
        hours = float(h_match.group(1))
    if m_match:
        minutes = float(m_match.group(1))
    return hours + minutes / 60.0


def _require_staff(cur, uid):
    cur.execute("SELECT role FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user or user["role"] not in STAFF_ROLES:
        return None
    return user


def _date_filter_and_params(prefix_and=True):
    date_from = request.args.get("from", "")
    date_to   = request.args.get("to", "")
    clause, params = "", []
    if date_from:
        clause += " AND t.created_at >= %s"
        params.append(date_from)
    if date_to:
        clause += " AND t.created_at < (%s::date + interval '1 day')"
        params.append(date_to)
    return clause, params


@report_bp.route("/client-activity", methods=["GET"])
@jwt_required()
def client_activity():
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    date_filter, date_params = _date_filter_and_params()

    query = f"""
        SELECT c.id as client_id, c.name as client_name,
               t.id as ticket_id, t.status, t.hours_worked
        FROM clients c
        LEFT JOIN users u ON u.client_id = c.id
        LEFT JOIN tickets t ON t.created_by = u.id {date_filter}
        ORDER BY c.name
    """
    cur.execute(query, date_params)
    rows = cur.fetchall()
    cur.close()
    db.close()

    clients = {}
    order = []
    for r in rows:
        cid = r["client_id"]
        if cid not in clients:
            clients[cid] = {
                "client_id": cid, "client_name": r["client_name"],
                "ticket_count": 0, "open_count": 0, "closed_count": 0, "total_hours": 0.0,
            }
            order.append(cid)
        if r["ticket_id"] is not None:
            clients[cid]["ticket_count"] += 1
            if r["status"] in ("open", "in_progress", "pending"):
                clients[cid]["open_count"] += 1
            elif r["status"] in ("resolved", "closed"):
                clients[cid]["closed_count"] += 1
            clients[cid]["total_hours"] += parse_hours_worked(r["hours_worked"])

    results = [clients[cid] for cid in order]
    results.sort(key=lambda c: (-c["ticket_count"], c["client_name"]))

    totals = {
        "ticket_count": sum(c["ticket_count"] for c in results),
        "open_count":   sum(c["open_count"] for c in results),
        "closed_count": sum(c["closed_count"] for c in results),
        "total_hours":  sum(c["total_hours"] for c in results),
    }
    return jsonify(clients=results, totals=totals)


@report_bp.route("/client-activity/<int:client_id>/tickets", methods=["GET"])
@jwt_required()
def client_activity_tickets(client_id):
    """Full ticket list for one client, for the printable per-client report."""
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    cur.execute("SELECT id, name FROM clients WHERE id=%s", (client_id,))
    client = cur.fetchone()
    if not client:
        cur.close(); db.close(); return jsonify(error="Client not found."), 404

    date_filter, date_params = _date_filter_and_params()
    query = f"""
        SELECT t.id, t.ticket_no, t.title, t.status, t.priority, t.request_level,
               t.category, t.support_type, t.created_at, t.resolved_at, t.hours_worked,
               u1.name as creator_name, u2.name as assignee_name
        FROM tickets t
        JOIN users u1 ON t.created_by = u1.id
        LEFT JOIN users u2 ON t.assigned_to = u2.id
        WHERE u1.client_id = %s {date_filter}
        ORDER BY t.created_at DESC
    """
    cur.execute(query, [client_id] + date_params)
    rows = cur.fetchall()
    cur.close()
    db.close()

    tickets = []
    total_hours = 0.0
    for r in rows:
        t = dict(r)
        t["parsed_hours"] = round(parse_hours_worked(t["hours_worked"]), 2)
        total_hours += t["parsed_hours"]
        tickets.append(t)

    return jsonify(client_name=client["name"], tickets=tickets, total_hours=round(total_hours, 2))
