"""Job card routes — standalone onsite work records, optionally linked to a ticket."""

from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import get_db, next_job_card_no

job_card_bp = Blueprint("job_cards", __name__)

STAFF_ROLES = ("admin", "agent", "technician")


def _require_staff(cur, uid):
    cur.execute("SELECT role, name FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user or user["role"] not in STAFF_ROLES:
        return None
    return user


EDITABLE_FIELDS = (
    "customer_name", "address", "contact_name", "tel_no", "email",
    "instruction_taken_by", "job_done_by", "time_started", "time_completed",
    "instructions", "comments", "signed_by", "designation", "ticket_id",
)


@job_card_bp.route("", methods=["GET"])
@jwt_required()
def list_job_cards():
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    search    = request.args.get("q", "")
    ticket_id = request.args.get("ticket_id", "")
    page      = max(1, int(request.args.get("page", 1)))
    per_page  = 20

    q = """SELECT jc.*, t.ticket_no, u.name as created_by_name
           FROM job_cards jc
           LEFT JOIN tickets t ON jc.ticket_id = t.id
           LEFT JOIN users u ON jc.created_by = u.id
           WHERE 1=1"""
    params = []
    if search:
        q += " AND (jc.job_card_no ILIKE %s OR jc.customer_name ILIKE %s OR t.ticket_no ILIKE %s)"
        s = f"%{search}%"
        params += [s, s, s]
    if ticket_id:
        q += " AND jc.ticket_id = %s"
        params.append(ticket_id)

    cur.execute(f"SELECT COUNT(*) as c FROM ({q}) AS sub", params)
    total = cur.fetchone()["c"]
    q += " ORDER BY jc.created_at DESC LIMIT %s OFFSET %s"
    params += [per_page, (page - 1) * per_page]

    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    db.close()
    return jsonify(
        job_cards=[dict(r) for r in rows],
        total=total, page=page, per_page=per_page,
        pages=(total + per_page - 1) // per_page
    )


@job_card_bp.route("", methods=["POST"])
@jwt_required()
def create_job_card():
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    ticket_id = data.get("ticket_id") or None
    if ticket_id:
        cur.execute("SELECT id FROM tickets WHERE id=%s", (ticket_id,))
        if not cur.fetchone():
            cur.close(); db.close(); return jsonify(error="Linked ticket not found."), 400

    fields = {f: (data.get(f) or "").strip() if isinstance(data.get(f), str) else data.get(f)
              for f in EDITABLE_FIELDS}
    fields["ticket_id"] = ticket_id

    job_card_no = next_job_card_no()
    cur.execute(
        """INSERT INTO job_cards
               (job_card_no, ticket_id, customer_name, address, contact_name, tel_no, email,
                date_received, instruction_taken_by, job_done_by, time_started, time_completed,
                instructions, comments, signed_by, designation, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s, NOW(), %s,%s,%s,%s, %s,%s,%s,%s, %s)
           RETURNING id""",
        (job_card_no, fields["ticket_id"], fields["customer_name"], fields["address"],
         fields["contact_name"], fields["tel_no"], fields["email"],
         fields["instruction_taken_by"], fields["job_done_by"], fields["time_started"],
         fields["time_completed"], fields["instructions"], fields["comments"],
         fields["signed_by"], fields["designation"], uid)
    )
    job_card_id = cur.fetchone()["id"]
    db.commit()

    cur.execute(
        """SELECT jc.*, t.ticket_no, u.name as created_by_name
           FROM job_cards jc
           LEFT JOIN tickets t ON jc.ticket_id = t.id
           LEFT JOIN users u ON jc.created_by = u.id
           WHERE jc.id=%s""", (job_card_id,)
    )
    job_card = cur.fetchone()
    cur.close()
    db.close()
    return jsonify(dict(job_card)), 201


@job_card_bp.route("/<int:job_card_id>", methods=["GET"])
@jwt_required()
def get_job_card(job_card_id):
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    cur.execute(
        """SELECT jc.*, t.ticket_no, u.name as created_by_name
           FROM job_cards jc
           LEFT JOIN tickets t ON jc.ticket_id = t.id
           LEFT JOIN users u ON jc.created_by = u.id
           WHERE jc.id=%s""", (job_card_id,)
    )
    job_card = cur.fetchone()
    cur.close()
    db.close()
    if not job_card:
        return jsonify(error="Job card not found."), 404
    return jsonify(dict(job_card))


@job_card_bp.route("/<int:job_card_id>", methods=["PUT"])
@jwt_required()
def update_job_card(job_card_id):
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    db  = get_db()
    cur = db.cursor()
    if not _require_staff(cur, uid):
        cur.close(); db.close(); return jsonify(error="Access denied."), 403

    cur.execute("SELECT * FROM job_cards WHERE id=%s", (job_card_id,))
    existing = cur.fetchone()
    if not existing:
        cur.close(); db.close(); return jsonify(error="Job card not found."), 404

    if "ticket_id" in data and data["ticket_id"]:
        cur.execute("SELECT id FROM tickets WHERE id=%s", (data["ticket_id"],))
        if not cur.fetchone():
            cur.close(); db.close(); return jsonify(error="Linked ticket not found."), 400

    set_clauses, params = [], []
    for f in EDITABLE_FIELDS:
        if f in data:
            set_clauses.append(f"{f} = %s")
            params.append(data[f])

    # Signed-off fields: signed_date is set once, the first time signed_by is provided.
    if "signed_by" in data and data["signed_by"] and not existing["signed_date"]:
        set_clauses.append("signed_date = NOW()")

    if set_clauses:
        set_clauses.append("updated_at = NOW()")
        params.append(job_card_id)
        cur.execute(f"UPDATE job_cards SET {', '.join(set_clauses)} WHERE id=%s", params)
        db.commit()

    cur.execute(
        """SELECT jc.*, t.ticket_no, u.name as created_by_name
           FROM job_cards jc
           LEFT JOIN tickets t ON jc.ticket_id = t.id
           LEFT JOIN users u ON jc.created_by = u.id
           WHERE jc.id=%s""", (job_card_id,)
    )
    updated = cur.fetchone()
    cur.close()
    db.close()
    return jsonify(dict(updated))


@job_card_bp.route("/<int:job_card_id>", methods=["DELETE"])
@jwt_required()
def delete_job_card(job_card_id):
    uid = int(get_jwt_identity())
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT role FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    if not user or user["role"] != "admin":
        cur.close(); db.close(); return jsonify(error="Admins only."), 403

    cur.execute("DELETE FROM job_cards WHERE id=%s", (job_card_id,))
    db.commit()
    cur.close()
    db.close()
    return jsonify(message="Job card deleted.")
