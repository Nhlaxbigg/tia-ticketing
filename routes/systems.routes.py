"""System/automation routes — SLA reminder job, triggered by an external scheduler."""

import os
from flask import Blueprint, request, jsonify
from database import get_db, sla_status, log_action

system_bp = Blueprint("system", __name__)

CRON_SECRET = os.environ.get("CRON_SECRET")
REMINDER_COOLDOWN_HOURS = 4  # don't re-notify the same ticket more than once per this window
OPEN_STATUSES = ("open", "in_progress", "pending")


@system_bp.route("/check-sla", methods=["POST"])
def check_sla():
    # Shared-secret auth — this endpoint has no user session, it's called by a cron trigger.
    auth = request.headers.get("Authorization", "")
    if not CRON_SECRET or auth != f"Bearer {CRON_SECRET}":
        return jsonify(error="Unauthorized."), 401

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        f"""SELECT * FROM tickets
            WHERE status IN ({','.join(['%s']*len(OPEN_STATUSES))})""",
        OPEN_STATUSES
    )
    tickets = cur.fetchall()

    notified = []
    for t in tickets:
        status = sla_status(t)
        if not (status["sla_response_breached"] or status["sla_resolution_breached"]):
            continue

        # Throttle: skip if we already reminded within the cooldown window
        if t["last_sla_reminder_at"]:
            cur.execute(
                "SELECT NOW() - %s < (%s || ' hours')::interval as recent",
                (t["last_sla_reminder_at"], REMINDER_COOLDOWN_HOURS)
            )
            if cur.fetchone()["recent"]:
                continue

        breach_kind = []
        if status["sla_response_breached"]:   breach_kind.append("first response")
        if status["sla_resolution_breached"]: breach_kind.append("resolution")
        breach_text = " and ".join(breach_kind)

        message = f"SLA breach ({breach_text}) on {t['ticket_no']}: {t['title']}"

        # Recipient: assigned technician, or every staff member if unassigned
        if t["assigned_to"]:
            recipients = [t["assigned_to"]]
        else:
            cur.execute("SELECT id FROM users WHERE role IN ('admin','agent','technician')")
            recipients = [r["id"] for r in cur.fetchall()]

        for uid in recipients:
            cur.execute(
                "INSERT INTO notifications (user_id, message, link) VALUES (%s,%s,%s)",
                (uid, message, f"/ticket/{t['id']}")
            )

        log_action(cur, t["id"], None, "sla_reminder", breach_text)
        cur.execute("UPDATE tickets SET last_sla_reminder_at = NOW() WHERE id=%s", (t["id"],))
        notified.append(t["ticket_no"])

    db.commit()
    cur.close()
    db.close()
    return jsonify(checked=len(tickets), reminders_sent=len(notified), tickets=notified)
