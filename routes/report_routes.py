"""Report routes — staff-only reporting views."""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import get_db

report_bp = Blueprint("reports", __name__)

STAFF_ROLES = ("admin", "agent", "technician")

# Matches a plain non-negative number, optionally with a decimal — anything
# else in hours_worked (blank, "n/a", "approx 2h", etc.) is treated as 0
# rather than causing a cast error.
NUMERIC_PATTERN = r'^[0-9]+(\.[0-9]+)?$'


def _require_staff(cur, uid):
    cur.execute("SELECT role FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user or user["role"] not in STAFF_ROLES:
        return None
    return user


@report_bp.route("/client-activity", methods=["GET"])
@jwt_required()
def client_activity():
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    date_from = request.args.get("from", "")
    date_to   = request.args.get("to", "")

    date_filter = ""
    params = [NUMERIC_PATTERN]
    if date_from:
        date_filter += " AND t.created_at >= %s"
        params.append(date_from)
    if date_to:
        date_filter += " AND t.created_at < (%s::date + interval '1 day')"
        params.append(date_to)

    query = f"""
        SELECT
            c.id   AS client_id,
            c.name AS client_name,
            COUNT(t.id) AS ticket_count,
            COUNT(*) FILTER (WHERE t.status IN ('open','in_progress','pending')) AS open_count,
            COUNT(*) FILTER (WHERE t.status IN ('resolved','closed')) AS closed_count,
            COALESCE(SUM(
                CASE WHEN t.hours_worked ~ %s THEN t.hours_worked::numeric ELSE 0 END
            ), 0) AS total_hours
        FROM clients c
        LEFT JOIN users u ON u.client_id = c.id
        LEFT JOIN tickets t ON t.created_by = u.id {date_filter}
        GROUP BY c.id, c.name
        ORDER BY ticket_count DESC, c.name ASC
    """
    cur.execute(query, params)
    rows = cur.fetchall()

    results = [dict(r) for r in rows]
    for r in results:
        r["total_hours"] = float(r["total_hours"])

    totals = {
        "ticket_count": sum(r["ticket_count"] for r in results),
        "open_count":   sum(r["open_count"] for r in results),
        "closed_count": sum(r["closed_count"] for r in results),
        "total_hours":  sum(r["total_hours"] for r in results),
    }

    cur.close()
    db.close()
    return jsonify(clients=results, totals=totals)
